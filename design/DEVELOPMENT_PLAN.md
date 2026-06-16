# 连续开发计划：从核心闭环到完整系统

## 1. 开发策略

本项目采用**连续开发、分层启用**。

含义：

1. Codex 可以按任务顺序一个接一个开发，不需要等 P0a 跑满 5 个交易日才写 P0b / P0c 代码。
2. 但后续功能必须通过 feature flag 默认关闭，不能污染已经稳定的核心闭环。
3. 每个阶段都有明确验收标准。没通过验收，可以继续开发下一模块的代码，但不得启用到日常生产流水线。
4. 真实账户只读、JSON First、安全扫描、ChatGPT 审核、人工确认是全程硬边界。

推荐节奏：

```text
先搭骨架 → 再做闭环 → 再做影子账户 → 再做估值和主线 → 再做 Web → 再做提醒和复盘
```

## 2. 里程碑总览

| 里程碑 | 名称 | 目标 | 是否可连续开发 |
|---|---|---|---|
| M0 | 项目骨架与安全边界 | 搭目录、配置、测试框架、安全扫描基线 | 是 |
| M1 | JSON Schema 与 SQLite | 建立结构化事实源和历史库 | 是 |
| M2 | 标的池与 QMT 只读导入 | 真实持仓进入标的池但不泄密 | 是 |
| M3 | 市场仓位与审核包 | 跑通 Codex → ChatGPT → 人工确认闭环 | 是 |
| M4 | 报告渲染 | JSON 渲染 Markdown / HTML，不让 AI 写报告 | 是 |
| M5 | 影子账户 | 纸面模拟、净值、回撤、基准对比 | 是，但默认 feature flag 关闭 |
| M6 | 组合分析与真实账户对比 | 比例偏离、桶暴露、ResearchFirst | 是 |
| M7 | ETF / 个股估值 | 估值区间、置信度、复查日期 | 是，但默认 feature flag 关闭 |
| M8 | 主线与龙头研究 | 周频观点、主线强弱、龙头排序 | 是，但默认 feature flag 关闭 |
| M9 | Web 工作台 | 只读展示当前状态、曲线、审核包 | 是 |
| M10 | 异常提醒与复盘评分 | 失败提醒、结论漂移、自动复盘 | 是 |

## 3. M0：项目骨架与安全边界

### 目标

建立可持续开发的工程骨架，先把“不越界”做成代码。

### 交付

```text
pyproject.toml 或 requirements.txt
src/invest_system/
scripts/
schemas/
tests/
config/feature_flags.yaml
scripts/security_scan.py
.gitignore
README.md
```

### 验收

1. 测试框架可以运行。
2. `.env`、`.db`、QMT 快照、真实持仓目录被 `.gitignore` 排除。
3. `security_scan.py` 能发现总资产、金额、股数、订单号等敏感字段。
4. CI 或本地测试命令可一键运行。

### Codex 提示词

```text
实现 M0 项目骨架与安全边界。
只搭结构、测试框架、配置和 security_scan，不实现投资逻辑。
必须新增测试，证明敏感字段会被扫描阻断。
不要接入真实交易接口。
```

## 4. M1：JSON Schema 与 SQLite

### 目标

确立 JSON 是唯一事实源，SQLite 是历史库。

### 交付

```text
schemas/common.schema.json
schemas/market_position.schema.json
schemas/portfolio.schema.json
schemas/target_pool.schema.json
schemas/shadow_account.schema.json
src/invest_system/validators/json_schema_validator.py
src/invest_system/repositories/sqlite_repo.py
scripts/init_db.py
```

### 验收

1. 合法 JSON 通过校验。
2. 缺少通用字段的 JSON 失败。
3. JSON 校验失败不得入库。
4. SQLite 能保存 snapshot_id、module、basis_date、status 和 payload。

### Codex 提示词

```text
实现 M1 JSON Schema 与 SQLite。
要求 JSON First：所有研究结果以 JSON snapshot 为主。
不要生成 Markdown。
实现 schema 校验和 SQLite 入库。
测试覆盖合法、缺字段、非法状态、入库失败场景。
```

## 5. M2：标的池与 QMT 只读导入

### 目标

真实持仓只读导入后自动进入标的池，但不能暴露金额、股数或账户信息。

### 交付

```text
src/invest_system/collectors/qmt_position_importer.py
src/invest_system/target_pool/service.py
schemas/target_pool.schema.json
scripts/import_qmt_positions.py
tests/fixtures/qmt_positions_sample.csv
```

### 验收

1. QMT 样例持仓能导入。
2. 导入后标的自动进入标的池。
3. 对外 JSON / Web payload 只展示比例和桶分类，不展示金额、股数、账户号。
4. QMT 未登录或文件缺失时，保留上一快照并提示。

### Codex 提示词

```text
实现 M2 标的池与 QMT 只读导入。
QMT 只允许读取样例文件，不允许下单或调用交易接口。
真实明细只能保存在本地私有路径，对外输出必须脱敏。
新增测试：导入成功、缺文件、敏感字段扫描、真实持仓自动进入标的池。
```

## 6. M3：市场仓位与审核包

### 目标

跑通每日最小闭环：事实包 → 市场仓位 JSON → 校验 → 安全扫描 → 审核包。

### 交付

```text
scripts/generate_fact_pack.py
src/invest_system/research/market_position.py
scripts/create_review_package.py
schemas/market_position.schema.json
review_packages/{date}/review_package.json
```

### 验收

1. 能用 fixture 生成 market_position snapshot。
2. snapshot 包含 executive_summary、key_facts、reasoning、risks、invalidation_conditions。
3. 审核包包含 JSON、schema 校验结果、数据质量结果、安全扫描结果和待审问题。
4. 未 ChatGPT 审核、未人工确认时不得 finalized。

### Codex 提示词

```text
实现 M3 市场仓位与审核包。
AI 模块只输出 JSON，不写 Markdown。
审核包必须可提交给 ChatGPT 二审。
实现状态流 draft → json_validated → review_package_created。
不要实现影子账户和估值。
```

## 7. M4：报告渲染

### 目标

证明 Markdown 是派生视图，不是事实源。

### 交付

```text
scripts/render_report.py
templates/market_position.md.j2
templates/portfolio.md.j2
tests/test_render_report.py
```

### 验收

1. JSON 能渲染为 Markdown。
2. Markdown 中带 source_snapshot_id 或 hash。
3. 渲染脚本不得修改结论、结论强度和可行动性。
4. Markdown 生成失败不影响 JSON 入库。

### Codex 提示词

```text
实现 M4 报告渲染。
render_report.py 只能从 JSON 或 SQLite 读取数据并套模板。
不得让 AI 生成 Markdown。
测试证明渲染结果与 JSON 结论一致。
```

## 8. M5：影子账户

### 目标

建立纸面模拟账户，验证策略与真实账户差异。

### 交付

```text
src/invest_system/shadow/account.py
src/invest_system/shadow/rebalance.py
schemas/shadow_account.schema.json
scripts/update_shadow_account.py
```

### 验收

1. 只使用标的池内标的。
2. ResearchFirst 权重必须为 0。
3. 审核失败或未 human_approved 时，不执行当日新策略。
4. 能输出 holdings_weight、paper_trades、nav_index、turnover、drawdown、benchmark_returns。
5. 池外标的买入测试必须失败。

### Codex 提示词

```text
实现 M5 影子账户，默认通过 feature flag 关闭。
首版只用固定规则，不允许 AI 自由调仓。
必须测试池外标的禁止买入、ResearchFirst 权重为 0、未 human_approved 不调仓。
```

## 9. M6：组合分析与真实账户对比

### 目标

用比例和风险桶展示真实账户、影子账户和指数的差异。

### 交付

```text
src/invest_system/portfolio/analyzer.py
schemas/portfolio.schema.json
scripts/analyze_portfolio.py
```

### 验收

1. 组合分析只展示比例、百分点、目标区间和风险桶。
2. 能计算 bucket_weights、target_ranges、deviation_pp。
3. 能输出 research_first_list 和 action_candidates。
4. ResearchFirst 不得进入 action_candidates。

### Codex 提示词

```text
实现 M6 组合分析与真实账户对比。
不得输出总资产、持仓金额、股数、收益金额、订单明细。
只输出比例、百分点、净值指数、回撤和偏离度。
```

## 10. M7：ETF / 个股估值

### 目标

建立结构化估值记录，不追求每天全量估值。

### 交付

```text
src/invest_system/research/etf_research.py
src/invest_system/research/stock_valuation.py
schemas/etf_research.schema.json
schemas/stock_valuation.schema.json
```

### 验收

1. ETF 研究包含 tracking_target、valuation_status、liquidity_status、rating、data_gaps。
2. 个股估值包含 fair_value_low/mid/high、method、confidence、rating、next_review_date。
3. 新标的必须先 research_first，不能直接 action_candidate。
4. 价格偏离、重大新闻、人工要求可触发复查。

### Codex 提示词

```text
实现 M7 ETF / 个股估值 JSON schema、服务和测试，默认 feature flag 关闭。
不要每天全量估值。
新增标的必须先进入 ResearchFirst。
```

## 11. M8：主线与龙头研究

### 目标

建立周频观点模块，不让 AI 每天重写主线。

### 交付

```text
src/invest_system/research/theme_research.py
src/invest_system/research/leader_research.py
schemas/theme_research.schema.json
schemas/leader_research.schema.json
```

### 验收

1. 主线研究只包含 theme_id、theme_name、sector、theme_state、signal_type、leading_indicators、strength_score（仅辅助）和 invalidation_conditions；禁止输出股票代码、ETF 代码、leading_symbols、related_etfs 或任何可交易资产集合。
2. 个股研究独立输出 symbol、valuation_state、research_first_status、risk_score、signal_type、gates、next_review_date；不得反向改写主线强度。
3. 重大结论变化必须写入 decision_change_log。
4. 缺少新增证据时，不得大幅改变结论。

### Codex 提示词

```text
实现 M8 主线与龙头研究，默认 feature flag 关闭。
该模块以周频观点为主，禁止每天无证据漂移。
实现结论漂移检测和测试。
```

## 12. M9：Web 工作台

### 目标

建立只读展示，不提供真实交易入口。

### 交付

```text
src/invest_system/web/app.py
src/invest_system/web/pages/
```

### 验收

1. 今日状态页。
2. 市场仓位页。
3. 标的池页。
4. 组合偏离页。
5. 影子账户页。
6. 审核包页。
7. 页面不得展示敏感字段。
8. 页面不得提供真实交易入口。

### Codex 提示词

```text
实现 M9 Web 工作台，只读展示。
所有页面读取 SQLite 或 JSON。
不得显示总资产、股数、金额、订单、账户号。
不得提供交易按钮或下单入口。
```

## 13. M10：异常提醒与复盘评分

### 目标

让系统能提醒失败、记录漂移、辅助长期复盘。

### 交付

```text
src/invest_system/alerts/
src/invest_system/review/decision_change_log.py
src/invest_system/review/backtest_review.py
```

### 验收

1. 数据源失败提醒。
2. QMT 未登录提醒。
3. JSON 校验失败提醒。
4. 安全扫描失败提醒。
5. 估值大幅变化提醒。
6. 结论漂移提醒。
7. 月度复盘评分。

### Codex 提示词

```text
实现 M10 异常提醒与复盘评分。
提醒只输出风险和状态，不输出真实交易指令。
结论漂移必须引用旧结论、新结论和新增证据。
```

## 14. 不建议让 Codex 自行决定的事项

不要让 Codex 自己决定：

1. 是否接入真实交易接口。
2. 是否改变 JSON First 原则。
3. 是否把 Markdown 作为事实源。
4. 是否跳过 ChatGPT 审核。
5. 是否跳过人工确认。
6. 是否允许 ResearchFirst 进入 action_candidates。
7. 是否启用 AI 自由调仓。
8. 是否扩大 Web 到多租户和收费服务。

这些应由文档和人工明确规定。

## 15. 可以让 Codex 自行设计的事项

可以让 Codex 在边界内自行设计：

1. Python 包结构细节。
2. 函数名和类名。
3. 测试 fixture 格式。
4. SQLite 表的具体索引。
5. Web 框架选择的轻量实现。
6. 模板渲染细节。
7. 局部重构方案。

原则是：

```text
边界你定，架构我定，局部实现让 Codex 定。
```

更准确地说：

```text
ChatGPT / 人工定产品边界和主架构；Codex 定代码实现细节。
```
