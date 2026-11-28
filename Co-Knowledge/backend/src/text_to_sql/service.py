"""Text2SQL 数据源与目录的业务层。

职责边界：校验/映射在 :mod:`text_to_sql.models`，SQL 在
:mod:`text_to_sql.repository_pg`，外部库只读扫描在 :mod:`text_to_sql.scanner`。
本层只负责把三者按协议串起来，并保证「密码不落日志、不出接口」。
"""

from __future__ import annotations

import time
from typing import Any, Optional
from uuid import UUID

import psycopg2

from text_to_sql import (account_guard, assist, build_queue, catalog_repository,
                         indexer, models, net_guard, repository_pg, scanner,
                         version_repository)
from text_to_sql.credentials import decrypt_password
from text_to_sql.errors import (Text2SqlNotFound, Text2SqlUpstreamError,
                             Text2SqlValidationError)

CONNECT_TIMEOUT_SECONDS = 8
# AI 辅助按批调用模型：控制单次 prompt，也让前端能看到进度。
ASSIST_BATCH_TABLES = 4
ASSIST_BATCH_VALUES = 60


def _merge_usage(total: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    for key, value in (usage or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total[key] = total.get(key, 0) + value
        else:
            total.setdefault(key, value)
    return total


def _dedupe_suggestions(kind: str,
                        suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """分批生成后去重：关联按列对、指标按 key，其余按 id。"""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in suggestions:
        if kind == 'relations':
            key = str(item.get('id'))
        elif kind == 'metrics':
            key = f"metric:{item.get('key')}"
        else:
            key = f"{item.get('target')}:{item.get('id')}"
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def parse_uuid(value: Any, label: str) -> str:
    """校验并归一化成字符串（psycopg2 不适配 ``uuid.UUID`` 对象）。"""
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise Text2SqlValidationError(f'{label} 不是合法的 UUID') from error


class Text2SqlService:
    def __init__(self, repository=repository_pg, scan_database=scanner.scan_database,
                 catalog=catalog_repository, versions=version_repository,
                 embed=indexer.embed_texts, assist_model=None):
        self._repo = repository
        self._scan = scan_database
        self._catalog = catalog
        self._versions = versions
        self._embed = embed
        self._assist_model = assist_model or assist.call_model

    # ------------------------------------------------------------------
    # 数据源
    # ------------------------------------------------------------------
    def list_datasources(self) -> dict[str, Any]:
        rows = self._repo.list_datasources()
        selected = self._repo.selected_tables_map()
        items = [models.datasource_to_api(row,
                                          selected_tables=selected.get(str(row['id']), []))
                 for row in rows]
        return {'items': items, 'total': len(items)}

    def get_datasource(self, datasource_id: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        row = self._repo.get_datasource(uuid)
        if row is None:
            raise Text2SqlNotFound('数据源不存在或已删除')
        return models.datasource_to_api(
            row, selected_tables=self._repo.selected_table_names(uuid))

    def create_datasource(self, payload: dict[str, Any]) -> dict[str, Any]:
        fields = models.parse_create_datasource(payload)
        net_guard.assert_host_allowed(fields['host'])
        row = self._repo.create_datasource(fields)
        return models.datasource_to_api(row, selected_tables=[])

    def update_datasource(self, datasource_id: str,
                          payload: dict[str, Any]) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        fields = models.parse_update_datasource(payload)
        if 'host' in fields:
            net_guard.assert_host_allowed(fields['host'])
        row = self._repo.get_datasource(uuid)
        if row is None:
            raise Text2SqlNotFound('数据源不存在或已删除')
        if fields:
            row = self._repo.update_datasource(uuid, fields)
            if row is None:
                raise Text2SqlNotFound('数据源不存在或已删除')
        return models.datasource_to_api(
            row, selected_tables=self._repo.selected_table_names(uuid))

    def delete_datasource(self, datasource_id: str) -> None:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        if not self._repo.soft_delete_datasource(uuid):
            raise Text2SqlNotFound('数据源不存在或已删除')

    def test_connection(self, datasource_id: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        connection = self._connection_for(uuid)
        net_guard.assert_host_allowed(connection['host'])
        started = time.monotonic()
        try:
            conn = psycopg2.connect(
                host=connection['host'], port=connection['port'],
                dbname=connection['database'], user=connection['username'],
                password=connection['password'],
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                application_name='co-knowledge-text2sql',
                options='-c statement_timeout=5000',
            )
            try:
                with conn.cursor() as cursor:
                    cursor.execute('SELECT 1')
                    cursor.fetchone()
                    state = account_guard.readonly_state(cursor)
                    schemas = scanner.list_schemas(cursor)
            finally:
                conn.close()
        except psycopg2.Error as error:
            raise Text2SqlUpstreamError(
                f"连接失败：{_safe_error(error)}") from error
        warnings = account_guard.assert_minimal_privilege(
            state, host=connection['host'])
        elapsed_ms = int((time.monotonic() - started) * 1000)
        row = self._repo.mark_connection_tested(uuid)
        if row is None:
            raise Text2SqlNotFound('数据源不存在或已删除')
        return {
            'ok': True,
            'latencyMs': elapsed_ms,
            'testedAt': row.get('connection_tested_at'),
            'warnings': warnings,
            'schemas': schemas,
            'datasource': models.datasource_to_api(
                row, selected_tables=self._repo.selected_table_names(uuid)),
        }

    def test_connection_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """测试「尚未保存」的连接配置（新增数据源表单用）。"""
        fields = models.parse_create_datasource(payload)
        net_guard.assert_host_allowed(fields['host'])
        started = time.monotonic()
        try:
            conn = psycopg2.connect(
                host=fields['host'], port=fields['port'],
                dbname=fields['database_name'], user=fields['username'],
                password=fields['password'],
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                application_name='co-knowledge-text2sql',
                options='-c statement_timeout=5000',
            )
            try:
                with conn.cursor() as cursor:
                    cursor.execute('SELECT 1')
                    cursor.fetchone()
                    state = account_guard.readonly_state(cursor)
                    schemas = scanner.list_schemas(cursor)
            finally:
                conn.close()
        except psycopg2.Error as error:
            raise Text2SqlUpstreamError(
                f"连接失败：{_safe_error(error)}") from error
        warnings = account_guard.assert_minimal_privilege(
            state, host=fields['host'])
        return {'ok': True,
                'latencyMs': int((time.monotonic() - started) * 1000),
                'warnings': warnings,
                'schemas': schemas}

    def scan(self, datasource_id: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        connection = self._connection_for(uuid)
        net_guard.assert_host_allowed(connection['host'])
        # 只为「已启用表 + 已启用列」收录取值：扫描时还没选表，第一次扫描
        # 自然一条值也不收；选完表（准备数据）会再扫描一次。
        scope = self._repo.profiling_scope(uuid)
        snapshot = self._scan(connection, connection['include_schemas'],
                              profile_scope=scope)
        result = self._repo.apply_scan(uuid, snapshot)
        if result is None:
            raise Text2SqlNotFound('数据源不存在或已删除')
        datasource = models.datasource_to_api(
            result['datasource'],
            selected_tables=self._repo.selected_table_names(uuid))
        return {
            'datasource': datasource,
            'summary': result['summary'],
            'revisionChanged': result['revisionChanged'],
        }

    def _connection_for(self, datasource_id: UUID) -> dict[str, Any]:
        row = self._repo.datasource_connection(datasource_id)
        if row is None:
            raise Text2SqlNotFound('数据源不存在或已删除')
        return {
            'host': row['host'],
            'port': row['port'],
            'database': row['database_name'],
            'username': row['username'],
            'password': decrypt_password(row['credential_ref']),
            'include_schemas': list(row['include_schemas'] or ['public']),
        }

    # ------------------------------------------------------------------
    # AI 辅助（只出建议，写入仍走各 PATCH 接口）
    # ------------------------------------------------------------------
    def assist(self, datasource_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """根据目录与少量样本生成建议；不落库。"""
        result = None
        for kind, data in self.assist_events(datasource_id, payload):
            if kind == 'result':
                result = data
        if result is None:
            raise Text2SqlUpstreamError('模型没有返回结果')
        return result

    def assist_events(self, datasource_id: str, payload: dict[str, Any]):
        """生成建议并逐段上报：``('stage', {...})`` … ``('result', {...})``。

        表多时按批调用模型（说明每批 4 张表、指标每表一批、枚举每批 60 个值），
        既控制单次 token，也让前端能看到进度。同步接口 :meth:`assist` 只是把
        这些事件抽干。
        """
        started = time.monotonic()
        uuid = parse_uuid(datasource_id, 'datasourceId')
        fields = models.parse_assist(payload)
        datasource = self._require_datasource(uuid)
        tables = self._repo.list_tables(uuid)
        kind = fields['kind']
        scope = self._assist_scope(uuid, tables, fields['table_ids'], kind)
        scope_ids = {str(table['id']) for table in scope}
        relations = self._catalog.list_relations(uuid)
        metrics = self._catalog.list_metrics(uuid)
        if kind in ('relations', 'metrics'):
            relations = [row for row in relations
                         if str(row.get('source_table_id')) in scope_ids
                         or str(row.get('target_table_id')) in scope_ids]
            metrics = [row for row in metrics
                       if str(row.get('base_table_id')) in scope_ids]
        values = []
        if kind == 'values':
            wanted = {f"{row['schema_name']}.{row['table_name']}" for row in scope}
            values = [value for value in self._catalog.list_values(uuid)
                      if value.get('enabled') is not False
                      and value.get('table_name') in wanted][:assist.MAX_VALUES]
            if not values:
                raise Text2SqlValidationError('所选表里还没有枚举值，请先扫描结构')
        yield ('stage', {
            'id': 'collect', 'status': 'success',
            'ms': int((time.monotonic() - started) * 1000),
            'tables': len(scope), 'values': len(values),
        })

        samples: dict[str, list[dict[str, Any]]] = {}
        sample_started = time.monotonic()
        if fields['include_samples'] and kind in ('descriptions', 'values',
                                                  'relations'):
            connection = self._connection_for(uuid)
            net_guard.assert_host_allowed(connection['host'])
            keys = [(row['schema_name'], row['table_name']) for row in scope]
            samples = assist.sample_rows(connection, keys)
        yield ('stage', {
            'id': 'sample', 'status': 'success' if samples else 'skipped',
            'ms': int((time.monotonic() - sample_started) * 1000),
            'tables': len(samples),
        })

        datasource_brief = {
            'name': datasource.get('name'),
            'database': datasource.get('database_name'),
            'business_description': datasource.get('business_description'),
            'topic_name': datasource.get('topic_name'),
            'topic_description': datasource.get('topic_description'),
        }
        batches = self._assist_batches(kind, scope, values)
        suggestions: list[dict[str, Any]] = []
        usage_total: dict[str, Any] = {}
        model_name = ''
        for index, (batch_tables, batch_values) in enumerate(batches):
            yield ('stage', {'id': 'generate', 'status': 'running',
                             'batch': index + 1, 'batches': len(batches)})
            batch_started = time.monotonic()
            batch_keys = {f"{row['schema_name']}.{row['table_name']}"
                          for row in batch_tables}
            system, user = assist.prompt_for(
                kind,
                datasource=datasource_brief,
                tables=batch_tables, relations=relations, values=batch_values,
                samples={key: rows for key, rows in samples.items()
                         if key in batch_keys},
                question=fields['question'],
                metrics=metrics + [{'metric_key': item['key']}
                                   for item in suggestions
                                   if item['target'] == 'metric'])
            try:
                content, usage, name = self._assist_model(
                    system, user, fields['model'])
            except Text2SqlUpstreamError:
                raise
            except Exception as error:                            # noqa: BLE001
                raise Text2SqlUpstreamError(
                    f'模型生成失败：{error}') from error
            suggestions.extend(assist.parse_suggestions(
                kind, content, tables=batch_tables, values=batch_values,
                relations=relations, metrics=metrics + [
                    {'metric_key': item['key']} for item in suggestions
                    if item['target'] == 'metric']))
            usage_total = _merge_usage(usage_total, usage)
            model_name = model_name or name
            yield ('stage', {'id': 'generate', 'status': 'success',
                             'batch': index + 1, 'batches': len(batches),
                             'ms': int((time.monotonic() - batch_started) * 1000)})
        suggestions = _dedupe_suggestions(kind, suggestions)
        yield ('result', {
            'kind': kind,
            'suggestions': suggestions,
            'model': model_name,
            'usage': usage_total,
            'sampled': bool(samples),
            'tables': [str(row['id']) for row in scope],
            'batches': len(batches),
        })

    def _assist_batches(self, kind: str, scope: list[dict],
                        values: list[dict]) -> list[tuple[list[dict], list[dict]]]:
        if kind == 'metrics':
            return [([table], []) for table in scope]
        if kind == 'values':
            return [(scope, values[index:index + ASSIST_BATCH_VALUES])
                    for index in range(0, len(values), ASSIST_BATCH_VALUES)]
        if kind == 'descriptions':
            return [(scope[index:index + ASSIST_BATCH_TABLES], [])
                    for index in range(0, len(scope), ASSIST_BATCH_TABLES)]
        return [(scope, [])]

    def _assist_scope(self, datasource_id: str, tables: list[dict],
                      table_ids: list[str], kind: str) -> list[dict]:
        by_id = {str(table['id']): table for table in tables}
        if table_ids:
            missing = [item for item in table_ids if item not in by_id]
            if missing:
                raise Text2SqlNotFound('数据表不存在')
            scope = [by_id[item] for item in table_ids]
        else:
            scope = [table for table in tables
                     if table.get('enabled') and not table.get('missing_since')]
        scope = [table for table in scope if not table.get('missing_since')]
        if not scope:
            raise Text2SqlValidationError(
                '没有可分析的表：请先在「准备数据」里选择要查询的表')
        if kind != 'tables' and len(scope) > assist.MAX_TABLES:
            raise Text2SqlValidationError(
                f'一次最多分析 {assist.MAX_TABLES} 张表，请缩小范围')
        return scope

    # ------------------------------------------------------------------
    # 目录
    # ------------------------------------------------------------------
    def list_tables(self, datasource_id: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        if self._repo.get_datasource(uuid) is None:
            raise Text2SqlNotFound('数据源不存在或已删除')
        items = [models.table_to_api(row, row.get('columns') or [])
                 for row in self._repo.list_tables(uuid)]
        return {'items': items, 'total': len(items)}

    def update_table(self, datasource_id: str, table_id: str,
                     payload: dict[str, Any]) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        table_uuid = parse_uuid(table_id, 'tableId')
        fields = models.parse_table_update(payload)
        if not fields:
            table = self._repo.get_table(uuid, table_uuid)
            if table is None:
                raise Text2SqlNotFound('数据表不存在')
            return models.table_to_api(table, table.get('columns') or [])
        row = self._repo.update_table(uuid, table_uuid, fields)
        if row is None:
            raise Text2SqlNotFound('数据表不存在')
        table = self._repo.get_table(uuid, table_uuid)
        return models.table_to_api(table, table.get('columns') or [])

    def update_column(self, datasource_id: str, column_id: str,
                      payload: dict[str, Any]) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        column_uuid = parse_uuid(column_id, 'columnId')
        fields = models.parse_column_update(payload)
        if not fields:
            column = self._repo.get_column(uuid, column_uuid)
            if column is None:
                raise Text2SqlNotFound('字段不存在')
            return models.column_to_api(column)
        row = self._repo.update_column(uuid, column_uuid, fields)
        if row is None:
            raise Text2SqlNotFound('字段不存在')
        column = self._repo.get_column(uuid, column_uuid)
        return models.column_to_api(column)


    # ------------------------------------------------------------------
    # 关联
    # ------------------------------------------------------------------
    def list_relations(self, datasource_id: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        self._require_datasource(uuid)
        items = [models.relation_to_api(row) for row in self._catalog.list_relations(uuid)]
        return {'items': items, 'total': len(items)}

    def create_relation(self, datasource_id: str,
                        payload: dict[str, Any]) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        fields = models.parse_relation_create(payload)
        relation_id = self._catalog.create_relation(uuid, fields)
        return models.relation_to_api(self._catalog.get_relation(uuid, relation_id))

    def update_relation(self, datasource_id: str, relation_id: str,
                        payload: dict[str, Any]) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        rid = parse_uuid(relation_id, 'relationId')
        fields = models.parse_relation_update(payload)
        if fields and not self._catalog.update_relation(uuid, rid, fields):
            raise Text2SqlNotFound('关联不存在')
        row = self._catalog.get_relation(uuid, rid)
        if row is None:
            raise Text2SqlNotFound('关联不存在')
        return models.relation_to_api(row)

    def delete_relation(self, datasource_id: str, relation_id: str) -> None:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        rid = parse_uuid(relation_id, 'relationId')
        if not self._catalog.delete_relation(uuid, rid):
            raise Text2SqlNotFound('关联不存在')

    def verify_relation(self, datasource_id: str, relation_id: str,
                        payload: dict[str, Any], actor: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        rid = parse_uuid(relation_id, 'relationId')
        verified = models.parse_relation_verification(payload)
        if not self._catalog.verify_relation(uuid, rid, actor, verified):
            raise Text2SqlNotFound('关联不存在')
        return models.relation_to_api(self._catalog.get_relation(uuid, rid))

    # ------------------------------------------------------------------
    # 枚举
    # ------------------------------------------------------------------
    def list_values(self, datasource_id: str,
                    column_id: str | None = None) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        self._require_datasource(uuid)
        column_uuid = parse_uuid(column_id, 'columnId') if column_id else None
        items = [models.value_to_api(row)
                 for row in self._catalog.list_values(uuid, column_uuid)]
        return {'items': items, 'total': len(items)}

    def create_value(self, datasource_id: str,
                     payload: dict[str, Any]) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        fields = models.parse_value_create(payload)
        value_id = self._catalog.create_value(uuid, fields)
        return models.value_to_api(self._catalog.get_value(uuid, value_id))

    def update_value(self, datasource_id: str, value_id: str,
                     payload: dict[str, Any]) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        vid = parse_uuid(value_id, 'valueId')
        fields = models.parse_value_update(payload)
        if fields and not self._catalog.update_value(uuid, vid, fields):
            raise Text2SqlNotFound('枚举值不存在')
        row = self._catalog.get_value(uuid, vid)
        if row is None:
            raise Text2SqlNotFound('枚举值不存在')
        return models.value_to_api(row)

    def delete_value(self, datasource_id: str, value_id: str) -> None:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        vid = parse_uuid(value_id, 'valueId')
        if not self._catalog.delete_value(uuid, vid):
            raise Text2SqlNotFound('枚举值不存在')

    # ------------------------------------------------------------------
    # 指标
    # ------------------------------------------------------------------
    def list_metrics(self, datasource_id: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        self._require_datasource(uuid)
        items = [models.metric_to_api(row) for row in self._catalog.list_metrics(uuid)]
        return {'items': items, 'total': len(items)}

    def create_metric(self, datasource_id: str,
                      payload: dict[str, Any]) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        fields = models.parse_metric_create(payload)
        if 'businessTimezone' not in payload:
            source = self._repo.get_datasource(uuid)
            if source is None:
                raise Text2SqlNotFound('数据源不存在或已删除')
            fields['business_timezone'] = source.get('business_timezone') or 'UTC'
        metric_id = self._catalog.create_metric(uuid, fields)
        return models.metric_to_api(self._catalog.get_metric(uuid, metric_id))

    def update_metric(self, datasource_id: str, metric_id: str,
                      payload: dict[str, Any]) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        mid = parse_uuid(metric_id, 'metricId')
        fields = models.parse_metric_update(payload)
        if fields and not self._catalog.update_metric(uuid, mid, fields):
            raise Text2SqlNotFound('指标不存在')
        row = self._catalog.get_metric(uuid, mid)
        if row is None:
            raise Text2SqlNotFound('指标不存在')
        return models.metric_to_api(row)

    def delete_metric(self, datasource_id: str, metric_id: str) -> None:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        mid = parse_uuid(metric_id, 'metricId')
        if not self._catalog.delete_metric(uuid, mid):
            raise Text2SqlNotFound('指标不存在')

    def set_metric_status(self, datasource_id: str, metric_id: str,
                          payload: dict[str, Any], actor: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        mid = parse_uuid(metric_id, 'metricId')
        status = models.parse_metric_status(payload)
        if not self._catalog.set_metric_status(uuid, mid, status, actor):
            raise Text2SqlNotFound('指标不存在')
        return models.metric_to_api(self._catalog.get_metric(uuid, mid))

    def _require_datasource(self, datasource_id: UUID) -> dict[str, Any]:
        row = self._repo.get_datasource(datasource_id)
        if row is None:
            raise Text2SqlNotFound('数据源不存在或已删除')
        return row


    # ------------------------------------------------------------------
    # 配置版本 / 发布
    # ------------------------------------------------------------------
    def create_version(self, datasource_id: str, payload: dict[str, Any],
                       actor: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        if not isinstance(payload, dict):
            payload = {}
        # 模型以数据源配置为准；请求参数只作为「首次配置」的入口。
        # 同一数据源此后始终用同一模型 → 维度确定，向量存储才能定长。
        source = self._repo.get_datasource(uuid)
        if source is None:
            raise Text2SqlNotFound('数据源不存在或已删除')
        configured = source.get('embedding_model')
        requested = payload.get('embeddingModel') or configured
        if configured and payload.get('embeddingModel') and \
                payload['embeddingModel'] != configured:
            raise Text2SqlValidationError(
                f'数据源已固定使用 {configured}；换模型请新建数据源')
        model_name, dimensions = self._resolve_embedding(requested)
        if not configured:
            self._repo.update_datasource(uuid, {'embedding_model': model_name})
        result = self._versions.create_version(uuid, model_name, dimensions, actor)
        version = self._versions.get_version(uuid, result['version_id'])
        return {**result,
                'versionId': result.get('version_id'),
                'version': models.version_to_api(version, include_snapshot=True)}

    def list_versions(self, datasource_id: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        self._require_datasource(uuid)
        items = [models.version_to_api(item)
                 for item in self._versions.list_versions(uuid)]
        return {'items': items, 'total': len(items)}

    def get_version(self, datasource_id: str, version_id: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        vid = parse_uuid(version_id, 'versionId')
        version = self._versions.get_version(uuid, vid)
        if version is None:
            raise Text2SqlNotFound('配置版本不存在')
        return models.version_to_api(version, include_snapshot=True)

    def start_build(self, datasource_id: str, version_id: str) -> dict[str, Any]:
        """把构建排进统一任务队列；已 READY 的版本直接返回现状。"""
        uuid = parse_uuid(datasource_id, 'datasourceId')
        vid = parse_uuid(version_id, 'versionId')
        version = self._versions.get_version(uuid, vid)
        if version is None:
            raise Text2SqlNotFound('配置版本不存在')
        if version['status'] == 'READY':
            return {'status': 'READY', 'taskId': None, 'queued': False,
                    'version': models.version_to_api(version, include_snapshot=True)}
        if not build_queue.enabled():
            # 队列关闭（单测/轻量环境）：保持同步语义，调用方拿到的仍是终态。
            return self.build_version(datasource_id, version_id)
        task_id = build_queue.enqueue(str(uuid), str(vid))
        return {'status': 'QUEUED', 'taskId': task_id, 'queued': True,
                'version': models.version_to_api(version, include_snapshot=True)}

    def build_version(self, datasource_id: str,
                      version_id: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        vid = parse_uuid(version_id, 'versionId')
        prepared = self._versions.prepare_build(uuid, vid, worker_id='api')
        if prepared is None:
            raise Text2SqlNotFound('配置版本不存在')
        if prepared['status'] == 'READY':
            return {'status': 'READY', 'processed': 0, 'failed': 0, 'errors': {},
                    'version': models.version_to_api(
                        self._versions.get_version(uuid, vid),
                        include_snapshot=True)}
        pending = prepared['pending']
        embeddings: dict[str, list[float]] = {}
        errors: dict[str, str] = {}
        if pending:
            try:
                vectors = self._embed([item['content'] for item in pending],
                                      prepared['embedding_model'])
                for item, vector in zip(pending, vectors):
                    embeddings[item['id']] = vector
            except Exception as error:                             # noqa: BLE001
                message = str(error)[:500]
                for item in pending:
                    errors[item['id']] = message
        try:
            result = self._versions.finish_build(uuid, vid, prepared['job_id'],
                                                 embeddings, errors)
        except Exception as error:                                 # noqa: BLE001
            # 写向量这类步骤失败时要收口任务与版本，否则一直停在 RUNNING/BUILDING。
            self._versions.fail_build(uuid, vid, prepared['job_id'], str(error))
            raise
        if result is None:
            raise Text2SqlNotFound('配置版本不存在')
        return {'status': result['status'], 'processed': result['processed'],
                'failed': result['failed'],
                'errors': {key: value for key, value in result['errors'].items()
                           if not key.startswith('_')},
                'version': models.version_to_api(
                    self._versions.get_version(uuid, vid),
                    include_snapshot=True)}

    def publish(self, datasource_id: str, payload: dict[str, Any],
                actor: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        if not isinstance(payload, dict):
            raise Text2SqlValidationError('请求体必须是对象')
        version_id = parse_uuid(payload.get('versionId'), 'versionId')
        expected = payload.get('expectedRevision')
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
            raise Text2SqlValidationError('expectedRevision 必须是正整数')
        # 发布是「这条数据源从此可被查询」的关口：在这里再校验一次地址，
        # 覆盖规则上线前就已存在的数据源（查询路径不重复做 DNS 校验）。
        connection = self._repo.datasource_connection(uuid)
        if connection is None:
            raise Text2SqlNotFound('数据源不存在或已删除')
        net_guard.assert_host_allowed(connection['host'])
        row = self._versions.publish_version(uuid, version_id, expected, actor)
        return {
            'id': str(row['id']),
            'datasourceId': str(row['datasource_id']),
            'previousVersionId': (str(row['previous_version_id'])
                                  if row.get('previous_version_id') else None),
            'versionId': str(row['version_id']),
            'revision': row.get('revision'),
            'actorId': row.get('actor_id'),
            'createdAt': row.get('created_at'),
        }

    def cleanup_versions(self, datasource_id: str, keep: int) -> dict[str, Any]:
        """回收旧版本：保留最近 ``keep`` 个 READY，其余归档并清掉知识。"""
        uuid = parse_uuid(datasource_id, 'datasourceId')
        if isinstance(keep, bool) or not isinstance(keep, int) or keep < 0:
            raise Text2SqlValidationError('keep 必须是非负整数')
        self._require_datasource(uuid)
        result = self._versions.archive_versions(uuid, keep)
        return {**result,
                'versions': [models.version_to_api(item)
                             for item in self._versions.list_versions(uuid)]}

    def list_publications(self, datasource_id: str) -> dict[str, Any]:
        uuid = parse_uuid(datasource_id, 'datasourceId')
        self._require_datasource(uuid)
        rows = self._versions.list_publications(uuid)
        items = [{
            'id': str(row['id']),
            'datasourceId': str(row['datasource_id']),
            'previousVersionId': (str(row['previous_version_id'])
                                  if row.get('previous_version_id') else None),
            'versionId': str(row['version_id']),
            'revision': row.get('revision'),
            'actorId': row.get('actor_id'),
            'createdAt': row.get('created_at'),
        } for row in rows]
        return {'items': items, 'total': len(items)}

    def _resolve_embedding(self, requested: Any) -> tuple[str, int]:
        from model.gateway import resolve_model

        try:
            target = resolve_model(requested if isinstance(requested, str) else None)
        except Exception as error:                                 # noqa: BLE001
            raise Text2SqlValidationError(
                f'无法解析 embedding 模型：{error}') from error
        name = target.model_name or target.api_model
        if not name or not target.dimension:
            raise Text2SqlValidationError('未配置可用的 embedding 模型')
        return name, int(target.dimension)


def _safe_error(error: BaseException) -> str:
    text = str(error).strip().splitlines()[0] if str(error).strip() else error.__class__.__name__
    return text[:300]


_service: Optional[Text2SqlService] = None


def get_service() -> Text2SqlService:
    global _service
    if _service is None:
        _service = Text2SqlService()
    return _service
