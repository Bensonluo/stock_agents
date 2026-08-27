# V2 升级进度记录

> 对应计划:`stock-analysis-v2-upgrade-plan.md`。本文件记录每个 Phase 的实际完成情况,先于代码合入更新。

## Phase 0:恢复可信基线 — ✅ 完成(2026-08-27)

| 计划项 | 状态 | 说明 |
|---|---|---|
| 修复 Poetry Python 环境 | ✅ | Poetry CLI 自身 venv 指向已删除的 Python 3.12 框架导致 `poetry` 完全不可用;用 `uv tool install poetry --force` 重装(2.4.1),并 `poetry config virtualenvs.in-project true --local`(生成 `poetry.toml`)使 Poetry 直接使用项目内已有的 `.venv`(Python 3.12.13,依赖完整) |
| 测试可运行(CI 基线) | ✅ | `poetry run pytest tests/ -q` → **133 passed, 5 deselected**(5 个 network 标记按配置跳过) |
| 回测参数错传 | ✅(前序会话) | `BacktestRequest` 改为按 strategy 的判别联合校验(`model_validator`),MACD 参数补齐;`tests/unit/api/test_backtest.py`、`tests/unit/services/test_backtest_service.py`、`tests/integration/test_backtest_api.py` 覆盖 |
| 财务百分数单位 | ✅(前序会话) | `data_agent` 将 yfinance `debtToEquity` /100 归一为小数,输出 `metric_units` 元数据;`fundamental.py` 阈值统一为小数口径;契约测试 `tests/unit/tools/test_data_fundamental_correctness.py` |
| SMA200 数据不足 | ✅(前序会话) | `fetcher.py`/`data_agent.py` 默认窗口 90 天 → 3 年(`DEFAULT_HISTORY_DAYS = 3*365`,`DEFAULT_HISTORY_PERIOD = "3y"`),所有数据源(含 stooq 备源)同步 |
| Beta/增长占位结果 | ✅(前序会话) | Beta 由对齐的真实 benchmark 收益计算(`_calculate_beta_from_histories`),缺失时 `beta_status=insufficient_data` 且不给仓位;增长分析缺失时返回 `insufficient_data`,总分按可用权重重归一化 |
| ReportV2/MetricEvidence/DataQuality schema | ✅(本次) | 新增 `app/domain/schemas/`:`metric_evidence.py`(canonical metric_id `symbol.domain.name.YYYY-MM-DD`,quality-value 一致性校验)、`data_quality.py`(覆盖率+问题清单 → pass/degraded/insufficient 硬门控 verdict)、`report_v2.py`(版本化报告对象,`from_legacy_report` 桥接现有 dict 报告) |
| 特征化测试 | ✅(前序会话+本次) | `tests/unit/domain/test_schemas.py`(25 例)及 risk/backtest/fundamental 各套契约测试 |

**验收达成**:测试全绿;占位值均以 `insufficient_data`/`status` 显式暴露而非中性分;未做任何破坏性重置,原有未提交修改全部保留。

## Phase 1:专业确定性分析 — 🚧 进行中

| 计划项 | 状态 | 说明 |
|---|---|---|
| 唯一 TechnicalEngine(种子) | ✅ 2026-08-27 | 新增 `app/analysis/technical/engine.py`:`resample_weekly`(日→周 W-FRI 重采样)、`weekly_sma_pack`(五组周 SMA 5/10/20/40/60,每条线含现值/距离%/4周与12周斜率/连续位于上方或下方周数/warm-up;相邻均线交叉含方向、交叉以来收益、成交量确认;多头/空头/缠绕排列及持续周数)。所有数值输出附带 `MetricEvidence`,warm-up 不足显式 `insufficient_data`,无 NaN 外泄。测试 `tests/unit/analysis/test_weekly_sma.py`(15 例,含确定性/可复现性) |
| 引擎接入 pipeline 与 ReAct | ✅ 2026-08-27 | `weekly_sma_summary` 提供 JSON 安全输出(`include_evidence=False` 供 ReAct 省 token);pipeline 的 `TechnicalAnalysisAgent` 每标的附带 `weekly_sma` 证据包,引擎异常降级不影响整体分析;两个报告层(agent + tool)经 `compact_weekly_view` 输出 `weekly_trend` 摘要(排列状态/持续周数/各线距离%/近期交叉),缺失时 `unavailable` 而非 0。集成测试 11 例 |
| 日线指标唯一引擎 | ✅ 2026-08-27 | `app/analysis/technical/daily.py` 承载规范超集(SMA20/50/200 带暖机守卫、EMA、RSI、MACD、Bollinger+宽度、ATR%、量比信号、s1-s3/r1-r3、量价确认情绪);`analysis_agent` 与 `tools/analysis/technical.py` 均改为委托(保留旧私有名别名),重复实现已删除 |
| 风险引擎升级 | ✅ 2026-08-27 | `app/analysis/risk/engine.py`:CVaR95、Sortino、beta/年化 alpha/R²/相关性(对齐收益)、波动率自身历史分位、beta 标定市场冲击压力情景(-5%/-10%/-20%)、组合相关矩阵、HHI 集中度;`assess_risk` 工具输出全部新指标,证据化 |
| 三情景估值引擎 | ✅ 2026-08-27 | `app/analysis/valuation/engine.py`:Bear/Base/Bull 区间(自身估值倍数锚定,非行业万能阈值)、盈利法(远期 EPS×倍数带)+ 销售法(亏损成长模板)、3×3 敏感性表、假设全部显式;亏损股自动路由销售法 |
| 财务质量引擎 | ✅ 2026-08-27 | `app/analysis/fundamental/engine.py`:营收趋势/CAGR/同比、毛利率变化、CFO/净利、FCF;红旗检查(利润无现金流=critical、负权益=critical、营收下滑/毛利率侵蚀=warning);缺失显式 insufficient_data |
| 接入两条路径 | ✅ 2026-08-27 | pipeline:`FundamentalAnalysisAgent` 每标的附 `quality`+`valuation_scenarios`;ReAct:`analyze_fundamental` 附质量摘要、新增 `analyze_valuation` 工具(已注册、结果路由 valuation_analysis);报告层(agent+tool)基本面段输出 `valuation_scenarios`/`quality` 摘要 |
| `as_of` 贯穿 | 🚧 | data_agent market_data 已盖 as_of(最后交易日);引擎输出均带 as_of;回测与 provider 级 vintage 未接(Phase 3) |

## Phase 2:Agent 与报告升级 — 🚧 进行中

| 计划项 | 状态 | 说明 |
|---|---|---|
| ReportService 合并 | ✅ 2026-08-27 | `app/services/report_service.py` 承载唯一分节构建;先归一化 pipeline-state 与 ReAct 两种输入形状,再输出最丰富并集(技术含 weekly_trend、基本面含 valuation_scenarios/quality、风险含 beta/压力、推荐 decisions 或推导、i18n 执行摘要)。`report_agent` 与 `tools/report/generate.py` 均为薄委托;agent 保留 LLM 叙述钩子 |
| Bull/Bear 辩论 | ✅ 2026-08-27 | `app/research/debate.py`:确定性抽取双侧论据,每条带 evidence_ref 指向来源块;thesis/最强反方/失效条件(红旗 critical 优先) |
| Evidence Auditor | ✅ 2026-08-27 | `app/research/auditor.py`:行情 as_of 超 7 天=blocked;基本面红旗与多头动能/情绪共存的 critical 冲突=blocked;缺失数据=warnings。审计员不参与方向投票 |
| Risk Committee | ✅ 2026-08-27 | `app/research/committee.py`:approve/limit/veto/watch;critical 红旗或审计 blocked → veto;very_high → veto;high 或 beta 隐含 -30% 冲击 → 限仓 5%+强制止损;数据不足 → watch;"低风险不构成买入理由"显式写入审批条件 |
| 综合接入 | ✅ 2026-08-27 | `ResearchSynthesisAgent` 为流水线新节点(risk → synthesis → decision,state 键 `research_synthesis`);ReAct 在报告组装前对工具结果综合;ReportService 存在 synthesis 时输出该段 |
| 证据约束 prompt 与结构化输出 | ⬜ | LLM 角色(Technical/Fundamental/Valuation/Event Analyst、PM)待接;当前综合为确定性规则 |
| 前端五周线/估值情景/财务趋势/催化剂/证据抽屉/多标的 | ⬜ | ReportV2 字段已在(weekly_trend、valuation_scenarios、quality、research_synthesis),前端消费待做 |

## Phase 3-4 — 未开始

见计划 §9(成本化回测、walk-forward、实验 manifest;文档 RAG、预期数据、Qlib/LEAN 级研究)。

## 环境备忘

- Poetry 2.4.1 经 `uv tool` 安装(`~/.local/bin/poetry`);项目本地 `poetry.toml` 固定 `virtualenvs.in-project=true`。
- 全量验证命令:`poetry run pytest tests/ -q`(当前 144 passed / 5 network 跳过)。
- 存量 lint 债务:`poetry run ruff check app/` 约 480+ 告警,属既有代码(主要 Dict→dict、Optional→`|` 迁移未完成),新代码已按新风格并通过。
