> 由 2026-11-20 源码包归档，不能代表 Beta 当前完成情况。旧实现和早期统计仅作历史参考。

# course-note-agent

大学生课程课件笔记整理与知识梳理 Agent —— 编程组代码仓库。

上传课程课件（PDF / PPTX），系统基于课件原文与领域知识库生成**结构化笔记、重点清单、文本思维导图**，
每个知识点都带**原文出处**（章节 / 页码 / 幻灯片），支持材料范围内问答、例题整理、笔记增量合并与
Markdown / LaTeX 导出。所有输出严格基于课件原文，无依据的内容在入库前被**证据校验**拦截。

## 当前状态

| 模块 | 状态 |
|---|---|
| 数据库结构（business.db / kb.db，17 张表） | ✅ 已完成并验证 |
| Agent 输入输出契约（`app/schemas/agent_io.py`） | ✅ 已完成 |
| 统一 LLM 客户端（多 key 轮换 / 重试 / JSON 三重兜底） | ✅ 已完成 |
| 中文检索：FTS5 二元组 + 覆盖率重排（含无关问题拦截） | ✅ 已完成并验证 |
| 证据校验（引文回查原文） | ✅ 已完成并验证 |
| 解析与入库（PDF / PPTX → chunk，含扫描件识别与定位） | ✅ 已完成并验证 |
| HTTP 接口层（认证 / 上传 / 任务 / 结果 / 导出 / 问答 / 管理） | ✅ 已完成并验证 |
| Agent 管线（逐块抽取 → 归并 → 生成三件套） | 🚧 骨架已就位，等陈瑀涵接模型 |
| 前端页面 | 🚧 等陈佳慧（接口与 mock 已就绪） |

### 测试状态（全部不需要 API key）

| 命令 | 内容 | 结果 |
|---|---|---|
| `python tests/test_contracts.py` | 契约、检索、引文核验 | 6 项通过 |
| `python tests/test_parse.py` | 解析、切块、入库、异常文件 | 11 项通过 |
| `python tests/test_api.py` | 接口端到端、越权隔离、导出 | 10 项通过 |
| `python scripts/selftest_pipeline.py` | 主链路自检（生成真 PDF 走通） | 4 步通过 |
| `python scripts/e2e_smoke.py` | 完整业务流程走查（可作演示脚本底稿） | 7 步通过 |
| `python scripts/lint_sql_params.py` | SQL 占位符与参数数量一致性静态检查 | 35 条通过 |

## 快速开始

```bash
# 1. 依赖（Python 3.12）
python -m pip install -r requirements.txt

# 2. 配置：复制 .env.example 为 .env，填入 LLM_API_KEYS 等
copy .env.example .env

# 3. 建库（--reset 会清空重来，开发期用）
python -m scripts.init_db --reset

# 4. 自检：不需要 API key，验证解析→索引→检索→出处核对整条链路
python scripts/selftest_pipeline.py

# 5. 契约测试
python tests/test_contracts.py
```

管理员账号由 `scripts/init_db.py` 生成，默认 `admin / admin123`，上线前必须改。

## 目录结构

```
app/
├─ core/       config 与安全（口令哈希：pbkdf2_sha256）
├─ db/         schema.sql（唯一建表来源）、连接管理
├─ schemas/    agent_io.py —— 后端 / Agent / 前端的接口契约
├─ services/   parse 解析 · query 检索 · llm 模型调用 · retriever / exporter / merge
├─ agents/     pipeline 编排 · prompts 提示词库 · tools 工具 · verifier 证据校验
└─ api/        auth / upload / sessions / notes / chat / export / admin
scripts/       init_db 建库 · selftest_pipeline 链路自检 · eval_agent 评测 · bench_compare 对比实验
tests/         契约与边界测试
```

## 关键设计决定（答辩要点）

1. **检索用 SQLite FTS5 + 二元组，不用向量库。** 单门课程几百个 chunk 的量级下 BM25 足够，
   省掉一个需要运维和解释的组件。向量召回保留为 `.env` 开关（`ENABLE_VECTOR`）。
2. **FTS 粗召回之后必须重排。** FTS5 的 OR 查询会因为命中「力学」而把导数章节召回给
   「量子力学的不确定性原理」，所以用二元组覆盖率重排并设阈值，让无关问题返回空 ——
   这是「材料未涉及就如实回答」的技术前提（见 `tests/test_contracts.py` 的回归用例）。
3. **每个知识点必须绑定可核验的原文引文。** `quote` 要求在原文中找到连续片段（容忍标点差异，
   不接受同义改写），否则整个知识点被丢弃并计入 `dropped_items`。这条把需求里的
   「无依据陈述比例」变成了可计算的指标。
4. **业务库与知识库物理分离**（`storage/business.db` 与 `storage/kb.db`），对应 SRS 3.4。
5. **一个块失败不拖垮整单任务**：LLM 调用失败按块跳过并记日志，任务状态转为 `partial`。

## 已完成事项

- [x] 数据库结构与初始化脚本（含字段增量迁移）
- [x] Agent 输入输出契约（Pydantic 模型 + 自评权重合成）
- [x] LLM 客户端（多 key、指数退避、JSON 三重兜底）
- [x] 中文检索与重排、引文核验
- [x] 课件解析与入库（PDF/PPTX、章节跨页继承、扫描件识别、失败不崩）
- [x] HTTP 接口层全部端点 + 越权隔离 + 导出渲染
- [x] 六套自检脚本（共 38 项断言）全绿
- [x] Agent 管线已集成；模型可用性取决于运行环境配置
- [x] 前端页面已接入真实接口（详见 1.2.0 发布日志）
- [ ] 部署与评测报告

## 开发过程中被自检抓到的真实缺陷（值得写进博客）

| 缺陷 | 影响 | 修法 |
|---|---|---|
| FTS 的 OR 粗召回会把「量子力学」答成导数章节 | 系统会拿无关材料编造答案 | 二元组覆盖率重排 + 阈值过滤 |
| 口语化提问被疑问词稀释（「可导和连续是什么关系」覆盖率仅 0.30） | 正常提问检索不到 | 检索前剔除疑问词与单字虚词 |
| `normalize_paragraphs` 把 `a\n\n\nb` 并成 `ab` | 页码、符号被粘进正文 | 改为显式的完整句/片段判定 |
| **章节上下文未跨页继承** | 每个小节各自成章，一份课件只产出 1 个条目 | 页间传递章节状态 |
| 「第1章 函数与极限」带空格的章标题识别失败 | 整份课件章节归属全错 | 编号规律容忍空格/全角空格 |
| **SQL 占位符与参数数量不一致（3 处）** | 材料列表、课程清单、问答历史接口直接 500 | 改用命名参数 + 新增静态检查脚本 |
| LaTeX 导出中文文件名触发 `UnicodeEncodeError` | 导出接口 500 | 按 RFC 5987 输出 `filename*` |
| 占位实现的提示语被当成数据质量告警 | 任务状态错误地显示「部分成功」 | 区分 `notices` 与 `warnings` |
| 出处展示的是存储哈希文件名 | 学生看到的出处对不上自己上传的文件 | 新增 `display_name` 保留原始文件名 |

## 接口一览（前端按此对接）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/meta` | 功能开关、上传限制、当前登录态、课程清单 |
| POST | `/api/auth/register` `/login` `/logout` | 注册 / 登录 / 登出（Cookie 与 Bearer 都支持） |
| GET | `/api/auth/me` | 当前用户 |
| POST | `/api/uploads` | 上传课件并解析（multipart：`file`、`course_name`） |
| GET | `/api/uploads` `/courses` `/{doc_id}` | 材料列表 / 课程清单 / 详情 |
| POST | `/api/sessions` | 发起整理任务（202，返回 `session_id`） |
| GET | `/api/sessions` `/{id}` `/{id}/result` | 历史 / 轮询进度 / 取结果 |
| GET | `/api/sessions/{id}/export?fmt=md\|tex` | 导出 Markdown / LaTeX |
| GET | `/api/sessions/{id}/chunks/search?q=` | 检索调试（返回 `confident` / `low_confidence` / `insufficient`） |
| POST | `/api/chat/ask` `/history` | 材料范围内问答 / 问答历史 |
| POST/GET | `/api/admin/materials` `/stats` `/compare-records` | 公共资料维护 / 运行概况 / 评测记录 |

统一响应结构：`{code, message, data}`，`code=0` 为成功；错误码直接用 HTTP 状态码。
交互文档：启动后在 `/docs` 查看（前端联调时很有用）。

## 已知需要人工确认的事项

以下信息我无法从代码或现有材料推断，一律留空，**不要凭空填写**：

| 事项 | 位置 | 状态 |
|---|---|---|
| 实际演示课程、章节与课件文件 | 验收用例 AT-03 | 【待确认】 |
| 人工标注的参考知识点清单（25~30 条） | 附录 B.1 | 【待确认】，10/17 前需提供 |
| LLM 供应商、模型名与额度 | `.env` | 【待确认】 |
| 服务器地址与域名 | 部署配置 | 【待确认】 |
| 调研样本、用户数量、经验差异 | SRS 2.3 / A.1 | 【待确认】 |
| 项目组名称、审核人及日期 | SRS 文档信息 | 【待确认】 |

## 环境变量

见 `.env.example`。功能开关（`ENABLE_EXAMPLE` / `ENABLE_NOTE_MERGE` / `ENABLE_EXAM_SCOPE` /
`ENABLE_QUALITY_EVAL` / `ENABLE_FORMULA_OCR`）用于控制可选功能的入口显隐，
**未实现的功能一律置 0，不要在界面上留半成品入口**。
