"""
自动化调度引擎
支持：A股交易时间自适应检测、盘中自选池高频监控、盘后15:05全市场主板量化选股
"""
import time
import json
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
import pandas as pd

from apscheduler.schedulers.background import BackgroundScheduler
from config import load_config, WATCHLIST_FILE
from core.data_fetcher import data_fetcher
from core.strategy import default_strategy
from core.t0_strategy import t0_strategy
from notifier.manager import notification_manager

class QuantScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self.is_running = False
        self.latest_scan_results: List[Dict[str, Any]] = []
        self.scan_status = {
            "is_scanning": False,
            "progress": 0,
            "total": 0,
            "message": "空闲",
            "last_scan_time": ""
        }

    @staticmethod
    def is_trading_time() -> bool:
        """判断当前是否为A股交易时间 (周一至周五 09:30-11:30, 13:00-15:00)"""
        now = datetime.now()
        # 周末不交易 (5=周六, 6=周日)
        if now.weekday() >= 5:
            return False
        curr_time = now.strftime("%H:%M")
        morning = "09:25" <= curr_time <= "11:30"
        afternoon = "13:00" <= curr_time <= "15:00"
        return morning or afternoon

    def get_watchlist(self) -> List[Dict[str, str]]:
        """获取自选股监控池"""
        if WATCHLIST_FILE.exists():
            try:
                with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        # 默认优质主板核心初始观察池
        default_watch = [
            {"symbol": "sh600519", "name": "贵州茅台", "entry_price": 0.0},
            {"symbol": "sz002594", "name": "比亚迪", "entry_price": 0.0},
            {"symbol": "sh601318", "name": "中国平安", "entry_price": 0.0},
            {"symbol": "sz000333", "name": "美的集团", "entry_price": 0.0},
            {"symbol": "sh601899", "name": "紫金矿业", "entry_price": 0.0},
            {"symbol": "sh601138", "name": "工业富联", "entry_price": 0.0},
            {"symbol": "sh600036", "name": "招商银行", "entry_price": 0.0},
            {"symbol": "sz002475", "name": "立讯精密", "entry_price": 0.0}
        ]
        self.save_watchlist(default_watch)
        return default_watch

    def save_watchlist(self, watchlist: List[Dict[str, Any]]) -> bool:
        """保存自选股池"""
        try:
            with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(watchlist, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存自选池失败: {e}")
            return False

    def monitor_watchlist(self, force: bool = False):
        """盘中巡检自选股池（仅在A股交易时段执行：周一至周五 09:25-11:30, 13:00-15:00）"""
        if not force and not self.is_trading_time():
            # 非开盘交易时段，静默跳过，绝不打扰用户
            return

        print(f"[{datetime.now().strftime('%H:%M:%S')}] 处于A股交易时段，启动自选池实时巡检...")
        watchlist = self.get_watchlist()
        if not watchlist:
            return

        symbols = [item['symbol'] for item in watchlist]
        # 1. 获取最新实时行情
        quotes = data_fetcher.get_realtime_quotes(symbols)

        for item in watchlist:
            sym = item['symbol']
            name = item.get('name', sym)
            quote = quotes.get(sym)
            if not quote:
                continue

            # 2. 获取K线做策略分析
            df = data_fetcher.get_daily_kline(sym, count=300)
            if df is None or len(df) < 30:
                continue

            # 替换最新日K为盘中实时数据
            last_date = df.iloc[-1]['date'].strftime('%Y-%m-%d')
            today_str = datetime.now().strftime('%Y-%m-%d')
            if last_date == today_str:
                df.iloc[-1, df.columns.get_loc('close')] = quote['price']
                df.iloc[-1, df.columns.get_loc('high')] = max(df.iloc[-1]['high'], quote['high'])
                df.iloc[-1, df.columns.get_loc('low')] = min(df.iloc[-1]['low'], quote['low'])
            else:
                # 盘中插入今日临时K线
                new_row = pd.DataFrame([{
                    "date": pd.to_datetime(today_str),
                    "open": quote['open'],
                    "close": quote['price'],
                    "high": quote['high'],
                    "low": quote['low'],
                    "volume": quote['volume']
                }])
                df = pd.concat([df, new_row], ignore_index=True)

            res = default_strategy.analyze(sym, name, df)
            if not res:
                continue

            # 若触发强力买点或减仓预警，自动推送
            if res.get("signal_type") in ["BUY", "SELL"]:
                print(f"-> 监控触发信号: {name} {res.get('signal_desc')}")
                notification_manager.send_signal(res)

            # 3. A股 T+1 底仓日内做T监控 (持有底仓时自动研判，且严控时间窗口)
            shares = int(item.get('shares', 0) or 0)
            t0_enabled = item.get('t0_enabled', True)
            curr_hm = datetime.now().strftime("%H:%M")
            if shares >= 100 and t0_enabled:
                m_df = data_fetcher.get_minute_data(sym)
                if m_df is not None and len(m_df) >= 5:
                    t0_res = t0_strategy.analyze_t0(
                        symbol=sym,
                        name=name,
                        minute_df=m_df,
                        quote=quote,
                        holding_shares=shares,
                        entry_price=float(item.get('entry_price', 0.0) or 0.0)
                    )
                    if t0_res:
                        action = t0_res.get("t_action")
                        # 1. 仅在14:15前允许触发新的买/卖做T开仓，且开仓成功后落盘跟踪
                        if action in ["BUY_T", "SELL_T"] and curr_hm <= "14:15":
                            print(f"-> [日内做T触发开仓] {name}: {t0_res.get('t_type')} 现价{t0_res.get('price')} 偏离{t0_res.get('bias')}%")
                            res_dict = notification_manager.send_t0_signal(t0_res)
                            if not res_dict.get("skipped"):
                                t0_strategy.record_trade_open(t0_res)
                        # 2. 触发止损(跌破防守价)或冲高止盈平仓预警，高优先级强制推送
                        elif action in ["STOP_T", "PROFIT_T"]:
                            print(f"-> [日内做T关键风控触发] {name}: {t0_res.get('t_type')} 现价{t0_res.get('price')}")
                            notification_manager.send_t0_signal(t0_res, force=True)
                            reasons = t0_res.get("reasons", [])
                            t0_strategy.record_trade_close(
                                symbol=sym,
                                action=action,
                                price=t0_res.get("price", 0.0),
                                reason=reasons[0] if reasons else action
                            )
                        # 3. 14:35-14:55 尾盘强制平仓对冲
                        elif action == "CLOSE_T":
                            print(f"-> [日内做T尾盘平仓] {name}: 现价{t0_res.get('price')}")
                            notification_manager.send_t0_signal(t0_res)
                            t0_strategy.record_trade_close(
                                symbol=sym,
                                action=action,
                                price=t0_res.get("price", 0.0),
                                reason="尾盘强制对冲平仓"
                            )

    def scan_main_board_market(self, max_stocks: int = 300, auto_notify: bool = False) -> List[Dict[str, Any]]:
        """
        全市场A股主板智能波段选股扫描
        :param auto_notify: 扫描完成后是否自动推送买点信号卡片（盘后定时调度时为True，Web手动为False）
        """
        if self.scan_status["is_scanning"]:
            return self.latest_scan_results

        self.scan_status["is_scanning"] = True
        self.scan_status["progress"] = 0
        self.scan_status["message"] = "正在获取A股主板股票池..."

        def safe_float(val, default=0.0):
            try:
                if val is None or val == "" or val == "-":
                    return default
                return float(val)
            except (ValueError, TypeError):
                return default

        def run_scan():
            try:
                default_strategy.reload_config()
                cfg = load_config()
                min_turnover = float(cfg.get("min_turnover_amount", 100000000))

                stocks = data_fetcher.get_main_board_stock_list()
                # 过滤低流动性标的，并优先按成交金额降序挑选最优质活跃标的 (安全解析成交额，防'-'等异常字符)
                filtered = [s for s in stocks if safe_float(s.get("turnover")) >= min_turnover]
                if len(filtered) < 30: # 盘后或初始无成交额数据时兜底
                    filtered = stocks
                else:
                    filtered.sort(key=lambda x: safe_float(x.get("turnover")), reverse=True)

                target_stocks = filtered[:max_stocks]
                total = len(target_stocks)
                self.scan_status["total"] = total
                self.scan_status["message"] = f"开始分析 {total} 只高流动性主板股票的RSRS与量价共振指标..."

                results = []
                completed = 0

                def process_stock(stock_info):
                    sym = stock_info['symbol']
                    name = stock_info['name']
                    try:
                        df = data_fetcher.get_daily_kline(sym, count=300)
                        if df is None or len(df) < 50:
                            return None
                        analysis = default_strategy.analyze(sym, name, df)
                        return analysis
                    except Exception:
                        return None

                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = {executor.submit(process_stock, s): s for s in target_stocks}
                    for future in as_completed(futures):
                        completed += 1
                        self.scan_status["progress"] = completed
                        self.scan_status["message"] = f"正在分析: {completed}/{total}"
                        res = future.result()
                        if res and res.get("score", 0) >= 60:
                            results.append(res)

                # 按综合评分由高到低排序
                results.sort(key=lambda x: x.get("score", 0), reverse=True)
                self.latest_scan_results = results
                self.scan_status["last_scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.scan_status["message"] = f"扫描完成！筛选出 {len(results)} 只高潜优质标的"

                if auto_notify:
                    # 仅在盘后定时全市场扫描时自动推送排名前3的高分买点标的
                    top_buys = [r for r in results if r.get("signal_type") == "BUY"][:3]
                    for buy_sig in top_buys:
                        notification_manager.send_signal(buy_sig)

            except Exception as e:
                self.scan_status["message"] = f"扫描异常: {e}"
            finally:
                self.scan_status["is_scanning"] = False

        threading.Thread(target=run_scan, daemon=True).start()
        return self.latest_scan_results

    def run_t0_closeout_reminder_job(self):
        """交易日 14:45 自动执行：A股尾盘做T强制平仓与对冲核对提醒"""
        try:
            watchlist = self.get_watchlist()
            t0_holdings = [
                item for item in watchlist 
                if int(item.get("shares", 0) or 0) >= 100 and item.get("t0_enabled", True)
            ]
            if not t0_holdings:
                return
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 触发交易日 14:45 尾盘做T强制平仓核对提醒...")
            notification_manager.send_t0_close_reminder(t0_holdings)
        except Exception as e:
            print(f"尾盘做T强平提醒任务异常: {e}")

    def run_daily_review_job(self):
        """执行每日收盘量化复盘与自我迭代优化，并推送到微信/钉钉"""
        try:
            from core.review_engine import review_engine
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 触发盘后每日量化复盘与自我迭代任务...")
            res = review_engine.run_daily_review(auto_optimize=True)
            report_md = res.get("report_markdown", "")
            if report_md:
                notification_manager.send_markdown_card("【A股收盘量化复盘与自我迭代】", report_md)
        except Exception as e:
            print(f"每日复盘任务异常: {e}")

    def start(self):
        """启动后台定时任务"""
        if self.is_running:
            return
        cfg = load_config()
        interval = cfg.get("scan_interval_minutes", 5)

        # 1. 盘中定时自选巡检 (内部严格判断交易时间，非开盘不执行)
        self.scheduler.add_job(
            self.monitor_watchlist,
            'interval',
            minutes=interval,
            id='watchlist_monitor',
            replace_existing=True
        )

        # 2. 交易日 14:45 准时发送：尾盘做T强制平仓与对冲核对提醒 (周一至周五)
        self.scheduler.add_job(
            self.run_t0_closeout_reminder_job,
            'cron',
            day_of_week='mon-fri',
            hour=14,
            minute=45,
            id='t0_closeout_reminder',
            replace_existing=True
        )

        # 3. 盘后 15:05 自动全市场主板选股 (周一至周五，自动推送)
        self.scheduler.add_job(
            lambda: self.scan_main_board_market(auto_notify=True),
            'cron',
            day_of_week='mon-fri',
            hour=15,
            minute=5,
            id='market_close_scan',
            replace_existing=True
        )

        # 4. 盘后 15:20 自动执行全景量化复盘与自迭代 (周一至周五，自动推送复盘卡片)
        self.scheduler.add_job(
            self.run_daily_review_job,
            'cron',
            day_of_week='mon-fri',
            hour=15,
            minute=20,
            id='market_close_review',
            replace_existing=True
        )

        self.scheduler.start()
        self.is_running = True
        print(">>> 定时调度器已成功启动！(含盘中盯盘、14:45做T强平提醒、15:05选股、15:20收盘复盘与自迭代)")

    def stop(self):
        if self.is_running:
            self.scheduler.shutdown()
            self.is_running = False

quant_scheduler = QuantScheduler()
