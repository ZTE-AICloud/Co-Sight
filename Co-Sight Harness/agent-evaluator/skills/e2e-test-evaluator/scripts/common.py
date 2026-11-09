#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.py — e2e-test-evaluator 的跨模块工具（IO / 路径解析 / 证据装载 / 守卫）。

定位逻辑与 e2e-test-runner 的 common.py 同源（同一个工程的两个 skill 必须表现得
一致），差异只在探测链顺序与产物目录名，见 config.SEED_PROBE_RELPATHS 的注释。
"""

import hashlib
import json
import sys
from pathlib import Path

import config


# ============================== 错误与退出 ==============================

class EvalError(Exception):
    """可预期的业务失败：打印后以退出码 1 结束，不打印堆栈。"""


def fail(message: str) -> None:
    """打印 ERROR 并以退出码 1 退出。"""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


# ============================== JSON / JSONL / TEXT IO ==============================

def read_json(path: Path):
    """读取 JSON；文件不存在返回 None，解析失败抛 EvalError。"""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError(f"无法解析 JSON：{path}（{exc}）") from exc


def read_json_text(path: Path):
    """读取 JSON，解析失败时返回 (None, 错误说明) 而不抛。

    裁判答案专用：坏掉的答案要能被"校验"归因（进而重派），而不是中断整轮。
    """
    path = Path(path)
    if not path.is_file():
        return None, f"文件不存在：{path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"JSON 解析失败：{exc}"


def write_json(path: Path, payload) -> None:
    """原子写入 JSON（先写临时文件再替换）。"""
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_text(path: Path, text: str) -> None:
    """原子写入文本；父目录按需创建。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_jsonl(path: Path) -> list:
    """逐行读取 JSONL；文件不存在返回 []，坏行抛 EvalError。"""
    path = Path(path)
    if not path.is_file():
        return []
    records = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalError(f"JSONL 第 {lineno} 行非法：{exc}") from exc
        if not isinstance(obj, dict):
            raise EvalError(f"JSONL 第 {lineno} 行不是 JSON 对象")
        records.append(obj)
    return records


def write_jsonl(path: Path, records: list) -> None:
    """写入 JSONL（每行一个紧凑 JSON 对象）。"""
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def sha256_file(path: Path) -> str:
    """单文件指纹；不可读返回空串。"""
    path = Path(path)
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


# ============================== 路径解析 ==============================

def newest_run_dir(parent: Path, glob: str) -> Path | None:
    """在 parent 下按**目录名倒序**取第一个匹配的目录。

    按名字而非 mtime：run 目录名本身带 %Y%m%d-%H%M%S 时间戳，字典序即时间序，
    且不受 git checkout / 拷贝导致的 mtime 漂移影响。
    """
    parent = Path(parent)
    if not parent.is_dir():
        return None
    candidates = sorted(
        (p for p in parent.glob(glob) if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _hint_generator_dir(path: Path, tried: str) -> str:
    """--input 落在生成器交付物上时，给一条能直接照做的提示。

    比笼统的"找不到 seed.jsonl"有用得多：用户多半是漏跑了 runner。
    """
    return (
        f"--input 指向的是生成器交付物，不是已执行过的用例集：\n"
        f"  {path}\n"
        f"  generated_datasets/ 里的 seed.jsonl 还没有 run 字段，无法评测。\n"
        f"  请先运行 e2e-test-runner 生成 run_datasets/，再对本 skill 指定：\n"
        f"    --input <run 目录>/run_datasets\n"
        f"  （已探测：{tried}）"
    )


def locate_seed(input_arg: str | None) -> Path:
    """把 --input 解析成 seed.jsonl 的绝对路径。

    接受三种形态：seed.jsonl 文件本身 / 含 seed.jsonl 的目录 / run 目录
    （其下 run_datasets/seed.jsonl）。目录形态按 config.SEED_PROBE_RELPATHS
    顺序探测。解析不出即抛 EvalError——不做静默回退。
    """
    tried = "、".join("/".join(r) for r in config.SEED_PROBE_RELPATHS)

    if input_arg:
        path = Path(input_arg).expanduser()
        if not path.exists():
            raise EvalError(f"--input 指向的路径不存在：{path}")
        if path.is_file():
            if path.name != config.SEED_FILENAME:
                raise EvalError(
                    f"--input 指向的文件不是 {config.SEED_FILENAME}：{path}")
            return path.resolve()
        if path.name == config.GENERATOR_ARTIFACT_DIRNAME:
            raise EvalError(_hint_generator_dir(path, tried))
        for relparts in config.SEED_PROBE_RELPATHS:
            candidate = path.joinpath(*relparts)
            if candidate.is_file():
                return candidate.resolve()
        # run 目录里只有 generated_datasets/ 时，给他生成器那条提示而不是笼统报错
        if path.joinpath(config.GENERATOR_ARTIFACT_DIRNAME,
                         config.SEED_FILENAME).is_file():
            raise EvalError(_hint_generator_dir(path, tried))
        raise EvalError(
            f"--input 目录下找不到 {config.SEED_FILENAME}：{path}\n"
            f"  已探测：{tried}"
        )

    parent = Path(config.RUN_PARENT_DIR)
    run_dir = newest_run_dir(parent, config.RUN_DIR_GLOB)
    if run_dir is None:
        raise EvalError(
            f"未指定 --input，且 {parent.resolve()} 下没有 {config.RUN_DIR_GLOB} 目录。\n"
            f"  请显式指定：--input <run 目录|run_datasets 目录|seed.jsonl>"
        )
    return locate_seed(str(run_dir))


def resolve_output_dir(output_arg: str | None, seed_path: Path) -> Path:
    """解析 --output 指向的 run 目录（结果落其下的 eval_datasets/）。

    缺省走与 --input 同一套规则——outputs/ 下按目录名倒序取第一个 e2e-test*。
    两条链**独立解析**：显式传了 --input 也不会把 --output 带偏，反之亦然。
    """
    if output_arg:
        path = Path(output_arg).expanduser()
        if not path.exists():
            raise EvalError(f"--output 指向的路径不存在：{path}")
        if not path.is_dir():
            raise EvalError(f"--output 必须指向目录：{path}")
        if path.name == config.INPUT_ARTIFACT_DIRNAME:
            raise EvalError(
                f"--output 给的是 {config.INPUT_ARTIFACT_DIRNAME}/ 目录，"
                f"但它要的是 **run 目录**：\n"
                f"  {path}\n"
                f"  结果会落在 <run 目录>/{config.OUTPUT_ARTIFACT_DIRNAME}/，"
                f"请把 --output 上移一层。"
            )
        return path.resolve()

    parent = Path(config.RUN_PARENT_DIR)
    run_dir = newest_run_dir(parent, config.RUN_DIR_GLOB)
    if run_dir is None:
        raise EvalError(
            f"未指定 --output，且 {parent.resolve()} 下没有 {config.RUN_DIR_GLOB} 目录。\n"
            f"  请显式指定：--output <run 目录>"
        )
    return run_dir.resolve()


# ============================== 记录校验 ==============================

def case_id_of(record: dict, index: int) -> str:
    """取用例标识。缺失或含路径分隔符即报错（它要用作文件名）。"""
    data_id = str(record.get(config.DATA_ID_KEY) or "").strip()
    if not data_id:
        raise EvalError(
            f"{config.SEED_FILENAME} 第 {index} 条记录缺少 {config.DATA_ID_KEY} 字段")
    for bad in config.FORBIDDEN_CASE_ID_PARTS:
        if bad in data_id:
            raise EvalError(
                f"{config.DATA_ID_KEY} 不能用作文件名（含 {bad!r}）：{data_id}")
    return data_id


def expected_output_of(record: dict, index: int) -> list:
    """取判据列表。缺失、非列表或为空即报错——没有判据就无法评测。"""
    raw = record.get(config.EXPECTED_OUTPUT_KEY)
    if raw is None:
        raise EvalError(
            f"{config.SEED_FILENAME} 第 {index} 条记录缺少 "
            f"{config.EXPECTED_OUTPUT_KEY} 字段，无法评测")
    if not isinstance(raw, list) or not raw:
        raise EvalError(
            f"{config.SEED_FILENAME} 第 {index} 条记录的 "
            f"{config.EXPECTED_OUTPUT_KEY} 必须是非空列表：{raw!r}")
    items = [str(x) for x in raw]
    if any(not x.strip() for x in items):
        raise EvalError(
            f"{config.SEED_FILENAME} 第 {index} 条记录的 "
            f"{config.EXPECTED_OUTPUT_KEY} 含空项")
    return items


def require_executed(records: list) -> None:
    """确认每条记录都跑过。缺 run 字段即报错，列出全部缺失项。

    没有执行就没有可裁判的输出，硬评只会产出一堆假低分——这是 runner 的交付物
    还没生成时的典型误用，报错比静默避让有用得多。
    """
    missing = []
    for index, record in enumerate(records, 1):
        if not isinstance(record.get(config.RUN_KEY), dict):
            missing.append(case_id_of(record, index))
    if missing:
        joined = "\n".join(f"    - {name}" for name in missing)
        raise EvalError(
            f"{len(missing)} 条用例尚未执行（记录里没有 {config.RUN_KEY} 字段）：\n"
            f"{joined}\n"
            f"  请先运行 e2e-test-runner 把用例跑完，再来评测。"
        )


# ============================== 证据装载 ==============================

def _text_of(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def load_evidence(record: dict) -> tuple:
    """装载某条用例的裁判证据，返回 (正文, 来源说明)。

    优先级：`{case_dir}/result.json` 的 result 全文为主，`run.result_preview` 兜底。
    两者都是**完整文本**（runner 不截断、不改写），区别只在来源：result.json 是
    磁盘产物，preview 是回写进 seed 的副本。

    result.json 的三种形态（见 runner SKILL.md）都在此归一：
      合法 JSON → result 字段；超时半截 → extracted_text；解析失败 → raw。
    """
    run = record.get(config.RUN_KEY) or {}
    case_dir = _text_of(run.get(config.RUN_CASE_DIR))
    fallback = "run.result_preview（result.json 不可用时的完整 result 文本）"

    if case_dir:
        # 用不抛的那个：证据装载是尽力而为，坏文件退到 preview 即可，
        # 不该因为一条用例的 result.json 损坏就带走整轮。
        payload, _ = read_json_text(Path(case_dir) / config.CASE_RESULT)
        if isinstance(payload, dict):
            full = _text_of(payload.get(config.RESULT_FULL_KEY))
            if full:
                return full, f"{config.CASE_RESULT} 的 {config.RESULT_FULL_KEY} 字段（完整输出）"
            if payload.get(config.RESULT_PARTIAL_FLAG):
                partial = _text_of(payload.get(config.RESULT_PARTIAL_TEXT))
                if partial:
                    return partial, ("result.json（超时被 kill，从半截 JSON 抢救出的 "
                                     "extracted_text，**尾部有缺失**）")
            if payload.get(config.RESULT_PARSE_ERROR_FLAG):
                raw = _text_of(payload.get(config.RESULT_PARSE_RAW))
                if raw:
                    return raw, ("result.json（CLI 输出无法解析为 JSON，"
                                 "保留的完整 raw stdout）")

    preview = _text_of(run.get(config.RUN_RESULT_PREVIEW))
    if preview:
        return preview, fallback
    return "", "（无任何输出证据：result.json 与 result_preview 均不可用）"


def workspace_dir_of(record: dict) -> str:
    """该用例会话真正的 cwd（agent_root 副本）。

    只作**参照系**塞进裁判 prompt——裁判不主动去读文件系统，Q7/Q21 已定证据一律
    内联。有了它，裁判才能交叉验证 Agent"路径不存在"的说法是否属实。
    """
    run = record.get(config.RUN_KEY) or {}
    explicit = _text_of(run.get(config.RUN_WORKSPACE_DIR))
    if explicit:
        return str(Path(explicit).expanduser().resolve())
    case_dir = _text_of(run.get(config.RUN_CASE_DIR))
    if case_dir:
        return str((Path(case_dir) / config.WORKSPACE_DIRNAME).resolve())
    return ""


def execution_meta_of(record: dict) -> dict:
    """执行元数据。给裁判**仅供参考**：超时导致的截断和 Agent 自己摆烂是两回事，
    但这类数字不该被拿去脑补分数，故单独成块并显式标注。"""
    run = record.get(config.RUN_KEY) or {}
    return {
        config.RUN_STATUS: run.get(config.RUN_STATUS),
        config.RUN_EXIT_CODE: run.get(config.RUN_EXIT_CODE),
        config.RUN_ELAPSED: run.get(config.RUN_ELAPSED),
        config.RUN_TIMED_OUT: run.get(config.RUN_TIMED_OUT),
        config.RUN_ERROR: run.get(config.RUN_ERROR),
    }


# ============================== 守卫 ==============================

def guard_no_seed_overwrite(seed_path: Path, output_seed: Path) -> None:
    """--output 不能覆盖 --input 的 seed.jsonl。

    输入侧那份是 runner 的交付物（有 run-manifest 存证），全程只读。
    """
    if Path(seed_path).resolve() == Path(output_seed).resolve():
        raise EvalError(
            f"--output 指向的目录会覆盖 --input 的 {config.SEED_FILENAME}：\n"
            f"  {Path(seed_path).resolve()}\n"
            f"  请换一个 --output，或换一份 --input。"
        )


def guard_no_answer_leak(artifact_dir: Path, records: list,
                         input_artifact_dir: Path) -> None:
    """产物目录不得落在任何用例的 workspace/ 之内。

    `.work/*.prompt.md` 里有 expected_output 与 precondition（=答案）。它若出现在被测
    Agent 的工作副本里，一旦重跑就会被读到，评测结果全部失真却看不出异常——比崩溃
    危险得多，所以这里早失败。
    """
    target = Path(artifact_dir).resolve()
    for index, record in enumerate(records, 1):
        run = record.get(config.RUN_KEY) or {}
        candidates = []
        explicit = _text_of(run.get(config.RUN_WORKSPACE_DIR))
        if explicit:
            candidates.append(Path(explicit))
        case_dir = _text_of(run.get(config.RUN_CASE_DIR))
        if case_dir:
            candidates.append(Path(case_dir) / config.WORKSPACE_DIRNAME)
        else:
            candidates.append(input_artifact_dir / case_id_of(record, index)
                              / config.WORKSPACE_DIRNAME)
        for workspace in candidates:
            resolved = workspace.expanduser().resolve()
            if target.is_relative_to(resolved):
                raise EvalError(
                    f"--output 解析出的产物目录落在被测 Agent 的工作副本内部：\n"
                    f"  产物目录     → {target}\n"
                    f"  用例副本(cwd) → {resolved}\n"
                    f"  {config.WORK_DIRNAME}/ 下的 prompt 含 expected_output（答案），"
                    f"落在这里等于把答案放进被测目录。\n"
                    f"  请把 --output 指到 run_datasets/ 之外。"
                )


def guard_no_agent_root_write(artifact_dir: Path, input_artifact_dir: Path) -> None:
    """产物目录不得落在被测 agent 的源目录内部。

    agent_root 从 runner 的 run-manifest.json 读；读不到就跳过（无从判断，不猜）。
    """
    manifest = read_json(Path(input_artifact_dir) / config.RUN_MANIFEST_FILENAME)
    if not isinstance(manifest, dict):
        return
    agent_root = _text_of(manifest.get(config.AGENT_ROOT_KEY))
    if not agent_root:
        return
    root = Path(agent_root).expanduser()
    if not root.is_dir():
        return
    target = Path(artifact_dir).resolve()
    if target.is_relative_to(root.resolve()):
        raise EvalError(
            f"--output 解析出的产物目录落在被测 Agent 的源目录内部：\n"
            f"  产物目录  → {target}\n"
            f"  agent_root → {root.resolve()}\n"
            f"  请把 --output 指到被测目录之外。"
        )
