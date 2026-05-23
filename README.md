# Nasdaq Traffic Light

中文优先的宏观跨资产风险仪表盘。它不是简单的“红灯看空、绿灯看多”，而是尝试识别宏观 regime、利率敏感度、美元流动性、波动率压力、风险偏好与跨资产一致性。

## 已实现能力

- 权益：Nasdaq 100、标普500、罗素2000
- 情绪与波动：CNN Fear & Greed、NAAIM、VIX、VVIX、MOVE
- 利率：美国2年期、10年期、2s10s期限利差、实际利率、10年盈亏平衡通胀率
- 外汇与商品：DXY、GBP/USD、USD/JPY、黄金、WTI原油
- 信用与流动性：高收益信用利差、美联储资产负债表、RRP、TGA、银行准备金
- 数据韧性：重试、本地缓存、最新有效观察值、异常区间校验、核心/辅助指标分层
- 解释层：宏观 regime、流动性 regime、收益率驱动归因、跨资产一致性、置信度、known unknowns
- 策略环境过滤：Iron Condor 环境过滤器，仅评估区间型卖波动环境，不提供交易建议

## 本地生成报告

```powershell
python -m market_report --config config.example.json --dry-run
```

报告会写入：

```text
output/market-report-YYYY-MM-DD.html
output/market-report-YYYY-MM-DD.json
```

其中 JSON 是结构化评分对象，供云端轻量邮件使用；HTML 是完整仪表盘。

## 本地邮件发送

复制配置模板：

```powershell
Copy-Item config.example.json config.json
```

编辑 `config.json` 的 `email` 配置，然后设置 SMTP 密码环境变量：

```powershell
$env:SMTP_PASSWORD="你的应用专用密码"
python -m market_report --config config.json
```

本地 Gmail / SMTP 流程仍然保留；GitHub Actions 云端流程使用 Resend。

## GitHub Actions 云端自动化（Resend）

云端自动化文件：

```text
.github/workflows/daily-market-report.yml
```

它会在 GitHub Actions 中生成报告、上传 artifact，并按 `EMAIL_MODE` 决定是否发送邮件。

需要在 GitHub repository 的 `Settings -> Secrets and variables -> Actions` 中设置：

- `RESEND_API_KEY`：Resend API key
- `REPORT_EMAIL_TO`：收件人邮箱，多个地址用英文逗号分隔
- `REPORT_EMAIL_FROM`：Resend 已验证的发件地址或域名邮箱

如果没有自己的域名，也可以改用 Gmail SMTP。设置以下 repository secrets：

- `EMAIL_PROVIDER`：填 `smtp`
- `REPORT_EMAIL_TO`：收件人邮箱，多个地址用英文逗号分隔
- `SMTP_USERNAME`：Gmail 地址
- `SMTP_PASSWORD`：Gmail App Password，不是网页登录密码
- `SMTP_FROM`：可选，默认使用 `SMTP_USERNAME`
- `SMTP_HOST`：可选，默认 `smtp.gmail.com`
- `SMTP_PORT`：可选，默认 `587`
- `SMTP_SECURITY`：可选，默认 `starttls`

使用 SMTP 时不需要 `RESEND_API_KEY` 或 `REPORT_EMAIL_FROM`。如果 `EMAIL_PROVIDER` 不设置，默认仍走 Resend。

邮件模式：

- `none`：只生成报告并上传 artifact，不发送邮件
- `pulse`：发送轻量 Market Pulse，包含综合风险分、宏观 regime、关键风险变化和 Iron Condor 环境
- `volatility`：发送波动率 / Iron Condor regime 简报，重点回答短波动环境是否恶化
- `full`：发送完整 HTML 报告
- `auto`：根据 Europe/London 当前本地时间自动推断邮件模式

`auto` 的 UK 本地时间映射：

- `00:00-11:59`：`none`
- `12:00-16:29`：`pulse`
- `16:30-19:59`：`volatility`
- `20:00-23:59`：`full`

手动运行：

1. 打开 GitHub repo 的 `Actions`
2. 选择 `Daily Market Report`
3. 点击 `Run workflow`
4. 在 `email_mode` 中选择 `none`、`pulse`、`volatility`、`full` 或 `auto`

## UK 监控时间与夏令时

默认工作日 UK 监控节奏：

- 08:30 UK：生成报告，不发邮件
- 14:45 UK：生成报告并发送轻量 Market Pulse
- 18:00 UK：生成报告并发送 Volatility / Iron Condor regime 简报
- 21:15 UK：生成报告并发送完整 HTML 报告

英国夏令时规则是固定规则：三月最后一个周日 01:00 GMT 进入 BST，十月最后一个周日 02:00 BST 回到 GMT。GitHub Actions cron 只能使用 UTC，所以 workflow 为每个 UK 本地目标时间配置了两个 UTC 候选触发点，并在 `Resolve email mode` step 中用 `Europe/London` 时区计算当天真正对应的 UTC 时间。错误季节的候选触发会自动跳过，不需要手工改 cron。

每次运行会上传 artifact，名称格式为：

```text
market-report-<github.run_id>-<EMAIL_MODE>
```

## 数据说明

Yahoo Finance、Investing、CNN、NAAIM 与 FRED 用于不同类别的数据源。系统会对外部请求进行重试，并保存成功 fetch 到本地缓存。FRED 等低频经济序列使用最近有效 observation，不强制要求当天更新。

如果核心指标失败，系统会尝试 fallback 或新鲜缓存，并在 UI 中标记；如果辅助指标失败，系统会降低置信度但继续生成报告。系统不会静默把缓存伪装成实时数据。

## 免责声明

本工具用于宏观市场监控与研究参考，不构成投资建议，也不构成期权交易建议。Iron Condor 模块只评估市场环境是否适合区间型卖波动策略，不提供行权价、期限、仓位或交易指令。
## UK ETF监控器

报告包含一个面向英国可交易产品的 ETF 监控模块，用于观察你实际可能买到的 ETF 的趋势、估值可得性和短线拥挤度。默认资产池包括：

- `VUAG.L`：Vanguard S&P 500 UCITS ETF
- `CNX1.L`：iShares Nasdaq 100 UCITS ETF
- `SEMI.L`：iShares Global Semiconductors UCITS ETF
- `QWTM.L`：WisdomTree Quantum Computing UCITS ETF
- `QNTM.L`：VanEck Quantum Computing UCITS ETF
- `QANT.L`：iShares Quantum Computing UCITS ETF
- `SGLN.L`：iShares Physical Gold ETC

该模块抓取 ETF 日线价格并计算 `SMA13`、`SMA50`、`SMA200`、`RSI14`、1日/5日/1个月/3个月动量、距200日线百分比和拥挤度评分。拥挤度评分结合 RSI、距200日线、1个月动量和可用估值分位数，用于提示主题交易是否已经偏热或趋势是否仍待确认。

估值字段采用 best-effort 方式抓取，不会因为估值接口失败而阻断价格和趋势监控：

- `PE`：市盈率，衡量市场愿意为每单位盈利支付多少价格；对成长和科技 ETF 的利率敏感度判断较有用。
- `Forward PE`：基于未来盈利预期的市盈率，更贴近市场当前定价逻辑，但依赖分析师盈利预测。
- `PB`：市净率，衡量市值相对账面净资产；对金融、周期和重资产行业更有解释力，对半导体、AI、量子等轻资产主题 ETF 的解释力弱于 PE。

黄金 ETC 没有盈利和净资产口径，因此不展示 PE/PB，应结合实际利率、美元和金价趋势解释。PE/PB 历史分位数会通过本地缓存逐步积累；样本不足时报告会明确显示“样本不足”，避免制造假精确。
