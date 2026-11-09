#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cosightbot-soc-kb-build CLI —— SOC 知识库注册与本地构建。

子命令：
  add-builtin --kb-id X [--name N] --source-dir DIR   注册本地源目录
  build <kb_id> [--force] [--skip-vision]             构建向量库（产物直通 kbs/）
  list                                                列出已注册 KB 与就绪状态
  status <kb_id>                                      构建/就绪状态详情
  remove <kb_id> [--confirm]                          删除 KB（配置+产物+注册表）

要点：
  - 仅支持本地源构建；构建产物直落 data/workspace-soc/kbs/<kb_id>/{pd_spec_vector_library,
    historical_paradigms}/；build 成功后写注册表；
  - 构建为前台同步执行（CC 会话中由 Claude 以后台任务方式调用本命令，
    进度行实时写入任务输出文件），无 daemon 调度器。

源目录约定（docs/soc-kb-format.md）：
  my-kb/
  ├── 01_Specs_PD/             # 产品规格/文档（pdf/docx/pptx/xlsx/md/txt...）
  └── 02_Historical_Responses/ # 历史应答（xlsx/csv，列约定见格式文档）
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# ---- sys.path 引导：本脚本位于 <插件根>/skills/cosightbot-soc-kb-build/scripts/ ----
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME = _PLUGIN_ROOT / "runtime" / "soc"
for _p in (str(_RUNTIME), str(_RUNTIME / "watch_dog")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.bootstrap import bootstrap  # noqa: E402

bootstrap()  # venv 重入 + .env 加载 + preflight（失败 exit 3）

from common.soc_kb_builder import kb_admin  # noqa: E402
from common.soc_kb_builder.config import load_config_from_file  # noqa: E402
from common.soc_kb_registry.load import load_registry, save_registry  # noqa: E402
from common.soc_kb_registry.models import KbType, KnowledgeBase  # noqa: E402
from common.soc_kb_registry.paths import SOC_AGENT_ID  # noqa: E402
from common.soc_vector_paths import kbs_root  # noqa: E402

AGENT_ID = SOC_AGENT_ID  # SOC 域固定 "soc"

# 源目录约定子目录（至少存在一个）
_SOURCE_SUBDIRS = ("01_Specs_PD", "02_Historical_Responses")


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _validate_source_dir(src: Path) -> str | None:
    """源目录布局校验（零兜底）：必须含 01_Specs_PD/ 或 02_Historical_Responses/。"""
    missing = [d for d in _SOURCE_SUBDIRS if not (src / d).is_dir()]
    if len(missing) == len(_SOURCE_SUBDIRS):
        return (
            f"源目录布局不符: {src} 下需要至少一个约定子目录 "
            f"{' / '.join(_SOURCE_SUBDIRS)}（见 docs/soc-kb-format.md）"
        )
    return None


# ---------------------------------------------------------------------------
# add-builtin
# ---------------------------------------------------------------------------

def cmd_add_builtin(args: argparse.Namespace) -> int:
    src = Path(args.source_dir).expanduser().resolve()
    if not src.is_dir():
        _print_json({"ok": False, "error": f"source_dir 不存在: {src}"})
        return 1
    layout_err = _validate_source_dir(src)
    if layout_err:
        _print_json({"ok": False, "error": layout_err})
        return 1

    result = kb_admin.add_builtin(kb_id=args.kb_id, name=args.name, source_dir=str(src))
    _print_json({
        "ok": result.ok,
        "kb_id": result.kb_id,
        **({"config_path": result.config_path} if result.ok else {}),
        **({"error": result.error, "suggestion": result.suggestion} if result.error else {}),
        "next": f"build {args.kb_id}" if result.ok else None,
    })
    return 0 if result.ok else 1


# ---------------------------------------------------------------------------
# build：run_build（产物 → builds/<kb_id>/）→ 镜像 lancedb → kbs/<kb_id>/ → 写注册表
# ---------------------------------------------------------------------------

def _promote_to_kbs(kb_id: str, build_dir: Path) -> dict:
    """把 builds/<kb_id>/lancedb/ 下的向量库镜像到 kbs/<kb_id>/（检索侧服务目录）。

    返回 {"promoted": [...], "skipped": [...]}。镜像 = 整体替换（先删后拷）。
    """
    promoted: list[str] = []
    skipped: list[str] = []
    for table in ("pd_spec_vector_library", "historical_paradigms"):
        src = build_dir / "lancedb" / table
        dst = kbs_root(AGENT_ID) / kb_id / table
        if not src.is_dir() or not any(src.iterdir()):
            skipped.append(table)
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        promoted.append(table)
    return {"promoted": promoted, "skipped": skipped}


def _upsert_registry(kb_id: str, name: str, source_dir: str) -> None:
    """build 成功后写注册表（已存在则更新，保持 enabled 状态）。"""
    registry = load_registry(AGENT_ID)
    existing = {kb.kb_id: kb for kb in registry.knowledge_bases}
    if kb_id in existing:
        old = existing[kb_id]
        updated = KnowledgeBase(
            kb_id=kb_id, type=old.type, name=name or old.name,
            enabled=old.enabled, server_path=old.server_path,
            auto_sync=False, local_path=source_dir,
        )
        kbs = tuple(updated if kb.kb_id == kb_id else kb for kb in registry.knowledge_bases)
    else:
        entry = KnowledgeBase(
            kb_id=kb_id, type=KbType.BUILT, name=name or kb_id,
            enabled=True, server_path="", auto_sync=False, local_path=source_dir,
        )
        kbs = (*registry.knowledge_bases, entry)
    from common.soc_kb_registry.models import KnowledgeBaseRegistry
    save_registry(KnowledgeBaseRegistry(version=registry.version, knowledge_bases=kbs), agent_id=AGENT_ID)


def cmd_build(args: argparse.Namespace) -> int:
    cfg_path = kb_admin.config_path(args.kb_id)
    if not cfg_path.is_file():
        _print_json({
            "ok": False,
            "error": f"KB 未注册: {args.kb_id}（先 add-builtin --kb-id {args.kb_id} --source-dir <目录>）",
        })
        return 1
    try:
        config = load_config_from_file(cfg_path)
    except Exception as exc:
        _print_json({"ok": False, "error": f"配置加载失败: {exc}"})
        return 1

    # LLM 配置前置检查（构建链需要 LLM：图片多模态/章节润色）——缺失即 exit 1
    # 并引导配置环境变量（S-05：不降级裸跑）
    from common.cosight_runtime import resolve_runtime_llm_config
    if not resolve_runtime_llm_config("kb_cli_build"):
        _print_json({
            "ok": False,
            "error": "未找到 LLM 配置——请在 data/.env 中配置 OPENAI_BASE_URL/"
                     "OPENAI_API_KEY/OPENAI_MODEL（未配时将回退会话继承的 ANTHROPIC_*），"
                     "详见 README 环境变量表",
        })
        return 1

    build_dir = kb_admin.builds_dir(args.kb_id)
    build_dir.mkdir(parents=True, exist_ok=True)

    # 延迟导入：build_soc_vector 依赖链很重（llama_index 全家桶）
    from common.soc_kb_builder.vector_build.build_soc_vector import run_build
    ns = argparse.Namespace(
        source=str(config.source_dir),
        force=args.force,
        agent_id=AGENT_ID,
        skip_vision=args.skip_vision,
        output_dir=str(build_dir),
    )
    try:
        rc, stats = run_build(ns)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
        stats = {}
    except Exception as exc:
        _print_json({"ok": False, "error": f"构建异常: {type(exc).__name__}: {exc}"})
        return 1

    if rc not in (0, 2):  # 2 = 全部指纹命中无需构建（产物已在）
        _print_json({"ok": False, "error": f"构建失败 rc={rc}", "stats": stats})
        return 1

    promote = _promote_to_kbs(args.kb_id, build_dir)
    _upsert_registry(args.kb_id, config.kb_name, str(config.source_dir))
    _print_json({
        "ok": True,
        "kb_id": args.kb_id,
        "skipped_up_to_date": rc == 2,
        "promote": promote,
        "kbs_dir": str(kbs_root(AGENT_ID) / args.kb_id),
        "stats": stats,
    })
    return 0


# ---------------------------------------------------------------------------
# list / status / remove
# ---------------------------------------------------------------------------

def _kb_rows() -> list[dict]:
    rows = []
    registry = load_registry(AGENT_ID)
    reg_map = {kb.kb_id: kb for kb in registry.knowledge_bases}
    for cfg_file in sorted(kb_admin.configs_dir().glob("*.json")):
        kb_id = cfg_file.stem
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
        except Exception:
            cfg = {}
        reg = reg_map.get(kb_id)
        spec_lib = kbs_root(AGENT_ID) / kb_id / "pd_spec_vector_library"
        built = spec_lib.is_dir() and any(spec_lib.iterdir())
        rows.append({
            "kb_id": kb_id,
            "name": cfg.get("kb_name", kb_id),
            "source_dir": cfg.get("source_dir", ""),
            "registered": reg is not None,
            "enabled": reg.enabled if reg else None,
            "built": bool(built),
        })
    return rows


def cmd_list(_args: argparse.Namespace) -> int:
    _print_json({"ok": True, "kbs": _kb_rows()})
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    rows = {r["kb_id"]: r for r in _kb_rows()}
    row = rows.get(args.kb_id)
    if not row:
        _print_json({"ok": False, "error": f"KB 未注册: {args.kb_id}"})
        return 1
    status_file = kb_admin.builds_dir(args.kb_id) / "lancedb" / "pd_spec_vector_library" / ".llamaindex_status"
    build_status = "none"
    if status_file.is_file():
        try:
            build_status = json.loads(status_file.read_text(encoding="utf-8")).get("status", "none")
        except (OSError, json.JSONDecodeError):
            build_status = "unknown"
    _print_json({"ok": True, **row, "build_status": build_status})
    return 0


class _LocalRemoveRuntime:
    """本地直通模式的运行态通道：构建同步执行，无后台 worker 可取消。"""

    def running_pid(self, kb_id: str) -> int | None:
        return None

    def cancel(self, kb_id: str) -> dict:
        return {"ok": True}


def cmd_remove(args: argparse.Namespace) -> int:
    result = kb_admin.remove_kb(args.kb_id, confirm=args.confirm, runtime=_LocalRemoveRuntime())
    if result.confirm_required:
        # 探测清单补全检索侧资产：确认阶段实际还会删 kbs/<kb_id>/ 向量库
        # 与注册表条目（kb_admin 只管构建侧，检索侧由本函数补充披露）。
        kbs_dir = kbs_root(AGENT_ID) / args.kb_id
        registry = load_registry(AGENT_ID)
        will_cleanup = dict(result.will_cleanup or {})
        will_cleanup["kbs_dir"] = str(kbs_dir) if kbs_dir.is_dir() else None
        will_cleanup["kbs_size_mb"] = (
            kb_admin.dir_size_mb(kbs_dir) if kbs_dir.is_dir() else 0
        )
        will_cleanup["registry_entry"] = any(
            kb.kb_id == args.kb_id for kb in registry.knowledge_bases
        )
        _print_json({
            "ok": False, "confirm_required": True,
            "message": result.message, "will_cleanup": will_cleanup,
        })
        return 1
    if not result.ok:
        _print_json({"ok": False, "error": result.error})
        return result.exit_code or 1

    # 构建侧清理完成后，同步清理检索侧：kbs/<kb_id>/ + 注册表条目
    kbs_dir = kbs_root(AGENT_ID) / args.kb_id
    kbs_removed = False
    if kbs_dir.is_dir():
        shutil.rmtree(kbs_dir, ignore_errors=True)
        kbs_removed = True
    registry = load_registry(AGENT_ID)
    kept = tuple(kb for kb in registry.knowledge_bases if kb.kb_id != args.kb_id)
    registry_removed = len(kept) != len(registry.knowledge_bases)
    if registry_removed:
        from common.soc_kb_registry.models import KnowledgeBaseRegistry
        save_registry(
            KnowledgeBaseRegistry(version=registry.version, knowledge_bases=kept),
            agent_id=AGENT_ID,
        )

    _print_json({
        "ok": True, "kb_id": args.kb_id,
        "config_removed": result.config_removed,
        "sources_dir_removed": result.sources_dir_removed,
        "builds_dir_removed": result.builds_dir_removed,
        "kbs_dir_removed": kbs_removed,
        "registry_entry_removed": registry_removed,
    })
    return 0


# ---------------------------------------------------------------------------

def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="cosightbot-soc-kb-build: SOC 知识库注册与本地构建")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add-builtin", help="注册本地源目录")
    p.add_argument("--kb-id", required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--source-dir", required=True)

    p = sub.add_parser("build", help="构建向量库（产物直通 kbs/）")
    p.add_argument("kb_id")
    p.add_argument("--force", action="store_true", help="强制全量重建")
    p.add_argument("--skip-vision", action="store_true", help="跳过图片多模态识别（加速）")

    sub.add_parser("list", help="列出已注册 KB")

    p = sub.add_parser("status", help="KB 状态详情")
    p.add_argument("kb_id")

    p = sub.add_parser("remove", help="删除 KB（配置+产物+注册表）")
    p.add_argument("kb_id")
    p.add_argument("--confirm", action="store_true", help="确认清理全部关联资产")

    args = parser.parse_args()

    if args.cmd == "add-builtin":
        return cmd_add_builtin(args)
    if args.cmd == "build":
        return cmd_build(args)
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "remove":
        return cmd_remove(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
