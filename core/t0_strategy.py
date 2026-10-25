"""
A股 T+1 底仓日内做T (Intraday T+0) 量化策略引擎
针对A股T+1规则：利用已有底仓，通过盘中分时VWAP均线偏离度与Pivot Points枢轴点，
实现“正T（低吸高抛，先买后卖）”与“倒T（高抛低吸，先卖后买）”，摊薄持仓成本，锁定日内差价收益。
集成日内做T持仓状态机（T0PositionTracker）：自动跟踪持仓、防守保护价跌破紧急止损、冲高止盈、
以及单边下跌防飞刀与止损后日内禁开正T风控。
"""
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
import pandas as pd
import numpy as np


class T0PositionTracker:
    """
    日内做T持仓状态跟踪与生命周期管理器
    保证：
    1. 单标的开仓后记录状态、建议买入价、防守保护价与目标对冲平仓价；
    2. 开仓持仓期间禁止重复盲目推送加仓买点，防范单边瀑布下跌多倍套牢；
    3. 跌破防守保护价后立即触发 STOP_T 止损，并标记 STOPPED 状态；
    4. 当日被止损破位的标的，当天全天冻结该标的正T低吸买入提示；
    5. 支持状态持久化至 storage/t0_trades.json，并在启动时从当日流水自动恢复。
    """
    def __init__(self, storage_file: Optional[Path] = None):
        if storage_file is None:
            try:
                from config import T0_TRADES_FILE
                self.storage_file = T0_TRADES_FILE
            except Exception:
                self.storage_file = Path(__file__).resolve().parent.parent / "storage" / "t0_trades.json"
        else:
            self.storage_file = storage_file

        self._trades: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        """加载持仓状态文件，如不存在则尝试从今日信号历史恢复"""
        today_str = datetime.now().strftime("%Y-%m-%d")
        loaded = False
        try:
            if self.storage_file and self.storage_file.exists():
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        # 仅保留今日有效记录
                        self._trades = {k: v for k, v in data.items() if v.get("date") == today_str}
                        loaded = len(self._trades) > 0
        except Exception as e:
            print(f"读取做T持仓文件失败: {e}")
            self._trades = {}

        if not loaded:
            self._recover_from_history()

    def _recover_from_history(self):
        """从 signals_history.json 恢复今日已有做T开仓与平仓状态"""
        try:
            from config import SIGNALS_FILE
            if not SIGNALS_FILE or not SIGNALS_FILE.exists():
                return
            with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)

            today_str = datetime.now().strftime("%Y-%m-%d")
            today_signals = [s for s in history if s.get("date") == today_str and str(s.get("signal_type", "")).startswith("T0_")]
            today_signals.reverse() # 按时间由早到晚处理

            for s in today_signals:
                sym = s.get("symbol")
                sig_type = s.get("signal_type")
                if not sym or not sig_type:
                    continue

                if sig_type in ["T0_BUY_T", "T0_SELL_T"]:
                    if sym not in self._trades or self._trades[sym].get("status") not in ["STOPPED", "PROFITED", "CLOSED"]:
                        levels = s.get("trade_levels", {})
                        entry_p = float(levels.get("entry_price") or s.get("price", 0.0))
                        stop_p = float(levels.get("initial_stop") or (entry_p * 0.985 if sig_type == "T0_BUY_T" else entry_p * 1.015))
                        target_p = float(levels.get("target_price") or (entry_p * 1.015 if sig_type == "T0_BUY_T" else entry_p * 0.985))
                        self._trades[sym] = {
                            "symbol": sym,
                            "name": s.get("name", ""),
                            "date": today_str,
                            "direction": sig_type.replace("T0_", ""),
                            "status": "OPEN",
                            "entry_price": entry_p,
                            "suggested_shares": 100,
                            "target_price": target_p,
                            "stop_price": stop_p,
                            "pivots": {},
                            "open_time": s.get("timestamp", "").split(" ")[-1] if " " in s.get("timestamp", "") else "09:30:00",
                            "close_time": None,
                            "close_price": None,
                            "close_reason": None,
                            "reasons": s.get("reasons", [])
                        }
                elif sig_type == "T0_STOP_T":
                    if sym in self._trades:
                        self._trades[sym]["status"] = "STOPPED"
                elif sig_type in ["T0_PROFIT_T", "T0_CLOSE_T"]:
                    if sym in self._trades:
                        self._trades[sym]["status"] = "CLOSED"
        except Exception as e:
            print(f"从历史信号流水恢复做T状态异常: {e}")

    def _save(self):
        """持久化持仓状态到磁盘"""
        try:
            if self.storage_file:
                self.storage_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.storage_file, "w", encoding="utf-8") as f:
                    json.dump(self._trades, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存做T持仓文件失败: {e}")

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取某只标的今日做T持仓状态"""
        today_str = datetime.now().strftime("%Y-%m-%d")
        pos = self._trades.get(symbol)
        if pos and pos.get("date") == today_str:
            return pos
        return None

    def is_stopped_today(self, symbol: str) -> bool:
        """检查今日该标的是否已触发跌破防守止损"""
        pos = self.get_position(symbol)
        return bool(pos and pos.get("status") == "STOPPED")

    def is_open_today(self, symbol: str) -> bool:
        """检查今日该标的是否有进行中的做T持仓"""
        pos = self.get_position(symbol)
        return bool(pos and pos.get("status") == "OPEN")

    def open_position(
        self,
        symbol: str,
        name: str,
        direction: str,
        entry_price: float,
        suggested_shares: int,
        target_price: float,
        stop_price: float,
        pivots: Optional[Dict[str, float]] = None,
        reasons: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """记录开立日内做T持仓"""
        today_str = datetime.now().strftime("%Y-%m-%d")
        now_time = datetime.now().strftime("%H:%M:%S")
        pos = {
            "symbol": symbol,
            "name": name,
            "date": today_str,
            "direction": direction,      # BUY_T (正T) | SELL_T (倒T)
            "status": "OPEN",            # OPEN (持仓中) | STOPPED (已止损) | PROFITED (已止盈) | CLOSED (尾盘已平)
            "entry_price": float(entry_price),
            "suggested_shares": int(suggested_shares),
            "target_price": float(target_price),
            "stop_price": float(stop_price),
            "pivots": pivots or {},
            "open_time": now_time,
            "close_time": None,
            "close_price": None,
            "close_reason": None,
            "reasons": reasons or []
        }
        self._trades[symbol] = pos
        self._save()
        return pos

    def close_position(
        self,
        symbol: str,
        status: str,
        close_price: Optional[float] = None,
        close_reason: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """平仓或止损止盈做T持仓"""
        pos = self.get_position(symbol)
        if pos:
            pos["status"] = status
            pos["close_time"] = datetime.now().strftime("%H:%M:%S")
            pos["close_price"] = float(close_price) if close_price is not None else pos.get("entry_price", 0.0)
            pos["close_reason"] = close_reason or status
            self._save()
            return pos
        return None

    def reset_position(self, symbol: str) -> bool:
        """重置某标的做T状态（供用户手动重置或测试）"""
        if symbol in self._trades:
            del self._trades[symbol]
            self._save()
            return True
        return False

    def get_all_today_positions(self) -> Dict[str, Dict[str, Any]]:
        """获取今日所有标的的做T状态字典"""
        today_str = datetime.now().strftime("%Y-%m-%d")
        return {k: v for k, v in self._trades.items() if v.get("date") == today_str}


class T0IntradayStrategy:
    def __init__(self, bias_buy_threshold: float = -1.5, bias_sell_threshold: float = 2.0):
        """
        :param bias_buy_threshold: 正T低吸分时偏离度阈值 (默认 -1.5%，即价格低于VWAP 1.5%)
        :param bias_sell_threshold: 倒T高抛分时偏离度阈值 (默认 +2.0%，即价格高于VWAP 2.0%)
        """
        self.bias_buy_threshold = bias_buy_threshold
        self.bias_sell_threshold = bias_sell_threshold
        self.stop_loss_pct = 1.5
        self.take_profit_pct = 1.5
        self.tracker = T0PositionTracker()
        self.reload_config()

    def reload_config(self):
        """动态同步日内做T配置"""
        try:
            from config import load_config
            cfg = load_config()
            self.bias_buy_threshold = cfg.get("t0_bias_buy", self.bias_buy_threshold)
            self.bias_sell_threshold = cfg.get("t0_bias_sell", self.bias_sell_threshold)
            self.stop_loss_pct = cfg.get("t0_stop_loss_pct", self.stop_loss_pct)
            self.take_profit_pct = cfg.get("t0_take_profit_pct", self.take_profit_pct)
        except Exception:
            pass

    def record_trade_open(self, t0_res: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """供调度器或通知模块确认开仓并落盘状态"""
        action = t0_res.get("t_action")
        if action not in ["BUY_T", "SELL_T"]:
            return None
        return self.tracker.open_position(
            symbol=t0_res.get("symbol", ""),
            name=t0_res.get("name", ""),
            direction=action,
            entry_price=t0_res.get("price", 0.0),
            suggested_shares=t0_res.get("suggested_shares", 100),
            target_price=t0_res.get("target_price", 0.0),
            stop_price=t0_res.get("stop_price", 0.0),
            pivots=t0_res.get("pivots", {}),
            reasons=t0_res.get("reasons", [])
        )

    def record_trade_close(
        self,
        symbol: str,
        action: str,
        price: float = 0.0,
        reason: str = ""
    ) -> Optional[Dict[str, Any]]:
        """供调度器在触发止损/止盈/尾盘平仓时确认关闭持仓"""
        status = "CLOSED"
        if "STOP" in action:
            status = "STOPPED"
        elif "PROFIT" in action:
            status = "PROFITED"
        return self.tracker.close_position(
            symbol=symbol,
            status=status,
            close_price=price,
            close_reason=reason
        )

    def reset_trade(self, symbol: str) -> bool:
        """重置某标的的做T状态"""
        return self.tracker.reset_position(symbol)

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
        分析单只股票的日内做T机会与持仓闭环监控
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

        # 检查近3-5分钟价格动量斜率
        recent_prices = minute_df['price'].tail(5).values

        # 建议做T股数：底仓的 30%~50%，至少100股，且为100的倍数
        suggested_shares = 0
        if holding_shares >= 100:
            suggested_shares = int((holding_shares * 0.4) // 100) * 100
            if suggested_shares == 0:
                suggested_shares = 100

        # 获取今日已有做T持仓状态
        existing_pos = self.tracker.get_position(symbol)

        # =========================================================================
        # 场景一：今日已触发做T跌破防守止损 (STOPPED)
        # 铁律：跌破防守线说明当日处于单边破位下跌，今日严禁再次推送正T买入！
        # =========================================================================
        if existing_pos and existing_pos.get("status") == "STOPPED":
            stop_p = existing_pos.get("stop_price", price)
            entry_p = existing_pos.get("entry_price", price)
            return {
                "symbol": symbol,
                "name": name,
                "time": curr_time,
                "price": price,
                "vwap": vwap,
                "bias": bias,
                "t_action": "STOPPED_WATCH",
                "t_type": "防守已止损 (今日不再提示买入)",
                "confidence": 0,
                "holding_shares": holding_shares,
                "entry_price": entry_p,
                "suggested_shares": existing_pos.get("suggested_shares", suggested_shares),
                "suggested_price": entry_p,
                "target_price": existing_pos.get("target_price", price),
                "stop_price": stop_p,
                "expected_spread_pct": 0.0,
                "pivots": pivots,
                "reasons": [
                    f"今日已于 {existing_pos.get('close_time', '盘中')} 跌破防守保护价({stop_p:.2f}元)触发紧急止损！",
                    "当前标的处于单边弱势破位下跌，严禁盲目左侧接飞刀，今日系统已冻结该标的正T买入提示以规避风险。"
                ],
                "t0_state": existing_pos
            }

        # =========================================================================
        # 场景二：今日已有进行中的做T持仓 (OPEN)
        # 核心监控：实时监控是否跌破防守保护价（止损）、是否触及目标价（止盈）、或尾盘强制平仓
        # 铁律：在当前做T持仓未完成对冲或未止损前，禁止重复推送同向买入开仓！
        # =========================================================================
        if existing_pos and existing_pos.get("status") == "OPEN":
            pos_dir = existing_pos.get("direction", "BUY_T")
            pos_entry = existing_pos.get("entry_price", price)
            pos_stop = existing_pos.get("stop_price", price)
            pos_target = existing_pos.get("target_price", price)
            pos_shares = existing_pos.get("suggested_shares", suggested_shares)

            if pos_dir == "BUY_T":
                # 1. 正T跌破防守保护价 -> 触发紧急止损卖出！
                if price <= pos_stop:
                    loss_pct = round((price - pos_entry) / pos_entry * 100, 2) if pos_entry > 0 else 0.0
                    return {
                        "symbol": symbol,
                        "name": name,
                        "time": curr_time,
                        "price": price,
                        "vwap": vwap,
                        "bias": bias,
                        "t_action": "STOP_T",
                        "t_type": "正T紧急止损 (跌破防守价，立即卖出底仓)",
                        "confidence": 95,
                        "holding_shares": holding_shares,
                        "entry_price": pos_entry,
                        "suggested_shares": pos_shares,
                        "suggested_price": pos_entry,
                        "target_price": pos_target,
                        "stop_price": pos_stop,
                        "expected_spread_pct": loss_pct,
                        "pivots": pivots,
                        "reasons": [
                            f"分时现价({price:.2f}元) 跌破日内做T防守保护价({pos_stop:.2f}元)！",
                            f"建议买入参考价 {pos_entry:.2f}元，当前破位幅度 {loss_pct:+.2f}%",
                            f"⚠️ 为防范单边瀑布下跌造成底仓深度套牢，请立即按现价卖出等量底仓（{pos_shares}股）果断对冲止损！",
                            "⚠️ 跌破防守线说明日内处于单边破位弱势，今日系统已冻结该标的正T买入提示，严禁逆势补仓！"
                        ],
                        "t0_state": existing_pos
                    }
                # 2. 正T冲高触达目标价 -> 触发止盈对冲卖出！
                elif price >= pos_target:
                    gain_pct = round((price - pos_entry) / pos_entry * 100, 2) if pos_entry > 0 else 0.0
                    return {
                        "symbol": symbol,
                        "name": name,
                        "time": curr_time,
                        "price": price,
                        "vwap": vwap,
                        "bias": bias,
                        "t_action": "PROFIT_T",
                        "t_type": "正T冲高止盈 (达到目标价，卖出底仓锁定利润)",
                        "confidence": 90,
                        "holding_shares": holding_shares,
                        "entry_price": pos_entry,
                        "suggested_shares": pos_shares,
                        "suggested_price": pos_entry,
                        "target_price": pos_target,
                        "stop_price": pos_stop,
                        "expected_spread_pct": gain_pct,
                        "pivots": pivots,
                        "reasons": [
                            f"分时现价({price:.2f}元) 冲高触达预期目标平仓价({pos_target:.2f}元)！",
                            f"日内做T差价已兑现：收益率达到 +{gain_pct}%",
                            f"🎯 请立即在交易软件中卖出等量底仓（{pos_shares}股），锁定日内价差收益，保持总持股数不变！"
                        ],
                        "t0_state": existing_pos
                    }
                # 3. 尾盘强制平仓窗口 (14:35 - 14:55)
                elif "14:35" <= curr_time <= "14:55":
                    return {
                        "symbol": symbol,
                        "name": name,
                        "time": curr_time,
                        "price": price,
                        "vwap": vwap,
                        "bias": bias,
                        "t_action": "CLOSE_T",
                        "t_type": "尾盘平仓 (今日做T对冲平仓窗口)",
                        "confidence": 90,
                        "holding_shares": holding_shares,
                        "entry_price": pos_entry,
                        "suggested_shares": pos_shares,
                        "suggested_price": pos_entry,
                        "target_price": pos_target,
                        "stop_price": pos_stop,
                        "expected_spread_pct": round((price - pos_entry) / pos_entry * 100, 2) if pos_entry > 0 else 0.0,
                        "pivots": pivots,
                        "reasons": [
                            f"当前时间已到达 {curr_time}，临近收盘强制平仓窗口！",
                            f"已有日内做T单（建议买入价 {pos_entry:.2f}元，现价 {price:.2f}元），请于 14:50 前按现价卖出等量底仓（{pos_shares}股）完成平仓！",
                            "严格执行 A股 T+1 纪律，严禁做T变加仓留仓过夜！"
                        ],
                        "t0_state": existing_pos
                    }
                # 4. 处于正常持仓波动区间中
                else:
                    float_pct = round((price - pos_entry) / pos_entry * 100, 2) if pos_entry > 0 else 0.0
                    return {
                        "symbol": symbol,
                        "name": name,
                        "time": curr_time,
                        "price": price,
                        "vwap": vwap,
                        "bias": bias,
                        "t_action": "IN_POSITION",
                        "t_type": "正T持仓监控中 (等待冲高平仓或破位防守)",
                        "confidence": 60,
                        "holding_shares": holding_shares,
                        "entry_price": pos_entry,
                        "suggested_shares": pos_shares,
                        "suggested_price": pos_entry,
                        "target_price": pos_target,
                        "stop_price": pos_stop,
                        "expected_spread_pct": float_pct,
                        "pivots": pivots,
                        "reasons": [
                            f"日内做T持仓中：入场参考 {pos_entry:.2f}元，目标止盈 {pos_target:.2f}元，防守止损 {pos_stop:.2f}元",
                            f"当前现价 {price:.2f}元 (浮动盈亏: {float_pct:+.2f}%)，维持纪律等待点位到达，严禁中途重复加仓！"
                        ],
                        "t0_state": existing_pos
                    }

            else:  # 倒T (SELL_T)
                # 1. 倒T突破压力防守线 -> 触发买回止损！
                if price >= pos_stop:
                    loss_pct = round((pos_entry - price) / pos_entry * 100, 2) if pos_entry > 0 else 0.0
                    return {
                        "symbol": symbol,
                        "name": name,
                        "time": curr_time,
                        "price": price,
                        "vwap": vwap,
                        "bias": bias,
                        "t_action": "STOP_T",
                        "t_type": "倒T紧急止损 (突破压力位，立即买回底仓)",
                        "confidence": 95,
                        "holding_shares": holding_shares,
                        "entry_price": pos_entry,
                        "suggested_shares": pos_shares,
                        "suggested_price": pos_entry,
                        "target_price": pos_target,
                        "stop_price": pos_stop,
                        "expected_spread_pct": loss_pct,
                        "pivots": pivots,
                        "reasons": [
                            f"分时现价({price:.2f}元) 突破日内倒T防守压力位({pos_stop:.2f}元)！",
                            f"高抛参考价 {pos_entry:.2f}元，当前突破幅度 {loss_pct:+.2f}%",
                            f"⚠️ 为防底仓被大幅抛飞，请立即在交易软件中按现价买回等量股份（{pos_shares}股）对冲止损！"
                        ],
                        "t0_state": existing_pos
                    }
                # 2. 倒T回踩目标位 -> 触发买回止盈！
                elif price <= pos_target:
                    gain_pct = round((pos_entry - price) / pos_entry * 100, 2) if pos_entry > 0 else 0.0
                    return {
                        "symbol": symbol,
                        "name": name,
                        "time": curr_time,
                        "price": price,
                        "vwap": vwap,
                        "bias": bias,
                        "t_action": "PROFIT_T",
                        "t_type": "倒T回踩止盈 (达到目标低位，买回底仓锁定收益)",
                        "confidence": 90,
                        "holding_shares": holding_shares,
                        "entry_price": pos_entry,
                        "suggested_shares": pos_shares,
                        "suggested_price": pos_entry,
                        "target_price": pos_target,
                        "stop_price": pos_stop,
                        "expected_spread_pct": gain_pct,
                        "pivots": pivots,
                        "reasons": [
                            f"分时现价({price:.2f}元) 回踩触达日内低吸目标价({pos_target:.2f}元)！",
                            f"倒T差价已兑现：收益率达到 +{gain_pct}%",
                            f"🎯 请立即在交易软件中低吸买回等量股份（{pos_shares}股），收复老底仓并锁定日内差价利润！"
                        ],
                        "t0_state": existing_pos
                    }
                # 3. 尾盘平仓 (14:35 - 14:55)
                elif "14:35" <= curr_time <= "14:55":
                    return {
                        "symbol": symbol,
                        "name": name,
                        "time": curr_time,
                        "price": price,
                        "vwap": vwap,
                        "bias": bias,
                        "t_action": "CLOSE_T",
                        "t_type": "尾盘平仓 (今日做T对冲平仓窗口)",
                        "confidence": 90,
                        "holding_shares": holding_shares,
                        "entry_price": pos_entry,
                        "suggested_shares": pos_shares,
                        "suggested_price": pos_entry,
                        "target_price": pos_target,
                        "stop_price": pos_stop,
                        "expected_spread_pct": round((pos_entry - price) / pos_entry * 100, 2) if pos_entry > 0 else 0.0,
                        "pivots": pivots,
                        "reasons": [
                            f"当前时间已到达 {curr_time}，临近收盘强制买回平仓窗口！",
                            f"已有倒T卖单（高抛价 {pos_entry:.2f}元，现价 {price:.2f}元），请于 14:50 前买回等量股份（{pos_shares}股）！"
                        ],
                        "t0_state": existing_pos
                    }
                else:
                    float_pct = round((pos_entry - price) / pos_entry * 100, 2) if pos_entry > 0 else 0.0
                    return {
                        "symbol": symbol,
                        "name": name,
                        "time": curr_time,
                        "price": price,
                        "vwap": vwap,
                        "bias": bias,
                        "t_action": "IN_POSITION",
                        "t_type": "倒T持仓监控中 (等待回踩低吸买回或突破防守)",
                        "confidence": 60,
                        "holding_shares": holding_shares,
                        "entry_price": pos_entry,
                        "suggested_shares": pos_shares,
                        "suggested_price": pos_entry,
                        "target_price": pos_target,
                        "stop_price": pos_stop,
                        "expected_spread_pct": float_pct,
                        "pivots": pivots,
                        "reasons": [
                            f"日内倒T持仓中：高抛参考 {pos_entry:.2f}元，回踩目标 {pos_target:.2f}元，突破防守 {pos_stop:.2f}元",
                            f"当前现价 {price:.2f}元 (浮动收益: {float_pct:+.2f}%)，维持纪律等待低吸买回点位。"
                        ],
                        "t0_state": existing_pos
                    }

        # =========================================================================
        # 场景三：今日暂无进行中的做T持仓 (IDLE) - 研判新开仓机会
        # =========================================================================
        t_action = "NONE"       # BUY_T (正T低吸) | SELL_T (倒T高抛) | CLOSE_T (平仓) | WATCH (观望)
        t_type = "NONE"         # 正T / 倒T
        reasons = []
        confidence = 0          # 0-100 置信度

        # 0. 做T时间窗口严控
        can_open_new_t = "09:40" <= curr_time <= "14:15"

        # 检查是否单边瀑布跳水 (Falling Knife) 绝不可接飞刀
        is_falling_knife = False
        if len(recent_prices) >= 4:
            # 连续4根K线单边下跌且现价几乎贴合日内最低点
            is_monotonic_falling = (recent_prices[-1] < recent_prices[-2] < recent_prices[-3] < recent_prices[-4])
            if is_monotonic_falling and price <= low * 1.001:
                is_falling_knife = True

        # 止跌反弹确认：近2分钟价格不再创新低，并出现企稳拐头迹象
        has_rebound = len(recent_prices) >= 3 and (recent_prices[-1] >= recent_prices[-2] or recent_prices[-1] > min(recent_prices))

        # 1. 正T信号检测（先买后卖，低吸高抛）
        if can_open_new_t and not is_falling_knife and (bias <= self.bias_buy_threshold or (price <= pivots['s1'] and bias < -0.8)):
            confidence += 40
            reasons.append(f"价格深度负偏离均线VWAP({vwap:.2f}元)，偏离度达到 {bias:.2f}% (超买超卖负极值)")

            if price <= pivots['s1']:
                confidence += 25
                reasons.append(f"价格触及日内S1关键支撑位({pivots['s1']:.2f}元)")

            if has_rebound:
                confidence += 25
                reasons.append("分时探底企稳，近2-3分钟出现止跌拐头企稳回升迹象")

            if confidence >= 65:
                t_action = "BUY_T"
                t_type = "正T (先低吸买入，冲高后卖出等量底仓)"

        # 2. 倒T信号检测（先卖后买，高抛低吸）
        elif can_open_new_t and (bias >= self.bias_sell_threshold or (price >= pivots['r1'] and bias > 1.0)):
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

        # 3. 尾盘安全强制平仓窗口（14:35 - 14:55）
        elif "14:35" <= curr_time <= "14:55" and holding_shares >= 100:
            t_action = "CLOSE_T"
            t_type = "尾盘平仓 (今日做T对冲平仓窗口)"
            confidence = 90
            reasons.append(f"当前时间已到达 {curr_time}，临近收盘强制平仓窗口！")
            reasons.append("为遵守A股T+1纪律，防止做T变套牢，请于14:50前完成等量对冲平仓，严格保持收盘持股数不变！")

        elif not can_open_new_t and curr_time > "14:15":
            reasons.append(f"当前时间已过 14:15 (当前 {curr_time})，做T窗口关闭，不再触发新开仓以规避尾盘无法平仓风险。")

        # 计算做T目标位与防守止损位
        stop_pct = self.stop_loss_pct / 100.0
        profit_pct = self.take_profit_pct / 100.0
        target_price = price
        stop_price = price
        expected_spread_pct = 0.0

        if t_action == "BUY_T":
            # 正T目标：回抽VWAP均价线或按目标比例
            target_price = round(max(vwap, price * (1.0 + profit_pct)), 2)
            # 正T防守止损：跌破S2支撑或最大容忍防守比例 (默认1.5%)
            stop_price = round(min(pivots['s2'], price * (1.0 - stop_pct)), 2)
            expected_spread_pct = round((target_price - price) / price * 100, 2)
        elif t_action == "SELL_T":
            # 倒T目标：回踩VWAP均线或按目标比例
            target_price = round(min(vwap, price * (1.0 - profit_pct)), 2)
            # 倒T防守止损：突破R2压力或最大容忍止损比例 (默认1.5%)
            stop_price = round(max(pivots['r2'], price * (1.0 + stop_pct)), 2)
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
            "reasons": reasons,
            "t0_state": existing_pos
        }


t0_strategy = T0IntradayStrategy()
