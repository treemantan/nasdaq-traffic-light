# Macro Regime Radar

中文优先的宏观跨资产风险仪表盘。项目不把市场机械地简化为“红灯看空、绿灯看多”，而是结合权益、波动率、利率、美元、信用、流动性、新闻事件和 UK 可交易 ETF，解释当前市场状态及其变化。

## 核心能力

- 宏观 regime、流动性状态、收益率驱动归因和跨资产一致性判断
- Nasdaq 100、S&P 500、Russell 2000、VIX、VVIX、MOVE、DXY、黄金、油价、信用利差和美债监控
- Iron Condor 环境过滤器，仅评估区间型卖波动环境，不提供交易指令
- UK 可交易 ETF 的估值、趋势、拥挤度、流动性、相关性和 beta 面板
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

## 文档导航

- [自动化、邮件与 OneDrive 云端导入](docs/AUTOMATION.md)
- [UK ETF 观察池、估值与组合导入](docs/ETF_AND_PORTFOLIO.md)
- [方法论：评分、相似环境、walk-forward 与 MAD 自适应校准](docs/METHODOLOGY.md)
- [评分解释、Iron Condor 上下文与现金/短债框架](docs/SCORING_EXPLANATION.md)
- [数据源、缓存与回退机制](docs/DATA_SOURCES.md)
- [组合行情缓存与降级机制](docs/PORTFOLIO_QUOTE_CACHE.md)
- [MAG7 企业资本关系图谱与后续地缘政治辅助分](docs/MAG7_CAPITAL_NETWORK.md)
- [Serenity 私人持仓周报](docs/SERENITY_WEEKLY.md)

点击下方链接可打开对应文档。Codex 本地预览可能会调用系统默认 Markdown 应用；GitHub 中可直接跳转。

## 关于持仓回撤观察

组合面板会显示距年内高点回撤。黄色观察阈值为 `max(5%, 1σ月度波动)`，红色观察阈值为 `max(10%, 2σ月度波动)`；同时结合 `SMA200`、稳健波动率和直接 ticker 新闻事件，区分：

- 常态波动
- 正常回调观察
- 需要复核
- 趋势破坏风险

它是风险管理提示，不是机械加减仓信号。详细逻辑见 [ETF 与组合文档](docs/ETF_AND_PORTFOLIO.md)。

## 关于 MAD

MAD 是“中位绝对偏差”，用于让不同 ETF 的相似环境尺度自动适配自身历史波动。它比普通标准差更不容易被少量极端行情扭曲。详细公式、例子和防止未来信息泄漏的约束见 [方法论文档](docs/METHODOLOGY.md)。

## 免责声明

本工具用于宏观市场监控与研究参考，不构成投资建议，也不构成期权交易建议。
