#!/usr/bin/env python3
"""Render Drive 核心原理两页 PPT（原生形状）+ SVG/PNG 预览。

单一场景数据源，双后端发射：
  - python-pptx → drive/docs/drive-principles.pptx
  - SVG (cairosvg) → drive/docs/images/drive-principles-p{1,2}.{svg,png} 预览

用法: python3 drive/scripts/render_drive_principles_ppt.py
"""

from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

EMU_PER_IN = 914400
SLIDE_W = 13.333
SLIDE_H = 7.5
FONT = "Microsoft YaHei"

# ---------------------------------------------------------------- palette
# 技术风格：白底 + 灰阶面板 + 单一科技蓝 accent，红色仅用于失败/回炉路径
PALETTE = {
    "ink": "101828", "gray": "344054", "gray2": "667085",
    "line": "D0D5DD", "hairline": "E4E7EC", "panel": "F9FAFB",
    "deep": "1D2939", "white": "FFFFFF",
    "accent": "175CD3", "accent_lt": "EFF4FF", "accent_bd": "84ADFF", "accent_dk": "1849A9",
    # 键名保持场景代码不变，值全部映射进上面的克制配色
    "blue_bg": "EFF4FF", "blue_bd": "84ADFF", "blue_tx": "175CD3", "blue_dk": "344054",
    "blue_bg2": "1D2939", "blue_bd2": "1D2939",
    "blue_stage": "F2F4F7", "blue_stage_tx": "1D2939",
    "violet_bg": "F9FAFB", "violet_bd": "D0D5DD", "violet_tx": "101828", "violet_dk": "344054",
    "green_bg": "FFFFFF", "green_bd": "D0D5DD", "green_tx": "1D2939", "green_dk": "175CD3",
    "green_md": "175CD3", "green_stage": "EFF4FF",
    "amber_bg": "F2F4F7", "amber_bd": "D0D5DD", "amber_tx": "1D2939", "amber_md": "667085",
    "amber_bg2": "FFFFFF", "amber_bd2": "D0D5DD", "amber_dk": "1D2939", "amber_hard": "1D2939",
    "red_bg": "FFFFFF", "red_bd": "D0D5DD", "red_tx": "1D2939", "red_dk": "344054",
    "red_md": "101828", "red": "D92D20", "red_bg2": "F2F4F7", "red_bd2": "D0D5DD",
    "indigo_bg": "FFFFFF", "indigo_bd": "D0D5DD", "indigo_tx": "1D2939", "indigo_dk": "475467",
    "green_soft": "FFFFFF", "green_soft_bd": "D0D5DD",
    "amber_soft": "FFFFFF", "amber_soft_bd": "D0D5DD",
    "quote_bg": "EFF4FF", "quote_bd": "84ADFF",
}

# ------------------------------------------------------------ primitives
# box:   ("box",  x, y, w, h, fill, border, lw, radius, dash)
# text:  ("text", x, y, w, h, align, anchor, [(txt,size,bold,color), ...])
# poly:  ("poly", [(x,y),...], color, lw, arrow_end, dash)
ALIGN = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}
ANCHOR = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE}


def B(x, y, w, h, fill, border=None, lw=1.0, radius=None, dash=False):
    return ("box", x, y, w, h, fill, border, lw, radius, dash)


def T(x, y, w, h, lines, align="left", anchor="top"):
    return ("text", x, y, w, h, align, anchor, lines)


def L(txt, size, color, bold=False):
    return (txt, size, bold, color)


def P(points, color, lw=1.5, arrow=False, dash=False):
    return ("poly", points, color, lw, arrow, dash)


# ================================================================ slide 1
def slide1():
    s = []
    c = PALETTE
    # ---- title
    s.append(T(0.35, 0.10, 9.4, 0.45, [L("Drive 核心原理：长链路任务如何保证可靠执行", 23, c["ink"], True)]))
    s.append(B(9.85, 0.16, 3.18, 0.40, c["blue_bg"], c["blue_bd"], 1.0, 0.3))
    s.append(T(9.85, 0.16, 3.18, 0.40, [L("Co-Sight Harness · 5G NR 实战", 10.5, c["blue_tx"], True)],
               align="center", anchor="middle"))
    cy, ch = 0.72, 4.00  # cards band

    # ---- left card: case
    s.append(B(0.30, cy, 3.20, ch, c["red_bg"], c["red_bd"], 1.2, 0.06))
    s.append(T(0.48, cy + 0.10, 2.90, 0.30, [L("真实案例 · 5G NR 需求方案域", 13, c["red_tx"], True)]))
    s.append(T(0.48, cy + 0.44, 2.90, 2.20, [
        L("3 大阶段：需求分析/特性设计/方案设计", 9.5, c["red_dk"]),
        L("3 顶层 Skill · 39+ 子 Skill · 200+ 关键步骤", 9.5, c["red_dk"]),
        L("", 4, c["red_dk"]),
        L("改造前：无人干预完成率仅 50%", 10, c["red_md"], True),
        L("· Skill 过多 → 意图漂移，混淆需求 ID", 9.5, c["red_dk"]),
        L("· 上下文腐化 → 流程不稳定", 9.5, c["red_dk"]),
        L("· 无验证环节 → 错误直达末端", 9.5, c["red_dk"]),
        L("· 场景召回 68% · 检索召回 56%", 9.5, c["red_dk"]),
        L("· 单需求 2h+，结果不可直接交付", 9.5, c["red_dk"]),
    ]))
    s.append(B(0.48, cy + 2.78, 2.84, 1.06, c["deep"], c["deep"], 1.0, 0.06))
    s.append(T(0.48, cy + 2.78, 2.84, 1.06, [
        L("误差沿链路连乘", 10, c["white"], True),
        L("单步质量 95% → 10 步 ≈ 60%", 10.5, c["white"], True),
        L("200+ 步 → 完成率腰斩", 9.5, "E4E7EC"),
    ], align="center", anchor="middle"))
    s.append(P([(3.50, 2.72), (3.75, 2.72)], c["gray2"], 1.75, arrow=True))

    # ---- middle panel: drive engine
    s.append(B(3.75, cy, 5.60, ch, c["panel"], c["line"], 1.2, 0.06))
    s.append(T(3.90, cy + 0.10, 5.30, 0.28, [L("核心设计：控制数据外置于模型", 13, c["ink"], True)], align="center"))
    s.append(T(3.90, cy + 0.40, 5.30, 0.22,
               [L("状态 / 约束 / 验收标准由 Harness 结构保证，不靠 LLM 自觉", 9.5, c["gray"])], align="center"))
    stages = [
        ("Start", c["blue_stage"], c["blue_stage_tx"], False),
        ("Analysis", c["blue_stage"], c["blue_stage_tx"], False),
        ("Plan", c["blue_stage"], c["blue_stage_tx"], False),
        ("Executor", c["green_stage"], c["green_dk"], True),
        ("Evaluation", c["amber_bg"], c["amber_tx"], False),
    ]
    notes = [
        ["建 .drive/ 骨架", "写 intent.md"],
        ["调研员澄清需求", "→ manifest.md"],
        ["200+ 步拆成", "taskRecord + waves"],
        ["11 个原子", "SubAgent 分波调度"],
        ["L0/L1/L2 质检", "DOD 门禁 verdict"],
    ]
    sx, sy, sw, sh, gap = 3.90, cy + 0.90, 0.98, 0.52, 0.10
    for i, (name, fill, tx, hot) in enumerate(stages):
        x = sx + i * (sw + gap)
        s.append(B(x, sy, sw, sh, fill, c["green_md"] if hot else c["line"], 1.5 if hot else 1.0, 0.12))
        s.append(T(x, sy, sw, sh, [L(name, 10, tx, True)], align="center", anchor="middle"))
        if i < 4:
            s.append(P([(x + sw, sy + sh / 2), (x + sw + gap, sy + sh / 2)], c["gray2"], 1.5, arrow=True))
        note_lines = [L(t, 8, c["gray2"]) for t in notes[i]]
        s.append(T(x, sy + sh + 0.06, sw, 0.42, note_lines, align="center"))
    # 回流 arrow: Evaluation 右下角 → 左侧 → Analysis 左边上行，避开 stage 注释
    ax_out, ax_in = 9.30, 4.83
    s.append(P([(9.15, sy + sh), (ax_out, sy + sh), (ax_out, sy + sh + 0.68),
                (ax_in, sy + sh + 0.68), (ax_in, sy + sh)], c["red"], 1.5, arrow=True))
    s.append(T(5.62, sy + sh + 0.44, 3.60, 0.18,
               [L("评估不通过 → 带证据回炉重做", 9, c["red"], True)], align="center"))
    # two mechanism boxes
    s.append(B(3.90, cy + 2.56, 5.30, 0.62, c["indigo_bg"], c["indigo_bd"], 1.0, 0.08))
    s.append(T(3.90, cy + 2.56, 5.30, 0.62, [
        L("状态机 executeState.json + 文件锁", 10, c["indigo_tx"], True),
        L("状态只允许合法迁移，跨会话续跑不丢", 9, c["indigo_dk"]),
    ], align="center", anchor="middle"))
    s.append(B(3.90, cy + 3.28, 5.30, 0.62, c["amber_bg2"], c["amber_bd2"], 1.0, 0.08))
    s.append(T(3.90, cy + 3.28, 5.30, 0.62, [
        L("Hook 防护层强制不变量", 10, c["amber_dk"], True),
        L(".drive/ 写盘 default-deny · 每次流转审计留痕 run-log.jsonl", 9, c["amber_dk"]),
    ], align="center", anchor="middle"))
    s.append(P([(9.35, 2.72), (9.60, 2.72)], c["gray2"], 1.75, arrow=True))

    # ---- right card: results
    s.append(B(9.60, cy, 3.43, ch, c["green_bg"], c["green_bd"], 1.2, 0.06))
    s.append(T(9.78, cy + 0.10, 3.10, 0.30, [L("改造效果 · 4.30 穿刺实测", 13, c["green_tx"], True)]))
    metrics = [
        ("无人干预任务完成率", "50% → 100%"),
        ("端到端时延（攻关全程）", "440 → 159 分钟"),
        ("场景分析 F1（9 条测试集）", "68% → 91.25%"),
    ]
    for i, (label, value) in enumerate(metrics):
        my = cy + 0.52 + i * 0.72
        s.append(T(9.78, my, 3.10, 0.22, [L(label, 9.5, c["green_md"])]))
        s.append(T(9.78, my + 0.24, 3.10, 0.40, [L(value, 17, c["accent"], True)]))
    s.append(B(9.78, cy + 2.82, 3.10, 1.02, c["quote_bg"], c["quote_bd"], 1.0, 0.08))
    s.append(T(9.78, cy + 2.82, 3.10, 1.02, [
        L("模型未更换，", 11.5, c["accent_dk"], True),
        L("改变的是运行时控制结构", 11.5, c["accent_dk"], True),
    ], align="center", anchor="middle"))

    # ---- bottom band: capability positioning
    s.append(T(0.35, 4.88, 8.0, 0.28, [L("能力定位：预置能力 + 可编排能力", 12.5, c["ink"], True)]))
    by, bh = 5.24, 1.95
    s.append(B(0.30, by, 6.32, bh, c["blue_bg"], c["blue_bd"], 1.2, 0.06))
    s.append(T(0.52, by + 0.12, 5.95, 0.28, [L("预置能力 —— 开箱即用的可靠执行底座", 12, c["blue_tx"], True)]))
    s.append(T(0.52, by + 0.48, 5.95, 1.40, [
        L("· 7 个岗位 agent：调研 / 规划 / 工头 / 质检 + 2 个只读审查者 + HITL 中介", 9.5, c["blue_dk"]),
        L("· phase 默认五阶段流水线，每阶段结束 HITL 闸门，人审不过不往下走", 9.5, c["blue_dk"]),
        L("· 8 个 Hook 防护脚本：写盘白名单 default-deny · 合法迁移 · 审计", 9.5, c["blue_dk"]),
        L("· 3 层质检：L0 文件存在 / L1 lint·类型 / L2 LLM Judge + 5 维 rubric", 9.5, c["blue_dk"]),
    ]))
    s.append(B(6.72, by, 6.32, bh, c["violet_bg"], c["violet_bd"], 1.2, 0.06))
    s.append(T(6.94, by + 0.12, 5.95, 0.28, [L("可编排能力 —— workflow.yaml 声明即流程", 12, c["violet_tx"], True)]))
    s.append(T(6.94, by + 0.48, 5.95, 1.40, [
        L("· 增删环节 / 换 agent / 调 gate，校验过即用，不改插件代码", 9.5, c["violet_dk"]),
        L("· DAG 模式：depends_on 自定义拓扑 + 节点级 HITL gate + 复杂度策略", 9.5, c["violet_dk"]),
        L("· 4 种 agent 地址混用：drive: 内置 / 项目本地 / @CC 子 agent / plugin:", 9.5, c["violet_dk"]),
        L("· 5G NR：三层控制配置由 Harness 从口语化需求自动生成，无需人工编写", 9.5, c["violet_dk"]),
    ]))
    return s


# ================================================================ slide 2
def slide2():
    s = []
    c = PALETTE
    s.append(T(0.35, 0.08, 11.5, 0.40,
               [L("编排执行架构：五阶段流水线，Executor 内三层结构按依赖调度", 21, c["ink"], True)]))

    # ---- declaration layer
    s.append(B(0.30, 0.55, 12.73, 0.50, c["blue_bg2"], c["blue_bd2"], 1.2, 0.06))
    s.append(T(0.30, 0.55, 12.73, 0.50, [L(
        "声明层 · workflow.yaml —— 可编排入口：增删环节 / 换 agent / 调 gate，校验过即用；"
        "5G NR 的控制配置由 Harness 从需求自动生成",
        10.5, c["white"], True)], align="center", anchor="middle"))

    # ---- pipeline stages (Executor expanded)
    sty, sth, stw = 1.45, 0.50, 1.15
    small = [("Start", 0.35), ("Analysis", 1.70), ("Plan", 3.05)]
    for name, x in small:
        s.append(B(x, sty, stw, sth, c["blue_stage"], c["line"], 1.0, 0.12))
        s.append(T(x, sty, stw, sth, [L(name, 10.5, c["blue_stage_tx"], True)], align="center", anchor="middle"))
    s.append(B(11.90, sty, stw, sth, c["amber_bg"], c["amber_bd"], 1.2, 0.12))
    s.append(T(11.90, sty, stw, sth, [L("Evaluation", 10, c["amber_tx"], True)], align="center", anchor="middle"))
    s.append(P([(1.50, sty + sth / 2), (1.70, sty + sth / 2)], c["gray2"], 1.5, arrow=True))
    s.append(P([(2.85, sty + sth / 2), (3.05, sty + sth / 2)], c["gray2"], 1.5, arrow=True))
    s.append(P([(4.20, sty + sth / 2), (4.70, sty + sth / 2)], c["gray2"], 1.5, arrow=True))
    s.append(P([(11.60, sty + sth / 2), (11.90, sty + sth / 2)], c["gray2"], 1.5, arrow=True))
    sub = [("建 .drive/ 骨架", 0.35), ("澄清 → manifest.md", 1.70),
           ("拆 task + 分波", 3.05), ("L0/L1/L2 + verdict", 11.90)]
    for txt, x in sub:
        s.append(T(x - 0.10, sty + sth + 0.06, stw + 0.20, 0.20, [L(txt, 8, c["gray2"])], align="center"))
    # quality loop: Evaluation top → Analysis top
    s.append(P([(12.475, sty), (12.475, 1.22)], c["red"], 1.5))
    s.append(P([(12.475, 1.22), (2.275, 1.22)], c["red"], 1.5))
    s.append(P([(2.275, 1.22), (2.275, sty)], c["red"], 1.5, arrow=True))
    s.append(T(2.42, 1.165, 2.20, 0.14, [L("FAIL → 回流 Analysis / Plan", 8.5, c["red"], True)]))

    # ---- Executor magnifier box
    ex0, ey0, ew, eh = 4.70, 1.30, 6.90, 4.80
    s.append(B(ex0, ey0, ew, eh, "FFFFFF", c["green_md"], 2.25, 0.04))
    s.append(T(ex0 + 0.15, ey0 + 0.10, ew - 0.30, 0.26,
               [L("Executor · 三层结构：生成与评估隔离", 13, c["green_dk"], True)], align="center"))
    s.append(T(ex0 + 0.15, ey0 + 0.38, ew - 0.30, 0.20,
               [L("控制层唯一不做 LLM 推理决策的组件 —— 只按依赖顺序调度、验证、记状态", 9, c["green_md"])],
               align="center"))
    # ① orchestrator
    s.append(B(4.90, 2.10, 6.50, 0.50, c["green_soft"], c["green_soft_bd"], 1.2, 0.10))
    s.append(T(4.90, 2.10, 6.50, 0.50, [L(
        "① 协调者 Orchestrator —— 按 depends_on 依赖关系，把 200+ 步骤分波派工（wave 拓扑）",
        10, c["green_dk"], True)], align="center", anchor="middle"))
    s.append(P([(8.15, 2.60), (8.15, 2.76)], c["green_md"], 1.5, arrow=True))
    # ② workers: waves
    s.append(T(4.90, 2.76, 1.10, 0.22, [L("② 执行者", 10, c["green_dk"], True)]))
    s.append(T(4.90, 2.97, 1.10, 0.20, [L("11 个原子 SubAgent", 7.5, c["green_md"])]))
    waves = [
        ("wave 1 · 并发", 3.24, ["需求提取", "根因分析", "场景要素分析"], None),
        ("wave 2 · 并发", 3.76, ["协议分析 ★极难", "用例召回与筛选"], None),
        ("wave 3", 4.28, ["系统域变更分析"], "..."),
    ]
    bw, bh2, bx0, bgap = 1.60, 0.42, 6.05, 0.15
    for label, wy, items, note in waves:
        s.append(T(4.90, wy + 0.10, 1.05, 0.22, [L(label, 8.5, c["amber_md"], True)]))
        for j, item in enumerate(items):
            x = bx0 + j * (bw + bgap)
            hard = "★" in item
            s.append(B(x, wy, bw, bh2, c["amber_hard"] if hard else c["green_bg"],
                       c["amber_hard"] if hard else c["green_bd"], 1.2, 0.10))
            s.append(T(x, wy, bw, bh2,
                       [L(item, 9, c["white"] if hard else c["green_tx"], hard)],
                       align="center", anchor="middle"))
        if note:
            s.append(B(bx0 + bw + bgap, wy, 3.35, bh2, "FFFFFF", c["line"], 1.0, 0.10, dash=True))
            s.append(T(bx0 + bw + bgap, wy, 3.35, bh2,
                       [L(note + " 共 11 个，每个只承载单一领域垂直知识", 8.5, c["gray2"])],
                       align="center", anchor="middle"))
    s.append(T(6.05, 4.78, 5.40, 0.18, [L(
        "wave 内并发 spawn · wave 间 barrier 强对账（task_id 不符拒写状态）· 失败 3-retry 预算重试",
        8, c["amber_md"])]))
    # ③ reviewer
    s.append(B(4.90, 5.10, 6.50, 0.62, c["amber_soft"], c["amber_soft_bd"], 1.2, 0.10))
    s.append(T(4.90, 5.10, 6.50, 0.62, [
        L("③ 校验者 ReviewAgent —— DOD 验收标准门禁 + 8 类审查规则（格式 + 业务校验）", 10, c["amber_dk"], True),
        L("不通过 → 带证据回炉，两次修不掉停下问人", 8.5, c["amber_dk"]),
    ], align="center", anchor="middle"))
    # 回炉 arrow (right channel)
    s.append(P([(11.40, 5.41), (11.52, 5.41), (11.52, 2.35), (11.40, 2.35)], c["red"], 1.5, arrow=True))
    # bottom strip
    s.append(B(4.90, 5.84, 6.50, 0.26, c["panel"], c["line"], 0.75, 0.06))
    s.append(T(4.90, 5.84, 6.50, 0.26, [L(
        "生成与评估隔离 —— 单体 Agent「无验证环节、错误直达末端」的对症药", 9, c["gray"])],
        align="center", anchor="middle"))

    # ---- guard base & persistence
    s.append(B(0.30, 6.32, 12.73, 0.50, c["red_bg2"], c["red_bd2"], 1.2, 0.06))
    s.append(T(0.30, 6.32, 12.73, 0.50, [L(
        "制度底座 · Hook 强制不变量：.drive/ 写盘 default-deny 白名单 · 状态机合法迁移 · run-log.jsonl 审计留痕"
        " ＋ 双重 HITL 闸门（权限弹窗，不可绕过）＋ 3-retry 上限",
        10, c["red_tx"], True)], align="center", anchor="middle"))
    s.append(B(0.30, 6.92, 12.73, 0.40, c["panel"], c["line"], 1.0, 0.06))
    s.append(T(0.30, 6.92, 12.73, 0.40, [L(
        ".drive/<plan_dir>/ 控制数据全落盘：目标与计划 · 状态与检查点 · 过程产物 · 经验沉淀"
        " —— 跨会话不丢，中断从断点续跑",
        9.5, c["gray"])], align="center", anchor="middle"))
    return s


# ================================================================ emitters
def _rgb(hex_str):
    return RGBColor.from_string(hex_str)


def _set_run(run, txt, size, bold, color):
    run.text = txt
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.color.rgb = _rgb(color)
    f.name = FONT
    rPr = run._r.get_or_add_rPr()
    ea = etree.SubElement(rPr, qn("a:ea"))
    ea.set("typeface", FONT)


def _arrowhead(line, dash=False):
    ln = line._get_or_add_ln()
    ln.set("cap", "rnd")
    if dash:
        d = etree.SubElement(ln, qn("a:prstDash"))
        d.set("val", "dash")
    tail = etree.SubElement(ln, qn("a:tailEnd"))
    tail.set("type", "triangle")
    tail.set("w", "med")
    tail.set("len", "med")


def emit_pptx(scenes, out_path):
    prs = Presentation()
    prs.slide_width = Emu(int(SLIDE_W * EMU_PER_IN))
    prs.slide_height = Emu(int(SLIDE_H * EMU_PER_IN))
    blank = prs.slide_layouts[6]
    for scene in scenes:
        slide = prs.slides.add_slide(blank)
        for prim in scene:
            kind = prim[0]
            if kind == "box":
                _, x, y, w, h, fill, border, lw, radius, dash = prim
                shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
                sp = slide.shapes.add_shape(shape_type, Emu(int(x * EMU_PER_IN)),
                                            Emu(int(y * EMU_PER_IN)), Emu(int(w * EMU_PER_IN)),
                                            Emu(int(h * EMU_PER_IN)))
                if radius:
                    try:
                        sp.adjustments[0] = min(0.5, radius / min(w, h))
                    except (IndexError, ValueError):
                        pass
                sp.fill.solid()
                sp.fill.fore_color.rgb = _rgb(fill)
                if border:
                    sp.line.color.rgb = _rgb(border)
                    sp.line.width = Pt(lw)
                    if dash:
                        _arrowhead(sp.line, dash=True)  # reuses prstDash setter
                        sp.line._get_or_add_ln().remove(
                            sp.line._get_or_add_ln().find(qn("a:tailEnd")))
                else:
                    sp.line.fill.background()
                sp.shadow.inherit = False
            elif kind == "text":
                _, x, y, w, h, align, anchor, lines = prim
                tb = slide.shapes.add_textbox(Emu(int(x * EMU_PER_IN)), Emu(int(y * EMU_PER_IN)),
                                              Emu(int(w * EMU_PER_IN)), Emu(int(max(h, 0.2) * EMU_PER_IN)))
                tf = tb.text_frame
                tf.word_wrap = False
                tf.vertical_anchor = ANCHOR[anchor]
                for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
                    setattr(tf, m, 0)
                for i, (txt, size, bold, color) in enumerate(lines):
                    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    p.alignment = ALIGN[align]
                    p.space_before = Pt(0)
                    p.space_after = Pt(0 if i == len(lines) - 1 else 2)
                    p.line_spacing = 1.0
                    _set_run(p.add_run(), txt, size, bold, color)
            elif kind == "poly":
                _, pts, color, lw, arrow, dash = prim
                for i in range(len(pts) - 1):
                    (x1, y1), (x2, y2) = pts[i], pts[i + 1]
                    conn = slide.shapes.add_connector(
                        MSO_CONNECTOR.STRAIGHT, Emu(int(x1 * EMU_PER_IN)), Emu(int(y1 * EMU_PER_IN)),
                        Emu(int(x2 * EMU_PER_IN)), Emu(int(y2 * EMU_PER_IN)))
                    conn.line.color.rgb = _rgb(color)
                    conn.line.width = Pt(lw)
                    conn.shadow.inherit = False
                    if dash:
                        ln = conn.line._get_or_add_ln()
                        d = etree.SubElement(ln, qn("a:prstDash"))
                        d.set("val", "dash")
                    if arrow and i == len(pts) - 2:
                        _arrowhead(conn.line)
    prs.save(out_path)


def _svg_escape(txt):
    return txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def emit_svg(scene, out_path):
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SLIDE_W}in" height="{SLIDE_H}in" '
        f'viewBox="0 0 {SLIDE_W * 100} {SLIDE_H * 100}">',
        "<defs>",
        '<marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="CONTEXT"/></marker>',
        "</defs>",
        f'<rect x="0" y="0" width="{SLIDE_W * 100}" height="{SLIDE_H * 100}" fill="white"/>',
    ]
    marker_colors = set()

    def marker(color):
        if color not in marker_colors:
            marker_colors.add(color)
        return f"arr-{color}"

    for prim in scene:
        kind = prim[0]
        if kind == "box":
            _, x, y, w, h, fill, border, lw, radius, dash = prim
            rx = min(radius or 0, 6)
            dashattr = ' stroke-dasharray="6 4"' if dash else ""
            parts.append(
                f'<rect x="{x*100:.1f}" y="{y*100:.1f}" width="{w*100:.1f}" height="{h*100:.1f}" '
                f'rx="{rx:.1f}" fill="#{fill}"'
                + (f' stroke="#{border}" stroke-width="{lw}"{dashattr}' if border else "") + "/>")
        elif kind == "text":
            _, x, y, w, h, align, anchor, lines = prim
            total = sum(size * 1.55 for _, size, _, _ in lines)
            if anchor == "middle":
                cur_y = y * 100 + (h * 100 - total) / 2 + lines[0][1] * 0.98
            else:
                cur_y = y * 100 + lines[0][1] * 0.98
            tx = {"left": x * 100 + 2, "center": (x + w / 2) * 100, "right": (x + w) * 100 - 2}[align]
            anchorattr = {"left": "start", "center": "middle", "right": "end"}[align]
            parts.append(
                f'<text x="{tx:.1f}" y="{cur_y:.1f}" text-anchor="{anchorattr}" '
                f'font-family="{FONT}, WenQuanYi Micro Hei">')
            for i, (txt, size, bold, color) in enumerate(lines):
                dy = 0 if i == 0 else size * 1.55
                weight = "bold" if bold else "normal"
                parts.append(
                    f'<tspan x="{tx:.1f}" dy="{dy:.1f}" font-size="{size * 1.35:.1f}" '
                    f'font-weight="{weight}" fill="#{color}">{_svg_escape(txt)}</tspan>')
            parts.append("</text>")
        elif kind == "poly":
            _, pts, color, lw, arrow, dash = prim
            ptstr = " ".join(f"{x*100:.1f},{y*100:.1f}" for x, y in pts)
            dashattr = ' stroke-dasharray="6 4"' if dash else ""
            mk = f' marker-end="url(#{marker(color)})"' if arrow else ""
            parts.append(f'<polyline points="{ptstr}" fill="none" stroke="#{color}" '
                         f'stroke-width="{lw * 1.1}"{dashattr}{mk}/>')
    for color in marker_colors:
        parts.append(
            f'<marker id="arr-{color}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6.5" '
            f'markerHeight="6.5" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="#{color}"/></marker>')
    parts.append("</svg>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def main():
    root = Path(__file__).resolve().parents[1]
    docs = root / "docs"
    images = docs / "images"
    images.mkdir(parents=True, exist_ok=True)
    scenes = [slide1(), slide2()]

    pptx_path = docs / "drive-principles.pptx"
    emit_pptx(scenes, pptx_path)
    print(f"pptx -> {pptx_path}")

    try:
        import cairosvg
        for i, scene in enumerate(scenes, 1):
            svg_path = images / f"drive-principles-p{i}.svg"
            png_path = images / f"drive-principles-p{i}.png"
            emit_svg(scene, svg_path)
            cairosvg.svg2png(url=str(svg_path), write_to=str(png_path),
                             output_width=1920, output_height=1080)
            print(f"preview -> {png_path}")
    except ImportError:
        print("cairosvg unavailable, skip previews")


if __name__ == "__main__":
    main()
