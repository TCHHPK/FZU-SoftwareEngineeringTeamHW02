"""生成《徐张睿 v1.3 交接文件》Word 文档。

内容：交付范围 / 已完成清单与证据 / 新增工具用法 / 12.02-12.03 操作手册 /
     未完成与等谁 / 交接单五项 / 本次发现的两个坑。
"""

from __future__ import annotations

import time
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parents[1] / "交接文件-徐张睿-v1.3.md"
DOCX = Path(__file__).resolve().parents[1] / "交接文件-徐张睿-v1.3.docx"

GREY = RGBColor(0x66, 0x66, 0x66)
BLUE = RGBColor(0x1F, 0x4E, 0x79)
GREEN = RGBColor(0x1E, 0x7A, 0x34)
AMBER = RGBColor(0xB0, 0x60, 0x00)
TAB = {"n": 0}


def set_font(run, *, name="宋体", size=10.5, bold=False, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), name)


def setup(doc):
    st = doc.styles["Normal"]
    st.font.name = "宋体"
    st.font.size = Pt(10.5)
    st.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
    st.paragraph_format.line_spacing = 1.3
    for s in doc.sections:
        s.top_margin = Cm(1.8)
        s.bottom_margin = Cm(1.8)
        s.left_margin = Cm(2.0)
        s.right_margin = Cm(2.0)


def title(doc, text, sub=""):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(text), name="微软雅黑", size=19, bold=True)
    if sub:
        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(p2.add_run(sub), name="微软雅黑", size=9.5, color=GREY)


def h1(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    set_font(p.add_run(text), name="微软雅黑", size=13.5, bold=True, color=BLUE)


def body(doc, text, *, size=10, color=None, bold=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    set_font(p.add_run(text), size=size, color=color, bold=bold)


def bullets(doc, items, *, size=9.8):
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(1)
        set_font(p.add_run(item), size=size)


def _shade(cell, fill="EDF3F8"):
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc.append(shd)


def table(doc, headers, rows, widths=None, *, size=8.6, caption=""):
    if caption:
        TAB["n"] += 1
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(5)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        set_font(p.add_run(f"表 {TAB['n']}　{caption}"), name="微软雅黑", size=8.5,
                 bold=True, color=GREY)
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        set_font(c.paragraphs[0].add_run(h), name="微软雅黑", size=size + 0.3, bold=True)
        _shade(c)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            para = cells[i].paragraphs[0]
            para.paragraph_format.space_after = Pt(0)
            color = GREEN if str(v).startswith("OK") else (AMBER if str(v).startswith("!") else None)
            for j, chunk in enumerate(str(v).split("\n")):
                if j:
                    para = cells[i].add_paragraph()
                    para.paragraph_format.space_after = Pt(0)
                set_font(para.add_run(chunk), size=size, color=color)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)


def code_block(doc, text: str, *, size=7.8):
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    cell = t.rows[0].cells[0]
    _shade(cell, "F5F7FA")
    cell.text = ""
    for i, line in enumerate(text.rstrip("\n").split("\n")):
        para = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        para.paragraph_format.space_after = Pt(0)
        para.paragraph_format.line_spacing = 1.0
        set_font(para.add_run(line), name="Consolas", size=size)


DELIVERED = [
    ("A30 状态白名单",
     "quiz.submit_test：仅 ready 判分；graded 幂等返回；draft/failed/submitted → 409 + 中文原因",
     "tests/test_self_test.py 用例 + 线上实测 422→409 路径"),
    ("A32 题数校验",
     "不再用实际条数覆盖 question_count；响应新增 target_count / actual_count / shortfall",
     "新增用例断言 target=5 而 actual<5 时 shortfall=True"),
    ("A33 并发判分",
     "conn.transaction 改 BEGIN IMMEDIATE；判分前 WHERE status='ready' 抢占并校验影响行数",
     "两线程并发用例：错题 wrong_count 恒为 1，两次 score 一致"),
    ("迁移 003",
     "wrong_questions 六字段（PRAGMA 守卫）+ session_traces 表 + 3 个索引",
     "scripts/verify_migration_003.py：造 v1.2 老库→升级→校验→再升级，两轮幂等"),
    ("契约文档",
     "docs/契约-v1.3.md：6 端点 + 2 表 + 鉴权 + 错误码 + 空章规则 + 路由顺序坑",
     "scripts/check_contract.py 校验契约与代码一致"),
    ("开关与依赖",
     "ENABLE_REVIEW_PACK/PLAN/WRONG_SCHEDULE 暴露到 /api/meta；requirements 锁 fsrs==6.3.3",
     "线上 /api/meta 已见三项；本地装 fsrs 6.3.3 成功"),
    ("路由登记",
     "router.py 可选导入 routes_review（模块未到位不阻塞启动）",
     "队友模块一到，重启即自动挂载，无需再改本文件"),
]

TOOLS = [
    ("scripts/gate.py", "一键门禁：pytest → e2e → 学习闭环 → 契约一致性",
     "python scripts/gate.py", "16 秒跑完，提交 PR 前必跑"),
    ("scripts/check_contract.py", "契约 vs 代码：6 端点实现进度、字段承诺、路由遮蔽",
     "python scripts/check_contract.py [--strict]", "封板用 --strict，要求 6/6"),
    ("scripts/premerge_check.py", "预合并检查：分支有没有改别人的文件",
     "python scripts/premerge_check.py --branch <分支> --as 姓名", "已实测能抓出越界"),
    ("scripts/seed_demo.py", "造发布会演示数据（账号+课件+任务+错题+导图）",
     "python scripts/seed_demo.py --base <线上> --username verify_37777bd6", "占位实现本地已跑通"),
    ("scripts/verify_release.py", "12.03 上线核验八项（含三条缺陷回归与性能）",
     "python scripts/verify_release.py --expect v1.3 --full --username ... ", "对线上已跑过 v1.2 基线"),
    ("scripts/verify_migration_003.py", "老库升级验证（造老库→升级→校验）",
     "python scripts/verify_migration_003.py", "已通过"),
    ("scripts/deploy_remote.py（加固）", "部署增加：迁移后字段校验、服务未起自动回滚",
     "python scripts/deploy_remote.py", "备份 83 MB 已实测"),
]

MANUAL_1202 = [
    ("上午", "各人交 PR 与交接单；用 premerge_check.py 逐个查越界",
     "python scripts/premerge_check.py --branch <分支> --as <姓名>"),
    ("下午", "跑门禁与契约检查，把「6 端点」当看板盯进度",
     "python scripts/gate.py && python scripts/check_contract.py"),
    ("18:00", "封板：PR 全部开完；之后只允许改冲突与阻断缺陷", "—"),
    ("20:00", "预合并：按文件归属合，冲突逐个找主责确认", "git merge --no-ff <分支>"),
    ("22:00", "合并窗口关闭；main 上跑一次 gate --release", "python scripts/gate.py --release"),
]

MANUAL_1203 = [
    ("上午", "部署：备份→上传→迁移→校验→重启→健康检查",
     "python scripts/deploy_remote.py"),
    ("上午", "迁移后确认六字段与 trace 表（脚本已内置）", "看输出 [7.5/9]"),
    ("下午", "造演示数据（预置账号、课件、错题、导图）",
     "python scripts/seed_demo.py --base http://47.114.55.115:8000 --username verify_37777bd6"),
    ("下午", "跑上线核验八项，全绿才算上线完成",
     "python scripts/verify_release.py --expect v1.3 --full --username verify_37777bd6 --password ***"),
    ("22:00", "版本冻结；打 tag v1.3.0（章玲改 CHANGELOG 后）", "git tag -a v1.3.0 -m 'v1.3.0' && git push --tags"),
]

PITS_FOUND = [
    ("路由遮蔽（实测）",
     "GET /api/wrong-questions/due 会先命中 /api/wrong-questions/{wrong_id}，"
     "登录后返回 422（Input should be a valid integer）。",
     "新路由必须声明在 /{wrong_id} 之前；check_contract.py 已加自动检测。"),
    ("SPA 回退误判（自查发现）",
     "线上访问不存在的 GET /api/xxx 会返回 200 + HTML（前端路由回退），"
     "容易被当成“接口已上线”。",
     "核验脚本改为看 Content-Type 与鉴权状态：只有 401/403/422 才算端点已注册。"),
]

PENDING = [
    ("routes_review 正式登记", "等沈文驰交 app/api/routes_review.py", "11.28"),
    ("api_io 五组模型", "等沈文驰写入（C5 模型先行）", "11.26 12:00"),
    ("trace 落库与端点", "等陈瑀涵在 ProgressReporter 写事件", "11.29"),
    ("自测页 409 与 shortfall 处理", "等陈佳慧改 SelfTestView", "11.27"),
    ("测试用例补充到 76 条", "等张佩琪补 15 条", "每日"),
    ("CHANGELOG / README 版本", "等章玲收口（docs 归她）", "12.01"),
    ("向量闸门判定", "11.30 按延迟实测决定是否接入", "11.30"),
]


def build() -> Document:
    doc = Document()
    setup(doc)
    title(doc, "v1.3 交接文件 · 徐张睿",
          "后端地基 / 集成工具 / 上线准备 ｜ 2026-11-24 ｜ 分支 feature/backend-core-xzr（已合 main）")

    h1(doc, "一、这次交付了什么")
    body(doc, "分三块：① 三条遗留缺陷修复与迁移 003；② 为集成和上线准备的一整套工具脚本；"
              "③ 契约文档与交接材料。已完成并合入 main（PR #4 / merge 2766057）。")

    table(doc, ["交付项", "做了什么", "证据"], [[a, b, c] for a, b, c in DELIVERED],
          widths=[3.2, 8.6, 5.4], caption="已完成清单")

    h1(doc, "二、新增的七个工具（都能直接跑）")
    table(doc, ["脚本", "用途", "怎么跑", "状态"], [[a, b, c, d] for a, b, c, d in TOOLS],
          widths=[4.4, 5.6, 5.4, 3.0], caption="工具清单")

    h1(doc, "三、12.02 封板当天怎么操作")
    table(doc, ["时间", "动作", "命令"], [[a, b, c] for a, b, c in MANUAL_1202],
          widths=[2.0, 8.4, 7.2], caption="12.02 操作手册")

    h1(doc, "四、12.03 上线当天怎么操作")
    table(doc, ["时间", "动作", "命令"], [[a, b, c] for a, b, c in MANUAL_1203],
          widths=[2.0, 8.4, 7.2], caption="12.03 操作手册")

    h1(doc, "五、本次发现并修掉的两个坑")
    table(doc, ["坑", "现象", "处理"], [[a, b, c] for a, b, c in PITS_FOUND],
          widths=[3.4, 8.0, 6.0], caption="值得写进博客的两个细节")

    h1(doc, "六、还没做完的（明确等谁）")
    table(doc, ["事项", "卡在谁那里", "时间"], [[a, b, c] for a, b, c in PENDING],
          widths=[6.4, 7.6, 3.2], caption="未完成项")

    h1(doc, "七、交接单五项（PR #4 已同稿）")
    body(doc, "改动清单", bold=True, size=9.8)
    bullets(doc, [
        "新增：app/db/migrations/003_review_plan.sql、docs/契约-v1.3.md、"
        "scripts/{gate,check_contract,premerge_check,seed_demo,verify_release,verify_migration_003}.py",
        "修改：app/services/quiz.py（A30/A32/A33）、app/db/conn.py（BEGIN IMMEDIATE + 六列）、"
        "app/core/config.py（三开关）、app/api/router.py（可选导入）、requirements.txt（fsrs）、"
        "tests/test_self_test.py（+3 组用例）",
    ])
    body(doc, "影响面", bold=True, size=9.8)
    bullets(doc, [
        "交卷在 draft/failed 时由 200 改 409，前端需处理 e.response.status；",
        "取卷新增 target_count/actual_count/shortfall，question_count 语义固定为 target；",
        "数据库新增 1 表 3 索引、wrong_questions 加 6 列，老库可原地升级；",
        "/api/meta 的 features 多三项。",
    ])
    body(doc, "自测证据", bold=True, size=9.8)
    code_block(doc, """python -m pytest -q                      -> 61 项通过
python scripts/e2e_smoke.py              -> 端到端通过
python scripts/smoke_learning_loop.py    -> 学习闭环通过
python scripts/verify_migration_003.py   -> 老库升级两轮幂等通过
python scripts/gate.py                   -> 四条门禁 16s 全过
python scripts/check_contract.py         -> 字段承诺全落实，6 端点待交付
python scripts/verify_release.py --base http://47.114.55.115:8000 --expect v1.2
                                         -> 15 项通过（v1.3 端点正确判为未注册）""")
    body(doc, "回滚方式", bold=True, size=9.8)
    bullets(doc, [
        "代码：单独 revert PR #4，行为回到 v1.2；迁移不可逆，但六个字段与新表留着无害。",
        "数据库：删 session_traces 与两个索引即可；六字段保留。",
        "fsrs：从 requirements 移除依赖；调度字段回默认值，旧薄弱度排序仍可用。",
        "部署：deploy_remote.py 会先备份到 /root/backup-<时间戳>.tar.gz，"
        "服务未起会自动还原（本次已内置）。",
    ])
    body(doc, "未完成项", bold=True, size=9.8)
    bullets(doc, ["见第六节；最紧的是 11.26 12:00 沈文驰的 api_io 五组模型——"
                  "在那之前 routes_review 只能保持可选导入。"])

    h1(doc, "八、留给人看的两句话")
    body(doc, "① 门禁别靠记忆：提交前跑 gate.py，它的顺序和 CI 一致，漏一步就会在 12.02 晚上补。",
         color=GREY)
    body(doc, "② 契约要当代码用：字段名或错误码变了先改契约，再改代码，"
              "否则 11 个人各写一套，合并那天一定对不上。", color=GREY)
    return doc


def build_md() -> str:
    lines = ["# v1.3 交接文件 · 徐张睿", "",
             "后端地基 / 集成工具 / 上线准备 ｜ 2026-11-24 ｜ 已合入 main（PR #4 / merge 2766057）", "",
             "## 一、已完成", "", "| 交付项 | 做了什么 | 证据 |", "| --- | --- | --- |"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in DELIVERED]
    lines += ["", "## 二、新增工具", "", "| 脚本 | 用途 | 怎么跑 |", "| --- | --- | --- |"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c, _ in TOOLS]
    lines += ["", "## 三、12.02 操作", ""]
    lines += [f"- {a}：{b}（`{c}`）" for a, b, c in MANUAL_1202]
    lines += ["", "## 四、12.03 操作", ""]
    lines += [f"- {a}：{b}（`{c}`）" for a, b, c in MANUAL_1203]
    lines += ["", "## 五、发现的两个坑", ""]
    lines += [f"- **{a}**：{b} → {c}" for a, b, c in PITS_FOUND]
    lines += ["", "## 六、未完成", ""]
    lines += [f"- {a}（等 {b}，{c}）" for a, b, c in PENDING]
    return "\n".join(lines) + "\n"


def main() -> int:
    doc = build()
    target = DOCX
    for attempt in range(3):
        try:
            doc.save(str(target))
            break
        except PermissionError:
            if attempt == 2:
                target = DOCX.with_name(f"交接文件-徐张睿-v1.3-{time.strftime('%H%M')}.docx")
                doc.save(str(target))
                break
            time.sleep(1)
    print(f"[ok] {target}（{target.stat().st_size / 1024:.0f} KB）")
    OUT.write_text(build_md(), encoding="utf-8")
    print(f"[ok] {OUT}（{OUT.stat().st_size / 1024:.0f} KB）")
    d = Document(str(target))
    print(f"[ok] 校验：{len(d.paragraphs)} 段落 / {len(d.tables)} 表格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
