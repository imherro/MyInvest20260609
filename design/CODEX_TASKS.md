# Codex 开发任务清单

## 使用方式

每次只给 Codex 一个任务。任务完成后要求它输出：

1. 修改了哪些文件。
2. 新增了哪些测试。
3. 测试命令和结果。
4. 是否触碰安全边界。
5. 下一步建议。

不要一次让 Codex 做完整系统，否则它容易扩大范围、跳过测试或把后续功能提前接入主流程。

## 全局硬约束

每个任务都必须遵守：

```text
1. 真实账户只读，不接真实下单接口。
2. AI 只生成 JSON，不直接生成 Markdown 报告。
3. Markdown / HTML / PDF 只能由脚本从 JSON 或 SQLite 渲染。
4. JSON 必须 schema 校验后才能入库。
5. 安全扫描失败不得发布。
6. ResearchFirst 不得进入 action_candidates。
7. ResearchFirst 不得进入影子账户。
8. 未 ChatGPT 审核、未人工确认，不得 finalized。
9. 影子账户只做纸面模拟。
10. Web 只读，不提供交易入口。
```

## 推荐分支命名

```text
feat/m0-scaffold-security
feat/m1-json-schema-sqlite
feat/m2-target-pool-qmt-readonly
feat/m3-market-position-review-package
feat/m4-render-report
feat/m5-shadow-account
feat/m6-portfolio-analysis
feat/m7-valuation
feat/m8-theme-leader-research
feat/m9-web-dashboard
feat/m10-alerts-review
```

## Task 0：读取文档并生成实现计划

### 给 Codex 的提示词

```text
请先阅读 FEATURES.md、REQUIREMENTS.md、ARCHITECTURE.md、DEVELOPMENT_PLAN.md、CODEX_TASKS.md。

不要写代码。

请输出你的实现计划，要求：
1. 按 M0-M10 分阶段。
2. 每阶段列出要修改/新增的文件。
3. 每阶段列出测试方案。
4. 明确哪些功能通过 feature flag 默认关闭。
5. 明确不会触碰真实交易接口。
6. 明确 JSON First，Markdown on Demand。

不要改变需求边界。
```

## Task 1：M0 项目骨架与安全扫描

### 提示词

```text
实现 M0：项目骨架与安全边界。

范围：
1. 创建推荐目录结构。
2. 创建 config/feature_flags.yaml。
3. 创建 scripts/security_scan.py。
4. 创建 .gitignore，排除 .env、*.db、data/qmt_snapshots、真实持仓明细。
5. 创建测试框架。
6. 新增 security_scan 测试。

禁止：
1. 不实现投资逻辑。
2. 不接入真实交易接口。
3. 不生成 Markdown 报告。

验收：
1. security_scan 能识别总资产、持仓金额、股数、订单号、账户号、API key。
2. 测试可运行并通过。
```

## Task 2：M1 JSON Schema 与 SQLite

### 提示词

```text
实现 M1：JSON Schema 与 SQLite。

范围：
1. schemas/common.schema.json。
2. schemas/market_position.schema.json。
3. schemas/portfolio.schema.json。
4. schemas/target_pool.schema.json。
5. schemas/shadow_account.schema.json。
6. JSON schema validator。
7. SQLite 初始化脚本和 repository。
8. fixture 和测试。

要求：
1. JSON 是唯一事实源。
2. 缺少通用字段必须校验失败。
3. 校验失败不得入库。
4. SQLite 至少保存 snapshot_id、module、basis_date、status、payload_json、created_at。

禁止：
1. 不生成 Markdown。
2. 不实现影子账户逻辑。
```

## Task 3：M2 标的池与 QMT 只读导入

### 提示词

```text
实现 M2：标的池与 QMT 只读导入。

范围：
1. qmt_position_importer.py，只读取 fixture 或本地导出文件。
2. target_pool service。
3. target_pool schema。
4. 脱敏输出。
5. 测试。

要求：
1. 真实持仓导入后自动进入标的池。
2. 对外输出只展示比例和分类，不展示金额、股数、账户号。
3. QMT 文件缺失时保留上一快照并提示。
4. 不得调用任何真实交易、下单、撤单接口。
```

## Task 4：M3 市场仓位与审核包

### 提示词

```text
实现 M3：市场仓位 JSON 与 ChatGPT 审核包。

范围：
1. generate_fact_pack.py。
2. market_position research service。
3. create_review_package.py。
4. review_package schema 或结构。
5. 测试。

要求：
1. AI 研究输出只允许 JSON。
2. market_position JSON 必须包含 executive_summary、key_facts、reasoning、risks、invalidation_conditions、conclusion_strength、actionability。
3. 审核包包含 schema 校验结果、数据质量结果、安全扫描结果、待审问题。
4. 状态只能到 review_package_created，不得 finalized。
```

## Task 5：M4 报告渲染

### 提示词

```text
实现 M4：报告渲染。

范围：
1. scripts/render_report.py。
2. templates/market_position.md.j2。
3. 测试。

要求：
1. Markdown 只能由 JSON 或 SQLite 渲染。
2. 渲染结果必须带 source_snapshot_id。
3. 渲染脚本不得新增事实，不得改变结论强度和可行动性。
4. JSON 入库不依赖 Markdown 成功。
```

## Task 6：M5 影子账户

### 提示词

```text
实现 M5：影子账户纸面模拟，默认 feature flag 关闭。

范围：
1. shadow account 模块。
2. 固定规则再平衡。
3. shadow_account schema。
4. update_shadow_account.py。
5. 测试。

要求：
1. 只做纸面模拟，不发送真实订单。
2. 只允许标的池内标的。
3. ResearchFirst 权重必须为 0。
4. 未 human_approved 不得执行当日新策略。
5. 输出 nav_index、holdings_weight、paper_trades、turnover、drawdown、benchmark_returns。
```

## Task 7：M6 组合分析

### 提示词

```text
实现 M6：组合分析与真实账户对比。

范围：
1. portfolio analyzer。
2. bucket 权重计算。
3. target_ranges 和 deviation_pp。
4. research_first_list 和 action_candidates。
5. 测试。

要求：
1. 只使用比例、百分点、目标区间、风险桶、净值指数。
2. 不展示总资产、金额、股数、收益金额、订单明细。
3. ResearchFirst 不得进入 action_candidates。
```

## Task 8：M7 ETF / 个股估值

### 提示词

```text
实现 M7：ETF / 个股估值 JSON 模块，默认 feature flag 关闭。

范围：
1. ETF research schema 和 service。
2. stock valuation schema 和 service。
3. 估值触发条件。
4. 测试。

要求：
1. 新标的必须先 ResearchFirst。
2. 估值输出必须有 fair_value_low/mid/high 或 valuation_status。
3. 必须有 confidence、rating、method、next_review_date。
4. 不要每天全量估值。
```

## Task 9：M8 主线与龙头研究

### 提示词

```text
实现 M8：主线与龙头研究，默认 feature flag 关闭。

范围：
1. theme_research schema 和 service。
2. leader_research schema 和 service。
3. decision_change_log。
4. 结论漂移检测。
5. 测试。

要求：
1. 主线观点以周频为主。
2. 重大结论变化必须记录旧结论、新结论、变化原因、新增证据。
3. 无新增证据不得大幅改变结论。
```

## Task 10：M9 Web 工作台

### 提示词

```text
实现 M9：只读 Web 工作台。

范围：
1. 今日状态页。
2. 市场仓位页。
3. 标的池页。
4. 组合偏离页。
5. 影子账户页。
6. 审核包页。

要求：
1. 所有页面读取 SQLite 或 JSON。
2. 不展示总资产、持仓金额、股数、订单号、账户号。
3. 不提供交易按钮、下单入口或交易 API。
4. 页面展示必须经过脱敏测试。
```

## Task 11：M10 异常提醒与复盘评分

### 提示词

```text
实现 M10：异常提醒与复盘评分。

范围：
1. 数据失败提醒。
2. QMT 未登录提醒。
3. JSON 校验失败提醒。
4. 安全扫描失败提醒。
5. 估值大幅变化提醒。
6. 结论漂移提醒。
7. 月度复盘评分。

要求：
1. 提醒只输出状态、风险和需要人工处理事项。
2. 不输出真实交易指令。
3. 复盘评分必须引用历史 JSON 和决策日志。
```

## 每次任务完成后的回复模板

要求 Codex 每次按这个格式回复：

```text
完成任务：M?

修改文件：
- ...

新增测试：
- ...

运行命令：
- ...

测试结果：
- passed / failed

安全边界：
- 未接入真实交易接口
- 未输出真实金额/股数/账户号
- JSON First 保持有效

风险：
- ...

下一步建议：
- ...
```


# ADDITIONAL CODEx SIMPLIFIED STRATEGY

See CODEx_GUIDE.md for execution rules.
