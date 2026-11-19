# 单片复测建议

`README.md` 定义现有 V1 工作流。复核员已经拿到一份双站门槛报告，准备从若干已公开的候选中选一片做无误差复测。本次交付使用原报告的第一项门槛作为二元裁决，给出复测前的建议。既有站件、命令和报告继续按 V1 读写。

## 站端冻结和发行

给 `observations.revision.freeze` 增加可选关键字参数 `candidates=()`。参数是由 `candidate_id` 和 `trial_id` 对象组成的可迭代序列，各字段均为非空字符串。`trial_id` 须来自本次提交的试片，同一修订内候选号和绑定试片号各自唯一。候选号由站端作为不透明标签提供，在该修订内逐字匹配。绑定与逐片证据同次冻结。空序列走原流程。更正仍提交完整新修订及其候选绑定。

沿用 `station.issuance.issue` 取得 V1 件，再调用 `station.issuance.issue_retest(observations, station, revision_id) -> str` 取得该修订的候选伴随件。未知修订抛 `LookupError`，已知修订未发行 V1 或没有候选时抛 `ValueError`。同一修订重发保持来源和证据。原试片号及候选到原片号的映射留在站库。

伴随件是 JSON 文本。顶层固定字段为 `batch_id`、`station_id`、`capacity`、`issue_id`、`revision_id`、`candidates`。前五项沿用 V1 的字段类型和确切发行身份。`candidates` 是非空 JSON 对象，键为候选号，值编码该候选的复测证据。证据编码和存储设计由实现者确定，并随交付说明。接纳与签发须使用同一解码语义。

每个候选的证据须能解出两支长度均为 `capacity + 1` 的非负精确有理权重。索引 `k` 表示本站全部试片中恰有 `k` 片缺陷，计入候选本身。正常支仅包含该候选为正常的分配，因此在 `k = capacity` 为零。缺陷支仅包含该候选为缺陷的分配，因此在 `k = 0` 为零。整支可为零。两支逐位相加，须等于原 V1 向量乘以同一个正有理数。同一候选的两支以共同倍率比较，不同候选可各用自己的倍率。

## 中心接纳和签发

- `receipt.intake.receive_retest(receipts, parent_receipt_id, envelope) -> int` 接纳伴随件。`parent_receipt_id` 是原 V1 站件已经取得的接纳号。中心核对全部父件字段和每个候选的证据。一个 V1 接纳号只固定一份伴随证据。
- `receipt.intake.read_accepted_retest(receipts, retest_receipt_id) -> dict` 按伴随接纳号返回 `parent_receipt_id` 与 `envelope`。`envelope` 为第一次成功接纳的完整原文。重投时，父件及候选号集合相同、每个候选的两支分别与首次保存的那一对成共同正比例，即为同义。JSON 排版和对象键次序不影响该判定。重投同义件返回原伴随接纳号并保留首份原文，异义件拒绝。
- `review.publication.publish_retest(receipts, reports, report_id, candidates)` 接受已签发的 V1 报告号和非空有序候选序列。每项为含 `retest_receipt_id` 与 `candidate_id` 的对象，两字段组成的引用须互异。候选须来自原报告实际采用的 V1 接纳号。同批同站另一次发行，即使原计数证据相同，也不能替代报告已采用的件。站库断开后仍可接纳和签发。
- `review.readback.fetch_retest(reports, suggestion_id)` 按建议号读回已保存的建议和回执。更正或重开后仍直接读取当时的成果和来源。

计算沿用原报告的全部选件和揭晓总数 `K`。设第一项门槛为事件 `E`，一次误判损失为 1，正确裁决损失为 0。复测前最小损失为 `min(P(E), 1-P(E))`，其中 `P(E)` 是原报告第一项的风险。对每个候选，以该候选为正常、缺陷分别作条件，按各结果的实际发生概率加权两种条件下的最小损失。结果概率仍按同一个固定 `K` 和同一组选件计算，质量为零的结果贡献零。改善等于复测前最小损失减复测后期望损失。择优使用精确改善，所有最大值并列者按候选请求顺序返回。允许全量重算。

签发和领取均返回 `(suggestion, receipt)`，两者均为字典。

| 字典 | 字段与内容 |
| --- | --- |
| `suggestion` | `suggestion_id`、`report_id`、`base_loss`、`candidates`、`best` |
| `suggestion['candidates']` 的每项 | `retest_receipt_id`、`candidate_id`、`parent_receipt_id`、`expected_loss`、`improvement`，按请求顺序列出 |
| `suggestion['best']` 的每项 | `retest_receipt_id`、`candidate_id`，按请求顺序列出 |
| `receipt` | `receipt_id`、`suggestion_id` |

`base_loss`、`expected_loss` 和 `improvement` 是 `Fraction`。两个候选输出集合都是列表。编号均为非布尔正整数。中心接纳和签发使用中心原有空闲连接，站端使用站库原有空闲连接，初始化可重复。非法输入、证据或身份冲突抛 `ValueError`，未知编号或已接纳件中未知候选号抛 `LookupError`。非法绑定、接纳失败均无新增。建议和成功回执同次提交，验证或 SQLite 提交失败无新增并可重试。SQLite 写入及提交异常向调用方传播。

## 样例和运行

`samples/retest.json` 复用同目录 `base_fixture` 指定的原批次。各场景独立使用原试片，先应用 `defect_overrides` 中以站号及试片号给出的缺陷权重覆盖，再按 `candidate_bindings` 冻结。`request_order` 中每项为 `[站号, 候选号]`，签发时用该站相应的伴随接纳号构成候选引用。`expected` 的两组逐候选损失与改善按请求顺序对照，`best` 用同样的站号和候选号表示。`original` 与 `swapped` 也可在同一批次冻结为两份甲站修订，用它们各自的原报告对照。两份 V1 风险均为 `2/3`、`1/3`、`0`，用第二份甲站伴随件为第一份报告签发须拒绝。

交付时沿用根目录 `.pointwise-runtime.json` 的运行清单。`verify` 保留并运行原回归，以及核对站库断开、证据等价与冲突、原件错配、零分支、并列和失败后重试的业务验证。核验失败须返回非零退出码。`demo` 展示原报告、断源择片和中心库重开后领取建议及回执。原 V1 演示命令继续可运行。
