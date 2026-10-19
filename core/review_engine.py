"""
A股主板收盘量化复盘与自我迭代优化引擎 (ReviewEngine)
核心职责：
1. 大盘大势量化定性：跟踪上证指数/沪深300均线、量比、牛熊生命线，判定宏观周期与适宜仓位；
2. 自选持仓深度体检：复盘当前持仓收盘盈亏、乖离度、止损/移动止盈安全边际；
3. 历史信号回访追踪：对过去1~10日系统给出的BUY和做T信号进行客观追踪，统计近端实盘胜率；
4. 自我迭代优化(Self-Tuning)：根据近期胜率与大盘环境动态微调策略准入门槛与风控参数，形成优化流水。
"""
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from config import DATA_DIR, load_config, save_config, SIGNALS_FILE, WATCHLIST_FILE
from core.data_fetcher import data_fetcher
from core.strategy import default_strategy
from core.risk_manager import risk_manager

REVIEW_FILE = DATA_DIR / "review_history.json"
OPTIMIZATION_FILE = DATA_DIR / "optimization_log.json"

class ReviewEngine:
    def __init__(self):
        pass

    def run_daily_review(self, auto_optimize: bool = True) -> Dict[str, Any]:
        """
        执行每日收盘全景量化复盘与自迭代
        :param auto_optimize: 是否根据复盘结果自动迭代调优系统参数
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        now_time = datetime.now().strftime("%H:%M:%S")

        print(f"[{now_time}] 启动收盘量化复盘分析...")

        # 1. 大盘大势量化复盘
        market_analysis = self._analyze_market_indices()

        # 2. 持仓与自选股收盘体检
        watchlist_review = self._review_watchlist()

        # 3. 历史推荐信号追踪与胜率核算
        signal_tracking = self._track_recent_signals(days_window=10)

        # 4. 执行自我迭代优化计算
        optimization_result = self._self_optimize_parameters(
            market_regime=market_analysis.get("regime", "震荡"),
            win_rate=signal_tracking.get("win_rate", 50.0),
            apply_changes=auto_optimize
        )

        # 5. 组装 Markdown 格式的完整复盘报告
        report_md = self._build_markdown_report(
            today_str=today_str,
            market=market_analysis,
            watchlist=watchlist_review,
            tracking=signal_tracking,
            opt=optimization_result
        )

        review_data = {
            "date": today_str,
            "timestamp": f"{today_str} {now_time}",
            "market_analysis": market_analysis,
            "watchlist_review": watchlist_review,
            "signal_tracking": signal_tracking,
            "optimization": optimization_result,
            "report_markdown": report_md
        }

        # 6. 持久化存储
        self._save_review_record(review_data)

        return review_data

    def _calc_index_status(self, name: str, symbol: str, df: Optional[pd.DataFrame]) -> Optional[Dict[str, Any]]:
        if df is None or len(df) < 30:
            return None
        df = df.copy()
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma60'] = df['close'].rolling(min(60, len(df))).mean()
        curr = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else curr
        close = float(curr['close'])
        prev_close = float(prev['close']) if float(prev['close']) > 0 else close
        change_pct = round((close - prev_close) / prev_close * 100, 2)
        ma20 = float(curr['ma20']) if not np.isnan(curr['ma20']) else close
        ma60 = float(curr['ma60']) if not np.isnan(curr['ma60']) else ma20

        bull_count = 0
        if close > ma20: bull_count += 1
        if close > ma60: bull_count += 1
        if ma20 > ma60: bull_count += 1

        ma_status = "多头排列" if bull_count >= 2 else ("多空纠缠" if bull_count == 1 else "空头受阻")
        
        # 量比评估 (取近5日成交量均值比)
        vol_curr = float(curr.get('volume', 1.0))
        vol_ma5 = float(df['volume'].tail(5).mean()) if 'volume' in df.columns else vol_curr
        vol_ratio = round(vol_curr / vol_ma5, 2) if vol_ma5 > 0 else 1.0
        vol_status = "明显放量" if vol_ratio >= 1.2 else ("缩量观望" if vol_ratio <= 0.8 else "温和放量")

        health = "强势波段" if close > ma20 else ("生命线纠缠" if abs(close - ma20)/ma20 < 0.015 else "弱势整理")

        return {
            "name": name,
            "symbol": symbol,
            "close": close,
            "change_pct": change_pct,
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "ma_status": ma_status,
            "vol_ratio": vol_ratio,
            "vol_status": vol_status,
            "is_above_ma20": close > ma20,
            "is_above_ma60": close > ma60,
            "bull_count": bull_count,
            "health": health
        }

    def _analyze_market_indices(self) -> Dict[str, Any]:
        """复盘上证指数(sh000001)与沪深300(sh000300)"""
        results = {
            "sh_index": {},
            "hs300": {},
            "indices": {},
            "regime": "结构震荡",
            "regime_desc": "大盘方向未明，多空博弈",
            "suggested_position_pct": 50,
            "suggested_position": "5成左右",
            "max_position_pct": 50,
            "summary": ""
        }

        # 分析上证指数
        sh_df = data_fetcher.get_daily_kline("sh000001", count=100)
        sh_data = self._calc_index_status("上证指数", "sh000001", sh_df)
        if sh_data:
            results["sh_index"] = sh_data
            results["indices"]["sh000001"] = sh_data

        # 分析沪深300
        hs_df = data_fetcher.get_daily_kline("sh000300", count=100)
        hs_data = self._calc_index_status("沪深300", "sh000300", hs_df)
        if hs_data:
            results["hs300"] = hs_data
            results["indices"]["sh000300"] = hs_data

        # 综合定性
        bull_score = 0
        if sh_data:
            bull_score += sh_data.get("bull_count", 0)
        if hs_data:
            bull_score += hs_data.get("bull_count", 0)

        if bull_score >= 4:
            regime = "强势多头"
            regime_desc = "主要指数站稳MA20生命线与MA60牛熊线上方，处于主升多头通道"
            pos_pct = 70
        elif bull_score >= 2:
            regime = "结构震荡"
            regime_desc = "均线交织纠缠，板块轮动分化，以低吸高抛波段防御为主"
            pos_pct = 40
        else:
            regime = "弱势空头"
            regime_desc = "指数受制于MA20与MA60生命线下方，空头压制明显，防守第一"
            pos_pct = 20

        results["regime"] = regime
        results["regime_desc"] = regime_desc
        results["suggested_position_pct"] = pos_pct
        results["suggested_position"] = f"{pos_pct}%左右"
        results["max_position_pct"] = pos_pct

        return results

    def _review_watchlist(self) -> Dict[str, Any]:
        """持仓与自选收盘全景体检"""
        items = []
        if WATCHLIST_FILE.exists():
            try:
                with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                    items = json.load(f)
            except Exception:
                pass

        cfg = load_config()
        trailing_pct = cfg.get("trailing_stop_pct", 0.06)

        if not items:
            return {
                "holding_count": 0, "holdings_count": 0,
                "total_market_value": 0, "total_market_val": 0,
                "total_floating_pnl": 0, "total_profit": 0,
                "stocks": [], "holdings": []
            }

        symbols = [it["symbol"] for it in items]
        quotes = data_fetcher.get_realtime_quotes(symbols)

        holdings_list = []
        total_market_val = 0.0
        total_profit = 0.0

        for it in items:
            sym = it["symbol"]
            name = it.get("name", sym)
            entry = float(it.get("entry_price", 0.0) or 0.0)
            shares = int(it.get("shares", 0) or 0)
            quote = quotes.get(sym, {})
            curr_price = float(quote.get("price", entry))
            change_pct = float(quote.get("change_pct", 0.0))

            pnl_pct = round((curr_price - entry) / entry * 100, 2) if entry > 0 else 0.0
            pnl_dollar = round((curr_price - entry) * shares, 2) if (entry > 0 and shares > 0) else 0.0
            market_val = round(curr_price * shares, 2)

            if shares > 0:
                total_market_val += market_val
                total_profit += pnl_dollar

            # 防守位测算
            stop_loss_price = round(entry * 0.92, 2) if entry > 0 else round(curr_price * 0.92, 2)
            stop_loss_margin = round((curr_price - stop_loss_price) / curr_price * 100, 1) if curr_price > 0 else 0.0
            trailing_stop_price = round(curr_price * (1 - trailing_pct), 2)
            trailing_stop_margin = round(trailing_pct * 100, 1)

            # 判断均线健康度
            health_status = "正常"
            health_action = "持有观察"
            if pnl_pct < -8.0:
                health_status = "⚠️ 深度套牢"
                health_action = "严禁盲目加仓，等待反弹做T或破位减仓"
            elif pnl_pct > 6.0:
                health_status = "🔥 强势浮盈"
                health_action = "锁定保本线，启动移动止盈跟踪"
            elif pnl_pct >= 0:
                health_status = "✅ 微利健康"
                health_action = "依托MA20生命线安心持有"
            else:
                health_status = "📉 正常轻套"
                health_action = "关注日内负偏离正T机会"

            holdings_list.append({
                "symbol": sym,
                "name": name,
                "entry_price": entry,
                "close": curr_price,
                "close_price": curr_price,
                "change_pct": change_pct,
                "shares": shares,
                "profit_pct": pnl_pct,
                "pnl_pct": pnl_pct,
                "profit_amount": pnl_dollar,
                "pnl_dollar": pnl_dollar,
                "market_val": market_val,
                "stop_loss_price": stop_loss_price,
                "stop_loss_margin_pct": stop_loss_margin,
                "trailing_stop_price": trailing_stop_price,
                "trailing_stop_margin_pct": trailing_stop_margin,
                "advice": health_action,
                "health_status": health_status,
                "health_action": health_action
            })

        count = len([h for h in holdings_list if h["shares"] > 0])
        return {
            "holding_count": count,
            "holdings_count": count,
            "total_market_value": round(total_market_val, 2),
            "total_market_val": round(total_market_val, 2),
            "total_floating_pnl": round(total_profit, 2),
            "total_profit": round(total_profit, 2),
            "stocks": holdings_list,
            "holdings": holdings_list
        }

    def _track_recent_signals(self, days_window: int = 10) -> Dict[str, Any]:
        """追踪回访最近N个交易日发出的买入与做T信号表现"""
        if not SIGNALS_FILE.exists():
            return {
                "tracked_count": 0, "total_audited": 0,
                "win_rate": 50.0, "avg_gain": 0.0, "avg_profit_pct": 0.0,
                "signals": [], "audited_signals": []
            }

        try:
            with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
                all_signals = json.load(f)
        except Exception:
            return {
                "tracked_count": 0, "total_audited": 0,
                "win_rate": 50.0, "avg_gain": 0.0, "avg_profit_pct": 0.0,
                "signals": [], "audited_signals": []
            }

        # 筛选最近窗口内的 BUY 和 T0 信号
        cutoff_date = (datetime.now() - timedelta(days=days_window + 5)).strftime("%Y-%m-%d")
        recent_signals = []
        for s in all_signals:
            if s.get("signal_type") in ["BUY", "T0_BUY_T"] and s.get("date", "") >= cutoff_date:
                recent_signals.append(s)

        if not recent_signals:
            return {
                "tracked_count": 0, "total_audited": 0,
                "win_rate": 50.0, "avg_gain": 0.0, "avg_profit_pct": 0.0,
                "signals": [], "audited_signals": []
            }

        # 获取标的最新价格以测算收益率
        symbols = list(set([s["symbol"] for s in recent_signals]))
        quotes = data_fetcher.get_realtime_quotes(symbols)

        tracked = []
        wins = 0
        total_pnl = 0.0

        for s in recent_signals[:15]: # 最多统计前15条
            sym = s["symbol"]
            name = s.get("name", sym)
            sig_date = s.get("date", "")
            rec_price = float(s.get("price", 0.0))
            quote = quotes.get(sym, {})
            now_price = float(quote.get("price", rec_price))

            if rec_price > 0 and now_price > 0:
                pnl = round((now_price - rec_price) / rec_price * 100, 2)
                is_win = pnl > 0
                if is_win:
                    wins += 1
                total_pnl += pnl

                status_code = "WIN" if is_win else ("LOSS" if pnl < 0 else "EVEN")

                tracked.append({
                    "symbol": sym,
                    "name": name,
                    "date": sig_date,
                    "sig_date": sig_date,
                    "signal_type": s.get("signal_type"),
                    "benchmark_price": rec_price,
                    "rec_price": rec_price,
                    "current_price": now_price,
                    "now_price": now_price,
                    "profit_pct": pnl,
                    "pnl_pct": pnl,
                    "status": status_code,
                    "status_label": "盈利" if is_win else "浮亏"
                })

        count = len(tracked)
        win_rate = round(wins / count * 100, 1) if count > 0 else 50.0
        avg_gain = round(total_pnl / count, 2) if count > 0 else 0.0

        return {
            "tracked_count": count,
            "total_audited": count,
            "win_rate": win_rate,
            "avg_gain": avg_gain,
            "avg_profit_pct": avg_gain,
            "signals": tracked,
            "audited_signals": tracked
        }

    def _self_optimize_parameters(
        self,
        market_regime: str,
        win_rate: float,
        apply_changes: bool = True
    ) -> Dict[str, Any]:
        """
        量化策略自我迭代算法：
        根据宏观环境温度与近期信号胜率，计算自适应最优参数并完成闭环更新
        """
        cfg = load_config()
        old_rsrs_th = cfg.get("rsrs_buy_threshold", 0.70)
        old_stop_pct = cfg.get("trailing_stop_pct", 0.08)
        old_turnover = cfg.get("min_turnover_amount", 100000000)

        new_rsrs_th = old_rsrs_th
        new_stop_pct = old_stop_pct
        new_turnover = old_turnover
        reasons = []

        # 1. 弱势或胜率低下：收紧防御，提升入场准入门槛
        if market_regime == "弱势空头" or win_rate < 40.0:
            new_rsrs_th = min(round(old_rsrs_th + 0.05, 2), 0.85)
            new_stop_pct = 0.06 # 收紧移动止盈，见好就收
            new_turnover = max(old_turnover, 150000000) # 仅聚焦1.5亿以上超高流动性核心
            reasons.append(f"大盘处于{market_regime}且近期胜率({win_rate}%)偏低，系统自动调高RSRS买入阈值({old_rsrs_th}->{new_rsrs_th})以过滤假突破")

        # 2. 强势多头且胜率优秀：放宽止盈空间，让利润奔跑
        elif market_regime == "强势多头" and win_rate >= 55.0:
            new_rsrs_th = 0.70 # 恢复基准
            new_stop_pct = 0.09 # 扩大移动止盈容忍度至9%，避免洗盘过早下车
            new_turnover = 100000000
            reasons.append(f"大盘进入强势多头且胜率({win_rate}%)稳健，系统放宽移动止盈容忍度({old_stop_pct*100:.0f}%->{new_stop_pct*100:.0f}%)以捕捉波段主升")

        # 3. 正常震荡
        else:
            new_rsrs_th = 0.75
            new_stop_pct = 0.08
            reasons.append("大盘处于结构性震荡，维持稳健型波段参数配置")

        is_changed = (new_rsrs_th != old_rsrs_th) or (new_stop_pct != old_stop_pct)

        action_taken = "维持稳态参数"
        if new_rsrs_th > old_rsrs_th:
            action_taken = f"收紧准入门槛: RSRS {old_rsrs_th} -> {new_rsrs_th}"
        elif new_stop_pct > old_stop_pct:
            action_taken = f"放宽移动止盈: {old_stop_pct*100:.0f}% -> {new_stop_pct*100:.0f}%"
        elif new_stop_pct < old_stop_pct:
            action_taken = f"收紧移动止盈: {old_stop_pct*100:.0f}% -> {new_stop_pct*100:.0f}%"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        opt_result = {
            "timestamp": now_str,
            "time": now_str,
            "market_regime": market_regime,
            "win_rate": win_rate,
            "recent_win_rate": win_rate,
            "is_changed": is_changed,
            "applied": (apply_changes and is_changed),
            "action_taken": action_taken,
            "old_params": {
                "rsrs_buy_threshold": old_rsrs_th,
                "trailing_stop_pct": old_stop_pct,
                "min_turnover_amount": old_turnover
            },
            "new_params": {
                "rsrs_buy_threshold": new_rsrs_th,
                "trailing_stop_pct": new_stop_pct,
                "min_turnover_amount": new_turnover
            },
            "current_params": {
                "rsrs_buy_threshold": new_rsrs_th if apply_changes else old_rsrs_th,
                "trailing_stop_pct": new_stop_pct if apply_changes else old_stop_pct,
                "min_turnover_amount": new_turnover if apply_changes else old_turnover
            },
            "reasons": reasons
        }

        if apply_changes and is_changed:
            cfg["rsrs_buy_threshold"] = new_rsrs_th
            cfg["trailing_stop_pct"] = new_stop_pct
            cfg["min_turnover_amount"] = new_turnover
            save_config(cfg)
            default_strategy.reload_config()
            print(f"-> [自我迭代生效] 参数已热更新：RSRS阈值={new_rsrs_th}, 止盈容忍度={new_stop_pct}")

        # 记录优化日志
        self._record_optimization_log(opt_result)
        return opt_result

    def _build_markdown_report(
        self,
        today_str: str,
        market: Dict[str, Any],
        watchlist: Dict[str, Any],
        tracking: Dict[str, Any],
        opt: Dict[str, Any]
    ) -> str:
        """组装供终端和微信/钉钉推送的富文本复盘报告卡片"""
        sh = market.get("sh_index", {})
        sh_text = f"{sh.get('close', 0):.2f}点 ({sh.get('change_pct', 0):+.2f}%)" if sh else "暂无"
        regime = market.get("regime", "震荡")
        regime_desc = market.get("regime_desc", "")
        pos_sug = market.get("suggested_position_pct", 50)

        # 持仓行
        stock_rows = []
        for s in watchlist.get("stocks", []):
            if s.get("shares", 0) > 0:
                pnl_str = f"{s['pnl_pct']:+.2f}% ({s['pnl_dollar']:+.0f}元)"
                stock_rows.append(f"• **{s['name']}** (现价{s['close_price']}元 | 盈亏: {pnl_str})\n  状态: {s['health_status']} · 建议: {s['health_action']}")

        stocks_summary_text = "\n".join(stock_rows) if stock_rows else "• 当前无底仓持股，资金空仓避险待命中"

        # 信号追踪
        sig_count = tracking.get("tracked_count", 0)
        win_rate = tracking.get("win_rate", 0)
        avg_gain = tracking.get("avg_gain", 0)

        # 优化建议
        reasons_text = "\n".join([f"• {r}" for r in opt.get("reasons", [])])

        report = f"""### 📊 【A股主板收盘量化复盘与自我迭代报告】
**复盘日期**：{today_str} (收盘总结)

---
#### 1. 🌐 大盘大势量化定性
- **上证指数**：{sh_text}
- **大盘周期**：**【{regime}】**（{regime_desc}）
- **量化仓位指引**：建议总仓位控制在 **{pos_sug}%** 左右

---
#### 2. 📋 持仓健康度深度体检
- **持仓总市值**：{watchlist.get('total_market_val', 0):.2f} 元
- **当前在手总盈亏**：{watchlist.get('total_profit', 0):+.2f} 元
{stocks_summary_text}

---
#### 3. 🎯 近期推荐信号实战追踪
- **近10日跟踪信号**：共 {sig_count} 笔
- **推荐后综合胜率**：**{win_rate}%** (平均收益: {avg_gain:+.2f}%)

---
#### 4. 🧠 系统自我迭代与参数进化
- **当前状态**：{'⚡ 参数已自动调优完成' if opt.get('is_changed') else '✅ 策略运行在最优参数区间'}
{reasons_text}
- **当前核心参数**：RSRS买入阈值 = `{opt['new_params']['rsrs_buy_threshold']}` | 移动止盈容忍度 = `{opt['new_params']['trailing_stop_pct']*100:.0f}%`

---
*A股主板顶级量化系统 · 自动闭环复盘与进化*
"""
        return report

    def _save_review_record(self, record: Dict[str, Any]):
        """将每日复盘结果存入 JSON 历史数据库"""
        history = []
        if REVIEW_FILE.exists():
            try:
                with open(REVIEW_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = []

        # 覆盖当天或新增
        today = record["date"]
        history = [h for h in history if h.get("date") != today]
        history.insert(0, record)
        history = history[:30] # 保留最近30天复盘

        try:
            with open(REVIEW_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存复盘历史失败: {e}")

    def _record_optimization_log(self, opt_data: Dict[str, Any]):
        """记录系统自迭代参数日志"""
        logs = []
        if OPTIMIZATION_FILE.exists():
            try:
                with open(OPTIMIZATION_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            except Exception:
                logs = []

        logs.insert(0, opt_data)
        logs = logs[:50] # 保留最近50次参数调优历史

        try:
            with open(OPTIMIZATION_FILE, "w", encoding="utf-8") as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"记录优化日志失败: {e}")

    def get_latest_review(self) -> Optional[Dict[str, Any]]:
        """获取最新一次复盘内容"""
        if REVIEW_FILE.exists():
            try:
                with open(REVIEW_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data[0] if data else None
            except Exception:
                return None
        return None

    def get_review_history(self, limit: int = 30) -> List[Dict[str, Any]]:
        """获取复盘历史记录列表"""
        if REVIEW_FILE.exists():
            try:
                with open(REVIEW_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data[:limit] if data else []
            except Exception:
                return []
        return []

    def get_optimization_history(self) -> List[Dict[str, Any]]:
        """获取参数调优历史"""
        if OPTIMIZATION_FILE.exists():
            try:
                with open(OPTIMIZATION_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

review_engine = ReviewEngine()

