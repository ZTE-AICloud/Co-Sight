"""清理 .drive/plan-*/ 中过期 plan 目录。

按字典序（= UTC 时间序）扫描 .drive/ 下所有 plan-* 子目录，按策略删除。

策略优先级（互斥）：
- 默认（无 args）：清理最早的 10 个（dry-run + 确认）
- --all：删所有（除 running）
- --keep N：保留最新 N 个，删更早的
- <names...>：删指定 plan-dir 全名

保护：
- running 跳过（最近 30 分钟有改动认为在跑）
- dry-run 默认 + 需确认
- --force 跳过确认（CI / 高级用户）
- --tar 先 tar 到 .drive/.cleared/<ts>.tar.gz 再删（可选）
- .cleared/ 和 .planning-backup-*.tar.gz 不在 glob 范围内（保留）

CLI:
    python3 clear_plans.py --work-dir <dir>
    python3 clear_plans.py --work-dir <dir> --all
    python3 clear_plans.py --work-dir <dir> --keep 30
    python3 clear_plans.py --work-dir <dir> plan-<ts>-a plan-<ts>-b
    python3 clear_plans.py --work-dir <dir> --tar
    python3 clear_plans.py --work-dir <dir> --force
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import tarfile
from pathlib import Path

DRIVE_ROOT_NAME = ".drive"
PLAN_PREFIX = "plan-"
CLEARED_DIR_NAME = ".cleared"
RUNNING_THRESHOLD_MINUTES = 30


def _is_running(plan_dir: Path) -> bool:
    """判定 plan 是否在跑：最近 RUNNING_THRESHOLD_MINUTES 分钟内有改动。"""
    if not plan_dir.is_dir():
        return False
    try:
        mtime = plan_dir.stat().st_mtime
    except OSError:
        return False
    age_seconds = dt.datetime.now(dt.timezone.utc).timestamp() - mtime
    return age_seconds < (RUNNING_THRESHOLD_MINUTES * 60)


def _plan_size(plan_dir: Path) -> int:
    """递归算 plan 目录总大小（字节）。"""
    total = 0
    try:
        for p in plan_dir.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        pass
    return total


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n // 1024}KB"
    return f"{n // (1024 * 1024)}MB"


def _print_preview(targets: list[Path]) -> int:
    """打印要清理的 plan 列表 + 合计大小。返回合计字节。"""
    if not targets:
        print("没有 plan 要清理。")
        return 0
    total_size = 0
    print(f"将清理 {len(targets)} 个 plan：")
    for p in targets:
        size = _plan_size(p)
        total_size += size
        try:
            mtime = dt.datetime.fromtimestamp(
                p.stat().st_mtime, tz=dt.timezone.utc
            ).isoformat(timespec="minutes")
        except OSError:
            mtime = "unknown"
        print(f"  - {p.name}  ({_format_size(size)}, mtime {mtime})")
    print(f"合计：{_format_size(total_size)}")
    return total_size


def clear_plans(
    work_dir: Path,
    *,
    keep: int | None = None,
    names: list[str] | None = None,
    all_: bool = False,
    tar: bool = False,
    dry_run: bool = True,
    force: bool = False,
    ts: str | None = None,
) -> dict:
    """扫描 .drive/plan-*/，按策略清理。返回 Envelope 风格 dict。

    Returns:
        {"ok": True, "data": {"cleared": [{"plan": ..., "tar_path": ...}],
                              "skipped_running": [...]}}
        {"ok": False, "reason": "needs_confirmation", "would_clear": [...],
                              "skipped_running": [...]}
        {"ok": False, "reason": "no_drive_root"}
        {"ok": False, "reason": "all_running"}
    """
    drive_root = work_dir / DRIVE_ROOT_NAME
    if not drive_root.is_dir():
        return {
            "ok": False,
            "reason": "no_drive_root",
            "drive_root": str(drive_root),
        }

    all_plans = sorted(p for p in drive_root.glob(f"{PLAN_PREFIX}*") if p.is_dir())

    if names is not None:
        targets = [drive_root / n for n in names]
        targets = [p for p in targets if p.exists()]
    elif keep is not None:
        if keep >= len(all_plans):
            targets = []
        else:
            targets = all_plans[:-keep]
    elif all_:
        targets = list(all_plans)
    else:
        targets = all_plans[:10]  # 默认：清理最早的 10 个

    running = [p for p in targets if _is_running(p)]
    targets = [p for p in targets if not _is_running(p)]

    if not targets:
        _print_preview([])
        if running:
            return {
                "ok": False,
                "reason": "all_running",
                "skipped_running": [p.name for p in running],
            }
        return {
            "ok": True,
            "data": {"cleared": [], "skipped_running": []},
        }

    _print_preview(targets)

    if dry_run and not force:
        print()
        print(f"⚠️  即将删除以上 {len(targets)} 个 plan。继续？")
        print("   加 --force 跳过确认。")
        return {
            "ok": False,
            "reason": "needs_confirmation",
            "would_clear": [p.name for p in targets],
            "skipped_running": [p.name for p in in_running_targets(running)],
        }

    ts = ts or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    cleared: list[dict] = []
    for plan_dir in targets:
        record = {"plan": plan_dir.name, "tar_path": None}
        if tar:
            cleared_dir = drive_root / CLEARED_DIR_NAME
            cleared_dir.mkdir(parents=True, exist_ok=True)
            tar_path = cleared_dir / f"{plan_dir.name}-{ts}.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tf:
                tf.add(plan_dir, arcname=plan_dir.name)
            record["tar_path"] = str(tar_path)
        shutil.rmtree(plan_dir)
        cleared.append(record)

    return {
        "ok": True,
        "data": {
            "cleared": cleared,
            "skipped_running": [p.name for p in running],
        },
    }


def in_running_targets(running: list[Path]) -> list[str]:
    """helper for skipped_running 列表。"""
    return [p.name for p in running]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="清理 .drive/plan-*/ 中过期 plan 目录（默认清理最早 10 个）"
    )
    parser.add_argument("--work-dir", default=".", help="项目工作目录")
    parser.add_argument("--keep", type=int, default=None, help="保留最新 N 个，删更早的")
    parser.add_argument("--all", dest="all_", action="store_true", help="删所有（除 running）")
    parser.add_argument("--tar", action="store_true", help="先 tar 备份到 .drive/.cleared/ 再删")
    parser.add_argument("--force", action="store_true", help="跳过确认直接执行")
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="关闭 dry-run（与 --force 配合才生效）",
    )
    parser.set_defaults(dry_run=True)
    parser.add_argument(
        "names",
        nargs="*",
        help="要删的 plan-dir 全名（不含 .drive/ 前缀）",
    )
    args = parser.parse_args(argv)

    result = clear_plans(
        Path(args.work_dir).resolve(),
        keep=args.keep,
        names=args.names or None,
        all_=args.all_,
        tar=args.tar,
        dry_run=args.dry_run,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())