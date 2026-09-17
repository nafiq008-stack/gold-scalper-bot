
Engine check · PY
"""
Runs once per invocation (called every 5 min by GitHub Actions).
Reads state.json for memory of pending sweeps, checks the latest live
candle for a signal, appends to signals_log.csv if one fires, and
saves updated state.json for the next run.
"""
import os
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
 
TWELVE_DATA_API_KEY = os.environ["90208414ac244d9ab0a6ff233885c6f0"]
 
SYMBOL = "XAU/USD"
INTERVAL = "5min"
OUTPUTSIZE = 60
 
RR = 1.3
CONFIRM_WINDOW = 12   # candles
LOOKBACK = 10         # candles
STOP_BUFFER = 0.3
SPREAD = 0.35
 
STATE_FILE = "state.json"
LOG_FILE = "signals_log.csv"
 
 
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"enabled": False, "pending_sweeps": [], "last_processed_ts": None}
    with open(STATE_FILE) as f:
        return json.load(f)
 
 
def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
 
 
def fetch_candles():
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": SYMBOL, "interval": INTERVAL, "outputsize": OUTPUTSIZE, "apikey": TWELVE_DATA_API_KEY}
    data = None
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=45)
            data = r.json()
            break
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt+1} failed: {e}")
            if attempt == 2:
                return None
    if "values" not in data:
        print(f"API error: {data}")
        return None
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    return df.sort_values("datetime").reset_index(drop=True)[["datetime", "open", "high", "low", "close"]]
 
 
def find_fvg_at(df, i):
    if i < 2:
        return None, None
    bull = None
    bear = None
    if df["high"].iloc[i - 2] < df["low"].iloc[i]:
        bull = (df["high"].iloc[i - 2], df["low"].iloc[i])
    if df["low"].iloc[i - 2] > df["high"].iloc[i]:
        bear = (df["high"].iloc[i], df["low"].iloc[i - 2])
    return bull, bear
 
 
def check_for_sweep(df, i):
    if i < LOOKBACK:
        return None
    level_high = df["high"].iloc[i - LOOKBACK:i].max()
    level_low = df["low"].iloc[i - LOOKBACK:i].min()
    c = df.iloc[i]
    if c["high"] > level_high and c["close"] < level_high:
        return {"direction": "short", "extreme": float(c["high"])}
    elif c["low"] < level_low and c["close"] > level_low:
        return {"direction": "long", "extreme": float(c["low"])}
    return None
 
 
def log_signal(ts, direction, entry, stop, target, enabled):
    header_needed = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a") as f:
        if header_needed:
            f.write("timestamp,direction,entry,stop,target,bot_enabled\n")
        f.write(f"{ts},{direction},{entry:.2f},{stop:.2f},{target:.2f},{enabled}\n")
 
 
def main():
    state = load_state()
    df = fetch_candles()
    if df is None or len(df) < LOOKBACK + 3:
        print("Not enough data this run, skipping.")
        return
 
    latest_ts = df["datetime"].iloc[-1]
    latest_ts_str = str(latest_ts)
 
    if state.get("last_processed_ts") == latest_ts_str:
        print("No new candle since last run. Nothing to do.")
        return
 
    i = len(df) - 1
 
    # 1. check for a new sweep
    sweep = check_for_sweep(df, i)
    pending = state.get("pending_sweeps", [])
    if sweep:
        expire_time = latest_ts + timedelta(minutes=5 * CONFIRM_WINDOW)
        pending.append({
            "direction": sweep["direction"],
            "extreme": sweep["extreme"],
            "expire_time": str(expire_time),
        })
        print(f"Sweep detected: {sweep['direction']} at {sweep['extreme']:.2f}")
 
    # 2. check pending sweeps for FVG confirmation on this candle
    bull_fvg, bear_fvg = find_fvg_at(df, i)
    still_pending = []
    for p in pending:
        fired = False
        expire_time = pd.to_datetime(p["expire_time"])
        if latest_ts <= expire_time:
            if p["direction"] == "long" and bull_fvg is not None:
                gap_low, gap_high = bull_fvg
                entry = gap_high - SPREAD / 2
                stop = min(p["extreme"], gap_low) - STOP_BUFFER
                risk = entry - stop
                if risk > 0:
                    target = entry + risk * RR
                    log_signal(latest_ts_str, "long", entry, stop, target, state.get("enabled", False))
                    fired = True
            elif p["direction"] == "short" and bear_fvg is not None:
                gap_low, gap_high = bear_fvg
                entry = gap_low + SPREAD / 2
                stop = max(p["extreme"], gap_high) + STOP_BUFFER
                risk = stop - entry
                if risk > 0:
                    target = entry - risk * RR
                    log_signal(latest_ts_str, "short", entry, stop, target, state.get("enabled", False))
                    fired = True
        if not fired and latest_ts < expire_time:
            still_pending.append(p)
 
    state["pending_sweeps"] = still_pending
    state["last_processed_ts"] = latest_ts_str
    save_state(state)
    print("Run complete.")
 
 
if __name__ == "__main__":
    main()
 
