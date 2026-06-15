# 需求规格

## 一、项目原则

本项目是本地投资研究与风控系统，不是自动交易系统。

系统只输出研究记录、风险提示、仓位区间、比例偏离、ResearchFirst 清单、影子账户纸面模拟和人工可审查候选建议。

真实账户永远只读导入，永远不自动交易。

最终入库流程：

```text
Codex JSON 初稿 → JSON 校验 → 安全检查 → ChatGPT 复核 → 人工确认 → finalized 入库
```

## 二、优先级

| 优先级 | 范围 | 目标 |
|---|---|---|
| P0a | SQLite、JSON schema、标的池、QMT 持仓只读导入、市场仓位快照、审核包、安全检查、报告渲染脚本 | 跑通证据库和审核闭环 |
| P0b | 影子账户、真实持仓/影子账户/指数对比、历史曲线、回撤、换手率 | 验证策略与真实账户差异 |
| P0c | ETF 估值、个股估值、主线识别、龙头排序、自动复盘评分 | 增强 AI 研究能力 |
| P1 | Web 工作台、异常提醒、复查任务、更多展示页面 | 提升可视化和日常使用体验 |
| P2 | 更多宏观、海外联动、多模型交叉审核、长期复盘评分 | 提升系统深度 |

开发可以按 P0a → P0b → P0c → P1 → P2 连续推进，不要求日历时间等待；但 P0b / P0c / P1 / P2 的功能必须默认通过 feature flag 控制，只有在其依赖的 schema、测试、安全扫描和审核门禁通过后，才能启用到日常生产流水线。P0a 未稳定前，后续模块可以开发和测试，但不得影响 P0a 的最终入库、审核闭环和真实账户只读边界。

## 三、结构化输出

系统采用 **JSON First，Markdown on Demand**。

每次研究必须生成结构化 JSON 快照，并通过 JSON Schema 校验。JSON 是入库、审计、复盘、曲线展示、Web 工作台、ChatGPT 审核和自动测试的唯一事实源。

AI 日常研究模块只允许直接输出 JSON，不直接输出 Markdown 报告。Markdown、HTML、PDF 等报告均为派生视图，由脚本基于 JSON 或 SQLite 模板按需生成，不作为主数据源。

推荐流程：

```text
AI 生成 JSON → JSON Schema 校验 → SQLite 入库 → Web 展示 → 按需渲染 Markdown / HTML / PDF
```

禁止流程：

```text
AI 写 Markdown → 从 Markdown 解析 JSON → 入库
```

### 通用字段

所有研究模块必须包含以下通用字段：

| 字段 | 说明 |
|---|---|
| basis_date | 数据基准日期 |
| generated_at | 生成时间 |
| module | 模块名称 |
| snapshot_id | 当前 JSON 快照唯一标识 |
| data_sources | 数据来源列表 |
| data_gaps | 数据缺口 |
| conflicts | 数据冲突 |
| executive_summary | 简短摘要，供人工、ChatGPT 和 Web 卡片使用 |
| key_facts | 支撑结论的关键事实 |
| reasoning | 从事实到结论的判断理由 |
| risk | 主要风险 |
| conclusion_strength | weak / medium / strong |
| actionability | observe / research_first / rebalance_candidate / no_action |
| confidence | 0.0 - 1.0 |
| invalidation_conditions | 失效条件 |
| next_review_date | 下次复查日期 |
| must_not_do | 明确禁止事项 |
| required_human_review | 是否必须人工复核 |
| status | 当前状态 |

### 各模块额外必填字段

| 模块 | 必填字段 |
|---|---|
| 市场仓位 | market_score、equity_min、equity_max、risk_level、reason、crowding_penalty、invalidation_conditions。 |
| 主线研究 | theme、strength_score、phase、leading_symbols、related_etfs、risk、invalidation_conditions。 |
| 龙头研究 | symbol、theme、leader_score、liquidity_status、valuation_status、risk、next_review_date。 |
| ETF 研究 | symbol、theme、role、tracking_target、valuation_status、liquidity_status、rating、data_gaps。 |
| 个股估值 | symbol、fair_value_low、fair_value_mid、fair_value_high、method、confidence、rating、next_review_date。 |
| 组合分析 | bucket_weights、target_ranges、deviation_pp、research_first_list、action_candidates。 |
| 影子账户 | trade_date、nav_index、holdings_weight、paper_trades、turnover、drawdown、benchmark_returns。 |
| 决策日志 | old_conclusion、new_conclusion、change_reason、evidence_added、is_material_change、requires_human_review。 |

### JSON 解释字段要求

JSON 不能只保存冷冰冰的数字，也必须保存可审计的文字解释。

每个研究 JSON 至少应包含：

```json
{
  "executive_summary": "简短摘要",
  "key_facts": ["事实1", "事实2"],
  "reasoning": ["判断理由1", "判断理由2"],
  "risks": ["风险1", "风险2"],
  "invalidation_conditions": ["失效条件1", "失效条件2"]
}
```

这样 ChatGPT 和人工可以直接审计 JSON 内部逻辑，不需要 AI 另写 Markdown。

## 四、报告渲染规则

Markdown、HTML、PDF 均为派生视图，不是事实源。

渲染规则：

1. AI 只生成 JSON，节省 token，避免双份文本结论冲突。
2. Web 工作台直接读取 SQLite 或 JSON 展示。
3. 需要 Markdown / HTML / PDF 时，用脚本模板渲染。
4. 渲染脚本不得新增事实、不得修改结论、不得改变结论强度和可行动性。
5. 渲染产物必须带有来源 JSON 的文件名、hash 或 `snapshot_id`。
6. 渲染失败不影响 JSON 入库，但不得发布对应人类阅读版报告。

示例命令：

```bash
python scripts/render_report.py \
  --input research/finalized/2026-06-15_market_position.json \
  --template templates/market_position.md.j2 \
  --output reports/2026-06-15_market_position.md
```

推荐模板字段：

```text
basis_date
module
status
executive_summary
key_facts
reasoning
risks
invalidation_conditions
conclusion_strength
actionability
required_human_review
source_snapshot_id
```

## 五、结论强度与可行动性

所有 AI 结论必须同时标注结论强度和可行动性。

### 结论强度

| 等级 | 含义 | 限制 |
|---|---|---|
| weak | 证据不足，只能作为观察 | 不得进入 action_candidates |
| medium | 证据基本充分，可进入候选 | 只能作为再平衡候选，不得写成交易指令 |
| strong | 证据较强，可影响目标组合建议 | 仍需 ChatGPT 审核和人工确认 |

### 可行动性

| actionability | 含义 |
|---|---|
| observe | 仅观察 |
| research_first | 先研究，不给操作建议 |
| rebalance_candidate | 可作为再平衡候选 |
| no_action | 明确不动作 |

任何模块不得输出“立即买入”“立即卖出”“下单”“委托”等真实交易指令。

## 六、标的池规则

1. 真实持仓从 QMT 只读导入后自动进入标的池。
2. 主线 ETF、主线龙头、防御 ETF、现金 ETF 和观察标的由 Codex 提议。
3. 新增池内标的必须有来源、分类、加入原因和复查日期。
4. 未完成研究的标的进入 ResearchFirst，不得直接给买卖建议。
5. ResearchFirst 标的不得进入影子账户。
6. ResearchFirst 标的不得进入 `action_candidates`。
7. ResearchFirst 只能输出“需要补哪些研究”。
8. 影子账户只能在标的池内选择持仓，不能买入池外标的。
9. 标的移出池子时保留历史原因、移出日期和操作人。

## 七、审核流程

### 状态流

| 状态 | 含义 | 是否可入库 | 是否可用于影子账户新策略 |
|---|---|---|---|
| draft | Codex 已生成 JSON 初稿 | 否 | 否 |
| json_validated | JSON 已通过 schema 校验 | 可入临时库 | 否 |
| review_package_created | 审核包已生成，可提交网页版 ChatGPT | 可入临时库 | 否 |
| chatgpt_reviewed | 网页版 ChatGPT 已复核 | 可入审核库 | 否 |
| human_approved | 人工已确认采用 | 是 | 是 |
| finalized | 最终 JSON 已生成并入库 | 是 | 是 |
| blocked | 数据、逻辑、安全或审核失败 | 否 | 否 |
| superseded | 被更新版本替代 | 保留历史 | 否 |

最终记录必须由 `human_approved` 版本生成。审核未完成、人工未确认或安全检查失败时，影子账户不得执行当日新策略。

### 审核包必须包含

- JSON 快照
- JSON Schema 校验结果
- 数据来源
- `data_gaps`
- `conflicts`
- `key_facts`
- `reasoning`
- `conclusion_strength`
- `actionability`
- ResearchFirst 清单
- `action_candidates`
- 安全扫描结果
- 待 ChatGPT 审核问题

Markdown 初稿不是审核包必需项。如需人工阅读版，应由 `render_report.py` 从 JSON 渲染，不允许 AI 另写一份独立 Markdown 结论。

## 八、影子账户规则

1. 只做纸面模拟，不发送真实订单。
2. 首版采用固定规则，不允许 AI 自由调仓。
3. 持仓来源只能是标的池。
4. ResearchFirst 标的权重必须为 0。
5. 默认按审核后且人工确认的目标仓位生成模拟交易。
6. 默认使用收盘价估算成交，后续可增加次日开盘价或滑点模型。
7. 记录手续费、滑点假设、换手率、回撤和基准收益。
8. 审核失败、人工未确认或数据阻断时，保持上一日持仓或进入现金规则。
9. 池外标的无法被影子账户买入，必须有自动测试覆盖。

默认规则：

```text
目标组合 = 宽基 40% + 进攻 40% + 防御 20%
单一 ETF 上限 = 15%
单一个股上限 = 5%
ResearchFirst = 0%
现金 ETF / 短融 ETF 下限 = 5%
权益总仓位必须落在 market_equity_min ~ market_equity_max 内
偏离超过 3 个百分点才模拟调仓
```

## 九、真实账户对比

1. QMT 只读导入真实持仓快照。
2. 本地可保存真实持仓明细，但不得提交 GitHub。
3. Web 和渲染报告默认只展示比例、收益率、净值指数、回撤、主题 / 行业暴露和偏离度。
4. 不展示总资产、持仓金额、股数、收益金额、真实订单、成交明细或账户号。
5. 对外展示统一使用指数化曲线，例如净值从 100 开始。

## 十、组合基准模板

系统默认使用以下组合政策作为基准，不得让 AI 每天重新发明组合框架。

```yaml
portfolio_policy:
  core:
    name: 宽基 / 核心底仓
    target: 40
    min: 30
    max: 50
  growth:
    name: 进攻 / 主线成长
    target: 40
    min: 25
    max: 50
  defensive:
    name: 防御 / 现金 / 红利 / 低波
    target: 20
    min: 10
    max: 35
```

组合分析只回答：

1. 当前比例偏离目标区间多少？
2. 市场仓位是否要求整体升档或降档？
3. 哪些标的需要 ResearchFirst？
4. 哪些只是 `rebalance_candidate`？
5. 哪些动作明确不建议做？

## 十一、失败处理

| 场景 | 处理 |
|---|---|
| Tushare 失败 | 标记数据缺失，尝试 BaoStock 交叉验证；关键字段缺失则阻断最终报告。 |
| BaoStock 也失败 | 标记数据源失败，进入 blocked。 |
| QMT 未登录 | 跳过真实持仓更新，保留上一快照并提示。 |
| ChatGPT 未审核 | 不生成最终记录，不执行影子账户新策略。 |
| 人工未确认 | 不生成最终记录，不执行影子账户新策略。 |
| JSON 校验失败 | 不入库，进入 blocked。 |
| 渲染报告失败 | 不影响 JSON 入库，但不得发布对应 Markdown / HTML / PDF。 |
| 安全检查失败 | 不发布、不入最终库，进入 blocked。 |
| 数据源冲突 | 记录冲突，超过阈值则阻断定稿。 |
| 结论漂移但无新证据 | 标记 requires_human_review，不得自动 finalized。 |
| 当日任务失败 | 记录失败原因，支持次日补跑。 |

### 数据源冲突阈值

| 冲突类型 | 处理 |
|---|---|
| 价格差异 < 0.3% | 记录，不阻断。 |
| 价格差异 0.3% - 1% | 标记 warning。 |
| 价格差异 > 1% | 阻断估值。 |
| 成交量差异 > 5% | 标记 warning。 |
| 复权因子不一致 | 阻断历史收益计算。 |
| 指数成分数据缺失 | 不阻断，但降低置信度。 |
| QMT 持仓缺失 | 不更新真实持仓，使用上一快照并提示。 |

## 十二、安全检查

安全检查必须是独立 gate，每次发布前执行。

禁止进入 GitHub、最终 JSON、渲染报告或对外页面的内容：

```text
.env
*.db
qmt_export/*
real_positions/*
account_id
total_asset
cash_balance
position_amount
share_count
order_id
trade_id
真实账户号
总资产
持仓金额
股数
真实订单
成交明细
```

允许展示：

```text
账户A：进攻桶 42%，防御桶 18%，现金 6%。
真实账户净值指数：从 100 到 103.5。
组合相对目标区间偏离：+4.2 个百分点。
```

禁止展示：

```text
持有 10600 股。
市值 573000 元。
浮亏 87000 元。
订单号 xxxxxx。
账户总资产 xxxxxx 元。
```

安全检查失败时必须进入 `blocked`。

## 十三、结论漂移检测

系统必须记录结论变化。

建议表：`decision_change_log`。

字段：

```text
module
subject
old_conclusion
new_conclusion
change_reason
changed_by
evidence_added
market_data_changed
is_material_change
requires_human_review
created_at
```

触发规则：

1. 结论强度从 weak 变 strong，必须 `requires_human_review`。
2. `actionability` 从 observe / research_first 变 rebalance_candidate，必须 `requires_human_review`。
3. 市场仓位区间上下限变化超过 10 个百分点，必须 `requires_human_review`。
4. 主题 phase 发生变化，必须记录新证据。
5. 没有新增证据却发生重大结论变化，必须 blocked 或 human_review。

提示文案：

```text
结论发生重大漂移，但缺少新增证据。
```

## 十四、数据保留

| 类型 | 策略 |
|---|---|
| 最终 JSON 快照、渲染报告、决策日志、影子账户历史 | 永久保留。 |
| 审核包、运行日志、按需渲染的临时报告 | 保留最近一段周期，可归档。 |
| 临时文件、缓存、下载中间文件 | 可清理。 |
| .env、本地数据库、真实账户明细、QMT 运行文件 | 不提交 GitHub。 |

## 十五、人工边界

1. Codex 自动跑 JSON 初稿、数据校验、审核包和影子账户纸面模拟。
2. 网页版 ChatGPT 负责二次复核和最终报告审核。
3. 人工确认后才能 finalized。
4. 真实账户永远不自动交易。
5. 人工可以修改标的池、审核结论和风险边界。
6. 所有人工修改必须保留记录。
7. 任何真实交易必须由人工在券商客户端独立完成。

## 十六、Web 工作台验收范围

首版 Web 只读展示，不提供真实交易入口。

页面要求：

| 页面 | 内容 |
|---|---|
| 今日状态页 | 数据是否成功、QMT 是否导入、今日报告状态、是否 blocked。 |
| 仓位页 | 建议权益仓位区间、实际权益仓位、偏离百分点。 |
| 标的池页 | 已研究、ResearchFirst、blocked、next_review_date。 |
| 影子账户页 | 净值曲线、回撤、换手率、与指数对比。 |
| 审核包页 | 今日待审、数据缺口、逻辑冲突、风险遗漏。 |

## 十七、验收标准

### P0a 验收

1. 连续 5 个交易日生成市场仓位 JSON 快照，并能画出仓位区间曲线。
2. 每个研究模块至少有一份可校验 JSON；Markdown / HTML / PDF 可由脚本按需渲染。
3. JSON schema 校验失败时不能入库。
4. 安全检查失败时不能发布最终 JSON 或渲染报告。
5. QMT 真实持仓导入后，持仓标的自动进入标的池。
6. 审核包能列出 `data_gaps`、`conflicts`、`actionability`、`key_facts`、`reasoning` 和待审核问题。
7. ChatGPT 未审核或人工未确认时，不发布最终记录。
8. `render_report.py` 能从 finalized JSON 渲染 Markdown，且不修改结论字段。

### P0b 验收

1. 影子账户能生成纸面模拟交易、持仓、净值和回撤。
2. 池外标的无法被影子账户买入。
3. ResearchFirst 标的权重必须为 0。
4. 真实持仓、影子账户和主要指数能生成同口径对比曲线。
5. 审核未完成、人工未确认或安全检查失败时，不执行影子账户新策略。

### P0c 验收

1. 主线研究能输出 `strength_score`、`phase`、`leading_symbols`、`related_etfs` 和失效条件。
2. ETF / 个股估值能输出合理区间、方法、置信度和 `next_review_date`。
3. 结论漂移检测能识别重大变化并要求人工复核。
4. AI 不能把 weak 结论写成可操作建议。

## 十八、推荐开发顺序

1. SQLite schema。
2. JSON schema + 校验器。
3. 安全扫描器。
4. 标的池表。
5. QMT 只读导入 mock。
6. JSON 入库器。
7. 报告渲染脚本 `render_report.py`。
8. 市场仓位快照模块。
9. 审核包生成器。
10. 跑 5 个交易日样例。
11. 影子账户。
12. Web 只读展示。
13. 主线识别、龙头排序、复杂估值。

先把“不会错得离谱、不会泄密、不会自动交易”做扎实，再追求“聪明”。
