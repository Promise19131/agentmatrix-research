
import akshare as ak
import pandas as pd

try:
    df = ak.stock_zh_index_daily(symbol='sh000300')
    print("Columns:", df.columns.tolist())
    print("Head:", df.head())
except Exception as e:
    print("Error:", e)
