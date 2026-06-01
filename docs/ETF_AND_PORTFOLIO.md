# UK ETF 观察池、估值与组合导入

## ETF 观察池

报告按 sector 分组显示 UK/LSE 可观察产品，包括宽基、科技、AI 基建、半导体、光模块、云计算、网络安全、量子计算、韩国权益、防务、固定收益和黄金 ETC。

当前主要池：

| 分组 | Ticker |
| --- | --- |
| 宽基与指数 | `VWRL.L`, `VUAG.L`, `ISF.L`, `CNX1.L` |
| 科技、AI 与自动化 | `IITU.L`, `AINF.L`, `WTAI.L`, `AIAI.L`, `RBOT.L`, `WCLD.L`, `LOCK.L` |
| 半导体与光模块 | `SEMI.L`, `SMGB.L`, `SEMG.L`, `LAZR.L` |
| 量子计算 | `QWTM.L`, `QNTM.L`, `QANT.L` |
| 韩国权益 | `CSKR.L`, `HKOR.L`, `FLRK.L` |
| 防务 | `DFND.L`, `WDEF.L`, `DFNG.L`, `NATO.L`, `DFNX.L`, `DFEU.L` |
| 固定收益与黄金 | `IGTM.L`, `SGLN.L`, `PHAU.L`, `SGBX.L` |

每只产品尽量展示：

- `TER`：总费用率
- AUM、20 日平均成交额和流动性标签
- PE、Forward PE、组合 P/B 和披露日期
- SMA13、SMA50、SMA200、RSI14、动量和稳健波动率
- 拥挤度、新增仓位环境分数、相关性与 beta
- walk-forward 相似环境样本和尾部历史阶段

免费数据源对 LSE ETF 的真实 bid/ask spread 不稳定，因此价差保持“待确认”，不填入伪精度。

## 组合估值字段

运行：

```powershell
python scripts/import_revolut_statement.py "trading-account-statement_*.csv"
```

导入器按 `BUY`、`SELL` 和 `STOCK SPLIT` 重建数量与历史 GBP 成本，并抓取 Yahoo 最新价格。美元和欧元资产使用抓取时点的 GBP/USD 或 GBP/EUR 汇率转换为 GBP 参考市值。

组合面板显示：

- native currency 当前价格和 native 市值
- GBP 参考市值、FX rate 和抓取时间
- 未实现盈亏和当日变化
- 组合权重、观察池覆盖状态和可识别 AI/HBM 暴露

## 回撤性质判断

距年内高点回撤仍保留两层直观预警：

- 超过 `5%`：黄色观察
- 超过 `10%`：红色观察

为了区分正常回调与趋势破坏，系统额外计算：

- `SMA200` 和价格距 SMA200 百分比
- 63/126/252 日窗口去极值后的稳健日波动率
- `回撤约多少 σ(1M)`：年内峰值回撤除以 `稳健日波动率 × sqrt(21)`
- 可直接匹配到持仓 ticker 的新闻事件

解释层：

- `常态波动`：回撤不超过 5%
- `正常回调观察`：回撤超过 5%，但仍在 SMA200 上方，且没有显著超出一个月正常波动区间
- `需要复核`：回撤已经离开常态区间，但技术证据尚未充分指向趋势破坏
- `趋势破坏风险`：价格明显跌破 SMA200，或较深回撤同时达到较高波动倍数

事件层只用于复核，不直接覆盖技术判断。直接 ticker 没有匹配到新闻，不代表 ETF 底层持仓不存在事件风险。

## 分数不是交易指令

新增仓位环境分数、拥挤度、回撤分类和相似环境样本用于风险管理与研究复核，不提供买卖、仓位比例、行权价或到期日建议。
