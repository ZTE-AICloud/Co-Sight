#!/usr/bin/env python3
"""集合构建器骨架 — 预设场景创建向量集合。

接口形状与职责边界固定, 实现按目标向量库客户端适配:
- 连接: 用户凭据经环境变量注入（VECTOR_DB_URI / VECTOR_DB_TOKEN）
- 创建: 预设场景（text_search / rag）→ 字段 + 索引 + 相似度配置
- 向量: Embedding 服务密钥由用户提供（兼容 OpenAI 接口）
"""
import os
from typing import Any, Dict, List, Optional

SCENES = {
    "text_search": {
        "fields": ["id", "content", "vector"],
        "metric": "COSINE",
        "dynamic": True,
    },
    "rag": {
        "fields": ["id", "text", "metadata", "vector"],
        "metric": "COSINE",
        "dynamic": True,
    },
}

EMBEDDING_DIMS = {
    "openai-3-large": 3072,
    "openai-3-small": 1536,
    "openai-ada-002": 1536,
    "bge-m3": 1024,
    "bge-large": 1024,
    "e5-large": 1024,
}


class VectorCollectionBuilder:
    """向量集合构建器（骨架: 连接 → 预设创建 → 向量生成接入位）。"""

    def __init__(self, uri: Optional[str] = None, token: Optional[str] = None):
        # 凭据契约位: 用户自备; 缺省回退本地服务地址
        self.uri = uri or os.environ.get("VECTOR_DB_URI", "http://localhost:19530")
        self.token = token or os.environ.get("VECTOR_DB_TOKEN") or None
        self._embedder = None

    # ── 预设场景创建 ──────────────────────────────────────────────
    def create_from_preset(self, collection_name: str, scene: str) -> Dict[str, Any]:
        """按预设场景创建集合。scene ∈ SCENES 键。"""
        if scene not in SCENES:
            return {"status": "error", "error": f"未知场景: {scene}, 可选: {list(SCENES)}"}
        spec = SCENES[scene]
        # 实现位: 调用向量库客户端建集合（字段/索引/相似度按 spec）
        # client = MilvusClient(uri=self.uri, token=self.token)
        # ... 建集合 + 建索引 ...
        return {
            "status": "success",
            "scene": scene,
            "fields": spec["fields"],
            "metric": spec["metric"],
            "code": f"# 集合 {collection_name} 创建代码（按场景 {scene} 渲染）",
        }

    def create_from_intent(self, collection_name: str, **intent) -> Dict[str, Any]:
        """意图解析结果接入位: intent 由意图解析器产出（scene/模型/字段）。"""
        scene = intent.get("scene", "text_search")
        return self.create_from_preset(collection_name, scene=scene)

    # ── Embedding 接入位（用户密钥）───────────────────────────────
    def init_embedding(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("Embedding 密钥缺失: 用户提供 OPENAI_API_KEY 或显式传参")
        # 实现位: 初始化 OpenAI 兼容客户端（base_url 指向用户兼容服务时必填）
        self._embedder = {"api_key": key, "base_url": base_url}

    def embed_text(self, texts: Any) -> List[List[float]]:
        if self._embedder is None:
            raise RuntimeError("先调用 init_embedding()")
        single = isinstance(texts, str)
        batch = [texts] if single else list(texts)
        # 实现位: 批量调用 embedding 接口返回向量
        return [[0.0]] * len(batch)  # 骨架占位 — 实现时替换为真实调用

    # ── 批量写入接入位 ────────────────────────────────────────────
    def embed_and_insert(self, collection_name: str, texts: List[str]) -> Dict[str, Any]:
        vectors = self.embed_text(texts)
        # 实现位: 批量插入 + 建索引, 返回写入条数
        return {"status": "success", "collection": collection_name, "inserted": len(vectors)}

    # ── 查询辅助 ────────────────────────────────────────────────
    def list_presets(self) -> List[Dict[str, str]]:
        return [{"scene": k, "fields": ",".join(v["fields"])} for k, v in SCENES.items()]

    def list_embedding_models(self) -> List[Dict[str, Any]]:
        return [{"model": k, "dim": v} for k, v in EMBEDDING_DIMS.items()]
