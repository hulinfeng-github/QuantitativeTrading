"""
A股 T+1 底仓日内做T (Intraday T+0) 量化策略引擎
针对A股T+1规则：利用已有底仓，通过盘中分时VWAP均线偏离度与Pivot Points枢轴点，
实现“正T（低吸高抛，先买后卖）”与“倒T（高抛低吸，先卖后买）”，摊薄持仓成本，锁定日内差价收益。
"""
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

class T0IntradayStrategy:
    def __init__(self, bias_buy_threshold: float = -1.5, bias_sell_threshold: float = 2.0):
        """
        :param bias_buy_threshold: 正T低吸分时偏离度阈值 (默认 -1.5%，即价格低于VWAP 1.5%)
        :param bias_sell_threshold: 倒T高抛分时偏离度阈值 (默认 +2.0%，即价格高于VWAP 2.0%)
        """
        self.bias_buy_threshold = bias_buy_threshold
        self.bias_sell_threshold = bias_sell_threshold
        self.reload_config()

    def reload_config(self):
        """动态同步日内做T配置"""
        try:
            from config import load_config
            cfg = load_config()
            self.bias_buy_threshold = cfg.get("t0_bias_buy", self.bias_buy_threshold)
            self.bias_sell_threshold = cfg.get("t0_bias_sell", self.bias_sell_threshold)
        except Exception:
            pass

    @staticmethod
    def calculate_pivot_points(prev_close: float, high: float, low: float) -> Dict[str, float]:
        """计算日内经典枢轴点 (Pivot Points) 支撑与阻力位"""
        p = (high + low + prev_close) / 3.0
        r1 = 2 * p - low
        r2 = p + (high - low)
        s1 = 2 * p - high
        s2 = p - (high - low)
        return {
            "pivot": round(p, 2),
            "r1": round(r1, 2),
            "r2": round(r2, 2),
            "s1": round(s1, 2),
            "s2": round(s2, 2)
        }

    def analyze_t0(
        self,
        symbol: str,
        name: str,
        minute_df: pd.DataFrame,
        quote: Dict[str, Any],
        holding_shares: int = 0,
        entry_price: float = 0.0
    ) -> Optional[Dict[str, Any]]:
        """
        分析单只股票的日内做T机会
        :param symbol: 如 'sh600519'
        :param name: 如 '贵州茅台'
        :param minute_df: 分时数据 (time, price, vwap, bias)
        :param quote: 实时行情快照
        :param holding_shares: 当前底仓股数 (A股做T的前提是持有底仓)
        :param entry_price: 持仓成本价
        """
        if minute_df is None or len(minute_df) < 5:
            return None

        curr_point = minute_df.iloc[-1]
        price = float(curr_point['price'])
        vwap = float(curr_point['vwap'])
        bias = float(curr_point['bias'])
        curr_time = str(curr_point['time'])

        prev_close = float(quote.get('prev_close', price))
        high = float(quote.get('high', price))
        low = float(quote.get('low', price))

        # 计算日内枢轴支撑阻力
        pivots = self.calculate_pivot_points(prev_close, high, low)

        # 检查近3-5分钟价格动量斜率（是否出现拐点）
        recent_prices = minute_df['price'].tail(5).values
        price_slope = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100

        # 做T方向研判
        t_action = "NONE"       # BUY_T (正T低吸) | SELL_T (倒T高抛) | CLOSE_T (平仓) | WATCH (观望)
        t_type = "NONE"         # 正T / 倒T
        reasons = []
        confidence = 0          # 0-100 置信度

        # 建议做T股数：底仓的 30%~50%，至少100股，且为100的倍数
        suggested_shares = 0
        if holding_shares >= 100:
            suggested_shares = int((holding_shares * 0.4) // 100) * 100
            if suggested_shares == 0:
                suggested_shares = 100

        # ----------------- 1. 正T信号检测（先买后卖，低吸高抛） -----------------
        # 条件：负偏离大、触及支撑S1/S2、低位止跌拐头
        if bias <= self.bias_buy_threshold or (price <= pivots['s1'] and bias < -0.8):
            confidence += 40
            reasons.append(f"价格深度负偏离均线VWAP({vwap:.2f}元)，偏离度达到 {bias:.2f}% (超买超卖负极值)")
            
            if price <= pivots['s1']:
                confidence += 25
                reasons.append(f"价格触及日内S1关键支撑位({pivots['s1']:.2f}元)")
            
            # 止跌反弹确认：近2分钟价格不再创新低
            if len(recent_prices) >= 3 and recent_prices[-1] >= recent_prices[-2]:
                confidence += 25
                reasons.append("分时出现止跌企稳拐头迹象")

            if confidence >= 65:
                t_action = "BUY_T"
                t_type = "正T (先低吸买入，冲高后卖出等量底仓)"

        # ----------------- 2. 倒T信号检测（先卖后买，高抛低吸） -----------------
        # 条件：早盘或盘中脉冲急拉、正偏离大、触及阻力R1/R2、高位滞涨
        elif bias >= self.bias_sell_threshold or (price >= pivots['r1'] and bias > 1.0):
            confidence += 40
            reasons.append(f"盘中脉冲急拉，偏离分时均线VWAP({vwap:.2f}元)达 {bias:.2f}%，短线透支")

            if price >= pivots['r1']:
                confidence += 25
                reasons.append(f"价格承压于日内R1关键阻力位({pivots['r1']:.2f}元)")

            # 滞涨确认：高位走平或回落
            if len(recent_prices) >= 3 and recent_prices[-1] <= recent_prices[-2]:
                confidence += 25
                reasons.append("分时放量滞涨，上攻动能减弱，回踩概率极高")

            if confidence >= 65:
                t_action = "SELL_T"
                t_type = "倒T (先高抛卖出部分底仓，回踩后低位买回)"

        # ----------------- 3. 尾盘安全平仓提示（14:35 - 14:55） -----------------
        if "14:35" <= curr_time <= "14:55":
            if t_action == "NONE":
                reasons.append("临近尾盘，日内做T窗口即将关闭，请核实今日做T单是否已等量平仓")

        # 计算做T目标位与止损位
        target_price = price
        stop_price = price
        expected_spread_pct = 0.0

        if t_action == "BUY_T":
            # 正T目标：回抽VWAP均价线或R1
            target_price = round(max(vwap, price * 1.015), 2)
            stop_price = round(min(pivots['s2'], price * 0.985), 2)
            expected_spread_pct = round((target_price - price) / price * 100, 2)
        elif t_action == "SELL_T":
            # 倒T目标：回踩VWAP均线或S1
            target_price = round(min(vwap, price * 0.985), 2)
            stop_price = round(max(pivots['r2'], price * 1.015), 2)
            expected_spread_pct = round((price - target_price) / price * 100, 2)

        return {
            "symbol": symbol,
            "name": name,
            "time": curr_time,
            "price": price,
            "vwap": vwap,
            "bias": bias,
            "t_action": t_action,
            "t_type": t_type,
            "confidence": confidence,
            "holding_shares": holding_shares,
            "entry_price": entry_price,
            "suggested_shares": suggested_shares,
            "suggested_price": price,
            "target_price": target_price,
            "stop_price": stop_price,
            "expected_spread_pct": expected_spread_pct,
            "pivots": pivots,
            "reasons": reasons
        }

t0_strategy = T0IntradayStrategy()
