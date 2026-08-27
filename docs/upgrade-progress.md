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
| 引擎接入 pipeline 与 ReAct | ⬜ | 下一步:analysis_agent / auto_tools 改调 `weekly_sma_pack`,删除重复公式;与 SMA200 现有日线逻辑合并 |
| 财务趋势、现金质量、行业相对估值、三情景估值 | ⬜ | `app/analysis/fundamental/`、`app/analysis/valuation/` 待建 |
| benchmark beta/CVaR/组合相关性/风险情景 | ⬜ 部分 | beta 已修;CVaR、组合相关性、情景压力待做 |
| 合并重复技术/报告实现 | ⬜ | `app/tools/analysis/technical.py` 与 analysis_agent 的重复实现待收敛到 engine |
| `as_of` 贯穿 provider/指标/回测 | ⬜ | schema 已定义,管道传递未接 |

## Phase 2-4 — 未开始

见计划 §9。

## 环境备忘

- Poetry 2.4.1 经 `uv tool` 安装(`~/.local/bin/poetry`);项目本地 `poetry.toml` 固定 `virtualenvs.in-project=true`。
- 全量验证命令:`poetry run pytest tests/ -q`(当前 133 passed / 5 network 跳过)。
- 存量 lint 债务:`poetry run ruff check app/` 约 480+ 告警,属既有代码(主要 Dict→dict、Optional→`|` 迁移未完成),新代码已按新风格并通过。
