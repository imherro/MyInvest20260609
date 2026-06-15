# 需求规格

## 优先级

| 优先级 | 范围 |
|---|---|
| P0 | SQLite、标的池、QMT 持仓只读导入、盘后估值、ChatGPT 审核包、影子账户。 |
| P1 | Web 历史曲线、真实持仓/影子账户/指数对比、异常提醒。 |
| P2 | 主线识别、龙头排序、自动复盘评分、更多宏观和海外联动。 |

## 结构化输出

每次研究必须同时生成 Markdown 报告和 JSON 快照。JSON 是入库和画图依据。

| 模块 | 必填字段 |
|---|---|
| 市场仓位 | basis_date、generated_at、market_score、equity_min、equity_max、risk_level、reason、invalidation_conditions。 |
| 主线研究 | theme、strength_score、phase、leading_symbols、related_etfs、risk、invalidation_conditions。 |
| 龙头研究 | symbol、theme、leader_score、liquidity_status、valuation_status、risk、next_review_date。 |
| ETF 研究 | symbol、theme、role、tracking_target、valuation_status、liquidity_status、rating、data_gaps。 |
| 个股估值 | symbol、fair_value_low、fair_value_mid、fair_value_high、method、confidence、rating、next_review_date。 |
| 组合分析 | basis_date、bucket_weights、target_ranges、deviation_pp、research_first_list、action_candidates。 |
| 影子账户 | trade_date、nav_index、holdings_weight、paper_trades、turnover、drawdown、benchmark_returns。 |

## 标的池规则

1. 真实持仓从 QMT 只读导入后自动进入标的池。
2. 主线 ETF、主线龙头、防御 ETF、现金 ETF 和观察标的由 Codex 提议。
3. 新增池内标的必须有来源、分类、加入原因和复查日期。
4. 未完成研究的标的进入 ResearchFirst，不得直接给买卖建议。
5. 影子账户只能在标的池内选择持仓，不能买入池外标的。
6. 标的移出池子时保留历史原因和移出日期。

## 审核流程

| 状态 | 含义 |
|---|---|
| draft | Codex 已生成初稿和 JSON。 |
| review_package_created | 审核包已生成，可提交网页版 ChatGPT。 |
| chatgpt_reviewed | 网页版 ChatGPT 已复核。 |
| finalized | 最终报告已生成并入库。 |
| blocked | 数据、逻辑或安全检查失败。 |
| superseded | 被更新版本替代。 |

最终报告必须由审核通过的版本生成。审核未完成时，影子账户不得执行当日新策略。

## 影子账户规则

1. 只做纸面模拟，不发送真实订单。
2. 持仓来源只能是标的池。
3. 默认按审核后的目标仓位生成模拟交易。
4. 默认使用收盘价估算成交，后续可增加次日开盘价或滑点模型。
5. 记录手续费、滑点假设、换手率、回撤和基准收益。
6. 审核失败或数据阻断时，保持上一日持仓或进入空仓/现金规则。

## 真实账户对比

1. QMT 只读导入真实持仓快照。
2. 本地可保存真实持仓明细，但不得提交 GitHub。
3. Web 和报告默认只展示比例、收益率、净值指数、回撤、主题/行业暴露和偏离度。
4. 不展示总资产、持仓金额、股数、收益金额、真实订单或成交明细。

## 失败处理

| 场景 | 处理 |
|---|---|
| Tushare 失败 | 标记数据缺失，尝试 BaoStock 交叉验证，阻断最终报告。 |
| QMT 未登录 | 跳过真实持仓更新，保留上一快照并提示。 |
| ChatGPT 未审核 | 不生成最终报告，不执行影子账户新策略。 |
| JSON 校验失败 | 不入库，进入 blocked。 |
| 数据源冲突 | 记录冲突，超过阈值则阻断定稿。 |
| 当日任务失败 | 记录失败原因，支持次日补跑。 |

## 验收标准

1. 连续 5 个交易日生成市场仓位快照，并能画出仓位区间曲线。
2. QMT 真实持仓导入后，持仓标的自动进入标的池。
3. 池外标的无法被影子账户买入。
4. 每个研究模块至少有一份 Markdown 和一份可校验 JSON。
5. 影子账户能生成模拟交易、持仓、净值和回撤。
6. 真实持仓、影子账户和主要指数能生成同口径对比曲线。
7. 审核未完成或安全检查失败时，不发布最终报告。

## 数据保留

| 类型 | 策略 |
|---|---|
| 最终报告、JSON 快照、决策日志、影子账户历史 | 永久保留。 |
| 初稿、审核包、运行日志 | 保留最近一段周期，可归档。 |
| 临时文件、缓存、下载中间文件 | 可清理。 |
| .env、本地数据库、真实账户明细、QMT 运行文件 | 不提交 GitHub。 |

## 人工边界

1. Codex 自动跑初稿、数据校验、审核包和影子账户模拟。
2. 网页版 ChatGPT 负责二次复核和最终报告审核。
3. 真实账户永远不自动交易。
4. 人工可以修改标的池、审核结论和风险边界。
5. 所有人工修改必须保留记录。
