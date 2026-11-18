"""生成《我需要交付给他人的内容》Word 文档。

只回答一个问题：我（组长 / 编程组）要往外给什么、给谁、什么形式、什么时候。
不写别人要做什么。

用法：python scripts/make_outbound_doc.py
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
OUTPUT = ROOT.parent / "我需要交付给他人的内容.docx"

GREY = RGBColor(0x66, 0x66, 0x66)
BLUE = RGBColor(0x1F, 0x4E, 0x79)
GREEN = RGBColor(0x1E, 0x7A, 0x34)
AMBER = RGBColor(0xB0, 0x60, 0x00)


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
        s.top_margin = Cm(1.8)
        s.bottom_margin = Cm(1.8)
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
    p.paragraph_format.space_before = Pt(13)
    p.paragraph_format.space_after = Pt(5)
    set_font(p.add_run(text), name="微软雅黑", size=14, bold=True, color=BLUE)


def body(doc, text, *, bold=False, color=None, size=10.5, indent=0.0):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    set_font(p.add_run(text), size=size, bold=bold, color=color)


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
            elif value.startswith("⬜"):
                color = AMBER
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

    title(doc, "我需要交付给他人的内容")
    subtitle(doc, "组长 / 编程组对外交付清单　｜　只列我要给出去的，不列别人要做什么")

    body(doc, "线上地址：http://47.114.55.115:8000")
    body(doc, "演示账号：verify_37777bd6　密码：verify123", color=GREY)
    body(doc, "说明：所有交付物都已在本机或线上验证过；标 ⬜ 的是还差最后一步整理。", color=GREY)

    # ================= 1. 给老师与助教 =================
    h1(doc, "一、给老师与助教（课程验收用）")
    table(doc, ["交付物", "形式", "内容要点", "状态"], [
        ["线上访问地址", "一个网址", "http://47.114.55.115:8000　（阿里云 ECS，Ubuntu 22.04，systemd 守护，开机自启）", "✅"],
        ["测试账号", "账号密码", "学生账号：verify_37777bd6 / verify123；管理员：admin / admin123", "✅"],
        ["三分钟走查说明", "一页纸 / 文档页", "① 打开地址登录　② 进「历史任务」看任务 #8 的结果"
                                    "　③ 新传一份 PDF 看整理过程　④ 点导出下载 Markdown", "⬜ 待整理"],
        ["部署与运行说明", "文档", "服务器、依赖、启动命令、已知限制（扫描件需配置 OCR）", "✅ 源码包内 README"],
        ["源码与可运行包", "zip", "course-note-agent-complete.zip（110 个文件，含前端源码与前端构建产物）", "✅"],
    ], widths=[3.2, 3.0, 8.4, 2.2])

    # ================= 2. 给答辩与博客组 =================
    h1(doc, "二、给答辩与博客组（PPT 与博客的素材）")

    body(doc, "2.1 效果数据（可直接放进 PPT 与博客）", bold=True)
    table(doc, ["指标", "定制 Agent", "裸模型基线", "备注"], [
        ["知识点覆盖率", "66.67%（24/36）", "38.89%（14/36）", "同一份课件、同一模型，高 27.78 个百分点"],
        ["无依据陈述比例", "0%", "100%", "定制结果全部绑定可核验出处"],
        ["问答正确率", "83.33%（5/6）", "未测", "自动关键词判定，口径偏保守"],
        ["质量自评", "82.1 / 100", "—", "85%（核心）/ 10%（结构）/ 5%（关联）加权"],
    ], widths=[3.6, 3.6, 3.4, 6.2])
    body(doc, "口径必须说清：66.67% 是「保守文本匹配」的自动判定结果，不能写成人工语义覆盖率；"
              "未匹配的 12 条中有多条已用近义表述抽取到。主动交代比被追问稳妥。", color=GREY)

    body(doc, "2.2 性能与成本", bold=True)
    table(doc, ["场景", "实测值"], [
        ["6 页 / 4MB 课件", "12 秒完成（线上真实调用）"],
        ["68 页全章", "约 2 分钟；71 次模型调用；49,167 tokens（输入 35,805 / 输出 13,362）"],
        ["单章成本", "约 1~2 元"],
        ["稳定性", "重试 0 次、JSON 降级 0 次"],
    ], widths=[4.0, 13.2])

    body(doc, "2.3 技术要点（写博客「技术方案」一节用）", bold=True)
    table(doc, ["要点", "一句话说法"], [
        ["多格式解析", "支持 PDF/PPTX/DOCX/TXT/MD/HTML/CSV/EPUB 共 8 种，按文件头识别，扩展名伪造也能认对"],
        ["防编造机制", "模型每条结论必须带原文引文，代码逐条回查原文，查不到即丢弃并计数"],
        ["检索方案", "SQLite FTS5 二元组 + 覆盖率重排；无关问题零召回，因此能如实回答「材料未涉及」"],
        ["长任务体验", "后台任务 + 1.5 秒轮询 + 阶段文案；6 页 12 秒、68 页约 2 分钟"],
        ["质量自评", "按 85%/10%/5% 固定权重自查，扣分理由可见"],
        ["工程保障", "37 项自动化测试；线上全流程验证脚本；SQL 参数静态检查；打包时自动扫描密钥泄露"],
    ], widths=[3.4, 13.8])

    body(doc, "2.4 界面截图包（⬜ 待截）", bold=True)
    body(doc, "建议截 7 张，用演示账号登录后依次截：", indent=0.3)
    for line in [
        "① 登录页（含背景图，体现视觉设计）",
        "② 「历史任务」列表（显示状态标签与进度）",
        "③ 结果页-结构化笔记（可见多条知识点及出处角标）",
        "④ 出处角标弹窗（展示原文引文 + 文件名 + 页码，这是最有说服力的一张）",
        "⑤ 结果页-质量自评卡片（87.9 分与三个维度）",
        "⑥ 结果页-文本思维导图",
        "⑦ 进度页（21% / 39% / 68% 任一张，证明真实进度）",
    ]:
        body(doc, line, indent=0.6)

    body(doc, "2.5 演示兜底", bold=True)
    table(doc, ["交付物", "说明", "状态"], [
        ["90 秒演示录屏", "覆盖 登录→历史结果→出处弹窗→导出；网络故障时直接播放", "⬜ 待录"],
        ["演示动线说明", "3 分钟讲哪几步、每步讲什么（避免现场等 2 分钟）", "✅ 见第四节"],
    ], widths=[4.2, 10.0, 3.0])

    # ================= 3. 给需求组 =================
    doc.add_page_break()
    h1(doc, "三、给需求组（回填 SRS 用）")
    body(doc, "SRS 里技术类的【代填】按右列直接填即可；左列是位置。", color=GREY)
    table(doc, ["SRS 位置", "建议填写内容"], [
        ["1.2 范围（材料边界）",
         "支持 PDF/PPTX/DOCX/TXT/Markdown/HTML/CSV/EPUB 共 8 种；单文件 ≤50MB；无文本层的扫描件与图片需配置 OCR 服务后支持"],
        ["2.4 约束",
         "Web 使用方式；后端 Python 3.12 + FastAPI；数据存储 SQLite；模型经 HTTP API 调用；部署于单台云服务器"],
        ["3.1.3 IF-01 上传",
         "格式见 1.2；单文件 ≤50MB；建议单份 ≤100 页；返回 parse_status（success/partial/failed）与失败原因"],
        ["3.1.3 IF-02 整理请求",
         "JSON：{doc_ids:[], course_name, task_type}；返回 session_id，异步处理，前端轮询状态"],
        ["3.1.3 IF-03 问答",
         "问题 ≤500 字符，UTF-8；回答附出处列表；材料不足时返回 insufficient=true 并说明未涉及"],
        ["3.1.3 IF-05 模型服务",
         "OpenAI 兼容协议；当前模型 deepseek-chat；字段定义见 app/schemas/agent_io.py"],
        ["3.1.3 IF-06 知识检索",
         "FTS5 全文索引 + 二元组覆盖率重排；按课程/文档过滤；返回 top-k 片段及页码出处"],
        ["3.2.2 FR-02",
         "解析保留页码/幻灯片序号/章节归属；扫描件（每页均 <40 字）识别后明确提示，不宣称成功"],
        ["3.3 PF-03 整理时间",
         "6 页约 12 秒；68 页约 2 分钟；95% 任务在 3 分钟内完成（线上实测）"],
        ["3.3 PF-04 问答时间",
         "检索毫秒级；含模型生成时 3~10 秒"],
        ["3.6 QA-07 正确性",
         "测试集：36 条人工参考知识点；覆盖率 66.67%；无依据陈述比例 0%；问答正确率 83.33%"],
        ["附录 B.1 代表性任务",
         "课件：9_副本.pdf（软件工程 第13章 构件级设计，68 页）；参考知识点 36 条"],
        ["附录 B.3 对比实验",
         "模型 deepseek-chat；temperature 0.2；定制与裸调用各跑 1 次全章；自动文本匹配 + 人工复核"],
    ], widths=[4.0, 13.2], size=9)

    # ================= 4. 给编程组组员 =================
    h1(doc, "四、给编程组组员（继续开发用）")
    table(doc, ["交付物", "给谁", "内容", "状态"], [
        ["完整源码包", "沈文驰、陈瑀涵、陈佳慧",
         "course-note-agent-complete.zip：后端 + Agent + 提示词 + 前端源码 + 前端构建产物 + 测试", "✅"],
        ["交接说明", "同上", "如何跑起来、哪些模块不用自己写、常见报错对照", "✅"],
        ["前端源码", "陈佳慧", "frontend/ 目录（含我修正的 4 个页面与 index.html）", "✅"],
        ["Agent 测试数据", "陈瑀涵", "参考知识点清单（36 条）+ 课件材料包获取方式", "✅"],
        ["部署命令清单", "任何人", "服务器更新步骤与排错方法", "✅"],
        ["演示账号", "全体", "verify_37777bd6 / verify123", "✅"],
    ], widths=[3.2, 3.2, 7.4, 3.4])

    # ================= 5. 自己留档 =================
    h1(doc, "五、给自己留档（不对外，但答辩前必须有）")
    table(doc, ["留存物", "用途"], [
        ["评测结果 JSON（compare / qa_eval / latest_result）", "被追问数据来源时可直接展示"],
        ["Agent 评测报告（md）", "数据口径与局限说明的依据"],
        ["线上验证脚本输出", "证明「老师打开后确实能用」，含时间戳"],
        ["源码备份（含合并前版本）", "答辩前误改可回滚"],
        ["服务器与密钥信息", "答辩当天排障用（不要外传）"],
    ], widths=[8.0, 9.2])

    doc.add_paragraph()
    body(doc, "制表：编程组　｜　数据来源：本机测试套件、线上全流程验证、"
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
