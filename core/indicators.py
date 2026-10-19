"""
A股量化数学模型与核心指标库
包含：修正RSRS模型（OLS回归斜率+Z-score+决定系数R2修正）、ATR动态风控、多周期均线与MACD
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple

def calculate_rsrs(df: pd.DataFrame, n: int = 18, m: int = 600) -> pd.DataFrame:
    """
    计算修正RSRS（阻力支撑相对强度）指标
    数学公式：
    1. OLS一元线性回归：High = alpha + beta * Low
       利用协方差与方差向量化计算：beta = Cov(Low, High) / Var(Low)
       判定系数 R^2 = Corr(Low, High)^2
    2. 滑动 Z-Score 标准化：Z = (beta - Mean_m(beta)) / Std_m(beta)
    3. 修正 RSRS = Z * R^2
    :param df: 包含 high, low, close 的 DataFrame（按时间升序）
    :param n: 回归窗口天数，默认18
    :param m: 统计Z-score的历史窗口，默认600（不足时按已有长度统计，最小10天）
    :return: 包含 rsrs_beta, rsrs_r2, rsrs_zscore, rsrs_norm 的 DataFrame
    """
    df = df.copy()
    length = len(df)
    
    if length < n:
        df['rsrs_beta'] = np.nan
        df['rsrs_r2'] = np.nan
        df['rsrs_zscore'] = np.nan
        df['rsrs_norm'] = np.nan
        return df

    low = df['low']
    high = df['high']

    # 1. 向量化计算滑动 OLS 斜率与决定系数 R^2
    # Cov(Low, High) 和 Var(Low)
    cov = low.rolling(window=n, min_periods=n).cov(high)
    var_low = low.rolling(window=n, min_periods=n).var()
    
    # 避免低价波动极小导致的除零
    beta = np.where(var_low > 1e-8, cov / var_low, 1.0)
    
    # R^2 等于 Pearson 相关系数的平方
    corr = low.rolling(window=n, min_periods=n).corr(high)
    r2 = np.clip(corr ** 2, 0.0, 1.0)
    
    df['rsrs_beta'] = beta
    df['rsrs_r2'] = r2

    # 2. 向量化计算滑动 Z-Score: Z = (beta - mean) / std
    beta_series = pd.Series(beta, index=df.index)
    rolling_beta = beta_series.rolling(window=m, min_periods=10)
    mean_beta = rolling_beta.mean()
    std_beta = rolling_beta.std(ddof=0)
    
    z_score = np.where(std_beta > 1e-6, (beta_series - mean_beta) / std_beta, 0.0)
    # 对于前 n-1 个有效周期填入 NaN
    z_score[:n - 1] = np.nan
    
    # 3. 修正 RSRS = z_score * r2
    rsrs_norm = z_score * r2
    
    df['rsrs_zscore'] = z_score
    df['rsrs_norm'] = rsrs_norm
    return df

def calculate_ma(df: pd.DataFrame, windows=(5, 10, 20, 60)) -> pd.DataFrame:
    """计算多周期均线"""
    df = df.copy()
    for w in windows:
        df[f'ma{w}'] = df['close'].rolling(window=w).mean()
    return df

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """计算真实波幅ATR（用于自适应动态止损）"""
    df = df.copy()
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    df['tr'] = tr
    df['atr'] = tr.rolling(window=period).mean()
    return df

def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """计算 MACD 指标"""
    df = df.copy()
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    df['dif'] = ema_fast - ema_slow
    df['dea'] = df['dif'].ewm(span=signal, adjust=False).mean()
    df['macd_bar'] = (df['dif'] - df['dea']) * 2
    return df

def calculate_all_indicators(df: pd.DataFrame, n: int = 18, m: int = 600) -> pd.DataFrame:
    """全量指标管道计算"""
    if df is None or len(df) < 5:
        return df
    df = calculate_ma(df)
    df = calculate_macd(df)
    df = calculate_atr(df)
    df = calculate_rsrs(df, n=n, m=m)
    
    # 计算量比和换手放量特征
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ratio'] = df['volume'] / (df['vol_ma5'] + 1e-6)
    return df
