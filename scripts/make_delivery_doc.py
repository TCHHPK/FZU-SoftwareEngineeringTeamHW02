"""生成《编程组交付清单与任务分派》Word 文档。

用法：python scripts/make_delivery_doc.py
产物：项目根目录的上一级「编程组交付清单与任务分派.docx」
"""

from __future__ import annotations

import time
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / "编程组交付清单与任务分派.docx"

GREY = RGBColor(0x66, 0x66, 0x66)
BLUE = RGBColor(0x1F, 0x4E, 0x79)
GREEN = RGBColor(0x1E, 0x7A, 0x34)
RED = RGBColor(0xC0, 0x00, 0x00)


# --------------------------------------------------------------------------
def set_font(run, *, name: str = "宋体", size: float = 10.5, bold: bool = False,
             color: RGBColor | None = None) -> None:
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def setup(doc: Document) -> None:
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    for s in doc.sections:
        s.top_margin = Cm(1.9)
        s.bottom_margin = Cm(1.9)
        s.left_margin = Cm(2.0)
        s.right_margin = Cm(2.0)


def title(doc, text, size=18):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(text), name="微软雅黑", size=size, bold=True)


def subtitle(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(text), name="微软雅黑", size=10, color=GREY)


def h1(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(15)
    p.paragraph_format.space_after = Pt(6)
    set_font(p.add_run(text), name="微软雅黑", size=14.5, bold=True, color=BLUE)


def h2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    set_font(p.add_run(text), name="微软雅黑", size=11.5, bold=True)


def body(doc, text, *, bold=False, color=None, indent=0.0, size=10.5):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    set_font(p.add_run(text), size=size, bold=bold, color=color)


def bullets(doc, items, *, size=10.5):
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(2)
        set_font(p.add_run(item), size=size)


def table(doc, headers, rows, widths=None, *, size=9.5):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, head in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        set_font(cell.paragraphs[0].add_run(head), name="微软雅黑", size=size + 0.5, bold=True)
    for row in rows:
        cells = t.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = ""
            para = cells[i].paragraphs[0]
            para.paragraph_format.space_after = Pt(1)
            color = None
            if value.startswith("❌"):
                color = RED
            elif value.startswith("✅"):
                color = GREEN
            elif value.startswith("⬜") or value.startswith("⚠"):
                color = RGBColor(0xB0, 0x60, 0x00)
            set_font(para.add_run(value), size=size, color=color)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def save_with_retry(doc: Document, target: Path) -> tuple[Path, str | None]:
    for attempt in range(3):
        try:
            doc.save(str(target))
            return target, None
        except PermissionError:
            if attempt < 2:
                time.sleep(1.0)
                continue
            stamp = time.strftime("%m%d-%H%M")
            fallback = target.with_name(f"{target.stem}-{stamp}{target.suffix}")
            doc.save(str(fallback))
            return fallback, (f"目标文件被占用（Word 正开着「{target.name}」）。"
                              f"已另存为「{fallback.name}」，请关闭 Word 后重新运行本脚本。")
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------
def build() -> Document:
    doc = Document()
    setup(doc)

    title(doc, "编程组交付清单与任务分派")
    subtitle(doc, "大学生课程课件笔记整理与知识梳理 Agent")

    body(doc, "项目：大学生课程课件笔记整理与知识梳理 Agent")
    body(doc, "编程小队：徐张睿（组长）、沈文驰、陈瑀涵、陈佳慧")
    p = doc.add_paragraph()
    set_font(p.add_run("线上地址：http://47.114.55.115:8000"), size=11, bold=True, color=GREEN)
    body(doc, "（已可外网访问；当前尚未配置模型密钥，只能上传解析、暂时生成不了笔记）", color=GREY)

    # ================= 支持格式 =================
    h1(doc, "支持的学习资料格式")
    body(doc, "系统不限定固定格式：任何格式只要接入一个提取器即可支持，"
              "下游的切块、检索、证据校验逻辑完全不用改。", color=GREY)
    table(doc, ["格式", "扩展名", "验证状态", "定位精度"], [
        ["PDF", ".pdf", "✅ 已用 10 份真实课件验证", "页码 + 章节"],
        ["PowerPoint", ".pptx", "🚧 只用生成的样例测过", "幻灯片序号 + 章节"],
        ["Word", ".docx", "🚧 只用生成的样例测过", "章节层级 + 段落"],
        ["纯文本", ".txt .text .log", "🚧 只用生成的样例测过", "分段"],
        ["Markdown", ".md .markdown", "🚧 只用生成的样例测过", "标题层级"],
        ["网页", ".html .htm", "🚧 只用生成的样例测过", "h1-h6 层级"],
        ["表格", ".csv", "🚧 只用生成的样例测过", "行号"],
        ["电子书", ".epub", "🚧 只用生成的样例测过", "章节文件"],
        ["图片", ".png .jpg .jpeg .webp", "⚠ 需配置 OCR 服务", "图片序号"],
        ["扫描版 PDF", "（整页为图片的 PDF）", "⚠ 需配置 OCR 服务", "原有页码"],
    ], widths=[2.6, 4.4, 5.4, 4.0])
    body(doc, "说明：已实现但只用样例验证过的格式，必须用真实文件再验一遍——"
              "真实文件的版式差异很大，自己造的样例证明不了老师手里的文件能读。", color=GREY)
    body(doc, "旧版 Office 格式（.doc / .ppt / .xls / .wps / .caj）会给出「请另存为」的"
              "明确提示，而不是笼统报错。", color=GREY)

    # ================= 一 =================
    h1(doc, "一、服务器与线上环境（已完成）")
    table(doc, ["项", "状态"], [
        ["云服务器", "阿里云 ECS，2核4G，Ubuntu 22.04，杭州地域，到期 2026/11/14"],
        ["代码部署", "已完成，位置 /root/course-note-agent"],
        ["Python", "3.12.15（独立虚拟环境）"],
        ["数据库", "storage/business.db（17 张表）+ storage/kb.db（领域知识库）"],
        ["服务守护", "systemd 服务 course-note-agent，开机自启 + 崩溃自动重启"],
        ["安全组", "已放行 8000（网站访问）与 22（远程登录）"],
        ["管理员账号", "admin / admin123 —— 首次登录后请立即修改"],
        ["外网验证", "http://47.114.55.115:8000/api/health 返回 {\"status\":\"ok\"}"],
    ], widths=[3.2, 13.2])

    body(doc, "常用维护命令（在服务器终端执行）：", bold=True)
    for cmd, desc in [
        ("systemctl status course-note-agent", "查看运行状态"),
        ("systemctl restart course-note-agent", "重启（修改 .env 后执行）"),
        ("tail -f /root/course-note-agent/logs/service.log", "查看实时日志"),
        ("journalctl -u course-note-agent -n 100", "查看服务日志最近 100 行"),
    ]:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.space_after = Pt(2)
        set_font(p.add_run(cmd), name="Consolas", size=9.5)
        set_font(p.add_run(f"    # {desc}"), size=9.5, color=GREY)

    # ================= 二 =================
    doc.add_page_break()
    h1(doc, "二、我要交付给队友的东西")

    h2(doc, "→ 给沈文驰（后端与数据）")
    table(doc, ["交付物", "位置", "说明"], [
        ["完整代码仓库", "course-note-agent.zip", "已部署到服务器，本地解压即可开发"],
        ["数据库结构", "app/db/schema.sql", "唯一建表来源；改字段要同步 schema 与 conn.py 的迁移表"],
        ["解析模块（已完成）", "app/services/parse.py", "支持 PDF / PPTX / DOCX / TXT / MD / HTML / CSV / EPUB；按文件头识别格式；含扫描件识别与章节继承"],
        ["入库模块（已完成）", "app/services/ingest.py", "解析结果落库并建立全文索引"],
        ["课件体检脚本", "scripts/inspect_materials.py", "批量检查课件能否解析，拿到新课件先用它"],
        ["解析自检", "python tests/test_parse.py", "17 项测试（含各种格式与异常文件），改完必须跑通"],
        ["服务器访问", "SSH root@47.114.55.115", "密码问徐张睿"],
    ], widths=[3.6, 4.8, 8.0])

    h2(doc, "→ 给陈瑀涵（Agent 与检索）")
    table(doc, ["交付物", "位置", "说明"], [
        ["Agent 管线骨架", "app/agents/pipeline.py", "接口已定稿；run_note_pipeline() 内有 6 步 TODO 注释，照着实现"],
        ["检索模块（已完成）", "app/services/query.py", "FTS5 + 二元组 + 覆盖率重排；已实现无关问题拦截，直接调用"],
        ["证据校验（已完成）", "query.quote_in_text()", "引文回查原文，查不到即丢弃"],
        ["模型客户端（已完成）", "app/services/llm.py", "多密钥轮换、重试、JSON 三重兜底，直接调用"],
        ["输出契约", "app/schemas/agent_io.py", "所有模型输出必须走这里，不要自建字典"],
        ["提示词目录", "app/agents/prompts/（待创建）", "建议按 extract / render_note / qa / self_eval 分文件"],
        ["真实课件", "10 份 PDF（见第五节）", "推荐首期使用 9_副本.pdf（第13章 构件级设计）"],
        ["参考知识点清单", "需求组提供，10/17 前", "用于计算知识点覆盖率，格式见第六节"],
        ["模型密钥", "徐张睿私聊发送", "服务器用主密钥；你本地开发请在同一账号下另建一个密钥"],
    ], widths=[3.6, 4.8, 8.0])

    h2(doc, "→ 给陈佳慧（前端）")
    table(doc, ["交付物", "位置", "说明"], [
        ["可视化接口文档", "http://47.114.55.115:8000/docs", "可在浏览器里直接点着试接口，无需等后端"],
        ["接口清单", "本文第四节", "方法、路径、用途一览"],
        ["响应字段定义", "app/schemas/api_io.py", "每个接口返回哪些字段，以这里为准"],
        ["统一响应格式", "{code, message, data}", "code=0 表示成功；错误码直接用 HTTP 状态码"],
        ["本地启动", "python -m scripts.init_db 后 uvicorn app.main:app --reload", "不依赖服务器也能开发"],
        ["功能开关", "GET /api/meta 的 features 字段", "未实现的入口按它隐藏，不要留半成品按钮"],
        ["测试账号", "线上自行注册", "管理员账号 admin / admin123"],
    ], widths=[3.6, 5.6, 7.2])

    h2(doc, "→ 给需求组（梁倩）")
    table(doc, ["交付物", "说明"], [
        ["课件体检结论", "见第五节：10 份中有 1 份不可用，需要替换"],
        ["待补材料（按格式各一份）",
         "系统现已支持 PDF / PPT / Word / 纯文本 / Markdown / 网页 / 电子书等格式。"
         "除 PDF 外都只用程序生成的样例验证过，需要每种格式各给一份真实文件"],
        ["待补数据", "参考知识点清单 25~30 条，模板见第六节"],
    ], widths=[4.0, 12.4])

    h2(doc, "→ 给答辩与博客组（章玲、庄剑钇）")
    table(doc, ["交付物", "时间", "说明"], [
        ["线上地址 + 测试账号 + 走查说明", "10/18", "供老师与助教检查"],
        ["评测数据（覆盖率、无依据率、问答正确率）", "10/19", "PPT 与博客的核心论据"],
        ["裸调用模型 vs 本系统管线对比结果", "10/21", "这是老师明确的评分项"],
        ["界面截图包（含移动端）", "10/21", "博客插图"],
    ], widths=[6.2, 2.0, 8.2])

    # ================= 三 =================
    doc.add_page_break()
    h1(doc, "三、每个人要完成的任务")

    h2(doc, "徐张睿（架构与交付）")
    table(doc, ["状态", "任务"], [
        ["✅", "代码骨架、数据库结构、统一模型客户端、登录鉴权、任务状态机、接口层"],
        ["✅", "服务器部署、systemd 守护、安全组放行、外网验证通过"],
        ["⬜", "拿到模型密钥，填进服务器 .env 并重启服务（当前生成不了笔记，就卡在这一步）"],
        ["⬜", "每日合并主干；main 分支只由你合并"],
        ["⬜", "10/18 前确认走查说明与测试账号，交给老师与助教"],
        ["⬜", "10/19 代码冻结，检查 README 完整性"],
    ], widths=[1.6, 14.8])

    h2(doc, "沈文驰（后端与数据）")
    table(doc, ["优先级", "任务", "依赖"], [
        ["高", "OP-04 笔记增量合并：新材料补充到已有笔记时按段落去重，用户改过的段落不被覆盖，产出变更摘要", "无"],
        ["高", "FR-06 导出完善：Markdown 与 LaTeX 模板，中文与公式不乱码", "无"],
        ["中", "解析边界测试补齐：加密 PDF、损坏文件、超页数、重复上传", "无"],
        ["中", "管理端 FR-08：公共资料上传与入库", "无"],
        ["低", "用 scripts/inspect_materials.py 对新课件体检并反馈给需求组", "新课件"],
        ["待验证", "PPTX / DOCX / HTML / EPUB 解析路径：只用程序生成的样例测过，尚未用真实文件验证", "需求组按格式各给一份"],
    ], widths=[1.8, 10.6, 4.0])

    h2(doc, "陈瑀涵（Agent 与检索）")
    table(doc, ["优先级", "任务", "依赖"], [
        ["高", "实现 run_note_pipeline()：逐块抽取 → 证据校验 → 归并去重 → 检索补全 → 生成笔记／重点／导图 → 加权自评", "模型密钥 + 真实课件"],
        ["高", "编写提示词库 app/agents/prompts/，版本化管理", "同上"],
        ["高", "FR-05 问答：接 prompts/qa.txt，证据不足时明确说明，不自由发挥", "同上"],
        ["中", "OP-06 质量自评：按 85% / 10% / 5% 加权，说明扣分位置", "同上"],
        ["中", "OP-01 例题整理、OP-05 考试范围复习", "同上"],
        ["高", "scripts/eval_agent.py：计算知识点覆盖率、无依据陈述比例、问答正确率", "参考知识点清单（10/17）"],
        ["中", "scripts/bench_compare.py：裸调用 vs 定制管线，同一份材料、同一套提示词", "参考知识点清单"],
    ], widths=[1.8, 10.6, 4.0])
    body(doc, "接入点提醒：管线只负责产出 NoteResult，落库由 pipeline._persist_result() 完成，不要自己写 SQL。",
         color=GREY, indent=0.4)

    h2(doc, "陈佳慧（前端）")
    table(doc, ["优先级", "任务", "依赖"], [
        ["高", "项目初始化（Vue 3 + Vite + Element Plus）、路由、布局", "无"],
        ["高", "登录 / 注册页", "无"],
        ["高", "上传页：拖拽、课程选择、进度展示", "无"],
        ["高", "结果页：结构化笔记 / 重点清单 / 文本思维导图 三个分区", "接口已就绪"],
        ["高", "出处角标组件：显示第 X 页或第 X 张幻灯片，点击查看原文片段", "接口已就绪"],
        ["中", "任务进度页：整理需 30~120 秒，必须有进度与阶段文案", "接口已就绪"],
        ["中", "问答页、历史列表与详情、导出按钮", "接口已就绪"],
        ["中", "异常态：上传失败、解析部分成功、任务失败、无权限、检索无结果、空列表", "答辩时很可能被问到"],
        ["低", "公式渲染（LaTeX）、移动端适配、截图包", "无"],
    ], widths=[1.8, 10.6, 4.0])

    # ================= 四 =================
    doc.add_page_break()
    h1(doc, "四、接口清单（前端对接用）")
    body(doc, "统一响应结构：{code, message, data}，code=0 表示成功。", color=GREY)
    table(doc, ["方法", "路径", "用途"], [
        ["GET", "/api/health", "健康检查"],
        ["GET", "/api/meta", "功能开关、上传限制、当前登录态、课程清单"],
        ["POST", "/api/auth/register  /login  /logout", "注册 / 登录 / 登出"],
        ["GET", "/api/auth/me", "当前用户"],
        ["POST", "/api/uploads", "上传课件（multipart：file + course_name）"],
        ["GET", "/api/uploads  /courses  /{doc_id}", "材料列表 / 课程清单 / 详情"],
        ["POST", "/api/sessions", "发起整理任务（202，返回 session_id）"],
        ["GET", "/api/sessions  /{id}  /{id}/result", "历史 / 轮询进度 / 取结果"],
        ["GET", "/api/sessions/{id}/export?fmt=md|tex", "导出 Markdown 或 LaTeX"],
        ["GET", "/api/sessions/{id}/chunks/search?q=", "检索调试，返回 confident / low_confidence / insufficient"],
        ["POST", "/api/chat/ask     GET /api/chat/history", "问答 / 问答历史"],
        ["POST/GET", "/api/admin/materials  /stats  /compare-records", "管理端：公共资料 / 运行概况 / 评测记录"],
    ], widths=[2.0, 7.2, 7.2])
    p = doc.add_paragraph()
    set_font(p.add_run("浏览器里可直接点着试："), size=10.5)
    set_font(p.add_run(" http://47.114.55.115:8000/docs"), size=10.5, bold=True, color=BLUE)

    # ================= 五 =================
    h1(doc, "五、课件体检结论（需求组请关注）")
    table(doc, ["文件", "页数", "每页均字数", "识别到的节", "结论"], [
        ["9_副本.pdf", "68", "139", "48", "✅ 首选，内容最密（第13章 构件级设计）"],
        ["6.pdf", "94", "140", "55", "✅ 可用"],
        ["7.pdf", "46", "124", "44", "✅ 可用"],
        ["5.pdf", "50", "118", "28", "✅ 可用"],
        ["4.pdf", "35", "105", "18", "✅ 可用"],
        ["10.pdf", "91", "86", "57", "✅ 可用（第14章 用户界面设计）"],
        ["8.pdf", "90", "79", "51", "✅ 可用（第13章 体系结构设计）"],
        ["3.pdf", "71", "62", "26", "⚠ 文本偏少，另有 1 页字体异常"],
        ["2.pdf", "67", "168", "0", "⚠ 24 页无文字层，约一半内容读不到"],
        ["1.pdf", "19", "79", "0", "❌ 11 页空页、结构识别为 0，建议替换"],
    ], widths=[2.4, 1.4, 2.2, 1.8, 8.6])

    body(doc, "建议首期范围：9_副本.pdf + 8.pdf（同属软件工程课程，内容连贯，文字密度高）。", bold=True)
    body(doc, "待需求组补充：", bold=True)
    bullets(doc, [
        "替换 1.pdf，或明确本期内不使用它",
        "补一份 .pptx 课件——把任意一章用 PowerPoint 另存为 pptx 即可，用于验证 PPT 解析路径",
        "说明每份课件对应的课程名（现有文件名是 1.pdf 至 10.pdf，系统里需要显示课程名）",
    ])

    # ================= 六 =================
    h1(doc, "六、参考知识点清单模板（需求组填写，10/17 前）")
    table(doc, ["知识点名称", "所属章节", "页码", "核心要点（2~5 条）", "重要度"], [
        ["（示例）构件与对象的区别", "第13章 构件级设计", "第 5 页",
         "构件是可部署单元；对象是运行时实例；构件通过接口对外提供服务", "高"],
        ["", "", "", "", ""],
        ["", "", "", "", ""],
        ["", "", "", "", ""],
        ["", "", "", "", ""],
    ], widths=[3.2, 3.0, 1.8, 7.0, 1.4])
    body(doc, "填写要求：", bold=True)
    bullets(doc, [
        "25~30 条，覆盖目标章节的主要内容",
        "每条都要能在课件里找到对应位置，页码必须准确",
        "这份清单是计算「知识点覆盖率」的唯一依据，直接决定「定制效果」这个评分项",
        "标注人应当是最熟悉该课程内容的人（需求组）；标注完成后由陈瑀涵写脚本自动比对，不需要人工核对",
    ])

    # ================= 七 =================
    h1(doc, "七、时间节点")
    table(doc, ["日期", "交付内容"], [
        ["10/15", "✅ 服务器上线；⬜ 模型密钥到位；⬜ 真实课件确认课程名"],
        ["10/16", "Agent 单章整理跑通：能出笔记、重点清单、文本导图，且每条带出处"],
        ["10/17", "前后端联调完成；参考知识点清单必须到位"],
        ["10/18", "问答、历史、导出、管理页完成；异常态补齐；对外走查说明与测试账号就绪"],
        ["10/19", "代码冻结并提交"],
        ["10/20 – 10/21", "缓冲：修缺陷、补可选项、评测与对比实验"],
        ["10/22 – 10/23", "PPT、演示彩排（至少两次全程，含断网兜底方案）"],
        ["10/24", "现场答辩"],
        ["10/25", "博客提交截止"],
    ], widths=[3.0, 13.4])

    doc.add_paragraph()
    body(doc, "制表：编程组　｜　依据：课程作业要求、组内需求文档（SRS V0.2）、"
              "知识库与提示词交付稿、课件体检结果", color=GREY)
    return doc


def main() -> int:
    doc = build()
    written, note = save_with_retry(doc, OUTPUT)
    print(f"[ok] 已生成：{written}")
    print(f"[ok] 文件大小：{written.stat().st_size:,} 字节")
    if note:
        print(f"[warn] {note}")
    check = Document(str(written))
    print(f"[ok] 校验：{len(check.paragraphs)} 个段落，{len(check.tables)} 张表格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
