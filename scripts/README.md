# Beta 小样本评测集 · 章玲

数据版本：`beta-zl-20261126`；结构版本：`1.0`。

5 份**自编**课件 PDF，共 20 页、20 个知识点、20 题：15 道可回答、2 道材料不足、3 道材料未涉及。不是教师原课件、真实用户测验或模型输出，不用于宣称真实课程普遍效果。纯文本同源副本便于审阅；应上传 PDF 而非假定服务端支持 TXT。

## 文件及字段

| 文件 | 用途 |
|---|---|
| `manifest.json` | 数据版本、来源、样本分布 |
| `documents.jsonl` | 每行一份课件：稳定 `doc` 标识、PDF 路径、SHA256、页内容、知识点与出处 |
| `qa.jsonl` | 每行一题，至少包含任务交接要求的 `id/doc/question/reference` |
| `sources/*.pdf` | 实际可上传的5份课件，每份4页，文内标注自编来源 |
| `sources/*.txt` | 人工核对用的同源文本副本 |
| `validate.py` | 离线校验、旧评测格式转换，标准库即可运行 |
| `test_dataset.py` | 校验与导出工具的行为测试，不改业务测试目录 |

QA 扩展字段：`expected_status` 为 `answerable/insufficient/not_covered`；`reference_claims` 为标准答案的可拆分要点（用于上下文召回率分母）；`evidence` 包含 `page_num/quote`；`expected_keywords` 为旧脚本辅助判定（外层 AND、内层同义词 OR）；`rubric` 为语义判定规则。`doc` 是数据集稳定标识，**不是数据库 doc_id**，须在上传后映射。

## 已可运行的命令

从仓库根目录执行（不要在 `eval_cases` 内再重复路径）：

```powershell
python scripts/eval_cases/validate.py
python -m unittest discover -s scripts/eval_cases -p "test_*.py" -v
```

校验失败返回退出码1；成功返回0。检查样本计数、唯一ID、材料哈希、页码、引文、标准答案结构与材料映射。离线校验不连接数据库，不需要 API key，不产生准确率或 LLM 裁判分数。

## 新版评测脚本接入（交陈瑀涵）

目标命令是 `python scripts/eval_agent.py --cases scripts/eval_cases -q`。当前提供的 1.2.0 脚本尚无这三个参数；本提交不替换其主责文件。接入时：

1. 读取 `qa.jsonl` 与 `documents.jsonl`，以 `doc` 加载相应材料。上传或导入后保存实际 doc_id 的映射，限定每题只检索对应材料，避免跨课件污染。
2. 保存系统真实答案、**检索实际返回的上下文**及出处。`evidence` 是参考标注，不能塞给被测模型或冒充检索结果；`reference` 只能给裁判，不能泄漏到被测输入。
3. 按 [评测口径](../../docs/评测口径.md) 并列输出旧关键词判定、faithfulness、context recall、拒答结果与有效分母；调用失败记录 error，不能计作0分或通过。
4. 固定同一模型、输入范围、检索设置与预算，保存版本、参数、时间及逐题记录。LLM 裁判按计划使用 DeepSeek，temperature=0，逐条0/1附理由。

`expected_status` 是评测标签，不要求业务接口新增同名字段。若当前接口仅有 `insufficient` 布尔值，材料不足和未涉及都可映射为拒答，但两种语义须结合真实答案文案判定并保留原始响应。

## 兼容旧脚本（可选，局限必须同时报告）

上传5份 PDF 后，自己新建 `doc-map.local.json`，填入各次上传接口返回的真实 doc_id，例如以下仅展示格式，不能照搬数字：

```json
{"se-testing":101,"db-transactions":102,"network-http":103,"algorithms":104,"math-derivative":105}
```

```powershell
python scripts/eval_cases/validate.py --export-legacy output/eval-legacy --doc-map doc-map.local.json
```

输出每份课件一个参考 CSV（4个知识点）和一个 QA JSON（3道可答题）。旧脚本不具备三态语义评测，因此**明确排除5道拒答题**，不可声称测了20题。

以软件测试材料为例：先登录上传该 PDF、发起整理并拿到真实 session_id，然后将下面 `123` 替换为该 session_id：

```powershell
python scripts/eval_agent.py --session-id 123 --reference-csv output/eval-legacy/se-testing.reference.csv --qa-file output/eval-legacy/se-testing.qa.json --output output/eval-legacy/se-testing.result.json
```

逐份运行，旧知识点覆盖率参考分母每份为4，总计20；旧关键词 QA 可答题分母总计15。不能给旧脚本传20题JSONL（它要求JSON数组）、不能把真实用户ID和密钥放入提交。若本地数据库不存在上传/整理数据，以上业务评测不可直接执行。

## 审阅及扩充

改材料后同步 PDF、TXT、documents 页码与哈希及 QA。校验工具会识别大部分结构性漂移；对 PDF 视觉、原文含义与标注合理性仍需人工复核。未来用真实课程材料扩充时，另建数据版本，记录授权来源及抽样方式，不静默改成“真实课件”。
