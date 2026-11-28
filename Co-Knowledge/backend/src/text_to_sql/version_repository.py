"""配置版本：冻结快照、知识构建、向量索引与发布。

事务边界刻意分成三段（见 :func:`build_version`）：

1. 事务 A：锁定版本与 datasource，登记任务并置 BUILDING；
2. 事务外：调用 embedding 服务（HTTP，不能占着数据库事务）；
3. 事务 B：写向量、更新知识状态、完成任务并把版本置 READY/FAILED。
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

import psycopg2
import psycopg2.extras

from text_to_sql import knowledge, vector_store
from text_to_sql.db import row as _row, transaction as _transaction
from text_to_sql.errors import (Text2SqlConflict, Text2SqlNotFound,
                                Text2SqlValidationError)

_TS = "'YYYY-MM-DD HH24:MI:SS'"


# ---------------------------------------------------------------------------
# 读取可发布的工作集
# ---------------------------------------------------------------------------
def _load_source(cursor, datasource_id: str, *, for_update: bool = True) -> dict | None:
    clause = ' FOR UPDATE' if for_update else ''
    cursor.execute(
        'SELECT * FROM text2sql.t2s_datasource '
        'WHERE id = %s AND deleted_at IS NULL' + clause, (datasource_id,))
    return _row(cursor.fetchone())


def _load_tables(cursor, datasource_id: str) -> list[dict]:
    cursor.execute(
        """
        SELECT id, schema_name, table_name, table_type, db_comment,
               business_name, business_description, business_aliases, enabled
          FROM text2sql.t2s_table
         WHERE datasource_id = %s AND enabled = TRUE AND missing_since IS NULL
         ORDER BY schema_name, table_name
        """, (datasource_id,))
    tables = [dict(item) for item in cursor.fetchall()]
    if not tables:
        return []
    cursor.execute(
        """
        SELECT id, table_id, column_name, data_type, ordinal_position,
               is_nullable, is_primary_key, is_unique, db_comment,
               business_name, business_description, business_aliases,
               semantic_type, enabled
          FROM text2sql.t2s_column
         WHERE datasource_id = %s AND missing_since IS NULL
         ORDER BY table_id, ordinal_position
        """, (datasource_id,))
    grouped: dict[str, list[dict]] = {}
    for column in cursor.fetchall():
        grouped.setdefault(str(column['table_id']), []).append(dict(column))
    for table in tables:
        table['columns'] = grouped.get(str(table['id']), [])
    return tables


def _load_relations(cursor, datasource_id: str) -> list[dict]:
    cursor.execute(
        """
        SELECT id, source_table_id, target_table_id, relation_name,
               relation_type, cardinality, description, enabled
          FROM text2sql.t2s_relation
         WHERE datasource_id = %s AND enabled = TRUE
         ORDER BY relation_name
        """, (datasource_id,))
    relations = [dict(item) for item in cursor.fetchall()]
    if not relations:
        return []
    cursor.execute(
        """
        SELECT relation_id, ordinal_position, source_column_id, target_column_id
          FROM text2sql.t2s_relation_column
         WHERE datasource_id = %s
         ORDER BY relation_id, ordinal_position
        """, (datasource_id,))
    pairs: dict[str, list[dict]] = {}
    for pair in cursor.fetchall():
        pairs.setdefault(str(pair['relation_id']), []).append(dict(pair))
    for relation in relations:
        relation['column_pairs'] = pairs.get(str(relation['id']), [])
    return relations


def _load_values(cursor, datasource_id: str) -> list[dict]:
    cursor.execute(
        """
        SELECT id, column_id, raw_value, value_type, business_name, aliases,
               description, source_type, enabled
          FROM text2sql.t2s_value
         WHERE datasource_id = %s AND enabled = TRUE
         ORDER BY column_id, raw_value
        """, (datasource_id,))
    return [dict(item) for item in cursor.fetchall()]


def _load_metrics(cursor, datasource_id: str) -> list[dict]:
    cursor.execute(
        """
        SELECT id, base_table_id, metric_key, business_name,
               business_description, aliases, expression_sql, filter_definition,
               time_column_id, unit, business_timezone, aggregation_behavior,
               attribution_description, status
          FROM text2sql.t2s_metric
         WHERE datasource_id = %s
         ORDER BY metric_key
        """, (datasource_id,))
    metrics = [dict(item) for item in cursor.fetchall()]
    if not metrics:
        return []
    cursor.execute(
        """
        SELECT metric_id, column_id, dependency_role
          FROM text2sql.t2s_metric_column WHERE datasource_id = %s
        """, (datasource_id,))
    columns: dict[str, list[dict]] = {}
    for item in cursor.fetchall():
        columns.setdefault(str(item['metric_id']), []).append(dict(item))
    cursor.execute(
        'SELECT metric_id, relation_id FROM text2sql.t2s_metric_relation '
        'WHERE datasource_id = %s', (datasource_id,))
    relations: dict[str, list[str]] = {}
    for item in cursor.fetchall():
        relations.setdefault(str(item['metric_id']), []).append(str(item['relation_id']))
    for metric in metrics:
        metric['column_dependencies'] = columns.get(str(metric['id']), [])
        metric['relation_dependencies'] = relations.get(str(metric['id']), [])
    return metrics


# ---------------------------------------------------------------------------
# 创建版本
# ---------------------------------------------------------------------------
def create_version(datasource_id: str, embedding_model: str,
                   embedding_dimensions: int, actor: str) -> dict[str, Any]:
    with _transaction() as cursor:
        source = _load_source(cursor, datasource_id)
        if source is None:
            raise Text2SqlNotFound('数据源不存在或已删除')
        if not source['enabled']:
            raise Text2SqlConflict('数据源已停用')
        tables = _load_tables(cursor, datasource_id)
        if not tables:
            raise Text2SqlValidationError('请先选择并启用至少一张数据表')
        relations = _load_relations(cursor, datasource_id)
        values = _load_values(cursor, datasource_id)
        metrics = _load_metrics(cursor, datasource_id)
        snapshot = knowledge.build_snapshot(
            datasource=source, tables=tables, relations=relations,
            values=values, metrics=metrics, embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions)
        drafts = knowledge.build_knowledge(snapshot)
        if not drafts:
            raise Text2SqlValidationError('当前配置没有可构建的知识对象')
        revision = source['config_revision']

        cursor.execute(
            'SELECT id, status FROM text2sql.t2s_config_version '
            'WHERE datasource_id = %s AND revision = %s',
            (datasource_id, revision))
        existing = cursor.fetchone()
        if existing is not None:
            return {'version_id': str(existing['id']), 'status': existing['status'],
                    'revision': revision, 'created': False}

        snapshot_hash = knowledge.content_hash(snapshot)
        cursor.execute(
            """
            INSERT INTO text2sql.t2s_config_version
                (datasource_id, revision, status, snapshot, content_hash,
                 expected_knowledge_count, embedding_model, embedding_dimensions,
                 created_by)
            VALUES (%s, %s, 'DRAFT', %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (datasource_id, revision, psycopg2.extras.Json(snapshot),
             snapshot_hash, len(drafts), embedding_model,
             embedding_dimensions, actor or 'system'))
        version_id = str(cursor.fetchone()['id'])

        namespace = knowledge.knowledge_vector_namespace(datasource_id, revision)
        for draft in drafts:
            link = {draft.link_field: draft.object_key}
            cursor.execute(
                """
                INSERT INTO text2sql.t2s_knowledge
                    (datasource_id, version_id, object_type, object_key,
                     table_id, column_id, value_id, relation_id, metric_id,
                     title, content, metadata, content_hash, vector_namespace,
                     index_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
                """,
                (datasource_id, version_id, draft.object_type, draft.object_key,
                 link.get('table_id'), link.get('column_id'), link.get('value_id'),
                 link.get('relation_id'), link.get('metric_id'), draft.title,
                 draft.content, psycopg2.extras.Json(draft.metadata),
                 knowledge.content_hash(draft.content), namespace))

        cursor.execute(
            """
            INSERT INTO text2sql.t2s_index_job
                (datasource_id, version_id, job_type, status, idempotency_key,
                 total_count)
            VALUES (%s, %s, 'KNOWLEDGE_BUILD', 'PENDING', %s, %s)
            RETURNING id
            """,
            (datasource_id, version_id, f'kb:{version_id}:{uuid4().hex}', len(drafts)))
        build_job_id = cursor.fetchone()['id']
        cursor.execute(
            "UPDATE text2sql.t2s_config_version SET status = 'BUILDING' WHERE id = %s",
            (version_id,))
        # 知识清单在同一个事务里生成完毕：任务如实经历 PENDING→RUNNING→COMPLETED，
        # 不留下 PENDING 行阻塞后续 EMBEDDING 任务。
        cursor.execute(
            "UPDATE text2sql.t2s_index_job SET status = 'RUNNING', started_at = now(), "
            "processed_count = %s, heartbeat_at = now() WHERE id = %s",
            (len(drafts), build_job_id))
        cursor.execute(
            "UPDATE text2sql.t2s_index_job SET status = 'COMPLETED', "
            "processed_count = %s, failed_count = 0, finished_at = now() WHERE id = %s",
            (len(drafts), build_job_id))
    return {'version_id': version_id, 'status': 'BUILDING', 'revision': revision,
            'created': True}


# ---------------------------------------------------------------------------
# 构建 / 索引
# ---------------------------------------------------------------------------
def prepare_build(datasource_id: str, version_id: str,
                  worker_id: str) -> dict[str, Any] | None:
    """登记一次构建尝试，返回待索引的知识（事务 A）。"""
    with _transaction() as cursor:
        cursor.execute(
            'SELECT * FROM text2sql.t2s_config_version '
            'WHERE id = %s AND datasource_id = %s FOR UPDATE',
            (version_id, datasource_id))
        version = cursor.fetchone()
        if version is None:
            return None
        version = dict(version)
        if version['status'] == 'READY':
            return {'status': 'READY', 'pending': [], 'total': 0,
                    'embedding_model': version['embedding_model'],
                    'embedding_dimensions': version['embedding_dimensions']}
        if version['status'] == 'CANCELLED':
            raise Text2SqlConflict('已取消的版本不能构建')
        if version['status'] in ('DRAFT', 'FAILED'):
            cursor.execute(
                "UPDATE text2sql.t2s_config_version SET status = 'BUILDING' WHERE id = %s",
                (version_id,))
        cursor.execute(
            "SELECT id FROM text2sql.t2s_index_job WHERE version_id = %s "
            "AND status IN ('PENDING', 'RUNNING')", (version_id,))
        if cursor.fetchone() is not None:
            raise Text2SqlConflict('该版本已有进行中的索引任务')

        cursor.execute(
            'SELECT id, content, index_status FROM text2sql.t2s_knowledge '
            'WHERE version_id = %s ORDER BY id', (version_id,))
        rows = [dict(item) for item in cursor.fetchall()]
        pending = [{'id': str(item['id']), 'content': item['content']}
                   for item in rows if item['index_status'] != 'INDEXED']
        total = len(rows)
        cursor.execute(
            """
            INSERT INTO text2sql.t2s_index_job
                (datasource_id, version_id, job_type, status, idempotency_key,
                 total_count, worker_id)
            VALUES (%s, %s, 'EMBEDDING', 'PENDING', %s, %s, %s)
            RETURNING id
            """,
            (datasource_id, version_id, f'emb:{version_id}:{uuid4().hex}', total,
             worker_id))
        job_id = str(cursor.fetchone()['id'])
        cursor.execute(
            "UPDATE text2sql.t2s_index_job SET status = 'RUNNING', "
            "started_at = now(), heartbeat_at = now() WHERE id = %s", (job_id,))
    return {
        'status': 'BUILDING', 'job_id': job_id, 'pending': pending, 'total': total,
        'embedding_model': version['embedding_model'],
        'embedding_dimensions': version['embedding_dimensions'],
    }


def fail_build(datasource_id: str, version_id: str, job_id: str,
               message: str) -> None:
    """构建过程抛出意外异常时收口：任务置 FAILED、版本置 FAILED。

    没有这一步，异常会让 ``t2s_index_job`` 永远停在 RUNNING、版本停在
    BUILDING——既看不出失败，也重试不了（prepare_build 会拒绝进行中的任务）。
    """
    reason = (message or '构建失败（未提供原因）')[:1000]
    with _transaction() as cursor:
        cursor.execute(
            "UPDATE text2sql.t2s_index_job "
            "   SET status = 'FAILED', error_message = %s, finished_at = now() "
            " WHERE id = %s AND status IN ('PENDING', 'RUNNING')",
            (reason, job_id))
        cursor.execute(
            "UPDATE text2sql.t2s_config_version SET status = 'FAILED' "
            " WHERE id = %s AND datasource_id = %s AND status IN ('DRAFT', 'BUILDING')",
            (version_id, datasource_id))


def finish_build(datasource_id: str, version_id: str, job_id: str,
                 embeddings: dict[str, list[float]],
                 errors: dict[str, str]) -> dict[str, Any] | None:
    """写向量并收口版本状态（事务 B）。"""
    processed = 0
    failed = 0
    with _transaction() as cursor:
        cursor.execute(
            'SELECT status, embedding_dimensions, expected_knowledge_count '
            'FROM text2sql.t2s_config_version '
            'WHERE id = %s AND datasource_id = %s FOR UPDATE',
            (version_id, datasource_id))
        version = cursor.fetchone()
        if version is None:
            return None
        expected_dimensions = version['embedding_dimensions']
        # 每个数据源一张定长向量表（首次构建时按维度建，含 HNSW）。
        vector_store.ensure_table(cursor, datasource_id, expected_dimensions)
        for knowledge_id, embedding in embeddings.items():
            if len(embedding) != expected_dimensions:
                errors[knowledge_id] = (
                    f'向量维度 {len(embedding)} 与版本声明的 {expected_dimensions} 不一致')
                continue
            cursor.execute(
                'SELECT content FROM text2sql.t2s_knowledge WHERE id = %s',
                (knowledge_id,))
            content = cursor.fetchone()['content']
            vector_store.upsert(cursor, datasource_id, knowledge_id, version_id,
                                content, embedding)
            cursor.execute(
                """
                UPDATE text2sql.t2s_knowledge
                   SET index_status = 'INDEXED', vector_document_id = %s,
                       indexed_at = now(), index_error = NULL
                 WHERE id = %s AND version_id = %s
                """, (knowledge_id, knowledge_id, version_id))
            _upsert_binding(cursor, knowledge_id, datasource_id, version_id,
                            'VECTOR', 'INDEXED', external_id=knowledge_id)
            processed += 1
        for knowledge_id, message in errors.items():
            cursor.execute(
                """
                UPDATE text2sql.t2s_knowledge
                   SET index_status = 'FAILED', vector_document_id = NULL,
                       indexed_at = NULL, index_error = %s
                 WHERE id = %s AND version_id = %s
                """, (message[:2000], knowledge_id, version_id))
            _upsert_binding(cursor, knowledge_id, datasource_id, version_id,
                            'VECTOR', 'FAILED', error=message)
            failed += 1

        cursor.execute(
            """
            SELECT count(*) FILTER (WHERE index_status = 'INDEXED') AS ok,
                   count(*) FILTER (WHERE index_status = 'FAILED') AS bad,
                   count(*) FILTER (WHERE index_status = 'PENDING') AS pending
              FROM text2sql.t2s_knowledge WHERE version_id = %s
            """, (version_id,))
        counts = dict(cursor.fetchone())
        expected = version['expected_knowledge_count']
        ok = int(counts['ok'] or 0)
        bad = int(counts['bad'] or 0)
        pending = int(counts['pending'] or 0)

        # READY 的前置条件必须在把任务置为终态之前就满足：guard_config_version 会
        # 拒绝「仍有 PENDING/RUNNING 任务」的 READY，而 guard_index_job 又禁止修改
        # 终态任务——所以先判定，再落任务终态，最后切版本状态。
        ready_possible = bad == 0 and pending == 0 and ok == expected and expected > 0
        if ready_possible:
            cursor.execute(
                """
                UPDATE text2sql.t2s_index_job
                   SET status = 'COMPLETED', processed_count = %s, failed_count = 0,
                       finished_at = now()
                 WHERE id = %s
                """, (ok, job_id))
            # 触发器 RAISE 会中止当前事务；用 savepoint 保住后续的 FAILED 落库。
            cursor.execute('SAVEPOINT ready_transition')
            try:
                cursor.execute(
                    "UPDATE text2sql.t2s_config_version SET status = 'READY' WHERE id = %s",
                    (version_id,))
                cursor.execute('RELEASE SAVEPOINT ready_transition')
                status = 'READY'
            except psycopg2.errors.RaiseException as error:
                cursor.execute('ROLLBACK TO SAVEPOINT ready_transition')
                # 预检已通过仍被拒绝：保留可诊断的 FAILED，而不是卡在 BUILDING。
                cursor.execute(
                    "UPDATE text2sql.t2s_config_version SET status = 'FAILED' WHERE id = %s",
                    (version_id,))
                status = 'FAILED'
                errors['_version'] = str(error).strip()[:500]
        else:
            not_indexed = max(expected - ok, bad)
            message = (f'{bad} 个知识对象索引失败' if bad
                       else f'{pending} 个知识对象未完成索引')
            cursor.execute(
                """
                UPDATE text2sql.t2s_index_job
                   SET status = 'FAILED', processed_count = %s, failed_count = %s,
                       error_message = %s, finished_at = now()
                 WHERE id = %s
                """, (ok, not_indexed, message, job_id))
            cursor.execute(
                "UPDATE text2sql.t2s_config_version SET status = 'FAILED' WHERE id = %s",
                (version_id,))
            status = 'FAILED'
        cursor.execute(
            'SELECT * FROM text2sql.t2s_config_version WHERE id = %s', (version_id,))
        version_row = dict(cursor.fetchone())
    return {'status': status, 'version': version_row,
            'processed': processed, 'failed': failed, 'errors': errors}


# ---------------------------------------------------------------------------
# 查询 / 发布
# ---------------------------------------------------------------------------
_VERSION_COLUMNS = f"""
    v.id, v.datasource_id, v.revision, v.status, v.content_hash,
    v.expected_knowledge_count, v.embedding_model, v.embedding_dimensions,
    v.created_by, to_char(v.ready_at, {_TS}) AS ready_at,
    to_char(v.created_at, {_TS}) AS created_at,
    to_char(v.updated_at, {_TS}) AS updated_at
"""


def list_versions(datasource_id: str) -> list[dict]:
    with _transaction() as cursor:
        cursor.execute(
            f"""
            SELECT {_VERSION_COLUMNS},
                   (SELECT count(*) FROM text2sql.t2s_knowledge k
                     WHERE k.version_id = v.id AND k.index_status = 'INDEXED') AS indexed_count,
                   (SELECT count(*) FROM text2sql.t2s_knowledge k
                     WHERE k.version_id = v.id AND k.index_status = 'FAILED') AS failed_count
              FROM text2sql.t2s_config_version v
             WHERE v.datasource_id = %s
             ORDER BY v.revision DESC
            """, (datasource_id,))
        return [dict(item) for item in cursor.fetchall()]


def get_version(datasource_id: str, version_id: str) -> dict | None:
    with _transaction() as cursor:
        cursor.execute(
            f"""
            SELECT {_VERSION_COLUMNS}, v.snapshot,
                   (SELECT count(*) FROM text2sql.t2s_knowledge k
                     WHERE k.version_id = v.id AND k.index_status = 'INDEXED') AS indexed_count,
                   (SELECT count(*) FROM text2sql.t2s_knowledge k
                     WHERE k.version_id = v.id AND k.index_status = 'FAILED') AS failed_count
              FROM text2sql.t2s_config_version v
             WHERE v.id = %s AND v.datasource_id = %s
            """, (version_id, datasource_id))
        version = _row(cursor.fetchone())
        if version is None:
            return None
        cursor.execute(
            """
            SELECT object_type, index_status, count(*) AS count
              FROM text2sql.t2s_knowledge WHERE version_id = %s
             GROUP BY object_type, index_status ORDER BY object_type, index_status
            """, (version_id,))
        version['knowledge'] = [dict(item) for item in cursor.fetchall()]
        cursor.execute(
            """
            SELECT store_kind, state, count(*) AS count
              FROM text2sql.t2s_knowledge_binding
             WHERE version_id = %s
             GROUP BY store_kind, state ORDER BY store_kind, state
            """, (version_id,))
        version['bindings'] = [dict(item) for item in cursor.fetchall()]
        cursor.execute(
            f"""
            SELECT id, job_type, status, attempt, total_count, processed_count,
                   failed_count, error_message, worker_id,
                   to_char(started_at, {_TS}) AS started_at,
                   to_char(finished_at, {_TS}) AS finished_at,
                   to_char(created_at, {_TS}) AS created_at
              FROM text2sql.t2s_index_job WHERE version_id = %s
             ORDER BY created_at
            """, (version_id,))
        version['jobs'] = [dict(item) for item in cursor.fetchall()]
        return version


def publish_version(datasource_id: str, version_id: str,
                    expected_revision: int, actor: str) -> dict:
    with _transaction() as cursor:
        cursor.execute("SELECT set_config('text2sql.actor_id', %s, true)",
                       (actor or '',))
        try:
            cursor.execute('SELECT text2sql.publish_version(%s, %s, %s)',
                           (datasource_id, version_id, expected_revision))
        except psycopg2.errors.RaiseException as error:
            raise Text2SqlConflict(str(error).strip()) from error
        cursor.execute(
            f"""
            SELECT p.id, p.datasource_id, p.previous_version_id, p.version_id,
                   p.actor_id, to_char(p.created_at, {_TS}) AS created_at,
                   v.revision
              FROM text2sql.t2s_publication p
              JOIN text2sql.t2s_config_version v ON v.id = p.version_id
             WHERE p.datasource_id = %s
             ORDER BY p.created_at DESC, p.id DESC LIMIT 1
            """, (datasource_id,))
        return dict(cursor.fetchone())


def _upsert_binding(cursor, knowledge_id: str, datasource_id: str,
                    version_id: str, store_kind: str, state: str,
                    *, external_id: Optional[str] = None,
                    error: Optional[str] = None) -> None:
    """记录「某个存储在某个知识对象上的索引结果」。

    ``t2s_knowledge.index_status`` 仍是汇总态；这张表让每种存储各自成败可见。
    """
    cursor.execute(
        """
        INSERT INTO text2sql.t2s_knowledge_binding
            (knowledge_id, datasource_id, version_id, store_kind, state,
             external_id, error, indexed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s,
                CASE WHEN %s = 'INDEXED' THEN now() END)
        ON CONFLICT (knowledge_id, store_kind) DO UPDATE
           SET state = EXCLUDED.state,
               external_id = EXCLUDED.external_id,
               error = EXCLUDED.error,
               indexed_at = EXCLUDED.indexed_at,
               updated_at = now()
        """,
        (knowledge_id, datasource_id, version_id, store_kind, state,
         external_id if state == 'INDEXED' else None,
         None if state == 'INDEXED' else (error or '')[:2000], state))


def binding_summary(version_id: str) -> list[dict[str, Any]]:
    """版本内每种存储的索引状态汇总（版本详情页与对账用）。"""
    with _transaction() as cursor:
        cursor.execute(
            """
            SELECT store_kind, state, count(*) AS count
              FROM text2sql.t2s_knowledge_binding
             WHERE version_id = %s
             GROUP BY store_kind, state
             ORDER BY store_kind, state
            """, (version_id,))
        return [dict(item) for item in cursor.fetchall()]


def archive_versions(datasource_id: str, keep: int) -> dict[str, int]:
    """回收旧版本存储：可归档的 READY → ARCHIVED，再清掉它们已经没用的知识。

    活动版本、被查询历史/收藏/反馈引用的版本、以及最近 ``keep`` 个 READY 一律跳过，
    由 :func:`text2sql.archive_versions` 在数据库侧保证。
    """
    with _transaction() as cursor:
        cursor.execute('SELECT text2sql.archive_versions(%s, %s) AS archived',
                       (datasource_id, int(keep)))
        archived = int(cursor.fetchone()['archived'] or 0)
        cursor.execute(
            'SELECT text2sql.purge_archived_knowledge(%s) AS purged', (datasource_id,))
        purged = int(cursor.fetchone()['purged'] or 0)
    return {'archived': archived, 'purgedKnowledge': purged}


def list_publications(datasource_id: str) -> list[dict]:
    with _transaction() as cursor:
        cursor.execute(
            f"""
            SELECT p.id, p.datasource_id, p.previous_version_id, p.version_id,
                   p.actor_id, to_char(p.created_at, {_TS}) AS created_at,
                   v.revision
              FROM text2sql.t2s_publication p
              JOIN text2sql.t2s_config_version v ON v.id = p.version_id
             WHERE p.datasource_id = %s
             ORDER BY p.created_at DESC, p.id DESC
            """, (datasource_id,))
        return [dict(item) for item in cursor.fetchall()]
