# 盲检能力验证站件与风险复核

检测中心配样员先登记站额和密封总数，再将不含总数的清册交给各站。站端分析员以完整证据冻结修订，并可在中心揭晓前发行 V1 站件。中心复核员收件、选定每站一个接纳号、揭晓总数并签发双站风险。次班只需中心库和报告号即可领取原定稿与成功回执。

## 运行

使用 Python 3.11 标准库。在项目根目录执行：

```sh
python3 -B check_project.py
python3 -B -m review.cli demo
```

控制台物化项目时提供 `check_project.py`。普通演示使用 `samples/demo.json`，关闭并移除临时站库以后才收件，随后重新打开中心库领取报告；复测演示在同一流程内绑定不透明候选、断源接纳伴随件并在重开后按号领取建议。两站各一片且权重中性，K 为 1，领取结果依次为 `1/2`、`1/2`、`0`；复测前最小损失为 `1/2`，两个候选复测后期望损失均为 `0`、改善均为 `1/2`，并列最优按请求顺序全部返回。直接运行 `python3 -B -m review.cli verify` 也可执行完整 unittest 套件。

## 命令

以下操作均以 `python3 -B -m review.cli` 开头。成功时标准输出是一个 JSON 值。业务拒绝时退出值为 1，原因写入标准错误。运行者将各步的 JSON 输出保存为下一步对应的输入文件。

| 操作 | 位置参数 | 返回值 |
| --- | --- | --- |
| `register` | `CENTER BATCH ALLOCATIONS_JSON K` | 可发往站端的清册 |
| `freeze` | `SITE MANIFEST_JSON STATION TRIALS_JSON` | `revision_id` |
| `issue` | `SITE REVISION_ID` | 独立 V1 站件 |
| `receive` | `CENTER BATCH PIECE_JSON` | `receipt_id` |
| `reveal` | `CENTER BATCH` | `defect_count` |
| `publish` | `CENTER BATCH RECEIPT_IDS_JSON THRESHOLDS_JSON` | `report` 和 `receipt` |
| `fetch` | `CENTER REPORT_ID` | 按号领取的 `report` 和 `receipt` |

`CENTER` 与每个 `SITE` 是不同 SQLite 文件。各命令幂等初始化自己使用的表。清册的 `allocations` 是由 `station_id` 与 `capacity` 对象组成的数组。`TRIALS_JSON` 是由 `trial_id`、`normal`、`defect` 对象组成的数组。权重可用 JSON 整数或有理数字符串，浮点 JSON 数值会被拒绝。`RECEIPT_IDS_JSON` 是正整数数组。`THRESHOLDS_JSON` 是两个 `station_id`、`minimum` 对象组成的有序数组。`samples/` 中有普通工作输入、手算核对输入和独立 V1 站件。

## Python 接口

仓储接收空闲的 `sqlite3.Connection`，可用 `storage.open_database(path)` 打开并自行关闭。仓储各自的 `initialize()` 可重复调用。站端在同一个库初始化 `ObservationRepository` 和 `StationRepository`。中心在同一个库初始化 `CampaignRepository`、`ReceiptRepository` 和 `ReportRepository`。

- `campaign.manifest.register(campaign, batch_id, allocations, sealed_count)` 返回 `Manifest`。`read_manifest(campaign, batch_id)` 读取同一投影。`allocations` 项使用 `campaign.allocation.StationAllocation`。
- `observations.revision.freeze(observations, manifest, station_id, rows)` 返回 `FrozenRevision`。`read_frozen_revision(observations, revision_id)` 按原号读回。本站修订号是本地正整数。更正时重新提交完整证据。
- `station.issuance.issue(observations, station, revision_id)` 返回含固定发行号的 V1 JSON 字符串。同一修订重复发行返回已固定的原文。
- `receipt.intake.receive(campaign, receipts, batch_id, envelope)` 返回中心接纳号。`read_accepted_piece(receipts, receipt_id)` 读回已解码站件和首次接纳原文。`receipt.selection.select_pieces(receipts, manifest, receipt_ids)` 按原顺序确定完整选件。
- `campaign.reveal.reveal(campaign, batch_id)` 返回固定总数并持久标记揭晓。`require_revealed_count(campaign, batch_id)` 读取已揭晓值。
- `review.publication.publish(campaign, receipts, reports, batch_id, receipt_ids, thresholds)` 以两个 `review.thresholds.Threshold` 发起签发。`review.readback.fetch(reports, report_id)` 领取。两者返回 `(PublishedReport, PublicationReceipt)`。

无效输入、冲突、未揭晓及证据不相容抛出 `ValueError`，未知批号、修订号、接纳号或报告号抛出 `LookupError`。SQLite 写入或提交错误向调用方传播。重复登记比较站额及密封总数并保留原揭晓状态。重复接纳按批号、站号与发行号识别同身份件，并按解析后的精确内容比较。

## V1 和计算口径

信封字段固定为 `version`、`batch_id`、`station_id`、`capacity`、`issue_id`、`revision_id`、`count_evidence`。版本为整数 `1`，身份字段为非空字符串。来源修订号在信封中是字符串。`count_evidence` 的长度为容量加一，索引就是本站缺陷片数。分数采用整数字符串或 `分子/正分母` 字符串。计数权重非负，至少一项为正，零项按索引保留。

每项权重是该计数下全部本站缺陷分配的证据权重之和。每片的正常和缺陷权重分别乘入相应分配。向量整体乘同一正因子只改变共同尺度。给定全批 K，所有大小为 K 的子集先验等可能。中心对所有站件的计数权重相乘，保留总数为 K 的组合，并在同一个分母下算第一站达标、第二站达标和共同达标。店外未查询站同样参加总数条件。门槛顺序保留，门槛零为必达，超站额的门槛事件概率为零。总相容权重为零则拒发。Python 结果用 `Fraction`，命令输出用对应字符串。

报告固定保存批号、揭晓总数、原接纳号序列、有序门槛和结果。报告与成功回执在同一次提交中写入。验证失败和 SQLite 提交失败均无新增定稿和成功回执。历史领取直接读取存档。完整套件使用独立手算数值核对两种 K、离线收件、旧修订及旧报告、站额输入边界和延迟外键造成的真实提交失败。

## 单片复测（V1 扩展）

站端在冻结时给 `observations.revision.freeze` 传可选 `candidates`，每项为 `candidate_id` 与 `trial_id`。候选号在修订内是不透明标签且唯一，绑定试片号也唯一，`trial_id` 必须属于本次提交；绑定与逐片证据同事务冻结，空序列走原 V1 流程，原试片号及候选映射只留在站库。

- `station.issuance.issue_retest(observations, station, revision_id)` 返回伴随件 JSON 文本，必须先 `issue` 出 V1 件且修订含候选，未知修订抛 `LookupError`。
- `receipt.intake.receive_retest(receipts, parent_receipt_id, envelope)` 以原 V1 接纳号为父件接纳；`receipt.intake.read_accepted_retest` 按伴随接纳号读回父接纳号与首份原文。
- `review.publication.publish_retest(receipts, reports, report_id, candidates)` 按非空有序候选引用签发建议；`review.readback.fetch_retest(reports, suggestion_id)` 按建议号领取。

伴随件顶层字段固定为 `batch_id`、`station_id`、`capacity`、`issue_id`、`revision_id`、`candidates`。前五项与父 V1 件逐字一致（`issue_id` 即确切 V1 发行身份，修订号为字符串），因此伴随件只能配其唯一父件。`candidates` 是非空对象，键为候选号，值为 `normal`、`defect` 两支长度 `capacity + 1` 的分数字符串数组。

证据编码与存储设计：站端把该候选绑定试片固定为正常（或缺陷），对其余试片照常做逐片多项式卷积，得到正常支与缺陷支。两支逐位相加恰好等于该修订的原 V1 计数向量（共同正有理数取 1），正常支在满容量位为零、缺陷支在零位为零，整支允许全零。接纳端用同一解码语义复核：每候选两支之和须等于父 V1 向量乘同一个正有理数，权重非负、边界位为零。重投时父件与候选号集合相同、且每候选两支分别与首件对应支成共同正比例即为同义，返回原伴随接纳号并保留首份原文；JSON 排版与键序不影响判定，异义件拒绝且无新增。

复测计算沿用原报告的全部选件、揭晓总数 K 与第一项门槛。把候选站的 V1 向量替换为正常支或缺陷支、其余站保持原选件证据，只保留总数为 K 的组合，分别累计两支的总质量 T 与门槛事件质量 E。该结果下条件风险为 E/T，条件最小损失为 `min(E/T, 1-E/T)`，按结果实际概率 `T/D`（D 为两支总质量之和）加权；零质量结果贡献零。改善为复测前最小损失 `min(P(E), 1-P(E))` 减去复测后期望损失。全部使用精确 `Fraction`，改善最大者按请求顺序全部并列返回。建议与成功回执同次提交，验证或提交失败无新增并可重试。
