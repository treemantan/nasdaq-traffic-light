# Serenity 私人持仓周报

`serenity` 是独立于每日 `full` 报告的周度私人组合研究模式。它采用 Serenity 供应链卡点框架中的核心约束：先写风险与反证，再写支持逻辑；明确催化剂、证伪条件、证据缺口和来源，不输出机械买卖指令。

## 运行与收件人

- 默认在周六 `09:00 UK` 运行，`10:00 UK` 为 GitHub cron 延迟兜底。
- 两个候选运行共享 `serenity` 邮件 marker，同一 UK 日期只发送一次。
- 仅发送到 `PORTFOLIO_EMAIL_TO`，不会发送到公共 `REPORT_EMAIL_TO`。
- 邮件正文是简要周报，完整 Serenity HTML 作为附件，并同步上传到 GitHub Actions artifact。
- 可在 GitHub Actions 手动选择 `email_mode=serenity` 测试；手动运行不使用定时去重 marker。

## 重点持仓选择

系统每周自动选择最多五个复核对象，优先级依次考虑：

1. 红色回撤或长期趋势破坏；
2. 组合核心权重；
3. AI、半导体、光互联及相关资本开支链条；
4. 临近公司事件或监管窗口；
5. 拥挤度偏高。

这是一套研究排队规则，不是收益预测器，也不是加减仓信号。

## 每个标的的输出

- 当前组合状态与权重；
- 主要风险与反证；
- 支持逻辑与观察线索；
- 未来催化剂和人工复核窗口；
- 可证伪条件；
- 证据缺口；
- 已登记的一手或可审计来源。

## 框架适用边界

Serenity 对半导体、AI 基础设施、网络、光互联和制造卡点的解释力较强。宽基 ETF、债券 ETF、现金和超短债不应被强行解释成供应链卡点；这些资产分别改看集中度、久期、收益率、信用质量和流动性。

GitHub Actions 版本使用项目已经结构化的数据和来源，属于规则化周度复核。它不会假装完成实时的一手深度研究。遇到来源不足时，报告会明确标记证据缺口；需要进一步研究时，可再用 `/serenity` 对单一标的开展人工深化分析。

## 本地生成

先生成普通结构化报告，再运行：

```powershell
python scripts/generate_serenity_report.py
```

输出：

```text
output/serenity-report-YYYY-MM-DD.html
output/serenity-report-YYYY-MM-DD.json
```

本模块仅用于研究与风险复核，属于非投资建议。
