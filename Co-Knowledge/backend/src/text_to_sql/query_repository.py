"""Text2SQL 查询运行、历史、常用查询、反馈与用户草稿的持久化。

查询运行表 ``t2s_query_run`` 保存的是**历史解释快照**：问题、绑定的版本、
检索/校验/执行结果都不可变；结果预览可被保留期清理，但不能被重新计算。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from text_to_sql import vector_store
from text_to_sql.db import row as _row, transaction as _transaction

_TS = "'YYYY-MM-DD HH24:MI:SS'"


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# 数据源 + 活动版本
# ---------------------------------------------------------------------------
def get_active_context(datasource_id: str) -> Optional[dict[str, Any]]:
    """返回数据源行 + 活动版本快照（没有活动版本时 version 字段为 NULL）。"""
    with _transaction() as cursor:
        cursor.execute(
            """
            SELECT d.*,
                   v.id AS active_version_id_joined,
                   v.revision AS active_version_revision,
                   v.status AS active_version_status,
                   v.snapshot,
                   v.embedding_model,
                   v.embedding_dimensions,
                   v.ready_at AS active_ready_at
              FROM text2sql.t2s_datasource d
              LEFT JOIN text2sql.t2s_config_version v ON v.id = d.active_version_id
             WHERE d.id = %s AND d.deleted_at IS NULL
            """, (datasource_id,))
        return _row(cursor.fetchone())


def list_versions(datasource_id: str) -> list[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(
            f"""
            SELECT id, revision, status,
                   to_char(created_at, {_TS}) AS created_at,
                   to_char(ready_at, {_TS}) AS ready_at,
                   expected_knowledge_count,
                   (SELECT count(*) FROM text2sql.t2s_knowledge k
                     WHERE k.version_id = v.id AND k.index_status = 'INDEXED') AS indexed_count,
                   (SELECT count(*) FROM text2sql.t2s_knowledge k
                     WHERE k.version_id = v.id AND k.index_status = 'FAILED') AS failed_count
              FROM text2sql.t2s_config_version v
             WHERE datasource_id = %s
             ORDER BY revision DESC
            """, (datasource_id,))
        return [dict(item) for item in cursor.fetchall()]


def list_publications(datasource_id: str) -> list[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(
            f"""
            SELECT p.id, p.previous_version_id, p.version_id, p.actor_id,
                   to_char(p.created_at, {_TS}) AS created_at,
                   v.revision
              FROM text2sql.t2s_publication p
              LEFT JOIN text2sql.t2s_config_version v ON v.id = p.version_id
             WHERE p.datasource_id = %s
             ORDER BY p.created_at DESC
            """, (datasource_id,))
        return [dict(item) for item in cursor.fetchall()]


# ---------------------------------------------------------------------------
# 向量检索
# ---------------------------------------------------------------------------
def search_knowledge(version_id: str, embedding: list[float],
                     limit: int = 24,
                     datasource_id: str = '') -> list[dict[str, Any]]:
    """版本隔离的余弦检索；``datasource_id`` 决定查哪张定长向量表。"""
    if not datasource_id:
        raise ValueError('search_knowledge 需要 datasource_id：向量表按数据源分表')
    with _transaction() as cursor:
        return vector_store.search(cursor, datasource_id, version_id,
                                   embedding, limit)


def list_knowledge_text(version_id: str) -> list[dict[str, Any]]:
    """版本内的知识正文：词法检索（BM25）在进程内算，需要一次拿全。

    版本不可变，调用方可以按 ``version_id`` 缓存分词结果。
    """
    with _transaction() as cursor:
        cursor.execute(
            """
            SELECT k.id, k.object_type, k.object_key, k.title, k.content,
                   k.metadata, k.table_id, k.column_id, k.value_id,
                   k.relation_id, k.metric_id
              FROM text2sql.t2s_knowledge k
             WHERE k.version_id = %s
             ORDER BY k.id
            """, (version_id,))
        return [dict(item) for item in cursor.fetchall()]


# ---------------------------------------------------------------------------
# 查询运行
# ---------------------------------------------------------------------------
def create_run(*, datasource_id: str, actor_id: str, question: str,
               version_id: str, parameters: dict[str, Any],
               date_policy: str, resolved_time_range: dict[str, Any],
               source_snapshot: dict[str, Any],
               parent_run_id: Optional[str]) -> dict[str, Any]:
    with _transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO text2sql.t2s_query_run
                (datasource_id, version_id, parent_run_id, actor_id, question,
                 status, request_parameters, date_policy, resolved_time_range,
                 source_snapshot)
            VALUES (%s, %s, %s, %s, %s, 'PENDING', %s::jsonb, %s, %s::jsonb, %s::jsonb)
            RETURNING id, request_id
            """, (datasource_id, version_id, parent_run_id, actor_id, question,
                  _json(parameters), date_policy, _json(resolved_time_range),
                  _json(source_snapshot)))
        return dict(cursor.fetchone())


def mark_running(run_id: str) -> None:
    with _transaction() as cursor:
        cursor.execute(
            "UPDATE text2sql.t2s_query_run "
            "SET status = 'RUNNING', started_at = now(), updated_at = now() "
            "WHERE id = %s AND status = 'PENDING'", (run_id,))


def finish_success(run_id: str, *, generated_sql: str, final_sql: str,
                   retrieval: dict[str, Any], explanation: dict[str, Any],
                   validation: dict[str, Any], explain: Optional[dict[str, Any]],
                   result: dict[str, Any], row_count: int, truncated: bool,
                   stages: list[dict[str, Any]], timing: dict[str, Any],
                   usage: Optional[dict[str, Any]],
                   context: Optional[dict[str, Any]] = None,
                   retention_days: int = 30) -> None:
    with _transaction() as cursor:
        cursor.execute(
            """
            UPDATE text2sql.t2s_query_run
               SET status = 'SUCCEEDED', generated_sql = %s, final_sql = %s,
                   retrieval_snapshot = %s::jsonb,
                   explanation_snapshot = %s::jsonb,
                   validation_snapshot = %s::jsonb,
                   explain_snapshot = %s::jsonb,
                   result_snapshot = %s::jsonb,
                   result_row_count = %s, result_truncated = %s,
                   stages = %s::jsonb, timing = %s::jsonb, usage = %s::jsonb,
                   context_snapshot = COALESCE(%s::jsonb, context_snapshot),
                   result_expires_at = now() + make_interval(days => %s),
                   finished_at = now(), updated_at = now()
             WHERE id = %s AND status = 'RUNNING'
            """, (generated_sql, final_sql, _json(retrieval), _json(explanation),
                  _json(validation), _json(explain) if explain is not None else None,
                  _json(result), row_count, bool(truncated), _json(stages),
                  _json(timing), _json(usage or {}),
                  _json(context) if context is not None else None,
                  int(retention_days), run_id))


def purge_expired_results() -> int:
    """清掉过期结果预览，保留运行记录本身（SQL/校验/耗时仍可查）。"""
    with _transaction() as cursor:
        cursor.execute(
            """
            UPDATE text2sql.t2s_query_run
               SET result_snapshot = NULL, updated_at = now()
             WHERE result_snapshot IS NOT NULL
               AND result_expires_at IS NOT NULL
               AND result_expires_at < now()
            """)
        return cursor.rowcount


def finish_failure(run_id: str, *, error_code: str, error_message: str,
                   error_stage: str, stages: list[dict[str, Any]],
                   timing: dict[str, Any],
                   generated_sql: Optional[str] = None) -> None:
    with _transaction() as cursor:
        cursor.execute(
            """
            UPDATE text2sql.t2s_query_run
               SET status = 'FAILED', error_code = %s, error_message = %s,
                   error_stage = %s, stages = %s::jsonb, timing = %s::jsonb,
                   generated_sql = COALESCE(%s, generated_sql),
                   finished_at = now(), updated_at = now()
             WHERE id = %s AND status = 'RUNNING'
            """, (error_code, (error_message or '查询失败')[:2000], error_stage,
                  _json(stages), _json(timing), generated_sql, run_id))


def get_run(run_id: str, actor_id: str) -> Optional[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(
            f"""
            SELECT r.*, to_char(r.created_at, {_TS}) AS created_at_text,
                   d.name AS datasource_name
              FROM text2sql.t2s_query_run r
              LEFT JOIN text2sql.t2s_datasource d ON d.id = r.datasource_id
             WHERE r.id = %s AND r.actor_id = %s
            """, (run_id, actor_id))
        return _row(cursor.fetchone())


def list_runs(actor_id: str, *, datasource_id: Optional[str] = None,
              status: Optional[str] = None, page: int = 1,
              size: int = 20) -> dict[str, Any]:
    where = ['r.actor_id = %s']
    params: list[Any] = [actor_id]
    if datasource_id:
        where.append('r.datasource_id = %s')
        params.append(datasource_id)
    if status:
        where.append('r.status = %s')
        params.append(status.upper())
    clause = ' AND '.join(where)
    offset = (page - 1) * size
    with _transaction() as cursor:
        cursor.execute(
            f'SELECT count(*) AS total FROM text2sql.t2s_query_run r WHERE {clause}',
            params)
        total = int(cursor.fetchone()['total'])
        cursor.execute(
            f"""
            SELECT r.*, to_char(r.created_at, {_TS}) AS created_at_text,
                   d.name AS datasource_name
              FROM text2sql.t2s_query_run r
              LEFT JOIN text2sql.t2s_datasource d ON d.id = r.datasource_id
             WHERE {clause}
             ORDER BY r.created_at DESC
             LIMIT %s OFFSET %s
            """, params + [int(size), int(offset)])
        items = [dict(item) for item in cursor.fetchall()]
    return {'items': items, 'total': total, 'page': page, 'pageSize': size}


def delete_run(run_id: str, actor_id: str) -> bool:
    with _transaction() as cursor:
        cursor.execute(
            'DELETE FROM text2sql.t2s_query_run WHERE id = %s AND actor_id = %s',
            (run_id, actor_id))
        return cursor.rowcount > 0


def clear_runs(actor_id: str, datasource_id: Optional[str] = None) -> int:
    with _transaction() as cursor:
        if datasource_id:
            cursor.execute(
                'DELETE FROM text2sql.t2s_query_run '
                'WHERE actor_id = %s AND datasource_id = %s',
                (actor_id, datasource_id))
        else:
            cursor.execute(
                'DELETE FROM text2sql.t2s_query_run WHERE actor_id = %s',
                (actor_id,))
        return cursor.rowcount


# ---------------------------------------------------------------------------
# 反馈
# ---------------------------------------------------------------------------
def create_feedback(*, run_id: str, datasource_id: str, actor_id: str,
                    category: str, helpful: Optional[bool],
                    notes: str) -> dict[str, Any]:
    with _transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO text2sql.t2s_feedback
                (run_id, datasource_id, actor_id, category, helpful, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, actor_id, category) DO UPDATE
               SET helpful = EXCLUDED.helpful,
                   notes = EXCLUDED.notes,
                   status = 'OPEN',
                   updated_at = now()
            RETURNING id, category, helpful, notes, status,
                      to_char(created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at
            """, (run_id, datasource_id, actor_id, category, helpful, notes))
        return dict(cursor.fetchone())


def list_feedback(datasource_id: str) -> list[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(
            """
            SELECT id, run_id, category, helpful, notes, status,
                   to_char(created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at
              FROM text2sql.t2s_feedback
             WHERE datasource_id = %s
             ORDER BY created_at DESC
            """, (datasource_id,))
        return [dict(item) for item in cursor.fetchall()]


# ---------------------------------------------------------------------------
# 常用查询
# ---------------------------------------------------------------------------
def list_favorites(actor_id: str) -> list[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(
            f"""
            SELECT id, datasource_id, name, question, parameters, date_policy,
                   fixed_time_range, notes, verified_version_id, verified_by,
                   to_char(verified_at, {_TS}) AS verified_at,
                   to_char(created_at, {_TS}) AS created_at,
                   to_char(updated_at, {_TS}) AS updated_at
              FROM text2sql.t2s_favorite
             WHERE actor_id = %s
             ORDER BY updated_at DESC
            """, (actor_id,))
        return [dict(item) for item in cursor.fetchall()]


def create_favorite(*, actor_id: str, datasource_id: Optional[str], name: str,
                    question: str, parameters: dict[str, Any], date_policy: str,
                    fixed_time_range: Optional[dict[str, Any]],
                    notes: str) -> dict[str, Any]:
    with _transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO text2sql.t2s_favorite
                (actor_id, datasource_id, name, question, parameters,
                 date_policy, fixed_time_range, notes)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s)
            RETURNING id
            """, (actor_id, datasource_id, name, question, _json(parameters),
                  date_policy,
                  _json(fixed_time_range) if fixed_time_range is not None else None,
                  notes))
        return dict(cursor.fetchone())


def update_favorite(favorite_id: str, actor_id: str,
                    fields: dict[str, Any]) -> bool:
    if not fields:
        return False
    sets = []
    params: list[Any] = []
    mapping = {
        'datasource_id': 'datasource_id', 'name': 'name', 'question': 'question',
        'parameters': 'parameters', 'date_policy': 'date_policy',
        'fixed_time_range': 'fixed_time_range', 'notes': 'notes',
    }
    for key, column in mapping.items():
        if key not in fields:
            continue
        value = fields[key]
        if key in ('parameters', 'fixed_time_range'):
            sets.append(f'{column} = %s::jsonb')
            params.append(_json(value) if value is not None else None)
        else:
            sets.append(f'{column} = %s')
            params.append(value)
    if not sets:
        return False
    sets.append('updated_at = now()')
    params.extend([favorite_id, actor_id])
    with _transaction() as cursor:
        cursor.execute(
            f"UPDATE text2sql.t2s_favorite SET {', '.join(sets)} "
            'WHERE id = %s AND actor_id = %s', params)
        return cursor.rowcount > 0


def delete_favorite(favorite_id: str, actor_id: str) -> bool:
    with _transaction() as cursor:
        cursor.execute(
            'DELETE FROM text2sql.t2s_favorite WHERE id = %s AND actor_id = %s',
            (favorite_id, actor_id))
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# 用户工作台草稿
# ---------------------------------------------------------------------------
def get_workspace(actor_id: str) -> Optional[dict[str, Any]]:
    with _transaction() as cursor:
        cursor.execute(
            f"""
            SELECT actor_id, datasource_id, question_draft, sql_draft,
                   preferences, to_char(updated_at, {_TS}) AS updated_at
              FROM text2sql.t2s_workspace WHERE actor_id = %s
            """, (actor_id,))
        return _row(cursor.fetchone())


def save_workspace(actor_id: str, *, datasource_id: Optional[str],
                   question_draft: str, sql_draft: str,
                   preferences: dict[str, Any]) -> None:
    with _transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO text2sql.t2s_workspace
                (actor_id, datasource_id, question_draft, sql_draft, preferences)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (actor_id) DO UPDATE
               SET datasource_id = EXCLUDED.datasource_id,
                   question_draft = EXCLUDED.question_draft,
                   sql_draft = EXCLUDED.sql_draft,
                   preferences = EXCLUDED.preferences,
                   updated_at = now()
            """, (actor_id, datasource_id, question_draft, sql_draft,
                  _json(preferences)))
