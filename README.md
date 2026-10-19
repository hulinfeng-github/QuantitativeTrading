# 🚀 A股主板顶级量化波段分析与预警系统

一套专为 **A股主板市场**（沪市60/深市00）量身打造的**中低频波段量化研判与半自动预警系统**，在本地电脑极速运行，免去频繁短线操作的心理消耗与高昂摩擦成本，追求收益风险比最大化。

---

## 🌟 核心特性

1. **严格主板权限适配**：
   - 自动过滤创业板（300xxx）、科创板（688xxx）、北交所（8/4/920xxx）及 ST/退市等高风险标的，专为主板权限设计。
2. **顶层数学模型（修正 RSRS 模型）**：
   - 基于光大证券金工团队经典研报的**阻力支撑相对强度（RSRS）**算法，利用每日最高价和最低价进行 OLS 线性回归斜率拟合，结合滑动窗口 $Z\text{-score}$ 与判定系数 $R^2$ 动态修正。
   - 敏锐捕捉主力资金推升阻力的扎实度与突破拐点，过滤虚假突破。
3. **多周期共振与中低频波段交易**：
   - **不频繁交易**：持股周期通常在数天至数周，捕捉确定性大波段。
   - 严格遵循周日均线顺势原则（收盘站上 MA20 生命线与 MA60 牛熊线，均线多头排列）与 MACD 动能加速。
4. **自适应 ATR 风控与移动止盈（Trailing Stop）**：
   - 进场根据日线 ATR 自适应测算硬止损位（给足波动缓冲区，防止被主力洗盘震出）。
   - 获利冲高后自动启动**保本止损**与**最高点回撤移动止盈**，杜绝坐过山车。
5. **钉钉与微信双通道决策卡片推送**：
   - 支持**钉钉机器人**（Webhook + 加签验证）。
   - 支持**微信推送**（PushPlus 微信模板消息、Server酱、企业微信）。
   - 发现买点自动推送结构化交易决策卡片：现价、买入评分、触发理由、建议止损位、预期目标位。
6. **A股 T+1 底仓日内做T量化助手 (Intraday T+0)**：
   - 专为 A 股 T+1 交易规则设计：针对已有底仓的持仓股，实时计算**分时成交均价线 (VWAP)** 与价格偏离度 (Bias)。
   - **正T（先买后卖）**：负偏离极端超卖（$\le -1.5\%$）且触及日内枢轴支撑 S1/S2 时提示低吸，冲高卖出等量底仓，锁定差价降低成本。
   - **倒T（先卖后买）**：早盘脉冲急拉正偏离超买（$\ge +2.0\%$）且遇阻 R1/R2 时先高抛部分底仓，跳水回踩均线买回，保住股份摊薄成本。
   - 自动生成专属日内做T决策卡片推送到钉钉/微信，附带 14:50 强制等量平仓安全纪律提醒。
7. **现代化本地 Web 暗黑金融控制台**：
   - 科技暗黑终端风格，提供全市场选股雷达、盘中自选股实时行情、A股T+1日内做T雷达、每日收盘复盘与自迭代面板、单股深度量化诊断与高精 HTML5 Canvas K线/RSRS 指标渲染。
8. **收盘全景复盘与策略闭环自我迭代 (Review & Self-Optimization Engine)**：
   - **每日 15:20 自动复盘**：交易日收盘后自动激活全链路分析，无需人工盯盘。
   - **大盘多空定性**：量化诊断上证指数与沪深300均线结构与量比，自适应输出仓位上限建议。
   - **持仓深度体检**：收盘逐笔核算浮盈、止损安全边际与移动止盈保利距离。
   - **信号客观回访**：对近10日 BUY 与做T信号进行客观追踪，统计真实胜率与平均收益，绝无未来函数。
   - **自适应自迭代微调**：根据胜率与大盘周期，系统自动自适应微调 RSRS 买入门槛与风控参数，形成完全自学习闭环！
   - **报告自动推送**：自动组装结构化 Markdown 富文本长文卡片直推手机微信与钉钉群。

---

## 📐 核心数学公式

### 1. 修正 RSRS 算法
- 对过去 $N$ 天（默认 $18$ 天）的高低价做滑动回归：
  $$High_i = \alpha + \beta \cdot Low_i + \epsilon_i$$
- 判定系数 $R^2$：
  $$R^2 = 1 - \frac{\sum (High_i - \hat{High}_i)^2}{\sum (High_i - \bar{High})^2}$$
- 滑动窗口 $M$ 天（默认 $600$ 天）标准化：
  $$Z_{\beta} = \frac{\beta - \mu_\beta}{\sigma_\beta}$$
- 修正 RSRS：
  $$RSRS_{mod} = Z_{\beta} \times R^2$$
  *当 $RSRS_{mod} \ge 0.7$ 且价格位于 MA20 上方时，触发强力波段买点！*

### 2. A股 T+1 日内做T分时均价 (VWAP) 与偏离度模型
- 分时成交均价 (Volume Weighted Average Price)：
  $$\text{VWAP}_t = \frac{\sum_{i=1}^t (\text{Price}_i \times \text{Volume}_i)}{\sum_{i=1}^t \text{Volume}_i}$$
- 分时均线偏离度 (Bias)：
  $$\text{Bias}_t = \frac{\text{Price}_t - \text{VWAP}_t}{\text{VWAP}_t} \times 100\%$$
- 日内枢轴点 (Pivot Points)：
  - 轴心价 $P = (\text{High} + \text{Low} + \text{PrevClose}) / 3$
  - 阻力 $R_1 = 2P - \text{Low}$，支撑 $S_1 = 2P - \text{High}$

---

## 🛠️ 安装与运行指南

### 1. 安装依赖
在项目根目录下打开命令行终端（推荐使用 `python -m pip` 避免 Windows 路径缓存冲突）：
```bash
python -m pip install -r requirements.txt
```

### 2. 启动系统（本地 Web 控制台）
```bash
python main.py
```   
启动后，打开浏览器访问：
👉 **http://127.0.0.1:8088**

即可体验完整的仪表盘、自选股管理与图表分析！

### 3. 命令行快捷操作
- **立即执行一次全市场主板选股并在终端输出**：
  ```bash
  python main.py --scan
  ```
- **运行系统全自动化自测自检套件 (100%全链路覆盖)**：
  ```bash
  python test_suite.py
  ```
- **历史真实数据量化回测（严格防未来函数 + 防过拟合检验）**：
  ```bash
  # 回测指定股票（如工业富联 601138，近 500 个交易日）
  python main.py --backtest --symbol 601138 --days 500

  # 批量对 A股主板核心标的池进行多标的交叉回测检验
  python main.py --backtest
  ```
- **测试钉钉/微信推送是否通畅**：
  ```bash
  python main.py --notify
  ```
- **立即执行一次收盘全景复盘与参数自我迭代 (终端输出 Markdown 长文)**：
  ```bash
  python main.py --review
  ```

---

## 📱 消息推送配置指引（微信 / 钉钉）

在 Web 界面的「⚙️ 策略与推送配置」中即可直接输入，无需修改代码：

### 1. 钉钉群机器人
1. 打开任意钉钉群 -> 群设置 -> **智能群助手** -> **添加机器人** -> **自定义**。
2. 安全设置推荐勾选 **加签**，复制生成的 `Webhook` 和 `Secret`。
3. 填入系统设置并点击保存即可。

### 2. 微信推送（推荐 PushPlus）
1. 微信搜索关注微信公众号 **PushPlus 推送加**（无需下载APP）。
2. 在其官网 [pushplus.plus](https://www.pushplus.plus) 微信一键登录，获取你的 **Token**。
3. 在系统设置中选择 `PushPlus`，填入 Token 保存。
4. 点击「🔔 发送测试推送到微信/钉钉」，手机微信即可立刻收到弹窗卡片！

---

## 🔒 安全与隐私保护 (零敏感信息泄露设计)

本项目遵循**配置与代码分离、开箱即用、隐私零泄露**的安全设计原则：
1. **真实数据永不上云**：
   - 您的个人持仓与成本记录（`storage/watchlist.json`）、钉钉/微信推送密钥（`storage/user_config.json`）、历史回测流水与复盘日志已在 `.gitignore` 中被**严格全局忽略**，永远不会被 `git push` 上传到 GitHub。
2. **开箱即用，自动初始化**：
   - 新用户首次通过 `git clone` 检出项目并启动（`python main.py`）时，系统会自动在本地构建默认配置和初始核心观察池，无需繁琐的手动配置。
3. **三种极简配置方式**：
   - **方式一（推荐·界面操作）**：直接打开 Web 控制台 `http://127.0.0.1:8088`，进入「⚙️ 策略与推送配置」输入自己的钉钉 Webhook 或微信 Token，本地自动加密落盘保存。
   - **方式二（模板复制）**：参考 `storage/user_config.json.example` 与 `storage/watchlist.json.example` 复制为本地 JSON 文件自行微调。
   - **方式三（环境变量 / .env）**：复制 `.env.example` 为 `.env`，配置 `DINGTALK_WEBHOOK` 等变量，适合服务器/Docker 容器化部署。

---

## 📁 目录架构说明

```
QuantitativeTrading/
├── main.py               # 系统主入口（集成 Web、选股、回测、复盘命令行）
├── test_suite.py         # 全链路高覆盖度自动化测试套件
├── config.py             # 配置管理（用户自选、策略阈值、推送密钥）
├── requirements.txt      # 依赖环境清单
├── .env.example          # 环境变量配置模板
├── .gitignore            # 严格的安全过滤规则（杜绝持仓与密钥外泄）
├── core/
│   ├── data_fetcher.py   # A股主板过滤与腾讯极速行情/日K获取
│   ├── indicators.py     # 数学指标库（OLS回归拟合、RSRS修正、ATR、MACD）
│   ├── strategy.py       # 核心波段量化策略与多因子共振评分
│   ├── risk_manager.py   # ATR自适应风控与最高价回撤移动止盈止损
│   ├── backtester.py     # 严格因果回测引擎（防未来函数 + 样本外盲测过拟合度量）
│   ├── t0_strategy.py    # A股 T+1 底仓日内做T分时偏离引擎
│   └── review_engine.py  # A股收盘全景量化复盘与闭环自我迭代引擎
├── notifier/
│   ├── dingtalk.py       # 钉钉机器人富文本Markdown卡片推送
│   ├── wechat.py         # 微信推送（PushPlus/Server酱/企业微信）
│   └── manager.py        # 统一推送中心（带防骚扰去重与信号流水记录）
├── scheduler/
│   └── task_runner.py    # 自动化调度器（盘中监控、做T、15:20收盘复盘、盘后全市场自动选股）
├── web/
│   ├── app.py            # FastAPI RESTful API 接口服务
│   └── static/           # 前端暗黑金融终端界面 (HTML5 + CSS3 + Canvas)
└── storage/              # 本地数据存储（在 .gitignore 中保护）
    ├── .gitkeep
    ├── user_config.json.example   # 安全无敏感信息的配置模板
    ├── watchlist.json.example     # 安全无敏感信息的自选持仓模板
    └── main_board_stocks.json     # 全市场主板股票池离线缓存（公开数据）
```
