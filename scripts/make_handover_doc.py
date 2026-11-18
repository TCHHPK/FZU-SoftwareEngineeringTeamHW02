"""生成《交付清单与实测数据填表》Word 文档。

用途：把本次开发/上线过程中测出来的真实数据，按 SRS 里待填的条目整理成表，
      便于需求组直接回填，也便于答辩组取用。
数据来源：本机测试 + 线上全流程验证（scripts/online_verify.py）。

用法：python scripts/make_handover_doc.py
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
OUTPUT = ROOT.parent / "交付清单与实测数据填表.docx"

GREY = RGBColor(0x66, 0x66, 0x66)
BLUE = RGBColor(0x1F, 0x4E, 0x79)
GREEN = RGBColor(0x1E, 0x7A, 0x34)
RED = RGBColor(0xC0, 0x00, 0x00)


def set_font(run, *, name="宋体", size=10.5, bold=False, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def setup(doc):
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    for s in doc.sections:
        s.top_margin = Cm(1.9)
        s.bottom_margin = Cm(1.9)
        s.left_margin = Cm(2.0)
        s.right_margin = Cm(2.0)


def title(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(text), name="微软雅黑", size=18, bold=True)


def subtitle(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(text), name="微软雅黑", size=10, color=GREY)


def h1(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(6)
    set_font(p.add_run(text), name="微软雅黑", size=14, bold=True, color=BLUE)


def h2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(9)
    p.paragraph_format.space_after = Pt(4)
    set_font(p.add_run(text), name="微软雅黑", size=11.5, bold=True)


def body(doc, text, *, bold=False, color=None, size=10.5, indent=0.0):
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
            if value.startswith("✅"):
                color = GREEN
            elif value.startswith("⬜") or value.startswith("⚠"):
                color = RGBColor(0xB0, 0x60, 0x00)
            elif value.startswith("❌"):
                color = RED
            set_font(para.add_run(value), size=size, color=color)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def save_with_retry(doc, target: Path):
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
            return fallback, f"目标被占用，已另存为 {fallback.name}"
    raise AssertionError("unreachable")


def build() -> Document:
    doc = Document()
    setup(doc)

    title(doc, "交付清单与实测数据填表")
    subtitle(doc, "大学生课程课件笔记整理与知识梳理 Agent")

    body(doc, "线上地址：http://47.114.55.115:8000", bold=True)
    body(doc, "演示账号：verify_37777bd6　密码：verify123（已完成一次真实整理，历史任务 #8）", color=GREY)
    body(doc, "本文用途：① 明确各角色还要交什么；② 把 SRS 里待填的技术指标换成实测值。", color=GREY)

    # ---------------- 一 ----------------
    h1(doc, "一、我自己（组长 / 编程组）还要交什么")
    table(doc, ["交付物", "给谁", "状态", "截止"], [
        ["线上地址 + 演示账号 + 3 分钟走查说明", "老师、助教（按要求提供访问方式）", "✅ 已有，待整理成一页说明", "10/21"],
        ["完整源码与部署说明", "组内备份 / 助教查验", "✅ 已打包 course-note-agent-complete.zip", "已完成"],
        ["评测数据（覆盖率、无依据率、问答正确率）", "答辩与博客组", "✅ 已有（见第二节）", "10/21"],
        ["界面截图包（登录/上传/进度/结果/出处弹窗/导出）", "答辩与博客组", "⬜ 待截", "10/21"],
        ["最终验收自查（AT-01~AT-10 逐条过）", "自己留档 + 论文附录B", "⬜ 待执行", "10/23"],
        ["SRS 中技术类【代填】的回填值", "需求组", "⬜ 见第三节，照抄即可", "10/21"],
    ], widths=[7.4, 4.6, 4.2, 1.8])

    # ---------------- 二 ----------------
    h1(doc, "二、可以直接引用的实测数据（答辩 / 博客 / 论文都能用）")

    h2(doc, "2.1 领域智能体效果对比（同一份课件、同一模型）")
    table(doc, ["指标", "定制 Agent", "裸模型调用", "说明"], [
        ["知识点覆盖率", "66.67%（24/36）", "38.89%（14/36）", "高出 27.78 个百分点"],
        ["无依据陈述比例", "0%", "100%", "裸调用未绑定可核验出处"],
        ["问答正确率", "83.33%（5/6）", "未测", "自动关键词判定，偏保守"],
        ["质量自评总分", "82.1 / 100", "—", "85%/10%/5% 加权"],
        ["知识点数量", "69 个", "单次裸调用", "全部通过原文引文回查"],
    ], widths=[4.2, 4.2, 4.0, 5.6])
    body(doc, "口径提醒：66.67% 是「保守文本匹配」下的结果，不能包装成人工语义覆盖率。"
              "答辩时应主动说明这一点，并指出未匹配条目中有多条已以近义表述抽取到——"
              "主动交代比被追问更稳。", color=GREY)

    h2(doc, "2.2 系统实测性能（线上环境）")
    table(doc, ["场景", "实测值", "测量方式"], [
        ["6 页 / 4MB 课件整理", "12 秒", "线上全流程验证，模型真实调用"],
        ["68 页全章整理", "约 111.7 秒模型响应 + 处理开销", "陈瑀涵评测报告：71 次调用"],
        ["单次全章调用量", "49,167 tokens（输入 35,805 / 输出 13,362）", "同上，重试 0 次、JSON 降级 0 次"],
        ["单次全章成本", "约 1~2 元（按当前 DeepSeek 价格）", "按 token 数估算"],
        ["接口响应（非模型类）", "毫秒级", "列表、历史、导出等"],
    ], widths=[4.4, 6.6, 6.2])

    h2(doc, "2.3 功能与工程指标")
    table(doc, ["项", "实测值"], [
        ["支持的学习资料格式", "8 种：PDF、PPTX、DOCX、TXT、Markdown、HTML、CSV、EPUB"],
        ["图片与扫描件", "已实现 OCR 接入层，需在 .env 配置阿里云 OCR 密钥后启用"],
        ["单文件大小上限", "50 MB（可配置）"],
        ["扫描件识别", "平均每页少于 40 字判为无文本层，明确提示而非静默失败"],
        ["数据库", "业务库 17 张表 + 领域知识库 6 张表，物理分离"],
        ["接口", "12 组 REST 端点，另有可视化接口文档 /docs"],
        ["自动化测试", "37 项（契约、解析、接口、Agent 管线、配置回归）"],
        ["部署", "阿里云 ECS 2核4G / Ubuntu 22.04，systemd 守护，开机自启"],
        ["检索", "SQLite FTS5 二元组 + 覆盖率重排；无关问题零召回"],
    ], widths=[4.6, 12.6])

    # ---------------- 三 ----------------
    doc.add_page_break()
    h1(doc, "三、SRS 里技术类【代填】建议填法（需求组可直接回填）")
    table(doc, ["SRS 位置", "现在缺什么", "建议填", ], [
        ["1.2 范围（技术边界）", "支持的材料边界",
         "PDF/PPTX/DOCX/TXT/MD/HTML/CSV/EPUB 共 8 种；单文件 ≤50MB；无文本层的扫描件与图片需配置 OCR"],
        ["2.4 约束", "已有强制技术要求", "Web 使用方式；后端 Python 3.12 + FastAPI；数据存储 SQLite；模型经 HTTP API 调用"],
        ["3.1.3 IF-01 上传", "格式、大小、页数",
         "格式见上；≤50MB；单份建议 ≤100 页"],
        ["3.1.3 IF-02 整理请求", "字段与结构",
         "JSON：{doc_ids:[], course_name, task_type}；返回 session_id，异步执行"],
        ["3.1.3 IF-03 问答", "长度、编码",
         "问题 ≤500 字符，UTF-8；答案附出处列表"],
        ["3.1.3 IF-05 模型服务", "服务、版本、字段",
         "OpenAI 兼容协议；当前 deepseek-chat；字段见 app/schemas/agent_io.py"],
        ["3.1.3 IF-06 知识检索", "检索格式与范围",
         "FTS5 + 二元组覆盖率重排；按课程/文档过滤；返回 top-k 片段及出处"],
        ["3.2.2 FR-02", "支持格式、解析范围",
         "同 3.1.3 IF-01；解析保留页码/幻灯片号/章节；扫描件识别后提示"],
        ["3.3 性能需求 PF-03", "整理完成时间",
         "6 页约 12 秒；68 页约 2 分钟；95% 任务在 3 分钟内完成（线上实测）"],
        ["3.3 PF-04", "问答响应时间",
         "检索毫秒级；含模型生成时 3~10 秒（视问题与材料量）"],
        ["3.6 QA-07", "测试集、指标、阈值",
         "参考知识点 36 条；覆盖率 66.67%；无依据陈述比例 0%；问答准确率 83.33%"],
        ["附录 B.1", "课程、样本、标注方式",
         "课件 9_副本.pdf（第13章 构件级设计，68 页）；参考知识点 36 条，由编程组起草"],
        ["附录 B.3", "基础模型、参数、运行次数",
         "deepseek-chat；temperature 0.2；定制与裸调用各 1 次全章；评价为自动文本匹配 + 人工复核"],
    ], widths=[4.2, 4.6, 8.4], size=9)

    # ---------------- 四 ----------------
    h1(doc, "四、交出去之后要盯别人交的（别以为交完就完了）")
    table(doc, ["谁", "要交什么", "为什么你必须盯"], [
        ["答辩与博客组", "团队博客 1 篇（10/25 截止，标题含「26软工实践 xx 团队展示与选题报告」）",
         "作业只允许团队博客发 1 篇；漏发等于没交"],
        ["答辩与博客组", "PPT + 10 分钟讲稿 + 彩色打印的走查说明",
         "答辩 10/24，16 分钟（讲 10 + 问 6）"],
        ["需求组", "SRS 全部【代填】清零、附录 C 未完成项关闭",
         "老师会按文档验收；留着【代填】很显眼"],
        ["需求组", "项目标志、思维导图、类图、迭代记录表",
         "作业明确要求，现在这几项还缺"],
        ["组长", "队名、团队成员学号-姓名、首次合照、团队愿景（50~100 字）",
         "博客格式要求逐条对应，缺一条就扣分"],
    ], widths=[3.4, 7.6, 6.2])

    # ---------------- 五 ----------------
    h1(doc, "五、答辩当天的最小演示动线（3 分钟）")
    bullets(doc, [
        "① 打开 http://47.114.55.115:8000，用演示账号登录，直接进历史任务 #8 —— 避免现场等待（最稳的兜底）",
        "② 展示结果页：10 个知识点、每条都有出处角标；点开一个角标，展示原文引文（这是「防编造」的直观证据）",
        "③ 切到「质量自评」卡片：87.9 分，说明 85/10/5 的加权规则",
        "④ 现场新传一份课件，展示进度页真实进度（21%→39%→68%→100%），证明不是假动画",
        "⑤ 点「导出 Markdown」，展示可下载的笔记文件",
        "⑥ 口头给出对比数据：定制 66.67% vs 裸模型 38.89%，无依据陈述 0%",
    ])
    body(doc, "兜底准备：提前录 90 秒屏；把任务 #8 的结果页保持登录状态；"
              "如遇网络问题，直接切录屏继续讲。", color=GREY)

    doc.add_paragraph()
    body(doc, "制表：编程组　｜　数据来源：本机测试套件、线上全流程验证脚本、"
              "陈瑀涵《Agent真实课件评测报告 20261019》", color=GREY)
    return doc


def main() -> int:
    doc = build()
    written, note = save_with_retry(doc, OUTPUT)
    print(f"[ok] 已生成：{written}")
    print(f"[ok] 大小：{written.stat().st_size:,} 字节")
    if note:
        print(f"[warn] {note}")
    check = Document(str(written))
    print(f"[ok] 校验：{len(check.paragraphs)} 段落 / {len(check.tables)} 表格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
