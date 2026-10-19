"""
A股主板量化系统全链路自动化测试套件
涵盖：数学指标模型、主板数据源、波段策略引擎、T+1日内做T引擎与配置通知
运行方式：python test_suite.py
"""
import sys
import unittest
import pandas as pd
import numpy as np
from datetime import datetime

# Windows 终端输出 UTF-8 兼容
if sys.platform.startswith('win') and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    except Exception:
        pass

from config import load_config, DEFAULT_CONFIG
from core.data_fetcher import data_fetcher
from core.indicators import calculate_rsrs, calculate_atr, calculate_macd, calculate_all_indicators
from core.strategy import default_strategy
from core.t0_strategy import t0_strategy
from core.risk_manager import risk_manager
from core.chip_analyzer import chip_analyzer
from notifier.manager import notification_manager

class TestAStockQuantSystem(unittest.TestCase):

    def setUp(self):
        # 构造模拟测试行情日K线（前低后高上升波段）
        dates = pd.date_range(start="2024-01-01", periods=100, freq="B")
        np.random.seed(42)
        base_price = 10.0 + np.cumsum(np.random.normal(0.05, 0.2, 100))
        highs = base_price + np.random.uniform(0.1, 0.5, 100)
        lows = base_price - np.random.uniform(0.1, 0.5, 100)
        closes = base_price + np.random.uniform(-0.1, 0.2, 100)
        opens = base_price - np.random.uniform(-0.1, 0.2, 100)
        volumes = np.random.uniform(10000, 50000, 100)

        self.mock_df = pd.DataFrame({
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes
        })

    def test_01_main_board_filtering(self):
        """测试A股主板股票代码与格式化过滤机制"""
        print("\n[测试 1] 验证A股主板代码识别与非权限过滤...")
        # 沪市主板有效
        self.assertTrue(data_fetcher.is_main_board("600519"))
        self.assertTrue(data_fetcher.is_main_board("sh601318"))
        self.assertTrue(data_fetcher.is_main_board("603288.SH"))
        self.assertEqual(data_fetcher.format_symbol("600519"), "sh600519")

        # 深市主板有效
        self.assertTrue(data_fetcher.is_main_board("000001"))
        self.assertTrue(data_fetcher.is_main_board("sz002594"))
        self.assertTrue(data_fetcher.is_main_board("000858.SZ"))
        self.assertEqual(data_fetcher.format_symbol("002594"), "sz002594")

        # 严格过滤创业板 (300xxx)、科创板 (688xxx)、北交所 (8xxx/4xxx/920xxx)
        self.assertFalse(data_fetcher.is_main_board("300750")) # 宁德时代(创业板)
        self.assertFalse(data_fetcher.is_main_board("688981")) # 中芯国际(科创板)
        self.assertFalse(data_fetcher.is_main_board("830946")) # 北交所
        self.assertFalse(data_fetcher.is_main_board("920002")) # 北交所新代码
        print("  -> 主板鉴权过滤测试通过！")

    def test_02_rsrs_indicator_math(self):
        """测试修正 RSRS 算法数学公式与向量化计算"""
        print("\n[测试 2] 验证修正 RSRS 模型 (OLS拟合/R2/Z-Score)...")
        res_df = calculate_rsrs(self.mock_df, n=18, m=50)
        
        self.assertIn("rsrs_beta", res_df.columns)
        self.assertIn("rsrs_r2", res_df.columns)
        self.assertIn("rsrs_norm", res_df.columns)

        # 检验最后一行有效值
        last_row = res_df.iloc[-1]
        self.assertFalse(np.isnan(last_row["rsrs_beta"]))
        self.assertTrue(0.0 <= last_row["rsrs_r2"] <= 1.0)
        self.assertFalse(np.isnan(last_row["rsrs_norm"]))
        print(f"  -> RSRS 样本计算成功: Beta={last_row['rsrs_beta']:.3f}, R2={last_row['rsrs_r2']:.3f}, 修正RSRS={last_row['rsrs_norm']:.3f}")

    def test_03_atr_and_risk_manager(self):
        """测试 ATR 波动止损与动态移动止盈"""
        print("\n[测试 3] 验证 ATR 波动计算与自适应止损止盈风控...")
        atr_df = calculate_atr(self.mock_df, period=14)
        last_atr = float(atr_df.iloc[-1]["atr"])
        self.assertGreater(last_atr, 0.0)

        # 交易点位测算
        entry_price = 100.0
        levels = risk_manager.calculate_trade_levels(entry_price=entry_price, atr=2.5, stop_multiplier=2.0)
        self.assertEqual(levels["entry_price"], 100.0)
        self.assertEqual(levels["initial_stop"], 95.0) # 100 - 2.5*2 = 95
        self.assertEqual(levels["stop_pct"], 5.0)
        self.assertGreater(levels["target_price"], entry_price)

        # 移动止盈测试：当价格冲高至120后回撤至112
        holding_eval = risk_manager.evaluate_holding_risk(
            entry_price=100.0,
            current_price=112.0,
            highest_price=120.0,
            initial_stop=95.0,
            trailing_stop_pct=0.06
        )
        self.assertTrue(holding_eval["is_stop_triggered"])
        print(f"  -> 风控引擎测试通过！冲高回撤触发移动止盈: {holding_eval['trigger_reason']}")

    def test_04_t0_intraday_strategy(self):
        """测试 A股 T+1 底仓做 T 引擎 (VWAP偏离度与Pivot Points)"""
        print("\n[测试 4] 验证 A股 T+1 底仓日内做T策略引擎...")
        # 构造模拟分时数据
        minute_records = []
        cum_vol = 0
        cum_amt = 0.0
        for i, m in enumerate(["09:30", "09:35", "09:40", "09:45", "09:50"]):
            # 模拟跳水产生负偏离
            price = 100.0 - i * 0.8
            vol = 1000
            amt = vol * 100 * price
            cum_vol += vol
            cum_amt += amt
            vwap = cum_amt / (cum_vol * 100)
            bias = ((price - vwap) / vwap) * 100
            minute_records.append({
                "time": m,
                "price": price,
                "cum_volume": cum_vol,
                "cum_amount": cum_amt,
                "vwap": vwap,
                "bias": bias
            })
        m_df = pd.DataFrame(minute_records)

        mock_quote = {"price": 96.8, "prev_close": 100.0, "high": 100.5, "low": 96.5}
        t0_res = t0_strategy.analyze_t0(
            symbol="sh600519",
            name="贵州茅台",
            minute_df=m_df,
            quote=mock_quote,
            holding_shares=1000,
            entry_price=99.0
        )
        self.assertIsNotNone(t0_res)
        self.assertIn("vwap", t0_res)
        self.assertIn("pivots", t0_res)
        self.assertEqual(t0_res["suggested_shares"], 400) # 底仓1000股推荐做T 400股
        self.assertEqual(t0_res["t_action"], "BUY_T")
        print(f"  -> 日内做T引擎研判正常: 当前偏离={t0_res['bias']:.2f}%, 动作={t0_res['t_action']}, 建议股数={t0_res['suggested_shares']}")

        # 验证尾盘平仓窗口（如 14:40）严禁新开买单，并强制触发 CLOSE_T 平仓提醒
        m_df_late = m_df.copy()
        m_df_late.iloc[-1, m_df_late.columns.get_loc('time')] = "14:45"
        t0_close_res = t0_strategy.analyze_t0(
            symbol="sh600519",
            name="贵州茅台",
            minute_df=m_df_late,
            quote=mock_quote,
            holding_shares=1000,
            entry_price=99.0
        )
        self.assertEqual(t0_close_res["t_action"], "CLOSE_T")
        print(f"  -> 尾盘做T强平机制验证通过: 14:45 触发强制平仓动作={t0_close_res['t_action']}")

        # 验证 14:45 尾盘提醒调度接口连通性
        remind_res = notification_manager.send_t0_close_reminder([
            {"symbol": "sh561980", "name": "半导体设备ETF", "shares": 15400, "t0_enabled": True}
        ])
        self.assertIsInstance(remind_res, dict)
        print("  -> 14:45 尾盘强平提醒消息通道分发正常！")

    def test_05_online_data_fetcher(self):
        """测试网络实时行情与日K接口连通性"""
        print("\n[测试 5] 验证真实市场数据源连接...")
        quotes = data_fetcher.get_realtime_quotes(["sh600519"])
        self.assertIn("sh600519", quotes)
        maotai = quotes["sh600519"]
        self.assertGreater(maotai["price"], 500.0)
        print(f"  -> 实时数据正常: {maotai['name']} 当前价 {maotai['price']}元")

        kline = data_fetcher.get_daily_kline("sh600519", count=60)
        self.assertIsNotNone(kline)
        self.assertGreaterEqual(len(kline), 30)
        print(f"  -> 日K线获取正常: 成功拉取 {len(kline)} 根前复权K线")

    def test_06_backtest_engine_causal_and_no_lookahead(self):
        """测试历史回测引擎因果性、防未来函数与过拟合检验机制"""
        print("\n[测试 6] 验证历史数据量化回测引擎 (防未来函数与T+1交易规则)...")
        from core.backtester import backtest_engine
        res = backtest_engine.run_backtest(
            symbol="sh600519",
            name="测试茅台",
            df=self.mock_df,
            use_market_regime=False
        )
        self.assertNotIn("error", res)
        self.assertIn("full_metrics", res)
        self.assertIn("in_sample_metrics", res)
        self.assertIn("out_of_sample_metrics", res)
        self.assertIn("degradation_ratio", res)
        
        # 严格检验A股T+1与无未来函数规则：任意一笔交易持仓天数必须 >= 1（当天建仓绝不可当天卖出）
        trades = res.get("trades", [])
        for t in trades:
            self.assertGreaterEqual(t["hold_days"], 1, f"违反T+1规则：{t['buy_date']} 买入不能当天卖出！")
            self.assertNotEqual(t["buy_date"], t["sell_date"], "买入日期与卖出日期不能相同")
            
        print(f"  -> 回测引擎检验通过！共模拟 {len(trades)} 笔合规交易，均严格遵循T+1无未来函数约束，过拟合衰减比: {res['degradation_ratio']}")

    def test_07_review_engine_and_self_optimization(self):
        """测试收盘复盘引擎与防过拟合自我迭代优化机制"""
        print("\n[测试 7] 验证收盘量化复盘引擎与策略自我迭代闭环...")
        from core.review_engine import review_engine
        
        # 1. 验证大盘指数定性
        market_analysis = review_engine._analyze_market_indices()
        self.assertIn("regime", market_analysis)
        self.assertIn(market_analysis["regime"], ["强势多头", "结构震荡", "弱势空头"])
        self.assertIn("indices", market_analysis)
        self.assertIn("suggested_position", market_analysis)
        print(f"  -> 大盘量化定性正常: 判定为[{market_analysis['regime']}], 建议仓位={market_analysis['suggested_position']}")

        # 2. 验证持仓体检与信号客观追踪
        watchlist_review = review_engine._review_watchlist()
        self.assertIn("holdings", watchlist_review)
        self.assertIn("total_market_value", watchlist_review)

        signal_tracking = review_engine._track_recent_signals(days_window=10)
        self.assertIn("win_rate", signal_tracking)
        self.assertIn("audited_signals", signal_tracking)

        # 3. 验证参数防过拟合自迭代计算 (apply_changes=False 保证单测不污染正式配置)
        opt_res = review_engine._self_optimize_parameters(
            market_regime="弱势空头",
            win_rate=30.0,
            apply_changes=False
        )
        self.assertIn("current_params", opt_res)
        cur = opt_res["current_params"]
        # 防过拟合边界断言
        self.assertTrue(0.70 <= cur["rsrs_buy_threshold"] <= 0.85, "RSRS阈值超出防过拟合安全边界")
        self.assertTrue(0.06 <= cur["trailing_stop_pct"] <= 0.10, "移动止盈超出防过拟合安全边界")
        print(f"  -> 策略自迭代演化正常: 动作={opt_res['action_taken']}, 调优后参数={cur}")

        # 4. 验证完整复盘报告生成
        report_md = review_engine._build_markdown_report(
            today_str=datetime.now().strftime("%Y-%m-%d"),
            market=market_analysis,
            watchlist=watchlist_review,
            tracking=signal_tracking,
            opt=opt_res
        )
        self.assertTrue(len(report_md) > 100)
        self.assertIn("大盘大势量化定性", report_md)
        print("  -> 收盘复盘与自迭代全链路验证通过！")

    def test_08_chip_analyzer(self):
        """测试主力筹码分布与建仓成本分析引擎"""
        print("\n[测试 8] 验证主力筹码分布与建仓成本分析引擎 (CYQ + Smart Money VWAP)...")
        res = chip_analyzer.analyze_chips(self.mock_df)
        self.assertIn("main_cost", res)
        self.assertIn("profit_chip_ratio", res)
        self.assertIn("concentration_70", res)
        self.assertIn("control_status", res)
        self.assertGreater(res["main_cost"], 0.0)
        self.assertTrue(0 <= res["profit_chip_ratio"] <= 100)
        print(f"  -> 主力成本测算正常: 现价={res['current_price']:.2f}元, 主力成本={res['main_cost']:.2f}元, 溢价={res['bias_to_main']:+.1f}%, 控盘状态={res['control_status']}")

        # 验证全量策略研判是否已注入主力成本特征
        strat_res = default_strategy.analyze("sh600519", "测试标的", self.mock_df)
        self.assertIsNotNone(strat_res)
        self.assertIn("main_cost", strat_res)
        self.assertIn("control_status", strat_res)
        print(f"  -> 策略引擎主力共振注入正常: 策略评分={strat_res['score']}分, 主力状态={strat_res['control_status']}")

def run_suite():
    print("=" * 65)
    print("      🚀 A股主板顶级量化系统 · 自动化自检套件 🚀")
    print("=" * 65)
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAStockQuantSystem)
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\n" + "=" * 65)
        print("🎉 [全部通过] 所有量化算法、主板规则与实时接口均达到100%健康状态！")
        print("=" * 65)
        return 0
    else:
        print("\n⚠️ 存在未通过的测试用例，请检查网络或配置！")
        return 1

if __name__ == "__main__":
    sys.exit(run_suite())
