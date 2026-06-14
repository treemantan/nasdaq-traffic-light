# 自动化、邮件与 OneDrive 云端导入

## 本地生成

```powershell
python -m market_report --config config.example.json --dry-run
```

本地 Gmail SMTP 可继续使用 `config.json` 和 `SMTP_PASSWORD` 环境变量。密码必须使用 Gmail App Password，不要使用网页登录密码。

## GitHub Actions

工作流文件：

```text
.github/workflows/daily-market-report.yml
```

工作流会生成报告、上传 artifact，并根据 `EMAIL_MODE` 决定是否发送邮件。

### 公共 Artifact 与私人组合数据

- GitHub Actions 的 `market-report-*` Artifact 只上传去除实际持仓、组合收益、组合事件和动态持仓补充 ticker 的公开市场报告。
- 私人组合 HTML/JSON 不上传 Artifact；`output/cache` 也不作为可下载 Artifact 发布。
- `full` 模式的邮件正文统一使用公开去持仓版本。
- 当存在 `portfolio.csv` 且配置了 `PORTFOLIO_EMAIL_TO` 时，完整私人组合 HTML 仅作为附件发送给私人收件人。
- 私人组合 JSON 不通过邮件或 Artifact 分发。

邮件模式：

- `none`：只生成报告和 artifact
- `pulse`：轻量市场脉冲邮件
- `volatility`：波动率和 Iron Condor 环境简报
- `full`：完整 HTML 报告
- `serenity`：私人持仓周度深度复核，仅发送到 `PORTFOLIO_EMAIL_TO`
- `auto`：按 `Europe/London` 当前本地时间自动推断

`auto` 映射：

- `00:00-07:59`：`none`
- `08:00-16:29`：`pulse`
- `16:30-19:59`：`volatility`
- `20:00-23:59`：`full`

`auto` 只用于日内邮件，不会自动推断为 `serenity`；Serenity 由周六 schedule 或手动选择触发。

默认工作日 UK 节奏：

- `08:30`：Market Pulse
- `14:45`：Market Pulse
- `18:00`：Volatility / Iron Condor 简报
- `21:15`：完整 HTML 报告
- `21:45` / `22:15`：full 报告兜底候选，仅在当天 full 尚未成功发送时补发

默认周末 UK 节奏：

- 周六 `09:00`：Serenity 私人持仓周报
- 周六 `10:00`：Serenity 兜底候选，仅在当周报告尚未成功发送时补发

Serenity 的两个候选运行通过 `market-report-scheduled-email-sent-...-serenity` cache marker 去重。手动 `workflow_dispatch` 的 `serenity` 不读取或写入定时 marker，因此可用于测试或主动重发。详细方法见 [Serenity 私人持仓周报](SERENITY_WEEKLY.md)。

英国夏令时按固定规则转换：三月最后一个周日进入 BST，十月最后一个周日回到 GMT。GitHub cron 使用 UTC，因此 workflow 配置两组候选 UTC 时间，并在运行时按 `Europe/London` 判断是否执行。GitHub scheduled workflow 可能被平台排队延迟；本项目不会因为 GitHub 延迟而跳过正确的 UK 候选，只会跳过错误的 BST/GMT 候选。为了避免当天最重要的 full 邮件缺失，workflow 额外设置 `21:45` 和 `22:15` full 兜底候选，并通过 `market-report-scheduled-email-sent-...-full` cache marker 确保同一天 scheduled full 邮件只发送一次。手动 `workflow_dispatch` 的 `full` 模式不会读取或写入 scheduled marker，不会影响当天定时 full 邮件；它只用于当天重新发送或验证邮件。

### 紧急市场冲击邮件

GitHub scheduled workflow 不是准点交易风控工具，平台高峰期可能延迟几十分钟甚至更久。因此项目新增独立的 `market shock alert` 检查器：每次报告生成后，无论当前 `EMAIL_MODE` 是 `none`、`pulse`、`volatility`、`full` 还是 `serenity`，都会先检查是否出现权益急跌、VIX/VVIX 快速扩张、美元与成长股压力共振或长端利率冲击。

触发后会发送一封独立的“紧急市场风险警报”，收件人来自 `REPORT_EMAIL_TO` 与 `PORTFOLIO_EMAIL_TO` 去重后的合集。邮件只包含市场冲击与复核动作，不包含私人持仓明细。已发送状态写入 `output/cache/market_shock_alerts.json`，同一天首次触发会发送；若之后风险强度显著升级，也会再次发送，避免在同一风险等级下重复刷屏。

如果需要比 GitHub cron 更及时，可以用外部定时服务调用 GitHub `workflow_dispatch`，并传入：

```text
email_mode=none
```

这样 workflow 只生成报告、上传 artifact，并执行紧急冲击检查；普通报告邮件不会发送，只有达到 shock 条件时才会额外报警。这个方案比依赖 GitHub schedule 更适合盘中风控兜底，但仍然不是券商级实时风控。

## 邮件 secrets

Resend：

```text
RESEND_API_KEY
REPORT_EMAIL_TO
REPORT_EMAIL_FROM
```

Gmail SMTP 替代方案：

```text
EMAIL_PROVIDER=smtp
REPORT_EMAIL_TO
SMTP_USERNAME
SMTP_PASSWORD
SMTP_FROM
SMTP_HOST
SMTP_PORT
SMTP_SECURITY
```

多个收件人使用英文逗号分隔。`PORTFOLIO_EMAIL_TO` 可选：当 full 报告包含实际持仓时，公开与私人收件人的邮件正文均为去持仓版本，私人收件人另获完整私人组合 HTML 附件。若同一邮箱同时出现在 `REPORT_EMAIL_TO` 和 `PORTFOLIO_EMAIL_TO`，会从公开收件人中去重，避免重复邮件。`serenity` 模式必须配置 `PORTFOLIO_EMAIL_TO`，并且只向该私人名单发送。

## OneDrive 本地 inbox

手机导出的 Revolut CSV 可保存到 Windows OneDrive 同步目录：

```text
C:\Users\<Windows用户>\OneDrive\Trading\Revolut Transaction Statement
```

入口：

```text
setup_onedrive_portfolio_inbox.bat
run_onedrive_portfolio_report.bat
```

本地状态记录：

```text
logs/portfolio-report-status.txt
```

本地 runner 按日期追加日志：

```text
logs/portfolio-report-YYYY-MM-DD.log
logs/market-report-YYYY-MM-DD.log
```

同一天可以运行多次。每次启动都会写入独立的 `RUN START` / `RUN END` 分隔块和唯一 `run_id`；结束块包含 `SUCCESS`、`FAILED` 或 `SKIPPED_BUSY`、耗时和最新 HTML 路径。组合导入会把自身 `run_id` 传给内部报告 runner 作为 `ParentRunId`，便于追踪一次双击触发的完整链路。需要排查单次运行时，在日志中搜索对应 `run_id` 即可。

OneDrive inbox 可以保留历史导出，无需每次手工清理。导入器会基于完整交易字段移除重叠 statement 中的重复行，再按时间顺序重建持仓。保留旧文件也便于后续审计和回溯测试。

## OneDrive Graph 云端导入

GitHub Actions 可以在本地电脑关机时通过 Microsoft Graph 下载 CSV：

```text
python scripts/download_onedrive_statements.py --output-dir .cloud-statements
python scripts/import_portfolio_statements.py .cloud-statements/*.csv
```

推荐最小权限 delegated refresh token 模式：

```text
ONEDRIVE_CLIENT_ID
ONEDRIVE_REFRESH_TOKEN
```

可选变量：

```text
ONEDRIVE_FOLDER_PATH=Trading/Revolut Transaction Statement
ONEDRIVE_IBKR_FOLDER_PATH=Trading/IBKR Transaction Statement
ONEDRIVE_USE_LATEST_PER_ACCOUNT_FOLDER=false
```

云端导入会先下载 OneDrive 中的 Revolut/IBKR 手动 statement，再尝试下载 IBKR Flex Web Service statement，最后统一导入 `.cloud-statements` 目录下的 CSV/XML。Revolut 默认匹配 `*.csv`；IBKR 默认同时匹配 `*.csv,*.xml`，也可通过 `ONEDRIVE_IBKR_STATEMENT_PATTERNS` 调整。IBKR 网页重复下载产生的 `PastTradesFullReport.xml`、`PastTradesFullReport 1.xml` 或 `PastTradesFullReport (1).xml` 会被视为同一查询系列，只下载 OneDrive 中修改时间最新的版本。不同 QueryName 仍分别保留，例如 Activity 与 Trade Confirmation 不会互相覆盖。

推荐 Full Activity 保留 XML，Activity Light 与 Trade Confirmation 使用 CSV。下载器会根据实际响应内容自动保存为 `.xml` 或 `.csv`，不依赖文件名猜测格式。IBKR Trade Confirmation 只使用 `LevelOfDetail=EXECUTION` 的成交明细，避免把 summary/order/execution 重复计入持仓；旧的 XML Trade Confirmation 中 `<TradeConfirm>` 节点也会被识别。如果某个来源不存在，会跳过该辅助来源并继续生成报告。

IBKR Flex token 对短时间连续请求可能触发限流，Activity statement 也可能临时返回 `Statement could not be generated at this time`。Activity statement 比 Trade Confirmation 更重，主要用于 full 报告中的历史账户、持仓、现金、股息和费用信息；pulse/volatility 等盘中轻量邮件默认只下载 Trade Confirmation，避免一天多次触发 Activity 生成。full 模式会先尝试完整 Activity query；如果 IBKR 在 `SendRequest` 阶段拒绝生成，会立刻尝试 `IBKR_ACTIVITY_LIGHT_QUERY_ID`，不再等待 90 秒重试。工作流仍会在不同 Flex Query 之间等待 30 秒，以降低 token 限流概率。

如果其中一个 query 已成功下载、另一个 query 最终仍失败，流程会记录 partial failure 并继续导入已下载的 CSV/XML。如果所有 Flex query 都失败，但 OneDrive 中已有可识别的手动 IBKR CSV/XML，流程会使用最新手动文件兜底；即使没有任何可用 IBKR 文件，市场报告和 Revolut 组合部分也不会因此中断。

组合报告会明确显示 IBKR 数据健康度：

- `live`：Activity 与 Trade Confirmation 均来自本次 IBKR Flex 下载。
- `manual-fallback`：自动下载未完整成功，至少一类数据使用 OneDrive 手动文件兜底。
- `partial`：Activity 或 Trade Confirmation 其中一类缺失。
- `missing`：已配置 IBKR，但本次没有任何可用 IBKR statement。

告警会分别显示 Activity 与 Trade Confirmation 的最近有效记录日期、来源和文件更新时间。该日期是信息覆盖截止点，不代表实时券商净值；发生新交易后应及时把最新手动 statement 放入 OneDrive，以免组合分析遗漏。

每次 IBKR Flex 下载都会生成 `.cloud-statements/ibkr-flex-diagnostics.json` 并随 GitHub Actions artifact 上传。该文件不包含 token 或 ReferenceCode，只记录 query label、attempt、IBKR 返回的 status/error、运行模式和耗时。若 Activity 在 Actions 中反复失败但网页手动生成成功，优先下载该诊断文件，对比是否一直停在 `send_request` 阶段、是否只发生在 full 模式、以及是否与同一天多次运行有关。

## IBKR Flex Web Service 云端导入

IBKR Flex Query 推荐采用混合格式：Full Activity 使用 XML，Activity Light 与 Trade Confirmation 使用 CSV。GitHub Actions 支持以下 secrets：

```text
IBKR_FLEX_TOKEN
IBKR_ACTIVITY_QUERY_ID=1531778
IBKR_ACTIVITY_LIGHT_QUERY_ID=<轻量 Activity query，可选但推荐>
IBKR_TRADE_CONFIRM_QUERY_ID=1535495
```

- `IBKR_ACTIVITY_QUERY_ID` 对应 `PastTradesTransacInfo`，用于历史交易、持仓、现金、股息、费用和表现。
- `IBKR_ACTIVITY_LIGHT_QUERY_ID` 对应轻量 Activity query，作为完整 Activity 被 IBKR Web Service 拒绝生成时的 fallback。
- `IBKR_TRADE_CONFIRM_QUERY_ID` 对应 `TodayTradesTransacInfo`，用于当天/近期成交确认，补充 Activity statement 的延迟。

推荐的 IBKR 输出设置：

| Query | Format | Header/trailer | Column headers | Single header row | Section code/line descriptor |
| --- | --- | --- | --- | --- | --- |
| Full Activity | XML | 不适用 | 不适用 | 不适用 | 不适用 |
| Activity Light | CSV | No | Yes | No | Yes |
| Trade Confirmation | CSV | No | Yes | Yes | No |

同一个 Flex Query ID 的输出格式由 IBKR 后台配置决定，Web Service 下载时不能临时覆盖。当前方案不创建额外的 Full Activity CSV Query：Full Activity 保留 XML，轻量 fallback 和当日成交确认使用 CSV。
- token 不应写入代码、日志或聊天记录，只放在 GitHub Secrets。

本地测试可运行：

```text
python scripts/download_ibkr_flex.py --output-dir .cloud-statements --query-delay-seconds 30 --transient-retries 0 --transient-wait-seconds 0
python scripts/import_portfolio_statements.py .cloud-statements/*.xml .cloud-statements/*.csv
```

该路径只使用免费 App Registration 和标准 Graph 文件读取接口，不创建 Azure VM、Storage、Functions、数据库或其他计费资源。CSV、refresh token 和 `portfolio.csv` 不应提交到 GitHub。

## 持仓事件提醒

GitHub Actions 在完成 OneDrive 持仓导入后，会运行轻量持仓事件检查器：

```text
python scripts/send_portfolio_event_reminders.py --lookahead-hours 7
```

- 提醒只发送至 `PORTFOLIO_EMAIL_TO`，不会发送到公开报告收件人。
- 有精确时刻的事件在首次进入约 7 小时观察窗口时提醒；这使现有定时任务能够覆盖“事件前约 6 小时”的需求。
- 只有日期的事件会在事件当天、美股开盘前首次检查时提醒。
- 已发送事件写入 `output/cache/portfolio_event_reminders.json`，并随 GitHub Actions cache 延续，避免重复提醒。
- 每个事件包含官方来源或可审计的进展链接。预计日期和媒体报道会明确标记，不应误读为公司已经正式确认。
- 所有红色回撤预警 ticker 都会进入事件复核覆盖检查。若尚未登记未来窗口，私人报告会显示“红色预警待补充事件来源”，提醒人工检查公司 IR、SEC 披露和行业监管进展。

事件日历维护在：

```text
data/portfolio_events.json
```

## 市场冲击历史类比

当市场冲击触发时，完整报告会显示“市场冲击历史类比”。该模块使用 Nasdaq 100、S&P 500、Russell 2000、VIX、VVIX 与 DXY 的当日变化寻找历史相似冲击日，并展示之后 `1D/5D/20D` 路径、回撤和独立历史阶段数。

匹配步骤不使用未来收益，未来路径只作为 outcome 复盘；详见 `docs/METHODOLOGY.md`。
