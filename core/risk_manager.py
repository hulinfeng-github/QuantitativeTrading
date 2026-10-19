"""
风控与动态止损止盈管理模块
支持：基于ATR的自适应波动止损、保本止损与最高价回撤移动止盈（Trailing Stop）
"""
from typing import Dict, Any, Optional

class RiskManager:
    @staticmethod
    def calculate_trade_levels(entry_price: float, atr: float, stop_multiplier: float = 2.0, target_rr: float = 2.5) -> Dict[str, float]:
        """
        计算交易风控点位（入场价、建议止损位、目标止盈位）
        :param entry_price: 买入参考价
        :param atr: 当前日线ATR值
        :param stop_multiplier: 止损ATR倍数，默认2.0
        :param target_rr: 盈亏比（Risk/Reward Ratio），默认2.5
        :return: 包含 initial_stop, stop_pct, target_price, reward_pct 的字典
        """
        stop_dist = max(atr * stop_multiplier, entry_price * 0.03) # 至少3%缓冲区
        initial_stop = max(round(entry_price - stop_dist, 2), 0.01)
        stop_pct = round((entry_price - initial_stop) / entry_price * 100, 2)
        
        target_dist = stop_dist * target_rr
        target_price = round(entry_price + target_dist, 2)
        reward_pct = round((target_price - entry_price) / entry_price * 100, 2)
        
        return {
            "entry_price": entry_price,
            "initial_stop": initial_stop,
            "stop_pct": stop_pct,
            "target_price": target_price,
            "reward_pct": reward_pct,
            "risk_reward_ratio": target_rr
        }

    @staticmethod
    def evaluate_holding_risk(
        entry_price: float,
        current_price: float,
        highest_price: float,
        initial_stop: float,
        trailing_stop_pct: float = 0.06,
        breakeven_trigger_pct: float = 0.035
    ) -> Dict[str, Any]:
        """
        持仓动态风控评估
        :param entry_price: 建仓价格
        :param current_price: 当前最新价
        :param highest_price: 建仓以来的最高价
        :param initial_stop: 初始止损位
        :param trailing_stop_pct: 最高价回撤容忍度（默认6%）
        :param breakeven_trigger_pct: 保本止损触发门槛（默认3.5%，达到后止损提至微盈覆盖手续费）
        """
        current_profit_pct = (current_price - entry_price) / entry_price * 100
        max_profit_pct = (highest_price - entry_price) / entry_price * 100
        
        # 初始默认止损位
        effective_stop = initial_stop
        dynamic_stop = initial_stop
        
        # 阶梯风控1：若最高盈利曾触及保本门槛(默认+5.0%)，止损位立即强制抬升至成本保本线（+0.3%覆盖手续费）
        if max_profit_pct >= (breakeven_trigger_pct * 100):
            effective_stop = max(effective_stop, entry_price * 1.003)
            
        # 阶梯风控2：移动止盈激活门槛（最高盈利必须至少达到 6.0% 才允许启动移动止盈，杜绝建仓即回撤误触发）
        trailing_activation_pct = max(trailing_stop_pct * 100, 6.0)
        if max_profit_pct >= trailing_activation_pct:
            dynamic_stop = highest_price * (1 - trailing_stop_pct)
            effective_stop = max(effective_stop, entry_price * 1.003, dynamic_stop)
            
        is_stop_triggered = current_price <= effective_stop
        trigger_reason = ""
        if is_stop_triggered:
            if max_profit_pct >= trailing_activation_pct and effective_stop == dynamic_stop:
                trigger_reason = f"从最高价 {highest_price:.2f} 回撤超过 {trailing_stop_pct*100:.1f}% 触发移动止盈"
            elif max_profit_pct >= (breakeven_trigger_pct * 100) and current_price <= entry_price * 1.005:
                trigger_reason = "触及保本止损线(保护本金)"
            else:
                trigger_reason = "触及初始硬止损线"

        return {
            "current_profit_pct": round(current_profit_pct, 2),
            "max_profit_pct": round(max_profit_pct, 2),
            "effective_stop": round(effective_stop, 2),
            "is_stop_triggered": is_stop_triggered,
            "trigger_reason": trigger_reason
        }

risk_manager = RiskManager()
