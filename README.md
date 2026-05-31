# Macro Regime Radar

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
- 新闻与政策叙事：抓取白宫原文与 GDELT 新闻聚合，识别重要主题、方向、来源置信度和被点名公司 ticker；新闻层仅用于解释市场叙事，不直接改变量化评分
- 新闻语言处理：中文和英文标题直接展示；其他语言标题自动翻译为英文，原始标题保留在折叠审计详情中
- AI产业叙事：独立跟踪AI龙头公司、CEO表态、IPO、资本开支、数据中心、芯片与算力供应链新闻；公开公司显示 ticker，未上市公司显示实体名

## 本地生成报告

```powershell
python -m market_report --config config.example.json --dry-run
```

报告会写入：

```text
output/market-report-YYYY-MM-DD.html
output/market-report-YYYY-MM-DD.json
```

## 手机保存 Revolut statement：OneDrive inbox

推荐在手机中将 Revolut 导出的 CSV 保存到已经由 Windows OneDrive 客户端同步的固定目录：

```text
C:\Users\<Windows用户名>\OneDrive\Trading\Revolut Transaction Statement
```

项目根目录提供两个入口：

- `setup_onedrive_portfolio_inbox.bat`：创建 inbox 并注册工作日 `21:30` 本地定时导入任务。
- `run_onedrive_portfolio_report.bat`：立即从 OneDrive inbox 导入 statement 并刷新本地报告。

OneDrive 主账号、MFA 验证方式和 recovery 邮箱由 Windows OneDrive 客户端管理。脚本仅访问已经同步到本地的 CSV 文件，不保存 OneDrive 邮箱、密码、验证码或 OAuth token。

默认 inbox 可以直接保存每个账户的最新 CSV。为避免 statement 时间窗口重叠导致重复计算，请及时删除同一账户的旧导出。需要长期保留历史导出时，可以按账户建立子目录，并用 `scripts\run_portfolio_report.ps1 -UseLatestPerAccountFolder` 让脚本只选择每个账户目录中的最新 CSV。

后续可选增强：使用 Microsoft Graph API 从 OneDrive 私人目录读取最新 CSV，使 GitHub Actions 在本地电脑关机时也能更新持仓。该方案需要单独配置 OAuth 权限与 refresh token，目前版本不启用。

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
- `pulse`：发送轻量 Market Pulse，包含综合风险分、宏观 regime、关键风险变化、Iron Condor 环境和 UK ETF 开盘观察
- `volatility`：发送波动率 / Iron Condor regime 简报，重点回答短波动环境是否恶化
- `full`：发送完整 HTML 报告
- `auto`：根据 Europe/London 当前本地时间自动推断邮件模式

`auto` 的 UK 本地时间映射：

- `00:00-07:59`：`none`
- `08:00-16:29`：`pulse`
- `16:30-19:59`：`volatility`
- `20:00-23:59`：`full`

手动运行：

1. 打开 GitHub repo 的 `Actions`
2. 选择 `Macro Regime Radar`
3. 点击 `Run workflow`
4. 在 `email_mode` 中选择 `none`、`pulse`、`volatility`、`full` 或 `auto`

## UK 监控时间与夏令时

默认工作日 UK 监控节奏：

- 08:30 UK：生成报告并发送轻量 Market Pulse，包含 UK ETF 开盘观察
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

- `VWRL.L`：Vanguard FTSE All-World UCITS ETF
- `VUAG.L`：Vanguard S&P 500 UCITS ETF
- `ISF.L`：iShares Core FTSE 100 UCITS ETF
- `CNX1.L`：iShares Nasdaq 100 UCITS ETF
- `IITU.L`：iShares S&P 500 Information Technology Sector UCITS ETF
- `AINF.L`：iShares AI Infrastructure UCITS ETF
- `LAZR.L`：L&G Optical Technology & Photonics ESG Exclusions UCITS ETF
- `WTAI.L`：WisdomTree Artificial Intelligence UCITS ETF
- `AIAI.L`：L&G Artificial Intelligence UCITS ETF
- `SEMI.L`：iShares Global Semiconductors UCITS ETF
- `SMGB.L`：VanEck Semiconductor UCITS ETF
- `SEMG.L`：Amundi MSCI Semiconductors UCITS ETF
- `RBOT.L`：iShares Automation & Robotics UCITS ETF
- `WCLD.L`：WisdomTree Cloud Computing UCITS ETF
- `LOCK.L`：iShares Digital Security UCITS ETF
- `QWTM.L`：WisdomTree Quantum Computing UCITS ETF
- `QNTM.L`：VanEck Quantum Computing UCITS ETF
- `QANT.L`：iShares Quantum Computing UCITS ETF
- `CSKR.L`：iShares MSCI Korea UCITS ETF
- `HKOR.L`：HSBC MSCI Korea Capped UCITS ETF
- `FLRK.L`：Franklin FTSE Korea UCITS ETF
- `IGTM.L`：iShares $ Treasury Bond 7-10yr UCITS ETF GBP Hedged
- `DFND.L`：iShares Global Aerospace & Defence UCITS ETF
- `WDEF.L`：WisdomTree Europe Defence UCITS ETF
- `DFNG.L`：VanEck Defense UCITS ETF
- `NATO.L`：HANetf Future of Defence UCITS ETF
- `DFNX.L`：Invesco Defence Innovation UCITS ETF
- `DFEU.L`：iShares Europe Defence UCITS ETF
- `SGLN.L`：iShares Physical Gold ETC
- `PHAU.L`：WisdomTree Physical Gold
- `SGBX.L`：WisdomTree Physical Swiss Gold

该模块抓取 ETF 日线价格并计算 `SMA13`、`SMA50`、`SMA200`、`RSI14`、1日/5日/1个月/3个月动量、距200日线百分比、日波动 sigma、距200日线的 `σ200` 拉伸度、拥挤度评分和新增仓位环境评分。日波动 sigma 使用最近最多 252 个交易日的日收益率标准差作为 `1σ`，用于判断当天涨跌是否只是常态波动，还是已经达到 `2σ`、`3σ` 这类显著偏离区间。`σ200` 不再直接使用普通 252 日标准差，而是使用 63/126/252 日窗口去极值后的稳健趋势波动率，再乘以 `sqrt(200)` 作为长期趋势波动尺度；这样可以降低 QWTM 这类高波动主题 ETF 中少数极端日收益对趋势拉伸判断的扭曲。高于 `2σ200` 说明趋势偏热，高于 `3σ200` 会提示回撤敏感度较高。拥挤度评分结合 RSI、距200日线、1个月动量和可用估值分位数，用于提示主题交易是否已经偏热或趋势是否仍待确认。新增仓位环境评分对权益 ETF 结合长期趋势、价格相对50/200日线位置、RSI冷却程度、1个月/3个月动量、单日波动和估值位置；黄金 ETC 不套用成长股 ETF 模型，而是结合实际利率、美元、长端利率、避险需求和金价自身趋势生成宏观配置环境评分。所有评分仅用于环境监控和风险管理，不构成买卖建议。

报告同时展示每只 ETF/ETC 的 `TER`（Total Expense Ratio，总费用率）和成本标签。TER 使用基金公司、justETF 或主流 ETF 数据页披露的静态资料录入，用于长期持有成本比较，不参与短期入场评分。成本标签口径为：`<=0.15%` 低成本，`<=0.35%` 成本适中，`<=0.50%` 主题费率偏高，`>0.50%` 高费率。宽基 ETF 更应重视 TER 差异；主题 ETF 则需同时权衡 TER、持仓集中度、流动性和是否与已有仓位重复暴露。

流动性/规模观察作为独立校验层展示，不直接改变宏观或入场评分。系统使用 Yahoo Chart 的日成交量估算 `20日均成交额`，并使用 StockAnalysis 的伦敦 ETF 页面抓取 `AUM`；若 AUM 或成交量缺失，会显示“待确认”而不是填入假数据。免费数据源对 LSE ETF 的实时 bid/ask 并不稳定，因此买卖价差默认标记为“价差待确认”。该模块用于提醒是否存在“产品太小、成交太薄或买卖成本可能偏高”的执行风险。

系统还会从 StockAnalysis 的伦敦 ETF holdings 页面读取可用的前十大持仓、总持仓数和 Top 10 concentration，并在每个 Sector 内展示成本最低、规模最大、成交最活跃以及前十大持仓近似重叠度最高的 ETF 组合。重叠度仅基于可获得的前十大持仓，不等同于完整穿透分析。Yahoo Chart 元数据会用于审计 ticker 是否仍对应 LSE、预期资产类型和主题名称；若出现类似 `CHIP.L` 的映射歧义，系统会停止将该标的纳入评分并显示警告。

## 实际组合导入

如需启用“实际组合视角”，在项目根目录创建不提交到 GitHub 的 `portfolio.csv`。可以复制 `portfolio.example.csv` 作为模板：

```csv
symbol,weight_pct
VUAG.L,40
CNX1.L,25
FLRK.L,15
SGLN.L,10
DFND.L,10
```

Revolut UK 官方支持下载 investment account statement：进入 `Invest → More → Documents → Stocks`，选择账户、statement 类型和时间范围。statement 可用于核对期末 portfolio snapshot；当前项目不直接读取 Revolut 账户，也不上传 statement。先将 ETF ticker 和组合权重整理进本地 `portfolio.csv` 即可。若未来提供脱敏 statement 样例，可再增加 PDF/CSV 自动解析适配器。

若 Revolut statement 为 CSV 交易流水，可以直接运行导入器：

```powershell
python scripts/import_revolut_statement.py "trading-account-statement_YYYY-MM-DD_YYYY-MM-DD_en-us_xxxxx.csv"
```

如果 Revolut 中有多个投资账户，可以将多个 CSV 路径依次传入：

```powershell
python scripts/import_revolut_statement.py "stocks-isa.csv" "general-investment.csv"
```

导入器会合并多个 statement，按 `BUY`、`SELL` 和 `STOCK SPLIT` 重建当前数量与平均成本，并生成本地 `portfolio.csv`。默认使用 Yahoo 最近价格估算当前市值、未实现盈亏、日变化和组合权重；美元资产会通过 `GBPUSD=X` 转换为英镑。若最新价格暂不可用，导入器会显式标记 `statement-average-cost fallback`，不会把降级估算伪装成实时价格。观察池外个股或 ETF 会列为尚未穿透覆盖。

网页报告会生成接近券商持仓页的“实际组合持仓”面板，展示数量、GBP平均成本、native currency 当前价格、native currency 市值、GBP参考市值、FX参考汇率、未实现盈亏、日变化与组合占比。Revolut statement 中的历史成交已经折算为 GBP，因此历史成本使用 statement 的 GBP 口径；当前市值使用 Yahoo 最近 native quote，并按报告抓取时点的 `GBP/USD` 或 `GBP/EUR` 换算为 GBP reference value。报告会明确显示 FX rate 和抓取时间。该面板只覆盖导入 statement 所属的账户和时间范围，不等同于 Revolut 实时账户净值；如 Revolut 中存在多个投资账户，需要分别导出并合并适配。原始 statement 和生成的 `portfolio.csv` 均已加入 `.gitignore`，不会上传到 GitHub。

组合面板还会将直接持有的 `NVDA`、`AVGO`、`META` 与 ETF 可获得的前十大持仓合并，显示 AI 核心公司与半导体核心暴露的“可识别下限”。直接个股仓位按完整权重计入；ETF 间接暴露仅根据公开前十大持仓近似计算，因此不等同于完整基金穿透。`ISF.L` 已纳入 UK 大盘股观察，`IGTM.L` 已纳入固定收益与久期观察；IGTM 不套用股票 PE 或 AI 拥挤度模型。

### 本地双击生成组合报告

将每个 Revolut 投资账户最新导出的 `trading-account-statement_*.csv` 放在项目根目录，然后双击：

```text
run_portfolio_report.bat
```

脚本会自动搜索 statement CSV、去除内容完全一致的重复文件、合并账户持仓、更新 `portfolio.csv`，并以 dry-run 模式生成最新 HTML 报告。整个过程会记录到：

```text
logs/portfolio-report-YYYY-MM-DD.log
```

由于 Revolut CSV 不包含稳定的账户标识，项目无法可靠判断两个内容不同的 CSV 是否属于同一个账户的不同时点导出。项目根目录中应只保留每个投资账户的一份最新导出文件；旧版本请移至其他目录，避免重复计算。该双击入口默认不发送邮件。

ETF 模块还会用 Yahoo 5 年日线做轻量历史检验。拥挤度口径统一为：`<35` 偏低，`65-69` 升温观察，`70-79` 偏高，`>=80` 高拥挤。回测采用周度抽样，默认把 `新增仓位环境 >= 60 且拥挤度 < 70` 视为“质量不差且尚未偏拥挤”的环境样本，并观察之后约 1M/3M/6M 的 forward return、3M 胜率和3M最大回撤，再与全样本对比。除此之外，系统会用当前的分数、拥挤度、RSI、1M/3M动量、距50/200日线、`σ200` 和日波动率做相似度匹配，并加入 SPY、QQQ、VIX、DXY、10Y yield、黄金和原油的同日历史环境代理变量，寻找历史上最接近当前市场环境的样本，并展示这些相似样本之后的 1M/3M/6M 表现与3M回撤。二级校准层会同时检验 `>=60`、`>=70`、`>=75` 三个阈值，并统一加入 `拥挤度 < 70` 的约束：`>=60` 表示环境尚可，`>=70` 表示环境较好，`>=75` 表示趋势结构较强但仍未进入偏拥挤区；系统会根据 forward return、3M胜率、3M回撤、样本数和相对全样本优势，动态给出“历史最优阈值”或“未发现稳定阈值优势”。该检验只使用当时已经可见的价格趋势、动量、波动和市场代理价格信息，不使用未来数据，也不把当前宏观指标回填到历史；因此它是环境评分的历史解释力检查，不是交易策略回测或买卖信号。

报告新增“相关性与Beta面板”，使用滚动60日数据展示每只ETF对 Nasdaq 100、DXY、美国10年期收益率和黄金的敏感度。Nasdaq、DXY和黄金的Beta按因子每变动1%解释；10年期收益率Beta按每上行10bp解释。该模块用于判断韩国ETF、半导体ETF或光通信ETF是否正在转化为AI capex、美元或久期代理变量。

相似环境模块采用 walk-forward 口径：历史样本只使用当时已经可见的信息计算距离，再观察其后的1M/3M/6M路径。网页会展示样本日期、距离分数、forward return、3M回撤，以及3M路径的P25/中位数/P75分布，降低少数极端行情对平均回报的误导。

`LAZR.L` 用于观察光学技术、Photonics、光模块、激光器与AI数据中心互连产业链。该ETF的规模较小，系统会将其标记为“观察型标的”，并要求在执行前额外核对实时买卖价差和盘口深度；它不应与高流动性的宽基ETF使用相同的执行假设。

估值字段采用 best-effort 方式抓取，不会因为估值接口失败而阻断价格和趋势监控：

- `PE`：市盈率，衡量市场愿意为每单位盈利支付多少价格；对成长和科技 ETF 的利率敏感度判断较有用。
- `Forward PE`：基于未来盈利预期的市盈率，更贴近市场当前定价逻辑，但依赖分析师盈利预测。
- `PB`：市净率，衡量市值相对账面净资产；对金融、周期和重资产行业更有解释力，对半导体、AI、量子等轻资产主题 ETF 的解释力弱于 PE。

估值源优先使用 Yahoo，若不可用则尝试 StockAnalysis 的伦敦 ETF 页面。若伦敦 ETF 本身不披露 PE，少数核心产品会使用高度相关的同类 ETF 作为 proxy，例如 `VWRL.L` 使用 `VT`、`VUAG.L` 使用 `VOO`、`IITU.L` 使用 `XLK`、半导体 ETF 使用 `SMH`、`QWTM.L` 使用 `QTUM`、韩国 ETF 使用 `EWY`、`DFND.L` / `DFNG.L` / `NATO.L` 使用 `ITA` 近似观察相关资产池估值；报告会明确标注 `proxy`，不把代理估值伪装成基金自身披露数据。韩国组优先纳入 Yahoo 可稳定抓取且 UK/LSE 可跟踪的 `CSKR.L`、`HKOR.L`、`FLRK.L`；若某些 Korea ticker 在 Yahoo 返回空历史，例如 `KWL.L`，默认池会暂不纳入，避免报告产生不可用资产。欧洲防务和防务创新 ETF 若缺少可比 proxy，会保留价格、趋势、拥挤度和历史环境检验，不强行填充不匹配估值。

黄金 ETC 没有盈利和净资产口径，因此不展示 PE/PB，应结合实际利率、美元和金价趋势解释。PE/PB 历史分位数会通过本地缓存逐步积累；样本不足时，报告会退而显示 `当前PE / 近一年缓存最高PE` 的近似比例，用来粗略判断当前估值是否贴近过去一年已观察到的高位，但该比例依赖本地缓存积累，不等同于严格历史分位。

GitHub Actions 会通过 `actions/cache` 持续保存 `output/cache`，因此云端每日运行也会逐步积累 ETF 估值历史、PE 位置和本地市场数据缓存。该缓存适合轻量连续监控，但不是永久数据库；如果 GitHub 清理缓存，PE 历史会从下一次运行重新积累。

## 后续路线图

- 真实买卖价差：优先考虑后续接入 IBKR 或其他稳定报价源。
- 组合穿透：在本地组合导入基础上，进一步聚合 Nvidia、Samsung、SK hynix 等底层持仓暴露。
- 相关性与 beta 面板：滚动观察 ETF 对 Nasdaq、DXY、10Y yield 和黄金的敏感度变化。
- Walk-forward 历史验证：展示相似环境样本日期、距离分数和未来路径分布，减少均值掩盖尾部风险的问题。
