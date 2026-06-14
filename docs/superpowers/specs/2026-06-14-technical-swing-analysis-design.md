# Technical Swing Analysis 设计规格

## 目标

为 Macro Regime Radar 增加独立的技术结构分析模块，统一覆盖：

1. 当前全部持仓；
2. 配置中的长期 `swing_watchlist`；
3. GitHub Actions 手动运行时可选的临时 ticker。

模块用于日常结构观察、回调复核和建仓准备，不提供直接买卖指令。输出使用“观察、确认、支撑、阻力、风险、失效、结构”等措辞。

## 范围与入口

分析集合为：

```text
当前持仓 + swing_watchlist + technical_tickers
```

- 当前持仓自动读取，无需重复配置。
- `swing_watchlist` 是长期观察池，每次 Full 或 Technical 模式均分析。
- `technical_tickers` 是单次 GitHub Actions 手动输入，不写回配置。
- 三个来源均允许为空。
- 临时 ticker 完全不提供时属于正常路径。
- 若最终集合为空，报告生成空状态说明，不报错、不发送误导性判断。
- 输入允许空格、连续逗号、尾部逗号和重复 ticker，解析后清理并去重。
- 完整 ticker 是唯一身份；`MSFT` 与 `MSFT.L` 不合并。

## 标的身份校验

每个 ticker 保存并展示：

- 请求 ticker；
- Yahoo/行情源返回 ticker；
- 名称；
- 交易所；
- 币种；
- instrument type。

若返回结果与请求交易所后缀、资产类型或持仓币种明显冲突，则标记“标的身份待确认”，保留数据质量说明，但不生成技术结论。持仓匹配优先使用 statement 中的 ticker、ISIN、交易所和币种；不自动把 LSE ticker 映射为美股 ticker。

## 架构边界

新增独立模块 `market_report/technical_swing.py`，不把新逻辑继续堆入 ETF 评分或 Serenity 模块。

实施遵循“复用优先”：

- 扩展现有 Yahoo chart HTTP 请求与缓存结构，不另建平行情源客户端；
- 抽取并复用现有 EMA、SMA、RSI、历史价格和 ticker/币种映射算法；
- 复用现有 `PortfolioPosition`、Full report payload、Serenity 输入及私人邮件附件流程；
- 复用公共 Artifact 的持仓清洗边界；
- 只有现有接口无法表达 OHLCV、ATR、pivot zone 或 Technical 专属报告时才新增类型和函数。

Full、Serenity 和 Technical 模式必须消费同一份 `SwingAssessment`，不得分别重算或维护不同阈值。

核心对象：

- `SwingInstrumentIdentity`
- `SwingMarketData`
- `SwingZone`
- `SwingAssessment`
- `TechnicalSwingReport`

核心职责：

1. universe resolver：合并持仓、长期观察池和临时 ticker；
2. market data provider：获取、校验并缓存 OHLCV；
3. indicator engine：计算均线、ATR、RSI、量比；
4. pivot/zone engine：识别 pivot、聚类支撑阻力区；
5. state classifier：输出趋势与技术状态；
6. renderer：为 Full、Serenity 和 Technical 私人邮件提供不同摘要层级。

宏观总风险分与现有 ETF 新增仓位环境分不因该模块直接改变。

## 数据获取与降级

第一优先复用项目现有 Yahoo chart HTTP 接口，避免为了同一来源额外引入 `yfinance` 依赖。可选适配器按以下优先级启用：

1. Yahoo Finance 日线与盘中 OHLCV；
2. Alpha Vantage（存在 API key 时）；
3. Finnhub（存在 API key 时）；
4. IBKR（存在可用市场数据订阅和接口时）。

每个 ticker 独立失败，不影响其他 ticker 或整份报告。

缓存条目必须包含：

- ticker 和身份信息；
- interval；
- observation timestamp；
- fetch timestamp；
- source；
- delayed/cache 状态；
- OHLCV 数据。

数据质量状态：

- 实时/盘中；
- 收盘数据；
- 延迟数据；
- 仅日线；
- 使用新鲜缓存；
- 缓存过期；
- 数据缺失；
- 身份待确认。

第一版允许只有日线数据。盘中数据不可用时明确显示“仅日线/延迟数据，盘中确认不可用”。

## 指标

每个有效 ticker 计算：

- 当前价格；
- EMA21；
- SMA50；
- SMA200；
- ATR(14)，使用 True Range 的 Wilder 平滑；
- RSI(14)，使用 Wilder 平滑；
- 20 日平均成交量；
- 当日成交量；
- 日线量比；
- 可用时的盘中同时间校准量比。

盘中量比同时保留两项：

```text
全天均量占比 = 当前累计成交量 / 过去20日全天平均成交量
同时间校准量比 = 当前累计成交量 / 过去可比交易日同一时刻平均累计成交量
```

若只有第一项，不把 `<0.7` 直接解释为低量，只说明其为全天均量占比。收盘后才使用原始量比阈值：

- `<0.7`：低量；
- `0.7–1.2`：正常；
- `1.2–1.5`：温和放量；
- `1.5–2.0`：明显放量；
- `>2.0`：极高成交量。

## Pivot 与支撑阻力区

确认 pivot 使用五根 K 线：

```text
Pivot low: Low[t] < Low[t-1], Low[t-2], Low[t+1], Low[t+2]
Pivot high: High[t] > High[t-1], High[t-2], High[t+1], High[t+2]
```

最近两根 K 线缺少未来两根确认，仅可产生“候选 pivot”，不进入确认突破和历史回测。

聚类规则：

- 合并阈值为 `min(1 ATR, 当前价格的3%)`；
- 支撑区由 swing lows 形成；
- 阻力区由 swing highs 形成；
- 默认区域半宽为 `0.5 ATR`，根据簇内离散度可放宽，但总宽度不得超过 `2 ATR` 或价格的 `6%`；
- 最多展示最近且得分最高的两个支撑区和两个阻力区；
- 被持续穿透、已长期失效或过旧的区域降低权重。

区域得分采用透明分项，而不是只显示黑箱总分：

- 触碰次数；
- 新近性；
- 反应成交量；
- EMA21/SMA50/SMA200 共振；
- 整数位共振；
- 被穿透次数惩罚；
- 突破后角色转换加分。

## 趋势分类

- 强势多头：`Price > EMA21 > SMA50 > SMA200`
- 上升趋势回调：`Price < EMA21` 且 `EMA21 > SMA50 > SMA200`
- 中期转弱：`Price < SMA50` 且 `EMA21 < SMA50`，但 `SMA50 > SMA200`
- 空头结构：`Price < EMA21 < SMA50 < SMA200`
- 其余：中性/混合

趋势分类只是结构描述，不等同于投资建议。

## 技术状态

可能状态：

- 接近支撑；
- 接近阻力；
- 回调观察；
- 候选突破；
- 收盘突破确认；
- 连续确认；
- 回踩确认；
- 失败突破；
- 候选跌破；
- 支撑失效；
- 趋势恢复观察；
- 延伸过度，等待结构重置；
- 弱势观察，暂无结构确认；
- 中性。

突破确认要求：

- 日线收盘高于阻力区上沿；
- 收盘成交量高于 20 日平均量；
- 盘中刺穿只能标记候选；
- 连续 2–3 个收盘维持在区域上方可升级为连续确认；
- 突破后收盘重新跌回原阻力区下方，标记失败突破。

跌破逻辑对称处理。

## ATR 失效观察位

- 支撑失效观察位：支撑区下沿减 `0.5 ATR`；
- 突破失效：收盘重新回到原阻力区下方；
- 该价位用于风险复核，不描述为止损价或交易指令。

## 资产类型差异

所有个股和 ETF 都执行技术分析，但解释层按资产类型调整：

- 个股与权益 ETF：完整趋势、成交量、突破和回调逻辑；
- 黄金/商品 ETF：保留技术结构，并提示美元、实际利率或商品驱动；
- 债券 ETF：结合久期、收益率方向和信用风险；
- 现金/超短债 ETF：不把分派后的机械回落或 SMA200 偏离解释为权益式趋势破坏，重点展示收益率、短端利率、久期和流动性。

## 报告集成

### Full report

新增：

1. 持仓技术结构；
2. 长期/临时观察池技术结构；
3. 数据质量与降级说明。

默认显示摘要；每个 ticker 展开后显示区域评分构成和详细依据。持仓额外展示成本、未实现盈亏和组合权重。

### Serenity 周报

- 保留现有筛选摘要；
- 对筛选出的重点个股加入趋势、量价、关键区域和失效条件；
- ETF 只提供技术结构摘要，不做公司级 Serenity 基本面分析；
- 现金/短债使用专属解释。

### 手动 Technical 模式

GitHub Actions 增加：

```text
email_mode: technical
technical_tickers: 可选，默认空字符串
```

运行行为：

- 分析全部持仓、`swing_watchlist` 和本次临时 ticker；
- 发送精简摘要至 `PORTFOLIO_EMAIL_TO`；
- 完整 Technical HTML 作为私人邮件附件；
- 不上传私人 HTML/JSON Artifact；
- 公共 Artifact 若保留，仅能包含去除持仓、成本和盈亏后的版本。

第一版不增加 UK ETF 专属定时扫描，也不启用自动 Swing 事件邮件。

## 状态记忆

第一版保存每个 ticker 的：

- 上次趋势分类；
- 上次技术状态；
- 上次支撑/阻力区；
- 上次确认突破/跌破日期；
- 数据身份和来源。

状态历史用于 Full 与 Serenity 的“较上次变化”，并为后续事件提醒积累误报验证数据。第一版不据此自动发信。

## 配置

配置增加：

```json
{
  "swing_watchlist": []
}
```

环境变量/手动输入：

```text
TECHNICAL_TICKERS=""
```

解析规则：

- 英文逗号分隔；
- 清理空格和空项；
- ticker 大写规范化，但保留后缀；
- 稳定去重；
- 无效 ticker 仅进入数据质量区。

## 隐私

- 持仓成本、数量、盈亏和权重只进入私人 Full、Serenity 和 Technical 邮件。
- 公共 Artifact 不包含私人组合数据。
- 临时 ticker 本身不视为持仓，但 Technical 私人报告仍不上传完整 Artifact，避免暴露用户研究意图。
- 行情缓存不得包含账户号、交易流水或 statement 原文。

## 测试与验收

单元测试至少覆盖：

- 三类 ticker 来源合并和稳定去重；
- 临时 ticker 缺失、空白、重复逗号和全部为空；
- `MSFT` 与 `MSFT.L` 不合并；
- 身份冲突停止技术判断；
- 指标计算；
- pivot 未来确认边界；
- ATR 聚类宽度限制；
- 区域评分与穿透惩罚；
- 盘中量比不误用收盘阈值；
- 突破、失败突破、跌破和回踩状态；
- ERNS 类现金/短债不产生权益式趋势破坏；
- 单 ticker 数据失败不影响其他 ticker；
- Technical 私人报告不进入公共 Artifact；
- Full 与 Serenity 使用同一 Swing assessment，避免文案和数值分叉。

验收样本应包含：

- 低波动宽基 ETF；
- 高波动个股；
- LSE ETF；
- 美股；
- 黄金或商品 ETF；
- 债券/现金替代 ETF；
- 无效 ticker；
- 只有日线数据的 ticker。
