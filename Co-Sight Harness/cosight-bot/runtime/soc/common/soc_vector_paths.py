#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC Agent 向量库固定路径 API

SOC 解绑本地目录后，向量库不再通过 `get_route_key(material_dir, ...)` 的 MD5 路由，
改为以下固定目录（位于 workspace-{agent_id}/llamaindex_data/ 下）：

  - pd_spec_vector_library     普通文档（产品规范/标书素材）向量库
  - historical_paradigms       历史应答标书向量库（与 file_watcher.config 保持一致）

所有涉及 SOC 向量库读写的新老代码都应通过本模块获取路径，禁止自行拼接。
"""
import os
from pathlib import Path

# SOC 固定的两个向量库目录名（lancedb 表目录）
SOC_PD_SPEC_VECTOR_NAME = "pd_spec_vector_library"
SOC_HISTORICAL_VECTOR_NAME = "historical_paradigms"
# 预处理后的 Markdown 目录名（与 pd_spec_vector_library 对应）
SOC_PD_SPEC_PRE_NAME = "pd_spec_vector_library"

# 历史应答源文件子目录（SOC 专用；通用智能体不再处理历史应答）。
HISTORICAL_RESPONSES_DIR = os.environ.get("HISTORICAL_RESPONSES_DIR", "02_Historical_Responses")
# 普通文档约定的产品规范子目录（仅作为约定布局，不影响路径计算）
SPECS_PD_DIR = "01_Specs_PD"

# 下载源文件的固定落地目录名（相对 workspace-{agent_id}/ 下）
SOC_SOURCE_DOWNLOAD_NAME = "source_download"

# .last_updated 时间戳文件相对位置（相对 workspace-{agent_id}/llamaindex_data/）
LAST_UPDATED_FILENAME = ".last_updated"


def cosight_state_root() -> Path:
    """数据根目录（工作目录下 data/，COSIGHTBOT_HOME 覆盖）。

    单一来源在 common.port_resolver；此处委托，保持既有调用方零改动。
    """
    from common.port_resolver import cosight_state_root as _root

    return _root()


def soc_workspace_root(agent_id: str = "soc") -> Path:
    """SOC 域的 workspace 根目录：data/workspace-{agent_id}（默认 workspace-soc）。"""
    return cosight_state_root() / f"workspace-{agent_id}"


def soc_llamaindex_data_root(agent_id: str = "soc") -> Path:
    """SOC 域存放 LlamaIndex 产物的根目录。"""
    return soc_workspace_root(agent_id) / "llamaindex_data"


def kbs_root(agent_id: str = "soc") -> Path:
    """多 KB 模式的运行时根目录：<workspace_root>/kbs/。

    每个 KB 在该目录下有独立的子目录：
      kbs/<kb_id>/
        ├── pd_spec_vector_library/   # 产品规范向量库
        ├── historical_paradigms/     # 历史应答范式库
        └── pre-processed/            # (本地 KB) 预处理产物

    注意：这是 soc_vector_paths 的规范定义；common.soc_kb_registry.paths
    中的同名函数委托到这里，两处路径计算保持单一来源。
    """
    return soc_workspace_root(agent_id) / "kbs"


def soc_pd_spec_lancedb_dir(agent_id: str = "soc") -> Path:
    """pd_spec_vector_library 向量库目录（含 nodes.lance / chapters.lance 等）。"""
    return soc_llamaindex_data_root(agent_id) / "lancedb" / SOC_PD_SPEC_VECTOR_NAME


def soc_pd_spec_pre_dir(agent_id: str = "soc") -> Path:
    """pd_spec_vector_library 预处理后的 Markdown 目录。"""
    return soc_llamaindex_data_root(agent_id) / "pre-processed" / SOC_PD_SPEC_PRE_NAME


def soc_historical_lancedb_dir(agent_id: str = "soc") -> Path:
    """historical_paradigms 历史应答向量库目录。"""
    return soc_llamaindex_data_root(agent_id) / "lancedb" / SOC_HISTORICAL_VECTOR_NAME


def soc_source_download_dir(agent_id: str = "soc") -> Path:
    """源文件固定落地目录。"""
    return soc_workspace_root(agent_id) / SOC_SOURCE_DOWNLOAD_NAME


def soc_last_updated_file(agent_id: str = "soc") -> Path:
    """SOC 向量库构建完成时间戳文件。"""
    return soc_llamaindex_data_root(agent_id) / LAST_UPDATED_FILENAME


def soc_llamaindex_status_file(agent_id: str = "soc") -> Path:
    """普通文档向量库的 .llamaindex_status 文件路径。"""
    return soc_pd_spec_lancedb_dir(agent_id) / ".llamaindex_status"


def soc_historical_status_file(agent_id: str = "soc") -> Path:
    """历史应答向量库的 .historical_status 文件路径。"""
    return soc_historical_lancedb_dir(agent_id) / ".historical_status"


def soc_build_output_dirs(
    agent_id: str = "soc",
    output_dir: "str | Path | None" = None,
) -> dict:
    """向量库构建产物目录（pre_dir / lan_dir / hist_lan_dir）的单一解析来源。

    - output_dir=None（legacy 单 KB 模式）：固定路径
      workspace-{agent_id}/llamaindex_data/{pre-processed,lancedb}/<table>/
    - output_dir 指定（soc-kb-builder 多 KB 模式）：全部产物隔离到
      <output_dir>/{pre-processed,lancedb}/<table>/，每个 KB 独占自己的
      builds/<kb_id>/，互不覆盖。

    只计算路径，不创建目录（调用方按需 mkdir）。
    """
    if output_dir is None:
        return {
            "pre_dir": soc_pd_spec_pre_dir(agent_id),
            "lan_dir": soc_pd_spec_lancedb_dir(agent_id),
            "hist_lan_dir": soc_historical_lancedb_dir(agent_id),
        }
    root = Path(output_dir)
    return {
        "pre_dir": root / "pre-processed" / SOC_PD_SPEC_PRE_NAME,
        "lan_dir": root / "lancedb" / SOC_PD_SPEC_VECTOR_NAME,
        "hist_lan_dir": root / "lancedb" / SOC_HISTORICAL_VECTOR_NAME,
    }


def ensure_soc_dirs(agent_id: str = "soc") -> dict:
    """按需创建 SOC 所有相关目录并返回路径字典。

    返回：
        {
            "workspace":    Path,
            "llamaindex":   Path,
            "pre_dir":      Path,
            "lan_dir":      Path,
            "hist_lan_dir": Path,
            "source_dir":   Path,
        }
    """
    dirs = {
        "workspace":    soc_workspace_root(agent_id),
        "llamaindex":   soc_llamaindex_data_root(agent_id),
        "pre_dir":      soc_pd_spec_pre_dir(agent_id),
        "lan_dir":      soc_pd_spec_lancedb_dir(agent_id),
        "hist_lan_dir": soc_historical_lancedb_dir(agent_id),
        "source_dir":   soc_source_download_dir(agent_id),
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    return dirs
