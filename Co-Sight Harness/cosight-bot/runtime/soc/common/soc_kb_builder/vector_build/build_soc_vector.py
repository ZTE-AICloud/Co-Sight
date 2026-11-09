#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC Agent 独立全量构建脚本

自包含构建链，不依赖任何外部常驻进程。
直接从源文件构建向量库，支持指纹校验跳过未变更文件。

CLI:
    python build_soc_vector.py --source <download_dir> [--force] [--agent-id soc-agent]

退出码:
    0 = 成功
    1 = 失败
    2 = 全部文件指纹命中，无需构建
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path


def _resolve_runtime_root() -> Path:
    """定位 runtime 根目录（本模块位于 runtime/common/soc_kb_builder/
    vector_build/，parents[3] 即 runtime 根；语义同 skill_utils）。

    关键：绝不回退到任何外部目录——本机装有其他版本时会把
    异版模块（异套环境变量名）混进 sys.path，静默劫持构建链。
    """
    return Path(__file__).resolve().parents[3]


sys.path.insert(0, str(_resolve_runtime_root()))
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from common.soc_vector_paths import (
    ensure_soc_dirs,
    soc_build_output_dirs,
    HISTORICAL_RESPONSES_DIR,
    SPECS_PD_DIR,
)

# 普通文档的事件处理器（在本包 common_processor.py 里实现）。
# main() 也本地 import 一次以触发 sys.modules 缓存（避免重复开销）。
from common.soc_kb_builder.vector_build.common_processor import handle_common_file_event

# product_taxonomy：从本包纯函数模块导入（避免 sync_soc_rag 侧 import 本模块
# 触发下方 logging/FileHandler 副作用；函数实现已移至 product_taxonomy.py）
from common.soc_kb_builder.vector_build.product_taxonomy import generate_product_taxonomy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# 独立文件日志只用于单独手工运行本脚本时的留存；流水线模式（builder.py 设
# SOC_BUILD_DISABLE_FILE_LOG=1）下子进程全部输出会被 runner 逐行转发进
# builds/<kb_id>/build_<时间戳>.log，不再另写文件。
if os.environ.get("SOC_BUILD_DISABLE_FILE_LOG") != "1":
    from common.port_resolver import cosight_state_root
    _log_dir = cosight_state_root() / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_ts = time.strftime("%Y%m%d_%H%M%S")
    _file_handler = logging.FileHandler(
        _log_dir / f"build_soc_vector_{_log_ts}.log", encoding="utf-8"
    )
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(_file_handler)

logger = logging.getLogger("build_soc_vector")

# Embedding 熔断阈值：单文件 embedding 失败记 failed 继续（毒 chunk 只影响
# 一个文件，下次构建自动补）；连续 N 个文件失败判定为服务侧故障，中止构建，
# 避免服务不可用时每个文件都拖满重试超时。env 可覆盖。
EMBED_CIRCUIT_BREAKER_THRESHOLD = max(
    1, int(os.environ.get("SOC_EMBED_CIRCUIT_BREAKER_THRESHOLD", "3"))
)



def run_build(args: argparse.Namespace) -> tuple[int, dict]:
    """执行向量库构建，返回 (exit_code, stats)。

    exit_code:
        0 = 成功
        1 = 失败（SystemExit 直接抛出）
        2 = 全部文件指纹命中，无需构建
    """
    source_dir = Path(args.source).resolve()
    if not source_dir.is_dir():
        logger.error(f"Source directory does not exist: {source_dir}")
        sys.exit(1)

    agent_id = args.agent_id
    force = args.force
    skip_vision = args.skip_vision

    # Statistics tracked across all steps
    stats = {
        "preprocessed_files": 0,
        "preprocess_success": 0,
        "preprocess_failed": 0,
        # 真实内容变更计数（供流水线判定"库是否有更新"）：
        # preprocess_success 混合了指纹跳过数，不能用来判定变更；
        # upserted/deleted 全 0 表示库内容零变化，调用方应跳过上传。
        "common_upserted": 0,
        "historical_upserted": 0,
        "common_built": False,
        "common_skipped": False,
        "historical_total": 0,
        "historical_processed": 0,
        "historical_skipped": 0,
        "historical_all_skipped": False,
        "build_skipped": False,
    }

    logger.info(f"Starting SOC vector build: source={source_dir}, agent={agent_id}, force={force}, skip_vision={skip_vision}")

    if args.output_dir:
        # 多 KB 模式：产物隔离到指定 output_dir（builds/<kb_id>/）下
        out_dirs = soc_build_output_dirs(agent_id, output_dir=args.output_dir)
        pre_dir = out_dirs["pre_dir"]
        lan_dir = out_dirs["lan_dir"]
        hist_lan_dir = out_dirs["hist_lan_dir"]
        for _p in (pre_dir, lan_dir, hist_lan_dir):
            _p.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output dirs overridden by --output-dir: {args.output_dir}")
    else:
        dirs = ensure_soc_dirs(agent_id)
        pre_dir = dirs["pre_dir"]
        lan_dir = dirs["lan_dir"]
        hist_lan_dir = dirs["hist_lan_dir"]

    from common.cosight_runtime import resolve_runtime_llm_config

    llm_config = resolve_runtime_llm_config("full_build")
    if not llm_config:
        # 构建链需要 LLM（图片多模态识别/章节润色），纯环境变量配置
        logger.error(
            "未找到 LLM 配置——请在 data/.env 中配置 OPENAI_BASE_URL/"
            "OPENAI_API_KEY/OPENAI_MODEL（未配时将回退会话继承的 ANTHROPIC_*），"
            "详见 README 环境变量表；或用 --skip-vision 跳过图片识别后重试"
        )
        sys.exit(1)

    from common.index_api import get_full_status_data, update_file_info, _update_status

    recorded_files = None
    if not force:
        try:
            status_data = get_full_status_data(lan_dir)
            files = status_data.get("files") if status_data else None
            if isinstance(files, dict) and files:
                # 断点续跑：指纹逐文件落盘（LanceDB 写入成功后才写指纹，单文件粒度
                # 一致），与顶层 status 无关。上次构建中途失败（如 embedding 服务
                # 不可用）时 status 永远到不了 ready，但已成功文件的指纹依旧可信——
                # 有效性由 per-file 条目的 status=="success" 强校验
                # （_is_fingerprint_match 内部），顶层 status 不再作为加载闸门。
                recorded_files = files
                top_status = status_data.get("status")
                if top_status == "ready":
                    logger.info(f"Loaded {len(recorded_files)} recorded files for fingerprint skip")
                else:
                    logger.info(
                        f"Resuming from incomplete build (status={top_status!r}): "
                        f"{len(recorded_files)} recorded files eligible for fingerprint skip"
                    )
        except Exception as e:
            logger.warning(f"Failed to load recorded files: {e}")

    logger.info("Step 1: Per-file preprocessing + incremental vector update (common docs)...")

    specs_pd_dir = source_dir / SPECS_PD_DIR
    # 收集当前 specs_pd_dir 下所有合法文件（POSIX rel path，相对 specs_pd_dir）
    # workspace_root = specs_pd_dir，所以 recorded_files key 也是相对 specs_pd_dir。
    # 只收入库白名单格式（office+pdf+文本，不含独立图片）：历史版本摄入过的
    # 不支持文件（html/图片等）不在集合里 → 下方孤儿清理自动删掉它们的
    # 指纹 + 向量行 + pre-md，实现重建时清残留。
    from watch_dog.file_watcher.preprocessor import is_build_indexable

    valid_specs: set[str] = set()
    if specs_pd_dir.is_dir():
        for f in specs_pd_dir.rglob("*"):
            if not f.is_file() or f.name.startswith("~$") or f.name.startswith("."):
                continue
            if not is_build_indexable(f):
                continue
            try:
                valid_specs.add(f.relative_to(specs_pd_dir).as_posix())
            except ValueError:
                continue

    # 01_Specs_PD 不做空源守卫：用户从云盘删除全部规格文档后，希望本地
    # 对应表也变成空库。下方孤儿清理会把 recorded 有、source 没有的条目
    # 全部删除，从而产生空表（--force 下仍不参与孤儿清理）。

    # Step 1a: 清理孤儿（recorded_files 有但 source 里没了的文件）
    #   对每个 status 孤儿调 handle_common_file_event('deleted')，
    #   删 fingerprint + nodes/chapters 行 + pre_dir .md。
    #   handler 内部已包含 _delete_pre_md，所以 pre_dir .md 也会被清理。
    #   删除会改变本地库内容，必须计数并阻止后续的 build_skipped 跳过上传。
    common_deleted_count = 0
    if not force and recorded_files:
        orphan_keys = [k for k in recorded_files.keys() if k not in valid_specs]
        common_deleted_count = len(orphan_keys)
        if common_deleted_count:
            logger.info(f"Removing {common_deleted_count} orphan file(s) deleted from source")
        for k in orphan_keys:
            handle_common_file_event(
                str(specs_pd_dir / k),  # 文件已不在 source
                "deleted",
                None,
                lan_dir,
                pre_dir,
                specs_pd_dir,
                llm_config,
                skip_vision=skip_vision,
            )

    # Step 1b: 对每个 source 文件调 handle_common_file_event('created')
    #   - 新文件：直接 insert
    #   - 文件未变：fingerprint 在 recorded_files 里 → handler 内部 process_single_file 会
    #     基于指纹匹配跳过 .md 生成；但即使是 modified/fingerprint-matched，handler 仍
    #     会按 file_path 删旧行再 insert（幂等于重新构建）。这里我们用 fingerprint 提前
    #     决定是否调用 handler（真正的指纹跳过在 process_single_file 内部）。
    #   - 文件变了：按 file_path 删旧行 + insert 新行 + 更新 fingerprint
    success_count = 0
    failed_count = 0
    skipped_count = 0

    if specs_pd_dir.is_dir():
        # 预扫描：收集要进 handler 的文件（指纹不命中的），
        # 给进度面板 add_waiting 一个准确的等待计数。
        # 指纹命中的文件不进 handler（不进 start_processing），
        # 走共享的 _is_fingerprint_match 提前 continue 即可。
        from watch_dog.file_watcher.preprocessor import _is_fingerprint_match
        from watch_dog.file_watcher.embedding_model import EmbeddingServiceError

        files_to_process: list = []
        for f in specs_pd_dir.rglob("*"):
            if not f.is_file() or f.name.startswith("~$") or f.name.startswith("."):
                continue
            if not is_build_indexable(f):
                continue
            try:
                rel = f.relative_to(specs_pd_dir).as_posix()
            except ValueError:
                continue
            if not force and recorded_files:
                if _is_fingerprint_match(f, specs_pd_dir, recorded_files, pre_dir,
                                        skip_vision=skip_vision):
                    skipped_count += 1
                    continue
            files_to_process.append(f)

        # 进度面板：把"实际要处理的文件数"加到 waiting 计数
        if files_to_process:
            from watch_dog.file_watcher.progress_ui import global_progress
            if hasattr(global_progress, "add_waiting"):
                global_progress.add_waiting(len(files_to_process))
                # 给进度输出线程让出 CPU，让 [progress] 行先于重 CPU 处理刷出。
                time.sleep(0.15)

        consecutive_embed_failures = 0
        for f in files_to_process:
            if not f.is_file() or f.name.startswith("~$") or f.name.startswith("."):
                continue
            try:
                rel = f.relative_to(specs_pd_dir).as_posix()
            except ValueError:
                continue

            # Fingerprint 跳过：如果 recorded 里命中且 .md 已存在，直接跳过整个 handler 调用
            if not force and recorded_files:
                if _is_fingerprint_match(f, specs_pd_dir, recorded_files, pre_dir,
                                        skip_vision=skip_vision):
                    skipped_count += 1
                    continue

            try:
                ok = handle_common_file_event(
                    str(f),
                    "created",
                    None,
                    lan_dir,
                    pre_dir,
                    specs_pd_dir,
                    llm_config,
                    skip_vision=skip_vision,
                )
            except EmbeddingServiceError as e:
                # 单文件 embedding 失败不再整库中止：记 failed 继续后续文件
                # （毒 chunk 只影响一个文件；无指纹落盘，下次构建自动补该文件）。
                # 连续失败说明 embedding 服务侧故障，继续跑只会把每个文件都拖满
                # 重试超时——熔断中止整个构建。
                failed_count += 1
                consecutive_embed_failures += 1
                logger.error(
                    f"Embedding failed for {rel} "
                    f"(consecutive={consecutive_embed_failures}): {e}"
                )
                if consecutive_embed_failures >= EMBED_CIRCUIT_BREAKER_THRESHOLD:
                    raise RuntimeError(
                        f"Embedding service appears down: "
                        f"{consecutive_embed_failures} consecutive file failures, "
                        f"aborting build (last error: {e})"
                    ) from e
                time.sleep(0.05)
                continue
            except Exception as e:
                # 单文件转换/解析失败同样只计 failed 不整库中止（2026-09-17 真实
                # 事故：伪装 .doc（实际 themeManager+xml）让 docx.Document 抛
                # ValueError，一路冒泡炸死整个 runner，库内剩余几百个文件全部
                # 没构建；且错误消息里的 surrogate 文件名在写日志时又触发
                # UnicodeEncodeError，连 status.json 都没写成）。与 embedding 分支
                # 同语义：无指纹落盘，下次构建自动补该文件。surrogate 文件名只
                # 影响日志可读性，不再具有杀伤力（runner 日志 handler 已加
                # errors=replace）。
                failed_count += 1
                logger.error(f"File processing failed for {rel}: {e}")
                time.sleep(0.05)
                continue
            if ok:
                success_count += 1
                consecutive_embed_failures = 0
            else:
                failed_count += 1
            # 让进度输出在重 CPU 处理之间有机会刷出（每文件 50ms，可忽略）。
            time.sleep(0.05)

        stats["preprocessed_files"] = skipped_count + success_count + failed_count
        stats["preprocess_success"] = skipped_count + success_count
        stats["preprocess_failed"] = failed_count
        stats["common_upserted"] = success_count
        logger.info(
            f"Common docs: {success_count} upserted, {skipped_count} fingerprint-skipped, "
            f"{failed_count} failed"
        )

        # 若 Step 1 有失败，给进度面板 1.5s 窗口渲染错误详情。
        # _close_delayed 是固定 1.2s 计时器：到期时若 waiting/processing > 0
        # （Step 3 的 add_waiting 已经抵达）就会被 abort，错误面板不再显示。
        # 实测：失败 build 在 Step 1 → Step 3 间隔 < 1.2s 时，progress UI 不会
        # 显示 "Job finished with X failures" 面板；间隔 > 1.2s 才会显示。
        if failed_count > 0:
            logger.info(
                f"Pausing 1.5s to let progress UI render error panel before Step 3..."
            )
            time.sleep(1.5)

    common_all_skipped = (
        not force
        and recorded_files is not None
        and success_count == 0
        and failed_count == 0
        and skipped_count == len(valid_specs)
        and common_deleted_count == 0
    )

    if common_all_skipped:
        stats["common_skipped"] = True
        logger.info("All common files fingerprint-matched, skipping index build.")
    else:
        stats["common_built"] = True
        # 删除是软删除（tombstone），不 compact 的话已删文件的向量数据
        # 仍留在数据文件里，会随 zip 一起上传到服务器。
        if success_count > 0 or common_deleted_count > 0:
            logger.info("Step 2: Optimizing common index tables...")
            from watch_dog.file_watcher.search import optimize_table
            try:
                optimize_table(lan_dir, "nodes")
            except Exception as oe:
                logger.warning(f"Failed to optimize nodes table: {oe}")
            try:
                optimize_table(lan_dir, "chapters")
            except Exception as oe:
                logger.warning(f"Failed to optimize chapters table: {oe}")

        _update_status(lan_dir, "ready")
        logger.info("Common index status set to 'ready'.")

        # ======== [CoSight-START] feature: soc-general-qa ========
        # 生成紧凑版 overview.md + node_index.json（[DIR]/[F###] 节点 +
        # 文件节点下展开章节标题，超行数上限时 overview_builder 自动降级为
        # 纯节点树），落在 lan_dir 下、随 Step 3 整目录 zip 上传到服务器，
        # 客户端 rag_sync 下载后即可供 soc-general-qa-skill 做文件级过滤检索。
        # fail-soft：overview 生成失败不阻断向量库交付（qa.py 对缺失
        # node_index.json 有明确的业务失败提示，管理员可用
        # `sync_soc_rag --build-overview-only` 单独补生成）。
        try:
            from watch_dog.file_watcher.overview_builder import (
                clear_overview_md,
                write_overview_md,
            )

            if any(pre_dir.rglob("*.md")):
                out = write_overview_md(
                    lan_dir=lan_dir, pre_dir=pre_dir,
                    compact=True, show_sections=True,
                )
                if out is not None:
                    logger.info(
                        "Compact overview.md / node_index.json generated for soc-general-qa."
                    )
                else:
                    # pre_dir 里的 .md 全在 references/assets 等排除目录、或写盘失败——
                    # fail-soft 不阻断交付，但日志必须如实记录产物未生成
                    logger.warning(
                        "write_overview_md returned None (no indexable .md after "
                        "filtering, or write failed); overview products NOT updated."
                    )
            else:
                # pre_dir 被清空（全部孤儿删除/目录清空场景）→ 同步清掉
                # overview 产物，避免旧树继续下发到客户端
                clear_overview_md(lan_dir)
                logger.info(
                    "pre_dir has no .md; cleared stale overview.md / node_index.json."
                )
        except Exception as e:
            logger.warning(f"Failed to generate compact overview: {e}")

        # node_sections.json（文件节点 → 章节标题列表）：供 qa.py --sections
        # 按需下钻（主 overview.md 只列目录与文件节点，大库章节全展开会
        # 超出 agent 上下文预算）。同样 fail-soft 不阻断交付；客户端缺此
        # 产物时 --sections 有明确的业务失败提示。
        try:
            from common.soc_kb_builder.vector_build.node_sections import write_node_sections

            sections_path = write_node_sections(lan_dir)
            logger.info(f"node_sections.json generated: {sections_path}")
        except Exception as e:
            logger.warning(f"Failed to generate node_sections.json: {e}")
        # ======== [CoSight-END] feature: soc-general-qa ========

    from common.soc_kb_builder.vector_build.historical_processor import (
        _is_historical_fingerprint_match,
        handle_historical_file_event,
        _update_historical_status,
    )
    from watch_dog.file_watcher.embedding_model import EmbeddingServiceError
    from watch_dog.file_watcher.search import optimize_table

    hist_dir = source_dir / HISTORICAL_RESPONSES_DIR
    hist_all_skipped = False
    # workspace_root = hist_dir，所以 recorded_files_hist key 也是相对 hist_dir 的
    # POSIX 路径（不再带 02_Historical_Responses/ 前缀，与 common handler 对称）。
    #
    # 关键修复：recorded_files_hist 与 valid_hist 的读取必须放在 if-block 外面，
    # 否则当 sync_soc_rag 因目录为空而 rmdir 掉整个 02_Historical_Responses/ 后，
    # build_soc_vector 进入 else 分支（"No historical responses directory found"），
    # recorded_files_hist 永远是 None → 下方孤儿指纹清理块整体被跳过 →
    # historical_paradigms/.llamaindex_status 残留指纹无法被清理，用户重新上传同一份
    # 文件后会被 fingerprint 命中、跳过重新学习。
    valid_hist: set[str] = set()
    if hist_dir.exists() and hist_dir.is_dir():
        # 收集当前 hist_dir 下所有合法历史应答文件（相对 hist_dir 的 POSIX 路径）
        for f in hist_dir.rglob("*"):
            if not f.is_file() or f.name.startswith("~$"):
                continue
            if f.suffix.lower() not in (".xlsx", ".csv"):
                continue
            try:
                valid_hist.add(f.relative_to(hist_dir).as_posix())
            except ValueError:
                continue

    # Read status from .llamaindex_status (written by _update_historical_status)
    # status 仅用于日志：指纹有效性由 per-file 条目的 status=="success" 强校验
    # （_is_historical_fingerprint_match 内部），顶层 status 不作为加载闸门——
    # 否则上次构建中途失败（status 停在 initializing）会把已成功文件的指纹
    # 整体废弃，重跑推倒重来。hist_dir 不存在时也照读。
    hist_status = "none"
    hist_status_file = hist_lan_dir / ".llamaindex_status"
    try:
        import json as _json
        if hist_status_file.exists():
            with open(hist_status_file, "r", encoding="utf-8-sig") as _f:
                hist_status = _json.load(_f).get("status", "none")
    except Exception:
        pass

    recorded_files_hist = None
    if not force:
        try:
            from common.index_api import get_all_file_info
            recorded_files_hist = get_all_file_info(hist_lan_dir) or None
            if recorded_files_hist and hist_status != "ready":
                logger.info(
                    f"Resuming historical from incomplete build (status={hist_status!r}): "
                    f"{len(recorded_files_hist)} recorded files eligible for fingerprint skip"
                )
        except Exception as e:
            logger.warning(f"Failed to load historical fingerprints: {e}")

    # 02_Historical_Responses 不做空源守卫：用户从云盘删除全部历史应答后，
    # 希望本地对应表也变成空库。下方孤儿清理会把 recorded 有、source 没有的
    # 条目全部删除，从而产生空表（--force 下仍不参与孤儿清理）。

    if hist_dir.exists() and hist_dir.is_dir():
        logger.info("Step 3: Processing historical responses...")

        _update_historical_status(hist_lan_dir, "initializing", source_dir=source_dir)

        files = [
            f
            for f in hist_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in [".xlsx", ".csv"] and not f.name.startswith("~$")
        ]
        stats["historical_total"] = len(files)

        if files:
            if recorded_files_hist and not force:
                to_process = []
                skipped = 0
                for f in files:
                    if _is_historical_fingerprint_match(f, hist_dir, recorded_files_hist):
                        skipped += 1
                    else:
                        to_process.append(f)
                logger.info(
                    f"Historical fingerprint pre-filter: "
                    f"{len(to_process)}/{len(files)} to process, {skipped} skipped"
                )
                stats["historical_skipped"] = skipped
                files = to_process

            if files:
                hist_lan_dir.mkdir(parents=True, exist_ok=True)
                stats["historical_processed"] = len(files)
                hist_success_count = 0
                hist_fail_count = 0
                hist_consecutive_embed_failures = 0
                for f in files:
                    # handle_historical_file_event 现在直接走 index_api 写指纹，
                    # 不再需要 build_soc_vector 在这里手工补 update_file_info
                    try:
                        success = handle_historical_file_event(
                            str(f),
                            "created",
                            None,
                            hist_lan_dir,
                            workspace_root=hist_dir,
                        )
                    except EmbeddingServiceError as e:
                        # 与普通文档同策略：单文件记 failed 继续（无指纹落盘，
                        # 下次构建自动补）；连续失败判定服务故障，熔断中止。
                        hist_fail_count += 1
                        hist_consecutive_embed_failures += 1
                        logger.error(
                            f"Historical embedding failed for {f.name} "
                            f"(consecutive={hist_consecutive_embed_failures}): {e}"
                        )
                        if hist_consecutive_embed_failures >= EMBED_CIRCUIT_BREAKER_THRESHOLD:
                            raise RuntimeError(
                                f"Embedding service appears down: "
                                f"{hist_consecutive_embed_failures} consecutive historical "
                                f"file failures, aborting build (last error: {e})"
                            ) from e
                        continue
                    if not success:
                        hist_fail_count += 1
                        logger.warning(f"Historical processing failed for {f.name}")
                        continue
                    hist_success_count += 1
                    hist_consecutive_embed_failures = 0
                if hist_fail_count > 0:
                    logger.warning(f"Historical: {hist_fail_count}/{len(files)} files failed processing")
                else:
                    logger.info(f"Historical: all {len(files)} files processed successfully")
                stats["historical_upserted"] = hist_success_count

                try:
                    optimize_table(hist_lan_dir, "response_paradigm")
                except Exception as oe:
                    logger.warning(f"Failed to optimize historical table: {oe}")

                _update_historical_status(hist_lan_dir, "ready", source_dir=source_dir)
                logger.info("Historical: All files processed")
            else:
                hist_all_skipped = recorded_files_hist is not None
                stats["historical_all_skipped"] = hist_all_skipped
                _update_historical_status(hist_lan_dir, "ready", source_dir=source_dir)
                logger.info("Historical: All files fingerprint-matched, nothing to do.")
        else:
            hist_all_skipped = True
            stats["historical_all_skipped"] = True
            _update_historical_status(hist_lan_dir, "ready", source_dir=source_dir)
            logger.info("Historical: No files found.")
    else:
        hist_all_skipped = True
        stats["historical_all_skipped"] = True
        logger.info("No historical responses directory found, skipping.")

    # 清理孤儿指纹 + response_paradigm 表行
    # 复用 handle_historical_file_event('deleted') —— 它现在直接走 index_api，
    # 独立脚本下指纹清理和 response_paradigm 行清理都生效。
    # 放在 if-block 外：02_Historical_Responses/ 里部分文件被删除时，
    # 也得跑这一步把 .llamaindex_status 里残留的孤儿指纹清掉。
    # 注：02_Historical_Responses 不做空源守卫，因此整目录缺失/清空且
    # recorded 非空时也会走到这里；此时 valid_hist 为空，全部 recorded 条目
    # 会被当孤儿删除，最终得到空表（符合用户清空云盘后本地也清空的需求）。
    hist_deleted_count = 0
    if not force and recorded_files_hist:
        orphan_hist_keys = [
            k for k in recorded_files_hist.keys() if k not in valid_hist
        ]
        hist_deleted_count = len(orphan_hist_keys)
        if hist_deleted_count:
            logger.info(f"Removing {hist_deleted_count} orphan historical entrie(s) deleted from source")
        for k in orphan_hist_keys:
            orphan_path = hist_dir / k
            handle_historical_file_event(
                str(orphan_path),
                "deleted",
                None,
                hist_lan_dir,
                workspace_root=hist_dir,
            )

    # 纯删除时上面的处理分支不会跑，这里补上 compact，物理清掉 tombstone 行。
    if hist_deleted_count > 0 and stats["historical_processed"] == 0 and hist_lan_dir.exists():
        try:
            optimize_table(hist_lan_dir, "response_paradigm")
        except Exception as oe:
            logger.warning(f"Failed to optimize historical table after deletions: {oe}")

    # 根据 01_Specs_PD 目录结构生成/更新 product_taxonomy.json
    # 该文件会随 pd_spec_vector_library ZIP 一起上传，respond.py 应答时按需加载。
    try:
        if specs_pd_dir.is_dir():
            taxonomy = generate_product_taxonomy(specs_pd_dir)
            taxonomy_path = lan_dir / "product_taxonomy.json"
            taxonomy_path.write_text(
                json.dumps(taxonomy, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                f"Generated product_taxonomy.json with {len(taxonomy['categories'])} "
                f"categories at {taxonomy_path}"
            )
    except Exception as e:
        logger.warning(f"Failed to generate product_taxonomy.json: {e}")

    stats["common_deleted"] = common_deleted_count
    stats["historical_deleted"] = hist_deleted_count

    if common_all_skipped and hist_all_skipped and hist_deleted_count == 0:
        stats["build_skipped"] = True
        logger.info("All files fingerprint-matched, no build needed.")
        return 2, stats

    logger.info("SOC vector build completed successfully.")
    return 0, stats


def main():
    parser = argparse.ArgumentParser(description="SOC Agent 独立全量构建脚本")
    parser.add_argument(
        "--source",
        required=True,
        help="源文件目录（含 01_Specs_PD、02_Historical_Responses 子目录）",
    )
    parser.add_argument("--force", action="store_true", help="强制全量重建，跳过指纹校验")
    parser.add_argument("--agent-id", default="soc", help="SOC 域 ID（默认 soc → data/workspace-soc/）")
    parser.add_argument(
        "--skip-vision",
        action="store_true",
        help="跳过 PDF/DOC/DOCX 的图片多模态识别（vision pipeline），"
        "直接走纯文本转换路径。大文件图多时显著加速，避免把整晚耗在 vision_client 上。",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="构建产物输出根目录（soc-kb-builder 多 KB 模式传入 builds/<kb_id>/）。"
        "指定后 pre-processed 与 lancedb 全部落到 <output_dir>/{pre-processed,lancedb}/<table>/；"
        "缺省保持 legacy 固定路径 workspace-{agent_id}/llamaindex_data/ 不变。",
    )
    args = parser.parse_args()

    rc, stats = run_build(args)
    print(f"STATS_JSON: {json.dumps(stats)}", flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)
