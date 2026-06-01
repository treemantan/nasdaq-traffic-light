# Macro Regime Radar

中文优先的宏观跨资产风险仪表盘。项目不把市场机械地简化为“红灯看空、绿灯看多”，而是结合权益、波动率、利率、美元、信用、流动性、新闻事件和 UK 可交易 ETF，解释当前市场状态及其变化。

## 核心能力

- 宏观 regime、流动性状态、收益率驱动归因和跨资产一致性判断
- Nasdaq 100、S&P 500、Russell 2000、VIX、VVIX、MOVE、DXY、黄金、油价、信用利差和美债监控
- Iron Condor 环境过滤器，仅评估区间型卖波动环境，不提供交易指令
- UK 可交易 ETF 的估值、趋势、拥挤度、流动性、相关性和 beta 面板
- Revolut statement 组合导入、GBP 参考估值、AI/HBM 持仓穿透和回撤风险复核
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

- [自动化、邮件与 OneDrive 云端导入](#automation-guide)
- [UK ETF 观察池、估值与组合导入](#etf-portfolio-guide)
- [方法论：评分、相似环境、walk-forward 与 MAD 自适应校准](#methodology-guide)
- [数据源、缓存与回退机制](#data-source-guide)
- [组合行情缓存与降级机制](#portfolio-cache-guide)

右侧 Markdown 预览器可能不会继续打开另一个本地相对路径文件。上面的导航使用同页锚点，适合在右侧直接阅读；每个速览末尾仍保留完整文档链接，方便在 GitHub 或编辑器中打开。

<a id="automation-guide"></a>
## 自动化、邮件与 OneDrive 云端导入

<details>
<summary>展开速览</summary>

- GitHub Actions 在工作日 UK 时间 `08:30`、`14:45`、`18:00` 和 `21:15` 运行，并自动处理 BST/GMT。
- `EMAIL_MODE` 支持 `none`、`pulse`、`volatility`、`full` 和 `auto`。
- 手机可把 Revolut CSV 保存到 OneDrive `Trading/Revolut Transaction Statement`。
- GitHub Actions 可通过 Microsoft Graph 下载最新 CSV，因此电脑关机时仍能运行。
- `PORTFOLIO_EMAIL_TO` 用于接收含实际持仓的私人 full 版本。

完整版本：[docs/AUTOMATION.md](docs/AUTOMATION.md)

</details>

<a id="etf-portfolio-guide"></a>
## UK ETF 观察池、估值与组合导入

<details>
<summary>展开速览</summary>

- ETF 按 sector 分组展示，包括宽基、AI、半导体、光模块、韩国权益、防务、固定收益和黄金。
- 每只 ETF 尽量展示 TER、AUM、成交额、PE、Forward PE、组合 P/B、SMA、RSI、拥挤度、相关性和 beta。
- Revolut statement 导入器按交易记录重建持仓，并把 native currency 市值转换为 GBP 参考市值。
- 回撤观察结合距年内高点、SMA200、稳健波动率和直接 ticker 新闻事件，区分正常回调与趋势破坏。

完整版本：[docs/ETF_AND_PORTFOLIO.md](docs/ETF_AND_PORTFOLIO.md)

</details>

<a id="methodology-guide"></a>
## 方法论：评分、相似环境与 MAD

<details>
<summary>展开速览</summary>

- 相似环境模块回答“过去哪些历史起点与今天接近，之后路径如何”，不是收益预测器。
- 历史候选日期只使用当时已经可见的信息，未来收益仅在匹配完成后作为 outcome 读取。
- MAD 是中位绝对偏差，用于降低极端单日行情对相似度尺度的扭曲。
- 相邻样本会按行情阶段聚类，避免把同一轮行情重复计算多次。

完整版本：[docs/METHODOLOGY.md](docs/METHODOLOGY.md)

</details>

<a id="data-source-guide"></a>
## 数据源、缓存与回退机制

<details>
<summary>展开速览</summary>

- 项目混合使用 Yahoo Finance、FRED、CNN、NAAIM、Investing、发行商页面、新闻源和本地缓存。
- 核心数据失败时优先 fallback，再考虑新鲜缓存；辅助数据缺失会降低置信度，但不会让报告整体中断。
- 缓存、fallback、缺失、延迟和可疑数值都会显式标记。
- GitHub Actions 使用 `actions/cache` 保存 `output/cache`，但它不是永久数据库。

完整版本：[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)

</details>

<a id="portfolio-cache-guide"></a>
## 组合行情缓存与降级机制

<details>
<summary>展开速览</summary>

- 成功抓取的组合行情会写入 `output/cache/portfolio_quote_cache.json`。
- Yahoo 暂时不可用时，依次尝试组合行情缓存、ETF monitor 缓存、statement 平均成本降级估值。
- 周末使用最近有效收盘价属于正常行为；整组持仓全部显示 `statement-average-cost fallback` 则需要检查数据源。
- iPhone 导出的 UUID 文件名不是乱码。系统会根据 CSV 表头识别 Revolut statement，不依赖文件名前缀。

完整版本：[docs/PORTFOLIO_QUOTE_CACHE.md](docs/PORTFOLIO_QUOTE_CACHE.md)

</details>

## 关于持仓回撤观察

组合面板会显示距年内高点回撤，并保留 `5%` 黄色观察、`10%` 红色观察阈值。新版同时结合 `SMA200`、稳健波动率和直接 ticker 新闻事件，区分：

- 常态波动
- 正常回调观察
- 需要复核
- 趋势破坏风险

它是风险管理提示，不是机械加减仓信号。详细逻辑见 [ETF 与组合文档](docs/ETF_AND_PORTFOLIO.md)。

## 关于 MAD

MAD 是“中位绝对偏差”，用于让不同 ETF 的相似环境尺度自动适配自身历史波动。它比普通标准差更不容易被少量极端行情扭曲。详细公式、例子和防止未来信息泄漏的约束见 [方法论文档](docs/METHODOLOGY.md)。

## 免责声明

本工具用于宏观市场监控与研究参考，不构成投资建议，也不构成期权交易建议。
