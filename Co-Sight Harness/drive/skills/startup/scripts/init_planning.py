"""建 .drive/<plan_dir>/ 骨架。

只建目录、记意图，不写 state（那是 state-machine skill 的事），不做编排决策
（那是 workflow.yaml 的事）。已存在且非空时拒绝覆盖。

迁移说明（旧 .planning/）：
- prop 升级后检测到 .planning/ 存在 → 拒绝 + 提示 rm
- drive runtime 不维护 legacy 兼容代码
- 旧数据如需访问从 git 历史恢复

plan-name 解析（PROP-20260817-001 机制 B + D）：
- `--plan-name <name>`：用户语义名（kebab-case + 长度 + 启发式校验），自动构造
  plan_dir = `plan-<UTC-YYYYMMDD-HHMM>-<name>`
- `--plan-dir <full>`：直接指定完整 plan_dir（向后兼容 / 测试 / 重跑特定 plan）
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DRIVE_ROOT_NAME = ".drive"
PLANNING_SUBDIRS: tuple[str, ...] = ("inputs", "runtime", "artifacts")
INTENT_FILENAME = "intent.md"
CURRENT_PLAN_MARKER = ".current-plan"
RUN_META_FILENAME = "run-meta.json"
RUN_META_SCHEMA_VERSION = "drive.runtime.run_meta.v1"
PLAN_DIR_PREFIX = "plan-"

# plan-name 字符集 + 长度约束
_PLAN_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")

REASON_WRITE_FAILED = "write_failed"
REASON_ALREADY_EXISTS = "already_exists"
REASON_INVALID_ARG = "invalid_arg"
REASON_LEGACY_PLANNING_EXISTS = "legacy_planning_exists"
REASON_MISSING_PLAN_DIR = "missing_plan_dir"
REASON_INVALID_PLAN_NAME = "invalid_plan_name"


@dataclass(frozen=True)
class Envelope:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok_envelope(cls, **data: Any) -> "Envelope":
        return cls(ok=True, data=data)

    @classmethod
    def fail(cls, reason: str, **details: Any) -> "Envelope":
        return cls(ok=False, reason=reason, details=details)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    def exit_code(self) -> int:
        return 0 if self.ok else 1


def _has_content(drive_root: Path, plan_dir: str) -> bool:
    """判定 .drive/<plan_dir>/ 是否已有实质内容（空目录或只有空子目录不算）。"""
    target = drive_root / plan_dir
    if not target.exists():
        return False
    for item in target.rglob("*"):
        if item.is_file():
            return True
    return False


def validate_plan_name(name: str) -> tuple[bool, str | None]:
    """校验 plan-name 格式。返回 (ok, reason)。

    规则：
    - kebab-case，只允许 [a-z0-9-]
    - 1-64 字符
    - 不能以 - 开头或结尾
    - 不能是 . 或 ..
    """
    if not name or name in (".", ".."):
        return False, "plan-name 不能为空或 . / .."
    if not _PLAN_NAME_RE.match(name):
        return False, (
            f"plan-name 必须 kebab-case（[a-z0-9-]，不以 - 开头/结尾）：{name!r}"
        )
    return True, None


def construct_plan_dir(user_name: str, *, ts: str | None = None) -> str:
    """构造完整 plan_dir：plan-<UTC-YYYYMMDD-HHMM>-<user_name>。

    Args:
        user_name: 用户语义 plan-name（不含时间戳）
        ts: 时间戳字符串（None 时用 UTC 当前时间）
    """
    if ts is None:
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M")
    return f"{PLAN_DIR_PREFIX}{ts}-{user_name}"


def _detect_git_branch(work_dir: Path) -> str | None:
    """检测 work_dir 当前 git branch。失败返回 None。"""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(work_dir),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        branch = out.strip()
        return branch or None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def _detect_git_head(work_dir: Path) -> str | None:
    """检测 work_dir 当前 HEAD commit SHA。失败返回 None。"""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(work_dir),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        return out.strip() or None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def _workflow_hash(work_dir: Path) -> str | None:
    """workflow.yaml 内容 sha256（不存在返回 None）。"""
    for name in ("workflow.yaml", "workflow.yml"):
        path = work_dir / name
        if path.is_file():
            try:
                content = path.read_bytes()
            except OSError:
                continue
            return "sha256:" + hashlib.sha256(content).hexdigest()
    return None


def _input_digests(plan_path: Path) -> dict[str, str]:
    """inputs/ 下每个文件的 sha256。"""
    out: dict[str, str] = {}
    inputs_dir = plan_path / "inputs"
    if not inputs_dir.is_dir():
        return out
    for p in sorted(inputs_dir.rglob("*")):
        if p.is_file():
            try:
                content = p.read_bytes()
            except OSError:
                continue
            rel = p.relative_to(inputs_dir).as_posix()
            out[rel] = "sha256:" + hashlib.sha256(content).hexdigest()
    return out


def _write_run_meta(
    plan_path: Path,
    *,
    plan_name: str,
    plan_dir: str,
    work_dir: Path,
) -> dict[str, Any]:
    """写 .drive/<plan_dir>/run-meta.json。返回写盘的 dict。"""
    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    meta = {
        "schema_version": RUN_META_SCHEMA_VERSION,
        "plan_name": plan_name,
        "plan_dir": plan_dir,
        "git_head": _detect_git_head(work_dir),
        "git_branch": _detect_git_branch(work_dir),
        "workflow_hash": _workflow_hash(work_dir),
        "input_digests": _input_digests(plan_path),
        "started_at": started_at,
        "worktree": str(root if (root := work_dir.resolve()) else work_dir),
    }
    meta = {k: v for k, v in meta.items() if v is not None}
    meta["plan_name"] = plan_name
    meta["plan_dir"] = plan_dir
    meta["started_at"] = started_at
    meta["worktree"] = str(work_dir.resolve())
    meta["schema_version"] = RUN_META_SCHEMA_VERSION
    (plan_path / RUN_META_FILENAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return meta


def _write_current_plan_marker(drive_root: Path, plan_dir: str) -> None:
    """写 .drive/.current-plan 标记供 hook_io.find_active_plan_dir 找当前 plan。"""
    marker = drive_root / CURRENT_PLAN_MARKER
    tmp = marker.with_suffix(marker.suffix + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(plan_dir, encoding="utf-8")
        os.replace(tmp, marker)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def init_planning(
    work_dir: Path | str,
    *,
    plan_dir: str = "",
    plan_name: str = "",
    intent: str | None = None,
    auto_mode: bool = False,
    force: bool = False,
) -> Envelope:
    """建 .drive/<plan_dir>/ 骨架。

    Args:
        work_dir: 项目工作目录（用户项目根）
        plan_dir: 完整 plan-dir 名（含时间戳前缀）。与与 plan_name 互斥。
        plan_name: 用户语义 plan-name。传时自动构造 plan_dir = plan-<ts>-<name>。
        intent: 用户意图，写入 intent.md
        auto_mode: 仅回传给调用方，由其写入 state；本脚本不碰 state
        force: 已有内容时仍继续（默认拒绝，避免覆盖既有工作）
    """
    root = Path(work_dir).resolve()
    if not root.is_dir():
        return Envelope.fail(REASON_INVALID_ARG, work_dir=str(root), error="目录不存在")

    # 解析 plan_name → plan_dir
    derived_name: str | None = None
    if plan_name:
        ok, reason = validate_plan_name(plan_name)
        if not ok:
            return Envelope.fail(
                REASON_INVALID_PLAN_NAME,
                plan_name=plan_name,
                error=reason,
            )
        derived_name = plan_name
        plan_dir = construct_plan_dir(plan_name)

    if not plan_dir:
        return Envelope.fail(
            REASON_MISSING_PLAN_DIR,
            work_dir=str(root),
            error="必须传入 --plan-dir（完整 plan 子目录名）或 --plan-name（自动构造）",
        )

    # 旧 .planning/ 检测：直接拒绝 + 提示用户 rm
    legacy_dir = root / ".planning"
    if legacy_dir.exists() and not force:
        return Envelope.fail(
            REASON_LEGACY_PLANNING_EXISTS,
            legacy_dir=str(legacy_dir),
            hint="检测到旧 .planning/，drive 已迁移到 .drive/<plan_dir>/ 路径。"
                 "请手动 `rm -rf .planning` 后重跑 drive。"
                 "如需访问旧数据，从 git 历史恢复。",
        )

    if _has_content(root / DRIVE_ROOT_NAME, plan_dir) and not force:
        return Envelope.fail(
            REASON_ALREADY_EXISTS,
            drive_root=str(root / DRIVE_ROOT_NAME),
            plan_dir=plan_dir,
            hint="该 plan 已存在，跳过 startup。如需重跑，使用 /drive-cleanup 清理或换 plan-name。",
        )

    drive_root = root / DRIVE_ROOT_NAME
    created: list[str] = []
    try:
        drive_root.mkdir(parents=True, exist_ok=True)
        plan_path = drive_root / plan_dir
        plan_path.mkdir(parents=True, exist_ok=True)
        created.append(f"{DRIVE_ROOT_NAME}/{plan_dir}")
        for sub in PLANNING_SUBDIRS:
            (plan_path / sub).mkdir(parents=True, exist_ok=True)
            created.append(f"{DRIVE_ROOT_NAME}/{plan_dir}/{sub}")
        if intent:
            (plan_path / INTENT_FILENAME).write_text(
                f"# 意图\n\n{intent}\n", encoding="utf-8"
            )
            created.append(f"{DRIVE_ROOT_NAME}/{plan_dir}/{INTENT_FILENAME}")
    except OSError as exc:
        return Envelope.fail(
            REASON_WRITE_FAILED,
            error=str(exc),
            drive_root=str(drive_root),
            plan_dir=plan_dir,
            hint="检查目录写权限，或切到正确的项目根",
        )

    # 写 .current-plan 标记 + run-meta.json（不致命：失败仅警告）
    try:
        _write_current_plan_marker(drive_root, plan_dir)
    except OSError:
        pass

    final_name = derived_name or plan_dir.removeprefix(PLAN_DIR_PREFIX).split("-", 2)[-1]
    try:
        run_meta = _write_run_meta(
            plan_path,
            plan_name=final_name,
            plan_dir=plan_dir,
            work_dir=root,
        )
    except OSError:
        run_meta = None

    return Envelope.ok_envelope(
        drive_root=str(drive_root),
        plan_dir=plan_dir,
        plan_name=final_name,
        planning_dir=str(plan_path),
        created=created,
        intent_recorded=bool(intent),
        auto_mode=auto_mode,
        run_meta=run_meta,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="建 .drive/<plan_dir>/ 骨架")
    parser.add_argument("--work-dir", default=".")
    parser.add_argument(
        "--plan-dir",
        default="",
        help="plan 子目录名（完整，含时间戳前缀）；与 --plan-name 互斥",
    )
    parser.add_argument(
        "--plan-name",
        default="",
        help="用户语义 plan-name（kebab-case），自动构造 plan-<ts>-<name>",
    )
    parser.add_argument("--intent", default=None)
    parser.add_argument("--auto", action="store_true", help="回传 auto_mode 供调用方写入 state")
    parser.add_argument("--force", action="store_true", help="已有内容时仍继续")
    args = parser.parse_args(argv)

    if args.plan_dir and args.plan_name:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": REASON_INVALID_ARG,
                    "error": "--plan-dir 和 --plan-name 互斥，不能同时传",
                },
                ensure_ascii=False,
            )
        )
        return 1

    env = init_planning(
        args.work_dir,
        plan_dir=args.plan_dir,
        plan_name=args.plan_name,
        intent=args.intent,
        auto_mode=args.auto,
        force=args.force,
    )
    print(env.to_json())
    return env.exit_code()


if __name__ == "__main__":
    sys.exit(main())