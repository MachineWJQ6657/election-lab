# 美国选举概率预测管线 · Election Forecast Lab

可复现的美国多级选举研究原型，覆盖数据抓取、来源留痕、真实性审计、时间安全特征、逐周期回测、逐场概率、模型解释、相关席位模拟、开票前封关、选举后结果评分，以及候选人尚未确定时的 2028 情景分析。

- 代码仓库：https://github.com/MachineWJQ6657/election-lab
- 网站：https://forecast.idontknowanythingowo.cc/ （发布状态见下文“网站”）
- `data/` 内的小型教学 CSV 不参与生产预测和回测指标，详见 `data/README.md`。

## 状态：2026 中期选举已结束

**2026-11-11 更新。** 民主党同时赢得众议院和参议院。11 月 3 日开票前封关的预测判断对了两院控制权方向，参议院和州长数量落在 90% 区间内；但全国环境被低估约 6 个百分点，众议院席位超出区间上沿。完整总结与展望见 **[docs/2026_retrospective.md](docs/2026_retrospective.md)**。

| 项目 | 封关预测（11-03） | 结果（截至 11-10 媒体统计，未认证） |
|---|---|---|
| 众议院控制权 | D 79.4% | 民主党 ✓ |
| 众议院 D 席位 | 中位 230，90% 区间 205–253 | 已宣布 253–255，预计约 258–259 ✗ |
| 参议院控制权 | D 76.5% | 民主党 ✓ |
| 参议院 D 阵营席位 | 中位 53，90% 区间 47–58 | 54–44，AK/MS 未定（D 领先）✓ |
| 州长（36 场）D 胜 | 中位 22，90% 区间 16–27 | 22–12，KS/AK 未定 ✓ |
| 全国众议院票差 | D+7.2 | 约 D+12 至 D+13 ✗ |

- **逐场评分**（53 场已宣布可比较竞选）：赢家正确率 84.9%、Brier 0.104；其中有直接民调的 36 场 Brier 0.063，无民调评级先验 17 场 Brier 0.190。判错的 8 场全部是“模型看好共和党、民主党获胜”，说明误差来自共同的全国环境，而不是单场噪声。
- **主要教训**：全国环境收缩过度、全国相关性偏弱、无民调评级先验尾部太薄；众议院预测市场（94%）比模型（79%）更接近。
- **仍待确认**：AK、MS 参议院；KS、AK 州长；13–19 个众议院席位（含路易斯安那 12 月 12 日决选）。各州认证后需用认证数据重新评分。
- 两院层面数字为媒体汇总（`config/results_2026_media_tallies.json`），不是认证结果；逐场评分只覆盖已导入的宣布结果，不是完整全国评分。

## 2026 封关预测（开票前锁定）

封关时刻 `2026-11-03T06:49:43.496741+00:00`（01:49:43 EST），**不含任何开票结果**。冻结副本位于 `artifacts/final_2026_20261103T064943Z/`，元数据为 `artifacts/final_release.json`；结果评分前后 23 个文件哈希均未改变。

- 1,567 条去重民调、75 个对阵，最新调查结束日 11 月 2 日；目录覆盖 506 场（435 众议院、35 参议院、36 州长）。中央对阵有直接民调的众议院/参议院/州长分别为 11/27/34 场，其余为明确标注的评级先验。
- 50,000 次相关模拟：民主党众议院控制 79.39%、参议院 76.54%；期望 D 席位 229.46、52.79。有限权市场参考为 82.54% / 76.48%，不替代席位模拟。
- 当天预测使用最近可用的 7 天历史校准（646 场历史有民调竞选，正确率 82.20%、Brier 0.11645）。提前投票的正式概率权重为 0。
- `scripts/freeze_final_forecast.py` 检查来源观察窗口与数据/输出/引擎哈希；导出后若数据或预测改动，拒绝沿用封关标记。

各次快照的详细更新说明见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。

## 结果导入与评分

结果层只读取冻结发布，不重新拟合、不覆盖已有输出目录。媒体宣布、初步计票和认证结果严格区分；认证记录必须附官方来源、认证文件 URL 和时间。流程与数据格式见 [docs/results_2026.md](docs/results_2026.md)。

```powershell
uv run python scripts/fetch_results_2026.py --output data/results/2026_new_snapshot   # 抓取新快照
uv run python -m scripts.score_results_2026 --output artifacts/results_2026_replay    # 离线重放评分
uv run python -m scripts.export_site_results                                          # 生成网站复盘数据
```

- 当前交付评分：`artifacts/results_2026_20261111_final/`（`report.md`、`race_scores.csv`、`aggregate_scores.csv`、`manifest.json`）。
- 抓取到的第三方网页原文只保存在本地 `data/results/*/raw/`，Git 中保留带 SHA-256 的来源清单。
- 人工复核的媒体宣布记录在 `config/results_2026_reviewed_calls.json`；两院层面汇总在 `config/results_2026_media_tallies.json`。

## 展望

- **近期**：等待剩余竞选宣布和各州认证（11 月下旬至 12 月），导入认证结果重新评分；取得完整逐选区计票后，完成 435 个选区和全国通用选票的正式评分。
- **模型**：加入中期选举执政党效应与总统支持率等全国基本面；用 2026 年真实误差重估相关结构并加入浪潮年厚尾；让无民调评级先验随全国环境移动；改用随时间漂移的分层 house effect；预先登记市场权重评估。
- **2028**：现有情景模型继续只输出候选人无关的条件情景；2026 州级结果在验证增量价值前不进入正式模型。
- **发布**：为网站准备备用发布渠道，避免再次出现封关版本无法上线的情况。

## 数据真实性与来源

数据层保留 `source`、`source_id`、原始 `source_url`、抓取时间、HTTP 状态和内容 SHA-256。`elex audit-data` 检查日期、百分比、重复键、缓存哈希、原始链接覆盖、FEC 候选人备案匹配，以及 MIT 与 538 结果差异。

以下具体数量为早期快照示例；封关时的审计以 `artifacts/authenticity_report.json` 为准，状态为 `pass_with_review_flags`：

- 缓存 payload 逐一校验 HTTP 状态和 SHA-256；历史、档案、当前民调的原始链接覆盖率均为 100%。
- 2024 年 82 个总统/参议院州级结果交叉核验，中位绝对差约为 0；8 个超过 0.25 点的差异被保留为审查项，主要来自总票数/小党票聚合口径。
- 856 个已命名联邦候选人侧中，832 个找到相容的 2026 FEC 备案；24 个未匹配项是人工复核标志，不等于候选人无效。FEC 备案本身也不证明已获提名或取得选票资格。
- 删除了全国普选页混入的州长候选人行和非代表性 straw poll；跨站去重容忍聚合器日期口径相差、整数四舍五入及机构别名，但保留所有报告日期、URL 和佐证来源供复核。
- 2024 历史结果只附着给最终大选候选人，避免早期假想对阵被错误赋予最终标签；众议院选区统一为 `PA-07` 一类两位编号。

主要来源：

- FiveThirtyEight 公共历史民调与 election-results 仓库。
- MIT Election Data + Science Lab 2024 官方结果集合，作为独立结果交叉核验。
- PollingSource 的参议院、众议院、州长和全国普选公开页面。
- Decision Labs 免费公开 API（CC BY 4.0）；仅保留与当前目录两党候选人同时匹配的记录，并优先保存其原始发布者链接。
- 270toWin 的参议院与州长公开州页面；只解析 general-election 表，并保存每份民调的原始发布链接。
- Silver Bulletin 的公开全国通用选票 CSV；同一调查优先使用 LV，其次 RV/V/adults，并保留 sponsor 与党派披露。
- University of Houston Hobby School 的州级与 TX-09 原始发布页；不把选区内的参议院/州长交叉表误当成全州民调。
- Michigan Enjoyer 发布的 Cygnal/Beacon 联合调查原始表格；仅提取全州参议院/州长大选，不把同页的州众议院通用选票当成联邦众议院调查。没有披露党派赞助不等于证明不存在党派赞助。
- civicAPI 提前投票聚合数据，以及 North Carolina State Board of Elections、Florida Division of Elections 官方报表。
- 美国众议院历史办公室的官方党派席位表，与 FiveThirtyEight election-results 的全国众议院票数共同校准席位—票差曲线。
- FEC 2026 candidate master file，只用于备案交叉检查。
- Polymarket Gamma API 与 Kalshi public election API；保存事件、合约、买卖中点、价差、成交量/深度、更新时间和原始市场链接。市场价格是外部概率预测，不作为民调记录。

审计能证明来源、完整性和内部一致性，不能证明每一份调查的受访者回答“真实”，也不能把聚合器之间的重合误称为独立证据。

## 模型

每个历史预测时点只允许看到当时已经结束的民调：

```text
周期 t 的训练集 = 所有早于 t 的周期
周期 t 的测试集 = t
民调可用条件     = poll_end_date <= simulated_as_of_date
已知发布日期时   = publication_date <= simulated_as_of_date（同时成立）
```

民调权重结合 30 天半衰期、样本量、调查总体质量（LV > RV > V > adults）、披露的党派赞助折扣和同机构频次上限；先对离群值做稳健截断。发布媒体本身不直接贴左右标签，因为媒体与实际执行调查的机构并不是同一个概念；模型改用只从此前已结束周期估计、带样本收缩的 pollster house effect，避免用未来结果校准过去预测。

特征包括原始与 house-effect 调整后的民调均值、离散度、趋势、机构数、党派比例、候选人延续性、全国普选和距选举日天数。参议院常规选举的历史基准严格取六年前的同一席位周期，而不是误用两年前同州另一 Class 的参议院结果；当前全国环境也单独构造为挑战模型特征。

候选模型包括直接加权民调、house-effect 民调、固定/证据自适应/候选人感知/全国环境调整的基本盘融合、Ridge、HistGradientBoosting、残差修正和集成。`candidate_evidence_ml_blend` 在候选人更换且署名机构证据较多时逐步退出 Ridge 历史收缩；4 个及以下署名维持 50/50，12 个时完全交给候选人感知规则，参数不按单场竞选调整。机构署名数并不保证底层调查机构完全独立。生产模型按职位和最近时距选择，当前最近验证窗为 14 天；复杂模型不会自动优先，具体选择见 `latest_model_selection.csv`。

实时市场校准在模型概率之后独立运行：先把同一事件的两党价格归一化去水位，再按质量在 log-odds 空间合并 Polymarket 与 Kalshi。单场市场权重上限 30%，只有一个平台时再乘 0.75，单次概率移动上限 8 点；质量分同时考虑成交量、流动性/未平仓量、价差、更新时间和跨平台一致性。候选人姓名不匹配时只留作审计，不修改预测。`model_only_dem_win_probability` 永远保留纯模型值，因此市场不会隐藏模型自身的问题，也不进入原有历史回测指标。

输出明确区分两个问题：`polling_nowcast_*` 表示当前民调池本身的领先方和概率；`predicted_margin` / `dem_win_probability` 表示加入历史基本盘后对最终投票日的预测。二者方向不同时不会再被折叠成一个数字。

`latest_explanations.csv/json` 为每一行预测提供解释：

- `weighted_poll`：精确展示加权民调分量；
- `fundamentals_blend`：精确拆分民调分量、上次结果分量和时间先验权重；
- `latest_poll_evidence.csv`：逐份列出时间、样本量、LV/RV、党派赞助、机构频次等权重及其对民调均值的贡献；
- `latest_model_sensitivity.csv`：逐场并列纯民调、固定基本盘、证据自适应、候选人感知和全国环境调整模型，避免把模型分歧藏在单一数字后；
- 外部评级：显示评级到概率的显式映射，并标记 `not_in_poll_model_backtest`；
- 复杂挑战模型：输出非因果特征快照，不冒充因果解释；
- 民调行保存最近原始来源 URL，便于逐条复核。
- `prediction_market_signals.csv` 保存逐平台原始、去水位概率和微观结构；`prediction_market_consensus.csv` 保存跨平台共识；`prediction_market_calibration.csv` 逐场显示纯模型概率、市场概率、实际权重和概率移动。

### 联合模拟

`forecast-latest` 在逐场预测后运行 50,000 次模拟。参议院和州长使用全国/职位相关潜变量；众议院因大多数选区缺少直接民调，使用 2012–2024 全国两党票差与官方席位数拟合席位曲线，再以逐周期留一误差和通用选票历史 MAE 传播不确定性。直接地区民调不变，只把无民调评级先验校准到全国席位期望。

## 2028 情景模型

2028 年尚无稳定候选人和对应大选民调，因此模型拒绝输出虚假的单一“候选人胜率”。它以官方交叉核验的 2024 州级结果、2020 年人口普查后的 538 张选举人票、全国/地区/州相关误差和 90% 州党派倾向持续性，生成候选人无关的条件情景：

- 全国普选 R+3：民主党选举人团胜率 19.3%。
- 全国普选持平：民主党选举人团胜率 44.3%。
- 全国普选 D+3：民主党选举人团胜率 71.6%。

缅因和内布拉斯加按全州票与国会选区分别计票。结果是结构情景，不是对任何具名候选人的预测；随着 2028 候选人、基本面和民调出现，应由正式实时层替换。

## 技术栈

- Python 3.12 + `uv`：环境、锁文件、命令入口。
- Pydantic / pydantic-settings：规范化 schema 与配置。
- httpx + SHA-256 内容寻址缓存：可复现抓取与来源元数据。
- pandas / NumPy / PyArrow / Parquet：特征与数据交换。
- DuckDB：本地分析仓库。
- scikit-learn：Ridge、HistGradientBoosting、残差模型与集成。
- NumPy Monte Carlo：相关竞选、席位和选举人团模拟。
- Typer + Rich：CLI 与终端报告。
- pytest / Ruff：测试与静态检查。
- React / TypeScript / Vinext / Vite / Cloudflare Workers：网站、服务端渲染、生产打包与界面验证。

## 运行

```powershell
uv sync --extra dev

uv run elex data fetch-history
uv run elex data fetch-reference
uv run elex data fetch-fec --refresh
uv run elex data fetch-archive
uv run elex data fetch-latest
uv run elex data fetch-markets
uv run elex data fetch-early-voting --as-of 2026-10-27 --refresh
uv run elex audit-data --as-of 2026-10-27

uv run elex backtest --horizons 7,14,30,60,90 --min-cycle 2008
uv run elex forecast-latest
uv run elex forecast-2028 --simulations 60000
uv run python scripts/evaluate_poll_decay.py
uv run python scripts/evaluate_publication_lag.py
uv run python scripts/evaluate_house_control.py
uv run python scripts/audit_research_questions.py
uv run python scripts/evaluate_correlated_counts.py
uv run python scripts/evaluate_pollster_identity.py
uv run python scripts/audit_source_links.py
uv run python scripts/freeze_final_forecast.py
uv run python scripts/export_site_data.py
uv run python -m scripts.export_site_results

uv run pytest
uv run ruff check .
```

`fetch-latest --refresh` 和 `fetch-markets --refresh` 忽略六小时缓存。`forecast-latest` 默认刷新/读取市场快照；显式 `--as-of` 的历史冻结预测自动禁用实时市场，防止未来泄漏。所有规范化表写入 `data/processed/*.parquet` 和 `data/elex.duckdb`，审计、回测、解释和模拟结果写入 `artifacts/`。选举已结束，重新运行 `fetch-latest` 不会改变冻结预测；冻结版本只从 `artifacts/final_2026_20261103T064943Z/` 读取。

## 网站

源码位于 `site/`（React / TypeScript / Vinext / Cloudflare Workers），页面是显式发布的快照，不在后台实时刷新。选举后页面顶部为“结果 vs. 封关预测”复盘区，下方原样保留 11 月 3 日封关预测（地图、逐场概率、证据、模拟分布、验证与来源）。

```powershell
cd site
npm ci
npm test            # 构建 + 服务端渲染、地图、复盘数据与发布检查测试
npm run typecheck
```

- `site/lib/forecast-data.json` 由 `scripts/export_site_data.py` 生成（封关快照）；`site/lib/results-data.json` 由 `scripts/export_site_results.py` 生成（复盘数据）。
- 网站通过 OpenAI Sites 发布，`site/.openai/hosting.json` 是现有站点的非密钥配置；`site/` 内另有独立的 Sites 发布仓库。**推送 GitHub 不会更新网站**，需要单独执行 Sites 保存与部署，发布后运行 `npm run verify:publication` 核验。步骤见 `site/README.md`。
- 截至 2026-11-11，原域名上线的仍是 2026-10-20 的 v11（10 月 19 日模型数据）：封关当天 Sites 返回 `project_not_found`，11 月 3 日版本未能上线。本次复盘版本已构建并通过测试，等待发布。

## 主要产物

- 审计：`authenticity_report.json` / `authenticity_issues.csv` / `candidate_fec_audit.csv`
- 回测：`backtest_metrics.csv` / `backtest_by_office.csv` / `backtest_by_horizon.csv` / `backtest_calibration.csv` / `backtest_predictions.parquet` / `model_card.json`
- 预测：`latest_forecast.csv/json` / `latest_coverage.csv` / `latest_model_selection.csv` / `latest_model_sensitivity.csv` / `latest_explanations.csv/json` / `latest_poll_evidence.csv` / `latest_generic_ballot_snapshot.csv` / `latest_excluded_polls.csv` / `house_national_calibration.json`
- 模拟：`forecast_2026_control.json` / `forecast_2026_seat_distributions.csv`
- 市场：`prediction_market_signals.csv` / `prediction_market_consensus.csv` / `prediction_market_calibration.csv`
- 2028：`forecast_2028_scenarios.json` / `forecast_2028_state_probabilities.csv` / `forecast_2028_ev_distributions.csv`
- 封关与结果：`final_release.json` / `final_2026_20261103T064943Z/` / `results_2026_20261111_final/`

除 `results_2026_20261111_final/` 外，`artifacts/` 不进入 Git，可按上文命令重新生成。原始数据、HTTP 缓存、虚拟环境和构建输出也不进入 Git；第三方数据按各自来源条款使用，不统一改授本项目许可。

## 目录结构

```text
election_forecast/      数据源适配器、特征、模型、回测、模拟、结果评分（results.py）
scripts/                研究实验、来源审计、封关、结果抓取/评分、网站导出
config/                 来源配置、已核对的原文修正、结果复核记录与媒体汇总
data/                   教学 CSV；processed/、raw/、cache/、results/*/raw/ 仅在本地
docs/                   选举复盘、结果评分流程、更新记录、简历要点
tests/                  Python 测试（pytest）
site/                   网站源码与测试
artifacts/              本地产物（仅交付的结果评分进入 Git）
```

## 仍未解决的限制

- **全国环境**：2026 年实际误差约 6 点，暴露出通用选票收缩与基本盘缺少中期选举/总统支持率特征的问题，尚未修复。
- **相关结构**：全国相关 0.18、职位相关 0.12 在浪潮年份偏弱；相关席位检验只有少量历史周期，不能证明两院层面校准。
- **评级先验**：众议院绝大多数选区无直接民调，依赖评级先验；Safe/Likely/Lean/Toss-up 概率缺少逐日历史评级快照回测，2026 年显示尾部过薄。
- **house effect** 仍是基于此前周期误差的收缩中位数，尚未形成随时间漂移的分层贝叶斯估计；调查模式效应和未决定选民分配也待加入。
- **候选人效应**：筹款、好感度、丑闻与党内整合度尚未进入结构化历史回测。
- **来源重合**：Decision Labs、270toWin 和 PollingSource 可能转载同一原始调查；`source_count` 是佐证数量，不是独立样本。部分 270toWin 表格只有发布/更新日期而非完整调查日期。
- **结果评分**：目前只覆盖已导入的媒体宣布，众议院仅北卡与德州；全国通用选票与两院席位需等完整认证计票后正式评分。
- **预测市场**会吸收民调、评级和新闻，与模型并非独立证据；限权规则是事前 guardrail，尚未完成逐周期历史市场快照回测。
- **2028** 的最大未知量是候选人、政治环境和未来民调；当前输出只能是条件情景。
