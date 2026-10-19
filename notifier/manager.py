"""
通知管理中心
统一处理钉钉与微信多渠道推送，提供去重防刷与信号历史存储
"""
import json
import time
from datetime import datetime
from typing import Dict, Any, List
from config import load_config, SIGNALS_FILE
from notifier.dingtalk import DingTalkNotifier
from notifier.wechat import WeChatNotifier

class NotificationManager:
    def __init__(self):
        # 记录今日已推送的 (symbol, signal_type, date)，避免重复打扰
        self._sent_cache = set()

    def send_signal(self, signal: Dict[str, Any], force: bool = False) -> Dict[str, bool]:
        """
        分发交易信号至已启用的推送通道
        """
        symbol = signal.get("symbol", "")
        sig_type = signal.get("signal_type", "")
        today = datetime.now().strftime("%Y-%m-%d")
        cache_key = f"{symbol}_{sig_type}_{today}"

        if not force and cache_key in self._sent_cache:
            return {"dingtalk": False, "wechat": False, "skipped": True}

        cfg = load_config()
        results = {"dingtalk": False, "wechat": False, "skipped": False}

        # 钉钉推送
        if cfg.get("dingtalk_enabled") and cfg.get("dingtalk_webhook"):
            dt = DingTalkNotifier(webhook=cfg.get("dingtalk_webhook"), secret=cfg.get("dingtalk_secret", ""))
            results["dingtalk"] = dt.send_trade_signal(signal)

        # 微信推送
        if cfg.get("wechat_enabled") and cfg.get("wechat_token"):
            wx = WeChatNotifier(provider=cfg.get("wechat_provider", "pushplus"), token=cfg.get("wechat_token"))
            results["wechat"] = wx.send_trade_signal(signal)

        if results["dingtalk"] or results["wechat"]:
            self._sent_cache.add(cache_key)

        # 存入历史信号文件
        self._record_signal(signal)
        return results

    def send_t0_signal(self, t0_data: Dict[str, Any], force: bool = False) -> Dict[str, bool]:
        """
        分发 A股 T+1 底仓日内做T交易卡片
        """
        symbol = t0_data.get("symbol", "")
        action = t0_data.get("t_action", "")
        # 按半小时粒度去重防刷
        now_slot = datetime.now().strftime("%Y-%m-%d_%H") + ("_1" if datetime.now().minute < 30 else "_2")
        cache_key = f"t0_{symbol}_{action}_{now_slot}"

        if not force and cache_key in self._sent_cache:
            return {"dingtalk": False, "wechat": False, "skipped": True}

        cfg = load_config()
        results = {"dingtalk": False, "wechat": False, "skipped": False}

        if cfg.get("dingtalk_enabled") and cfg.get("dingtalk_webhook"):
            dt = DingTalkNotifier(webhook=cfg.get("dingtalk_webhook"), secret=cfg.get("dingtalk_secret", ""))
            results["dingtalk"] = dt.send_t0_signal(t0_data)

        if cfg.get("wechat_enabled") and cfg.get("wechat_token"):
            wx = WeChatNotifier(provider=cfg.get("wechat_provider", "pushplus"), token=cfg.get("wechat_token"))
            results["wechat"] = wx.send_t0_signal(t0_data)

        if results["dingtalk"] or results["wechat"]:
            self._sent_cache.add(cache_key)

        # 转换并记录做T流水
        sig_record = {
            "symbol": symbol,
            "name": t0_data.get("name", ""),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "price": t0_data.get("price", 0.0),
            "signal_type": "T0_" + action,
            "signal_desc": t0_data.get("t_type", "日内做T"),
            "score": t0_data.get("confidence", 80),
            "reasons": t0_data.get("reasons", [])
        }
        self._record_signal(sig_record)
    def send_t0_close_reminder(self, holdings: List[Dict[str, Any]]) -> Dict[str, bool]:
        """向微信与钉钉分发 14:45 尾盘做T强制平仓与对冲核对提醒卡片"""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_key = f"t0_closeout_reminder_{today}"
        if cache_key in self._sent_cache:
            return {"dingtalk": False, "wechat": False, "skipped": True}

        cfg = load_config()
        results = {"dingtalk": False, "wechat": False, "skipped": False}
        if cfg.get("dingtalk_enabled") and cfg.get("dingtalk_webhook"):
            dt = DingTalkNotifier(webhook=cfg.get("dingtalk_webhook"), secret=cfg.get("dingtalk_secret", ""))
            results["dingtalk"] = dt.send_t0_close_reminder(holdings)

        if cfg.get("wechat_enabled") and cfg.get("wechat_token"):
            wx = WeChatNotifier(provider=cfg.get("wechat_provider", "pushplus"), token=cfg.get("wechat_token"))
            results["wechat"] = wx.send_t0_close_reminder(holdings)

        if results["dingtalk"] or results["wechat"]:
            self._sent_cache.add(cache_key)

        return results

    def send_markdown_card(self, title: str, content: str) -> Dict[str, bool]:
        """向已配置的微信与钉钉通道分发通用Markdown卡片（用于每日收盘复盘报告）"""
        cfg = load_config()
        results = {"dingtalk": False, "wechat": False}

        # 钉钉推送
        if cfg.get("dingtalk_enabled") and cfg.get("dingtalk_webhook"):
            dt = DingTalkNotifier(webhook=cfg.get("dingtalk_webhook"), secret=cfg.get("dingtalk_secret", ""))
            results["dingtalk"] = dt.send_markdown(title, content)

        # 微信推送
        if cfg.get("wechat_enabled") and cfg.get("wechat_token"):
            wx = WeChatNotifier(provider=cfg.get("wechat_provider", "pushplus"), token=cfg.get("wechat_token"))
            results["wechat"] = wx.send_markdown(title, content)

        return results

    def _record_signal(self, signal: Dict[str, Any]):
        try:
            history = []
            if SIGNALS_FILE.exists():
                with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            
            sig_copy = signal.copy()
            sig_copy["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # 最多保留前 500 条历史信号
            history.insert(0, sig_copy)
            history = history[:500]

            with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"写入信号历史失败: {e}")

    def send_test_message(self) -> Dict[str, bool]:
        """发送测试消息，验证渠道是否配置正确"""
        mock_signal = {
            "symbol": "sh600519",
            "name": "贵州茅台 (测试消息)",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "price": 1400.0,
            "change_pct": 2.15,
            "signal_type": "BUY",
            "signal_desc": "测试买点信号",
            "score": 88,
            "reasons": [
                "这是一条系统测试消息，表明您的通知渠道配置完全正确！",
                "修正RSRS指标突破阀值，多头量价共振良好",
                "系统正在本地平稳监控A股主板市场"
            ],
            "trade_levels": {
                "entry_price": 1400.0,
                "initial_stop": 1330.0,
                "stop_pct": 5.0,
                "target_price": 1550.0,
                "reward_pct": 10.7,
                "risk_reward_ratio": 2.14
            }
        }
        return self.send_signal(mock_signal, force=True)

notification_manager = NotificationManager()
