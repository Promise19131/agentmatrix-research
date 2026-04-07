import akshare as ak
import pandas as pd
import sys
from common.paths import data_path

if __name__ == "__main__":
    print("Starting simple fetch...", flush=True)
    try:
        # Try EM Daily directly - usually faster and reliable for standard indices
        print("Fetching sh000300 via stock_zh_index_daily_em...", flush=True)
        df = ak.stock_zh_index_daily_em(symbol="sh000300")
        print(f"Fetched {len(df)} rows.", flush=True)
        
        # Filter and process
        df['date'] = pd.to_datetime(df['date'])
        start_date = pd.to_datetime("2019-12-31")
        end_date = pd.to_datetime("2025-12-25")
        
        mask = (df['date'] >= start_date) & (df['date'] <= end_date)
        df = df.loc[mask].copy()
        
        if df.empty:
            print("No data in range.", flush=True)
            sys.exit(1)
            
        # Sort
        df = df.sort_values('date')
        
        # Base value
        base_row = df[df['date'] == start_date]
        if not base_row.empty:
            base_val = base_row.iloc[0]['close']
        else:
            base_val = df.iloc[0]['close']
            print(f"Warning: Exact start date not found, using {df.iloc[0]['date']}", flush=True)
            
        print(f"Base Value: {base_val}", flush=True)
        
        df['normalized'] = df['close'] / base_val
        
        # Output
        out_df = df[['date', 'close', 'normalized']]
        out_df.columns = ['日期', '收盘', '归一化净值']
        
        out_path = data_path("csi300_normalized_2019_2025.csv")
        out_df.to_csv(out_path, index=False, encoding='utf-8-sig')
        print(f"Saved to {out_path}", flush=True)
        
    except Exception as e:
        print(f"Error: {e}", flush=True)
