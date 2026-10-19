import sys
import argparse
import uvicorn

# 兼容 Windows GBK 控制台编码，防止 UnicodeEncodeError
if sys.platform.startswith('win') and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    except Exception:
        pass

from config import load_config
from core.data_fetcher import data_fetcher
from core.strategy import default_strategy
from notifier.manager import notification_manager
from scheduler.task_runner import quant_scheduler

BANNER = """
==================================================================
        [A股主板顶级量化波段分析与预警系统]
   - 算法：修正 RSRS 机构模型 + 多周期量价共振 + ATR 自适应风控
   - 权限：专为主板定制（严格过滤科创/创业板/ST股）
   - 交易：中低频波段（非频繁交易，收益风险比最大化）
   - 告警：支持钉钉机器人 + 微信 PushPlus/Server酱/企业微信
==================================================================
"""

def run_cli_scan():
    print(BANNER)
    print(">>> 正在拉取A股主板股票清单并执行全市场扫描...")
    stocks = data_fetcher.get_main_board_stock_list()
    print(f"-> 成功加载主板股票池：共计 {len(stocks)} 只有效标的")
    
    # 扫描前50只标的作为快速演示
    top_candidates = []
    print("-> 正在计算修正 RSRS 与多周期量价特征...")
    for idx, s in enumerate(stocks[:50]):
        sym = s['symbol']
        name = s['name']
        try:
            df = data_fetcher.get_daily_kline(sym, count=300)
            if df is not None and len(df) >= 30:
                res = default_strategy.analyze(sym, name, df)
                if res and res.get("score", 0) >= 65:
                    top_candidates.append(res)
        except Exception:
            continue
            
    top_candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    print("\n" + "=" * 60)
    print(f"【A股主板高潜波段标的精选结果 (共 {len(top_candidates)} 只)】")
    print("=" * 60)
    for c in top_candidates:
        levels = c.get('trade_levels', {})
        print(f"[{c['signal_desc']}] {c['name']} ({c['symbol']}) - 现价: {c['price']:.2f}元 (涨跌: {c['change_pct']:+.2f}%)")
        print(f"   评分: {c['score']}分 | 修正RSRS: {c['rsrs_norm']} | 换手量比: {c['vol_ratio']}x")
        print(f"   风控: 建议止损 {levels.get('initial_stop')}元 (-{levels.get('stop_pct')}%) | 目标止盈 {levels.get('target_price')}元 (+{levels.get('reward_pct')}%)")
        print(f"   理由: {'; '.join(c.get('reasons', []))}\n")

def run_cli_backtest(symbol: str = None, days: int = 600):
    print(BANNER)
    from core.backtester import backtest_engine
    
    if symbol:
        info = data_fetcher.resolve_symbol(symbol)
        sym = info["symbol"] if info else data_fetcher.format_symbol(symbol)
        name = info["name"] if info else sym
        print(f">>> 正在对标的 [{name} ({sym})] 进行严格防未来函数与防过拟合历史回测 (近 {days} 个交易日)...")
        res = backtest_engine.run_backtest(sym, name=name, days=days, use_market_regime=True)
        if "error" in res:
            print(f"❌ 回测失败: {res['error']}")
            return
            
        fm = res["full_metrics"]
        im = res["in_sample_metrics"]
        om = res["out_of_sample_metrics"]
        print("\n" + "=" * 70)
        print(f"   【{name} ({sym}) 历史量化回测综合报告】")
        print("=" * 70)
        print(f"回测区间: {res['start_date']} 至 {res['end_date']} (共 {res['total_bars']} 根因果K线)")
        print(f"过拟合检验: 衰减比={res['degradation_ratio']} | 状态: {res['overfit_status']}")
        print("-" * 70)
        print(f"全周期指标: 交易笔数={fm['total_trades']:2d} | 胜率={fm['win_rate']:4.1f}% | 累计收益={fm['total_return_pct']:+6.1f}% | 年化={fm['annualized_return_pct']:4.1f}%")
        print(f"           盈亏比={fm['pl_ratio']:4.2f}:1 | 最大回撤={fm['max_drawdown_pct']:4.1f}% | 夏普比率={fm['sharpe_ratio']:4.2f} | 单笔期望={fm['expected_value_pct']:+4.2f}%")
        print("-" * 70)
        print(f"样本内(前70% 训练期): 笔数={im['total_trades']:2d} | 胜率={im['win_rate']:4.1f}% | 收益={im['total_return_pct']:+6.1f}% | 夏普={im['sharpe_ratio']:4.2f} | 盈亏比={im['pl_ratio']:4.2f}:1")
        print(f"样本外(后30% 盲测期): 笔数={om['total_trades']:2d} | 胜率={om['win_rate']:4.1f}% | 收益={om['total_return_pct']:+6.1f}% | 夏普={om['sharpe_ratio']:4.2f} | 盈亏比={om['pl_ratio']:4.2f}:1")
        print("=" * 70)
        trades = res.get("trades", [])
        if trades:
            print(f"最近 10 笔严格因果交易明细 (共 {len(trades)} 笔):")
            for t in trades[-10:]:
                phase = "盲测" if t["is_oos"] else "训练"
                print(f"  [{phase}] {t['buy_date']} 买入({t['buy_price']:.2f}元) -> {t['sell_date']} 卖出({t['sell_price']:.2f}元) | 净收益: {t['net_pnl_pct']:+5.2f}% ({t['net_pnl_dollar']:+6.1f}元) | 理由: {t['exit_reason']}")
        print()
    else:
        print(f">>> 正在对 A股主板代表性核心组合进行交叉回测检验 (近 {days} 个交易日)...")
        core_pool = [
            ("sh601138", "工业富联"),
            ("sz002475", "立讯精密"),
            ("sh600036", "招商银行"),
            ("sh601899", "紫金矿业"),
            ("sz000333", "美的集团"),
            ("sz002594", "比亚迪"),
            ("sh600418", "江淮汽车")
        ]
        res = backtest_engine.run_portfolio_backtest(core_pool, days=days, use_market_regime=True)
        if "error" in res:
            print(f"❌ 回测失败: {res['error']}")
            return
            
        print("\n" + "=" * 80)
        print("     【A股主板代表性标的 · 严格多标的交叉回测验证汇总】")
        print("=" * 80)
        print(f"标的数量: {res['stocks_tested']} 只 | 总交易笔数: {res['total_trades']} 笔")
        print(f"组合综合胜率: {res['portfolio_win_rate']}% | 综合盈亏比: {res['portfolio_pl_ratio']} : 1")
        print(f"平均单笔盈利: +{res['portfolio_avg_win']}% | 平均单笔亏损: {res['portfolio_avg_loss']}%")
        print(f"平均单笔期望收益 (EV): {res['portfolio_avg_ev']:+}% | 组合平均收益率: {res['portfolio_avg_return']:+}%")
        print(f"平均过拟合衰减比 (OOS/IS): {res['average_degradation_ratio']}")
        print("-" * 80)
        print("各标的分项明细:")
        for d in res["details"]:
            fm = d["full_metrics"]
            im = d["in_sample_metrics"]
            om = d["out_of_sample_metrics"]
            print(f"  [{d['name']:4s} {d['symbol']}] 笔数:{fm['total_trades']:2d} | 胜率:{fm['win_rate']:4.1f}% (IS:{im['win_rate']:4.1f}% / OOS:{om['win_rate']:4.1f}%) | 收益:{fm['total_return_pct']:+6.1f}% | 盈亏比:{fm['pl_ratio']:4.2f}:1 | 衰减比:{d['degradation_ratio']} [{d['overfit_status']}]")
        print("=" * 80 + "\n")

def run_cli_review():
    print(BANNER)
    from core.review_engine import review_engine
    print(">>> 正在执行A股收盘全景量化复盘与自我迭代...")
    res = review_engine.run_daily_review(auto_optimize=True)
    print("\n" + res.get("report_markdown", ""))

def run_test_notify():
    print(">>> 发送测试消息到微信 / 钉钉...")
    res = notification_manager.send_test_message()
    print("发送结果:", res)

import socket

def find_available_port(host: str, start_port: int, max_attempts: int = 10) -> int:
    """智能检测端口占用并自动顺延至可用端口"""
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            # connect_ex 返回非0表示端口未被监听，可以使用
            if s.connect_ex((host, p)) != 0:
                return p
    return start_port

def main():
    parser = argparse.ArgumentParser(description="A股主板量化波段分析系统")
    parser.add_argument("--scan", action="store_true", help="单次执行全市场主板扫描并在终端输出")
    parser.add_argument("--review", action="store_true", help="执行收盘全景量化复盘与策略自迭代优化")
    parser.add_argument("--notify", action="store_true", help="发送一条测试通知到微信/钉钉")
    parser.add_argument("--backtest", action="store_true", help="执行历史数据回测（严格防未来函数与过拟合检验）")
    parser.add_argument("--symbol", type=str, default=None, help="指定回测股票代码（如 601138, 002475，留空回测核心池）")
    parser.add_argument("--days", type=int, default=600, help="回测历史K线天数（默认600天）")
    parser.add_argument("--port", type=int, default=None, help="Web 控制台运行端口（默认8088）")
    args = parser.parse_args()

    if args.review:
        run_cli_review()
        return

    if args.backtest:
        run_cli_backtest(symbol=args.symbol, days=args.days)
        return

    if args.scan:
        run_cli_scan()
        return

    if args.notify:
        run_test_notify()
        return

    cfg = load_config()
    pref_port = args.port or cfg.get("web_port", 8088)
    host = cfg.get("web_host", "127.0.0.1")

    # 智能探测可用端口，防止 Errno 10048 绑定失败
    actual_port = find_available_port(host, pref_port)
    if actual_port != pref_port:
        print(f"\n[提示] 端口 {pref_port} 当前已被占用，已自动为您无缝切换至可用端口: {actual_port}")

    print(BANNER)
    print(f">>> Web 仪表盘控制台地址：http://{host}:{actual_port}")
    print(">>> 盘中自选高频监控与盘后选股调度器已随服务启动")
    print(">>> 按 Ctrl+C 停止运行\n")

    uvicorn.run("web.app:app", host=host, port=actual_port, log_level="info", reload=False)

if __name__ == "__main__":
    main()
