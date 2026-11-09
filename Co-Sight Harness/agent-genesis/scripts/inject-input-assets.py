#!/usr/bin/env python3
"""输入资产注入器：把内置 RAG 检索 skill 注入到待构建 Agent 的产物目录。

当前仅支持知识库能力（``knowledge.json`` -> ``rag-knowledge-search``）。
MCP 能力不在迁移范围内：输入目录中的 ``mcp.json`` 会被忽略并记入 warnings。

用法::

    python scripts/inject-input-assets.py \
        --input-dir <目录，含 knowledge.json> \
        --output-dir output/agents/{name}/v1 \
        --work-dir .agent-genesis/work/{name}/agent-creation \
        [--target-platform claude-code|dsh|both] \
        [--knowledge-workflow-id RAG_Workflow_xxx] \
        [--verify] [--finalize]

输入契约 ``<input-dir>/knowledge.json``::

    {"workflow_id": "RAG_Workflow_xxx"}

产物：

  - ``<output-dir>/.claude/skills/rag-knowledge-search/``（platform=claude-code，默认）
  - ``<output-dir>/dsh/skills/rag-knowledge-search/``（platform=dsh；
    由 preset 的 skill-filesystem.customSkillDirs 挂载，见 platforms/dsh.yaml）
  - ``both`` 时上述两处都写。
  - ``<work-dir>/injected-assets.yaml``（注入清单，供 build-planner / gate 消费；
    记录 target_platform 与 knowledge.relative_dirs，relative_dir 保留首个落点作兼容）

退出码：0 = injected/noop；2 = 输入错误或注入失败。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - 环境缺 PyYAML 时直接失败
    yaml = None

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_SKILL = PLUGIN_ROOT / "knowledge" / "skill" / "rag-knowledge-search"

SKILL_NAME = "rag-knowledge-search"
MANIFEST_NAME = "injected-assets.yaml"

PLATFORM_CLAUDE = "claude-code"
PLATFORM_DSH = "dsh"
PLATFORM_BOTH = "both"
DEFAULT_PLATFORM = PLATFORM_CLAUDE
# 平台 → 技能落点根（相对 output/agents/{name}/v1）；唯一事实源见
# knowledge/agent-creation/platforms/dsh.yaml 的 mapping.skill。
# both = 两套产物都要，技能两侧各落一份（manifest 的 knowledge.relative_dirs 记录全部落点）。
SKILL_ROOTS_BY_PLATFORM = {
    PLATFORM_CLAUDE: (Path(".claude") / "skills",),
    PLATFORM_DSH: (Path("dsh") / "skills",),
    PLATFORM_BOTH: (Path(".claude") / "skills", Path("dsh") / "skills"),
}


def skill_rel_dirs(platform: str) -> List[Path]:
    """返回指定平台的技能落点目录列表（相对 output_dir）。"""
    try:
        roots = SKILL_ROOTS_BY_PLATFORM[platform]
    except KeyError as exc:
        raise InjectionError(
            f"未知平台 {platform!r}，可选：{', '.join(SKILL_ROOTS_BY_PLATFORM)}"
        ) from exc
    return [root / SKILL_NAME for root in roots]

WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
WORKFLOW_ID_ASSIGN_RE = re.compile(r"(DEFAULT_WORKFLOW_ID\s*=\s*)(['\"])(.*?)\2")
WORKFLOW_ID_FIELD = "rag_knowledge_search.py"

IGNORED_NAMES = {"__pycache__", "test_skill.py"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
# 内置资产中硬编码的技能落点（claude-code 形态）；其他平台需改写
CLAUDE_SKILL_REL = ".claude/skills/rag-knowledge-search"
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".py", ".sh", ".txt", ".json"}
DEFAULT_BASE_URL = "http://localhost:4910"
QUERY_PATH = "/api/co-knowledge/v1/agent/query"


class InjectionError(Exception):
    """注入失败（输入非法 / 资产损坏 / 路径逃逸）。"""


def emit(payload: Dict[str, Any], code: int) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return code


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ensure_within(path: Path, base: Path, label: str) -> Path:
    resolved = path.resolve()
    base_resolved = base.resolve()
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise InjectionError(f"{label} 路径逃逸：{resolved} 不在 {base_resolved} 内")
    return resolved


def validate_workflow_id(value: Any) -> str:
    if not isinstance(value, str):
        raise InjectionError("workflow_id 必须是字符串")
    value = value.strip()
    if not WORKFLOW_ID_RE.match(value):
        raise InjectionError(
            "workflow_id 只允许 [A-Za-z0-9_-]{1,128}，"
            f"当前为 {value!r}"
        )
    return value


def load_workflow_id(input_dir: Optional[Path], cli_value: Optional[str]) -> Tuple[str, Optional[Path]]:
    """解析工作流 id。CLI 直传优先于 knowledge.json。"""
    if cli_value:
        return validate_workflow_id(cli_value), input_dir

    if input_dir is None:
        raise InjectionError("缺少 --input-dir 或 --knowledge-workflow-id")

    knowledge_path = input_dir / "knowledge.json"
    if not knowledge_path.is_file():
        raise InjectionError(f"未找到 {knowledge_path}")

    try:
        data = json.loads(knowledge_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InjectionError(f"knowledge.json 非法 JSON：{exc}") from exc
    except OSError as exc:
        raise InjectionError(f"无法读取 knowledge.json：{exc}") from exc

    if not isinstance(data, dict):
        raise InjectionError("knowledge.json 顶层必须是 JSON 对象")

    return validate_workflow_id(data.get("workflow_id")), input_dir


def render_source(
    rel_path: Path, raw: bytes, workflow_id: str, target_rel_dir: Path
) -> bytes:
    """按目标落点渲染内置资产。

    - 客户端脚本（``rag_knowledge_search.py``）替换 DEFAULT_WORKFLOW_ID
    - 所有文本文件把内置的 ``.claude/skills/rag-knowledge-search`` 前缀改写成
      目标落点（dsh 平台为 ``dsh/skills/rag-knowledge-search``）——skill 文档
      里的可执行路径必须指向自身真实位置，且 DSH 产物不得残留 ``.claude/`` 引用
    """
    if rel_path.suffix not in TEXT_SUFFIXES:
        return raw
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw

    target = target_rel_dir.as_posix()
    if target != CLAUDE_SKILL_REL and CLAUDE_SKILL_REL in text:
        text = text.replace(CLAUDE_SKILL_REL, target)
    if rel_path.name != WORKFLOW_ID_FIELD:
        return text.encode("utf-8")

    matches = WORKFLOW_ID_ASSIGN_RE.findall(text)
    if len(matches) != 1:
        raise InjectionError(
            f"{rel_path} 中 DEFAULT_WORKFLOW_ID 赋值应恰好出现 1 次，实际 {len(matches)} 次"
        )
    rendered, count = WORKFLOW_ID_ASSIGN_RE.subn(
        lambda m: f"{m.group(1)}{m.group(2)}{workflow_id}{m.group(2)}",
        text,
        count=1,
    )
    if count != 1:
        raise InjectionError(f"{rel_path} 替换 DEFAULT_WORKFLOW_ID 失败")
    return rendered.encode("utf-8")


def collect_skill_files(workflow_id: str, rel_dir: Path) -> Dict[str, bytes]:
    """收集内置 skill 的待写入文件：{相对 output_dir 的 posix 路径: 内容}。"""
    if not BUILTIN_SKILL.is_dir():
        raise InjectionError(f"内置 skill 不存在：{BUILTIN_SKILL}")

    files: Dict[str, bytes] = {}
    for path in sorted(BUILTIN_SKILL.rglob("*")):
        if not path.is_file():
            continue
        if path.name in IGNORED_NAMES or any(part in IGNORED_NAMES for part in path.parts):
            continue
        if path.suffix in IGNORED_SUFFIXES:
            continue

        _ensure_within(path, BUILTIN_SKILL, "内置 skill 文件")

        rel = path.relative_to(BUILTIN_SKILL)
        rendered = render_source(rel, path.read_bytes(), workflow_id, rel_dir)
        target_rel = (rel_dir / rel).as_posix()
        files[target_rel] = rendered

    if not files:
        raise InjectionError(f"内置 skill 为空：{BUILTIN_SKILL}")
    return files


def read_existing(target_dir: Path) -> Dict[str, bytes]:
    existing: Dict[str, bytes] = {}
    if not target_dir.is_dir():
        return existing
    for path in sorted(target_dir.rglob("*")):
        if path.is_file() and path.suffix not in IGNORED_SUFFIXES:
            existing[path.relative_to(target_dir).as_posix()] = path.read_bytes()
    return existing


def backup_existing(target_dir: Path, backup_root: Optional[Path] = None) -> Path:
    """把旧 skill 目录移走。

    claude-code 沿用同级 ``<name>.bak-<stamp>``；DSH 必须移到技能根之外——
    customSkillDirs 会扫到同级子目录里的 SKILL.md，残留备份会导致同名技能冲突。
    """
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if backup_root is None:
        backup = target_dir.with_name(f"{target_dir.name}.bak-{stamp}")
    else:
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / f"{target_dir.name}.bak-{stamp}"
    counter = 1
    while backup.exists():
        counter += 1
        backup = backup.with_name(f"{backup.name}-{counter}")
    target_dir.rename(backup)
    return backup


def write_files(target_dir: Path, relative_to_skill: Dict[str, bytes]) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for rel, data in relative_to_skill.items():
        dest = target_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


def run_verify(warnings: List[str]) -> None:
    check_script = BUILTIN_SKILL / "scripts" / "check_env.py"
    if not check_script.is_file():
        warnings.append("未找到 check_env.py，跳过连通性自检")
        return
    try:
        completed = subprocess.run(
            [sys.executable, str(check_script), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        warnings.append(f"连通性自检未能执行：{exc}")
        return
    if completed.returncode != 0:
        detail = (completed.stdout or completed.stderr).strip()
        warnings.append(f"co-knowledge 当前不可达（不阻断构建）：{detail}")


def write_manifest(path: Path, manifest: Dict[str, Any]) -> None:
    if yaml is None:
        raise InjectionError("PyYAML 不可用，无法写 injected-assets.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def read_existing_manifest(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    if yaml is None:
        raise InjectionError("PyYAML 不可用，无法读取 injected-assets.yaml")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        raise InjectionError(f"injected-assets.yaml 解析失败：{exc}") from exc
    return data if isinstance(data, dict) else None


def build_manifest(
    status: str,
    workflow_id: str,
    input_dir: Optional[Path],
    files: List[str],
    warnings: List[str],
    renames: List[Dict[str, str]],
    rel_dirs: List[Path],
    platform: str,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "input_dir": str(input_dir.resolve()) if input_dir else None,
        "target_platform": platform,
        "error": error,
        "knowledge": {
            "injected": True,
            "workflow_id": workflow_id,
            "base_url": os.environ.get("CO_KNOWLEDGE_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            "query_path": QUERY_PATH,
            "relative_dirs": [rel.as_posix() for rel in rel_dirs],
            # 兼容单落点消费方；真实落点以 relative_dirs 为准
            "relative_dir": rel_dirs[0].as_posix(),
            "files": files,
        },
        "renames": renames,
        "applied_renames": [],
        "warnings": warnings,
    }


def inject(args: argparse.Namespace) -> Dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    work_dir = Path(args.work_dir).resolve()
    input_dir = Path(args.input_dir).resolve() if args.input_dir else None
    manifest_path = work_dir / MANIFEST_NAME

    if not output_dir.is_dir():
        raise InjectionError(f"--output-dir 不存在或不是目录：{output_dir}")

    platform = args.target_platform
    rel_dirs = skill_rel_dirs(platform)
    target_dirs = [output_dir / rel_dir for rel_dir in rel_dirs]
    for target_dir in target_dirs:
        _ensure_within(target_dir, output_dir, "skill 目标目录")

    warnings: List[str] = []
    renames: List[Dict[str, str]] = []

    if input_dir and (input_dir / "mcp.json").is_file():
        warnings.append("检测到 mcp.json：本插件不迁移 MCP 能力，已忽略")

    if args.finalize:
        existing_manifest = read_existing_manifest(manifest_path)
        if not existing_manifest:
            raise InjectionError(f"--finalize 需要已存在的 {manifest_path}")
        manifest_knowledge = existing_manifest.get("knowledge") or {}
        manifest_platform = existing_manifest.get("target_platform")
        if not manifest_platform:
            # 兼容旧清单：无 target_platform 时按 relative_dir 推断
            manifest_platform = (
                PLATFORM_DSH
                if str(manifest_knowledge.get("relative_dir", "")).startswith("dsh/")
                else PLATFORM_CLAUDE
            )
        if manifest_platform != platform:
            raise InjectionError(
                f"--finalize 的目标平台与清单不一致：清单为 {manifest_platform!r}，"
                f"当前为 {platform!r}；换平台请去掉 --finalize 重新注入"
            )
        manifest_dirs = manifest_knowledge.get("relative_dirs")
        if not isinstance(manifest_dirs, list) or not manifest_dirs:
            # 兼容旧清单：只有 relative_dir
            manifest_dirs = [manifest_knowledge.get("relative_dir")]
        expected_dirs = [rel_dir.as_posix() for rel_dir in rel_dirs]
        manifest_dirs = [d for d in manifest_dirs if isinstance(d, str)]
        if sorted(manifest_dirs) != sorted(expected_dirs):
            raise InjectionError(
                f"清单技能落点与平台不一致：清单为 {manifest_dirs!r}，"
                f"当前平台 {platform!r} 应为 {expected_dirs!r}"
            )
        workflow_id = validate_workflow_id(
            (existing_manifest.get("knowledge") or {}).get("workflow_id")
        )
        if existing_manifest.get("input_dir"):
            input_dir = Path(existing_manifest["input_dir"])
        for target_dir in target_dirs:
            if not target_dir.is_dir():
                raise InjectionError(f"--finalize 目标 skill 不存在：{target_dir}")
    else:
        workflow_id, input_dir = load_workflow_id(input_dir, args.knowledge_workflow_id)
        if input_dir and not input_dir.is_dir():
            raise InjectionError(f"--input-dir 不存在或不是目录：{input_dir}")

    expected: Dict[str, bytes] = {}
    expected_by_dir: List[Tuple[Path, Dict[str, bytes]]] = []
    for rel_dir in rel_dirs:
        rendered = collect_skill_files(workflow_id, rel_dir)
        expected.update(rendered)
        prefix = rel_dir.as_posix() + "/"
        expected_by_dir.append(
            (rel_dir, {rel[len(prefix):]: data for rel, data in rendered.items()})
        )

    status = "noop"
    for rel_dir, expected_inside_skill in expected_by_dir:
        target_dir = output_dir / rel_dir
        existing = read_existing(target_dir)
        if args.finalize:
            if existing != expected_inside_skill:
                warnings.append(
                    f"{rel_dir.as_posix()} 与内置资产不一致，建议重新执行注入（去掉 --finalize）"
                )
            continue
        if existing == expected_inside_skill:
            continue
        if existing:
            # DSH 的 customSkillDirs（及 both 场景）会扫到技能根下每个子目录——
            # 备份必须移出技能根，否则残留 SKILL.md 会造成同名技能冲突。
            backup_root = work_dir / "backups" if platform != PLATFORM_CLAUDE else None
            backup = backup_existing(target_dir, backup_root)
            renames.append({
                "from": rel_dir.as_posix(),
                "to": str(backup) if backup_root is not None else backup.name,
                "reason": "content_mismatch",
            })
        write_files(target_dir, expected_inside_skill)
        status = "injected"

    if args.verify:
        run_verify(warnings)

    manifest = build_manifest(
        status=status,
        workflow_id=workflow_id,
        input_dir=input_dir,
        files=sorted(expected.keys()),
        warnings=warnings,
        renames=renames,
        rel_dirs=rel_dirs,
        platform=platform,
    )
    write_manifest(manifest_path, manifest)

    return {
        "status": status,
        "workflow_id": workflow_id,
        "target_platform": platform,
        "skill_dirs": manifest["knowledge"]["relative_dirs"],
        "skill_dir": manifest["knowledge"]["relative_dir"],
        "output_dir": str(output_dir),
        "manifest": str(manifest_path),
        "files": manifest["knowledge"]["files"],
        "renames": renames,
        "warnings": warnings,
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="注入知识检索 skill 到 Agent 产物目录")
    parser.add_argument("--input-dir", help="输入资产目录（含 knowledge.json）")
    parser.add_argument("--output-dir", required=True, help="Agent 产物目录 output/agents/{name}/v1")
    parser.add_argument("--work-dir", required=True, help="工作目录 .agent-genesis/work/{name}/agent-creation")
    parser.add_argument(
        "--target-platform",
        choices=sorted(SKILL_ROOTS_BY_PLATFORM),
        default=DEFAULT_PLATFORM,
        help=(
            "技能落点平台：claude-code=.claude/skills/；dsh=dsh/skills/；"
            "both=两处都落（默认 claude-code）"
        ),
    )
    parser.add_argument("--knowledge-workflow-id", help="直接指定 RAG 工作流 id（优先于 knowledge.json）")
    parser.add_argument("--verify", action="store_true", help="注入后探测 co-knowledge 连通性（不阻断）")
    parser.add_argument("--finalize", action="store_true", help="仅根据已有清单刷新/校验，不重新解析输入")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        result = inject(args)
    except InjectionError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    return emit(result, 0)


if __name__ == "__main__":
    sys.exit(main())
