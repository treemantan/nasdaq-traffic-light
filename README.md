# Macro Regime Radar

中文优先的宏观跨资产风险仪表盘。项目不把市场机械地简化为“红灯看空、绿灯看多”，而是结合权益、波动率、利率、美元、信用、流动性、新闻事件和 UK 可交易 ETF，解释当前市场状态及其变化。

## 核心能力

- 宏观 regime、流动性状态、收益率驱动归因和跨资产一致性判断
- Nasdaq 100、S&P 500、Russell 2000、VIX、VVIX、MOVE、DXY、黄金、油价、信用利差和美债监控
- Short Premium 环境过滤器，覆盖 cash-secured put、bull put spread、bear call spread 与 iron condor 的宏观环境筛选，不提供交易指令
- UK 可交易 ETF 的估值、趋势、拥挤度、流动性、相关性和 beta 面板
- Options Gamma / Dealer Hedging 启发式监控，覆盖 SPY、QQQ、ETF 观察池和实际持仓
- Options Sentiment / Short Premium Context，按当前持仓与关注 ticker 拉取 Alpha Vantage 免费 put-call ratio，辅助判断 put-side、call-side 或双边卖权利金环境
- Revolut statement 组合导入、GBP 参考估值、AI/HBM 持仓穿透和回撤风险复核
- Serenity 私人持仓周报：每周从红色预警、核心仓位、AI/半导体链和临近事件中筛选重点复核对象
- MAG7 企业资本关系图谱，区分具名股权投资、附条件投资权利、战略合作与聚合披露
- GitHub Actions 每次运行后独立检查市场冲击，触发急跌/波动率扩张时发送紧急风险警报
- 本地、Windows Task Scheduler、GitHub Actions、OneDrive Graph 导入和邮件发送

## 快速开始

```powershell
python -m market_report --config config.example.json --dry-run
```

输出文件：

```text
output/market-report-YYYY-MM-DD.html
output/market-report-YYYY-MM-DD.json
```

## 本地一键同步运行

双击 `run_full_local_pipeline.bat` 会执行接近 GitHub Actions 的本地流程：

- 复制 OneDrive 中的 Revolut / IBKR statement 到 `.cloud-statements`
- 如 `secrets/local_pipeline.env` 存在 IBKR Flex 配置，则先尝试下载最新 IBKR Flex 数据
- 导入 `.cloud-statements` 中的 CSV/XML statement，自动去重
- 生成本地报告，默认 dry-run，不发送邮件
- 日志写入 `logs/full-local-pipeline-YYYY-MM-DD.log`

IBKR Flex 使用与 GitHub Actions Secrets 同名的本地配置项，不需要写入 Windows 永久环境变量。配置文件为 `secrets/local_pipeline.env`，该目录已被 git 忽略，不会提交到 GitHub：

```text
IBKR_FLEX_TOKEN=你的 IBKR Flex token
IBKR_ACTIVITY_QUERY_ID=1531778
IBKR_ACTIVITY_LIGHT_QUERY_ID=你的 light activity query id
IBKR_TRADE_CONFIRM_QUERY_ID=1535495
```

双击 `run_full_local_pipeline.bat` 会自动读取这个文件。若文件不存在或 token 为空，会跳过 IBKR Flex 实时下载，并使用 OneDrive 里最新的手动导出文件兜底。若要本地发送邮件：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_full_local_pipeline.ps1 -ProjectDir . -ConfigPath config.email.json -SendEmail
```

## 文档导航

- [自动化、邮件与 OneDrive 云端导入](docs/AUTOMATION.md)
- [UK ETF 观察池、估值与组合导入](docs/ETF_AND_PORTFOLIO.md)
- [方法论：评分、相似环境、walk-forward 与 MAD 自适应校准](docs/METHODOLOGY.md)
- [评分解释、Iron Condor 上下文与现金/短债框架](docs/SCORING_EXPLANATION.md)
- [数据源、缓存与回退机制](docs/DATA_SOURCES.md)
- [组合行情缓存与降级机制](docs/PORTFOLIO_QUOTE_CACHE.md)
- [MAG7 企业资本关系图谱与后续地缘政治辅助分](docs/MAG7_CAPITAL_NETWORK.md)
- [Serenity 私人持仓周报](docs/SERENITY_WEEKLY.md)
- [Technical Swing Analysis 技术波段观察](docs/TECHNICAL_SWING.md)
- [Agentic Event Radar 路线图](docs/AGENTIC_EVENT_RADAR_ROADMAP.md)

点击下方链接可打开对应文档。Codex 本地预览可能会调用系统默认 Markdown 应用；GitHub 中可直接跳转。

## 关于持仓回撤观察

组合面板会显示距年内高点回撤。黄色观察阈值为 `max(5%, 1σ月度波动)`，红色观察阈值为 `max(10%, 2σ月度波动)`；同时结合 `SMA200`、稳健波动率和直接 ticker 新闻事件，区分：

- 常态波动
- 正常回调观察
- 需要复核
- 趋势破坏风险

它是风险管理提示，不是机械加减仓信号。详细逻辑见 [ETF 与组合文档](docs/ETF_AND_PORTFOLIO.md)。

## 关于相关性与 Beta

相关性 `ρ` 衡量“像不像”，范围为 `-1` 到 `+1`。`ρ` 越接近 `+1`，说明该 ETF 或持仓最近 60 个交易日越倾向于和对应因子同涨同跌；越接近 `-1`，说明越倾向于反向变化；接近 `0` 则表示关系不稳定。

Beta 衡量“有多敏感”。报告中的近似回归形式为：

```text
ETF_return = alpha + beta × factor_return + error
```

因此 Nasdaq beta `1.2` 可以理解为：过去 60 日里，Nasdaq 100 日涨跌 `1%` 时，该资产平均约涨跌 `1.2%`。它不是 alpha，也不等于相关性。两者关系可以写成：

```text
beta = ρ × (资产波动率 / 因子波动率)
```

所以 `ρ=0.8`、Nasdaq beta `1.2` 的含义是：资产与 Nasdaq 同步性较高，同时自身波动率约为 Nasdaq 的 `1.5` 倍。相关性说明方向跟随程度，Beta 说明放大或缩小倍数；二者都是最近 60 日统计关系，不代表未来因果或交易信号。

## 关于 Short Premium 与 Options Gamma

Short Premium 环境过滤器先用 VIX、VVIX、MOVE、指数单日波动、美元、利率和信用利差判断整体卖波动环境；Options Sentiment 面板再按 `SPY`、`QQQ`、当前持仓和 `options_sentiment.tickers` 里的关注标的读取 Alpha Vantage 免费 put-call ratio，给出 ticker-level context。输出用于区分 cash-secured put / bull put spread / bear call spread / iron condor 的环境偏向，不构成期权交易建议。

Options Gamma / Dealer Hedging 模块使用免费期权链里的 open interest、成交量、bid/ask/last 和 Black-Scholes gamma 近似，估计“OI 隐含 gamma 暴露”和可能的 dealer hedging 压力。它默认覆盖 `SPY`、`QQQ`、ETF 观察池和实际持仓；英国 UCITS ETF 通常没有可用期权链，会显示为数据不足而不是强行估算。

默认数据源顺序为 `Yahoo/yfinance -> Alpha Vantage`。模块会先尝试 Yahoo JSON option-chain endpoint；如果遇到 401/session/cookie 限制，则回退到 `yfinance` 获取同一类期权链字段。Alpha Vantage `HISTORICAL_OPTIONS` 属于 premium option-chain endpoint，只保留给显式配置且具备 premium 权限的 key；免费 put-call ratio 与 volume-to-open-interest ratio endpoint 可用于情绪监控，但不足以计算 strike-level gamma。

该模块只能作为启发式监控：成交靠近 ask 会被视为可能的买方发起，靠近 bid 会被视为可能的卖方发起；大额 OTM call/put 买入更偏负 gamma、可能放大方向波动；高 OI 行权价附近且缺少方向性流量时，更偏 pinning/磁吸观察。报告不会声称直接知道 dealer book。

## 关于 MAD

MAD 是“中位绝对偏差”，用于让不同 ETF 的相似环境尺度自动适配自身历史波动。它比普通标准差更不容易被少量极端行情扭曲。详细公式、例子和防止未来信息泄漏的约束见 [方法论文档](docs/METHODOLOGY.md)。

## 免责声明

本工具用于宏观市场监控与研究参考，不构成投资建议，也不构成期权交易建议。
