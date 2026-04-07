import akshare as ak
import pandas as pd
import numpy as np
import json
import os
import datetime
import time
import random
import urllib.request
import traceback

import argparse
from common.paths import data_path

# --- Configuration ---
DATA_DIR = str(data_path())
os.makedirs(DATA_DIR, exist_ok=True)
DEFAULT_OUTPUT_FILE = os.path.join(DATA_DIR, 'etf_agent_data.json')
POOL_FILE = os.path.join(DATA_DIR, 'etf_pool_cache.json')

INITIAL_EQUITY = 1_000_000

HOLD_SIZE = 10
BASE_WEIGHT = 0.10
MAX_WEIGHT = 0.20
SECTOR_MAX_WEIGHT = 0.30

MOMENTUM_WINDOW = 20
MOMENTUM_WINDOW_LONG = 60
VOLATILITY_WINDOW = 20
RSI_WINDOW = 14
RSI_OVERBOUGHT = 80
MA_FILTER_WINDOW = 20

MIN_VOLUME_CNY = 50_000_000

MAX_POOL_SIZE = 80
POOL_SECTOR_CAP = 20
MAX_NEW_FETCHES_PER_RUN = 15
_NEW_FETCHES_THIS_RUN = 0

HIST_CACHE_DIR = os.path.join(DATA_DIR, 'etf_hist_cache')
os.makedirs(HIST_CACHE_DIR, exist_ok=True)

SIGNAL_CSV_COLUMNS = [
    'trade_date',
    'signal_time',
    'symbol',
    'name',
    'sector',
    'direction',
    'target_weight',
    'current_weight',
    'delta_weight',
    'adjust_amount_cny',
    'price',
    'score',
    'mom_20d',
]

DRAWDOWN_ALERT = 0.07
DRAWDOWN_ALERT_2 = 0.08
DRAWDOWN_STOP = 0.09

ASSET_TRAIL_STOP_60D = -0.07

COMMISSION_RATE = 0.0003
SLIPPAGE_RATE = 0.0005

ACTIVE_PARAMS = {
    'hold_size': 10,
    'base_weight': 0.1,
    'max_weight': 0.2,
    'sector_max_weight': 0.3,
    'rsi_overbought': 80,
    'ma20_gap_min': 0.0,
    'mom20_min': 0.0,
    'asset_trail_stop_60d': -0.06,
    'w_mom20': 0.50,
    'w_mom60': 0.30,
    'w_trend50': 0.15,
    'w_vol20': 0.12,
    'w_dd60': 0.05,
    'dd_alert': 0.07,
    'dd_alert2': 0.08,
    'dd_stop': 0.10,
    'risk_full': 1.0,
    'risk_alert': 0.40,
    'risk_alert2': 0.35,
    'risk_stop': 0.0,
    'bear_budget_cap': 0.30,
    'crash_budget_cap': 0.20,
    'allow_sectors_bear': ['Commodity', 'Bond', 'Overseas', 'Index'],
    'crash_ret1': -0.03,
    'crash_ret5': -0.06,
}

# Whitelist of Cross-Border/Commodity ETFs to ALWAYS include if liquid
# (To ensure diversification even if volume dips slightly)
SPECIAL_ETFS = [
    "513100", # Nasdaq
    "513500", # S&P 500
    "513520", # Nikkei
    "513030", # DAX
    "518880", # Gold
    "513330", # Oil (Hengsheng)
    "159985", # Soybean
    "159981", # Energy
]

CORE_ETFS = [
    ("510300", "沪深300ETF"),
    ("510500", "中证500ETF"),
    ("510050", "上证50ETF"),
    ("159915", "创业板ETF"),
    ("588000", "科创50ETF"),
    ("512480", "半导体ETF"),
    ("515030", "新能源车ETF"),
    ("512010", "医药50ETF"),
    ("512880", "证券ETF"),
    ("512690", "酒ETF"),
    ("512660", "军工ETF"),
    ("518880", "黄金ETF"),
    ("513100", "纳指ETF"),
    ("513500", "标普500ETF"),
]

def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

def load_best_params():
    report_file = os.path.join(DATA_DIR, 'etf_agent_backtest_report.json')
    try:
        with open(report_file, 'r', encoding='utf-8') as f:
            report = json.load(f)
        if isinstance(report.get('tuning_best_params'), dict):
            return report.get('tuning_best_params')
    except Exception:
        pass
    return None

def _pct_str(x: float) -> str:
    return f"{x * 100:.0f}%"

def _safe_float(x, default=0.0) -> float:
    try:
        v = float(x)
        if np.isnan(v) or np.isinf(v):
            return default
        return v
    except Exception:
        return default

def classify_sector(symbol: str, name: str) -> str:
    n = (name or "").strip()
    if symbol in {"518880", "518600", "518680", "159934", "159937", "159834"}:
        return "Commodity"
    if any(k in n for k in ["黄金", "金ETF", "上海金", "白银", "原油", "豆", "能源", "有色", "商品"]):
        return "Commodity"
    if any(k in n for k in ["纳指", "标普", "日经", "DAX", "德国", "海外", "恒生", "港股", "美股"]):
        return "Overseas"
    if any(k in n for k in ["医药", "医疗", "生物", "创新药"]):
        return "Healthcare"
    if any(k in n for k in ["证券", "银行", "保险", "金融"]):
        return "Finance"
    if any(k in n for k in ["半导体", "芯片", "通信", "计算机", "软件", "AI", "人工智能", "电子", "卫星"]):
        return "Tech"
    if any(k in n for k in ["军工", "国防", "航天"]):
        return "Defense"
    if any(k in n for k in ["新能源", "光伏", "风电", "电池", "汽车", "锂", "储能"]):
        return "NewEnergy"
    if any(k in n for k in ["消费", "酒", "食品", "家电"]):
        return "Consumer"
    if any(k in n for k in ["沪深300", "中证500", "上证50", "科创", "创业板", "红利", "指数"]):
        return "Index"
    if any(k in n for k in ["债", "国债", "信用"]):
        return "Bond"
    return f"Other:{symbol}"

def fetch_dynamic_etf_pool():
    """
    Fetches ALL ETFs, filters by volume, returns list of (symbol, name).
    Caches result for 24h to avoid API spam.
    """
    if os.path.exists(POOL_FILE):
        mtime = os.path.getmtime(POOL_FILE)
        if time.time() - mtime < 86400: # 24h cache
            try:
                with open(POOL_FILE, 'r', encoding='utf-8') as f:
                    log("Loading ETF pool from cache...")
                    pool = json.load(f)
                    if isinstance(pool, list):
                        cleaned = []
                        for x in pool:
                            if isinstance(x, (list, tuple)) and len(x) >= 2:
                                cleaned.append([str(x[0]), str(x[1])])

                        diversified = []
                        sector_cnt = {}
                        for sym, name in cleaned:
                            sector = classify_sector(sym, name)
                            key = sector if not sector.startswith('Other:') else 'Other'
                            if sector_cnt.get(key, 0) >= POOL_SECTOR_CAP:
                                continue
                            diversified.append([sym, name])
                            sector_cnt[key] = sector_cnt.get(key, 0) + 1
                            if len(diversified) >= MAX_POOL_SIZE:
                                break

                        return diversified
                    return []
            except:
                pass

    log("Fetching fresh ETF pool from AkShare (this may take a moment)...")
    try:
        # Get all ETF spot data
        df = ak.fund_etf_spot_em()
        
        # Filter: Volume > Threshold OR in Special List
        # Note: '成交额' is usually in unit (CNY). Double check data.
        # AkShare spot data usually returns '成交额' in numeric (e.g., 100000000)
        
        # Rename columns for safety
        df.rename(columns={'代码': 'symbol', '名称': 'name', '成交额': 'turnover'}, inplace=True)
        
        # Clean numeric
        df['turnover'] = pd.to_numeric(df['turnover'], errors='coerce').fillna(0)
        
        # Filter
        liquid_df = df[
            (df['turnover'] >= MIN_VOLUME_CNY) | 
            (df['symbol'].isin(SPECIAL_ETFS))
        ]
        
        # Deduplicate
        liquid_df = liquid_df.drop_duplicates(subset=['symbol'])
        
        # Optimization: Limit to Top 50 by turnover to ensure speed
        liquid_df = liquid_df.sort_values('turnover', ascending=False).head(MAX_POOL_SIZE)
        
        pool_raw = liquid_df[['symbol', 'name']].values.tolist()

        diversified = []
        sector_cnt = {}
        for sym, name in pool_raw:
            sym = str(sym)
            name = str(name)
            sector = classify_sector(sym, name)
            key = sector if not sector.startswith('Other:') else 'Other'
            if sector_cnt.get(key, 0) >= POOL_SECTOR_CAP:
                continue
            diversified.append([sym, name])
            sector_cnt[key] = sector_cnt.get(key, 0) + 1
            if len(diversified) >= MAX_POOL_SIZE:
                break

        pool = diversified
        
        # Save cache
        with open(POOL_FILE, 'w', encoding='utf-8') as f:
            json.dump(pool, f, ensure_ascii=False)
            
        log(f"Dynamic Pool Updated: {len(pool)} ETFs selected.")
        return pool
        
    except Exception as e:
        log(f"Error fetching dynamic pool: {e}")
        # Fallback to a basic list if API fails
        return [
            ["510300", "沪深300ETF"], ["510050", "上证50ETF"], ["510500", "中证500ETF"],
            ["588000", "科创50ETF"], ["512480", "半导体ETF"], ["512690", "酒ETF"],
            ["512010", "医药50ETF"], ["512880", "证券ETF"], ["512660", "军工ETF"],
            ["518880", "黄金ETF"], ["159915", "创业板ETF"], ["515030", "新能源车ETF"],
            ["513100", "纳指ETF"], ["513500", "标普500ETF"]
        ]

def fetch_etf_data(symbol, start_date=None, end_date=None):
    cache_path = os.path.join(HIST_CACHE_DIR, f"{symbol}.csv")
    start_dt = pd.to_datetime(start_date) if start_date else None
    end_dt = pd.to_datetime(end_date) if end_date else None

    def _post_process(x: pd.DataFrame) -> pd.DataFrame:
        if x.empty:
            return x
        x.rename(columns={'日期': 'date', '收盘': 'close', '开盘': 'open', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
        if 'date' not in x.columns:
            return pd.DataFrame()
        x['date'] = pd.to_datetime(x['date'])
        x.sort_values('date', inplace=True)
        if start_dt is not None:
            x = x[x['date'] >= start_dt]
        if end_dt is not None:
            x = x[x['date'] <= end_dt]
        return x

    global _NEW_FETCHES_THIS_RUN

    try:
        if os.path.exists(cache_path):
            try:
                cached = pd.read_csv(cache_path)
                cached = _post_process(cached)
                if not cached.empty:
                    mtime = os.path.getmtime(cache_path)
                    if time.time() - mtime < 6 * 3600:
                        return cached
            except Exception:
                cached = pd.DataFrame()
        else:
            cached = pd.DataFrame()

        if _NEW_FETCHES_THIS_RUN >= MAX_NEW_FETCHES_PER_RUN:
            return cached

        _NEW_FETCHES_THIS_RUN += 1
        df = ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust="qfq")
        df = _post_process(df)
        if not df.empty:
            df.to_csv(cache_path, index=False, encoding='utf-8-sig')
        return df
    except Exception:
        return pd.DataFrame()

def fetch_hs300_index_history():
    try:
        df = ak.stock_zh_index_daily(symbol='sh000300')
        df['date'] = pd.to_datetime(df['date'])
        df.sort_values('date', inplace=True)
        return df
    except:
        return pd.DataFrame()

def _sina_prefix(symbol: str) -> str:
    if symbol.startswith(('5', '6')): return 'sh'
    return 'sz'

def fetch_realtime_etf_prices_sina(symbols):
    # Batch fetch in chunks of 80 to respect URL length limits
    chunk_size = 80
    price_map = {}
    
    symbols = list(set(symbols)) # Unique
    
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        codes = [f"{_sina_prefix(s)}{s}" for s in chunk]
        url = f"http://hq.sinajs.cn/list={','.join(codes)}"
        headers = {'Referer': 'http://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                content = response.read().decode('gbk', errors='ignore')
                
            for line in content.splitlines():
                if '="' not in line: continue
                left, right = line.split('="', 1)
                code = left.split('hq_str_', 1)[-1].strip()
                data_str = right.split('"', 1)[0]
                parts = data_str.split(',')
                if len(parts) < 4: continue
                
                symbol = code[-6:]
                try:
                    p = float(parts[3])
                    if p > 0: price_map[symbol] = p
                except: continue
        except Exception as e:
            log(f"Error fetching batch {i}: {e}")
            
    return price_map

def calculate_rsi(series, window=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_factors(close_df, asof_date):
    """
    Calculates Multi-Factor Score:
    Score = (Momentum / Volatility)
    Filter: RSI < 80
    """
    # 1. Momentum (Return)
    mom = close_df / close_df.shift(MOMENTUM_WINDOW) - 1
    
    # 2. Volatility (Std Dev of daily returns)
    daily_ret = close_df.pct_change()
    vol = daily_ret.rolling(VOLATILITY_WINDOW).std()
    
    # 3. Risk-Adjusted Momentum (Sharpe-like)
    # Add small epsilon to avoid div by zero
    score = mom / (vol + 0.0001)
    
    # 4. RSI Filter
    # We need to calculate RSI for each column. Vectorized is tricky, loop is safer for clarity.
    rsi_df = pd.DataFrame(index=close_df.index, columns=close_df.columns)
    for col in close_df.columns:
        rsi_df[col] = calculate_rsi(close_df[col], RSI_WINDOW)
        
    if asof_date not in score.index:
        return pd.Series(dtype=float)
        
    current_scores = score.loc[asof_date].copy()
    current_rsi = rsi_df.loc[asof_date]
    
    # Filter: Drop if RSI > 80 (Overbought)
    # Also drop if Momentum < 0 (Absolute Momentum)
    # Also drop NaN
    
    valid_mask = (mom.loc[asof_date] > 0) & (current_rsi < RSI_OVERBOUGHT)
    final_scores = current_scores[valid_mask].dropna().sort_values(ascending=False)
    
    return final_scores

def precompute_indicators(close_df: pd.DataFrame) -> dict:
    x = close_df.astype(float).replace([np.inf, -np.inf], np.nan)
    mom_20 = x / x.shift(MOMENTUM_WINDOW) - 1
    mom_60 = x / x.shift(MOMENTUM_WINDOW_LONG) - 1
    vol_20 = x.pct_change().rolling(VOLATILITY_WINDOW).std()
    ma_20 = x.rolling(20).mean()
    ma_50 = x.rolling(50).mean()
    trend_50 = x / ma_50 - 1
    dd_60 = x / x.rolling(60).max() - 1

    delta = x.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.rolling(RSI_WINDOW).mean()
    avg_loss = loss.rolling(RSI_WINDOW).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    ma20_gap = x / ma_20 - 1

    return {
        'mom_20d': mom_20,
        'mom_60d': mom_60,
        'vol_20d': vol_20,
        'rsi_14d': rsi,
        'trend_50d': trend_50,
        'dd_60d': dd_60,
        'ma20_gap': ma20_gap,
    }

def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return s * 0
    return (s - s.mean()) / std

def compute_factor_table(precomp: dict, asof_date: pd.Timestamp, params: dict) -> pd.DataFrame:
    if asof_date not in precomp['mom_20d'].index:
        return pd.DataFrame()

    row = pd.DataFrame({
        'mom_20d': precomp['mom_20d'].loc[asof_date],
        'mom_60d': precomp['mom_60d'].loc[asof_date],
        'vol_20d': precomp['vol_20d'].loc[asof_date],
        'rsi_14d': precomp['rsi_14d'].loc[asof_date],
        'trend_50d': precomp['trend_50d'].loc[asof_date],
        'dd_60d': precomp['dd_60d'].loc[asof_date],
        'ma20_gap': precomp['ma20_gap'].loc[asof_date],
    })

    row = row.replace([np.inf, -np.inf], np.nan).dropna(how='any')
    if row.empty:
        return row

    row = row[
        (row['mom_20d'] > params.get('mom20_min', 0.0)) &
        (row['rsi_14d'] < params.get('rsi_overbought', RSI_OVERBOUGHT)) &
        (row['ma20_gap'] > params.get('ma20_gap_min', 0.0)) &
        (row['dd_60d'] > params.get('asset_trail_stop_60d', ASSET_TRAIL_STOP_60D))
    ]
    if row.empty:
        return row

    score = (
        params.get('w_mom20', 0.45) * _zscore(row['mom_20d']) +
        params.get('w_mom60', 0.30) * _zscore(row['mom_60d']) +
        params.get('w_trend50', 0.15) * _zscore(row['trend_50d']) -
        params.get('w_vol20', 0.10) * _zscore(row['vol_20d']) +
        params.get('w_dd60', 0.05) * _zscore(row['dd_60d'])
    )

    row = row.assign(score=score)
    row = row.sort_values('score', ascending=False)
    return row

def calculate_rsrs_score(high, low, N=18, M=600):
    """
    Calculate RSRS (Resistance Support Relative Strength) Z-Score.
    """
    dates = high.index
    high_vals = high.values
    low_vals = low.values
    n_len = len(high_vals)
    
    betas = np.full(n_len, np.nan)
    
    for i in range(N, n_len):
        y = high_vals[i-N:i]
        x = low_vals[i-N:i]
        
        # Linear Regression: High = Beta * Low + Alpha
        try:
            # np.polyfit is fast enough for daily data
            slope, _ = np.polyfit(x, y, 1)
            betas[i] = slope
        except:
            pass
            
    betas_s = pd.Series(betas, index=dates)
    # Z-Score with M-day rolling window
    zscore = (betas_s - betas_s.rolling(M, min_periods=250).mean()) / betas_s.rolling(M, min_periods=250).std()
    return zscore

def precompute_market_indicators(hs300_data) -> dict:
    """
    hs300_data: pd.DataFrame with 'close', 'high', 'low' columns OR pd.Series (close only)
    """
    if isinstance(hs300_data, pd.Series):
        close = hs300_data.astype(float)
        high = close
        low = close
    else:
        close = hs300_data['close'].astype(float)
        high = hs300_data['high'].astype(float) if 'high' in hs300_data.columns else close
        low = hs300_data['low'].astype(float) if 'low' in hs300_data.columns else close

    rsrs = calculate_rsrs_score(high, low)

    return {
        'close': close,
        'ma20': close.rolling(20).mean(),
        'ma60': close.rolling(60).mean(),
        'ret1': close.pct_change(),
        'ret5': close.pct_change(5),
        'rsrs': rsrs
    }

def determine_market_regime(market_precomp: dict, asof_date: pd.Timestamp, params=None) -> str:
    if not isinstance(market_precomp, dict):
        log(f"Error: market_precomp is not a dict, it is {type(market_precomp)}")
        return 'BEAR'
    if 'close' not in market_precomp:
        log(f"Error: market_precomp missing 'close' key. Keys: {list(market_precomp.keys())}")
        return 'BEAR'

    if asof_date not in market_precomp['close'].index:
        return 'BEAR'

    c = market_precomp['close'].loc[asof_date]
    m20 = market_precomp['ma20'].loc[asof_date]
    m60 = market_precomp['ma60'].loc[asof_date]
    r1 = market_precomp['ret1'].loc[asof_date]
    r5 = market_precomp['ret5'].loc[asof_date]
    rsrs = market_precomp['rsrs'].loc[asof_date] if 'rsrs' in market_precomp else np.nan

    p = params or ACTIVE_PARAMS
    
    # Check for RSRS override flag in params (passed via command line -> main -> run_strategy -> params)
    use_rsrs = p.get('use_rsrs', False)

    # 1. CRASH Protection (Always Priority)
    if not np.isnan(r1) and r1 <= p.get('crash_ret1', -0.03):
        return 'CRASH'
    if not np.isnan(r5) and r5 <= p.get('crash_ret5', -0.06):
        return 'CRASH'
        
    # 2. RSRS Timing (If available and enabled)
    # RSRS > 0.7 -> Strong Bull (Buy Signal - Early Entry)
    if use_rsrs and not np.isnan(rsrs):
        if rsrs > 0.7:
            return 'BULL'
        if rsrs < -0.7:
            return 'BEAR'
            
    # 3. MA Trend Follow (Fallback or when RSRS is neutral)
    if not np.isnan(m60) and c < m60:
        return 'BEAR'
    if not np.isnan(m20) and c < m20:
        return 'BEAR'
        
    return 'BULL'

def risk_control_params(current_drawdown: float, params: dict):
    if current_drawdown >= params.get('dd_stop', DRAWDOWN_STOP):
        return params.get('risk_stop', 0.0), 'STOP'
    if current_drawdown >= params.get('dd_alert2', DRAWDOWN_ALERT_2):
        return params.get('risk_alert2', 0.25), 'DE_RISK_2'
    if current_drawdown >= params.get('dd_alert', DRAWDOWN_ALERT):
        return params.get('risk_alert', 0.50), 'DE_RISK_1'
    return params.get('risk_full', 1.0), 'NORMAL'

def build_target_weights(
    factor_table: pd.DataFrame,
    name_map: dict,
    risk_budget: float,
    allow_sectors=None,
    params=None,
):
    p = params or ACTIVE_PARAMS
    if risk_budget <= 0 or factor_table.empty:
        return {}, {}

    selected = []
    sector_map = {}
    sector_weight = {}

    base_w = float(p.get('base_weight', BASE_WEIGHT))
    max_w = float(p.get('max_weight', MAX_WEIGHT))
    sector_cap = float(p.get('sector_max_weight', SECTOR_MAX_WEIGHT))
    hold_size = int(p.get('hold_size', HOLD_SIZE))

    for sym in factor_table.index.tolist():
        name = name_map.get(sym, sym)
        sector = classify_sector(sym, name)
        if allow_sectors is not None and sector not in allow_sectors:
            continue
        if sector_weight.get(sector, 0.0) + base_w > sector_cap + 1e-9:
            continue
        selected.append(sym)
        sector_map[sym] = sector
        sector_weight[sector] = sector_weight.get(sector, 0.0) + base_w
        if len(selected) >= hold_size:
            break

    if not selected:
        return {}, {}

    weights = {sym: base_w for sym in selected}
    total_w = sum(weights.values())
    if total_w > risk_budget + 1e-9:
        scale = risk_budget / total_w
        for sym in list(weights.keys()):
            weights[sym] *= scale
        return weights, sector_map

    extra = risk_budget - total_w
    for _ in range(50):
        if extra <= 1e-8:
            break
        eligible = []
        for sym in selected:
            sector = sector_map[sym]
            cap_left = min(max_w - weights[sym], sector_cap - sum(w for s, w in weights.items() if sector_map.get(s) == sector))
            if cap_left > 1e-12:
                eligible.append((sym, cap_left))
        if not eligible:
            break
        per = extra / len(eligible)
        consumed = 0.0
        for sym, cap_left in eligible:
            add = min(per, cap_left)
            weights[sym] += add
            consumed += add
        extra -= consumed
        if consumed <= 1e-12:
            break

    return weights, sector_map

def get_market_status(hs300_close, asof_date):
    """
    Returns 'BULL' or 'BEAR' based on MA20.
    """
    if asof_date not in hs300_close.index:
        return 'BEAR' # Default safety
        
    ma = hs300_close.rolling(MA_FILTER_WINDOW).mean()
    curr = hs300_close.loc[asof_date]
    curr_ma = ma.loc[asof_date]
    
    if pd.isna(curr_ma): return 'BULL'
    
    return 'BULL' if curr > curr_ma else 'BEAR'

def backtest_strategy(close_df, hs300_close, name_map=None, params=None, precomp=None, market_precomp=None):
    p = params or ACTIVE_PARAMS
    if name_map is None:
        name_map = {}
    dates = close_df.index
    equity = float(INITIAL_EQUITY)
    bench_equity = float(INITIAL_EQUITY)

    asset_ret = close_df.pct_change().fillna(0.0)
    asset_ret = asset_ret.replace([np.inf, -np.inf], 0.0)
    bench_ret = hs300_close.pct_change().fillna(0.0)
    bench_ret = bench_ret.replace([np.inf, -np.inf], 0.0)

    lookback = max(MOMENTUM_WINDOW_LONG, 60, 50, MA_FILTER_WINDOW, RSI_WINDOW + 2) + 2
    if len(dates) <= lookback + 2:
        return {
            'strategy': pd.Series(dtype=float),
            'benchmark': pd.Series(dtype=float),
            'stats': {}
        }

    if precomp is None:
        precomp = precompute_indicators(close_df)
    
    if market_precomp is None:
        market_precomp = precompute_market_indicators(hs300_close)

    curve_dates = []
    curve = []
    bench_curve = []
    dd_series = []
    turnover_series = []
    cost_series = []

    weights_prev = {}
    peak_equity = equity

    for i in range(lookback + 1, len(dates)):
        today = dates[i]
        decision_date = dates[i - 1]

        peak_equity = max(peak_equity, equity)
        current_dd = (peak_equity - equity) / peak_equity if peak_equity else 0.0

        regime = determine_market_regime(market_precomp, decision_date, p)
        risk_budget, risk_mode = risk_control_params(current_dd, p)

        allow_sectors = None
        if regime in {'BEAR', 'CRASH'}:
            allow_sectors = set(p.get('allow_sectors_bear', ['Commodity', 'Bond', 'Overseas', 'Index']))
            risk_budget = min(risk_budget, float(p.get('bear_budget_cap', 0.30)))

        if regime == 'CRASH':
            risk_budget = min(risk_budget, float(p.get('crash_budget_cap', 0.20)))

        factor_table = compute_factor_table(precomp, decision_date, p)
        target_weights, _ = build_target_weights(factor_table, name_map, risk_budget, allow_sectors=allow_sectors, params=p)

        turnover = 0.0
        all_syms = set(weights_prev.keys()) | set(target_weights.keys())
        for sym in all_syms:
            turnover += abs(target_weights.get(sym, 0.0) - weights_prev.get(sym, 0.0))

        cost = equity * turnover * (COMMISSION_RATE + SLIPPAGE_RATE)
        equity = max(0.0, equity - cost)

        port_ret = 0.0
        if target_weights:
            r = asset_ret.loc[today]
            for sym, w in target_weights.items():
                port_ret += w * _safe_float(r.get(sym, 0.0), 0.0)

        equity *= (1.0 + port_ret)
        bench_equity *= (1.0 + _safe_float(bench_ret.loc[today], 0.0))

        peak_equity = max(peak_equity, equity)
        current_dd = (peak_equity - equity) / peak_equity if peak_equity else 0.0

        curve_dates.append(today)
        curve.append(equity)
        bench_curve.append(bench_equity)
        dd_series.append(current_dd)
        turnover_series.append(turnover)
        cost_series.append(cost)

        weights_prev = target_weights

    strategy = pd.Series(curve, index=pd.DatetimeIndex(curve_dates))
    benchmark = pd.Series(bench_curve, index=pd.DatetimeIndex(curve_dates))
    dd_s = pd.Series(dd_series, index=pd.DatetimeIndex(curve_dates))
    turnover_s = pd.Series(turnover_series, index=pd.DatetimeIndex(curve_dates))

    daily_ret = strategy.pct_change().fillna(0.0)
    ann_ret = (strategy.iloc[-1] / strategy.iloc[0]) ** (252 / max(1, len(strategy))) - 1 if len(strategy) > 1 else 0.0
    vol = daily_ret.std(ddof=0)
    sharpe = (daily_ret.mean() / vol) * np.sqrt(252) if vol and not np.isnan(vol) else 0.0
    max_dd = dd_s.max() if not dd_s.empty else 0.0

    stats = {
        'annualized_return': float(ann_ret),
        'sharpe': float(sharpe),
        'max_drawdown': float(max_dd),
        'avg_turnover': float(turnover_s.mean()) if not turnover_s.empty else 0.0,
        'days': int(len(strategy))
    }

    return {
        'strategy': strategy,
        'benchmark': benchmark,
        'drawdown': dd_s,
        'stats': stats
    }

def _load_prev_positions():
    try:
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        positions = {}
        for p in data.get('portfolio', []) or []:
            sym = p.get('symbol')
            w = p.get('target_weight')
            if not sym:
                continue
            if isinstance(w, str) and w.endswith('%'):
                positions[str(sym)] = _safe_float(w[:-1], 0.0) / 100.0
            else:
                positions[str(sym)] = _safe_float(w, 0.0)
        return positions
    except Exception:
        return {}

def _next_trading_day(index: pd.DatetimeIndex, d: pd.Timestamp) -> pd.Timestamp:
    try:
        pos = index.get_indexer([d])[0]
        if pos >= 0 and pos + 1 < len(index):
            return index[pos + 1]
    except Exception:
        pass
    return d + datetime.timedelta(days=1)

def _write_signal_csv(rows, latest_path: str, archive_path: str):
    if rows:
        df = pd.DataFrame(rows)
        for c in SIGNAL_CSV_COLUMNS:
            if c not in df.columns:
                df[c] = np.nan
        df = df[SIGNAL_CSV_COLUMNS]
    else:
        df = pd.DataFrame(columns=SIGNAL_CSV_COLUMNS)
    df.to_csv(latest_path, index=False, encoding='utf-8-sig')
    df.to_csv(archive_path, index=False, encoding='utf-8-sig')

def run_tuning():
    log("Tuning mode started...")

    pool = fetch_dynamic_etf_pool()
    name_map = {p[0]: p[1] for p in pool}
    for sym, name in CORE_ETFS:
        if sym not in name_map:
            name_map[sym] = name
    symbols = list(name_map.keys())

    now = datetime.datetime.now()
    end_date = now.strftime('%Y%m%d')
    start_date = (now - datetime.timedelta(days=1095)).strftime('%Y%m%d')

    close_list = []
    for sym in symbols:
        try:
            df = fetch_etf_data(sym, start_date, end_date)
            if not df.empty:
                s = df.set_index('date')['close'].sort_index()
                s.name = sym
                close_list.append(s)
            
            if len(close_list) > 0 and len(close_list) % 10 == 0:
                log(f"Fetched {len(close_list)} for tuning...")
            
            time.sleep(0.1)
        except Exception as e:
            log(f"Error fetching {sym} for tuning: {e}")

    log(f"Tuning dataset: ETFs={len(close_list)}")

    if not close_list:
        log("No data found.")
        return

    close_df = pd.concat(close_list, axis=1).dropna(how='all').ffill()
    log(f"Tuning date range: {close_df.index.min()} to {close_df.index.max()}, rows={len(close_df)}")

    hs300 = fetch_hs300_index_history()
    if hs300.empty:
        log("Error: HS300 history not found.")
        return

    hs300 = hs300.set_index('date').sort_index()
    market_precomp_full = precompute_market_indicators(hs300)

    hs300_close = hs300['close'].astype(float)
    hs300_close = hs300_close[hs300_close.index >= pd.to_datetime(start_date)]

    common_index = hs300_close.index.intersection(close_df.index)
    if common_index.empty:
        log("No overlapping dates between HS300 and ETFs.")
        return

    common_index = common_index.sort_values()
    hs300_close = hs300_close.loc[common_index]
    close_df = close_df.reindex(common_index).ffill().fillna(0.0).astype(float)

    log(f"Aligned rows={len(close_df)}, cols={close_df.shape[1]}")

    precomp = precompute_indicators(close_df)
    market_precomp = {k: v.reindex(common_index) for k, v in market_precomp_full.items()}

    base = dict(ACTIVE_PARAMS)

    trail_list = [-0.07, -0.08, -0.09]
    dd_stop_list = [0.10]
    dd_alert_list = [0.06, 0.07]
    dd_alert2_list = [0.08, 0.09]
    vol_pen_list = [0.10, 0.12]
    trend_list = [0.10, 0.15, 0.20]
    mom20_list = [0.40, 0.50]
    risk_alert_list = [0.50]
    risk_alert2_list = [0.25]

    candidates = []
    tested = 0

    for trail in trail_list:
        for dd_stop in dd_stop_list:
            for dd_alert in dd_alert_list:
                for dd_alert2 in dd_alert2_list:
                    if not (dd_alert < dd_alert2 < dd_stop):
                        continue
                    for w_vol in vol_pen_list:
                        for w_trend in trend_list:
                            for w_mom20 in mom20_list:
                                w_dd = 0.05
                                w_mom60 = 1.0 - w_mom20 - w_trend - w_dd
                                if w_mom60 < 0.10 or w_mom60 > 0.55:
                                    continue
                                for r1 in risk_alert_list:
                                    for r2 in risk_alert2_list:
                                        if r2 >= r1:
                                            continue
                                        params = dict(base)
                                        params['asset_trail_stop_60d'] = float(trail)
                                        params['dd_stop'] = float(dd_stop)
                                        params['dd_alert'] = float(dd_alert)
                                        params['dd_alert2'] = float(dd_alert2)
                                        params['w_vol20'] = float(w_vol)
                                        params['w_trend50'] = float(w_trend)
                                        params['w_mom20'] = float(w_mom20)
                                        params['w_mom60'] = float(w_mom60)
                                        params['w_dd60'] = float(w_dd)
                                        params['risk_alert'] = float(r1)
                                        params['risk_alert2'] = float(r2)

                                        res = backtest_strategy(close_df, hs300_close, name_map=name_map, params=params, precomp=precomp, market_precomp=market_precomp)
                                        stats = res.get('stats', {})
                                        if not stats:
                                            continue

                                        max_dd = float(stats.get('max_drawdown', 1.0))
                                        ann = float(stats.get('annualized_return', -1.0))
                                        sharpe = float(stats.get('sharpe', -99.0))
                                        turnover = float(stats.get('avg_turnover', 0.0))

                                        if max_dd > 0.10:
                                            continue

                                        score = sharpe + 0.6 * ann - 0.15 * turnover - 2.0 * max(0.0, 0.30 - ann)
                                        candidates.append({
                                            'score': float(score),
                                            'stats': {
                                                'annualized_return': ann,
                                                'sharpe': sharpe,
                                                'max_drawdown': max_dd,
                                                'avg_turnover': turnover,
                                                'days': int(stats.get('days', 0)),
                                            },
                                            'params': params,
                                        })
                                        tested += 1
                                        if tested % 100 == 0:
                                            log(f"Tested {tested} combinations...")
                                        
                                        # if tested >= 120:
                                        #     break
                                    # if tested >= 120:
                                    #     break
                                # if tested >= 120:
                                #     break
                            # if tested >= 120:
                            #     break
                        # if tested >= 120:
                        #     break
                    # if tested >= 120:
                    #     break
                # if tested >= 120:
                #     break
            # if tested >= 120:
            #     break
        # if tested >= 120:
        #     break

    if not candidates:
        log("No feasible candidates under max drawdown constraint.")
        return

    candidates.sort(key=lambda x: x['score'], reverse=True)
    best = candidates[0]
    top = candidates[:15]

    report_file = os.path.join(DATA_DIR, 'etf_agent_backtest_report.json')
    try:
        with open(report_file, 'r', encoding='utf-8') as f:
            report = json.load(f)
        if not isinstance(report, dict):
            report = {}
    except Exception:
        report = {}

    report['tuning_updated'] = now.strftime('%Y-%m-%d %H:%M:%S')
    report['tuning_best_score'] = best['score']
    report['tuning_best_stats'] = best['stats']
    report['tuning_best_params'] = best['params']
    report['tuning_top'] = top
    report['use_tuning_best'] = False

    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    log(f"Tuning done. Best Sharpe={best['stats']['sharpe']:.2f}, AnnRet={best['stats']['annualized_return']:.2%}, MaxDD={best['stats']['max_drawdown']:.2%}")

def run_strategy():
    log("Starting ETF Agent v2.0 (Low Drawdown Mode)...")
    
    # 1. Pool
    pool = fetch_dynamic_etf_pool()
    name_map = {p[0]: p[1] for p in pool}
    for sym, name in CORE_ETFS:
        if sym not in name_map:
            name_map[sym] = name
    symbols = list(name_map.keys())
    if len(symbols) > MAX_POOL_SIZE:
        symbols = symbols[:MAX_POOL_SIZE]
    
    # 2. Data
    now = datetime.datetime.now()
    end_date = now.strftime('%Y%m%d')
    start_date = (now - datetime.timedelta(days=1095)).strftime('%Y%m%d') # 3 years (365*3)
    
    close_list = []
    last_prices = {}
    
    log(f"Fetching history for {len(symbols)} ETFs...")
    fetched_count = 0
    for sym in symbols:
        # log(f"Fetching {sym}...")
        try:
            df = fetch_etf_data(sym, start_date, end_date)
            if not df.empty:
                s = df.set_index('date')['close'].sort_index()
                s.name = sym
                close_list.append(s)
                last_prices[sym] = float(s.iloc[-1])
                fetched_count += 1
            
            if fetched_count > 0 and fetched_count % 5 == 0:
                log(f"Fetched {fetched_count} series (latest: {sym})...")
            
            time.sleep(0.2) # Avoid rate limits
        except Exception as e:
            log(f"Error fetching {sym}: {e}")

    log(f"History fetch done. Non-empty series={len(close_list)}")
        
    if not close_list:
        log("No data found.")
        return
        
    close_df = pd.concat(close_list, axis=1).dropna(how='all')
    close_df = close_df.ffill()
    
    # Do NOT drop rows where ANY ETF is missing, because new ETFs (like Satellite ETF)
    # have short history. If we use dropna(how='any'), we lose all history before their listing.
    # Instead, we just drop rows where we have NO data for any ETF (which we did with how='all').
    # But calculate_factors and backtest need clean data?
    # calculate_factors handles NaNs by returning NaN for that asset.
    # backtest_strategy uses .pct_change().fillna(0), so missing assets just have 0 return.
    
    # However, we must ensure we have a continuous date index.
    # Reindex to HS300 index to ensure trading days
    hs300 = fetch_hs300_index_history()
    if hs300.empty:
        log("Error: HS300 history not found.")
        return

    hs300 = hs300.set_index('date').sort_index()
    # Precompute RSRS and other indicators on full history
    market_precomp_full = precompute_market_indicators(hs300)

    hs300_close = hs300['close'].astype(float)
    hs300_close = hs300_close[hs300_close.index >= pd.to_datetime(start_date)]

    common_index = hs300_close.index.intersection(close_df.index)
    if common_index.empty:
        log("No overlapping dates between HS300 and ETFs.")
        return

    common_index = common_index.sort_values()
    hs300_close = hs300_close.loc[common_index]
    close_df = close_df.reindex(common_index).ffill().fillna(0.0)
    
    if close_df.shape[0] < 120:
        log("Insufficient data after alignment.")
        return

    close_df = close_df.astype(float)

    use_tuned = '--use-tuned' in os.sys.argv
    best = load_best_params() if use_tuned else None
    params = best if isinstance(best, dict) else ACTIVE_PARAMS
    
    precomp = precompute_indicators(close_df)
    
    # Align market_precomp to common_index
    market_precomp = {k: v.reindex(common_index) for k, v in market_precomp_full.items()}
    
    log(f"Running Backtest... (Use Tuned Params: {use_tuned})")
    bt_res = backtest_strategy(close_df, hs300_close, name_map=name_map, params=params, precomp=precomp, market_precomp=market_precomp)
    strategy_equity = bt_res.get('strategy', pd.Series(dtype=float))
    benchmark_equity = bt_res.get('benchmark', pd.Series(dtype=float))
    dd_series = bt_res.get('drawdown', pd.Series(dtype=float))
    perf_stats = bt_res.get('stats', {})
    
    last_date = close_df.index[-1]
    regime = determine_market_regime(market_precomp, last_date, params)

    total_equity = float(strategy_equity.iloc[-1]) if len(strategy_equity) else float(INITIAL_EQUITY)
    prev_equity = float(strategy_equity.iloc[-2]) if len(strategy_equity) >= 2 else total_equity
    daily_return_pct = ((total_equity - prev_equity) / prev_equity * 100.0) if prev_equity else 0.0
    peak = float(strategy_equity.cummax().iloc[-1]) if len(strategy_equity) else total_equity
    current_dd = (peak - total_equity) / peak if peak else 0.0

    risk_budget, risk_mode = risk_control_params(current_dd, params)
    allow_sectors = None
    if regime in {'BEAR', 'CRASH'}:
        allow_sectors = set(params.get('allow_sectors_bear', ['Commodity', 'Bond', 'Overseas', 'Index']))
        risk_budget = min(risk_budget, float(params.get('bear_budget_cap', 0.30)))
    if regime == 'CRASH':
        risk_budget = min(risk_budget, float(params.get('crash_budget_cap', 0.20)))

    factor_table = compute_factor_table(precomp, last_date, params)
    target_weights, sector_map = build_target_weights(factor_table, name_map, risk_budget, allow_sectors=allow_sectors, params=params)
    prev_weights = _load_prev_positions()

    trade_date = _next_trading_day(hs300_close.index, last_date)

    target_symbols = sorted(target_weights.keys())
    rt_prices = fetch_realtime_etf_prices_sina(target_symbols)

    portfolio = []
    trades = []
    csv_rows = []

    for sym in target_symbols:
        name = name_map.get(sym, sym)
        sector = sector_map.get(sym) or classify_sector(sym, name)
        price = _safe_float(rt_prices.get(sym, last_prices.get(sym, 0.0)), 0.0)

        tw = float(target_weights.get(sym, 0.0))
        cw = float(prev_weights.get(sym, 0.0))
        dw = tw - cw
        direction = 'HOLD'
        if dw > 1e-6:
            direction = 'BUY'
        elif dw < -1e-6:
            direction = 'SELL'
        adjust_amt = dw * total_equity

        score = _safe_float(factor_table.loc[sym, 'score'] if sym in factor_table.index else 0.0, 0.0)
        mom_20d = _safe_float(factor_table.loc[sym, 'mom_20d'] if sym in factor_table.index else 0.0, 0.0)

        portfolio.append({
            'symbol': sym,
            'name': name,
            'sector': sector,
            'direction': direction,
            'target_weight': _pct_str(tw),
            'current_weight': _pct_str(cw),
            'adjust_amount': round(adjust_amt, 2),
            'price': round(price, 4),
            'mom_20d': round(mom_20d, 6),
            'score': round(score, 6)
        })

        if direction != 'HOLD':
            trades.append({
                'symbol': sym,
                'name': name,
                'direction': direction,
                'target_weight': _pct_str(tw),
                'current_weight': _pct_str(cw),
                'adjust_amount': round(adjust_amt, 2)
            })

        csv_rows.append({
            'trade_date': trade_date.strftime('%Y-%m-%d'),
            'signal_time': '14:45',
            'symbol': sym,
            'name': name,
            'sector': sector,
            'direction': direction,
            'target_weight': round(tw, 6),
            'current_weight': round(cw, 6),
            'delta_weight': round(dw, 6),
            'adjust_amount_cny': round(adjust_amt, 2),
            'price': round(price, 4),
            'score': round(score, 6),
            'mom_20d': round(mom_20d, 6)
        })

    cash_weight = 1.0 - sum(target_weights.values())
    cash_weight = max(0.0, cash_weight)

    max_dd = float(perf_stats.get('max_drawdown', 0.0))

    log(f"Backtest Stats: AnnRet={perf_stats.get('annualized_return', 0.0):.2%}, Sharpe={perf_stats.get('sharpe', 0.0):.2f}, MaxDD={max_dd:.2%}")
    
    # Output JSON
    signal_dir = os.path.join(DATA_DIR, 'etf_agent_signals')
    os.makedirs(signal_dir, exist_ok=True)

    latest_csv = os.path.join(DATA_DIR, 'etf_agent_signal_latest.csv')
    archive_csv = os.path.join(signal_dir, f"{trade_date.strftime('%Y-%m-%d')}.csv")
    _write_signal_csv(csv_rows, latest_csv, archive_csv)

    index_file = os.path.join(DATA_DIR, 'etf_agent_signals_index.json')
    try:
        with open(index_file, 'r', encoding='utf-8') as f:
            idx = json.load(f)
        if not isinstance(idx, list):
            idx = []
    except Exception:
        idx = []

    idx = [x for x in idx if x.get('date') != trade_date.strftime('%Y-%m-%d')]
    idx.insert(0, {
        'date': trade_date.strftime('%Y-%m-%d'),
        'csv': f"data/etf_agent_signals/{trade_date.strftime('%Y-%m-%d')}.csv",
        'updated': now.strftime('%Y-%m-%d %H:%M:%S')
    })
    idx = idx[:180]
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

    buy_list = [t['symbol'] for t in trades if t.get('direction') == 'BUY']
    sell_list = [t['symbol'] for t in trades if t.get('direction') == 'SELL']

    output_data = {
        'updated': now.strftime('%Y-%m-%d %H:%M:%S'),
        'signal_time': '14:45',
        'trade_date': trade_date.strftime('%Y-%m-%d'),
        'market_regime': regime,
        'signal': {
            'trade_date': trade_date.strftime('%Y-%m-%d'),
            'buy': buy_list,
            'sell': sell_list
        },
        'risk': {
            'current_drawdown': round(current_dd * 100, 2),
            'risk_mode': risk_mode,
            'risk_budget': round(risk_budget, 4)
        },
        'trades': trades,
        'portfolio': portfolio,
        'cash_weight': _pct_str(cash_weight),
        'csv': {
            'latest': 'data/etf_agent_signal_latest.csv',
            'archive': f"data/etf_agent_signals/{trade_date.strftime('%Y-%m-%d')}.csv"
        },
        'stats': {
            'total_equity': int(round(total_equity)),
            'daily_return': round(daily_return_pct, 2),
            'annualized_return': round(_safe_float(perf_stats.get('annualized_return', 0.0), 0.0) * 100, 2),
            'sharpe': round(_safe_float(perf_stats.get('sharpe', 0.0), 0.0), 2),
            'max_drawdown': round(max_dd * 100, 2),
            'benchmark': '沪深300'
        },
        'chart': {
            'labels': [d.strftime('%Y-%m-%d') for d in strategy_equity.index],
            'strategy': [round(_safe_float(x, 0.0), 2) for x in strategy_equity.values],
            'benchmark': [round(_safe_float(x, 0.0), 2) for x in benchmark_equity.reindex(strategy_equity.index).values],
            'drawdown': [round(_safe_float(x, 0.0) * 100, 2) for x in dd_series.reindex(strategy_equity.index).fillna(0.0).values]
        }
    }

    report_file = os.path.join(DATA_DIR, 'etf_agent_backtest_report.json')
    try:
        last_60 = strategy_equity.pct_change().fillna(0.0).tail(60)
        paper_ann = (strategy_equity.iloc[-1] / strategy_equity.iloc[-60]) ** (252 / 60) - 1 if len(strategy_equity) >= 60 else 0.0
        paper_vol = last_60.std(ddof=0)
        paper_sharpe = (last_60.mean() / paper_vol) * np.sqrt(252) if paper_vol and not np.isnan(paper_vol) else 0.0

        report = {
            'updated': now.strftime('%Y-%m-%d %H:%M:%S'),
            'period_start': strategy_equity.index.min().strftime('%Y-%m-%d') if len(strategy_equity) else None,
            'period_end': strategy_equity.index.max().strftime('%Y-%m-%d') if len(strategy_equity) else None,
            'stats': perf_stats,
            'active_params': params,
            'paper_simulation_60d': {
                'annualized_return': float(paper_ann),
                'sharpe': float(paper_sharpe)
            },
            'risk': {
                'drawdown_alert': float(params.get('dd_alert', DRAWDOWN_ALERT)),
                'drawdown_alert2': float(params.get('dd_alert2', DRAWDOWN_ALERT_2)),
                'drawdown_stop': float(params.get('dd_stop', DRAWDOWN_STOP))
            },
            'constraints': {
                'hold_size': int(params.get('hold_size', HOLD_SIZE)),
                'base_weight': float(params.get('base_weight', BASE_WEIGHT)),
                'max_weight': float(params.get('max_weight', MAX_WEIGHT)),
                'sector_max_weight': float(params.get('sector_max_weight', SECTOR_MAX_WEIGHT))
            }
        }
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=4)
        
    log(f"Data saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--tune', action='store_true', help='Run parameter tuning mode')
    parser.add_argument('--use-tuned', action='store_true', help='Use tuned parameters')
    parser.add_argument('--self-test', action='store_true', help='Run self test')
    parser.add_argument('--strategy', type=str, default='original', choices=['original', 'rsrs'], help='Strategy variant')
    parser.add_argument('--output', type=str, default=DEFAULT_OUTPUT_FILE, help='Output JSON path')
    
    args, unknown = parser.parse_known_args()

    try:
        if args.tune:
            run_tuning()
        elif args.self_test:
            x = pd.DataFrame({
                'A': np.linspace(1, 2, 260),
                'B': np.linspace(1, 1.5, 260) + 0.05 * np.sin(np.linspace(0, 20, 260)),
                'C': np.linspace(1, 1.2, 260) + 0.10 * np.sin(np.linspace(0, 30, 260)),
                'D': np.linspace(1, 0.8, 260),
                'E': np.linspace(1, 1.1, 260),
                'F': np.linspace(1, 1.3, 260),
                'G': np.linspace(1, 1.4, 260),
                'H': np.linspace(1, 1.05, 260),
                'I': np.linspace(1, 0.95, 260),
                'J': np.linspace(1, 1.25, 260),
                'K': np.linspace(1, 1.15, 260),
            }, index=pd.date_range('2024-01-01', periods=260, freq='B'))
            hs = pd.Series(np.linspace(1000, 1200, 260), index=x.index)
            pre = precompute_indicators(x)
            res = backtest_strategy(x, hs, name_map={}, params=ACTIVE_PARAMS, precomp=pre)
            if res.get('strategy', pd.Series(dtype=float)).empty:
                raise SystemExit(1)
            log("Self-test OK")
        else:
            run_strategy(args)
    except Exception as e:
        log(f"Critical Error: {e}")
        traceback.print_exc()
