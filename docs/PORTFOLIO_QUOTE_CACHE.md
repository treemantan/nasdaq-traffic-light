# 组合行情缓存与降级机制

Revolut statement 只负责重建持仓数量和历史 GBP 成本，不包含可靠的实时行情。组合导入器会额外抓取 Yahoo 行情，并把每次成功结果保存到：

```text
output/cache/portfolio_quote_cache.json
```

缓存包含 ticker、最近价格、前收盘价、原币币种、抓取时间和最近历史日线。本地运行和 GitHub Actions 都会复用该文件。

## 降级顺序

当实时行情暂时不可用时，导入器依次尝试：

1. 使用最近 7 天内的组合行情缓存。完整历史日线仍可用于 SMA200、距年内高点和回撤性质判断。
2. 对 ETF 观察池中的产品，使用 `output/cache/etf_monitor_cache.json` 的最近有效价格。该层可恢复参考估值和日变化，但不一定具备完整历史日线。
3. 若仍无有效行情，使用 statement 平均成本作为参考估值。

第 3 层仅用于避免报告中断。报告会明确显示 `statement-average-cost fallback`，此时原币市值、日变化、距年内高点、SMA200 和未实现盈亏不应视为可用。

## 如何判断是否正常

周末或节假日使用最近有效收盘价属于正常行为。

如果整组持仓全部显示 `statement-average-cost fallback`，则不属于正常周末状态。应优先检查：

- Yahoo 行情接口是否临时不可用
- 本地或 GitHub Actions 是否受到网络限制
- ticker 是否需要市场后缀，例如 `.L`
- FX ticker 是否可以正常获取

GitHub Actions 已经保存 `output/cache`，因此云端成功运行后会逐步积累组合行情缓存。缓存适合轻量连续监控，不应当作永久数据库。

## iPhone 导出的 UUID 文件名

iPhone 保存到 OneDrive 后，statement 有时会显示为类似：

```text
9B4221B1-92C0-4957-B42B-320C617C4FE8.csv
```

这是导出流程生成的 UUID 文件名，不是乱码。系统不会依赖文件名前缀，而是读取 CSV 表头确认是否为 Revolut trading statement。专用 inbox 中可以同时保存标准文件名和 UUID 文件名的 `.csv` 导出。
