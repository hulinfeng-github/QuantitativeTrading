"""
微信消息推送模块
支持：PushPlus(推送加)、Server酱(ServerChan)、企业微信机器人(WeCom)
"""
import requests
from typing import Dict, Any

class WeChatNotifier:
    def __init__(self, provider: str = "pushplus", token: str = ""):
        self.provider = provider.lower().strip()
        self.token = token.strip()

    def send_trade_signal(self, signal: Dict[str, Any]) -> bool:
        if not self.token:
            return False

        name = signal.get("name", "")
        code = signal.get("symbol", "").replace("sh", "").replace("sz", "")
        signal_type = signal.get("signal_type", "BUY")
        signal_desc = signal.get("signal_desc", "波段买点")
        price = signal.get("price", 0.0)
        change_pct = signal.get("change_pct", 0.0)
        score = signal.get("score", 0)
        levels = signal.get("trade_levels", {})
        reasons = signal.get("reasons", [])

        title = f"【A股量化】{name}({code}) 触发{signal_desc} - 现价{price:.2f}元"
        badge = "🔥 强力波段买点" if signal_type == "BUY" else ("👀 蓄势突破关注" if signal_type == "WATCH" else "⚠️ 减仓避险预警")

        reasons_text = "\n".join([f"• {r}" for r in reasons])

        content = f"""### {badge}：{name} ({code})
- **量化评分**：{score} 分
- **当前最新价**：{price:.2f} 元 ({change_pct:+.2f}%)
- **建议止损位**：{levels.get('initial_stop', 0):.2f} 元 (-{levels.get('stop_pct', 0)}%)
- **目标止盈位**：{levels.get('target_price', 0):.2f} 元 (+{levels.get('reward_pct', 0)}%)
- **盈亏比**：1 : {levels.get('risk_reward_ratio', 2.5)}

#### 研判理由：
{reasons_text}

---
*A股主板量化波段系统（本地运行）*
"""

        if self.provider == "pushplus":
            return self._send_pushplus(title, content)
        elif self.provider == "serverchan":
            return self._send_serverchan(title, content)
        elif self.provider == "wecom":
            return self._send_wecom(title, content)
        return False

    def send_markdown(self, title: str, content: str) -> bool:
        """发送自定义Markdown格式通知（供收盘复盘报告等推送使用）"""
        if not self.token:
            return False
        if self.provider == "pushplus":
            return self._send_pushplus(title, content)
        elif self.provider == "serverchan":
            return self._send_serverchan(title, content)
        elif self.provider == "wecom":
            return self._send_wecom(title, content)
        return False

    def send_t0_signal(self, t0_data: Dict[str, Any]) -> bool:
        if not self.token:
            return False

        name = t0_data.get("name", "")
        code = t0_data.get("symbol", "").replace("sh", "").replace("sz", "")
        action = t0_data.get("t_action", "")
        t_type = t0_data.get("t_type", "")
        price = t0_data.get("price", 0.0)
        vwap = t0_data.get("vwap", 0.0)
        bias = t0_data.get("bias", 0.0)
        shares = t0_data.get("suggested_shares", 100)
        target = t0_data.get("target_price", 0.0)
        spread = t0_data.get("expected_spread_pct", 0.0)
        reasons_text = "\n".join([f"• {r}" for r in t0_data.get("reasons", [])])

        badge = "⚡ 【A股日内正T·低吸买点】" if action == "BUY_T" else "🎯 【A股日内倒T·高抛卖点】"
        title = f"【日内做T】{name}({code}) 现价{price:.2f}元 (偏离均线{bias:+.1f}%)"

        content = f"""### {badge} {name} ({code})
- **分时现价**：{price:.2f} 元
- **分时均价(VWAP)**：{vwap:.2f} 元 (偏离: {bias:+.2f}%)
- **操作方向**：{t_type}
- **建议做T股数**：{shares} 股 (利用已有底仓对冲)
- **目标对冲平仓价**：{target:.2f} 元 (预期做T差价: +{spread}%)

#### 研判理由：
{reasons_text}

---
*提示：A股T+1规则，请于当日收盘前完成等量平仓！*
"""
        if self.provider == "pushplus":
            return self._send_pushplus(title, content)
        elif self.provider == "serverchan":
            return self._send_serverchan(title, content)
        elif self.provider == "wecom":
            return self._send_wecom(title, content)
        return False

    def _send_pushplus(self, title: str, content: str) -> bool:
        url = "http://www.pushplus.plus/send"
        payload = {
            "token": self.token,
            "title": title,
            "content": content,
            "template": "markdown"
        }
        try:
            resp = requests.post(url, json=payload, timeout=6)
            res = resp.json()
            return res.get("code") == 200
        except Exception as e:
            print(f"PushPlus微信推送异常: {e}")
            return False

    def _send_serverchan(self, title: str, content: str) -> bool:
        url = f"https://sctapi.ftqq.com/{self.token}.send"
        payload = {
            "title": title,
            "desp": content
        }
        try:
            resp = requests.post(url, data=payload, timeout=6)
            res = resp.json()
            return res.get("code") == 0
        except Exception as e:
            print(f"Server酱推送异常: {e}")
            return False

    def _send_wecom(self, title: str, content: str) -> bool:
        url = self.token if self.token.startswith("http") else f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={self.token}"
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"## {title}\n{content}"
            }
        }
        try:
            resp = requests.post(url, json=payload, timeout=6)
            res = resp.json()
            return res.get("errcode") == 0
        except Exception as e:
            print(f"企业微信推送异常: {e}")
            return False
