# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
LightRAG 知识库管理代理路由
将前端请求代理转发到 LightRAG REST API 服务
"""

import os
import sys
import json
import signal
import asyncio
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, UploadFile, File, Body

from app.common.logger_util import logger

knowledgeBaseRouter = APIRouter()

# ---------- LightRAG 服务进程管理 ----------
_lightrag_process: Optional[subprocess.Popen] = None
_lightrag_log_lines: List[str] = []


# ---------- 工具函数 ----------

def _get_lightrag_base_url() -> str:
    return os.getenv("LIGHTRAG_BASE_URL", "http://localhost:9621").rstrip("/")


def _get_lightrag_api_key() -> Optional[str]:
    return os.getenv("LIGHTRAG_API_KEY") or None


def _get_storage_dir() -> str:
    return os.getenv("LIGHTRAG_STORAGE_DIR", "lightrag_storage")


def _get_kb_meta_path() -> str:
    """知识库元数据文件路径"""
    storage_dir = _get_storage_dir()
    os.makedirs(storage_dir, exist_ok=True)
    return os.path.join(storage_dir, "kb_meta.json")


def _load_kb_meta() -> List[Dict]:
    """加载知识库元数据"""
    meta_path = _get_kb_meta_path()
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_kb_meta(meta: List[Dict]):
    """保存知识库元数据"""
    meta_path = _get_kb_meta_path()
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _build_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = _get_lightrag_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def _proxy_get(path: str, params: dict = None, workspace: str = None) -> dict:
    """代理 GET 请求到 LightRAG"""
    url = f"{_get_lightrag_base_url()}{path}"
    headers = _build_headers()
    if workspace:
        headers["LIGHTRAG-WORKSPACE"] = workspace
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


async def _proxy_post(path: str, data: Any = None, files: dict = None, workspace: str = None) -> dict:
    """代理 POST 请求到 LightRAG"""
    url = f"{_get_lightrag_base_url()}{path}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        if files:
            headers = {}
            api_key = _get_lightrag_api_key()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            if workspace:
                headers["LIGHTRAG-WORKSPACE"] = workspace
            resp = await client.post(url, headers=headers, files=files, data=data or {})
        else:
            headers = _build_headers()
            if workspace:
                headers["LIGHTRAG-WORKSPACE"] = workspace
            resp = await client.post(url, headers=headers, json=data)
        resp.raise_for_status()
        return resp.json()


async def _proxy_delete(path: str, params: dict = None, data: Any = None, workspace: str = None) -> dict:
    """代理 DELETE 请求到 LightRAG"""
    url = f"{_get_lightrag_base_url()}{path}"
    headers = _build_headers()
    if workspace:
        headers["LIGHTRAG-WORKSPACE"] = workspace
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request("DELETE", url, headers=headers, params=params, json=data)
        resp.raise_for_status()
        return resp.json()


# ---------- LightRAG 服务启停 ----------

def _get_lightrag_work_dir() -> str:
    """获取 LightRAG 专用工作目录"""
    explicit = os.getenv("LIGHTRAG_SERVER_DIR")
    if explicit:
        os.makedirs(explicit, exist_ok=True)
        return explicit
    # 默认使用与 kb_meta.json 同级的 lightrag_data 目录
    storage = os.path.abspath(os.getenv("LIGHTRAG_STORAGE_DIR", "./lightrag_data"))
    os.makedirs(storage, exist_ok=True)
    return storage


def _write_lightrag_env_file(work_dir: str):
    """在 LightRAG 工作目录下生成格式正确的 .env 文件"""
    lines = []

    # 端口
    base_url = os.getenv("LIGHTRAG_BASE_URL", "http://localhost:9621")
    parsed = urlparse(base_url)
    port = str(parsed.port or 9621)
    lines.append(f"HOST=0.0.0.0")
    lines.append(f"PORT={port}")

    # LLM
    lines.append("LLM_BINDING=openai")
    if os.getenv("API_BASE_URL"):
        lines.append(f"LLM_BINDING_HOST={os.getenv('API_BASE_URL')}")
    if os.getenv("API_KEY"):
        lines.append(f"LLM_BINDING_API_KEY={os.getenv('API_KEY')}")
    if os.getenv("MODEL_NAME"):
        lines.append(f"LLM_MODEL={os.getenv('MODEL_NAME')}")

    # Embedding
    lines.append("EMBEDDING_BINDING=openai")
    emb_mapping = {
        "LIGHTRAG_EMBEDDING_API_KEY": "EMBEDDING_BINDING_API_KEY",
        "LIGHTRAG_EMBEDDING_API_BASE": "EMBEDDING_BINDING_HOST",
        "LIGHTRAG_EMBEDDING_MODEL": "EMBEDDING_MODEL",
        "LIGHTRAG_EMBEDDING_DIM": "EMBEDDING_DIM",
        "LIGHTRAG_EMBEDDING_MAX_TOKENS": "EMBEDDING_TOKEN_LIMIT",
    }
    for src, dst in emb_mapping.items():
        val = os.getenv(src)
        if val:
            lines.append(f"{dst}={val}")

    # Rerank
    rerank_enabled = os.getenv("LIGHTRAG_RERANK_ENABLED", "False").lower() in ("true", "1", "yes")
    if rerank_enabled:
        lines.append("RERANK_BINDING=cohere")
        rerank_mapping = {
            "LIGHTRAG_RERANK_API_KEY": "RERANK_BINDING_API_KEY",
            "LIGHTRAG_RERANK_API_BASE": "RERANK_BINDING_HOST",
            "LIGHTRAG_RERANK_MODEL": "RERANK_MODEL",
        }
        for src, dst in rerank_mapping.items():
            val = os.getenv(src)
            if val:
                lines.append(f"{dst}={val}")
    else:
        lines.append("RERANK_BINDING=null")

    env_path = os.path.join(work_dir, ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    logger.info(f"Generated LightRAG .env file at {env_path}")


@knowledgeBaseRouter.post("/deep-research/kb/start-service")
async def kb_start_service():
    """启动 LightRAG 服务"""
    global _lightrag_process, _lightrag_log_lines

    # 先检查是否已在运行
    try:
        result = await _proxy_get("/health")
        return {"code": 0, "data": {"status": "already_running", "message": "LightRAG 服务已在运行中"}}
    except Exception:
        pass

    # 如果有旧进程引用但进程已死，清理掉
    if _lightrag_process is not None:
        if _lightrag_process.poll() is not None:
            # 进程已退出，清理引用
            _lightrag_process = None
        else:
            # 进程还活着但 health check 失败（上面已经试过了）
            # 再给几秒机会，可能还在启动中
            logger.info("LightRAG process alive but health check failed, waiting...")
            for _ in range(5):
                await asyncio.sleep(2)
                try:
                    await _proxy_get("/health")
                    _lightragStatus = 'connected'
                    return {"code": 0, "data": {"status": "already_running", "message": "LightRAG 服务已就绪"}}
                except Exception:
                    if _lightrag_process.poll() is not None:
                        _lightrag_process = None
                        break
            # 如果仍然不通，杀掉旧进程重新启动
            if _lightrag_process is not None:
                logger.warning("LightRAG process unresponsive, killing and restarting...")
                try:
                    _lightrag_process.terminate()
                    _lightrag_process.wait(timeout=5)
                except Exception:
                    try:
                        _lightrag_process.kill()
                        _lightrag_process.wait(timeout=3)
                    except Exception:
                        pass
                _lightrag_process = None

    try:
        # 准备专用工作目录和 .env 文件
        work_dir = _get_lightrag_work_dir()
        _write_lightrag_env_file(work_dir)

        cmd = os.getenv("LIGHTRAG_START_CMD", "lightrag-server")
        logger.info(f"Starting LightRAG service: cmd={cmd}, cwd={work_dir}")
        _lightrag_log_lines = []

        creation_flags = 0
        startup_env = os.environ.copy()
        # 强制 UTF-8 编码，避免 Windows GBK 无法输出 emoji 导致崩溃
        startup_env["PYTHONIOENCODING"] = "utf-8"
        startup_env["PYTHONUTF8"] = "1"
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

        _lightrag_process = subprocess.Popen(
            cmd.split(),
            env=startup_env,
            cwd=work_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )

        # 等待服务启动（最多 30 秒）
        for i in range(15):
            await asyncio.sleep(2)
            if _lightrag_process.poll() is not None:
                # 进程已退出，读取输出
                out = _lightrag_process.stdout.read().decode("utf-8", errors="replace") if _lightrag_process.stdout else ""
                _lightrag_log_lines = out.splitlines()[-50:]
                _lightrag_process = None
                log_summary = "\n".join(_lightrag_log_lines[-10:]) if _lightrag_log_lines else "无输出"
                return {"code": 1, "msg": f"LightRAG 启动失败，进程已退出。\n最后日志:\n{log_summary}", "data": {"logs": _lightrag_log_lines}}
            # 尝试 health check
            try:
                await _proxy_get("/health")
                logger.info("LightRAG service started successfully")
                return {"code": 0, "data": {"status": "started", "message": "LightRAG 服务启动成功", "pid": _lightrag_process.pid}}
            except Exception:
                continue

        return {"code": 0, "data": {"status": "starting", "message": "LightRAG 服务正在启动中，请稍候检查状态", "pid": _lightrag_process.pid}}

    except FileNotFoundError:
        _lightrag_process = None
        return {"code": 1, "msg": "找不到 lightrag-server 命令，请确认已安装 LightRAG (pip install lightrag-hku)"}
    except Exception as e:
        _lightrag_process = None
        logger.error(f"Failed to start LightRAG: {e}", exc_info=True)
        return {"code": 1, "msg": f"启动失败: {str(e)}"}


@knowledgeBaseRouter.post("/deep-research/kb/stop-service")
async def kb_stop_service():
    """停止 LightRAG 服务"""
    global _lightrag_process

    if _lightrag_process is None:
        return {"code": 0, "data": {"status": "not_running", "message": "服务未在运行"}}

    try:
        pid = _lightrag_process.pid
        if sys.platform == "win32":
            _lightrag_process.terminate()
        else:
            os.kill(pid, signal.SIGTERM)

        try:
            _lightrag_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _lightrag_process.kill()
            _lightrag_process.wait(timeout=5)

        _lightrag_process = None
        logger.info(f"LightRAG service stopped (pid={pid})")
        return {"code": 0, "data": {"status": "stopped", "message": "LightRAG 服务已停止"}}
    except Exception as e:
        logger.error(f"Failed to stop LightRAG: {e}", exc_info=True)
        _lightrag_process = None
        return {"code": 1, "msg": f"停止失败: {str(e)}"}


@knowledgeBaseRouter.get("/deep-research/kb/service-logs")
async def kb_service_logs():
    """获取 LightRAG 服务最近的日志"""
    global _lightrag_process, _lightrag_log_lines
    if _lightrag_process and _lightrag_process.stdout:
        import select
        # Non-blocking read of available output
        try:
            while True:
                line = _lightrag_process.stdout.readline()
                if not line:
                    break
                _lightrag_log_lines.append(line.decode("utf-8", errors="replace").rstrip())
                if len(_lightrag_log_lines) > 100:
                    _lightrag_log_lines = _lightrag_log_lines[-100:]
        except Exception:
            pass
    return {"code": 0, "data": {"logs": _lightrag_log_lines[-30:]}}


# ---------- 知识库 CRUD ----------

@knowledgeBaseRouter.get("/deep-research/kb/health")
async def kb_health():
    """检查 LightRAG 服务健康状态"""
    try:
        result = await _proxy_get("/health")
        return {"code": 0, "data": {"status": "connected", "detail": result}}
    except Exception as e:
        logger.warning(f"LightRAG health check failed: {e}")
        return {"code": 0, "data": {"status": "disconnected", "detail": str(e)}}


@knowledgeBaseRouter.get("/deep-research/kb/list")
async def kb_list():
    """列出所有知识库"""
    meta = _load_kb_meta()
    return {"code": 0, "data": {"knowledge_bases": meta}}


@knowledgeBaseRouter.post("/deep-research/kb/create")
async def kb_create(params: Any = Body(None)):
    """创建新知识库"""
    name = params.get("name", "").strip()
    description = params.get("description", "").strip()
    if not name:
        return {"code": 1, "msg": "知识库名称不能为空"}

    meta = _load_kb_meta()
    # 生成唯一 ID
    kb_id = f"kb_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

    # 检查名称是否重复
    for kb in meta:
        if kb["name"] == name:
            return {"code": 1, "msg": f"知识库名称 '{name}' 已存在"}

    new_kb = {
        "id": kb_id,
        "name": name,
        "description": description,
        "created_at": datetime.now().isoformat(),
        "doc_count": 0,
    }
    meta.append(new_kb)
    _save_kb_meta(meta)

    logger.info(f"Knowledge base created: {kb_id} ({name})")
    return {"code": 0, "data": new_kb}


@knowledgeBaseRouter.delete("/deep-research/kb/{kb_id}")
async def kb_delete(kb_id: str):
    """删除知识库"""
    meta = _load_kb_meta()
    found = None
    for i, kb in enumerate(meta):
        if kb["id"] == kb_id:
            found = i
            break

    if found is None:
        return {"code": 1, "msg": "知识库不存在"}

    removed = meta.pop(found)
    _save_kb_meta(meta)

    # 尝试通过 LightRAG API 清除相关数据
    try:
        await _proxy_delete("/documents", workspace=kb_id)
    except Exception as e:
        logger.warning(f"Failed to clear LightRAG data for {kb_id}: {e}")

    logger.info(f"Knowledge base deleted: {kb_id} ({removed['name']})")
    return {"code": 0, "data": {"id": kb_id}}


# ---------- 文档管理 ----------

@knowledgeBaseRouter.post("/deep-research/kb/{kb_id}/documents/upload")
async def kb_upload_document(kb_id: str, file: UploadFile = File(...)):
    """上传文档到知识库"""
    try:
        file_content = await file.read()
        files = {"file": (file.filename, file_content, file.content_type)}
        result = await _proxy_post(
            "/documents/upload",
            files=files,
            workspace=kb_id
        )
        # 更新文档计数
        _increment_doc_count(kb_id)
        return {"code": 0, "data": result}
    except httpx.HTTPStatusError as e:
        logger.error(f"Upload to LightRAG failed: {e}")
        return {"code": 1, "msg": f"上传失败: {e.response.status_code}"}
    except Exception as e:
        logger.error(f"Upload to LightRAG failed: {e}", exc_info=True)
        return {"code": 1, "msg": f"上传失败: {str(e)}"}


@knowledgeBaseRouter.post("/deep-research/kb/{kb_id}/documents/text")
async def kb_insert_text(kb_id: str, params: Any = Body(None)):
    """插入文本到知识库"""
    text = params.get("text", "").strip()
    description = params.get("description", "")
    if not text:
        return {"code": 1, "msg": "文本内容不能为空"}

    try:
        result = await _proxy_post("/documents/text", data={
            "text": text,
            "file_source": description or None,
        }, workspace=kb_id)
        _increment_doc_count(kb_id)
        return {"code": 0, "data": result}
    except Exception as e:
        logger.error(f"Insert text to LightRAG failed: {e}", exc_info=True)
        return {"code": 1, "msg": f"插入失败: {str(e)}"}


@knowledgeBaseRouter.get("/deep-research/kb/{kb_id}/documents")
async def kb_list_documents(kb_id: str):
    """获取知识库文档列表（分页）"""
    try:
        result = await _proxy_post("/documents/paginated", data={
            "page": 1,
            "page_size": 100
        }, workspace=kb_id)
        return {"code": 0, "data": result}
    except Exception as e:
        logger.warning(f"List documents failed: {e}")
        return {"code": 0, "data": {"documents": [], "pagination": {"total_count": 0}}}


@knowledgeBaseRouter.get("/deep-research/kb/{kb_id}/documents/status")
async def kb_document_status(kb_id: str):
    """获取文档处理管线状态"""
    try:
        result = await _proxy_get("/documents/pipeline_status", workspace=kb_id)
        return {"code": 0, "data": result}
    except Exception as e:
        logger.warning(f"Get pipeline status failed: {e}")
        return {"code": 0, "data": {"busy": False, "latest_message": "", "docs": 0, "batchs": 0, "cur_batch": 0}}


@knowledgeBaseRouter.get("/deep-research/kb/{kb_id}/graph-labels")
async def kb_graph_labels(kb_id: str):
    """获取知识库知识图谱的实体标签列表"""
    try:
        result = await _proxy_get("/graph/label/list", workspace=kb_id)
        return {"code": 0, "data": result}
    except Exception as e:
        logger.warning(f"Get graph labels failed: {e}")
        return {"code": 0, "data": []}


# ---------- 查询 ----------

@knowledgeBaseRouter.post("/deep-research/kb/{kb_id}/query")
async def kb_query(kb_id: str, params: Any = Body(None)):
    """查询知识库"""
    question = params.get("question", "").strip()
    mode = params.get("mode", os.getenv("LIGHTRAG_DEFAULT_QUERY_MODE", "hybrid"))
    only_context = params.get("only_context", False)

    if not question:
        return {"code": 1, "msg": "查询内容不能为空"}

    try:
        result = await _proxy_post("/query", data={
            "query": question,
            "mode": mode,
            "only_need_context": only_context,
            "stream": False,
        }, workspace=kb_id)
        return {"code": 0, "data": result}
    except Exception as e:
        logger.error(f"Query LightRAG failed: {e}", exc_info=True)
        return {"code": 1, "msg": f"查询失败: {str(e)}"}


@knowledgeBaseRouter.post("/deep-research/kb/query-multiple")
async def kb_query_multiple(params: Any = Body(None)):
    """查询多个知识库并合并结果"""
    question = params.get("question", "").strip()
    kb_ids = params.get("kb_ids", [])
    mode = params.get("mode", os.getenv("LIGHTRAG_DEFAULT_QUERY_MODE", "hybrid"))

    if not question or not kb_ids:
        return {"code": 1, "msg": "查询内容和知识库ID不能为空"}

    async def query_single(kb_id: str):
        try:
            return await _proxy_post("/query", data={
                "query": question,
                "mode": mode,
                "only_need_context": True,
                "stream": False,
            }, workspace=kb_id)
        except Exception as e:
            logger.warning(f"Query kb {kb_id} failed: {e}")
            return None

    results = await asyncio.gather(*[query_single(kb_id) for kb_id in kb_ids])

    # 合并上下文
    contexts = []
    meta = _load_kb_meta()
    for kb_id, result in zip(kb_ids, results):
        if result:
            kb_name = kb_id
            for kb in meta:
                if kb["id"] == kb_id:
                    kb_name = kb["name"]
                    break
            context_text = result if isinstance(result, str) else result.get("response", str(result))
            if context_text:
                contexts.append(f"【知识库: {kb_name}】\n{context_text}")

    merged = "\n\n---\n\n".join(contexts) if contexts else ""
    return {"code": 0, "data": {"context": merged, "source_count": len(contexts)}}


# ---------- 辅助函数 ----------

def _increment_doc_count(kb_id: str):
    """增加知识库文档计数"""
    meta = _load_kb_meta()
    for kb in meta:
        if kb["id"] == kb_id:
            kb["doc_count"] = kb.get("doc_count", 0) + 1
            break
    _save_kb_meta(meta)
