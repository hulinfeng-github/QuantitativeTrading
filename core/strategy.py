"""
A股主板顶级量化策略：修正RSRS模型 + 多周期量价共振波段系统
专注中低频波段（持仓数天至数周），避开高频手续费摩擦与日内洗盘，收益风险比最大化
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from core.indicators import calculate_all_indicators
from core.risk_manager import risk_manager

class RSRSMomentumStrategy:
    def __init__(self, rsrs_n: int = 18, rsrs_m: int = 600, buy_threshold: float = 0.7, sell_threshold: float = -0.7):
        self.rsrs_n = rsrs_n
        self.rsrs_m = rsrs_m
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.reload_config()

    def reload_config(self):
        """动态同步最新策略配置"""
        try:
            from config import load_config
            cfg = load_config()
            self.rsrs_n = cfg.get("rsrs_n", self.rsrs_n)
            self.rsrs_m = cfg.get("rsrs_m", self.rsrs_m)
            self.buy_threshold = cfg.get("rsrs_buy_threshold", self.buy_threshold)
            self.sell_threshold = cfg.get("rsrs_sell_threshold", self.sell_threshold)
        except Exception:
            pass

    def analyze(self, symbol: str, name: str, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """对单只股票最新K线进行全量指标计算与策略逻辑研判"""
        if df is None or len(df) < 30:
            return None
        df = calculate_all_indicators(df, n=self.rsrs_n, m=self.rsrs_m)
        return self.analyze_bar(symbol, name, df, idx=-1)

    def analyze_bar(
        self,
        symbol: str,
        name: str,
        df: pd.DataFrame,
        idx: int = -1,
        market_regime_bull: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        对已计算全部因子的DataFrame指定位置(idx)进行因果研判（杜绝未来函数）
        :param df: 已计算好全量滚动指标的 DataFrame
        :param idx: 研判条目索引（默认为 -1 最后一根K线）
        :param market_regime_bull: 大盘是否处于多头环境（上证指数/沪深300在MA60上方）
        """
        length = len(df)
        if idx < 0:
            idx = length + idx
        if idx < 1 or idx >= length:
            return None

        curr = df.iloc[idx]
        prev = df.iloc[idx - 1]

        close = float(curr['close'])
        ma5 = float(curr['ma5']) if not np.isnan(curr['ma5']) else close
        ma20 = float(curr['ma20']) if not np.isnan(curr['ma20']) else close
        ma60 = float(curr['ma60']) if not np.isnan(curr['ma60']) else close
        
        prev_ma20 = float(prev['ma20']) if not np.isnan(prev['ma20']) else ma20
        ma20_slope = (ma20 - prev_ma20) / prev_ma20 * 100 if prev_ma20 > 0 else 0

        rsrs_norm = float(curr['rsrs_norm']) if not np.isnan(curr['rsrs_norm']) else 0.0
        prev_rsrs_norm = float(prev['rsrs_norm']) if not np.isnan(prev['rsrs_norm']) else 0.0
        rsrs_beta = float(curr['rsrs_beta']) if not np.isnan(curr['rsrs_beta']) else 1.0
        rsrs_r2 = float(curr['rsrs_r2']) if not np.isnan(curr['rsrs_r2']) else 0.0
        
        dif = float(curr['dif']) if not np.isnan(curr['dif']) else 0.0
        dea = float(curr['dea']) if not np.isnan(curr['dea']) else 0.0
        macd_bar = float(curr['macd_bar']) if not np.isnan(curr['macd_bar']) else 0.0
        
        vol_ratio = float(curr['vol_ratio']) if not np.isnan(curr['vol_ratio']) else 1.0
        atr = float(curr['atr']) if not np.isnan(curr['atr']) else close * 0.03

        # ----------------- 综合多因子评分系统 (满分 100 分) -----------------
        score = 0
        reasons = []

        # 1. 修正RSRS模型得分 (最高 40 分)
        if rsrs_norm >= self.buy_threshold:
            score += 40
            reasons.append(f"修正RSRS强劲超标({rsrs_norm:.2f} > {self.buy_threshold})，买方推升阻力扎实")
        elif rsrs_norm >= 0.4:
            score += 25
            reasons.append(f"RSRS指标多头偏强({rsrs_norm:.2f})")
        elif rsrs_norm > 0:
            score += 10

        # RSRS 拐点上穿加分
        if prev_rsrs_norm < self.buy_threshold and rsrs_norm >= self.buy_threshold:
            score += 5
            reasons.append("RSRS金叉放量上穿临界线，波段拐点成立")

        # 2. 均线与多头排列趋势 (最高 30 分)
        trend_score = 0
        if close > ma20:
            trend_score += 10
            if ma20_slope > 0.05:
                trend_score += 5
                reasons.append("收盘站上MA20且生命线拐头向上")
        if close > ma60:
            trend_score += 10
            reasons.append("位于MA60牛熊线之上，处于中期多头通道")
        if ma5 > ma20 and ma20 > ma60:
            trend_score += 5
            reasons.append("MA5/20/60均线多头完美发散排列")
        score += trend_score

        # 3. MACD 动能确认 (最高 15 分)
        if dif > dea:
            score += 8
            if dif > 0 and dea > 0:
                score += 4
                reasons.append("MACD位于零轴上方多头区域")
            if macd_bar > 0 and macd_bar > prev['macd_bar']:
                score += 3
                reasons.append("MACD红柱持续放大，多头动能加速")

        # 4. 成交量配合度 (最高 15 分)
        if vol_ratio >= 1.5:
            score += 15
            reasons.append(f"今日成交量明显放大(量比达 {vol_ratio:.2f})，主力资金介入")
        elif vol_ratio >= 1.1:
            score += 10
            reasons.append(f"成交量温和放大(量比 {vol_ratio:.2f})")

        # ----------------- 信号判定与评级 (结合大盘牛熊环境) -----------------
        signal_type = "HOLD" # BUY | SELL | HOLD | WATCH
        signal_desc = "震荡观望"

        # 卖出条件：RSRS跌破下限 或 严重破位MA20
        if rsrs_norm < self.sell_threshold or (close < ma20 and prev['close'] < prev['ma20']):
            signal_type = "SELL"
            signal_desc = "减仓/清仓信号"
            reasons.append(f"RSRS破位下行({rsrs_norm:.2f} < {self.sell_threshold})或跌破MA20")
        elif score >= 75 and rsrs_norm >= self.buy_threshold and close > ma20:
            if not market_regime_bull:
                # 大盘弱势熊市环境下，若未达到极高分(>=85)与量比放大，降级为观望
                if score < 85 or vol_ratio < 1.3:
                    signal_type = "WATCH"
                    signal_desc = "大盘弱势压制·观望"
                    reasons.append("大盘处于MA60牛熊线下方，防范系统性假突破风险，暂缓开仓")
                else:
                    signal_type = "BUY"
                    signal_desc = "弱市逆势高分买点"
            else:
                signal_type = "BUY"
                signal_desc = "强力波段买点(五星)"
        elif score >= 60 and rsrs_norm >= 0.4 and close > ma20:
            signal_type = "WATCH"
            signal_desc = "蓄势突破关注(四星)"

        # ----------------- 风控止损止盈点位测算 -----------------
        trade_levels = risk_manager.calculate_trade_levels(entry_price=close, atr=atr)

        return {
            "symbol": symbol,
            "name": name,
            "date": str(curr['date'])[:10],
            "price": close,
            "change_pct": round((close - float(prev['close'])) / float(prev['close']) * 100, 2),
            "signal_type": signal_type,
            "signal_desc": signal_desc,
            "score": min(score, 100),
            "rsrs_norm": round(rsrs_norm, 3),
            "rsrs_beta": round(rsrs_beta, 3),
            "rsrs_r2": round(rsrs_r2, 3),
            "vol_ratio": round(vol_ratio, 2),
            "atr": round(atr, 2),
            "ma5": round(ma5, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "reasons": reasons,
            "trade_levels": trade_levels
        }

default_strategy = RSRSMomentumStrategy()
