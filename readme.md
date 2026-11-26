# course-note-agent · Beta v1.3.0 文档准备版

大学生课程课件笔记整理与知识梳理 Agent，团队：天生一队。

**状态（2026-11-26）：v1.3.0 是本轮目标版本，本提交仅交付章玲负责的评测集与文档，不代表 Beta 已集成、已上线或全量测试通过。**
本版源码校对基线更新为补充包中的 `99ea0cc` 快照；其 `VERSION` 仍为1.2.0，已包含Beta地基改动，不代表完整Beta已发布。发布状态以集成后的 `VERSION`、`GET /api/meta`、发布标签与测试记录为准。

## 产品与本轮范围

基于用户上传的课程材料生成结构化笔记、重点清单，提供原文证据、材料内问答、导出，以及自测—错题—导图学习闭环。Agent 采用分阶段流水线；引文匹配只能核验出处，不能保证所有事实、推理均正确。

| 模块 | 本提交能核验的状态 |
|---|---|
| 1.2.0 自测、错题本、思维导图 | 基线包已包含代码；本提交未重新执行线上验收 |
| K1 五章复习包与 Word 导出 | v1.3.0 集成目标，等待模块交付与实测 |
| K2 考前计划、K4 到期复习队列 | v1.3.0 集成目标，排期需校验约束 |
| K3 出处抽屉、K5 执行轨迹 | v1.3.0 集成目标，按实际事件渲染轨迹 |
| 5 份自编课件、20 题评测集及校验工具 | 本提交交付，可离线校验，无需模型密钥 |

## 本地启动与升级

Python 3.12；在项目根目录操作，先根据 `.env.example` 建立本地配置，不提交密钥。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -c "from app.db.conn import init_databases; init_databases()"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

老库升级不要使用 `--reset`。v1.3.0 的迁移 003 与 `fsrs==6.3.3` 由徐张睿合入；本提交不修改依赖、迁移、`VERSION` 或业务代码。访问本地 `http://127.0.0.1:8000`；团队提供的线上入口为 `http://47.114.55.115:8000`，本提交未核验其运行版本。前端单独开发步骤见 [Alpha 归档](docs/历史说明/README-Alpha归档.md)。

## 评测与测试

```powershell
python scripts/eval_cases/validate.py
python -m unittest discover -s scripts/eval_cases -p "test_*.py" -v
```

以上只校验数据完整性与工具行为，不调用模型、不产生产品分数。完整评测口径见 [评测口径](docs/评测口径.md)，数据接入见 [评测集说明](scripts/eval_cases/README.md)。

陈瑀涵交付新版脚本后，联调目标命令为 `python scripts/eval_agent.py --cases scripts/eval_cases -q`。提供的基线脚本目前不支持 `--cases` / `--limit` / `-q`，**不能把目标命令记为已通过**。可先使用数据工具导出旧脚本的 CSV / QA 输入，具体限制见数据说明。

测试条数：最新 v1.3 交接汇总记录为 **58 → 61**（交接方报告，本提交未复测）；封板目标约 73，最终只引用封板实际报告。数据校验用例不与业务 pytest 用例混加。

## 文档与提交

- [CHANGELOG](CHANGELOG.md)：保留历史版本，新版放 Unreleased，实测发布后再移到 1.3.0。
- [契约校对版](docs/契约-v1.3.md)：已收到冻结原文并对照99ea0cc快照逐段校对；只修正一处示例数值并附差异说明，冻结接口未变。
- [提交交接单](docs/章玲-Beta交接单.md)：改动范围、验证、回滚与待办。

## 已知限制

小样本自编材料不代表真实课程效果；没有人工双评。LLM 裁判存在偏差，temperature=0 也不保证完全可复现。向量检索默认关闭；扫描件识别依赖 OCR 环境，不把未配置功能写成已支持。所有公开演示数字须附样本、分母、运行记录；不公开个人密钥。
