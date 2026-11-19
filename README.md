# 盲检能力验证站件与风险复核

检测中心配样员先登记站额和密封总数，再将不含总数的清册交给各站。站端分析员以完整证据冻结修订，并可在中心揭晓前发行 V1 站件。中心复核员收件、选定每站一个接纳号、揭晓总数并签发双站风险。次班只需中心库和报告号即可领取原定稿与成功回执。

## 运行

使用 Python 3.11 标准库。在项目根目录执行：

```sh
python3 -B check_project.py
python3 -B -m review.cli demo
```

控制台物化项目时提供 `check_project.py`。普通演示使用 `samples/demo.json`，关闭并移除临时站库以后才收件，随后重新打开中心库领取报告。两站各一片且权重中性，K 为 1，领取结果依次为 `1/2`、`1/2`、`0`。直接运行 `python3 -B -m review.cli verify` 也可执行完整 unittest 套件。

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
