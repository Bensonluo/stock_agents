# Stock Agents V2：专业股票研究方法论与全栈升级方案

> 调研日期：2026-08-27  
> 目标：把当前“多个模块给出几个标签和总分”的演示系统，升级为可解释、可核验、可回测的专业股票研究辅助系统。本文不构成投资建议。

## 1. 执行摘要

当前系统的问题不只是技术指标数量少，而是四层信息损失叠加：

1. 数据层只取约 90 天日线，却尝试计算 50/200 日均线，长周期指标天然缺失。
2. 分析层存在单位错误、占位结果和过度简化规则，例如 Yahoo ROE 通常是小数，代码却用 20、15、10 作为阈值；Beta 固定为 1.0；增长固定给 50 分。
3. 决策层使用没有研究依据的固定权重，把缺失数据当成中性数据，并把不同投资周期压缩成一个买卖标签。
4. 报告层丢掉大部分指标细节，深度 LLM 报告又被禁用；前端只显示首个股票和前 8 个指标。

V2 应采用以下原则：

`带截止时间的数据快照 -> 确定性指标与估值 -> 专业分工分析 -> Bull/Bear 质询 -> 证据审计 -> 风险门控 -> 情景化结论 -> 成本化回测`

最重要的边界是：代码负责事实、公式和计算；LLM 负责解释、比较、质疑和综合。任何精确数字都必须带来源、截止时间、单位和计算方法。

## 2. 当前代码审计

### 2.1 P0：会直接影响结论正确性的问题

| 问题 | 当前证据 | 影响 | 应对 |
|---|---|---|---|
| 活跃输出契约断裂 | `app/react_agent/react_agent.py:321-340` 把 report 重新拼成 Markdown + JSON code block；前端 `frontend/src/app/result/page.tsx:674-691` 主要对纯 JSON 走结构化渲染 | 当前主入口常退化为原始 Markdown/代码块，结构化研究数据无法稳定显示 | API 返回版本化 `ReportV2` 对象；Markdown 只是独立 renderer；Pydantic schema 与 TypeScript 类型同源生成 |
| 历史窗口不足 | `app/agents/data_agent.py:90-92` 和 `app/tools/data/fetcher.py:87-89` 只取 90 天；`app/agents/analysis_agent.py:143-146` 却计算 SMA20/50/200 | SMA200 为 NaN/None，周线分析不可能成立 | 默认获取至少 3 年复权日线，同时生成周线；按最长窗口校验 warm-up |
| 财务单位错误 | `app/agents/data_agent.py:145-166` 直接使用 yfinance 比率；`app/agents/analysis_agent.py:624-664` 把 ROE/ROA 与 20、15、10 比较，但利润率又与 0.2、0.1 比较 | 常见 ROE=0.20 会被当成低于 5，盈利质量严重低估；Debt/Equity 也可能存在百分数尺度差异 | 在 provider adapter 中统一为明确单位；schema 增加 `unit`；加入真实样本契约测试 |
| 增长分析是假结果 | `app/agents/analysis_agent.py:790-807` 永远返回 50 分 | 缺失信息被伪装成“中性”，随后参与总分 | 缺失返回 `status=insufficient_data`，总分按可用权重重归一化，禁止填充中性分 |
| Beta 是占位值 | `app/agents/risk_agent.py:191-202` 固定返回 1.0 | 风险分、仓位和报告中的 Beta 没有信息量 | 按股票与正确基准的对齐收益计算 rolling beta，并报告窗口、R²、置信区间 |
| 回测参数会错传 | `app/api/routes/backtest.py:120-126` 把 SMA 和 RSI 参数同时传给任一策略 | Backtrader 策略可能收到未知参数而失败；API 宣称支持但不可可靠运行 | 按 strategy 构建判别联合参数模型，只传当前策略字段；增加每种策略 API 集成测试 |
| ReAct 推荐可脱离投资证据 | `app/react_agent/react_agent.py:261-309` 在没有决策时仅按风险分推导 buy/add/hold/reduce | “风险低”会被错误等价为“值得买” | 风险只能限制仓位/否决，不能产生方向性买入信号；必须有估值与预期收益证据 |

### 2.2 P1：造成信息量低和专业性不足的问题

| 问题 | 当前证据 | 改造方向 |
|---|---|---|
| 两套技术分析重复且不一致 | `app/agents/analysis_agent.py` 与 `app/tools/analysis/technical.py` 各自实现 RSI/MACD/SMA，后者甚至没有 SMA200 | 合并为唯一 `TechnicalEngine`，pipeline 与 ReAct 只调用同一领域服务 |
| 指标实现与行业标准有偏差 | RSI 使用简单 rolling 均值，EMA 未显式指定 `adjust=False`，docstring 声称使用 pandas-ta 但依赖中没有它 | 明确公式版本；用 TA-Lib 结果做 golden test；返回参数和 warm-up 元数据 |
| 支撑阻力过于脆弱 | 只在最近 20 个收盘价中找局部极值，忽略 high/low、成交量和多次触碰 | 用 pivot/ATR 容差聚类、成交量分布和多时间框架确认；输出区间而非伪精确点位 |
| 基本面阈值跨行业通用 | P/E、P/B、负债率等使用绝对固定阈值 | 使用行业/市场/自身历史分位数；按银行、保险、REIT、周期、亏损成长股切换估值模板 |
| 新闻情绪是英文关键词计数 | `app/agents/sentiment_agent.py:89-149` 用 substring 计分 | 先做股票实体关联、时间衰减、来源权重、事件分类和“实际值 vs 预期值”；LLM 输出必须引用新闻 ID |
| 组合风险名不副实 | `app/agents/risk_agent.py:383-433` 主要按股票数量给 diversification score | 基于收益协方差、行业/因子暴露、集中度、流动性和压力场景计算 |
| 决策权重无校准 | `app/agents/decision_agent.py:109-154` 固定为技术 30%、基本面 40%、情绪 15%，且置信度只是符号一致程度 | 先声明投资周期/风格，再选择模型；置信度由数据覆盖、证据一致、历史校准和模型不确定性构成 |
| 报告主动丢数据 | `app/agents/report_agent.py:152-194` 只保留 trend/RSI/MACD/支撑阻力；`app/tools/report/generate.py:67-82` 更少 | 报告直接消费统一 ResearchPacket，显示关键数值、变化、对比、来源和反方观点 |
| 深度报告被关闭 | `app/agents/report_agent.py:56-65` 整段 LLM 报告被注释 | 恢复异步、可超时降级的证据约束生成；即使降级也保留完整结构化表格 |
| 前端只展示首个股票 | `frontend/src/components/analysis/AnalysisResult.tsx:17-20` 固定 `firstSymbol`；指标又 `.slice(0, 8)` | 每个标的独立页面/标签，增加多周期图、证据抽屉、场景表和可比公司表 |

### 2.3 工程可靠性

- 当前测试目录几乎没有覆盖技术、基本面、估值、报告、回测策略。
- 本次审计执行 `poetry run pytest -q` 时，Poetry 环境指向已不存在的 Python 3.12 动态库，测试无法启动。
- 工作区已有未提交改动；实施 V2 时应先建立基线分支并保护现有修改，不能用破坏性重置。

## 3. 专业股票研究方法论

### 3.1 先定义研究任务

同一只股票对短线交易者和三年期投资者可能有相反结论。每次分析必须先记录：

- `as_of`：所有数据不得晚于该截止时间。
- 市场、币种、交易所时区、复权方式。
- 投资期限：短线 1-20 个交易日、中期 1-6 个月、长期 1-3 年。
- 目标：择时、长期持有、事件交易、同业比较或组合风控。
- 基准：A 股用合适宽基/行业指数，美股用市场和行业 ETF，不能所有股票统一对比 S&P 500。
- 用户约束：已有持仓、成本、最大可承受回撤、流动性和集中度限制。

输出若缺少这些上下文，只能给“研究观察”，不能给仓位建议。

### 3.2 八层研究框架

#### A. 公司与商业模式

- 收入、利润、资产和现金流按业务/地区拆分，至少覆盖 3-5 年。
- 客户与供应商集中度、定价权、复购/留存、单位经济性、资本强度。
- 竞争格局、进入壁垒、替代风险、监管依赖。
- 管理层资本配置：再投资、并购、回购、分红、股权稀释及历史兑现率。

这一层产生“公司如何赚钱、什么驱动价值、什么会破坏逻辑”，不产生简单分数。

#### B. 财务质量与趋势

至少分析 5 年年报和 8-12 个季度，区分 TTM、年度和单季：

- 增长：收入、毛利、营业利润、EPS、经营现金流、自由现金流 CAGR 与增速变化。
- 盈利：毛利率、营业利润率、净利率、ROA、ROE、ROIC；必须拆解一次性项目和杠杆贡献。
- 现金质量：CFO/净利润、FCF/净利润、应收/存货增速与收入增速、应计项目。
- 偿债：净负债/EBITDA、利息覆盖、短债与现金、债务到期结构；银行等金融企业另用资本充足率和资产质量指标。
- 资本配置：增量 ROIC、回购价格、分红覆盖、并购商誉、SBC 稀释。
- 红旗：审计意见、频繁更换审计师、关联交易、非经常性损益、资本化政策变化。

可以把 Piotroski F-score 当作财务健康辅助检查，但不能替代行业分析和估值。

#### C. 估值

必须同时给出区间和敏感性，而不是一个“精确目标价”：

1. 内在价值：DCF/股利折现/剩余收益，使用 Bear/Base/Bull 三种情景。
2. 相对估值：同行可比、公司自身历史分位；说明同行选择标准。
3. 行业模板：
   - 一般非金融企业：EV/EBITDA、P/E、FCF yield、DCF。
   - 银行/保险：P/B、ROE、资本充足与剩余收益，避免机械用 EV/EBITDA。
   - REIT：P/FFO、NAV、利率敏感性。
   - 周期股：中周期利润/EBITDA 和资产负债表，不用景气顶点利润外推。
   - 亏损成长股：EV/Sales、毛利、留存、单位经济性与达到盈亏平衡所需融资。
4. 输出关键敏感性：收入增长、利润率、WACC、终值增长率、估值倍数每变动一档，价值区间如何变化。

#### D. 技术面与市场状态

技术面用于描述趋势、拥挤程度、波动和交易位置，不应被宣传为确定预测。研究证据并不一致：早期研究支持部分移动平均规则，但后续真正样本外研究发现预测力衰减。因此指标必须经当前市场、成本和样本外验证。

固定核心包：

- 趋势：周线 SMA 组、日线 SMA/EMA、ADX、52 周位置。
- 动量：1/3/6/12 月收益、RSI、MACD histogram 的方向和加速度、相对强弱。
- 波动：ATR%、20/60 日实现波动、布林带宽及波动率分位。
- 成交量：量比、OBV/累积量、突破是否放量。
- 结构：经 ATR 容差聚类的支撑/阻力区、缺口、近期高低点。
- 市场状态：趋势/震荡、高波/低波、风险偏好，以及大盘/行业是否同向。

##### 五组周线 SMA

默认产品预设建议为 `5/10/20/40/60 周`，覆盖约一个月至一年以上的趋势层级。这只是可解释的默认网格，不是被证明“最优”的神奇参数，必须允许按市场和持有期配置。

每条 SMA 不只返回数值，还必须返回：

- 当前 SMA、现价距离 `%`、4 周与 12 周斜率。
- 价格在其上/下，连续维持的周数。
- 与其他均线最近交叉日期、交叉后收益和成交量确认。
- 均线多头/空头/缠绕排列及排列持续时间。
- 样本数、warm-up 是否满足、最后有效交易日。

综合解释示例：

- `价格 > SMA5 > SMA10 > SMA20 > SMA40 > SMA60` 且中长均线向上：多周期趋势一致，但若 ATR 和 RSI 位于高分位，应提示追高风险。
- 价格上穿 SMA20 但仍低于下行的 SMA40/60：可能只是中期反弹，不能称长期反转。
- 均线缠绕、ADX 低：均线交叉更容易产生噪声，应降低趋势信号权重。
- 突破未获成交量与相对强弱确认：标记为低置信度，而不是直接买入。

#### E. 催化剂与预期差

- 未来 90/180/365 天的财报、产品、审批、解禁、回购、股东大会、宏观事件。
- 区分“好消息”与“超预期”：价格更常反映实际值相对市场预期的变化。
- 每个事件给方向、可能影响、日期确定性、市场是否已计价和反证。

#### F. 新闻、公告与情绪

- 一手公告优先于媒体摘要；保存 URL、发布日期、事件时间和抓取时间。
- 对每条新闻做实体关联、重复去除、事件分类、来源可信度、时间衰减。
- 财报事件提取 actual/consensus/surprise；分析师一致预期必须标记数据供应商和更新时间。
- 情绪只能作为证据之一，不能用新闻标题词频直接生成方向性仓位。

#### G. 风险与组合影响

- 个股：历史/隐含波动、下行波动、VaR/CVaR、最大回撤、跳空、流动性、财务和事件风险。
- 相对风险：rolling beta、相关性、行业和风格因子暴露；报告估计窗口与稳定性。
- 组合：单票/行业集中度、相关性簇、压力测试、预期亏损和流动性天数。
- 情景：至少 Bear/Base/Bull，给概率区间、价格/收益区间和触发条件。
- 仓位：由风险预算、止损距离和组合相关性决定；“风险低”本身不能推出“买入”。

#### H. 最终投资论点

每个结论必须回答：

1. 一句话 thesis。
2. 市场可能错在哪里。
3. 3-5 条支持证据及来源。
4. 最强反方证据。
5. Bear/Base/Bull 估值与概率区间。
6. 催化剂、投资期限和预期路径。
7. thesis invalidation：出现什么事实就承认判断失效。
8. 数据覆盖率与置信度；置信度不是“模型自信”，而是可校准的证据质量指标。

### 3.3 评分方式

不要继续使用一个适用于所有股票的固定总分。建议两阶段：

1. 硬门控：数据不足、流动性不足、财务高风险、估值不可用或证据冲突时，输出 `insufficient_data/watch/avoid`。
2. 情景决策：根据投资期限选择权重，计算预期收益区间、下行风险和风险收益比。

置信度由四部分组成：数据覆盖 30%、数据时效和来源 20%、独立证据一致性 25%、历史校准/样本外稳定性 25%。任何一项缺失都要显式扣分。

## 4. V2 目标架构

```text
Request + as_of + horizon + benchmark
                  |
          Data Snapshot Builder
     prices / filings / news / macro / estimates
                  |
       Normalization + Quality Gate
                  |
       Deterministic Research Engines
 technical | financial | valuation | events | risk
                  |
          Evidence Store / ResearchPacket
                  |
    Analysts in parallel (facts may only cite packet)
 technical | fundamental | valuation | event/macro
                  |
        Bull vs Bear Cross-Examination
                  |
             Evidence Auditor
                  |
              Risk Committee
                  |
            Portfolio Manager
                  |
       Structured report + UI + artifacts
                  |
       OOS backtest / evaluation feedback
```

关键设计：

- `as_of` 是贯穿所有 provider、指标、公告、新闻和回测的必填字段。
- 所有计算输出统一 `MetricEvidence`，禁止裸 float 在 Agent 间传播。
- 分析 Agent 可并行；Evidence Auditor 和 Risk Committee 必须在最终决策前串行门控。
- Bull/Bear 辩论只允许引用 evidence ID，不能自由补充数字。
- Pipeline 和 ReAct 共享同一领域服务，不能再维护两套指标和报告逻辑。

建议的核心数据契约：

```json
{
  "metric_id": "AAPL.technical.sma_weekly_20.2026-08-26",
  "name": "sma_weekly_20",
  "value": 215.37,
  "unit": "USD",
  "as_of": "2026-08-26T20:00:00Z",
  "source": "provider_name",
  "source_ref": "snapshot-id-or-url",
  "formula": "mean(adjusted_weekly_close, 20)",
  "params": {"window": 20, "frequency": "1wk", "adjustment": "split_dividend"},
  "sample_count": 20,
  "quality": "verified"
}
```

## 5. 代码改造蓝图

### 5.1 新领域层

建议逐步形成：

```text
app/domain/schemas/              # Snapshot、MetricEvidence、ResearchPacket、ReportV2
app/data/providers/              # yfinance/akshare/SEC/公告/宏观 adapter
app/data/normalization/          # 单位、币种、时区、复权、财报期间标准化
app/data/quality/                # freshness、coverage、冲突、as_of 检查
app/analysis/technical/          # 唯一技术指标引擎
app/analysis/fundamental/        # 财务趋势、质量、行业模板
app/analysis/valuation/          # DCF、comps、敏感性、场景
app/analysis/events/             # 公告/财报/催化剂与预期差
app/analysis/risk/               # 个股、组合、压力测试
app/research/evidence_store.py   # evidence ID、来源、artifact
app/research/evaluator.py        # 覆盖率、引用、矛盾、校准
app/backtest/                    # 数据、策略、成本、walk-forward、报告
```

### 5.2 对现有文件的处理

1. `app/agents/data_agent.py`
   - 只保留编排；具体供应商移入 provider adapter。
   - 日线默认 3-5 年，生成等频周线；保存交易所日历、时区、复权方式和 `as_of`。
   - 财报保存 fiscal period、filed_at、accepted_at，避免用后来修订数据回测过去。

2. `app/agents/analysis_agent.py` 与 `app/tools/analysis/technical.py`
   - 抽出唯一 TechnicalEngine；删除重复公式。
   - 实现五组周 SMA、日线 20/50/100/150/200、ADX、RSI、MACD、ATR%、OBV、相对强弱和 regime。
   - 缺数据返回明确状态，不返回 NaN 或伪中性。

3. `app/agents/analysis_agent.py` 的基本面部分
   - 拆成 FinancialQualityEngine 和 ValuationEngine。
   - 统一百分数单位，补齐 quarterly/annual trend、CFO/NI、FCF、ROIC、稀释、行业分位与专用行业模板。

4. `app/agents/risk_agent.py`
   - 用实际 benchmark 计算 beta/alpha/R²；增加 CVaR、Sortino、rolling drawdown、相关性和情景压力。
   - 仓位建议需要账户风险预算；无账户信息只给“风险观察”，不给精确仓位百分比。

5. `app/agents/decision_agent.py`
   - 删除硬编码万能权重和“风险低即可以买”的推导。
   - 改为 ThesisDecision：期望收益区间、风险收益比、证据覆盖、反方观点、失效条件、action gate。

6. `app/agents/report_agent.py` 与 `app/tools/report/generate.py`
   - 合并为 ReportService，schema 与渲染分离。
   - LLM 只填叙述字段，数字从 ResearchPacket 引用；生成后做引用完整性和数值一致性检查。

7. `app/orchestration/orchestrator.py`
   - 数据与确定性计算先执行；四个研究 Agent 并行。
   - 新增 Bull、Bear、EvidenceAuditor、RiskCommittee、PortfolioManager；每个有结构化输入输出和否决条件。

8. `app/react_agent/prompts.py` 与 `app/react_agent/react_agent.py`
   - 工具 schema 增加 `as_of/horizon/benchmark`。
   - 取消从位置大小或风险分反推动作的 fallback。
   - 最终回答通过 ReportService，不再把 JSON 直接塞进 Markdown code block。

9. `app/services/backtest_service.py` 与 `app/api/routes/backtest.py`
   - 修复策略参数分派；保存结果与实验配置。
   - 增加 benchmark、手续费、印花税/SEC fee、滑点、成交延迟、分红拆股、停牌/涨跌停处理。
   - 加入 rolling walk-forward、参数邻域、跨股票/跨市场、样本外区间和失败结果展示。

10. `frontend/src/components/analysis/AnalysisResult.tsx`
    - 改成 ReportV2 类型而非 `any`。
    - 增加多标的导航、K 线和五周线、估值情景、财务趋势、催化剂时间线、风险瀑布、证据来源抽屉、Bull/Bear 分歧。

### 5.3 依赖选择

- 技术指标：SMA 自己用 pandas 实现很简单，但必须用 TA-Lib 作为一致性基准；复杂指标可直接使用 TA-Lib。其官方库覆盖 150/200+ 类指标。
- 快速参数研究：可评估 vectorbt；适合大量组合扫描，但商业使用前检查当前许可证，且高速扫描必须配套过拟合控制。
- 实验与组合研究：借鉴 Microsoft Qlib 的 Dataset/Workflow/Recorder 分层；初期不必一次性重写到 Qlib，可先实现兼容的 run manifest。
- 高保真回测：短期修好现有 Backtrader；中长期若需要实盘级成交/风控，评估 LEAN。
- 财务一手数据：美股优先 SEC EDGAR/XBRL；A 股优先交易所/巨潮公告，yfinance/AkShare 适合作为便利层而非唯一事实源。
- 宏观：FRED/ALFRED 等带 vintage 的数据，回测必须使用当时可见版本，避免修订后数据泄漏。

## 6. Agent 角色与协议

| 角色 | 输入 | 输出 | 禁止事项 |
|---|---|---|---|
| Technical Analyst | TechnicalEvidencePack | 多周期趋势、regime、关键区间、反转/延续条件 | 自己算数、把单一交叉当确定信号 |
| Fundamental Analyst | 财报与行业证据 | 商业质量、财务趋势、红旗、可持续性 | 用统一阈值评价所有行业 |
| Valuation Analyst | 标准化财务与估值假设 | Bear/Base/Bull、公允价值区间、敏感性 | 输出无假设的精确目标价 |
| Event/Macro Analyst | 公告、新闻、日历、宏观 | 催化剂、预期差、冲击路径 | 引用无时间戳摘要 |
| Bull Researcher | 所有 analyst packet | 最强多头论据及证据 ID | 忽略反方证据 |
| Bear Researcher | 同上 | 最强空头论据、尾部风险和 thesis breaker | 只做措辞相反的重复 |
| Evidence Auditor | 全部 claim/evidence | unsupported、stale、conflict、look-ahead 清单 | 参与方向投票 |
| Risk Committee | 已审计研究包与组合 | 风险预算、压力情景、批准/限制/否决 | 用低风险生成买入方向 |
| Portfolio Manager | 审计与风控后的包 | 条件化结论、期限、仓位上限、失效条件 | 覆盖硬风险门控 |

## 7. 回测与有效性验证

### 7.1 最低回测标准

- 时间序列严格按 `as_of` 截断；财务数据用 filing/accepted date，不用财报期末日假装可见。
- 调仓信号至少下一根可交易 bar 成交，不能用本 bar 收盘产生信号又按同一收盘成交。
- 计入佣金、税费、滑点、买卖价差、最小费用和流动性约束。
- 同时展示 buy-and-hold、宽基和行业基准。
- 指标：CAGR、超额收益、Sharpe、Sortino、Calmar、最大回撤、CVaR、胜率、盈亏比、换手、暴露和成本占比。
- walk-forward：滚动训练/选择参数，随后只在下一段未见数据测试。
- 展示全部参数邻域和失败年份，不只展示最优组合。
- 记录测试过的参数/策略数量；大量尝试会显著增加 backtest overfitting 风险。

### 7.2 五周线验证

不要问“哪一条均线最好”，而要验证：

1. 5/10/20/40/60 周作为状态特征，是否在不同 regime 下改善风险收益。
2. 使用均线排列、斜率、距离、ADX/量价确认，是否优于单纯交叉。
3. 参数在相邻窗口（例如 18/20/22 周）是否稳定。
4. 在 A 股、美股、宽基、行业与不同市值中是否一致。
5. 加入真实成本后是否仍有效。

结果只能称“在指定样本和假设下有效”，不能把历史相关性写成未来保证。

## 8. 测试与评估体系

### 8.1 代码测试

- Provider contract：单位、币种、时区、复权、财报期间和缺失值。
- Indicator golden test：与 TA-Lib/手工小样本对齐，覆盖 warm-up、停牌、零成交量、拆股。
- Property test：指标不得读取未来；同一 snapshot 重跑结果一致。
- Fundamental fixtures：美股/A 股、银行、亏损成长股、负权益公司。
- Backtest fixtures：策略参数只传给对应策略；禁止同 bar 偷看；费用可核算。
- Report schema：任何展示数字必须能解析到 evidence ID。

### 8.2 Agent 评估

建立 30-50 个固定历史案例的离线 eval：

- 数字准确率、引用覆盖率、引用是否真的支持 claim。
- stale/look-ahead 检出率、矛盾检出率。
- 缺数据时拒答率，不能用流畅文字掩盖空数据。
- Bull/Bear 是否提供独立证据，而不是措辞镜像。
- 同一 snapshot 多次运行的关键结论一致性。
- 结论校准：70% 置信度的事件长期应接近相应命中频率；未校准前不要展示“87% 信心”这类数字。

## 9. 分期实施路线

### Phase 0：恢复可信基线（2-3 天）

- 修复 Poetry Python 环境并锁定可复现版本。
- 为当前输出建立 characterization tests 和 3-5 个冻结数据 snapshot。
- 修复回测参数错传、财务百分数单位、SMA200 数据不足、Beta/增长占位结果。
- 定义 ReportV2、MetricEvidence、DataQuality schema。

验收：CI 可运行；所有占位值被标为缺失而非进入评分；已有用户修改不丢失。

### Phase 1：专业确定性分析（第 1-3 周）

- 数据窗口、周线、五组 SMA 和完整 TechnicalEvidencePack。
- 财务趋势、现金质量、行业相对估值与三情景估值。
- 正确的 benchmark beta、CVaR、组合相关性和风险情景。
- 合并重复技术/报告实现。

验收：固定 snapshot 的所有指标可复现；每个指标有单位、公式、日期和质量状态；无 NaN 静默流入。

### Phase 2：Agent 与报告升级（第 4-6 周）

- 并行专业 Analyst、Bull/Bear、Evidence Auditor、Risk Committee。
- 证据约束 prompt 与结构化输出；报告前自动 contradiction/citation check。
- 前端五周线、估值情景、财务趋势、催化剂、证据抽屉和多股票视图。

验收：固定 eval 中精确数字 100% 可追溯；无证据 claim 被拦截；缺数据明确降级；报告不再只给标签。

### Phase 3：回测与研究闭环（第 7-10 周）

- 成本化、基准化、walk-forward 与参数敏感性。
- 实验 manifest：数据哈希、参数、代码 commit、模型/prompt 版本和 artifacts。
- 技术信号与综合评分的历史校准；展示失败结果。

验收：任何策略结果可一键重现；无未来数据；报告同时显示样本内/样本外、成本前/后和参数邻域。

### Phase 4：高级能力（后续）

- SEC/交易所公告的文档 RAG 与表格解析。
- 预期数据、估值修正、期权隐含信息和供应链事件。
- Qlib/LEAN 级组合研究、模拟盘和事后归因。
- 自动因子研究只能进入 sandbox，必须经过多重检验和人工批准才能进入正式报告。

## 10. 最终验收指标

| 维度 | V2 最低标准 |
|---|---|
| 数据 | 100% 数字有 source/as_of/unit；核心数据覆盖率可见；冲突不静默覆盖 |
| 技术 | 5/10/20/40/60 周 SMA、斜率/距离/交叉/排列/warm-up 全部可复现 |
| 基本面 | 至少 5 年年度 + 8 季度趋势；缺失不填中性分；行业模板正确路由 |
| 估值 | 至少两种方法或说明为何不适用；Bear/Base/Bull 与敏感性完整 |
| 风险 | 实际 benchmark beta、CVaR/回撤、催化剂风险、组合集中与相关性 |
| Agent | 每个 claim 引用 evidence；Auditor 可阻止 unsupported/stale/look-ahead 输出 |
| 报告 | thesis、反方、催化剂、失效条件、估值区间、数据质量齐全 |
| 回测 | OOS/walk-forward、成本、基准、参数邻域、实验次数和失败区间齐全 |
| 工程 | CI 全绿；领域核心高覆盖；固定 snapshot 回归；schema 有版本迁移 |

## 11. 外部方案的正确借鉴方式

- TradingAgents：学习 Analyst -> Bull/Bear -> Trader -> Risk -> Portfolio Manager 的角色设计；不要采信其短样本高收益作为生产证明。
- FinRobot：学习 lead agent、多数据源、估值和专业研究报告；不要让 LLM 承担关键计算。
- Microsoft Qlib：学习数据集、特征、策略、回测、Recorder 和 point-in-time 研究闭环。
- LEAN：学习手续费、滑点、成交、市场冲击和组合级硬风控。
- vectorbt：用于快速参数矩阵与 walk-forward 研究；用得越快，越要控制多重尝试和过拟合。
- TA-Lib：作为确定性指标层和测试基准；它不替代投资方法、数据质量或回测。

## 12. 主要依据与可信度

- [CFA Institute：Equity Valuation—Applications and Processes](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/equity-valuation-applications-and-processes)：研究报告应及时、客观、区分事实和观点、披露假设和风险，并保持预测/估值/建议一致。可信度：高。
- [Kenneth French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)：价值、盈利、投资和动量等因子定义与历史数据。可信度：高。
- [Damodaran Valuation resources](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valuation/val.htm)：DCF、相对估值和敏感性分析方法与模板。可信度：高。
- [Piotroski, 2000](https://www.ivey.uwo.ca/media/3775523/value_investing_the_use_of_historical_financial_statement_information.pdf)：用财务报表信号区分价值股财务强弱。适合作为辅助，不是万能选股模型。可信度：高。
- [Brock, Lakonishok & LeBaron, 1992](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1992.tb04681.x)：早期长样本支持移动平均和突破规则。可信度：高，但时间外推有限。
- [真正样本外技术规则研究](https://www.sciencedirect.com/science/article/abs/pii/S1058330013000396)：1987-2011 新数据未发现若干经典规则具有预测力。可信度：高；说明技术指标必须重新验证。
- [Moskowitz, Ooi & Pedersen, 2012：Time Series Momentum](https://fairmodel.econ.yale.edu/ec439/mosk.pdf)：多资产中 1-12 个月趋势持续、长期部分反转的证据。可信度：高；个股直接外推为中。
- [Bailey et al.：Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659)：测试配置越多，历史最优结果越容易过拟合。可信度：高。
- [QuantConnect Research Guide](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/research-guide)：假设驱动、限制反复试验、保留样本外数据。可信度：高。
- [Microsoft Qlib 官方文档](https://github.com/microsoft/qlib/blob/main/docs/index.rst)：数据、模型、策略、回测、实验记录和 point-in-time 组件。可信度：高。
- [QuantConnect LEAN algorithm engine](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/algorithm-engine)：事件驱动、现实模型和避免未来数据。可信度：高。
- [TA-Lib 官方文档](https://ta-lib.github.io/index.html)：指标库范围与标准实现。可信度：高。
- [TradingAgents 官方仓库](https://github.com/TauricResearch/TradingAgents) 与 [论文](https://arxiv.org/abs/2412.20138)：多角色研究/辩论架构。架构可信度：高；其短期回测收益外推可信度：低。
- [FinRobot 官方仓库](https://github.com/AI4Finance-Foundation/FinRobot) 与 [论文](https://arxiv.org/abs/2405.14767)：金融 Agent 平台和 equity research 工作流。架构可信度：高；投资绩效结论：中低。
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)：公司 submissions 与 XBRL Company Facts 的一手接口。可信度：高。
- [FRED/ALFRED API](https://fred.stlouisfed.org/docs/api/fred/overview.html)：宏观序列和历史 vintage 数据。可信度：高。

总体判断置信度：

- 对当前代码正确性缺陷：高，来自直接代码证据。
- 对专业研究流程和可复现架构：高，得到官方/学术资料和成熟开源系统交叉支持。
- 对任何特定技术指标能产生未来超额收益：低到中，依赖市场、样本、成本和参数，必须由本项目自己的样本外测试决定。
