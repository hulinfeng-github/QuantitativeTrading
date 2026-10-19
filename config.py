"""
A股主板量化系统配置模块
"""
import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "storage"
CONFIG_FILE = DATA_DIR / "user_config.json"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
SIGNALS_FILE = DATA_DIR / "signals_history.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    # 策略参数（修正RSRS模型 + 多周期均线）
    "rsrs_n": 18,               # RSRS OLS回归窗口周期（通常18天）
    "rsrs_m": 600,              # RSRS滑动Z-score标准化窗口（通常600天，样本不足时自动降级）
    "rsrs_buy_threshold": 0.7,   # 修正RSRS买入阈值
    "rsrs_sell_threshold": -0.7, # 修正RSRS卖出清仓阈值
    "ma_short": 5,              # 短期均线
    "ma_mid": 20,               # 中期生命线
    "ma_long": 60,              # 长期牛熊线
    "atr_period": 14,           # ATR波动周期
    "atr_stop_multiplier": 2.0, # 初始ATR硬止损倍数
    "trailing_stop_pct": 0.06,  # 最高点回撤动态止盈止损（6%）
    
    # 选股与扫描过滤参数
    "min_turnover_amount": 100000000, # 最小日成交额（1亿元，剔除死水流动性差的股票）
    "allow_main_board_only": True,    # 仅允许主板（沪市60/深市00）
    "exclude_st": True,               # 过滤ST/*ST/退市
    
    # 消息通知配置
    "dingtalk_enabled": False,
    "dingtalk_webhook": "",
    "dingtalk_secret": "",
    
    "wechat_enabled": False,
    "wechat_provider": "pushplus",     # pushplus | serverchan | wecom
    "wechat_token": "",                # PushPlus Token 或 Server酱 SendKey 或 企业微信 Webhook
    
    # 自动化调度配置
    "scheduler_enabled": True,
    "scan_interval_minutes": 5,        # 盘中自选股巡检间隔（分钟）
    "market_close_scan_time": "15:05", # 盘后全市场主板扫描时间
    
    # A股 T+1 日内做T配置
    "t0_monitor_enabled": True,       # 是否开启持仓股日内做T监控
    "t0_bias_buy": -1.5,              # 正T低吸均线负偏离阈值 (%)
    "t0_bias_sell": 2.0,              # 倒T高抛均线正偏离阈值 (%)
    
    # Web 服务端口
    "web_port": 8088,
    "web_host": "127.0.0.1"
}

def _load_env_file():
    """轻量级解析 .env 文件（避免引入额外第三方依赖）"""
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass

def load_config() -> dict:
    _load_env_file()
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg.update(data)
        except Exception:
            pass

    # 允许环境变量覆盖敏感配置（适合容器化/服务器部署）
    if os.getenv("DINGTALK_WEBHOOK"):
        cfg["dingtalk_webhook"] = os.getenv("DINGTALK_WEBHOOK")
        cfg["dingtalk_enabled"] = True
    if os.getenv("DINGTALK_SECRET"):
        cfg["dingtalk_secret"] = os.getenv("DINGTALK_SECRET")
    if os.getenv("WECHAT_PROVIDER"):
        cfg["wechat_provider"] = os.getenv("WECHAT_PROVIDER")
    if os.getenv("WECHAT_TOKEN"):
        cfg["wechat_token"] = os.getenv("WECHAT_TOKEN")
        cfg["wechat_enabled"] = True
    if os.getenv("WEB_PORT"):
        try:
            cfg["web_port"] = int(os.getenv("WEB_PORT"))
        except ValueError:
            pass
    if os.getenv("WEB_HOST"):
        cfg["web_host"] = os.getenv("WEB_HOST")

    return cfg

def save_config(new_config: dict) -> bool:
    try:
        cfg = load_config()
        cfg.update(new_config)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False
