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

邮件模式：

- `none`：只生成报告和 artifact
- `pulse`：轻量市场脉冲邮件
- `volatility`：波动率和 Iron Condor 环境简报
- `full`：完整 HTML 报告
- `auto`：按 `Europe/London` 当前本地时间自动推断

`auto` 映射：

- `00:00-07:59`：`none`
- `08:00-16:29`：`pulse`
- `16:30-19:59`：`volatility`
- `20:00-23:59`：`full`

默认工作日 UK 节奏：

- `08:30`：Market Pulse
- `14:45`：Market Pulse
- `18:00`：Volatility / Iron Condor 简报
- `21:15`：完整 HTML 报告
- `21:45` / `22:15`：full 报告兜底候选，仅在当天 full 尚未成功发送时补发

英国夏令时按固定规则转换：三月最后一个周日进入 BST，十月最后一个周日回到 GMT。GitHub cron 使用 UTC，因此 workflow 配置两组候选 UTC 时间，并在运行时按 `Europe/London` 判断是否执行。GitHub scheduled workflow 可能被平台排队延迟；本项目不会因为 GitHub 延迟而跳过正确的 UK 候选，只会跳过错误的 BST/GMT 候选。为了避免当天最重要的 full 邮件缺失，workflow 额外设置 `21:45` 和 `22:15` full 兜底候选，并通过 `market-report-scheduled-email-sent-...-full` cache marker 确保同一天 scheduled full 邮件只发送一次。手动 `workflow_dispatch` 的 `full` 模式不会读取或写入 scheduled marker，不会影响当天定时 full 邮件；它只用于当天重新发送或验证邮件。

### 紧急市场冲击邮件

GitHub scheduled workflow 不是准点交易风控工具，平台高峰期可能延迟几十分钟甚至更久。因此项目新增独立的 `market shock alert` 检查器：每次报告生成后，无论当前 `EMAIL_MODE` 是 `none`、`pulse`、`volatility` 还是 `full`，都会先检查是否出现权益急跌、VIX/VVIX 快速扩张、美元与成长股压力共振或长端利率冲击。

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

多个收件人使用英文逗号分隔。`PORTFOLIO_EMAIL_TO` 可选：当 full 报告包含实际持仓时，公开收件人收到移除组合信息的版本，私人收件人收到完整版本。若同一邮箱同时出现在 `REPORT_EMAIL_TO` 和 `PORTFOLIO_EMAIL_TO`，full 模式会优先发送私人完整版本，并从公开版收件人中去重。

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

云端导入会先下载 OneDrive 中的 Revolut/IBKR 手动 statement，再尝试下载 IBKR Flex Web Service XML，最后统一导入 `.cloud-statements` 目录下的 CSV/XML。IBKR Trade Confirmation 会只使用 `LevelOfDetail=EXECUTION` 的成交明细，避免把 summary/order/execution 重复计入持仓；如果某个来源不存在，会跳过该辅助来源并继续生成报告。

IBKR Flex token 对短时间连续请求可能触发限流，Activity statement 也可能临时返回 `Statement could not be generated at this time`。Activity statement 比 Trade Confirmation 更重，主要用于 full 报告中的历史账户、持仓、现金、股息和费用信息；pulse/volatility 等盘中轻量邮件默认只下载 Trade Confirmation，避免一天多次触发 Activity 生成。工作流会在两个 Flex Query 之间等待 30 秒；对限流和“稍后重试”的生成失败会自动重试。如果其中一个 query 已成功下载、另一个 query 最终仍失败，流程会记录 partial failure 并继续导入已下载的 XML。只有所有 IBKR Flex query 都失败时，才会中断该下载步骤。

## IBKR Flex Web Service 云端导入

IBKR Flex Query 推荐使用 XML。GitHub Actions 支持以下 secrets：

```text
IBKR_FLEX_TOKEN
IBKR_ACTIVITY_QUERY_ID=1531778
IBKR_TRADE_CONFIRM_QUERY_ID=1535495
```

- `IBKR_ACTIVITY_QUERY_ID` 对应 `PastTradesTransacInfo`，用于历史交易、持仓、现金、股息、费用和表现。
- `IBKR_TRADE_CONFIRM_QUERY_ID` 对应 `TodayTradesTransacInfo`，用于当天/近期成交确认，补充 Activity statement 的延迟。
- token 不应写入代码、日志或聊天记录，只放在 GitHub Secrets。

本地测试可运行：

```text
python scripts/download_ibkr_flex.py --output-dir .cloud-statements --query-delay-seconds 30 --transient-retries 2 --transient-wait-seconds 90
python scripts/import_portfolio_statements.py .cloud-statements/*.xml
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
