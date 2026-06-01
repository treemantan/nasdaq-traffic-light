# 数据源、缓存与回退机制

## 数据源

项目按指标类型混合使用 Yahoo Finance、FRED、CNN、NAAIM、Investing、发行商产品页、StockAnalysis、白宫 RSS、Google News 和 GDELT。

混合数据源是有意设计：实时市场价格、低频宏观数据、基金静态资料和新闻事件不应被强制塞进同一个接口。

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
