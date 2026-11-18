"""生成《待确认事项清单》Word 文档。

用法：python scripts/make_decision_doc.py
产物：项目根目录下的「编程组待确认事项清单.docx」

为什么用脚本生成而不是手写文档：
    这些事项会随讨论变化，改内容只需改本脚本再跑一次，避免文档与代码/需求文档不同步。
"""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
# 输出到「新建文件夹 (2)」这一层，与需求文档、分工表放在一起
OUTPUT = ROOT.parent / "编程组待确认事项清单.docx"

TODO = "【待确认】"
GREY = RGBColor(0x66, 0x66, 0x66)
RED = RGBColor(0xC0, 0x00, 0x00)


# --------------------------------------------------------------------------
# 基础排版工具
# --------------------------------------------------------------------------
def set_font(run, *, name: str = "宋体", size: float = 10.5, bold: bool = False,
             color: RGBColor | None = None) -> None:
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def setup_document(doc: Document) -> None:
    """设置正文默认中文字体，避免中文显示成方框。"""
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.2)
        section.right_margin = Cm(2.2)


def add_title(doc: Document, text: str, *, size: float = 18) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(text), name="微软雅黑", size=size, bold=True)


def add_subtitle(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(text), name="微软雅黑", size=10.5, color=GREY)


def add_heading(doc: Document, text: str, *, size: float = 14) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(6)
    set_font(p.add_run(text), name="微软雅黑", size=size, bold=True)


def add_body(doc: Document, text: str, *, bold: bool = False,
             color: RGBColor | None = None, indent: float = 0.0) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    set_font(p.add_run(text), size=10.5, bold=bold, color=color)


def add_bullets(doc: Document, items: list[str]) -> None:
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(2)
        set_font(p.add_run(item), size=10.5)


def add_table(doc: Document, headers: list[str], rows: list[list[str]],
              widths: list[float] | None = None) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        set_font(cell.paragraphs[0].add_run(header), name="微软雅黑", size=10, bold=True)

    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = ""
            paragraph = cells[i].paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(1)
            color = RED if TODO in value else None
            set_font(paragraph.add_run(value), size=9.5, color=color)

    if widths:
        for row in table.rows:
            for i, width in enumerate(widths):
                row.cells[i].width = Cm(width)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


# --------------------------------------------------------------------------
# 文档内容
# --------------------------------------------------------------------------
def build() -> Document:
    doc = Document()
    setup_document(doc)

    add_title(doc, "编程组待确认事项清单")
    add_subtitle(doc, "大学生课程课件笔记整理与知识梳理 Agent ｜ 供组会讨论使用")

    add_body(doc, "项目：大学生课程课件笔记整理与知识梳理 Agent")
    add_body(doc, "编程小队：徐张睿（组长）、沈文驰、陈瑀涵、陈佳慧")
    add_body(doc, "代码节点：10/19 交代码 ｜ 10/24 答辩 ｜ 10/25 博客截止")
    add_body(doc, "本文档用途：把需要小组拍板的事项集中列出，便于逐条讨论并记录结论。"
                  "红色标注为尚未确定的内容，不要凭猜测填写。", color=GREY)

    # ---------------- 一 ----------------
    add_heading(doc, "一、今天必须定（不定就卡住）")
    add_body(doc, "以下 6 项直接影响另外三名成员能否开工，建议本次组会逐条给出结论。")

    add_table(doc,
              ["序号", "要定什么", "可选项", "建议", "不定后果"],
              [
                  ["1", "真实演示课件",
                   "由需求组提供一份真实 PDF 与一份 PPTX，并明确课程名与章节范围",
                   "首期只做一门课的 1~2 章",
                   "解析与检索调优全部空转，只能用生成的假 PDF 测试"],
                  ["2", "模型服务与密钥",
                   "DeepSeek / 通义千问 / Kimi / 校内自建；谁申请、谁付费、额度多少",
                   "中文任务用 DeepSeek 或通义；另备第二家密钥防限流",
                   "Agent 管线写完无法调效果"],
                  ["3", "服务器与访问地址",
                   "是否有现成服务器（学校项目机、组员已有的云主机）；"
                   "没有则任选一家云厂商领新用户免费试用。"
                   "关键：用公网 IP + 端口访问，不要绑域名（域名指向境内服务器需要备案，来不及）",
                   "阿里云 / 腾讯云 / 华为云 均可，哪家有额度用哪家；"
                   "2 核 2G 起步，Ubuntu 22.04 或 24.04",
                   "10/18 无法上线，直接违反“应用需上线运行”的要求"],
                  ["4", "手写公式转 LaTeX（OP-02）是否实施",
                   "实施 / 本期不实施",
                   "本期不实施。手写识别准确率不可控，演示风险最高",
                   "SRS 的 2.6 与 3.2.11 无法定稿"],
                  ["5", "原文出处标注（OP-03）是否提升为必做",
                   "保持可选 / 提升为必做",
                   "提升为必做。这是“领域定制”最直观的证据，实现成本低",
                   "项目最有说服力的差异点被标成“可选”"],
                  ["6", "是否做硬件联动",
                   "不做 / 做基本输入输出 / 做完整任务闭环",
                   "不做。规则明确“仅展示硬件不加分”，工期不够会拖垮演示",
                   "SRS 3.1.2 硬件接口章节无法定稿，范围无法冻结"],
              ],
              widths=[1.1, 3.4, 4.2, 4.2, 3.6])

    # ---------------- 二 ----------------
    add_heading(doc, "二、本周内要定（影响工期与答辩口径）")

    add_body(doc, "2.1 可选功能取舍（决定工作量，逐行打勾）", bold=True)
    add_table(doc,
              ["编号", "功能", "建议", "结论"],
              [
                  ["OP-01", "例题整理（检索优先、生成兜底）", "实施", TODO],
                  ["OP-02", "手写公式转 LaTeX", "本期不实施", TODO],
                  ["OP-03", "原文出处标注", "实施（提升为必做）", TODO],
                  ["OP-04", "笔记增量合并与版本记录", "实施", TODO],
                  ["OP-05", "考试范围复习笔记", "实施（复用既有管线）", TODO],
                  ["OP-06", "固定权重质量自评（85%/10%/5%）", "实施", TODO],
              ],
              widths=[1.8, 6.4, 4.6, 3.6])

    add_body(doc, "2.2 项目范围与材料边界", bold=True)
    add_table(doc,
              ["事项", "说明", "结论"],
              [
                  ["首期课程与章节", "建议一门课 1~2 章，不铺开", TODO],
                  ["支持的文件格式", "当前仅 .pdf 与 .pptx；.ppt 旧格式提示另存", TODO],
                  ["单文件大小上限", "代码当前默认 50MB，可调整", TODO],
                  ["页数或幻灯片数上限", "是否需要限制，用于控制处理时长", TODO],
                  ["扫描件处理策略", "当前识别后明确提示“不支持 OCR”，不做识别", TODO],
              ],
              widths=[3.6, 8.4, 4.4])

    add_body(doc, "2.3 人工标注与定制效果对比（最容易拖死进度）", bold=True)
    add_table(doc,
              ["事项", "要求", "结论"],
              [
                  ["参考知识点标注", "某章节 25~30 条，由最熟悉课程的同学标注", TODO],
                  ["标注交付时间", "10/17 前必须给到，否则评测做不出来", TODO],
                  ["对比实验范围", "建议同一章节，裸调用模型 vs 本系统管线", TODO],
                  ["运行次数与评分人", "建议同一输入跑 3 次；2 人独立评分取平均", TODO],
                  ["评价指标", "知识点覆盖率、无依据陈述比例、问答正确率", TODO],
              ],
              widths=[3.8, 8.2, 4.4])

    add_body(doc, "2.4 前端分工与开发方式", bold=True)
    add_table(doc,
              ["事项", "说明", "结论"],
              [
                  ["前端两人分工", "建议陈佳慧做结果展示（笔记/重点/导图/出处/问答），"
                                    "陈瑀涵做骨架（登录/上传/进度/历史/导出/异常态）", TODO],
                  ["并行开发方式", "后端完成前用约定好的 mock 数据，避免互相等待", TODO],
                  ["部署形态", "建议同源单服务：前端构建产物由后端挂静态目录", TODO],
              ],
              widths=[3.4, 8.6, 4.4])

    add_body(doc, "2.5 技术选型定稿（决定答辩怎么讲，改动会返工）", bold=True)
    add_table(doc,
              ["选型项", "当前实现", "可讨论的替代方案", "结论"],
              [
                  ["数据库", "SQLite（单文件，零运维，分业务库与知识库两个文件）",
                   "MySQL / PostgreSQL（需额外部署，单人课程量级无必要）", TODO],
                  ["检索方式", "SQLite FTS5 二元组索引 + 覆盖率重排，向量库为关闭的开关",
                   "引入向量检索（需额外组件与解释成本）", TODO],
                  ["前端框架", "接口已按 Vue 3 + Element Plus + Vite 准备",
                   "React / 其他", TODO],
                  ["登录鉴权", "签名令牌，同时支持 Cookie 与 Bearer", "无", TODO],
              ],
              widths=[2.6, 6.4, 5.0, 2.4])

    add_body(doc, "2.6 答辩口径：单智能体还是多智能体", bold=True)
    add_body(doc, "作业描述中提到“多智能体方案应说明分工与协作”。当前实现是"
                  "单条管线内的多角色协作：逐块抽取 → 证据校验 → 归并去重 → 检索补全 → "
                  "生成笔记 → 质量自评。", indent=0.6)
    add_bullets(doc, [
        "方案甲：答辩口径为“多角色协作的任务流”，强调每一步的职责与可验证性。",
        "方案乙：把“证据校验”与“质量自评”独立成两个智能体角色来讲述，"
        "代码上可复用现有模块，改动量小。",
    ])
    add_body(doc, f"统一口径结论：{TODO}", color=RED)

    # ---------------- 三 ----------------
    add_heading(doc, "三、需要其他小组提供的东西")
    add_body(doc, "说明：以下是编程组无法自己产出的输入。请在组会上逐条指派负责人与时间，"
                  "并注意最后列的“交付要求”——格式不对等于没给。", color=GREY)

    add_body(doc, "3.1 阻塞项（没有就干不了，今天到明天必须给）", bold=True)
    add_table(doc,
              ["序号", "需要什么", "找谁要", "交付要求（验收口径）", "最晚时间", "不给的后果"],
              [
                  ["1", "一份真实 PDF 课件",
                   "需求组（梁倩）",
                   "已确定要做的课程与章节，每页都有可复制的文字（能在 PDF 阅读器里选中文字）",
                   "10/15",
                   "解析与检索无法用真数据调优"],
                  ["2", "一份真实 PPT 课件",
                   "需求组（梁倩）",
                   "内容与上面同一门课或同一章节；不要纯图片版幻灯片",
                   "10/15",
                   "PPTX 解析路径（幻灯片序号定位）无法验证"],
                  ["3", "参考知识点清单（用于评测）",
                   "需求组 + 组长",
                   "25~30 条，每条含知识点名称、所属章节、页码或幻灯片号、2~5 个要点",
                   "10/17",
                   "覆盖率与无依据率算不出来，定制效果无法证明"],
                  ["4", "模型服务与密钥",
                   "组长（徐张睿）",
                   "供应商、模型名、可用额度；密钥私聊发送，不进仓库；另备一家备用密钥",
                   "10/15",
                   "Agent 管线无法调试"],
                  ["5", "服务器",
                   "组长（徐张睿）",
                   "可访问的 IP 或域名；开放 80/443 端口；能安装 Python 3.12",
                   "10/17",
                   "10/18 无法上线"],
              ],
              widths=[1.0, 3.0, 2.2, 5.6, 1.6, 3.0])

    add_body(doc, "3.2 非阻塞项（可并行，但不能拖过 10/22）", bold=True)
    add_table(doc,
              ["序号", "需要什么", "找谁要", "交付要求", "最晚时间"],
              [
                  ["6", "调研依据", "需求组（梁倩）+ 组长",
                   "调研时间、方法（问卷/访谈/统计）、对象、样本数、主要结论；"
                   "每一项结论要能对应到一条需求编号", "10/17"],
                  ["7", "项目组名称与项目简称", "组长",
                   "中文全称 + 2~4 字简称；用于页面标题、导出文件名、博客标题", "10/18"],
                  ["8", "项目 Logo", "需求组",
                   "PNG 或 SVG，建议 512×512 以上，透明底；讲清图形与配色含义（SRS A.3 要写）",
                   "10/20"],
                  ["9", "测试账号", "编程组生成，需求组转交",
                   "一个学生账号 + 一个管理员账号；附 3 分钟走查步骤（先做什么、看哪里）", "10/18"],
                  ["10", "答辩安排", "组长",
                   "谁主讲、谁答问、PPT 谁做、博客谁写；答辩时段与地点", "10/22"],
                  ["11", "演示兜底录屏", "编程组录制，答辩组保管",
                   "90 秒，提前录好，用于现场断网或接口异常时切换", "10/22"],
              ],
              widths=[1.0, 3.2, 2.6, 7.2, 1.8])

    add_body(doc, "3.3 编程组反过来要主动提供的东西", bold=True)
    add_body(doc, "以下内容由编程组产出并交付给其他小组，也需要在组会上确认接收人：", indent=0.4)
    add_table(doc,
              ["交付物", "接收方", "用途", "最晚时间"],
              [
                  ["可访问的线上地址 + 测试账号 + 走查说明", "组长 → 任课老师与助教",
                   "作业要求“上线运行并提供访问地址与测试方式”", "10/18"],
                  ["评测数据（覆盖率、无依据率、问答正确率）",
                   "答辩与博客小组（章玲、陈瑀涵、庄剑钇）", "PPT 与博客的核心论据", "10/19"],
                  ["裸调用模型与本系统管线的对比结果", "答辩与博客小组",
                   "证明“定制前后”的能力提升，这是评分项", "10/21"],
                  ["界面截图包（含移动端）", "博客负责人", "博客插图", "10/21"],
                  ["部署步骤与已知限制说明", "组长 → 老师", "验收时会被问到“怎么跑起来”", "10/19"],
              ],
              widths=[6.2, 4.4, 4.4, 2.0])

    add_body(doc, "3.4 提要求时请回避这三种情况", bold=True)
    add_bullets(doc, [
        "不要给“扫描版 PDF”或“整页是图片的 PPT”——程序读不到文字，会明确提示不支持，"
        "这不是程序的问题，是材料的问题。判断方法：在阅读器里试着选中一句话，选不中就属于扫描件。",
        "不要给“知识点清单”就一两行，例如“第二章重点：导数”。评测需要的是能逐条打勾的清单，"
        "格式越具体越好。",
        "不要给“旧格式 .ppt”或“加密 PDF”。前者请用 PowerPoint 另存为 .pptx，"
        "后者请先解除限制或提供未加密版本。",
    ])

    add_body(doc, "3.5 建议的参考知识点清单格式（可直接照抄填写）", bold=True)
    add_table(doc,
              ["知识点名称", "所属章节", "页码/幻灯片号", "核心要点（2~5 条）", "重要度"],
              [
                  ["导数的定义", "2.1 导数的概念", "第 98 页 / 第 7 张",
                   "变化率；记作 f'(x0)；左导数与右导数相等才可导", "高"],
                  ["导数的几何意义", "2.1 导数的概念", "第 99 页 / 第 8 张",
                   "曲线在该点处切线的斜率", "高"],
                  ["（示例行，请替换为真实内容）", "", "", "", ""],
                  ["（示例行，请替换为真实内容）", "", "", "", ""],
              ],
              widths=[3.4, 3.2, 2.8, 6.2, 1.4])
    add_body(doc, "说明：这张表的每一行都会参与覆盖率计算——系统生成的知识点能否覆盖到这些条目，"
                  "直接决定“知识点覆盖率”这个指标。标注人应当是最熟悉该课程的人（需求组），"
                  "标注完成后由陈瑀涵写脚本自动比对，不需要人工核。", color=GREY)

    # ---------------- 四 ----------------
    add_heading(doc, "四、需求文档必须同步修改的地方")
    add_body(doc, "以下位置在结论确定后必须同步更新，否则会出现“文档与答辩口径不一致”，"
                  "评审时容易被追问。", color=GREY)
    add_table(doc,
              ["位置", "需要改什么"],
              [
                  ["SRS 2.6 需求分配表", "逐行填写“是否实施”，未选功能必须明确写“本期不实施”"],
                  ["SRS 3.2.11（OP-02）", "若不实施，明确记为不实施并从验收范围移除"],
                  ["SRS 3.1.2 硬件接口", "若不做硬件，保持“不涉及”；若做，需补设备、协议与时序"],
                  ["SRS 附录 C 未完成事项", "逐条关闭，或明确写“本期不做”，不留【代填】"],
                  ["SRS 文档信息", "项目组名称、审核人与审核日期"],
                  ["SRS 附录 D 分工表", "按现有四人小队更新角色与职责"],
              ],
              widths=[4.6, 11.8])

    add_body(doc, "特别提醒：作业规则中存在硬件联动加分，而当前需求文档写的是"
                  "“当前不涉及硬件联动”。两处必须保持一致，不要出现“文档说不做、"
                  "答辩说做了”的矛盾。", color=RED)

    # ---------------- 五 ----------------
    doc.add_page_break()
    add_heading(doc, "五、当前实现进度（供讨论时参考，无需决策）")
    add_body(doc, "代码位于 course-note-agent 目录，全部自检均不需要模型服务与密钥。")

    add_table(doc,
              ["模块", "状态"],
              [
                  ["数据库结构（业务库与知识库分离，17 张表）", "已完成并通过验证"],
                  ["接口层：注册登录、上传解析、任务流转、结果、导出、历史、问答、管理端",
                   "已完成并通过验证"],
                  ["中文检索与重排（含无关问题零召回）", "已完成并通过验证"],
                  ["证据校验（引文回查原文，查不到即丢弃）", "已完成并通过验证"],
                  ["课件解析（PDF/PPTX、章节跨页继承、扫描件识别）", "已完成并通过验证"],
                  ["Agent 管线（接模型、提示词、评测脚本）", "骨架就位，等陈瑀涵接手"],
                  ["前端页面", "等陈佳慧开发，接口与 mock 已就绪"],
                  ["部署上线与评测报告", "等服务器与标注数据"],
              ],
              widths=[10.4, 6.0])

    add_body(doc, "自检命令与结果：", bold=True)
    add_table(doc,
              ["命令", "内容", "结果"],
              [
                  ["python tests/test_contracts.py", "契约、检索、引文核验", "6 项通过"],
                  ["python tests/test_parse.py", "解析、切块、入库、异常文件", "11 项通过"],
                  ["python tests/test_api.py", "接口端到端、越权隔离、导出", "10 项通过"],
                  ["python scripts/selftest_pipeline.py", "主链路自检", "4 步通过"],
                  ["python scripts/e2e_smoke.py", "完整业务流程走查（可作演示脚本）", "7 步通过"],
                  ["python scripts/lint_sql_params.py", "SQL 参数一致性静态检查", "35 条通过"],
              ],
              widths=[6.6, 6.6, 3.2])

    # ---------------- 六 ----------------
    add_heading(doc, "六、组会结论记录")
    add_body(doc, "讨论后请把结论填在这里，并同步更新需求文档与分工表。")
    add_table(doc,
              ["序号", "事项", "结论", "负责人", "完成时间"],
              [[str(i), "", "", "", ""] for i in range(1, 9)],
              widths=[1.2, 4.6, 5.0, 2.8, 2.8])

    doc.add_paragraph()
    add_body(doc, "制表：编程组　｜　依据：课程作业要求、组内需求文档（SRS V0.2）、"
                  "知识库与提示词交付稿、项目架构思维导图", color=GREY)

    return doc


def save_with_retry(doc: Document, target: Path) -> tuple[Path, str | None]:
    """保存文档。Word 打开着文件时会报 PermissionError，这里给出可操作的提示。

    返回 (实际写入路径, 提示信息)。若目标被占用，则改名另存，避免用户以为生成失败。
    """
    import time

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
            return fallback, (
                f"目标文件被占用（通常是 Word 正开着「{target.name}」）。"
                f"本次已另存为「{fallback.name}」，请关闭 Word 后重新运行本脚本，"
                "或直接使用另存的新文件。")
    raise AssertionError("unreachable")


def main() -> int:
    doc = build()
    written, note = save_with_retry(doc, OUTPUT)
    print(f"[ok] 已生成：{written}")
    print(f"[ok] 文件大小：{written.stat().st_size:,} 字节")
    if note:
        print(f"[warn] {note}")
    # 简单校验：重新打开确认能读出章节与表格数量
    check = Document(str(written))
    print(f"[ok] 校验：{len(check.paragraphs)} 个段落，{len(check.tables)} 张表格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
