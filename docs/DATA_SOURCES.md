# 数据源、缓存与回退机制

## 数据源

项目按指标类型混合使用 Yahoo Finance、FRED、CNN、NAAIM、Investing、发行商产品页、StockAnalysis、白宫 RSS、Google News 和 GDELT。

混合数据源是有意设计：实时市场价格、低频宏观数据、基金静态资料和新闻事件不应被强制塞进同一个接口。

## Options Gamma / Dealer Hedging 数据源

- 默认首选 Yahoo/yfinance option chain。模块先尝试 Yahoo JSON endpoint；如果遇到 401/session/cookie 限制，则回退到 `yfinance`。
- Alpha Vantage `HISTORICAL_OPTIONS` 和 `REALTIME_OPTIONS` 是 premium option-chain endpoint，因此不作为免费默认源；只有显式配置且 key 有 premium 权限时才应启用。
- Alpha Vantage 免费 ratio endpoint（`REALTIME_PUT_CALL_RATIO`、`HISTORICAL_PUT_CALL_RATIO`、`REALTIME_VOLUME_OPEN_INTEREST_RATIO`、`HISTORICAL_VOLUME_OPEN_INTEREST_RATIO`）可用于情绪监控，但不提供计算 dealer gamma 所需的 strike-level chain 字段。
- 如果显式启用 Alpha Vantage option chain 且期权链里缺少 spot，`alpha_vantage_fetch_spot_quote=true` 会用 Alpha Vantage `GLOBAL_QUOTE` 补充标的价格。
- UK/LSE UCITS ETF 通常没有可用期权链；系统保留覆盖说明，但不生成大量 N/A 卡片。
- Dealer gamma 只是基于 OI、成交量、成交位置和 Black-Scholes gamma 的启发式估计，不是直接观察 dealer books。

## 期权历史快照与回测

- `scripts/snapshot_option_chain.py` 将 Yahoo/yfinance 当前期权链按日期写入 `output/option_history/<TICKER>/`，同时保存 CSV 和来源/告警元数据 JSON。
- Yahoo/yfinance 只提供当前可交易期权链；缓存或当天快照不能重建过去的 Bid/Ask、IV 或 Greeks。回测只能使用实际逐日积累的快照，不能使用当前链回填历史。
- Alpha Vantage `HISTORICAL_OPTIONS` 需要 premium 权限。配置免费 key 不代表该端点可用。
- Cboe 免费 Historical Options Data Download 是成交量汇总，不是逐合约历史 NBBO 数据。专业 EOD 回测应使用 Cboe DataShop `Option EOD Summary`（含 15:45 NBBO，可选 IV/Greeks）或等价的授权数据集。
- 快照命令示例：`python scripts/snapshot_option_chain.py QQQ --max-days 120 --expirations 18`。
- `scripts/download_thetadata_option_eod.py` 可选地通过 ThetaData Python client 下载授权范围内的逐合约 EOD 数据。API key 仅从 `THETADATA_API_KEY` 环境变量读取，默认输出写入已被 Git 忽略的 `output/thetadata/`。
- ThetaData 命令示例：`python scripts/download_thetadata_option_eod.py SPY 2026-09-18 2026-07-01 2026-07-31 --right put`。该脚本是通用下载器，不保证特定订阅层级的数据覆盖范围。

## Options Sentiment / Short Premium Context 数据源

- 默认使用 Alpha Vantage 免费 `REALTIME_PUT_CALL_RATIO`，按 `SPY`、`QQQ`、当前持仓和配置的关注 ticker 生成 ticker-level short premium context。
- Put-call ratio 用于辅助判断 put-side premium、call-side pressure 或 two-sided neutral premium；它不替代期权链、IV rank、earnings/event check、delta/POP 或保证金约束。
- 没有 `ALPHA_VANTAGE_API_KEY` 时该面板会降级为单条数据不足说明，不影响 Gamma/yfinance option chain。

## 韧性策略

- 外部请求使用重试和合理超时
- 成功抓取写入本地 JSON cache
- FRED 使用最近有效 observation，不强制要求当天更新
- 核心指标失败时优先 fallback，再考虑新鲜缓存
- 辅助指标失败时降低置信度，但继续生成报告
- 缓存、fallback、缺失、延迟和可疑范围都会显式标记

系统不会把缓存伪装成实时数据。

## GitHub Actions cache

GitHub Actions 使用 `actions/cache` 保存：

```text
output/cache
```

它用于逐步积累 ETF 估值历史、PE 位置和市场数据缓存，但不是永久数据库。GitHub 清理 cache 后，轻量历史会从下一次运行重新积累。

Actions 页面只能查看 cache key、大小和最近使用时间，不能直接浏览内容。需要审计时，应在 workflow 中增加只读 artifact 导出步骤，或在本地查看 `output/cache`。
