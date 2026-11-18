"""生成《服务器迁移操作清单》Word 文档。

场景：阿里云 ECS 到期，要换一台新服务器（或续费前先迁移演练）。

用法：python scripts/make_migration_doc.py
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
OUTPUT = ROOT.parent / "服务器迁移操作清单.docx"

GREY = RGBColor(0x66, 0x66, 0x66)
BLUE = RGBColor(0x1F, 0x4E, 0x79)
GREEN = RGBColor(0x1E, 0x7A, 0x34)
AMBER = RGBColor(0xB0, 0x60, 0x00)
RED = RGBColor(0xC0, 0x00, 0x00)


def set_font(run, *, name="宋体", size=10.5, bold=False, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), name)


def setup(doc):
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(10.5)
    style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
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
    set_font(p.add_run(text), name="微软雅黑", size=9.5, color=GREY)


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


def code(doc, text):
    for line in text.strip("\n").splitlines():
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.left_indent = Cm(0.6)
        set_font(p.add_run(line), name="Consolas", size=9, color=RGBColor(0x33, 0x33, 0x33))


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
            if value.startswith("✓"):
                color = GREEN
            elif value.startswith("!"):
                color = AMBER
            elif value.startswith("✗"):
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

    title(doc, "服务器迁移操作清单")
    subtitle(doc, "阿里云 ECS 到期换机 ｜ 课程课件笔记整理 Agent")

    body(doc, "结论先说：不难。整个项目是自包含的——代码 + 一个 SQLite 库 + 一个 .env 配置文件。"
              "实际操作用 20 分钟，其中一半时间在等 pip 装依赖。", bold=True)

    h1(doc, "一、到底要搬哪些东西")
    table(doc, ["内容", "位置", "能不能重建", "说明"], [
        ["代码", "整个项目目录（.py / static / scripts）", "✓ 有压缩包或 Git", "790 KB 左右"],
        ["配置", ".env", "✗ 必须搬", "含密钥、格式白名单、SECRET_KEY"],
        ["业务数据", "storage/business.db", "✗ 必须搬", "账号、任务、文档记录"],
        ["知识库", "storage/kb.db", "✓ 目前是空表", "建库时自动生成"],
        ["上传文件", "storage/uploads/", "✗ 建议搬", "用户传的原始课件，任务导出要用"],
        ["虚拟环境", ".venv/", "✓ 新机重建", "跨机器不能用，别拷"],
    ], widths=[3.2, 6.0, 3.6, 5.0])

    body(doc, "一句话：**除 .venv 外，整目录搬过去就行**。", color=GREY)

    h1(doc, "二、迁移前先想清楚三件事")

    table(doc, ["问题", "影响", "建议"], [
        ["公网 IP 会变", "访问地址从旧 IP 变成新 IP，老师同学手里的链接失效",
         "! 如果还要长期用，建议绑个域名（几元/年），以后换机只改解析"],
        ["SECRET_KEY 变了", "所有人登录态失效，要重新登录",
         "! 保留旧 .env 就没事，别让 deploy.sh 重新生成"],
        ["旧服务器到期后数据没了", "无法再补救", "! 迁移完成并验证后，旧机再留 2~3 天做回滚"],
    ], widths=[4.0, 6.4, 6.6])

    h1(doc, "三、操作步骤（照着做）")

    body(doc, "第 1 步：在【旧服务器】打包（会自动暂停服务保证数据一致，完成后自动恢复）", bold=True)
    code(doc, """
cd /root/course-note-agent
bash scripts/migrate_backup.sh
""")
    body(doc, "脚本会输出压缩包路径、大小和 SHA256，例如："
              "/root/course-note-agent-migrate-20261105-2330.tar.gz", indent=0.3)

    body(doc, "第 2 步：把包下载到本地（在【你自己电脑的 PowerShell】里执行，不是在服务器上）", bold=True)
    code(doc, """
scp root@旧服务器IP:/root/course-note-agent-migrate-*.tar.gz .
""")

    body(doc, "第 3 步：上传到新服务器（同样在你自己电脑上执行）", bold=True)
    code(doc, """
scp course-note-agent-migrate-*.tar.gz root@新服务器IP:/root/
""")

    body(doc, "第 4 步：在【新服务器】解压并部署", bold=True)
    code(doc, """
mkdir -p /root/course-note-agent
tar xzf /root/course-note-agent-migrate-*.tar.gz -C /root/course-note-agent
cd /root/course-note-agent
bash deploy.sh
""")
    body(doc, "deploy.sh 会自动：装系统依赖 → 建 venv → 装 requirements → 初始化数据库 → "
              "注册 systemd 服务（开机自启、崩溃重启）→ 打印访问地址。"
              "它会沿用已有的 .env 和 storage/，不会覆盖你的数据和密钥。", indent=0.3)

    body(doc, "第 5 步：控制台放行端口（最容易漏）", bold=True)
    body(doc, "新服务器默认只开 22。必须在安全组入方向加：", indent=0.3)
    table(doc, ["字段", "填什么"], [
        ["协议", "自定义 TCP"],
        ["端口", "8000/8000"],
        ["授权对象", "0.0.0.0/0"],
    ], widths=[4.0, 10.0])
    body(doc, "不加这条的表现：服务器上 curl 127.0.0.1:8000 正常，但外部打不开。", color=GREY, indent=0.3)

    body(doc, "第 6 步：验证", bold=True)
    code(doc, """
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/meta | head -c 300
systemctl status course-note-agent --no-pager | head -5
""")
    body(doc, "然后从外网（手机流量）打开 http://新IP:8000，登录看历史任务是否还在。", indent=0.3)

    h1(doc, "四、换域名的话更省事（推荐）")

    body(doc, "如果以后还会换服务器，花几块钱买个域名并解析到新 IP，"
              "以后换机只改解析记录，访问地址永远不变。")
    body(doc, "注意：国内服务器绑定域名对外提供 Web 服务需要备案；"
              "如果只是用 IP+端口访问，则不需要备案。", color=GREY)

    h1(doc, "五、常见问题")
    table(doc, ["现象", "原因", "处理"], [
        ["deploy.sh 报 python3.12 找不到", "新机是 Ubuntu 22.04 自带 3.10", "脚本会自动装 deadsnakes PPA，失败则回退系统 python3，能跑"],
        ["服务起来但接口 500", "storage 没搬或权限不对", "确认 storage/ 存在且 root 可读；重跑 init_db"],
        ["登录后立刻退出", "SECRET_KEY 变了", "确认 .env 是旧机那份，没被重新生成"],
        ["上传历史文件 404", "storage/uploads 没搬", "重搬 storage 目录"],
        ["外部打不开、本机正常", "安全组没放行", "控制台加入方向 8000"],
    ], widths=[5.0, 5.2, 6.8])

    doc.add_paragraph()
    body(doc, "配套脚本：scripts/migrate_backup.sh（旧机打包）、deploy.sh（新机部署）", color=GREY)
    return doc


def main() -> int:
    doc = build()
    written, note = save_with_retry(doc, OUTPUT)
    print(f"[ok] 已生成：{written}")
    print(f"[ok] 大小：{written.stat().st_size:,} 字节")
    if note:
        print(f"[warn] {note}")
    print(f"[ok] 校验：{len(Document(str(written)).paragraphs)} 段落")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
