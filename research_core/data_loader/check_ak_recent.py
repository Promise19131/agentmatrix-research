
import akshare as ak
import pandas as pd

try:
    df = ak.stock_zh_index_daily(symbol='sh000300')
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    print("Recent Data:")
    print(df.tail(10))
    
    # Check if High != Close
    diff = (df['high'] - df['close']).abs().sum()
    print(f"Total High-Close Diff: {diff}")
    
    recent = df.iloc[-200:]
    diff_recent = (recent['high'] - recent['close']).abs().sum()
    print(f"Recent High-Close Diff: {diff_recent}")
    
except Exception as e:
    print("Error:", e)
