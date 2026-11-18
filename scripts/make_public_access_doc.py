"""生成《如何让 Agent 支持公网访问》说明文档，供组员/同学参考。

背景：章玲自己做的 Agent 只能在同一个 WiFi 下访问，问怎么才能用一个公网地址访问。
      本文把我方（课程笔记 Agent）的做法拆成原理 + 三条路线 + 实操步骤。

用法：python scripts/make_public_access_doc.py
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
OUTPUT = ROOT.parent / "如何让Agent支持公网访问.docx"

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


def h2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(9)
    p.paragraph_format.space_after = Pt(3)
    set_font(p.add_run(text), name="微软雅黑", size=11.5, bold=True)


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

    title(doc, "如何让 Agent 支持公网访问")
    subtitle(doc, "从一个只能在同 WiFi 打开的本地服务，到任何人用网址就能用")

    h1(doc, "一、先搞清楚为什么只能在同一个 WiFi 下用")

    body(doc, "本机跑起来的服务，默认只监听 127.0.0.1（本机回环地址）。这意味着只有"
              "「这台机器自己」能访问，连隔壁工位的电脑都访问不到。要让它被别人访问，"
              "必须同时满足三个条件：")

    table(doc, ["条件", "你现在的情况", "要做的事"], [
        ["① 监听地址允许外部连接", "多为 127.0.0.1", "改成 0.0.0.0（监听所有网卡）"],
        ["② 对方能路由到你这台机器", "你的电脑在路由器后面，没有公网 IP", "云服务器 或 内网穿透"],
        ["③ 中间没有防火墙拦截", "宿舍/公司网络通常会拦入站", "放行端口（云上叫安全组）"],
    ], widths=[5.0, 6.0, 6.0])

    body(doc, "常见误解：以为「本地能跑通」就等于「别人能访问」。实际差的是 ② 和 ③——"
              "你缺的是一个公网可达的入口，而不是缺代码。", color=GREY)

    h1(doc, "二、三条路线，按推荐顺序")

    table(doc, ["路线", "适合场景", "地址是否固定", "电脑关机后", "成本"], [
        ["① 云服务器部署（我们用这个）", "要给别人长期访问、要交作业演示", "固定（公网 IP 或域名）", "✓ 照常可用", "学生机约 ¥10~40/月"],
        ["② 内网穿透（cpolar / 花生壳 / cloudflared）", "临时演示、不想买服务器", "免费版会变", "✗ 立即失效", "免费版够用"],
        ["③ 只在本机 localhost 演示", "现场答辩、完全不依赖网络", "仅本机", "—", "0"],
    ], widths=[5.0, 5.0, 3.4, 2.6, 3.0])

    body(doc, "如果只是答辩临时用：②+③ 组合最省事。如果要交「可访问地址」给老师检查：必须用 ①。",
         color=GREY)

    h1(doc, "三、路线①：云服务器部署（推荐，一次配好长期可用）")

    h2(doc, "1. 买一台最便宜的实例")
    body(doc, "阿里云/腾讯云的「轻量应用服务器」或「ECS 入门款」，1 核 2G 就够本项目的量级。"
              "系统选 Ubuntu 22.04。买完在控制台能看到一个「公网 IP」。")

    h2(doc, "2. 放行端口（这一步最容易被忘）")
    body(doc, "云厂商默认只开放 22 端口（SSH）。你的应用监听 8000，就必须在"
              "「安全组 / 防火墙」里加一条入方向规则：")

    table(doc, ["字段", "填什么"], [
        ["协议类型", "自定义 TCP"],
        ["端口范围", "8000/8000"],
        ["授权对象", "0.0.0.0/0（允许所有人）"],
    ], widths=[4.0, 10.0])

    body(doc, "不加这条，服务器本机 curl 是通的，但外部永远打不开——我们项目就踩过这个坑。",
         color=GREY)

    h2(doc, "3. 把代码传上去并启动")
    code(doc, """
# 本地电脑：上传代码（把路径换成你自己的）
scp -r 你的项目目录 root@你的公网IP:/root/

# 服务器：装依赖并启动
cd /root/你的项目目录
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
""")

    body(doc, "注意 --host 0.0.0.0 这个参数：它决定「只听本机」还是「听所有网卡」。"
              "写成 127.0.0.1 就等于拒绝外部访问。")

    h2(doc, "4. 用 systemd 守护，别让进程一关终端就死")
    code(doc, """
# /etc/systemd/system/my-agent.service
[Unit]
Description=My Agent
After=network-online.target

[Service]
WorkingDirectory=/root/你的项目目录
ExecStart=/root/你的项目目录/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
""")
    code(doc, """
systemctl daemon-reload
systemctl enable my-agent
systemctl restart my-agent
systemctl status my-agent --no-pager
""")

    h1(doc, "四、路线②：不买服务器，用内网穿透")

    body(doc, "原理：你在本机跑一个客户端，它主动连到穿透服务商的服务器，"
              "服务商给你一个公网地址，把请求转发回你本机。因为是你主动连出去，"
              "所以不需要公网 IP，也不用手动做端口映射。")

    table(doc, ["工具", "命令或操作", "备注"], [
        ["cloudflared（免注册）", "cloudflared tunnel --url http://127.0.0.1:8000", "给一个 trycloudflare.com 地址，国内访问不稳定"],
        ["cpolar", "cpolar http 8000", "需注册，国内线路较稳，免费版地址会变"],
        ["花生壳", "客户端里配置映射", "需实名，免费版有流量限制"],
        ["ngrok", "ngrok http 8000", "海外服务，国内可能连不上"],
    ], widths=[4.0, 6.6, 6.4])

    body(doc, "缺点要讲清楚：① 地址每次重启都变，② 你的电脑必须一直开着且不休眠，"
              "③ 大文件上传容易超时（穿透服务通常有单请求时长限制，我们试过 4 MB 的 PDF "
              "在 Cloudflare 通道上会 100 秒超时）。", color=GREY)

    h1(doc, "五、API 密钥怎么管（你担心的「别人要用我的 key」）")

    body(doc, "正确做法：key 只放在**服务端**，访问者永远看不到，也不需要提供。")

    table(doc, ["做法", "效果"], [
        ["✓ 服务端 .env 文件保存 key", "只有服务器上的程序读得到，前端页面不接触"],
        ["✓ 前端只调用你自己的后端接口", "浏览器里看不到 key，抓包也抓不到"],
        ["✓ 给访问者开账号（登录）", "用「谁在用」来控权限，而不是发 key"],
        ["✗ 把 key 写进前端代码", "打开网页源码就能看到，等于公开"],
        ["✗ 把 key 提交到 GitHub", "会被自动扫描，几分钟内被盗刷"],
    ], widths=[7.0, 10.0])

    body(doc, "另外建议：给项目单独申请一个 key，不要用你个人的主力 key，"
              "万一泄露可以单独吊销，不影响其他项目。")

    h1(doc, "六、排查清单（打不开时按顺序看）")

    table(doc, ["现象", "最可能原因", "怎么确认"], [
        ["服务器本机 curl 通，外部打不开", "安全组没放行端口", "控制台看入方向规则"],
        ["本机 curl 也不通", "服务没起 / 端口被占", "systemctl status、ss -ltnp | grep 8000"],
        ["页面能开但接口全 500", "密钥没配或数据库没初始化", "看服务日志，跑一次健康检查接口"],
        ["能开但描述成「连接被重置」", "被中间设备拦截", "换端口（8080）再试"],
        ["过一段时间就打不开", "进程被系统杀掉，没守护", "配 systemd Restart=always"],
    ], widths=[5.4, 5.0, 6.6])

    doc.add_paragraph()
    body(doc, "参考实现：课程笔记 Agent（http://47.114.55.115:8000）"
              "就是按路线①部署的——阿里云 ECS + 安全组放行 8000 + systemd 守护，"
              "代码与密钥都在服务器上，访问者只需注册账号即可使用。", color=GREY)
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
