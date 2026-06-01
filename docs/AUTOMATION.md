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

英国夏令时按固定规则转换：三月最后一个周日进入 BST，十月最后一个周日回到 GMT。GitHub cron 使用 UTC，因此 workflow 配置两组候选 UTC 时间，并在运行时按 `Europe/London` 判断是否执行。

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

多个收件人使用英文逗号分隔。`PORTFOLIO_EMAIL_TO` 可选：当 full 报告包含实际持仓时，公开收件人收到移除组合信息的版本，私人收件人收到完整版本。

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
python scripts/download_onedrive_statements.py --output-dir .cloud-statements --import-portfolio
```

推荐最小权限 delegated refresh token 模式：

```text
ONEDRIVE_CLIENT_ID
ONEDRIVE_REFRESH_TOKEN
```

可选变量：

```text
ONEDRIVE_FOLDER_PATH=Trading/Revolut Transaction Statement
ONEDRIVE_USE_LATEST_PER_ACCOUNT_FOLDER=false
```

该路径只使用免费 App Registration 和标准 Graph 文件读取接口，不创建 Azure VM、Storage、Functions、数据库或其他计费资源。CSV、refresh token 和 `portfolio.csv` 不应提交到 GitHub。
