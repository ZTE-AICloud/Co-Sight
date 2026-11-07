"""Public vector/keyword search surface used by the Agent domain."""
from __future__ import annotations

from retrieval.repository import es_store, vector_store


def index_name_for_row(row: dict) -> str:
    return es_store.index_name(row.get('table_name'), row.get('id'),
                               row.get('kbase_id') or '')


def index_exists(name: str) -> bool:
    return es_store.index_exists_by_name(name)


def search_index(name: str, question: str, top_k: int) -> list[dict]:
    return es_store.search_index(name, question, top_k)


def table_exists(table_name: str) -> bool:
    return vector_store.table_exists(table_name)


def query_by_embedding_with_chunk(table_name: str, chunk_table_name: str,
                                  embedding_literal: str, score_threshold: float,
                                  top_k: int) -> list[dict]:
    return vector_store.query_by_embedding_with_chunk(
        table_name, chunk_table_name, embedding_literal, score_threshold, top_k)
