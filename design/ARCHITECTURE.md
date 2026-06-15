# 架构设计：本地投资研究与风控系统

## 1. 架构目标

本系统的目标不是自动交易，而是建设一个**本地、可审计、可复盘、可扩展**的投资研究与风控流水线。

核心原则：

1. **JSON First，Markdown on Demand**：AI 日常只生成结构化 JSON；Markdown、HTML、PDF 都由脚本按需渲染。
2. **真实账户只读**：QMT 只能导入真实持仓快照，不允许任何真实下单接口。
3. **研究与执行隔离**：系统只输出研究、风险、仓位区间、比例偏离和影子账户模拟。
4. **审核与人工确认**：Codex 只能生成草稿和审核包；ChatGPT 复核；人工确认后才能 finalized。
5. **连续开发、分层启用**：功能可以一个接一个连续开发，但通过 feature flag、schema、测试、安全扫描和审核门禁分层启用。

## 2. 总体分层

```text
数据源层
  ├─ Tushare
  ├─ BaoStock
  ├─ QMT 只读持仓
  ├─ yfinance / FRED
  └─ 网络补充证据
        ↓
数据处理层
  ├─ 采集器 collectors
  ├─ 清洗器 normalizers
  ├─ 数据质量检查 data_quality
  └─ 数据冲突检测 conflict_detector
        ↓
事实包层
  ├─ facts.json
  ├─ market_facts.json
  ├─ portfolio_facts.json
  └─ target_pool_facts.json
        ↓
AI 研究层
  ├─ market_position.snapshot.json
  ├─ theme_research.snapshot.json
  ├─ etf_research.snapshot.json
  ├─ stock_valuation.snapshot.json
  ├─ portfolio.snapshot.json
  └─ shadow_account.snapshot.json
        ↓
校验与安全层
  ├─ JSON Schema 校验
  ├─ ResearchFirst 规则检查
  ├─ 真实账户泄露扫描
  ├─ 影子账户池内约束检查
  └─ 状态流检查
        ↓
审核层
  ├─ review_package.json
  ├─ ChatGPT 二审结果
  ├─ human_approval.json
  └─ finalized JSON
        ↓
存储与展示层
  ├─ SQLite 历史库
  ├─ Web 工作台
  ├─ Markdown / HTML / PDF 渲染
  └─ 曲线与复盘报表
```

## 3. 核心数据流

### 3.1 每日研究主流程

```text
collect_daily_data
→ validate_data
→ generate_fact_pack
→ run_ai_research_json
→ validate_json_schema
→ run_policy_guards
→ run_security_scan
→ create_review_package
→ ChatGPT review
→ human approve
→ finalize_snapshot
→ update_sqlite
→ update_shadow_account_if_allowed
→ render_report_on_demand
→ update_dashboard
```

### 3.2 状态流

```text
draft
→ json_validated
→ review_package_created
→ chatgpt_reviewed
→ human_approved
→ finalized
```

异常状态：

```text
blocked
superseded
```

任何 `blocked` 状态都不得进入 finalized，也不得触发影子账户新策略。

## 4. 模块设计

### 4.1 数据采集模块

职责：

- 拉取行情、指数、ETF、行业、主题、宏观和真实持仓快照。
- 记录数据来源、数据日期、采集时间、版本和异常。
- 不做投资解释。

建议目录：

```text
src/invest_system/collectors/
  tushare_collector.py
  baostock_collector.py
  qmt_position_importer.py
  yfinance_collector.py
  fred_collector.py
```

输出：

```text
data/raw/{date}/
data/processed/{date}/
```

### 4.2 数据质量模块

职责：

- 检查缺失、过期、异常值、来源冲突。
- 生成 `data_quality.json`。
- 超过阈值时将相关模块置为 `blocked`。

关键检查：

```text
价格差异
成交量差异
复权因子差异
交易日缺失
QMT 未登录
字段缺失
数据日期不一致
```

### 4.3 事实包模块

职责：

- 把原始数据整理成 AI 可读、可审计的 `facts.json`。
- 事实包只放事实，不放建议。
- 所有研究 JSON 必须引用事实包的 `fact_pack_id` 或 hash。

示例：

```json
{
  "basis_date": "2026-06-15",
  "fact_pack_id": "20260615_market_v1",
  "market_breadth": {},
  "index_returns": {},
  "theme_etfs": [],
  "data_gaps": [],
  "conflicts": []
}
```

### 4.4 AI 研究 JSON 模块

职责：

- AI 只输出 JSON。
- JSON 必须包含事实、摘要、理由、风险、失效条件、结论强度和可行动性。
- 不直接输出 Markdown。

所有研究 JSON 必须符合 schema。

### 4.5 策略规则与风控守卫

职责：

- 检查 ResearchFirst 是否越权。
- 检查 actionability 与 conclusion_strength 是否冲突。
- 检查影子账户是否买入池外标的。
- 检查真实账户信息是否泄露。
- 检查 finalized 是否缺少 ChatGPT 审核和人工确认。

示例规则：

```text
ResearchFirst 权重必须为 0
ResearchFirst 不得进入 action_candidates
weak 结论不得进入 rebalance_candidate
未 human_approved 不得 finalized
安全扫描失败不得发布报告
```

### 4.6 审核包模块

职责：

- 打包 JSON 快照、schema 校验结果、数据质量结果、安全扫描结果和待审问题。
- 不强制包含 Markdown。
- 给 ChatGPT 二审使用。

建议输出：

```text
review_packages/{date}/review_package.json
review_packages/{date}/snapshots/*.json
review_packages/{date}/checks/*.json
```

### 4.7 影子账户模块

职责：

- 只做纸面模拟。
- 首版使用固定规则，不允许 AI 自由调仓。
- 只使用标的池中已完成研究且非 ResearchFirst 的标的。
- 记录净值、回撤、换手率、基准收益和纸面交易。

默认组合：

```text
宽基 40%
进攻 40%
防御 20%
现金 ETF / 短融 ETF 下限 5%
单一 ETF 上限 15%
单一个股上限 5%
偏离超过 3 个百分点才模拟调仓
```

### 4.8 报告渲染模块

职责：

- 从 JSON 或 SQLite 渲染 Markdown / HTML / PDF。
- 不新增事实，不改结论。
- 报告必须记录来源 `snapshot_id` 或 hash。

建议目录：

```text
templates/
  market_position.md.j2
  portfolio.md.j2
  shadow_account.md.j2
scripts/render_report.py
```

### 4.9 Web 工作台

职责：

- 只读展示。
- 默认不展示总资产、持仓金额、股数、订单号、账户号。
- 不提供真实交易入口。

首版页面：

```text
今日状态页
市场仓位页
标的池页
组合偏离页
影子账户页
审核包页
```

## 5. 推荐目录结构

```text
investment-system/
  config/
    portfolio_policy.yaml
    risk_limits.yaml
    feature_flags.yaml
  data/
    raw/
    processed/
    qmt_snapshots/          # 不提交 GitHub
  db/
    local.sqlite            # 不提交 GitHub
  research/
    drafts/
    finalized/
    review_packages/
  schemas/
    common.schema.json
    market_position.schema.json
    portfolio.schema.json
    target_pool.schema.json
    shadow_account.schema.json
  scripts/
    collect_daily_data.py
    validate_data.py
    generate_fact_pack.py
    validate_snapshot.py
    create_review_package.py
    security_scan.py
    render_report.py
    finalize_snapshot.py
    update_shadow_account.py
  src/
    invest_system/
      collectors/
      validators/
      schemas/
      repositories/
      research/
      review/
      shadow/
      web/
  templates/
  tests/
    fixtures/
    golden/
    unit/
    integration/
  logs/
  README.md
  FEATURES.md
  REQUIREMENTS.md
  ARCHITECTURE.md
  DEVELOPMENT_PLAN.md
  CODEX_TASKS.md
```

## 6. Feature Flag 设计

连续开发时，后续模块可以先实现，但默认不开启到生产流水线。

```yaml
features:
  p0a_core_pipeline: true
  p0b_shadow_account: false
  p0c_theme_research: false
  p0c_valuation: false
  p1_web_dashboard: false
  p1_alerts: false
```

规则：

1. 开发可以连续推进。
2. 没有通过测试和门禁的功能必须保持 disabled。
3. disabled 功能不得影响核心 finalized 流程。
4. 每个 feature flag 都必须有测试覆盖。

## 7. 数据安全边界

不得提交 GitHub：

```text
.env
*.db
data/qmt_snapshots/
真实持仓明细
真实账户导出文件
API key
账户号
总资产
持仓金额
股数
真实订单号
成交编号
```

报告、Web 和审核包默认只展示：

```text
比例
百分点
净值指数
回撤
主题/行业暴露
偏离度
ResearchFirst 清单
风险提示
```

## 8. 测试策略

每个模块至少需要：

1. 单元测试。
2. JSON schema 校验测试。
3. 安全扫描测试。
4. fixture 输入输出测试。
5. golden 文件回归测试。
6. 禁止越权测试。

关键测试：

```text
ResearchFirst 不得进入 action_candidates
池外标的不得进入影子账户
安全扫描发现股数/金额时必须失败
JSON 校验失败不得入库
未 human_approved 不得 finalized
render_report 不得修改结论
```

## 9. Codex 开发原则

Codex 每次任务必须遵守：

1. 只做当前任务，不自行扩范围。
2. 先读 FEATURES.md、REQUIREMENTS.md、ARCHITECTURE.md。
3. 先更新或新增测试，再实现功能。
4. 每个任务完成后跑测试。
5. 不修改真实账户边界。
6. 不引入真实交易能力。
7. 不把 Markdown 作为事实源。
8. 不把 disabled 功能接入生产流水线。
9. 需要新增 schema 时，必须同时新增 fixture 和测试。
10. 任务完成后输出变更摘要、测试结果、风险和下一步建议。
