"""Graph lifecycle operations owned by the graph domain.

Knowledge-base creation/deletion needs to create or drop graph storage, and
document deletion needs to purge graph chunks.  Those callers must not reach
into ``graph.repository`` directly, so this module is the public seam.
"""
from __future__ import annotations

from graph.constants import GRAPH_TABLE_PREFIX
from graph.repository import graph_delete_store, graph_index_store, graph_pg
from infrastructure.logging.logutil import log


def ensure_database(table_name: str) -> None:
    """Create the graph database when the KB table is a ``graph_`` table."""
    if table_name.startswith(GRAPH_TABLE_PREFIX):
        graph_pg.ensure_database_exists(graph_pg.new_client(table_name), table_name)


def count_graph_entities_and_edges(kbase_id: str) -> dict[str, int] | None:
    """Exact entity/edge totals for a graph knowledge base.

    Returns ``None`` when the graph tables do not exist yet.  A failed count
    must never break the KB detail page, so storage errors are logged and
    reported as ``None`` as well.
    """
    db_name = graph_pg.graph_db_name_for_query(str(kbase_id))
    try:
        return graph_pg.count_entities_and_edges(db_name)
    except Exception:                                              # noqa: BLE001
        log.warning('failed to count graph rows for %s', kbase_id, exc_info=True)
        return None


def delete_import_and_extract_tasks(kbase_id: str) -> None:
    graph_delete_store.delete_import_tasks(kbase_id)
    graph_delete_store.delete_extract_tasks(kbase_id)


def drop_chunk_and_vector_tables(kbase_id: str) -> None:
    graph_delete_store.drop_table_if_exists(graph_delete_store.chunk_table(kbase_id))
    graph_delete_store.drop_table_if_exists(graph_delete_store.vector_table(kbase_id))


def delete_graph_database(kbase_id: str) -> None:
    """Drop the graph database, then remove its registry row.

    ``missing_ok=True`` treats a missing database as already deleted.  A drop
    failure propagates so the caller can retry the whole KB deletion.
    """
    db_name = graph_delete_store.graph_db_name(kbase_id)
    client = graph_pg.new_client(db_name)
    graph_pg.drop_database(client, db_name, missing_ok=True)
    graph_delete_store.delete_knowledge_graph_info(db_name)


def delete_chunks_by_sources(table_name: str, sources: list[str]) -> None:
    graph_index_store.delete_chunks_by_sources(table_name, sources)


def chunk_ids_for_sources(table_name: str, file_names: list[str]) -> list:
    return graph_index_store.chunk_ids_for_sources(table_name, file_names)


def delete_source_graph_data(table_name: str, kbase_id: str, chunk_ids: list) -> None:
    graph_index_store.delete_source_graph_data(table_name, kbase_id, chunk_ids)
