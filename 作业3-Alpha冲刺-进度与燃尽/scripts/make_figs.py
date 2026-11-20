# -*- coding: utf-8 -*-
"""生成 Alpha 冲刺的进度曲线、燃尽图与测试分布图（中文字体 微软雅黑）。"""
import csv
import datetime as dt

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.ticker import MultipleLocator

FONT = r"C:\Windows\Fonts\msyh.ttc"
font = fm.FontProperties(fname=FONT)
plt.rcParams["font.family"] = font.get_name()
plt.rcParams["axes.unicode_minus"] = False

BASE = Path(__file__).resolve().parents[1]
OUT = str(BASE / "figs")
BASE.joinpath("figs").mkdir(exist_ok=True)

# ---- 测试分布（与 pytest 实跑结果一致后使用） ----
MODS = ["契约/配置", "解析入库", "接口权限", "Agent 管线", "Agent 出题",
        "智能自测", "错题本", "迁移脚本", "前端单测"]
COUNTS = [7, 17, 10, 3, 5, 4, 10, 2, 4]

rows = []
with open(BASE / "data" / "daily.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        rows.append(r)

days = [dt.date(int(r["date"][:4]), int(r["date"][5:7]), int(r["date"][8:])) for r in rows]
planned = [float(r["planned"]) for r in rows]
actual = [float(r["actual"]) for r in rows]
labels = [f"{d.month}.{d.day:02d}" for d in days]

CUTOFF = dt.date(2026, 11, 20)
idx_cut = max(i for i, d in enumerate(days) if d <= CUTOFF)
act_x = days[: idx_cut + 1]
act_y = actual[: idx_cut + 1]

BLUE = "#1f6feb"
GRAY = "#8b949e"
ORANGE = "#d97706"
GREEN = "#2f9e44"
RED = "#c92a2a"


def style(ax):
    ax.grid(True, which="major", color="#e6e8eb", linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color("#c9ced6")
    ax.spines["bottom"].set_color("#c9ced6")
    ax.tick_params(colors="#4a5568", labelsize=9)


def frame(ax, title, ylabel, note):
    ax.set_ylim(-4, 108)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.set_ylabel(ylabel, fontsize=10, color="#2d3748")
    ax.set_xticks(days)
    ax.set_xticklabels(labels, fontsize=8.4)
    ax.set_xlim(days[0] - dt.timedelta(days=0.4), days[-1] + dt.timedelta(days=0.3))
    ax.set_title(title, fontsize=13, color="#1a202c", pad=12, loc="left")
    ax.text(1, 1.005, note, transform=ax.transAxes, ha="right", va="bottom",
            fontsize=8.2, color="#718096")
    style(ax)


# ---------------- 图 1：进度曲线 ----------------
fig, ax = plt.subplots(figsize=(9.2, 4.9), dpi=200)
ax.fill_between(days, planned, actual, where=[p >= a for p, a in zip(planned, actual)],
                color=ORANGE, alpha=0.10, interpolate=True, zorder=1)
ax.plot(days, planned, color=GRAY, linewidth=1.9, linestyle=(0, (5, 3)),
        label="计划进度（冲刺计划 v2 里程碑）", zorder=3)
ax.plot(act_x, act_y, color=BLUE, linewidth=2.4, marker="o", markersize=5.0,
        markerfacecolor="white", markeredgewidth=1.7, label="实际进度（截至 11.20）", zorder=4)
ax.plot([days[idx_cut], days[idx_cut + 1]], [actual[idx_cut], actual[idx_cut + 1]],
        color=BLUE, linewidth=1.9, linestyle=(0, (2, 2)), alpha=0.8, zorder=4)
ax.scatter([days[idx_cut + 1]], [actual[idx_cut + 1]], s=40, facecolor="white",
           edgecolor=BLUE, linewidth=1.6, zorder=5)

marks = [
    (dt.date(2026, 11, 9), 6, "二次作业收尾\nUML·说明书入库", 0, 20, "center", "bottom"),
    (dt.date(2026, 11, 16), 20, "契约冻结\n4 表·9 接口", 8, -34, "left", "top"),
    (dt.date(2026, 11, 19), 60, "深夜集中合入\n三功能落地", -6, 32, "center", "bottom"),
    (dt.date(2026, 11, 20), 95, "测试·打包\n1.2.0 发布", -12, 18, "right", "bottom"),
]
for x, y, txt, dx, dy, ha, va in marks:
    ax.scatter([x], [y], s=44, color=ORANGE, edgecolor="white", linewidth=1.1, zorder=6)
    ax.annotate(txt, xy=(x, y), xytext=(dx, dy), textcoords="offset points",
                fontsize=8, color="#7c4a03", ha=ha, va=va)

ax.annotate("11.21 计划收尾 100%", xy=(days[idx_cut + 1], 100), xytext=(4, -30),
            textcoords="offset points", fontsize=8.2, color=BLUE, ha="left", va="top")

frame(ax, "天生一队 Alpha 冲刺项目实际进度曲线", "累计完成度（%）",
      "权重口径：12 个工作包按计划工作量占比合计 100%")
ax.legend(loc="upper left", fontsize=8.8, frameon=False)
fig.tight_layout()
fig.savefig(OUT + r"\fig1-进度曲线.png", bbox_inches="tight", facecolor="white")
plt.close(fig)

# ---------------- 图 2：燃尽图 ----------------
fig, ax = plt.subplots(figsize=(9.2, 4.9), dpi=200)
total = 100.0
n = len(days) - 1
ideal = [total - total * i / n for i in range(len(days))]
rem_planned = [total - p for p in planned]
rem_actual = [total - a for a in actual]

ax.plot(days, ideal, color=GRAY, linewidth=1.8, linestyle=(0, (6, 3)), label="理想燃尽线", zorder=3)
ax.plot(days, rem_planned, color=GREEN, linewidth=1.6, linestyle=(0, (3, 2)),
        label="计划剩余（按里程碑）", zorder=3)
ax.plot(act_x, rem_actual[: idx_cut + 1], color=RED, linewidth=2.4, marker="o", markersize=5.0,
        markerfacecolor="white", markeredgewidth=1.7, label="实际剩余", zorder=4)
ax.plot([days[idx_cut], days[idx_cut + 1]], [rem_actual[idx_cut], rem_actual[idx_cut + 1]],
        color=RED, linewidth=1.9, linestyle=(0, (2, 2)), alpha=0.8, zorder=4)
ax.scatter([days[idx_cut + 1]], [rem_actual[idx_cut + 1]], s=40, facecolor="white",
           edgecolor=RED, linewidth=1.6, zorder=5)

ax.annotate("11.10–11.18 仓库无代码合入\n剩余量停在 94→80", xy=(dt.date(2026, 11, 13), 94),
            xytext=(dt.date(2026, 11, 10), 46), fontsize=8.4, color="#4a5568",
            arrowprops=dict(arrowstyle="-", color="#a0aec0", linewidth=0.9,
                            connectionstyle="arc3,rad=-0.25"))
ax.annotate("11.20 集中合入：剩余 5 点", xy=(dt.date(2026, 11, 20), 5),
            xytext=(dt.date(2026, 11, 20), 40), fontsize=8.4, color=RED,
            ha="left", va="bottom",
            arrowprops=dict(arrowstyle="->", color=RED, linewidth=0.9,
                            connectionstyle="arc3,rad=0.15"))

frame(ax, "天生一队 Alpha 冲刺燃尽图", "剩余工作量（点，总量 100）",
      "理想燃尽窗口 11.07–11.21；11.22 00:00 为作业截止缓冲")
ax.legend(loc="upper right", fontsize=8.6, frameon=False)
fig.tight_layout()
fig.savefig(OUT + r"\fig2-燃尽图.png", bbox_inches="tight", facecolor="white")
plt.close(fig)

# ---------------- 图 3：测试用例分布 ----------------
colors = [BLUE] * 8 + [GREEN]
fig, ax = plt.subplots(figsize=(9.2, 3.5), dpi=200)
bars = ax.bar(MODS, COUNTS, color=colors, width=0.58, zorder=3)
for b, c in zip(bars, COUNTS):
    ax.text(b.get_x() + b.get_width() / 2, c + 0.3, str(c), ha="center", va="bottom",
            fontsize=9.5, color="#2d3748")
ax.set_ylim(0, max(COUNTS) + 3)
ax.set_ylabel("用例数", fontsize=10, color="#2d3748")
ax.set_title("自动化测试用例分布（后端 58 + 前端 4，合计 62）",
             fontsize=12.5, color="#1a202c", pad=10, loc="left")
ax.yaxis.set_major_locator(MultipleLocator(5))
ax.grid(True, axis="y", color="#e6e8eb", linewidth=0.8)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.tick_params(colors="#4a5568", labelsize=9.5)
fig.tight_layout()
fig.savefig(OUT + r"\fig3-测试分布.png", bbox_inches="tight", facecolor="white")
plt.close(fig)
print("charts done")
