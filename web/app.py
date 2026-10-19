"""
Web后端 API 服务 (FastAPI)
提供行情监控、策略选股、单股量化诊断、自选股管理及通知通道测试接口
"""
import os
import json
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from config import load_config, save_config, SIGNALS_FILE
from core.data_fetcher import data_fetcher
from core.strategy import default_strategy, RSRSMomentumStrategy
from core.t0_strategy import t0_strategy
from core.risk_manager import risk_manager
from core.review_engine import review_engine
from notifier.manager import notification_manager
from scheduler.task_runner import quant_scheduler

app = FastAPI(title="A-Share Main Board Quant System", version="1.0.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# 挂载静态资源
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.on_event("startup")
async def startup_event():
    # 启动后台自动调度器
    cfg = load_config()
    if cfg.get("scheduler_enabled", True):
        quant_scheduler.start()

@app.get("/")
def read_root():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "A股主板量化系统已启动，前端界面加载中..."}

@app.get("/api/status")
def get_status():
    return {
        "is_trading_time": quant_scheduler.is_trading_time(),
        "scheduler_running": quant_scheduler.is_running,
        "scan_status": quant_scheduler.scan_status
    }

@app.get("/api/config")
def get_config():
    return load_config()

@app.post("/api/config")
def update_config(cfg: Dict[str, Any]):
    success = save_config(cfg)
    if success:
        default_strategy.reload_config()
        t0_strategy.reload_config()
    return {"success": success}

@app.post("/api/notify/test")
def test_notification():
    res = notification_manager.send_test_message()
    return {"success": True, "details": res}

import time
from core.chip_analyzer import chip_analyzer

_chip_cache: Dict[str, Dict[str, Any]] = {}

def get_cached_chip_info(sym: str, price: float) -> Dict[str, Any]:
    now = time.time()
    if sym in _chip_cache and (now - _chip_cache[sym]["time"]) < 600:
        return _chip_cache[sym]["data"]
    try:
        df = data_fetcher.get_daily_kline(sym, count=100)
        if df is not None and len(df) >= 20:
            c_info = chip_analyzer.analyze_chips(df, current_price=price)
            _chip_cache[sym] = {"time": now, "data": c_info}
            return c_info
    except Exception:
        pass
    return chip_analyzer._empty_result(price)

@app.get("/api/watchlist")
def get_watchlist_data():
    items = quant_scheduler.get_watchlist()
    if not items:
        return []
    symbols = [it["symbol"] for it in items]
    quotes = data_fetcher.get_realtime_quotes(symbols)
    
    result = []
    for it in items:
        sym = it["symbol"]
        quote = quotes.get(sym, {})
        entry_price = float(it.get("entry_price", 0.0) or 0.0)
        curr_price = float(quote.get("price", 0.0))
        shares = int(it.get("shares", 0) or 0)
        t0_enabled = it.get("t0_enabled", True)
        
        profit_pct = 0.0
        profit_amount = 0.0
        if entry_price > 0 and curr_price > 0:
            profit_pct = round((curr_price - entry_price) / entry_price * 100, 2)
            if shares > 0:
                profit_amount = round((curr_price - entry_price) * shares, 2)
            
        chip_info = get_cached_chip_info(sym, curr_price)
        main_cost = chip_info.get("main_cost", curr_price)
        bias_to_main = chip_info.get("bias_to_main", 0.0)
        control_status = chip_info.get("control_status", "洗盘震荡")
        profit_chip_ratio = chip_info.get("profit_chip_ratio", 50.0)

        result.append({
            "symbol": sym,
            "name": it.get("name", quote.get("name", sym)),
            "entry_price": entry_price,
            "shares": shares,
            "t0_enabled": t0_enabled,
            "price": curr_price,
            "change_pct": quote.get("change_pct", 0.0),
            "high": quote.get("high", curr_price),
            "low": quote.get("low", curr_price),
            "turnover": quote.get("turnover", 0.0),
            "profit_pct": profit_pct,
            "profit_amount": profit_amount,
            "main_cost": main_cost,
            "bias_to_main": bias_to_main,
            "control_status": control_status,
            "profit_chip_ratio": profit_chip_ratio,
            "chip_info": chip_info
        })
    return result

class AddWatchlistRequest(BaseModel):
    code: str
    entry_price: Optional[float] = 0.0
    shares: Optional[int] = 0
    t0_enabled: Optional[bool] = True

@app.post("/api/watchlist")
def add_watchlist(req: AddWatchlistRequest):
    query = req.code.strip()
    resolved = data_fetcher.resolve_symbol(query)
    if not resolved:
        raise HTTPException(status_code=400, detail="未找到有效的主板标的，目前仅支持A股主板股票代码或名称（沪市60/深市00开头）")
    symbol = resolved["symbol"]
    name = resolved["name"]
    
    quotes = data_fetcher.get_realtime_quotes([symbol])
    if quotes.get(symbol, {}).get("name"):
        name = quotes[symbol]["name"]
    
    current_list = quant_scheduler.get_watchlist()
    for item in current_list:
        if item["symbol"] == symbol:
            item["name"] = name
            item["entry_price"] = req.entry_price or 0.0
            item["shares"] = req.shares or 0
            item["t0_enabled"] = req.t0_enabled if req.t0_enabled is not None else True
            quant_scheduler.save_watchlist(current_list)
            return {"success": True, "message": f"已更新自选持仓信息: {name}"}
            
    current_list.append({
        "symbol": symbol,
        "name": name,
        "entry_price": req.entry_price or 0.0,
        "shares": req.shares or 0,
        "t0_enabled": req.t0_enabled if req.t0_enabled is not None else True
    })
    quant_scheduler.save_watchlist(current_list)
    return {"success": True, "message": f"成功加入自选: {name}"}

@app.delete("/api/watchlist/{symbol}")
def delete_watchlist(symbol: str):
    sym = data_fetcher.format_symbol(symbol)
    current_list = quant_scheduler.get_watchlist()
    new_list = [item for item in current_list if item["symbol"] != sym]
    quant_scheduler.save_watchlist(new_list)
    return {"success": True}

@app.get("/api/t0/monitor")
def get_t0_monitor():
    """
    获取持仓标的日内做T实时偏离度与建议
    """
    items = quant_scheduler.get_watchlist()
    # 筛选有持仓或开启了T0监控的标的
    target_items = [it for it in items if it.get("shares", 0) > 0 or it.get("t0_enabled", True)]
    if not target_items:
        target_items = items[:4] # 无持仓时展示前几只观察股
        
    symbols = [it["symbol"] for it in target_items]
    quotes = data_fetcher.get_realtime_quotes(symbols)
    
    results = []
    for it in target_items:
        sym = it["symbol"]
        quote = quotes.get(sym, {})
        if not quote:
            continue
        m_df = data_fetcher.get_minute_data(sym)
        shares = int(it.get("shares", 0) or 0)
        entry_price = float(it.get("entry_price", 0.0) or 0.0)
        
        t0_res = t0_strategy.analyze_t0(
            symbol=sym,
            name=it.get("name", quote.get("name", sym)),
            minute_df=m_df,
            quote=quote,
            holding_shares=shares,
            entry_price=entry_price
        )
        if t0_res:
            results.append(t0_res)
            
    return results

@app.get("/api/stock/minute")
def get_stock_minute(symbol: str):
    """获取单只股票今日分时与均价序列"""
    sym = data_fetcher.format_symbol(symbol)
    m_df = data_fetcher.get_minute_data(sym)
    if m_df is None or len(m_df) == 0:
        raise HTTPException(status_code=404, detail="暂无分时数据")
    return m_df.to_dict(orient="records")

@app.post("/api/scan/start")
def start_scan():
    quant_scheduler.scan_main_board_market(max_stocks=150)
    return {"success": True, "status": quant_scheduler.scan_status}

@app.get("/api/scan/results")
def get_scan_results():
    return {
        "status": quant_scheduler.scan_status,
        "results": quant_scheduler.latest_scan_results
    }

@app.get("/api/stock/search")
def search_stock(q: str):
    """根据代码或名称模糊查询主板股票"""
    if not q or not q.strip():
        return []
    return data_fetcher.search_stocks(q.strip(), limit=8)

@app.get("/api/stock/diagnose")
def diagnose_stock(symbol: str):
    resolved = data_fetcher.resolve_symbol(symbol)
    if not resolved:
        raise HTTPException(status_code=400, detail=f"未找到与 '{symbol}' 匹配的A股主板标的，请确认代码或名称是否正确（仅限沪深主板）")
    
    sym = resolved["symbol"]
    name = resolved["name"]
    
    quote = data_fetcher.get_realtime_quotes([sym]).get(sym, {})
    if quote and quote.get("name"):
        name = quote["name"]
    
    df = data_fetcher.get_daily_kline(sym, count=300)
    if df is None or len(df) < 30:
        raise HTTPException(status_code=404, detail="无法获取该股票的历史K线数据")
        
    analysis = default_strategy.analyze(sym, name, df)
    
    # 构建最近60根K线序列供图表渲染
    recent_kline = []
    tail_df = df.tail(60)
    for _, row in tail_df.iterrows():
        recent_kline.append({
            "date": str(row["date"])[:10],
            "open": round(float(row["open"]), 2),
            "close": round(float(row["close"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "volume": round(float(row["volume"]), 0),
            "ma5": round(float(row["ma5"]), 2) if not np.isnan(row.get("ma5", np.nan)) else None,
            "ma20": round(float(row["ma20"]), 2) if not np.isnan(row.get("ma20", np.nan)) else None,
            "rsrs_norm": round(float(row["rsrs_norm"]), 2) if not np.isnan(row.get("rsrs_norm", np.nan)) else None
        })
        
    return {
        "analysis": analysis,
        "quote": quote,
        "kline": recent_kline
    }

@app.get("/api/signals/history")
def get_signals_history():
    if SIGNALS_FILE.exists():
        try:
            with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

@app.get("/api/backtest")
def run_backtest_api(symbol: Optional[str] = None, days: int = 600, use_regime: bool = True):
    """
    提供历史数据量化回测 API 接口（严格防未来函数与过拟合检验）
    """
    from core.backtester import backtest_engine
    if symbol:
        resolved = data_fetcher.resolve_symbol(symbol)
        sym = resolved["symbol"] if resolved else data_fetcher.format_symbol(symbol)
        name = resolved["name"] if resolved else sym
        res = backtest_engine.run_backtest(sym, name=name, days=days, use_market_regime=use_regime)
        return res
    else:
        core_pool = [
            ("sh601138", "工业富联"),
            ("sz002475", "立讯精密"),
            ("sh600036", "招商银行"),
            ("sh601899", "紫金矿业"),
            ("sz000333", "美的集团"),
            ("sz002594", "比亚迪"),
            ("sh600418", "江淮汽车")
        ]
        return backtest_engine.run_portfolio_backtest(core_pool, days=days, use_market_regime=use_regime)

@app.get("/api/review/latest")
def get_latest_review():
    """获取最新收盘复盘报告与体检数据"""
    res = review_engine.get_latest_review()
    return res or {"message": "暂无收盘复盘数据，可点击立即执行收盘复盘"}

@app.get("/api/review/history")
def get_review_history(limit: int = 20):
    """获取历史收盘复盘记录"""
    return review_engine.get_review_history(limit=limit)

class RunReviewRequest(BaseModel):
    auto_optimize: Optional[bool] = True
    send_notify: Optional[bool] = False

@app.post("/api/review/run")
def trigger_daily_review(req: Optional[RunReviewRequest] = None):
    """手动立即触发收盘复盘与参数自我迭代"""
    auto_opt = req.auto_optimize if req is not None else True
    send_notif = req.send_notify if req is not None else False
    
    review_res = review_engine.run_daily_review(auto_optimize=auto_opt)
    
    if send_notif:
        title = f"📊 A股收盘量化复盘报告 ({review_res.get('date', '')})"
        report_md = review_res.get("report_markdown", "")
        notification_manager.send_markdown_card(title, report_md)
        
    return {
        "success": True,
        "date": review_res.get("date"),
        "regime": review_res.get("market_analysis", {}).get("regime"),
        "optimization": review_res.get("optimization"),
        "data": review_res
    }

@app.get("/api/optimization/log")
def get_optimization_log():
    """获取系统参数自迭代调优演进历史"""
    return review_engine.get_optimization_history()

