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

## Phase 2:Agent 与报告升级 — ✅ 核心完成(2026-08-27;催化剂时间线随 Phase 4 事件数据补)

| 计划项 | 状态 | 说明 |
|---|---|---|
| ReportService 合并 | ✅ 2026-08-27 | `app/services/report_service.py` 承载唯一分节构建;先归一化 pipeline-state 与 ReAct 两种输入形状,再输出最丰富并集(技术含 weekly_trend、基本面含 valuation_scenarios/quality、风险含 beta/压力、推荐 decisions 或推导、i18n 执行摘要)。`report_agent` 与 `tools/report/generate.py` 均为薄委托;agent 保留 LLM 叙述钩子 |
| Bull/Bear 辩论 | ✅ 2026-08-27 | `app/research/debate.py`:确定性抽取双侧论据,每条带 evidence_ref 指向来源块;thesis/最强反方/失效条件(红旗 critical 优先) |
| Evidence Auditor | ✅ 2026-08-27 | `app/research/auditor.py`:行情 as_of 超 7 天=blocked;基本面红旗与多头动能/情绪共存的 critical 冲突=blocked;缺失数据=warnings。审计员不参与方向投票 |
| Risk Committee | ✅ 2026-08-27 | `app/research/committee.py`:approve/limit/veto/watch;critical 红旗或审计 blocked → veto;very_high → veto;high 或 beta 隐含 -30% 冲击 → 限仓 5%+强制止损;数据不足 → watch;"低风险不构成买入理由"显式写入审批条件 |
| 综合接入 | ✅ 2026-08-27 | `ResearchSynthesisAgent` 为流水线新节点(risk → synthesis → decision,state 键 `research_synthesis`);ReAct 在报告组装前对工具结果综合;ReportService 存在 synthesis 时输出该段 |
| 证据约束 prompt 与结构化输出 | ✅ 2026-08-27 | `app/research/narrator.py`(叙述)+ `app/research/analysts.py`(四专业 Analyst + PM):引用必须在允许集合内否则该角色输出被丢弃;PM 必须原样复述委员会裁决否则结论被丢弃(不得越过门控);超时/异常/不可解析静默降级。结构化校验由代码而非 prompt 保证 |
| 前端消费 V2 字段 | ✅ 2026-08-27 | result 页已渲染:周线排列+金叉/死叉、估值情景区间+质量红旗、研究综合卡(审计/多空/叙述/委员会)、PM 结论(论点/期限/条件/失效/复述裁决)、四 Analyst 视图(带引用)、多标的切换页签、证据抽屉(指标/数值/单位/as_of/来源/公式,按标的折叠)。催化剂时间线依赖 Phase 4 事件数据,随 Phase 4 做 |

## Phase 3:回测与研究闭环 — ✅ 核心完成(2026-08-28;逐笔 filing date 随 Phase 4 数据源精化)

| 计划项 | 状态 | 说明 |
|---|---|---|
| 成本化确定性引擎 | ✅ 2026-08-27 | `app/backtest/`:CostModel(佣金/最低费用/卖方印花税/过户费/双向滑点,中美预设);引擎强制 t 收盘出信号、t+1 开盘成交,warm-up NaN=不持仓,期末强制平仓补全回合统计 |
| 完整指标 | ✅ 2026-08-27 | CAGR/Sharpe/Sortino/Calmar/最大回撤/CVaR95/波动率/基准超额/胜率/盈亏比/换手/成本占比;不可计算的返回 None 不造假 |
| walk-forward 与参数邻域 | ✅ 2026-08-27 | 滚动 train/test:参数仅在 train 段选出、test 段评分;报告全部窗口(含亏损)、参数稳定性、configs_tested |
| 实验 manifest | ✅ 2026-08-27 | 价格帧 sha256、参数、成本模型、git commit、configs_tested、时间戳 |
| API | ✅ 2026-08-27 | `POST /api/backtest/v2/run`、`/v2/walkforward`(旧 /run 契约不变);service 层 run_backtest_v2/run_walk_forward |
| as_of/vintage 数据防泄漏 | ✅ 2026-08-28 | `app/backtest/point_in_time.py`:财报仅在 period end + 报告滞后(默认 60 天)后可见,`latest_visible_value` 只返回已披露期间;data_agent 为每个财报块盖 `visible_from` 戳。逐笔 filing date(SEC EDGAR/巨潮)随 Phase 4 数据源接入精化 |
| 历史校准与失败结果展示 | ✅ 2026-08-28 | `app/backtest/calibration.py`:入场信号按前瞻窗口(默认 20/60 bar)的实测命中率——样本数、Wilson 95% 下界、平均前瞻收益、分年明细(亏损年可见);`POST /api/backtest/v2/calibrate`。置信度自此以实测频率为锚。引擎数据卫生:乱序/重复索引确定性归一 |
| 引擎数据卫生 | ✅ 2026-08-28 | run_backtest 对非递增索引排序、重复时间戳 keep-last 去重——索引乱序本身就是 look-ahead 缺陷 |

## 重复实现统一(2026-08-28,计划 §5.1"共享领域服务"收口)

| 项 | 状态 | 说明 |
|---|---|---|
| 风险数学 | ✅ | `risk_agent` 只留编排+组合层;个股指标走 `assess_symbol`(引擎路径),流水线同步获得 CVaR/Sortino/alpha/R²/压力情景。共享评分升级为带 None 校验的超集;废弃 agent 独有的 `beta<=0.5→+5` 分支(与"分高=险高"语义相悖) |
| 旧 Backtrader 路径 | ✅ | `/run` 委托 V2 引擎并映射旧响应字段;四个 Backtrader 策略类删除(-203 行)。依赖暂留 pyproject,随下次 lock 刷新移除 |
| 基本面评分 | ✅ | `app/analysis/fundamental/scoring.py` 为规范实现;工具=LangChain 包装+别名;`FundamentalAnalysisAgent` 委托 |
| 情绪评分 | ✅ | `app/analysis/sentiment.py` 为规范实现;工具与 agent 均委托(agent 保留 LLM 增强——那是特性不是重复) |
| 执行摘要第三份 | ✅ | `routes/agent.py` 改调 `ReportService.detect_lang/executive_summary` |
| 决策权重 | ✅ | `DecisionMakingAgent` 以 `ReportService.derive_recommendation`(45/30/15/10+固定动作带)为唯一公式;私有权重与 4 个超集辅助函数删除。两条路径同一数据同一建议 |
| 数据供应商链 | 🚧 第一步 | 常量单一来源;流水线 yfinance 失败时回退共享 5 级供应商链(+3 测试)。财报/新闻深度合并留待后续 |

净删约 700 行重复代码;全程 251→258 测试绿。

2026-08-28 全面质量检查:全量 258 通过;新代码与被深改文件 ruff 零告警;双路径一致性固化为永久测试(4 项逐一相等);全链路合成数据冒烟通过(报告 JSON 安全,29 条证据记录);覆盖:backtest/research/domain 90%,fundamental 98%,valuation 99%,周线 86%,日线 80%,风险 77%。审计修复 5 处(死代码×2、类型谎言、重复常量、冗余导入)。已知限制:pytest-cov 插件与 stub-module 测试模式同进程冲突(用 coverage run 直跑替代)。

2026-08-28 功能测试补齐:V2 回测 API(TestClient+真引擎)与七-agent 流水线全链贯通测试落地;抓出并修复 3 个真 bug(report_agent 的 await/方法名两处——合并后流水线报告路径实际已断、^GSPC 基准被股票校验误拦);pipeline 结果视图补齐 V2 渲染(周线/估值情景/红旗/委员会卡)与 confidence 0-1 适配。回测 UI 调旧 /run,已由 V2 引擎支撑,无需改动。当前 278 测试。

2026-08-28 线上反馈修复:用户在服务器跑 AAPL 得到"空壳报告"(全 _error 段+假持有建议+审计 pass)。两轮修复:①执行摘要对"无价格且无可用技术块"显式告警(⚠ 行情数据不可用),不再输出中性回退建议;②审计对象改为运行符号全集(全源失败时 ReAct 不写 market_data,旧逻辑空循环→漏检),_error/缺失块=数据不足。线上复现验证通过。另:服务器磁盘 100% 曾致构建假挂(no space on device),已清理 docker 构建缓存 12.7GB。

## Phase 4 — 未开始

见计划 §9(文档 RAG、预期数据、期权隐含、Qlib/LEAN 级研究、沙盒内自动因子)。

## 环境备忘

- Poetry 2.4.1 经 `uv tool` 安装(`~/.local/bin/poetry`);项目本地 `poetry.toml` 固定 `virtualenvs.in-project=true`。
- 全量验证命令:`poetry run pytest tests/ -q`(当前 144 passed / 5 network 跳过)。
- 存量 lint 债务:`poetry run ruff check app/` 约 480+ 告警,属既有代码(主要 Dict→dict、Optional→`|` 迁移未完成),新代码已按新风格并通过。
