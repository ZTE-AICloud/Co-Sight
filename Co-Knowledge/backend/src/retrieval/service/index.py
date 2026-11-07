"""Public retrieval-index lifecycle used by the knowledge-base domain."""
from __future__ import annotations

from retrieval.repository import es_store, vector_write_store
from retrieval.repository.kbase_lookup import get_kbase_row


def create_index(kbase_id: str, keyword_analyzer: str | None = None) -> None:
    es_store.create_index(kbase_id, keyword_analyzer=keyword_analyzer)


def delete_index(kbase_id: str) -> None:
    es_store.delete_index(kbase_id)


def delete_documents_by_file_id(kbase_id: str, file_id: str) -> None:
    """Delete one document's ES rows; a missing index is a no-op."""
    row = get_kbase_row(kbase_id)
    index = es_store.index_name(row.get('table_name') if row else None,
                                row.get('id') if row else 0, kbase_id)
    client = es_store._client()
    if not client.indices.exists(index):
        return
    client.delete_by_query(index, {'query': {'term': {'file_id': file_id}}})


def delete_documents_by_query(kbase_id: str, field_name: str, values: list) -> None:
    vector_write_store.delete_es_documents_by_query(kbase_id, field_name, values)
