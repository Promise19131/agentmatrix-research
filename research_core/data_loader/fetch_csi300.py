import akshare as ak
import pandas as pd
import os
import sys
from common.paths import data_path

def fetch_and_normalize_csi300():
    print("Fetching CSI 300 data...", flush=True)
    
    # Define date range
    start_date_str = "2019-12-31"
    end_date_str = "2025-12-25"
    
    df = pd.DataFrame()
    
    # Method 1: index_zh_a_hist (EastMoney History)
    try:
        print("Attempting Method 1: ak.index_zh_a_hist(symbol='000300')...", flush=True)
        df = ak.index_zh_a_hist(symbol="000300", period="daily", start_date="20191231", end_date="20251225")
        if not df.empty:
            print("Method 1 success.", flush=True)
    except Exception as e:
        print(f"Method 1 failed: {e}", flush=True)

    # Method 2: stock_zh_index_daily_em (EastMoney Daily)
    if df.empty:
        try:
            print("Attempting Method 2: ak.stock_zh_index_daily_em(symbol='sh000300')...", flush=True)
            df = ak.stock_zh_index_daily_em(symbol="sh000300")
            if not df.empty:
                # Rename columns to match standard if needed, but usually it's 'date', 'close' etc.
                # EM returns: date, open, close, high, low, volume, amount
                print("Method 2 success.", flush=True)
        except Exception as e:
             print(f"Method 2 failed: {e}", flush=True)

    # Method 3: stock_zh_index_daily (Sina)
    if df.empty:
        try:
            print("Attempting Method 3: ak.stock_zh_index_daily(symbol='sh000300')...", flush=True)
            df = ak.stock_zh_index_daily(symbol="sh000300")
            if not df.empty:
                print("Method 3 success.", flush=True)
                # Sina returns: date, open, high, low, close, volume
        except Exception as e:
            print(f"Method 3 failed: {e}", flush=True)

    if df.empty:
        print("Error: All methods failed to fetch data.", flush=True)
        return

    # Standardize column names
    # Ensure we have 'date' and 'close'
    print(f"Columns fetched: {df.columns.tolist()}", flush=True)
    
    col_map = {
        'date': '日期', 'Date': '日期', 
        'close': '收盘', 'Close': '收盘',
        'open': '开盘', 'Open': '开盘',
        'high': '最高', 'High': '最高',
        'low': '最低', 'Low': '最低'
    }
    df = df.rename(columns=col_map)
    
    if '日期' not in df.columns or '收盘' not in df.columns:
        print("Error: Required columns (日期, 收盘) not found.", flush=True)
        return

    df['日期'] = pd.to_datetime(df['日期'])
    df = df.sort_values('日期')
    
    # Filter range
    mask = (df['日期'] >= pd.to_datetime(start_date_str)) & (df['日期'] <= pd.to_datetime(end_date_str))
    df = df.loc[mask].copy()
    
    if df.empty:
        print(f"Error: No data in range {start_date_str} to {end_date_str}.", flush=True)
        return

    # Find base value
    # If 2019-12-31 exists, use it. Else use first available.
    start_row = df[df['日期'] == pd.to_datetime(start_date_str)]
    if not start_row.empty:
        base_value = start_row.iloc[0]['收盘']
        print(f"Found exact match for {start_date_str}. Base Value: {base_value}", flush=True)
    else:
        base_value = df.iloc[0]['收盘']
        actual_start = df.iloc[0]['日期'].date()
        print(f"Warning: {start_date_str} not found. Using first available: {actual_start}. Base Value: {base_value}", flush=True)
        
    # Normalize
    df['归一化净值'] = df['收盘'] / base_value
    
    # Format for output
    result_df = df[['日期', '收盘', '归一化净值']]
    
    output_file = data_path("csi300_normalized_2019_2025.csv")
    result_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    
    print(f"Successfully saved {len(result_df)} rows to {output_file}", flush=True)
    print(result_df.head(), flush=True)

if __name__ == "__main__":
    fetch_and_normalize_csi300()
