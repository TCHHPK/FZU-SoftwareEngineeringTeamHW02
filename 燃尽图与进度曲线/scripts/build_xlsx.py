# -*- coding: utf-8 -*-
"""生成《进度与燃尽数据》Excel（含可编辑原生图表）。输出到本目录，不入库。"""
import csv

from pathlib import Path
import xlsxwriter

BASE = Path(__file__).resolve().parents[1]
OUT = str(BASE / "进度与燃尽数据.xlsx")

rows = list(csv.DictReader(open(BASE / "data" / "daily.csv", encoding="utf-8-sig")))
n = len(rows)
FIRST = 3                 # 0-based 首条数据行
LAST = FIRST + n - 1

wb = xlsxwriter.Workbook(OUT)
wb.set_properties({
    "title": "天生一队 Alpha 冲刺 进度与燃尽数据",
    "subject": "2026 秋软件工程与软件工程实践 第三次团队作业",
    "author": "吴雅晴",
    "company": "福州大学 计算机与大数据学院 天生一队",
})

F = {}
F["title"] = wb.add_format({"bold": True, "font_size": 15, "font_color": "#1F3864",
                            "font_name": "微软雅黑"})
F["sub"] = wb.add_format({"font_size": 9, "font_color": "#6B7280", "font_name": "微软雅黑"})
F["h"] = wb.add_format({"bold": True, "font_size": 9, "font_color": "#FFFFFF",
                        "bg_color": "#1F3864", "align": "center", "valign": "vcenter",
                        "border": 1, "border_color": "#1F3864", "text_wrap": True,
                        "font_name": "微软雅黑"})
F["t"] = wb.add_format({"font_size": 9, "valign": "vcenter", "border": 1,
                        "border_color": "#D5DCE8", "text_wrap": True})
F["tc"] = wb.add_format({"font_size": 9, "valign": "vcenter", "border": 1,
                         "border_color": "#D5DCE8", "align": "center"})
F["n"] = wb.add_format({"font_size": 9, "num_format": "0.0", "align": "center",
                        "border": 1, "border_color": "#D5DCE8"})
F["z"] = wb.add_format({"font_size": 9, "align": "center", "border": 1,
                        "border_color": "#D5DCE8", "bg_color": "#F7F9FC"})
F["zn"] = wb.add_format({"font_size": 9, "num_format": "0.0", "align": "center",
                         "border": 1, "border_color": "#D5DCE8", "bg_color": "#F7F9FC"})
F["zt"] = wb.add_format({"font_size": 9, "valign": "vcenter", "border": 1,
                         "border_color": "#D5DCE8", "bg_color": "#F7F9FC", "text_wrap": True})
F["note"] = wb.add_format({"font_size": 8.5, "font_color": "#6B7280", "italic": True,
                           "font_name": "微软雅黑"})

SHEET = "01-进度与燃尽数据"

# ---------------- Sheet 1 ----------------
ws = wb.add_worksheet(SHEET)
ws.hide_gridlines(2)
ws.set_column("A:A", 9)
ws.set_column("B:B", 58)
ws.set_column("C:H", 12)
ws.set_column("I:I", 3)
ws.set_column("J:S", 11)

ws.write("A1", "天生一队 · Alpha 冲刺 进度曲线与燃尽图数据", F["title"])
ws.write("A2", "统计口径：12 个工作包按计划工作量占比折算权重，合计 100 点；工作包验收通过当日计入累计完成度。"
              "数据截至 2026-11-20 24:00。", F["sub"])

heads = ["日期", "当日完成 / 里程碑", "计划累计%", "实际累计%",
         "计划剩余", "实际剩余", "理想剩余", "偏差(计划-实际)"]
for i, h in enumerate(heads):
    ws.write(2, i, h, F["h"])
ws.set_row(2, 30)

for i, r in enumerate(rows):
    rr = FIRST + i
    zebra = i % 2 == 1
    tf, nf = (F["zt"], F["zn"]) if zebra else (F["t"], F["n"])
    cf = F["z"] if zebra else F["tc"]
    planned = float(r["planned"])
    actual = float(r["actual"])
    ideal = round(100 - 100 * i / (n - 2), 1) if i <= n - 2 else 0.0
    ws.write(rr, 0, r["date"][5:], cf)
    ws.write(rr, 1, r["note"], tf)
    ws.write_number(rr, 2, planned, nf)
    ws.write_number(rr, 3, actual, nf)
    ws.write_number(rr, 4, round(100 - planned, 1), nf)
    ws.write_number(rr, 5, round(100 - actual, 1), nf)
    ws.write_number(rr, 6, ideal, nf)
    ws.write_number(rr, 7, round(planned - actual, 1), nf)

# 图 1：进度曲线
ch = wb.add_chart({"type": "line"})
ch.add_series({
    "name": "计划进度",
    "categories": [SHEET, FIRST, 0, LAST, 0],
    "values": [SHEET, FIRST, 2, LAST, 2],
    "line": {"color": "#8B949E", "width": 1.75, "dash_type": "dash"},
    "marker": {"type": "none"},
})
ch.add_series({
    "name": "实际进度",
    "categories": [SHEET, FIRST, 0, LAST, 0],
    "values": [SHEET, FIRST, 3, LAST, 3],
    "line": {"color": "#1F6FEB", "width": 2.25},
    "marker": {"type": "circle", "size": 5, "border": {"color": "#1F6FEB"},
               "fill": {"color": "#FFFFFF"}},
})
ch.set_title({"name": "项目实际进度曲线", "name_font": {"size": 12, "bold": True,
                                                       "color": "#1F3864"}})
ch.set_x_axis({"name": "日期", "name_font": {"size": 9}, "num_font": {"size": 8},
               "line": {"color": "#C9CED6"}})
ch.set_y_axis({"name": "累计完成度（%）", "min": 0, "max": 100, "major_unit": 20,
               "name_font": {"size": 9}, "num_font": {"size": 8},
               "major_gridlines": {"visible": True, "line": {"color": "#E6E8EB"}},
               "line": {"none": True}})
ch.set_legend({"position": "top", "font": {"size": 8}})
ch.set_size({"width": 640, "height": 310})
ch.set_chartarea({"border": {"none": True}, "fill": {"color": "#FFFFFF"}})
ws.insert_chart("J2", ch)

# 图 2：燃尽图
ch2 = wb.add_chart({"type": "line"})
ch2.add_series({
    "name": "理想燃尽线",
    "categories": [SHEET, FIRST, 0, LAST, 0],
    "values": [SHEET, FIRST, 6, LAST, 6],
    "line": {"color": "#8B949E", "width": 1.5, "dash_type": "dash"},
    "marker": {"type": "none"},
})
ch2.add_series({
    "name": "计划剩余",
    "categories": [SHEET, FIRST, 0, LAST, 0],
    "values": [SHEET, FIRST, 4, LAST, 4],
    "line": {"color": "#2F9E44", "width": 1.5, "dash_type": "round_dot"},
    "marker": {"type": "none"},
})
ch2.add_series({
    "name": "实际剩余",
    "categories": [SHEET, FIRST, 0, LAST, 0],
    "values": [SHEET, FIRST, 5, LAST, 5],
    "line": {"color": "#C92A2A", "width": 2.25},
    "marker": {"type": "circle", "size": 5, "border": {"color": "#C92A2A"},
               "fill": {"color": "#FFFFFF"}},
})
ch2.set_title({"name": "项目燃尽图", "name_font": {"size": 12, "bold": True,
                                                  "color": "#1F3864"}})
ch2.set_x_axis({"name": "日期", "name_font": {"size": 9}, "num_font": {"size": 8},
                "line": {"color": "#C9CED6"}})
ch2.set_y_axis({"name": "剩余工作量（点）", "min": 0, "max": 100, "major_unit": 20,
                "name_font": {"size": 9}, "num_font": {"size": 8},
                "major_gridlines": {"visible": True, "line": {"color": "#E6E8EB"}},
                "line": {"none": True}})
ch2.set_legend({"position": "top", "font": {"size": 8}})
ch2.set_size({"width": 640, "height": 310})
ch2.set_chartarea({"border": {"none": True}, "fill": {"color": "#FFFFFF"}})
ws.insert_chart("J20", ch2)

ws.write(LAST + 2, 0,
         "说明：理想燃尽线按 11.07—11.21 匀速归零计算（共 15 天）；实际剩余 = 100 − 实际累计完成度。"
         "11.21 / 11.22 为计划与截止日值，实际数据截止 11.20。", F["note"])
ws.freeze_panes(FIRST, 2)

# ---------------- Sheet 2 ----------------
ws2 = wb.add_worksheet("02-工作分解")
ws2.hide_gridlines(2)
ws2.set_column("A:A", 7)
ws2.set_column("B:B", 40)
ws2.set_column("C:C", 20)
ws2.set_column("D:D", 8)
ws2.set_column("E:F", 10)
ws2.set_column("G:G", 30)
ws2.write("A1", "冲刺工作分解与权重（合计 100%）", F["title"])
wbs = [
    ("W01", "前期复盘与改进方案（MVP 边界、降级预案、分工）", "吴政迅 / 全员", "8%", "11.15", "11.15", "冲刺计划 v2 第 1—3 节定稿"),
    ("W02", "第二次作业收尾（UML、说明书、验收报告入库）", "张佩琪 / 陈瑀涵 / 徐张睿", "6%", "11.09", "11.08", "11.08 仓库 12 次提交"),
    ("W03", "契约冻结：4 张新表 + 9 个接口字段", "徐张睿", "6%", "11.16", "11.16", "11.17 站会确认；1.0.0 基线"),
    ("W04", "迁移脚本与数据层（幂等迁移、老库补列）", "蔡靖熹 / 章玲", "8%", "11.17", "11.18", "002_learning_loop.sql；PR #2"),
    ("W05", "智能自测后端（4 接口 + 判分事务 + 幂等）", "徐张睿", "12%", "11.17", "11.20", "合并说明：main 缺自测，11.20 补齐"),
    ("W06", "错题本后端（3 接口 + 薄弱度聚合 + 连对掌握）", "沈文驰", "9%", "11.18", "11.18", "PR #2 于 11.18 18:18 合入"),
    ("W07", "Agent 出题 + 导图树数据接口", "陈瑀涵", "9%", "11.18", "11.19", "提交 ea274418（11.19 14:48）"),
    ("W08", "前端三页面（U13 / U14 / U15）与路由接入", "陈佳慧 / 梁倩", "14%", "11.18", "11.19", "frontend/ 与 app/static 产物"),
    ("W09", "前后端联调、线上部署与回归冒烟", "蔡靖熹", "8%", "11.19", "11.20", "1.2.0 打包部署"),
    ("W10", "测试执行与回归（58 + 4 项、三条演示路径）", "张佩琪 / 吴雅晴", "8%", "11.20", "11.20", "测试记录见 Sheet 03"),
    ("W11", "答辩 PPT", "王可人 / 梁倩", "7%", "11.20", "11.20", "PPT 定稿并进仓库"),
    ("W12", "冲刺总结博客、vlog、release 发布", "吴政迅 / 庄剑钇", "5%", "11.21", "待完成", "计划 11.21 23:59 前"),
]
h2 = ["编号", "工作包", "负责人", "权重", "计划完成", "实际完成", "判定依据"]
for i, h in enumerate(h2):
    ws2.write(2, i, h, F["h"])
ws2.set_row(2, 26)
for i, row in enumerate(wbs):
    rr = 3 + i
    zebra = i % 2 == 1
    tf = F["zt"] if zebra else F["t"]
    cf = F["z"] if zebra else F["tc"]
    for ci, val in enumerate(row):
        ws2.write(rr, ci, val, tf if ci in (1, 2, 6) else cf)
ws2.freeze_panes(3, 0)

# ---------------- Sheet 3 ----------------
ws3 = wb.add_worksheet("03-测试记录")
ws3.hide_gridlines(2)
ws3.set_column("A:A", 32)
ws3.set_column("B:B", 11)
ws3.set_column("C:C", 72)
ws3.set_column("D:D", 14)
ws3.write("A1", "测试用例分布与执行结果", F["title"])
ws3.write("A2", "后端 58 项（pytest）+ 前端 4 项（node --test），合计 62 项。", F["sub"])

ws3.write(3, 0, "用例文件 / 模块", F["h"])
ws3.write(3, 1, "用例数", F["h"])
ws3.write(3, 2, "覆盖的关键行为", F["h"])
mods = [
    ("tests/test_contracts.py", 7, "双库初始化、口令哈希、FTS5 检索、引文回查、JSON 降级、Agent IO 契约、.env 行内注释"),
    ("tests/test_parse.py", 17, "PDF/PPTX/DOCX/TXT/MD/CSV/HTML 解析、页码与分块键、扫描件不伪造、格式嗅探"),
    ("tests/test_api.py", 10, "鉴权、伪造令牌、上传校验、整理→结果→导出、越权隔离、管理端"),
    ("tests/test_agent_pipeline.py", 3, "不可核验条目过滤、去重合并、覆盖率评测"),
    ("tests/test_agent_quiz.py", 5, "出题校验、非法项丢弃、出处回填、无密钥/异常降级"),
    ("tests/test_self_test.py", 4, "取卷不下发答案、判分、错题回填去重、幂等与跨用户 404"),
    ("tests/test_wrong_book.py", 10, "判分归一化、薄弱度聚合、越权 404、连对掌握、答错打回、筛选"),
    ("tests/test_learning_loop_migration.py", 2, "4 张新表建表、老库升级补列"),
    ("frontend/tests/mindmap.test.mjs", 4, "树构建、折叠状态、节点摘要与出处页码"),
]
for i, (f, c, d) in enumerate(mods):
    rr = 4 + i
    zebra = i % 2 == 1
    tf = F["zt"] if zebra else F["t"]
    cf = F["z"] if zebra else F["tc"]
    ws3.write(rr, 0, f, tf)
    ws3.write_number(rr, 1, c, cf)
    ws3.write(rr, 2, d, tf)

ws3.write(15, 0, "检查项", F["h"])
ws3.write(15, 1, "结果", F["h"])
ws3.write(15, 2, "证据 / 说明", F["h"])
res = [
    ("后端全量回归 python -m pytest", "58 passed", "1.2.0 发布前；合并说明与 VERSION 记录一致"),
    ("前端单测 node --test", "4 passed", "前端构建产物同批验证"),
    ("端到端自检 e2e_smoke.py", "通过", "注册→上传→整理→结果→导出→检索→越权"),
    ("学习闭环联调 smoke_learning_loop.py", "通过", "自测→判分→错题库→薄弱度→导图→导出"),
    ("接口总数", "27 个", "原 22 + 错题 3 + 自测 4 − 路径去重 2"),
    ("本文复核（2026-11-20）", "83/83 编译通过", "全量源码语法编译；58 + 4 项用例在位"),
]
for i, (a, b, c) in enumerate(res):
    rr = 16 + i
    zebra = i % 2 == 1
    tf = F["zt"] if zebra else F["t"]
    cf = F["z"] if zebra else F["tc"]
    ws3.write(rr, 0, a, tf)
    ws3.write(rr, 1, b, cf)
    ws3.write(rr, 2, c, tf)

ws3.write(23, 0, "编号", F["h"])
ws3.write(23, 1, "现象", F["h"])
ws3.write(23, 2, "根因 → 修复", F["h"])
ws3.write(23, 3, "验证", F["h"])
bugs = [
    ("D01", "导图生成接口 500", "占位符与参数个数不一致 → 对齐", "复测通过"),
    ("D02", "自测接口 500", "缺 error_message 列、CHECK 不含 failed → 迁移补列", "迁移用例通过"),
    ("D03", "组卷后取卷为空", "draft 状态就渲染 → 轮询到 ready", "取卷用例覆盖"),
    ("D04", "交卷字段不一致", "补 correct_answer 别名", "交卷断言通过"),
    ("D05", "重做缺选项", "详情回填 options / question_type", "重做用例通过"),
    ("D06", "节点标题撑爆", "名称清洗截断 20 字", "前端单测覆盖"),
    ("D07", "导图路由不生效", "文件在仓库根目录 → 移入 app/api 并注册", "联调通过"),
]
for i, b in enumerate(bugs):
    rr = 24 + i
    ws3.set_row(rr, 22)
    zebra = i % 2 == 1
    tf = F["zt"] if zebra else F["t"]
    cf = F["z"] if zebra else F["tc"]
    for ci, val in enumerate(b):
        ws3.write(rr, ci, val, cf if ci in (0, 3) else tf)

wb.close()
print("saved", OUT)
