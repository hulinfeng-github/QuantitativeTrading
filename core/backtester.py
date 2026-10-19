"""
A股主板顶级量化回测与验证引擎 (BacktestEngine)
核心原则：
1. 绝对杜绝未来函数：T日收盘产出信号，T+1日开盘撮合成交；盘中严控低开跳空跌破止损滑点；
2. 严防过拟合：内置 In-Sample(样本内) 与 Out-of-Sample(样本外盲测) 步进切分与衰减度量；
3. 真实A股交易摩擦：包含印花税(卖出万5)、双边佣金(万2.5最低5元)、过户费与冲击滑点(0.1%)；
4. 涨跌停流动性限制：一字涨停无法买入，一字跌停无法卖出。
"""
import math
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from core.data_fetcher import data_fetcher
from core.indicators import calculate_all_indicators
from core.strategy import default_strategy, RSRSMomentumStrategy
from core.risk_manager import risk_manager

class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 50000.0,
        commission_rate: float = 0.00025,
        min_commission: float = 5.0,
        stamp_duty_rate: float = 0.0005,
        transfer_fee_rate: float = 0.00001,
        slippage_rate: float = 0.001,
        oos_ratio: float = 0.30,
        trailing_stop_pct: float = 0.08,
        breakeven_trigger_pct: float = 0.06
    ):
        """
        :param initial_capital: 初始本金（默认 50,000 元）
        :param commission_rate: 券商佣金率（默认 万2.5）
        :param min_commission: 最低佣金（默认 5元）
        :param stamp_duty_rate: 印花税率（仅卖出收取，默认 万5 即0.05%）
        :param transfer_fee_rate: 过户费率（双边收取，万0.1）
        :param slippage_rate: 滑点率（双边各 0.1%，模拟冲击成本）
        :param oos_ratio: 样本外(Out-of-Sample)时间切分比例（默认后 30% 为盲测验证期）
        :param trailing_stop_pct: 移动止盈回撤容忍度（默认8%，留足主升浪震荡空间）
        :param breakeven_trigger_pct: 保本止损触发线（默认+6%以上才启动保本，避免被正常日内杂波扫出局）
        """
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stamp_duty_rate = stamp_duty_rate
        self.transfer_fee_rate = transfer_fee_rate
        self.slippage_rate = slippage_rate
        self.oos_ratio = oos_ratio
        self.trailing_stop_pct = trailing_stop_pct
        self.breakeven_trigger_pct = breakeven_trigger_pct

    def run_backtest(
        self,
        symbol: str,
        name: str = "",
        df: Optional[pd.DataFrame] = None,
        days: int = 600,
        use_market_regime: bool = True,
        strategy: Optional[RSRSMomentumStrategy] = None
    ) -> Dict[str, Any]:
        """
        执行单只标的因果无未来函数回测
        :param symbol: 如 'sh600519'
        :param name: 股票名称
        :param df: K线数据，若为None则自动从腾讯API拉取
        :param days: 回测历史天数
        :param use_market_regime: 是否开启大盘牛熊环境自适应滤网（上证指数MA60）
        :param strategy: 策略实例，默认使用 default_strategy
        """
        strat = strategy or default_strategy
        sym = data_fetcher.format_symbol(symbol)
        
        if df is None:
            df = data_fetcher.get_daily_kline(sym, count=days)
            
        if df is None or len(df) < 80:
            return {"error": f"标的 {sym} 有效K线不足80根，无法进行回测"}

        # 确保按日期升序
        df = df.sort_values("date").reset_index(drop=True)
        if not name:
            name = sym

        # 1. 严格因果滚动计算技术因子（rolling计算内部绝无全样本均值）
        df = calculate_all_indicators(df, n=strat.rsrs_n, m=strat.rsrs_m)

        # 2. 如果开启大盘牛熊滤网，拉取同期上证指数（sh000001）
        market_bull_series = pd.Series(True, index=df.index)
        if use_market_regime:
            try:
                mkt_df = data_fetcher.get_daily_kline("sh000001", count=days + 100)
                if mkt_df is not None and len(mkt_df) > 60:
                    mkt_df['mkt_ma60'] = mkt_df['close'].rolling(60).mean()
                    mkt_df['mkt_date'] = pd.to_datetime(mkt_df['date']).dt.strftime('%Y-%m-%d')
                    mkt_map = dict(zip(mkt_df['mkt_date'], mkt_df['close'] > mkt_df['mkt_ma60']))
                    dates_str = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
                    market_bull_series = dates_str.map(lambda d: mkt_map.get(d, True))
            except Exception:
                pass

        # 3. 逐日事件驱动撮合模拟（严格杜绝未来函数）
        # 预留指标预热窗口（至少 max(strat.rsrs_n, 30)）
        warmup = max(strat.rsrs_n + 5, 30)
        total_bars = len(df)

        trades: List[Dict[str, Any]] = []
        equity_records: List[Dict[str, Any]] = []

        cash = self.initial_capital
        holding_shares = 0
        buy_price = 0.0
        buy_date = ""
        buy_idx = 0
        highest_price = 0.0
        initial_stop = 0.0
        pending_buy = False
        pending_buy_reason = ""
        pending_sell = False
        pending_sell_reason = ""

        # 计算样本内与样本外的切分点
        oos_start_idx = int(warmup + (total_bars - warmup) * (1.0 - self.oos_ratio))

        for i in range(warmup, total_bars):
            curr_bar = df.iloc[i]
            prev_bar = df.iloc[i - 1]
            curr_date = str(curr_bar['date'])[:10]
            open_p = float(curr_bar['open'])
            high_p = float(curr_bar['high'])
            low_p = float(curr_bar['low'])
            close_p = float(curr_bar['close'])
            prev_close_p = float(prev_bar['close'])
            atr_val = float(curr_bar['atr']) if not np.isnan(curr_bar['atr']) else close_p * 0.03

            is_oos = (i >= oos_start_idx)

            # -------------------------------------------------------------
            # [步骤 1: 盘前与开盘执行] 处理上一日收盘生成的待买入/待卖出委托
            # -------------------------------------------------------------
            # A. 执行前一日的卖出信号平仓
            if pending_sell and holding_shares > 0:
                # 检查跌停板限制（若一字跌停则无法平仓）
                is_limit_down = (open_p == low_p == high_p) and (open_p <= prev_close_p * 0.902)
                if not is_limit_down:
                    sell_exec_price = max(open_p * (1 - self.slippage_rate), 0.01)
                    gross_val = holding_shares * sell_exec_price
                    comm = max(gross_val * self.commission_rate, self.min_commission)
                    stamp = gross_val * self.stamp_duty_rate
                    trans = gross_val * self.transfer_fee_rate
                    net_proceeds = gross_val - comm - stamp - trans
                    cash += net_proceeds

                    pnl_dollar = net_proceeds - buy_cost_total
                    pnl_pct = (pnl_dollar / buy_cost_total) * 100

                    trades.append({
                        "symbol": sym,
                        "name": name,
                        "buy_date": buy_date,
                        "buy_price": round(buy_price, 2),
                        "sell_date": curr_date,
                        "sell_price": round(sell_exec_price, 2),
                        "shares": holding_shares,
                        "hold_days": i - buy_idx,
                        "net_pnl_pct": round(pnl_pct, 2),
                        "net_pnl_dollar": round(pnl_dollar, 2),
                        "max_runup_pct": round((highest_price - buy_price) / buy_price * 100, 2),
                        "exit_reason": pending_sell_reason,
                        "is_oos": is_oos
                    })

                    holding_shares = 0
                    pending_sell = False
                    pending_sell_reason = ""

            # B. 执行前一日的买入信号建仓
            if pending_buy and holding_shares == 0:
                # 检查涨停板限制（若一字涨停无法买入）
                is_limit_up = (open_p == high_p == low_p) and (open_p >= prev_close_p * 1.098)
                if not is_limit_up and cash >= 2000:
                    buy_exec_price = open_p * (1 + self.slippage_rate)
                    # 按照95%仓位计算可买股数（A股一手100股）
                    target_invest = cash * 0.95
                    shares = int(target_invest / (buy_exec_price * 100)) * 100
                    if shares >= 100:
                        gross_cost = shares * buy_exec_price
                        comm = max(gross_cost * self.commission_rate, self.min_commission)
                        trans = gross_cost * self.transfer_fee_rate
                        buy_cost_total = gross_cost + comm + trans
                        
                        cash -= buy_cost_total
                        holding_shares = shares
                        buy_price = buy_exec_price
                        buy_date = curr_date
                        buy_idx = i
                        highest_price = buy_exec_price
                        
                        # 初始止损位（ATR自适应：根据波动率预留2倍ATR或至少4%的合理缓冲区）
                        stop_dist = max(atr_val * 2.0, buy_price * 0.04)
                        initial_stop = round(max(buy_price - stop_dist, 0.01), 2)

                pending_buy = False
                pending_buy_reason = ""

            # -------------------------------------------------------------
            # [步骤 2: 盘中持仓风控与出场判定] (严格遵守A股 T+1 制度：当天建仓不可卖出，需 i > buy_idx)
            # -------------------------------------------------------------
            if holding_shares > 0 and i > buy_idx:
                highest_price = max(highest_price, high_p)
                
                # 评估持仓风控（保本止损与最高价回撤移动止盈）
                risk_eval = risk_manager.evaluate_holding_risk(
                    entry_price=buy_price,
                    current_price=low_p, # 用当日最低价测试是否破位
                    highest_price=highest_price,
                    initial_stop=initial_stop,
                    trailing_stop_pct=self.trailing_stop_pct,
                    breakeven_trigger_pct=self.breakeven_trigger_pct
                )

                if risk_eval["is_stop_triggered"]:
                    # 触及止损/止盈：成交价取有效止损价与开盘价中的较低者（模拟跳空低开穿价滑点）
                    trigger_price = min(open_p, risk_eval["effective_stop"])
                    sell_exec_price = max(trigger_price * (1 - self.slippage_rate), 0.01)

                    gross_val = holding_shares * sell_exec_price
                    comm = max(gross_val * self.commission_rate, self.min_commission)
                    stamp = gross_val * self.stamp_duty_rate
                    trans = gross_val * self.transfer_fee_rate
                    net_proceeds = gross_val - comm - stamp - trans
                    cash += net_proceeds

                    pnl_dollar = net_proceeds - buy_cost_total
                    pnl_pct = (pnl_dollar / buy_cost_total) * 100

                    trades.append({
                        "symbol": sym,
                        "name": name,
                        "buy_date": buy_date,
                        "buy_price": round(buy_price, 2),
                        "sell_date": curr_date,
                        "sell_price": round(sell_exec_price, 2),
                        "shares": holding_shares,
                        "hold_days": i - buy_idx,
                        "net_pnl_pct": round(pnl_pct, 2),
                        "net_pnl_dollar": round(pnl_dollar, 2),
                        "max_runup_pct": round((highest_price - buy_price) / buy_price * 100, 2),
                        "exit_reason": risk_eval["trigger_reason"],
                        "is_oos": is_oos
                    })

                    holding_shares = 0

            # -------------------------------------------------------------
            # [步骤 3: 盘后收盘生成明日决策信号]（严格仅基于当天及历史K线）
            # -------------------------------------------------------------
            is_bull_mkt = bool(market_bull_series.iloc[i])
            bar_analysis = strat.analyze_bar(sym, name, df, idx=i, market_regime_bull=is_bull_mkt)

            if bar_analysis:
                sig = bar_analysis.get("signal_type", "HOLD")
                if holding_shares == 0:
                    if sig == "BUY":
                        pending_buy = True
                        pending_buy_reason = bar_analysis.get("signal_desc", "强力波段买点")
                else:
                    if sig == "SELL":
                        pending_sell = True
                        pending_sell_reason = bar_analysis.get("signal_desc", "破位清仓信号")

            # 记录每日总资产
            current_equity = cash + (holding_shares * close_p if holding_shares > 0 else 0.0)
            equity_records.append({
                "date": curr_date,
                "equity": round(current_equity, 2),
                "is_oos": is_oos,
                "close": close_p
            })

        # 4. 统计与计算量化指标（区分全周期、In-Sample 与 Out-of-Sample）
        full_metrics = self._calculate_metrics(trades, equity_records)
        is_trades = [t for t in trades if not t["is_oos"]]
        is_equity = [e for e in equity_records if not e["is_oos"]]
        is_metrics = self._calculate_metrics(is_trades, is_equity)

        oos_trades = [t for t in trades if t["is_oos"]]
        oos_equity = [e for e in equity_records if e["is_oos"]]
        oos_metrics = self._calculate_metrics(oos_trades, oos_equity)

        # 过拟合衰减比 (Degradation Ratio): OOS夏普比率 / IS夏普比率
        is_sharpe = is_metrics.get("sharpe_ratio", 0.0)
        oos_sharpe = oos_metrics.get("sharpe_ratio", 0.0)
        degrade_ratio = round(oos_sharpe / is_sharpe, 2) if is_sharpe > 0.05 else 1.0

        if degrade_ratio >= 0.70:
            overfit_status = "健康 (Robust · 样本外表现良好)"
        elif degrade_ratio >= 0.40:
            overfit_status = "轻度衰减 (Acceptable · 正常损耗)"
        else:
            overfit_status = "高危预警 (High Risk · 存在过拟合)"

        return {
            "symbol": sym,
            "name": name,
            "total_bars": total_bars - warmup,
            "start_date": equity_records[0]["date"] if equity_records else "",
            "end_date": equity_records[-1]["date"] if equity_records else "",
            "full_metrics": full_metrics,
            "in_sample_metrics": is_metrics,
            "out_of_sample_metrics": oos_metrics,
            "degradation_ratio": degrade_ratio,
            "overfit_status": overfit_status,
            "trades": trades,
            "equity_curve": equity_records
        }

    def _calculate_metrics(self, trades: List[Dict[str, Any]], equity_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """计算一套标准量化绩效指标"""
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "pl_ratio": 0.0,
                "total_return_pct": 0.0,
                "annualized_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "avg_win_pct": 0.0,
                "avg_loss_pct": 0.0,
                "expected_value_pct": 0.0
            }

        pnls = [t["net_pnl_pct"] for t in trades]
        win_trades = [p for p in pnls if p > 0]
        loss_trades = [p for p in pnls if p <= 0]

        win_rate = (len(win_trades) / len(pnls)) * 100
        avg_win = float(np.mean(win_trades)) if win_trades else 0.0
        avg_loss = float(np.mean(loss_trades)) if loss_trades else 0.0
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 999.0
        ev = float(np.mean(pnls))

        # 净值计算
        start_eq = equity_records[0]["equity"] if equity_records else self.initial_capital
        end_eq = equity_records[-1]["equity"] if equity_records else self.initial_capital
        total_return_pct = ((end_eq - start_eq) / start_eq) * 100

        # 年化收益率（按每年250个交易日）
        num_days = max(len(equity_records), 1)
        years = num_days / 250.0
        if years > 0 and end_eq > 0:
            cagr = ((end_eq / start_eq) ** (1.0 / years) - 1.0) * 100
        else:
            cagr = 0.0

        # 最大回撤 (Max Drawdown)
        equities = np.array([e["equity"] for e in equity_records])
        running_max = np.maximum.accumulate(equities)
        drawdowns = (equities - running_max) / running_max
        max_drawdown_pct = abs(float(np.min(drawdowns))) * 100 if len(drawdowns) > 0 else 0.0

        # 夏普比率 (Sharpe Ratio, 假设无风险利率 2.0%)
        if len(equities) > 10:
            daily_returns = np.diff(equities) / equities[:-1]
            excess_daily = daily_returns - (0.02 / 250.0)
            daily_std = float(np.std(excess_daily))
            daily_mean = float(np.mean(excess_daily))
            sharpe = (daily_mean / daily_std * math.sqrt(250.0)) if daily_std > 1e-6 else 0.0
        else:
            sharpe = 0.0

        return {
            "total_trades": len(trades),
            "win_rate": round(win_rate, 1),
            "pl_ratio": round(pl_ratio, 2),
            "total_return_pct": round(total_return_pct, 2),
            "annualized_return_pct": round(cagr, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "sharpe_ratio": round(sharpe, 2),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "expected_value_pct": round(ev, 2)
        }

    def run_portfolio_backtest(
        self,
        symbols_with_names: List[Tuple[str, str]],
        days: int = 600,
        use_market_regime: bool = True
    ) -> Dict[str, Any]:
        """批量多标的交叉回测验证"""
        results = []
        all_trades = []
        for sym, name in symbols_with_names:
            try:
                res = self.run_backtest(sym, name=name, days=days, use_market_regime=use_market_regime)
                if "error" not in res:
                    results.append(res)
                    all_trades.extend(res.get("trades", []))
            except Exception as e:
                print(f"回测标的异常 {sym}: {e}")

        if not results:
            return {"error": "无有效回测结果"}

        # 汇总全部标的交易表现
        pnls = [t["net_pnl_pct"] for t in all_trades]
        win_trades = [p for p in pnls if p > 0]
        loss_trades = [p for p in pnls if p <= 0]

        portfolio_win_rate = (len(win_trades) / len(pnls) * 100) if pnls else 0.0
        avg_w = float(np.mean(win_trades)) if win_trades else 0.0
        avg_l = float(np.mean(loss_trades)) if loss_trades else 0.0
        pl = abs(avg_w / avg_l) if avg_l != 0 else 999.0

        # 平均收益与衰减比
        avg_ret = float(np.mean([r["full_metrics"]["total_return_pct"] for r in results]))
        avg_degrade = float(np.mean([r["degradation_ratio"] for r in results]))

        return {
            "stocks_tested": len(results),
            "total_trades": len(all_trades),
            "portfolio_win_rate": round(portfolio_win_rate, 1),
            "portfolio_pl_ratio": round(pl, 2),
            "portfolio_avg_return": round(avg_ret, 2),
            "portfolio_avg_win": round(avg_w, 2),
            "portfolio_avg_loss": round(avg_l, 2),
            "portfolio_avg_ev": round(float(np.mean(pnls)), 2) if pnls else 0.0,
            "average_degradation_ratio": round(avg_degrade, 2),
            "details": results
        }

backtest_engine = BacktestEngine()
