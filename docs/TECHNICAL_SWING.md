# Technical Swing Analysis 技术波段观察

该模块用于日常技术结构复核与建仓准备，不提供直接买卖指令。报告统一使用“观察、确认、支撑、阻力、风险、失效与 setup”等措辞。

## 分析范围

技术分析覆盖三类 ticker：

1. 当前持仓：从已导入的组合持仓自动读取，ETF 与个股均分析。
2. 固定观察池：在配置文件的 `swing_watchlist` 中维护。
3. 临时 ticker：手动运行 GitHub Actions 时通过 `technical_tickers` 输入，仅对本次运行生效；可以留空。

Ticker 必须使用明确的交易所符号。系统不会根据公司名称猜测证券：

```text
MSFT    = Nasdaq 上市的 Microsoft
MSFT.L  = LSE 上使用该代码的证券
```

## 数据与降级

日线 OHLCV 的优先级为：

1. Yahoo Finance
2. Alpha Vantage（配置 `ALPHAVANTAGE_API_KEY` 时）
3. Finnhub（配置 `FINNHUB_API_KEY` 时）
4. 本地最近有效缓存

当前版本使用日线数据，因此明确标记为“日线/可能延迟”，不冒充实时行情。单个 ticker 获取失败只会降低该标的的数据质量，不会中断整份报告。交易所后缀 ticker 不会在 fallback 阶段被擅自替换为无后缀证券。

## 指标

每个 ticker 统一计算：

- EMA21、SMA50、SMA200
- ATR(14)
- RSI(14)
- 20 日平均成交量
- 最新日成交量及成交量比率
- 5-bar swing high / swing low
- 支撑区、阻力区及区域强度

成交量比率：

```text
volume_ratio = 最新日成交量 / 20日平均成交量
```

- `<0.7`：低量
- `0.7-1.2`：正常
- `1.2-1.5`：小幅放量
- `1.5-2.0`：明显放量
- `>2.0`：异常放量

## 支撑与阻力

确认后的 5-bar pivot 会按 ATR 聚类。相距不超过约 `1 ATR` 的 pivot 合并为价格区域，不把单一价格点当作精确支撑或阻力。

区域评分综合：

- 触及次数
- 最近出现时间
- 反应时的相对成交量
- ATR 聚类后的区域清晰度
- 是否已经被多次刺穿或有效突破

成交量反应分不再使用“区域内最大成交量是否高于区域内平均成交量”这种弱判断。当前规则为：

```text
volume_ratio = 区域内 pivot 日平均成交量 / 最近20日平均成交量

volume_ratio < 1.0        -> 成交量+0
1.0 <= volume_ratio < 1.5 -> 成交量+5
volume_ratio >= 1.5       -> 成交量+10
```

这里的含义是：支撑或阻力附近是否出现了高于近期常态的成交量反应。它只是区域强度的一部分，不代表该区域一定会反转或突破。

报告中的 `强度 XX/100` 是支撑或阻力区域的结构强度分，用于比较区域的可靠程度。它不是上涨概率、下跌概率、目标价或交易胜率。

Full report 和 Technical HTML 会在每个技术卡片中提供可折叠的“强度拆解”。明细包括区间上下沿、触及次数、距现价、算法组成项和概率提示，方便人工复核该区域是当前交易附近的有效位置，还是距离现价较远的深层结构位。

支撑失效参考：

```text
支撑区下沿 - 0.5 × ATR(14)
```

突破候选要求日线收盘越过历史阻力区，并且成交量高于 20 日均量。报告仍建议观察后续 2-3 个交易日能否守住原阻力区，避免把盘中刺穿当成有效突破。

## 资产类型一致性

权益 ETF 与股票使用趋势、支撑、阻力和量价框架。ERNS 等现金替代或超短债产品不使用“趋势破坏”式权益语言，而改为观察收益率、久期、派息与净值路径。

## 报告与隐私

- Full report 与 Serenity 周报复用同一个 `TechnicalSwingReport`，不重复计算。
- 手动 `technical` 模式向 `PORTFOLIO_EMAIL_TO` 发送精简正文，并附完整 Technical HTML。
- 私人 Technical HTML/JSON 不上传公共 GitHub Artifact。
- 公共 Artifact 继续只包含去除私人持仓的市场报告。
- `output/cache/technical_swing_state.json` 仅保存非敏感技术状态，为以后避免重复提醒保留基础；当前版本不会自动发送独立 swing 警报。

## 手动运行

GitHub Actions 选择：

```text
email_mode = technical
technical_tickers = MSFT,AMD,MSFT.L
```

`technical_tickers` 可完全留空。此时系统仍分析当前持仓和固定 `swing_watchlist`。

本模块用于研究与风险复核，不构成交易建议。
