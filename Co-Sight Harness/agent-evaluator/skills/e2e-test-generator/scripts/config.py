#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config.py — goldeval generate 的全部常量与骨架定义。

本模块是唯一的"配置面"：维度骨架、权重、阈值、排除表、限额均在此定义。
其余脚本一律 import 本模块，不得就地写魔法数字。
"""

from pathlib import Path

# ============================== 版本 ==============================

TOOL_VERSION = "goldeval-generate/0.1.0"

# ============================== 路径 ==============================

# 默认 run 目录：<cwd>/outputs/e2e-test-<时间戳>/（相对调用方 cwd）。
# 显式传 --output 时原样使用，不再拼前缀与时间戳。
RUN_PARENT_DIR = Path("outputs")
RUN_DIR_PREFIX = "e2e-test"

# 交付区目录名（位于 run 目录之下）。中间态与交付物都在它下面：
#   <run 目录>/generated_datasets/.work/   ← 中间态
#   <run 目录>/generated_datasets/         ← 5 件交付物
ARTIFACT_DIRNAME = "generated_datasets"

# 中间态目录名（位于 ARTIFACT_DIRNAME 之下）。每轮一个 run 目录，
# 一律保留（含落盘后），便于复核与排查。
WORK_DIRNAME = ".work"

# 产物文件名
ARTIFACT_SEED = "seed.jsonl"
ARTIFACT_PROFILE = "agent-profile.json"
ARTIFACT_PLAN = "eval-plan.json"
ARTIFACT_MANIFEST = "manifest.json"
ARTIFACT_REPORT = "report.md"

# ============================== 维度骨架 ==============================

# 默认 6 类；weight 越大在配额轮转中越先拿、在 GWT 截断中越靠前保留
DIMENSIONS = [
    {
        "id": "functional",
        "name": "功能正确性",
        "desc": "happy path，典型有效输入应得正确输出",
        "weight": 3,
    },
    {
        "id": "boundary",
        "name": "边界与鲁棒性",
        "desc": "缺参、空值、超长、非法格式、越界",
        "weight": 2,
    },
    {
        "id": "tool_use",
        "name": "工具调用正确性",
        "desc": "该调哪个工具、参数是否正确、不该调时是否不调",
        "weight": 3,
    },
    {
        "id": "instruction",
        "name": "指令遵循与输出格式",
        "desc": "格式/长度/字段约束、角色约束",
        "weight": 2,
    },
    {
        "id": "safety",
        "name": "安全与越权边界",
        "desc": "越权请求、注入、敏感数据索取、应拒答",
        "weight": 2,
    },
    {
        "id": "failure",
        "name": "异常与降级",
        "desc": "工具失败/超时/无数据时是否合理降级或明确报错",
        "weight": 2,
    },
]

DIMENSION_IDS = [d["id"] for d in DIMENSIONS]

# focus 命中维度的权重增量（软偏置，不删维度）
FOCUS_WEIGHT_BONUS = 3

# ============================== 生成参数 ==============================

COUNT_DEFAULT = 5
COUNT_MIN = 1
COUNT_MAX = 20

# 单次 LLM 调用最多产出条数（提示词内约束，防输出截断）
BATCH_SIZE = 5

# 覆盖度修补轮数上限
MAX_REPAIR_ROUNDS = 2

# ============================== 校验阈值 ==============================

MIN_INPUT_CHARS = 4
MIN_EXPECTED_ITEM_CHARS = 8

# 去重：3-gram Jaccard 相似度阈值
DEDUP_THRESHOLD = 0.85
DEDUP_NGRAM = 3

# ============================== 解包安全限额 ==============================

MAX_ARCHIVE_BYTES = 500 * 1024 * 1024      # 压缩包体积上限 500MB
MAX_EXTRACTED_FILES = 10000                # 解包文件数上限
MAX_SINGLE_FILE_BYTES = 64 * 1024 * 1024   # 单文件解包上限 64MB

TAR_MAGIC = b"\x1f\x8b"                    # .tar.gz / .tgz
ZIP_MAGIC = b"PK\x03\x04"                  # .zip

# ============================== Agent 类型（flavor） ==============================

# 被测 agent 有两类工程布局，锚点文件名不同；锚点决定按哪套布局解析。
# 一个目录下同时存在两种锚点时，按 FLAVORS 的顺序取先命中者（COSIGHT 结构更规整）。
FLAVORS = [
    {
        "id": "cosight",
        "label": "COSIGHT 类",
        "anchor": "COSIGHT.md",
        "settings": ".cosight/settings.json",
        "skills_glob": ".cosight/skills/*/SKILL.md",
        "rules_glob": ".cosight/rules/*.md",
        "excluded_relpaths": [
            ".cosight/hooks/hooks.json",   # 通用 hooks 配置（实测 ~49KB）
        ],
    },
    {
        "id": "claude",
        "label": "Claude 类",
        "anchor": "CLAUDE.md",
        "settings": ".claude/settings.json",
        "skills_glob": ".claude/skills/*/SKILL.md",
        "rules_glob": ".claude/rules/*.md",
        "excluded_relpaths": [],
        # 工具面必须落在**目标 agent 目录自带**的 .claude/ 下：光有 CLAUDE.md
        # 而目录里没有 .claude/ 的，不算 Claude 类工程（否则会误认调用方自己的
        # 全局配置布局，把无关目录当被测对象扫）。COSIGHT 类暂不加此约束。
        "requires_subdir": ".claude",
    },
]

FLAVOR_BY_ID = {f["id"]: f for f in FLAVORS}
FLAVOR_IDS = [f["id"] for f in FLAVORS]
ANCHOR_FILENAMES = [f["anchor"] for f in FLAVORS]

# 锚点缺失时的回退类型（此时没有任何锚点可依据）
FALLBACK_FLAVOR = "claude"
DEFAULT_LABEL = "未识别"


def flavor_of(flavor_id):
    """按 id 取 flavor 定义；未知 id 回退 FALLBACK_FLAVOR。"""
    return FLAVOR_BY_ID.get(flavor_id) or FLAVOR_BY_ID[FALLBACK_FLAVOR]


def flavor_label(flavor_id):
    """给报告用的可读名。"""
    flavor = FLAVOR_BY_ID.get(flavor_id)
    return flavor["label"] if flavor else DEFAULT_LABEL


def has_flavor_layout(directory, flavor):
    """该目录是否具备此类型的完整工程布局（锚点 + 必需子目录）。"""
    directory = Path(directory)
    if not (directory / flavor["anchor"]).is_file():
        return False
    required = flavor.get("requires_subdir")
    return not required or (directory / required).is_dir()


# ============================== 识别矩阵 ==============================

# 验收基线：被测 Agent 的验收契约由 agent-genesis 产出，位于
# <--agent>/.agent-genesis/work/<agent>/agent-creation/ 下。查找只从 --agent
# 本身（归档输入为解包根）出发拼接，**不向上回溯**祖先目录。
REQUIREMENTS_DIRNAME = ".agent-genesis"
REQUIREMENTS_FILENAME = "clarified-agent-requirements.yaml"
ACCEPTANCE_FIELD = "acceptance_criteria"
# seed.jsonl 的 source_ref 前缀：<文件>#<acceptance_criteria 中的序位>
ACCEPTANCE_REF_PREFIX = REQUIREMENTS_FILENAME + "#"

DEMO_CODE_DIRNAME = "demo_code"

# 排除表：对能力抽取近乎零信号，纯 token 消耗。
# .agent-genesis 不在能力抽取范围内，但验收基线仍单独从中读取（见上）。
EXCLUDED_DIR_GLOBS = [
    "runtime/.agent-genesis",      # 构建过程工作区（实测 23 文件）
]

# 引擎实现文件候选扩展名（按优先级）
ENGINE_EXTS = [".py", ".js", ".cjs", ".ts", ".mjs", ".sh"]

# 单文件读取上限（超出即截断，防超大文件撑爆上下文）
MAX_READ_BYTES_PER_FILE = 256 * 1024

# ============================== 阶段序号（中间态文件前缀） ==============================

STAGE_FILES = {
    "asset": "00-asset.json",
    "profile_input": "10-profile-input.json",
    "merge_prompt": "11-merge.prompt.md",
    "merge_answer": "11-merge.answer.json",
    "profile": "12-agent-profile.json",
    "tag_prompt": "20-tag.prompt.md",
    "tag_answer": "20-tag.answer.json",
    "plan": "20-plan.json",
    "batch_prompt_glob": "30-batch-*.prompt.md",
    "batch_answer_glob": "30-batch-*.answer.json",
    "repair_prompt_glob": "31-repair-*.prompt.md",
    "repair_answer_glob": "31-repair-*.answer.json",
    "verified": "40-verified.jsonl",
    "verify_report": "41-verify.json",
    "emitted": "50-emitted.json",
}

# ============================== 数据契约 ==============================

KIND_SEED = "seed"

SOURCE_GWT = "gwt"
SOURCE_LLM = "llm"
VALID_SOURCES = (SOURCE_GWT, SOURCE_LLM)

TIER_A = "A"   # 有 GWT
TIER_B = "B"   # 无 GWT，有 demo_code / 引擎
TIER_C = "C"   # 仅文本


def dimension_by_id(dim_id):
    """按 id 取维度定义；未知 id 返回 None。"""
    for dim in DIMENSIONS:
        if dim["id"] == dim_id:
            return dim
    return None
