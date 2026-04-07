import json
import time
import random
import datetime
import pandas as pd
import numpy as np
import os
from common.paths import data_path

# Configuration
DATA_FILE = str(data_path("index_sniper_data.json"))
SYMBOL = "IF888" # Simulation of Index Futures
NAME = "Index Futures Main"

def generate_mock_5min_data(n=200):
    """Generates mock 5-minute bar data."""
    dates = pd.date_range(end=datetime.datetime.now(), periods=n, freq="5min")
    
    # Random walk with drift
    base_price = 3500.0
    prices = [base_price]
    highs = [base_price]
    lows = [base_price]
    opens = [base_price]
    
    volatility = 0.002 # 0.2% per 5 min
    
    for i in range(1, n):
        prev_close = prices[-1]
        change = np.random.normal(0, volatility)
        
        # Add some trend components
        if i > 150: # Recent uptrend
            change += 0.0005
            
        curr_close = prev_close * (1 + change)
        curr_open = prev_close
        curr_high = max(curr_open, curr_close) * (1 + abs(np.random.normal(0, volatility/2)))
        curr_low = min(curr_open, curr_close) * (1 - abs(np.random.normal(0, volatility/2)))
        
        prices.append(curr_close)
        opens.append(curr_open)
        highs.append(curr_high)
        lows.append(curr_low)
        
    df = pd.DataFrame({
        "time": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices
    })
    return df

def calculate_indicators(df):
    # WR: -100 * (HHV(H,32) - C) / (HHV(H,32) - LLV(L,32)) + 50
    # Range: +50 (High) to -50 (Low)
    period = 32
    df['hhv'] = df['high'].rolling(window=period).max()
    df['llv'] = df['low'].rolling(window=period).min()
    
    # Avoid division by zero
    df['range'] = df['hhv'] - df['llv']
    df['range'] = df['range'].replace(0, 0.01)
    
    df['wr'] = -100 * (df['hhv'] - df['close']) / df['range'] + 50
    
    # RSI 12
    rsi_period = 12
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    return df

def run_strategy(df):
    # State variables for simulation
    position = 0 # 0: Flat, 1: Long, -1: Short
    entry_price = 0.0
    highest_price_since_entry = 0.0
    lowest_price_since_entry = 0.0
    
    # Simulate strictly based on user logic row by row
    # To keep it simple for the snapshot, we'll just check the LATEST signal
    # But to show "Status", we need to know if we are currently holding
    
    # Let's run a quick backtest loop on the last 50 bars to determine current state
    signals = []
    
    last_buy_index = -999
    last_sell_index = -999
    
    # Parameters
    STOP_LOSS_PCT_L = 0.008 # 0.992
    STOP_LOSS_PCT_S = 0.008 # 1.008
    TRAILING_STOP_PCT = 0.01 # 1%
    
    cooldown = 54
    
    status = "FLAT"
    pnl = 0.0
    
    for i in range(len(df) - 100, len(df)):
        if i < 32: continue
        
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        
        # Conditions
        # WR Cross 45: Current WR > 45 and Prev WR <= 45 (approx)
        wr_cross_up_45 = (row['wr'] > 45) and (prev_row['wr'] <= 45)
        wr_cross_down_neg45 = (row['wr'] < -45) and (prev_row['wr'] >= -45)
        
        # Ref WR > 45 in last 9 (excluding current)
        # Simple approximation for this script
        past_9_wr = df['wr'].iloc[i-9:i]
        wr_cond_long = (past_9_wr > 45).any()
        wr_cond_short = (past_9_wr < -45).any()
        
        # Time filter (ignored for mock data, assumed always open)
        
        # Entry Logic
        if position == 0:
            # Long Entry
            if (row['rsi'] > 65 and 
                wr_cross_up_45 and 
                wr_cond_long and 
                (i - last_buy_index > cooldown)):
                
                position = 1
                entry_price = row['close']
                highest_price_since_entry = row['close']
                last_buy_index = i
                status = "LONG"
                signals.append({"time": str(row['time']), "action": "BUY", "price": row['close'], "reason": "RSI+WR Breakout"})
                
            # Short Entry
            elif (row['rsi'] < 35 and 
                  wr_cross_down_neg45 and 
                  wr_cond_short and 
                  (i - last_sell_index > cooldown)):
                  
                position = -1
                entry_price = row['close']
                lowest_price_since_entry = row['close']
                last_sell_index = i
                status = "SHORT"
                signals.append({"time": str(row['time']), "action": "SELL", "price": row['close'], "reason": "RSI+WR Breakdown"})

        # Exit Logic
        elif position == 1: # Long
            highest_price_since_entry = max(highest_price_since_entry, row['high'])
            
            # Stop Loss: C <= BKPRICE * 0.992
            sl_hit = row['close'] <= entry_price * (1 - STOP_LOSS_PCT_L)
            # Trailing Stop: C <= BKHIGH * 0.99
            ts_hit = row['close'] <= highest_price_since_entry * (1 - TRAILING_STOP_PCT)
            
            if sl_hit or ts_hit:
                position = 0
                status = "FLAT"
                reason = "Stop Loss" if sl_hit else "Trailing Stop"
                signals.append({"time": str(row['time']), "action": "CLOSE_LONG", "price": row['close'], "reason": reason})

        elif position == -1: # Short
            lowest_price_since_entry = min(lowest_price_since_entry, row['low'])
            
            # Stop Loss: C >= SKPRICE * 1.008
            sl_hit = row['close'] >= entry_price * (1 + STOP_LOSS_PCT_S)
            # Trailing Stop: C >= SKLOW * 1.01
            ts_hit = row['close'] >= lowest_price_since_entry * (1 + TRAILING_STOP_PCT)
            
            if sl_hit or ts_hit:
                position = 0
                status = "FLAT"
                reason = "Stop Loss" if sl_hit else "Trailing Stop"
                signals.append({"time": str(row['time']), "action": "CLOSE_SHORT", "price": row['close'], "reason": reason})
    
    return {
        "status": status,
        "position": position,
        "entry_price": entry_price,
        "current_price": df.iloc[-1]['close'],
        "current_rsi": df.iloc[-1]['rsi'],
        "current_wr": df.iloc[-1]['wr'],
        "recent_signals": signals[-5:] if signals else []
    }

def main():
    print(f"[{datetime.datetime.now()}] Starting IndexSniper Engine...")
    
    # 1. Generate Data
    df = generate_mock_5min_data(300)
    
    # 2. Calculate Indicators
    df = calculate_indicators(df)
    
    # 3. Run Strategy
    result = run_strategy(df)
    
    # 4. Save Data
    output = {
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": SYMBOL,
        "name": NAME,
        "market_status": "OPEN",
        "strategy": {
            "status": result['status'],
            "position_size": "1 Lot" if result['position'] != 0 else "0",
            "entry_price": round(result['entry_price'], 2) if result['position'] != 0 else 0,
            "current_price": round(result['current_price'], 2),
            "pnl_pct": round((result['current_price'] - result['entry_price'])/result['entry_price']*100, 2) if result['position'] == 1 else (round((result['entry_price'] - result['current_price'])/result['entry_price']*100, 2) if result['position'] == -1 else 0),
            "indicators": {
                "rsi": round(result['current_rsi'], 2),
                "wr": round(result['current_wr'], 2)
            }
        },
        "recent_signals": result['recent_signals'],
        "chart_data": {
            "times": df['time'].tail(50).dt.strftime("%H:%M").tolist(),
            "prices": df['close'].tail(50).round(2).tolist(),
            "wr": df['wr'].tail(50).round(2).tolist()
        }
    }
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)
        
    print(f"IndexSniper data saved to {DATA_FILE}")

if __name__ == "__main__":
    main()
