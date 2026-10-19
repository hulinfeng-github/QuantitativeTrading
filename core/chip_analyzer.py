"""
A股主力筹码分布与主力控盘成本分析引擎 (Smart Money & Chip Accumulation Engine)
基于经典 CYQ 换手率衰减模型、Smart Money 密集吸筹 VWAP 与筹码集中度，
精准测算主力建仓成本、获利盘比例与主力控盘生命周期（吸筹/起爆/锁仓/派发）。
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List

class ChipCostAnalyzer:
    def __init__(self, lookback_days: int = 120, price_bins: int = 100):
        """
        :param lookback_days: 筹码回溯历史天数（通常取过去 120 个交易日，约半年筹码周期）
        :param price_bins: 筹码价格网格刻度数
        """
        self.lookback_days = lookback_days
        self.price_bins = price_bins

    def analyze_chips(self, df: pd.DataFrame, current_price: Optional[float] = None) -> Dict[str, Any]:
        """
        全量计算单只标的的筹码分布、主力平均建仓成本、获利比例及控盘生命周期
        :param df: 历史日K线 DataFrame (包含 open, high, low, close, volume)
        :param current_price: 最新现价（若为空则使用最后一根K线收盘价）
        :return: 筹码与主力成本结构体
        """
        if df is None or len(df) < 20:
            return self._empty_result(current_price or 0.0)

        data = df.tail(self.lookback_days).copy()
        if current_price is None or current_price <= 0:
            current_price = float(data.iloc[-1]['close'])

        # 1. 价格网格区间确定
        min_p = float(data['low'].min()) * 0.98
        max_p = float(data['high'].max()) * 1.02
        if max_p <= min_p or np.isnan(min_p) or np.isnan(max_p):
            return self._empty_result(current_price)

        bin_edges = np.linspace(min_p, max_p, self.price_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
        chip_density = np.zeros(self.price_bins)

        # 2. 估计每日换手率与筹码衰减迁移 (CYQ 核心模拟)
        median_vol = data['volume'].median()
        if median_vol <= 0:
            median_vol = 1.0

        for _, row in data.iterrows():
            c_high = float(row['high'])
            c_low = float(row['low'])
            c_close = float(row['close'])
            c_open = float(row['open'])
            c_vol = float(row['volume'])

            if c_high <= c_low or c_vol <= 0:
                continue

            # 估算当日有效换手衰减率 (日均基础换手约 2.0%，随量比动态浮动，限制在 0.5% ~ 15%)
            turnover_est = np.clip((c_vol / median_vol) * 0.025, 0.005, 0.15)

            # 历史筹码换手衰减
            chip_density *= (1.0 - turnover_est)

            # 当日新生成筹码分布在 [c_low, c_high] 之间，使用三角分布模拟（重心在 (open+close+high+low)/4）
            mid_val = (c_open + c_close + c_high + c_low) / 4.0
            mask = (bin_centers >= c_low) & (bin_centers <= c_high)
            
            if np.any(mask):
                # 越接近均值重心，筹码密度权重越高
                spread = max(c_high - c_low, 1e-4)
                dists = 1.0 - np.abs(bin_centers[mask] - mid_val) / spread
                weights = np.maximum(dists, 0.1)
                norm_weights = weights / (weights.sum() + 1e-8)
                chip_density[mask] += turnover_est * norm_weights

        total_chips = chip_density.sum()
        if total_chips <= 0:
            return self._empty_result(current_price)

        chip_density /= total_chips # 归一化

        # 3. 计算筹码主峰价格 (单峰密集最高点)
        peak_idx = int(np.argmax(chip_density))
        chip_peak_price = round(float(bin_centers[peak_idx]), 2)

        # 4. 计算当前全盘获利比例 (Profit Ratio)
        profit_mask = bin_centers <= current_price
        profit_chip_ratio = round(float(chip_density[profit_mask].sum()) * 100, 2)

        # 5. 计算 70% 与 90% 筹码集中度
        cumsum = np.cumsum(chip_density)
        # 70% 筹码集中区间 (15% ~ 85%)
        p15_idx = np.searchsorted(cumsum, 0.15)
        p85_idx = np.searchsorted(cumsum, 0.85)
        p15 = bin_centers[min(p15_idx, len(bin_centers) - 1)]
        p85 = bin_centers[min(p85_idx, len(bin_centers) - 1)]
        concentration_70 = round(float((p85 - p15) / (p85 + p15 + 1e-6)) * 100, 2)

        # 90% 筹码集中区间 (5% ~ 95%)
        p05_idx = np.searchsorted(cumsum, 0.05)
        p95_idx = np.searchsorted(cumsum, 0.95)
        p05 = bin_centers[min(p05_idx, len(bin_centers) - 1)]
        p95 = bin_centers[min(p95_idx, len(bin_centers) - 1)]
        concentration_90 = round(float((p95 - p05) / (p95 + p05 + 1e-6)) * 100, 2)

        # 6. 计算主力特征吸筹加权成本 (Smart Money Accumulation VWAP)
        # 重点提取过去 60 天内阳线放量、大资金吸筹特征日的 VWAP
        smart_data = data.tail(60).copy()
        vol_ma = smart_data['volume'].rolling(5).mean()
        
        weights = []
        typical_prices = []
        for i, row in smart_data.iterrows():
            c = float(row['close'])
            o = float(row['open'])
            h = float(row['high'])
            l = float(row['low'])
            v = float(row['volume'])
            
            # 放量阳线加权（说明主力真金白银推升拿货）
            v_ratio = v / (vol_ma.loc[i] + 1e-6) if i in vol_ma and not np.isnan(vol_ma.loc[i]) else 1.0
            is_bull = c >= o
            w = v * (1.5 if is_bull else 0.7) * (1.3 if v_ratio > 1.2 else 1.0)
            
            typical_p = (h + l + c * 2) / 4.0
            weights.append(w)
            typical_prices.append(typical_p)

        sum_w = sum(weights)
        if sum_w > 0:
            smart_vwap = sum(p * w for p, w in zip(typical_prices, weights)) / sum_w
        else:
            smart_vwap = current_price

        # 7. 综合评定主力持仓成本 (筹码主峰与资金加权 VWAP 综合加权)
        main_cost = round(0.55 * chip_peak_price + 0.45 * smart_vwap, 2)

        # 8. 主力控盘状态与安全边际研判
        bias_to_main = round(((current_price - main_cost) / main_cost) * 100, 2)
        
        control_status, safety_score, advice = self._evaluate_lifecycle(
            current_price=current_price,
            main_cost=main_cost,
            bias=bias_to_main,
            profit_ratio=profit_chip_ratio,
            conc70=concentration_70
        )

        return {
            "current_price": float(round(float(current_price), 2)),
            "main_cost": float(round(float(main_cost), 2)),
            "chip_peak_price": float(round(float(chip_peak_price), 2)),
            "bias_to_main": float(round(float(bias_to_main), 2)),
            "profit_chip_ratio": float(round(float(profit_chip_ratio), 2)),
            "concentration_70": float(round(float(concentration_70), 2)),
            "concentration_90": float(round(float(concentration_90), 2)),
            "chip_support_lower": float(round(float(p15), 2)),
            "chip_resistance_upper": float(round(float(p85), 2)),
            "control_status": str(control_status),
            "safety_score": int(safety_score),
            "action_advice": str(advice)
        }

    @staticmethod
    def _evaluate_lifecycle(
        current_price: float,
        main_cost: float,
        bias: float,
        profit_ratio: float,
        conc70: float
    ) -> (str, int, str):
        """
        研判主力操盘生命周期阶段与操作建议
        """
        # 1. 突破主力成本起爆 (黄金主升浪点)
        if 2.0 <= bias <= 12.0 and profit_ratio >= 70.0:
            status = "主力突破起爆"
            score = 95
            advice = "股价刚突破主力建仓成本，获利盘超70%抛压极轻，主力必须向上拉出利润空间，确定性最强！"

        # 2. 底部主力吸筹蓄势 (安全垫极厚)
        elif -3.0 <= bias < 2.0 and conc70 <= 13.0:
            status = "主力吸筹蓄势"
            score = 90
            advice = "筹码呈低位单峰高度密集，主力完成底仓收集，向下有主力成本坚决护盘，安全边际极高。"

        # 3. 稳健主升锁仓拉升
        elif 12.0 < bias <= 30.0 and profit_ratio >= 80.0:
            status = "主力锁仓主升"
            score = 80
            advice = "主力大幅控盘锁仓，趋势多头强劲，建议紧跟 MA5/MA20 移动止盈，顺势吃足波段大肉。"

        # 4. 主力高位派发风险 (谨防接盘)
        elif bias > 35.0 or (bias > 25.0 and conc70 > 18.0):
            status = "主力高位派发风险"
            score = 30
            advice = f"股价已脱离主力成本 {bias:+.1f}%，主力获利丰厚随时可能借利好出货，严禁盲目追高给庄家接盘！"

        # 5. 跌破主力成本破位 (主力护盘失败或出逃)
        elif bias < -6.0:
            status = "破位主力被套"
            score = 40
            advice = "价格跌破主力底仓密集支撑区，主力护盘乏力或选择割肉，趋势走弱，防范阴跌风险。"

        # 6. 普通震荡
        else:
            status = "区间震荡洗盘"
            score = 65
            advice = f"现价较主力成本偏离 {bias:+.1f}%，筹码正在换手重组，保持跟踪观察突破信号。"

        return status, score, advice

    @staticmethod
    def _empty_result(price: float) -> Dict[str, Any]:
        return {
            "current_price": price,
            "main_cost": price,
            "chip_peak_price": price,
            "bias_to_main": 0.0,
            "profit_chip_ratio": 50.0,
            "concentration_70": 15.0,
            "concentration_90": 25.0,
            "chip_support_lower": price,
            "chip_resistance_upper": price,
            "control_status": "数据不足",
            "safety_score": 50,
            "action_advice": "历史K线数据不足，暂未形成完整筹码模型。"
        }

chip_analyzer = ChipCostAnalyzer()
