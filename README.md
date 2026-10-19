# 美国选举概率预测管线

这是一个可复现的美国多级选举研究原型，覆盖数据抓取、来源留痕、真实性审计、时间安全特征、逐周期回测、逐场概率、模型解释、相关席位模拟，以及候选人尚未确定时的 2028 情景分析。

代码仓库：https://github.com/MachineWJQ6657/election-lab 。`data/` 内的小型教学 CSV 不参与生产预测和下述回测指标，详见 `data/README.md`。

## 当前快照：2026-10-19

- 最新生产集：1,155 条去重民调、66 个对阵，最新调查结束日为 2026-10-18。新增休斯敦大学 Hobby School 原始发布页适配器，核对 10 月 19 日公布的德州参议院/州长调查及 TX-09 调查，保留调查期、发布日期、样本口径和内容哈希。
- 完整历史档案：21,662 条记录、808 个竞选，包含补齐的 3,809 条全国通用选票调查（其中 661 条来自 2024 年）。合并按职位/周期替换已有摘要，避免重复计权。
- 提前投票：38 个州、229 条党籍/方式记录；10 个州有可核对人口属性数据，共 131 条边际观察。使用北卡与佛州官方报表核验，缺失不当零、未知属性不按党派或候选人分配。当前合计只覆盖有报告地区，不是完整全国投票率。
- 提前投票的中央概率权重仍为 **0**。只取得 5 个同距选举日历史州级快照，投票方式口径和当时发布记录尚不足以验证增量预测价值。
- 历史比较覆盖 1,343 场竞选、16 个周期、3,105 个留出 race/horizon 快照。全样本事后冠军的 84.0% 正确率/Brier 0.1053 不等同于生产选择策略表现，也不验证无民调评级先验或市场层。
- 当前 15 天预测时距对应 14 天验证：嵌套策略的参议院/众议院/州长子集为 619 场、10 个周期，正确率 **80.45%**、Brier **0.12156**；不混入总统和全国通用选票结果。预测概率处于 20%–80% 的 282 场竞争竞选，正确率 **60.64%**、Brier **0.23290**。
- 按整个选举周期进行 10,000 次配对 bootstrap：相对简单加权民调的 Brier 差为 +0.000039，探索性 95% 区间为 [-0.00689, +0.00631]，没有证明复杂策略优于简单策略。另一项仅在此前历史达到门槛时才启用复杂策略的实验反而变差（Brier 0.12403），未采用。
- 机构别名归并挑战实验在相同 619 场竞选上将 Brier 从 0.12156 降至 0.11922、正确率从 80.45% 提至 81.26%；逐周期配对差的探索性 95% 区间为 [-0.00706, -0.000066]。它同时改变频次折扣、机构数和 house-effect 分组，尚未拆分归因，也未处理所有赞助商/执行方区别，因此仅作为研究结果，不自动替换生产模型。机构归并键不等于统计独立样本。
- 21/30/45 天半衰期实验及外层时间选择未支持更换生产 30 天参数；加入三天发布延迟的敏感性分析仍保留。真实发布日期已知时直接执行可用性限制，不把归档 `created_at` 当成原始发布日期。
- TX-09 的已确认重划选区标志使旧选区票差先验失效。候选人姓名的重音符与缩写统一后再匹配，但未知人名不会视为匹配。MT 三方竞争与 NE 独立候选人的党团归属仍需单独解释。
- 众议院全国席位曲线只有两个完整时间外控制权周期可检验；不能用单场竞选正确率宣传两院控制权准确率。
- 新增相关席位数量检验：参议院/州长各 6 个历史民调覆盖子集周期，比较 0/0.15/0.30/0.45 相关性及只用此前周期选择的策略；按整条数量分布的 ranked probability loss 评价，未支持生产参数变更。这不是完整两院控制权回测。
- 修复同姓继任者被当成同一候选人的问题；南卡 Darline/Lindsey Graham、新泽西 Shelley/John Adler 不再继承候选人连续性。另以官方资料核对 Bob/Robert Menendez、Tim/Timothy Kaine 的特定别名，避免过度拆分。其余未核实昵称不猜测扩展。
- FEC 审计仅将给定名、相容首字母或已验证别名建立的 339/435 个记录列为兼容匹配，其余 96 个是待审名称，包含昵称、使用中间名等情况，不表示候选人无效。备案匹配不证明提名或选票资格。
- 模拟拒绝负相关、非有限概率与无效抽样次数，并保持 0/1 概率事件确定性。Python 测试覆盖上述边界与机构别名的幂等性；网站还单独执行构建、TypeScript 和服务端渲染测试。
- 验证缓存按数据、模型代码、参数和运行时版本校验。当前预测只重算当前周期和实际需要的模型依赖；早期计时中暖缓存由约 45 秒降至约 11 秒，历史所有挑战模型仍保留回测。
- 导出前检查训练数据、实时数据、关键预测文件、提前投票组件和研究报告版本，拒绝混合半更新的快照。HTTP 版本同时保存内容与观察序列，支持不使用未来来源版本的离线重放。

网站源码位于 `site/`，公开网址为 https://forecast.idontknowanythingowo.cc/ 。网站是显式发布的快照，不承诺后台实时刷新。当前本地已包含进一步审计和问题检验；最后确认成功的远端发布为版本 7，后续发布暂因原 Sites 项目连接返回 `project_not_found` 等待恢复，**GitHub 推送本身不等于网站发布成功**。

原始数据、HTTP 缓存、虚拟环境和构建输出不进入 Git；第三方数据按各自来源条款使用，不统一改授本项目许可。仓库中的网站快照保留来源链接，历史验证可按下文命令重新生成。

## 2026-10-19 初轮更新记录（历史，非当前统计）

- 民调快照：1,150 条去重记录、67 个候选人对阵，最新结束日 2026-10-18；保留四个聚合来源及原始发布链接。调查机构与赞助商的署名变体不应宣称为独立机构数。
- 抓取修复：270toWin 地图接口返回 404 时，仅使用已校验缓存中的州页面目录，再逐页抓取；移除 PollingSource 适配器内“同日同票数即重复”的错误规则，保留调查身份后集中去重；剥离机构署名中的往年误差徽标。
- 新增 `elex data fetch-early-voting --as-of 2026-10-19 --refresh`：38 个州、229 条党籍/投票方式记录，北卡官方族裔/种族/性别边际表 28 条；另抓取北卡、佛州官方报表交叉核验。当前报表合计 6,609,691 张邮寄退回与 2,884,907 张现场提前选票，仅为有报告地区的合计。
- 佛州聚合站与官方州总表有两处差异（邮寄退回及现场提前投票），采用官方州总表并展示差异。已寄出/申请、尚未退回和已退回分别处理，不把申请数算作已投票。
- 抓取三个历史周期的同距选举日数据：114 个请求中取得 5 个有效州级历史快照。历史 `returned` 有时包含现场提前投票，且缺少足够可比的当时发布记录，故提前投票对中央胜率的权重仍为 0；未用选民党籍推断秘密选票。
- 新增固定挑战模型 `quality_candidate_blend`：仅用此前周期估计机构相对误差，向总体收缩并限权，截断极端调查值。3,097 个留出快照 Brier 0.105399、MAE 4.8109、方向正确率 84.15%；原最佳 Brier 0.105259，故没有整体替换现有模型。当前办公室模型由独立历史选择规则决定。
- 更严格的嵌套时间选择评估：576 场竞选，正确率 84.55%、Brier 0.11024、MAE 4.7941。它与“挑选整体冠军后”的 3,097 快照比较指标口径不同。
- 保留独立候选人列并标注模型事件：MT 的三方竞争不显示完整胜者概率；NE 的 Dan Osborn 标为独立候选人，不暗示其参议院党团归属。控制权结果另附未决独立议席压力端点，端点不代表置信区间。
- HTTP 客户端开始按内容哈希留存不同版本，避免后续刷新覆盖滚动页面历史；这项改动无法恢复过去从未留存的版本。来源审计新增有效 HTTP URL 检查。
- 网站日期、剩余天数、验证时距和留出快照数均从实际产物生成；新增提前投票与原始来源检视。当前预测时距 15 天，对应最近的历史验证时距为 14 天。
- 补充当前时距的严格模型选择评估：773 场竞选，正确率 82.66%、Brier 0.109648、MAE 5.1018；网站使用这一口径。前述 576 场、84.55% 是 60 天时距的不同竞选集合，保留为历史参考。
- `scripts/evaluate_poll_decay.py` 比较 21/30/45 天半衰期，并另设外层逐周期选择。对应 Brier 为 0.110379 / 0.109648 / 0.108969；45 天的小幅改进未通过事先设定的 0.002 切换门槛，外层策略始终保留 30 天，生产参数未改。
- `scripts/audit_source_links.py` 检查 24 个原始来源链接，22 个可访问，Morning Consult 与一条 SurveyUSA 链接返回 403；未把访问受限当作民调虚假的证据。
- 新增预测版本清单 `forecast_manifest.json`。导出网站前必须核对当前民调、原始来源表、候选人目录与关键预测输出的 SHA-256，拒绝把刷新一半的产物混合发布。62 项测试通过。
- 网站原项目访问已恢复，第一批更新于 2026-10-19 发布到 `https://forecast.idontknowanythingowo.cc/`（版本 6）；当前时距指标及进一步审计随后同步。

## 2026-10-05 更新（历史）

- 最新抓取：1,041 条去重民调、61 个候选人对阵，最新记录日期为 2026-10-05；四个聚合来源仍为 PollingSource、Decision Labs、270toWin、Silver Bulletin。
- 市场快照刷新：两个平台、154 个来源事件、110 个竞选/控制权信号。市场不是独立民调，也不作为回测真实标签。
- 修复跨来源去重：要求调查机构或原始文档身份一致；区分 LV/RV；防止通过第三条记录把同一来源的不同跟踪波次合并；处理 Fox News 与联合 Beacon/Shaw 署名。
- 当前预测与历史训练的民调回看窗口统一为 120 天，保留 30 天半衰期。模型选择使用最近的 30 天验证时距，而非上次的 60 天。
- 49 项测试通过。此次变化不构成新的样本外准确率提升证据。
- 刷新前数据与输出保存在 `artifacts/baseline_20261005/`。滚动页面会删除旧记录、修订署名和日期；本轮发现旧快照中 109 行没有精确字段匹配，不自动重新加入，以免恢复被撤回记录或重复计权。持续历史保存仍待完善。
- 自动审计为 `pass_with_review_flags`，保留 8 条历史结果差异警告；FEC 候选人匹配 433/437。缓存哈希、URL 和表结构检查不等同于全面事实认证。
- 网站尚未发布本轮更新：Sites 返回原项目 `project_not_found`，需恢复该项目访问，未创建替代站点。

以下为旧快照记录，当前数值以 `artifacts/latest_forecast.csv` 和 `artifacts/forecast_2026_control.json` 为准。

## 2026-09-06 快照（历史）

- 长期历史：18,109 条民调，包含全国普选（generic ballot）系列。
- 完整周期档案：17,852 条 2018–2024 民调，最终结果覆盖率 98.8%。
- 最新数据：生产集有 737 条 2026 民调、64 个规范化候选人对阵、204 家调查机构；最新结束日 2026-09-04。候选人全名、简称和姓氏差异会先统一，避免同一对阵被拆成多个民调池。
- 当前竞选覆盖：435 场众议院、35 场参议院、36 场州长选举及全国通用选票。直接民调模型分别覆盖 9、21、28、1 场，其余使用明确标注的评级先验；同一调查被多个站点转载时只计一次，约 19.8% 的规范化记录保留两个以上来源的交叉佐证。
- 预测市场：从 Polymarket 和 Kalshi 官方公开 API 获取 158 个合格 source-event，去水位并合并为 111 个单场或控制权信号；69 个候选人完全匹配的竞选概率进入有限权校准。
- 回测：1,342 场独立竞选、16 个周期、3,097 个 race/horizon 留出样本；整体 Brier 最优的 `house_effect_fundamentals_blend` 方向正确率 84.0%、MAE 4.78、Brier 0.1053、log loss 0.326；`fundamentals_blend` 为 84.3%、MAE 4.94、Brier 0.1057、log loss 0.325。

84.3% 只适用于能够构造历史民调快照的留出样本，不是全部当前竞选的宣称正确率，也不验证无民调竞选的外部评级先验。

## 数据真实性与来源

数据层保留 `source`、`source_id`、原始 `source_url`、抓取时间、HTTP 状态和内容 SHA-256。`elex audit-data` 检查日期、百分比、重复键、缓存哈希、原始链接覆盖、FEC 候选人备案匹配，以及 MIT 与 538 结果差异。

以下具体数量为早期快照示例；当前审计以 `artifacts/authenticity_report.json` 为准，状态为 `pass_with_review_flags`：

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

## 2026 联合结果与历史示例

`forecast-latest` 在逐场预测后运行 50,000 次模拟。参议院和州长使用全国/职位相关潜变量；众议院因大多数选区缺少直接民调，使用 2012–2024 全国两党票差与官方席位数拟合席位曲线，再以逐周期留一误差和通用选票历史 MAE 传播不确定性。直接地区民调不变，只把无民调评级先验校准到全国席位期望。

以下数字保留为早期快照示例，**不是当前预测**；最新数值以 `artifacts/forecast_2026_control.json` 与网站导出快照为准：

- 全国通用选票：30 天半衰期加权均值 D+5.77，历史 house-effect 调整后 D+4.92。
- 众议院：民主党期望 223.0 席，模拟控制概率 64.4%；5%–95% 席位范围 198–248。Polymarket/Kalshi 去水位共识约 85.8%，有限权外部参照为 67.7%，不替代席位分布。
- 参议院：民主党阵营期望 50.30 席；在共和党副总统打破平票的假设下，模拟控制概率 47.2%。市场共识约 49.4%，有限权外部参照为 47.4%。
- 36 场州长选举：民主党期望赢得 18.94 场。
- TX Senate：19 条时点内去重民调给出 Talarico +2.0 nowcast，新模型预测 Talarico +1.9、纯模型胜率 62.9%；两平台市场约 49.0%，以有限权校准后为 59.3%。

对于尚未完成提名、存在多个对阵的州，模拟会按民调深度选中央组合，并另做“每州最不利/最有利对阵 + 所有未校准评级先验下调/上调 5 个百分点”的压力测试：众议院民主党控制概率区间 14.8%–92.3%，参议院为 43.4%–54.7%。这是刻意很宽的压力范围，不是置信区间。

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
uv run elex data fetch-early-voting --as-of 2026-10-19
uv run elex audit-data --as-of 2026-10-19

uv run elex backtest --horizons 7,14,30,60,90 --min-cycle 2008
uv run elex forecast-latest
uv run elex forecast-2028 --simulations 60000
uv run python scripts/evaluate_poll_decay.py
uv run python scripts/evaluate_publication_lag.py
uv run python scripts/evaluate_house_control.py
uv run python scripts/audit_research_questions.py
uv run python scripts/evaluate_correlated_counts.py
uv run python scripts/evaluate_pollster_identity.py
uv run python scripts/export_site_data.py

uv run pytest
uv run ruff check .
```

网站在 `site/` 下运行 `npm ci`、`npm run build`、`npm run typecheck`，以及 `node --test tests/rendered-html.test.mjs`。`site/.openai/hosting.json` 是现有站点的非密钥配置；不要为发布重建或替换项目身份。

`fetch-latest --refresh` 和 `fetch-markets --refresh` 忽略六小时缓存。`forecast-latest` 默认刷新/读取市场快照；显式 `--as-of` 的历史冻结预测自动禁用实时市场，防止未来泄漏。所有规范化表写入 `data/processed/*.parquet` 和 `data/elex.duckdb`，审计、回测、解释和模拟结果写入 `artifacts/`。

## 主要产物

- `authenticity_report.json` / `authenticity_issues.csv` / `candidate_fec_audit.csv`
- `backtest_metrics.csv` / `backtest_by_office.csv` / `backtest_by_horizon.csv`
- `backtest_calibration.csv` / `backtest_predictions.parquet` / `model_card.json`
- `latest_forecast.csv/json` / `latest_coverage.csv` / `latest_model_selection.csv` / `latest_model_sensitivity.csv`
- `latest_explanations.csv/json` / `latest_poll_evidence.csv` / `latest_generic_ballot_snapshot.csv`
- `polls_latest_raw_sources.parquet` / `latest_excluded_polls.csv` / `house_national_calibration.json`
- `forecast_2026_control.json` / `forecast_2026_seat_distributions.csv`
- `prediction_market_signals.csv` / `prediction_market_consensus.csv` / `prediction_market_calibration.csv`
- `forecast_2028_scenarios.json` / `forecast_2028_state_probabilities.csv` / `forecast_2028_ev_distributions.csv`

## 仍未解决的限制

- 当前民调严重集中于竞争州和竞争席位；众议院仅少数选区有直接民调模型支持（具体数量见 `latest_coverage.csv`），其余仍依赖评级先验。
- Safe/Likely/Lean/Toss-up 概率仍缺少逐日历史评级快照回测；全国席位曲线修复了总体与通用选票明显冲突的问题，但不能把每个无民调选区都变成已验证的地区预测。
- house effect 目前是基于此前周期误差的收缩中位数，尚未形成随时间漂移的分层贝叶斯估计；调查模式效应、未决定选民分配和地区级历史相关矩阵也仍待加入。
- 候选人筹款、好感度、丑闻/任职表现与党内整合度尚未进入结构化历史回测，因此像 Talarico–Paxton 这种候选人效应异常强的竞选，中央基本盘融合可能仍然过度保守；nowcast 与多个透明规则模型会并列输出。
- Decision Labs、270toWin 和 PollingSource 都可能转载同一原始调查；`source_count` 是来源佐证数量，不是新的独立样本，也不会增加该调查权重。
- 270toWin 表格有时只列一个发布/更新日期，而不是完整 field dates；模型保留各站报告日期与原始链接，并在跨源去重时允许有限日期偏差。
- 初选与候选人状态会变化；`nominee TBD` 表示未知，不做姓名猜测。
- 2028 的最大未知量是候选人、政治环境和未来民调；当前输出只能是条件情景。
- 预测市场会吸收民调、评级和新闻，因此与模型并非独立证据；市场可能受交易者结构、费用、流动性、监管和合约结算口径影响。当前限权规则是事前 guardrail，尚未完成逐周期历史市场快照回测，故控制权市场只显示为外部参照。
