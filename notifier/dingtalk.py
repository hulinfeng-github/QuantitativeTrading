"""
钉钉群机器人推送模块
支持：Webhook + 安全加签验证 + Markdown富文本决策卡片
"""
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
from typing import Dict, Any

class DingTalkNotifier:
    def __init__(self, webhook: str = "", secret: str = ""):
        self.webhook = webhook.strip()
        self.secret = secret.strip()

    def _get_signed_url(self) -> str:
        """根据secret计算加签签名"""
        if not self.secret:
            return self.webhook
        timestamp = str(round(time.time() * 1000))
        secret_enc = self.secret.encode('utf-8')
        string_to_sign = f'{timestamp}\n{self.secret}'
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        
        delim = "&" if "?" in self.webhook else "?"
        return f"{self.webhook}{delim}timestamp={timestamp}&sign={sign}"

    def send_markdown(self, title: str, text: str) -> bool:
        """发送Markdown格式通知"""
        if not self.webhook:
            return False
        url = self._get_signed_url()
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text
            }
        }
        try:
            resp = requests.post(url, json=payload, timeout=5)
            res = resp.json()
            if res.get("errcode") == 0:
                return True
            else:
                print(f"钉钉发送失败: {res}")
                return False
        except Exception as e:
            print(f"钉钉网络请求异常: {e}")
            return False

    def send_trade_signal(self, signal: Dict[str, Any]) -> bool:
        """发送交易信号卡片"""
        name = signal.get("name", "")
        code = signal.get("symbol", "").replace("sh", "").replace("sz", "")
        signal_type = signal.get("signal_type", "BUY")
        signal_desc = signal.get("signal_desc", "波段买点")
        price = signal.get("price", 0.0)
        change_pct = signal.get("change_pct", 0.0)
        score = signal.get("score", 0)
        levels = signal.get("trade_levels", {})
        reasons = signal.get("reasons", [])

        color = "#e53e3e" if signal_type == "BUY" else ("#dd6b20" if signal_type == "WATCH" else "#3182ce")
        badge = "🔥 强力买点" if signal_type == "BUY" else ("👀 蓄势关注" if signal_type == "WATCH" else "⚠️ 减仓预警")

        reasons_md = "\n".join([f"- {r}" for r in reasons])

        markdown_text = f"""### {badge}：{name} ({code})
> **量化综合评分**：`{score}分` | **当前现价**：`{price:.2f}元` ({change_pct:+.2f}%)

---
#### 🎯 交易风控参考点位
- **建议买入区间**：`{price:.2f}元` 附近
- **初始防守止损**：`{levels.get('initial_stop', 0):.2f}元` (-{levels.get('stop_pct', 0)}%)
- **波段目标止盈**：`{levels.get('target_price', 0):.2f}元` (+{levels.get('reward_pct', 0)}%)
- **盈亏比(R:R)**：`1 : {levels.get('risk_reward_ratio', 2.5)}`

#### 📊 策略研判逻辑 (RSRS + 量价共振)
{reasons_md}

> *A股主板量化波段系统（非频繁交易，半自动辅助研判）*
"""
        return self.send_markdown(title=f"【A股量化】{name} 触发{signal_desc}", text=markdown_text)

    def send_t0_signal(self, t0_data: Dict[str, Any]) -> bool:
        """发送 A股 T+1 底仓日内做T交易卡片"""
        name = t0_data.get("name", "")
        code = t0_data.get("symbol", "").replace("sh", "").replace("sz", "")
        action = t0_data.get("t_action", "")
        t_type = t0_data.get("t_type", "")
        price = t0_data.get("price", 0.0)
        vwap = t0_data.get("vwap", 0.0)
        bias = t0_data.get("bias", 0.0)
        shares = t0_data.get("suggested_shares", 100)
        target = t0_data.get("target_price", 0.0)
        stop = t0_data.get("stop_price", 0.0)
        spread = t0_data.get("expected_spread_pct", 0.0)
        pivots = t0_data.get("pivots", {})
        reasons_md = "\n".join([f"- {r}" for r in t0_data.get("reasons", [])])

        badge = "⚡ 【A股日内正T·低吸买点】" if action == "BUY_T" else "🎯 【A股日内倒T·高抛卖点】"

        text = f"""### {badge} {name} ({code})
> **分时现价**：`{price:.2f}元` | **均价线(VWAP)**：`{vwap:.2f}元` | **偏离度**：`{bias:+.2f}%`

---
#### 🔄 T+1 底仓做T建议
- **做T方向**：`{t_type}`
- **建议操作股数**：`{shares} 股` (利用已有底仓对冲)
- **建议执行价格**：`{price:.2f} 元` 附近
- **预期对冲平仓价**：`{target:.2f} 元` (预期日内价差: `+{spread}%`)
- **防守保护价**：`{stop:.2f} 元`

#### 🧭 日内枢轴点位 (Pivot Points)
- 压力位 R1/R2: `{pivots.get('r1')}元 / {pivots.get('r2')}元`
- 支撑位 S1/S2: `{pivots.get('s1')}元 / {pivots.get('s2')}元`

#### 💡 做T触发依据
{reasons_md}

> ⚠️ *重要提示：A股执行T+1，请务必于当日14:50前完成等量对冲平仓，严格保持总持股数量不变！*
"""
        return self.send_markdown(title=f"【日内做T】{name} 触发{action}", text=text)
