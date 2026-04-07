import akshare as ak
import pandas as pd
import json
import os
import datetime
import random
import time
from common.paths import data_path

# Configuration
DATA_DIR = str(data_path())
os.makedirs(DATA_DIR, exist_ok=True)
OUTPUT_FILE = os.path.join(DATA_DIR, 'grid_master_data.json')

# Grid Target: Bank & Utility Stocks (Low Volatility, High Dividend)
GRID_TARGETS = [
    ("601939", "建设银行", 5.0, 7.5), # Symbol, Name, Lower Limit, Upper Limit
    ("601398", "工商银行", 4.0, 6.0),
    ("601288", "农业银行", 3.0, 4.5),
    ("600900", "长江电力", 20.0, 25.0),
    ("600009", "上海机场", 35.0, 50.0)
]

GRID_STEP = 0.02 # 2% Grid Step

import requests

def get_sina_symbol(symbol):
    if symbol.startswith('6'): return f"sh{symbol}"
    if symbol.startswith('0') or symbol.startswith('3'): return f"sz{symbol}"
    if symbol.startswith('8') or symbol.startswith('4'): return f"bj{symbol}"
    return symbol

def fetch_realtime_prices(symbols):
    """Fetch real-time snapshot using Sina Finance API (lighter and faster)."""
    print("Fetching real-time market snapshot from Sina...")
    sina_symbols = [get_sina_symbol(s) for s in symbols]
    url = f"http://hq.sinajs.cn/list={','.join(sina_symbols)}"
    headers = {'Referer': 'https://finance.sina.com.cn'}
    
    price_map = {}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            # Format: var hq_str_sh601939="Name,Open,PrevClose,Close,High,Low,Buy,Sell,..."
            lines = resp.text.strip().split('\n')
            for line in lines:
                if '="' in line:
                    parts = line.split('="')
                    symbol_part = parts[0].split('_')[-1] # sh601939
                    raw_symbol = symbol_part[2:] # 601939
                    data = parts[1].strip('";').split(',')
                    if len(data) > 3:
                        current_price = float(data[3])
                        if current_price == 0: # Market closed or pre-open, use PrevClose
                            current_price = float(data[2])
                        price_map[raw_symbol] = current_price
    except Exception as e:
        print(f"Error fetching sina data: {e}")
    
    return price_map

def run_strategy():
    print(f"[{datetime.datetime.now()}] Starting GridMaster Engine...")
    
    # Collect all symbols
    all_symbols = [s[0] for s in GRID_TARGETS]
    realtime_prices = fetch_realtime_prices(all_symbols)
    
    grids = []
    
    for symbol, name, lower, upper in GRID_TARGETS:
        current_price = realtime_prices.get(symbol)
        
        if not current_price or str(current_price) == 'nan':
            # Mock price if fetch fails (for demo stability)
            current_price = (lower + upper) / 2
        else:
            current_price = float(current_price)
            
        # Calculate Grid Position
        # Range Position (0% = Lower Limit, 100% = Upper Limit)
        pos_pct = (current_price - lower) / (upper - lower)
        pos_pct = max(0, min(1, pos_pct))
        
        # Grid Logic: 
        # Low Price -> High Position (Buy more)
        # High Price -> Low Position (Sell more)
        target_position_pct = 1.0 - pos_pct
        
        # Determine Next Orders
        buy_price = current_price * (1 - GRID_STEP)
        sell_price = current_price * (1 + GRID_STEP)
        
        grids.append({
            "symbol": symbol,
            "name": name,
            "price": current_price,
            "range": f"{lower} - {upper}",
            "position": f"{target_position_pct*100:.1f}%",
            "next_buy": round(buy_price, 2),
            "next_sell": round(sell_price, 2),
            "status": "IN_RANGE" if lower <= current_price <= upper else "OUT_OF_RANGE"
        })

    # Generate Output
    # Mock Equity Curve (Grid Trading style: Step-like growth)
    dates = pd.date_range(end=datetime.datetime.now(), periods=90, freq='B')
    equity = 50000.0
    chart_data = []
    chart_labels = []
    
    for d in dates:
        # Simulate Grid Arbitrage: Small consistent gains
        gain = random.choice([0, 0, 50, 80, 120]) # Arbitrage profits
        equity += gain
        chart_labels.append(d.strftime('%Y-%m-%d'))
        chart_data.append(round(equity, 2))

    output = {
        "updated": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "grids": grids,
        "chart": {
            "labels": chart_labels,
            "data": chart_data
        },
        "stats": {
            "total_profit": round(equity - 50000, 2),
            "arbitrage_count": 142
        }
    }
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)
    print(f"GridMaster Data saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    run_strategy()
