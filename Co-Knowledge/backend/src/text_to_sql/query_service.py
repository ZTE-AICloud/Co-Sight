"""Text2SQL 查询编排：检索 → 生成 → 校验 → 只读执行 → 历史落库。

一次查询是一条 ``t2s_query_run``，绑定当时发布的活动版本。问题、版本与检索
快照都不可变；失败也会落库，前端从历史里能看到失败阶段和错误码。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from text_to_sql import (context_builder, models, query_repository, retention,
                         schema_retriever, sql_guard, value_resolver)
from text_to_sql.credentials import decrypt_password
from text_to_sql.errors import (Text2SqlConflict, Text2SqlNotFound,
                                Text2SqlUpstreamError)

log = logging.getLogger(__name__)

STAGE_DEFS = (
    ('tables', 'Table Retrieval', '表检索'),
    ('columns', 'Column Retrieval', '字段检索'),
    ('values', 'Value Retrieval', '值匹配'),
    ('relations', 'Relation Expansion', '关系补全'),
    ('llm', 'SQL Generation', 'SQL 生成'),
    ('validation', 'SQL Validation', '安全校验'),
    ('explain', 'EXPLAIN', '执行计划'),
    ('execute', 'Execute', '只读查询'),
)

TIMING_KEYS = tuple(f'{stage}_ms' for stage, _, _ in STAGE_DEFS)

#: 生成 + 结构校验的最大尝试次数。只对「校验不通过」重试；模型调用失败不重试。
MAX_GENERATION_ATTEMPTS = 2


class QueryFailure(RuntimeError):
    def __init__(self, code: str, message: str, stage: str,
                 category: str = '查询失败'):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.category = category


class Text2SqlQueryService:
    def __init__(self, repository=query_repository,
                 embed=None, llm=None, rerank_model: Optional[str] = None):
        self._repo = repository
        self._embed = embed or _embed_question
        self._llm = llm or _generate_sql
        #: 未显式指定时，重排交给注册表里的默认重排端点；没有就跳过。
        self._rerank_model = rerank_model or _default_rerank_model()

    # ------------------------------------------------------------------
    # 生成 + 校验（失败回灌原因，有限次重试）
    # ------------------------------------------------------------------
    def _generate_and_validate(
            self, *, request: dict[str, Any], snapshot: dict[str, Any],
            schema_context: str, value_hints: list[dict[str, Any]],
            resolved_range: dict[str, Any], reference_date: str,
            model: Optional[str] = None
    ) -> tuple[dict[str, Any], str, int]:
        """最多 ``MAX_GENERATION_ATTEMPTS`` 次：把校验失败的原因回灌给模型。

        只对「结构/白名单」类失败重试；模型调用本身失败、或用户给了手工 SQL 时不重试。
        """
        feedback = ''
        last_error: Optional[sql_guard.SqlGuardError] = None
        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            generated = self._llm(
                question=request['question'], snapshot=snapshot,
                schema_context=schema_context, value_hints=value_hints,
                date_policy=request['date_policy'],
                resolved_time_range=resolved_range,
                reference_date=reference_date,
                model=model,
                feedback=feedback)
            try:
                return generated, sql_guard.validate_sql(
                    generated.get('sql') or '', snapshot), attempt
            except sql_guard.SqlGuardError as error:
                last_error = error
                if attempt >= MAX_GENERATION_ATTEMPTS:
                    raise
                feedback = (f'上一版 SQL 未通过校验（{error.code}）：{error.message}。'
                            '请修正后重新输出完整 JSON。')
        raise last_error or sql_guard.SqlGuardError('SQL_EMPTY', 'SQL 不能为空')

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def run_query(self, datasource_id: str, payload: dict[str, Any],
                  actor: str, *,
                  on_stage: Optional[Callable[[str, str, Optional[int]], None]] = None
                  ) -> dict[str, Any]:
        """执行一次查询；``on_stage(stage, status, ms)`` 用于流式进度上报。

        阶段 id 与 ``STAGE_DEFS`` 一致；``status`` 只有 ``running`` /
        ``success`` / ``skipped``，失败由最终响应里的 ``error.stage`` 表达。
        回调异常只记日志，不影响查询本身。
        """
        emit = _stage_emitter(on_stage)
        request = models.parse_query_request(payload)
        datasource_uuid = models._uuid_text(datasource_id, 'datasourceId')
        context = self._repo.get_active_context(datasource_uuid)
        if context is None:
            raise Text2SqlNotFound('数据源不存在或已删除')
        version_id = str(context.get('active_version_id') or '')
        if (not version_id
                or context.get('active_version_status') != 'READY'
                or context.get('active_version_revision') != context.get('config_revision')):
            raise Text2SqlConflict('数据源尚未发布可用的语义索引，请先构建并发布版本',
                                   problem_code='text2sql.not_published')
        snapshot = context.get('snapshot') or {}
        if not snapshot.get('tables'):
            raise Text2SqlConflict('当前版本没有可查询的表，请先扫描并选择表',
                                   problem_code='text2sql.not_published')

        timezone = context.get('business_timezone') or 'UTC'
        reference_date = datetime.now(ZoneInfo(timezone)).date().isoformat()
        resolved_range = _resolved_time_range(request, reference_date, timezone)
        # 生成模型优先级：请求显式指定 > 数据源配置 > 部署默认（由 resolve 回落）。
        # 数据源这一层可随时修改，不参与版本冻结；请求里的 model 仍可直接覆盖。
        generation_model = request.get('model') or context.get('llm_model') or None
        source_snapshot = {
            'datasource': {
                'id': str(context['id']),
                'name': context.get('name'),
                'revision': context.get('config_revision'),
                'businessTimezone': timezone,
            },
            'versionId': version_id,
            'versionRevision': context.get('active_version_revision'),
            'embeddingModel': context.get('embedding_model'),
            # 实际使用的 SQL 生成模型（请求 > 数据源 > 部署默认），用于事后回放。
            'llmModel': generation_model,
        }
        run = self._repo.create_run(
            datasource_id=str(context['id']), actor_id=actor,
            question=request['question'], version_id=version_id,
            parameters=request['parameters'], date_policy=request['date_policy'],
            resolved_time_range=resolved_range, source_snapshot=source_snapshot,
            parent_run_id=request['parent_run_id'])
        self._repo.mark_running(run['id'])

        started = time.perf_counter()
        timing: dict[str, int] = {key: 0 for key in TIMING_KEYS}
        generated_sql = ''
        try:
            emit('tables', 'running')
            connection = self._external_connection(context)
            retrieval_started = time.perf_counter()
            try:
                vector = self._embed(request['question'],
                                     context.get('embedding_model'))
            except Exception as error:                             # noqa: BLE001
                raise QueryFailure('SCHEMA_RETRIEVAL_FAILED',
                                   f'问题向量化失败：{_safe_error(error)}',
                                   'tables', 'Retrieval Error') from error
            found = schema_retriever.search(
                self._repo, version_id, request['question'], vector, limit=24,
                rerank_model=self._rerank_model,
                datasource_id=str(context['id']))
            hits = found['hits']
            timing['tables_ms'] = _ms(retrieval_started)
            emit('tables', 'success', timing['tables_ms'])

            # 上下文构建 = 选表 + 关系扩展 + 值/指标过滤 + 预算裁剪。
            # 检索命中在这里第一次真正参与生成（此前只进「答案依据」）。
            emit('columns', 'running')
            context_result = context_builder.build(snapshot, hits)
            timing['columns_ms'] = context_result.render_ms
            emit('columns', 'success', timing['columns_ms'])

            emit('values', 'running')
            values_started = time.perf_counter()
            value_hints = _value_hints(snapshot, request['question'])
            timing['values_ms'] = _ms(values_started)
            emit('values', 'success', timing['values_ms'])

            # 关系扩展发生在选表阶段，单独计时，避免这一段永远显示 0ms。
            emit('relations', 'running')
            timing['relations_ms'] = context_result.select_ms
            emit('relations', 'success', timing['relations_ms'])
            schema_context = context_result.text

            attempts = 1
            final_sql = ''
            if request['sql']:
                generated = {'sql': request['sql'],
                             'explanation': '使用人工编辑的 SQL 草稿',
                             'tables': [], 'confidence': None}
                timing['llm_ms'] = 0
                emit('llm', 'skipped')
            else:
                emit('llm', 'running')
                llm_started = time.perf_counter()
                generated, final_sql, attempts = self._generate_and_validate(
                    request=request, snapshot=snapshot,
                    schema_context=schema_context, value_hints=value_hints,
                    resolved_range=resolved_range, reference_date=reference_date,
                    model=generation_model)
                timing['llm_ms'] = _ms(llm_started)
                emit('llm', 'success', timing['llm_ms'])
            generated_sql = generated.get('sql') or ''

            emit('validation', 'running')
            validation_started = time.perf_counter()
            if request['sql']:
                final_sql = sql_guard.validate_sql(generated_sql, snapshot)
            policy = context.get('query_policy') or models.DEFAULT_QUERY_POLICY
            final_sql, value_resolution = value_resolver.resolve_and_rewrite(
                connection, final_sql, snapshot, policy)
            if value_resolution:
                final_sql = sql_guard.validate_sql(final_sql, snapshot)
            timing['validation_ms'] = _ms(validation_started)
            emit('validation', 'success', timing['validation_ms'])

            def on_phase(phase: str, ms: Optional[int] = None) -> None:
                # 进 EXPLAIN 前把上一段收尾，避免 UI 上一直挂着「执行计划进行中」。
                if phase == 'execute':
                    emit('explain', 'success', ms)
                emit(phase, 'running')

            try:
                executed = sql_guard.execute_readonly(
                    connection, final_sql,
                    context.get('query_policy') or models.DEFAULT_QUERY_POLICY,
                    snapshot, on_phase=on_phase)
            except sql_guard.QueryExecutionError as error:
                raise QueryFailure(error.code, error.message, 'execute',
                                   'SQL Execution Error') from error
            timing['explain_ms'] = int(executed.get('explain_ms') or 0)
            timing['execute_ms'] = int(executed.get('execute_ms') or 0)
            emit('execute', 'success', timing['execute_ms'])
            timing['total_ms'] = _ms(started)

            retrieval = _retrieval_view(snapshot, hits)
            retrieval['sources'] = found['sources']
            retrieval['context'] = _context_view(context_result)
            for item in value_resolution:
                if item.get('match') != 'resolved':
                    continue
                retrieval['values'].append({
                    'table': item['table'],
                    'column': item['column'],
                    'value': item['value'],
                    'label': item['value'],
                    'score': None,
                    'source': 'resolution',
                    'matched': item['from'],
                })
            validation = _validation_view(final_sql, executed,
                                          context.get('query_policy') or {})
            validation['attempts'] = attempts
            resolved_values = [item for item in value_resolution
                               if item.get('match') == 'resolved']
            if resolved_values:
                validation['checks'].append({
                    'label': '值解析',
                    'detail': '；'.join(f"{item['from']} → {item['value']}"
                                       for item in resolved_values),
                    'valid': True,
                })
            skipped_values = [item for item in value_resolution
                              if item.get('match') == 'skipped']
            if skipped_values:
                validation['warnings'].append(
                    '值解析超时，已按原值执行：'
                    + '、'.join(item['from'] for item in skipped_values))
            response = _response(
                request=request, context=context, run=run,
                reference_date=reference_date, timing=timing,
                retrieval=retrieval, generated=generated,
                final_sql=final_sql, validation=validation,
                executed=executed, error=None)
            self._repo.finish_success(
                run['id'], generated_sql=generated_sql, final_sql=final_sql,
                retrieval=retrieval,
                explanation={'text': generated.get('explanation') or ''},
                validation=validation, explain=executed.get('explain'),
                result={'columns': executed['columns'], 'rows': executed['rows'],
                        'row_count': executed['row_count'],
                        'truncated': executed['truncated'],
                        'byte_truncated': executed.get('byte_truncated', False)},
                row_count=executed['row_count'], truncated=executed['truncated'],
                stages=response['stages'], timing=timing,
                usage=generated.get('usage') or {},
                context=_context_snapshot(context_result),
                retention_days=retention.retention_days())
            return response
        except QueryFailure as failure:
            timing['total_ms'] = _ms(started)
            return self._failure_response(
                run, request, context, reference_date, timing, failure,
                generated_sql)
        except sql_guard.SqlGuardError as error:
            timing['total_ms'] = _ms(started)
            failure = QueryFailure(error.code, error.message, error.stage,
                                   'SQL Validation Error')
            return self._failure_response(
                run, request, context, reference_date, timing, failure,
                generated_sql)
        except value_resolver.ValueResolutionError as error:
            timing['total_ms'] = _ms(started)
            failure = QueryFailure(error.code, error.message, 'validation',
                                   'Value Resolution Error')
            return self._failure_response(
                run, request, context, reference_date, timing, failure,
                generated_sql)
        except Text2SqlUpstreamError as error:
            timing['total_ms'] = _ms(started)
            failure = QueryFailure('DATASOURCE_UNAVAILABLE', str(error),
                                   'tables', 'Retrieval Error')
            self._failure_response(
                run, request, context, reference_date, timing, failure,
                generated_sql)
            raise
        except Exception as error:                                 # noqa: BLE001
            timing['total_ms'] = _ms(started)
            failure = QueryFailure('QUERY_INTERNAL_ERROR', _safe_error(error),
                                   'execute', 'Query Error')
            return self._failure_response(
                run, request, context, reference_date, timing, failure,
                generated_sql)

    def _failure_response(self, run: dict[str, Any], request: dict[str, Any],
                          context: dict[str, Any], reference_date: str,
                          timing: dict[str, int], failure: QueryFailure,
                          generated_sql: str) -> dict[str, Any]:
        stages = _stages(timing, failure.stage)
        response = _response(
            request=request, context=context, run=run,
            reference_date=reference_date, timing=timing,
            retrieval={'tables': [], 'columns': [], 'values': [], 'relations': []},
            generated={'sql': generated_sql, 'explanation': ''},
            final_sql='', validation={'valid': False, 'checks': [], 'warnings': []},
            executed=None,
            error={'code': failure.code, 'message': failure.message,
                   'stage': failure.stage, 'category': failure.category},
            stages_override=stages)
        try:
            self._repo.finish_failure(
                run['id'], error_code=failure.code,
                error_message=failure.message, error_stage=failure.stage,
                stages=stages, timing=timing, generated_sql=generated_sql or None)
        except Exception:                                          # noqa: BLE001
            pass
        return response

    # ------------------------------------------------------------------
    # 历史 / 收藏 / 反馈
    # ------------------------------------------------------------------
    def list_runs(self, actor: str, *, datasource_id: Optional[str] = None,
                  status: Optional[str] = None, page: int = 1,
                  size: int = 20) -> dict[str, Any]:
        page = max(1, int(page or 1))
        size = min(100, max(1, int(size or 20)))
        data = self._repo.list_runs(
            actor, datasource_id=datasource_id, status=status,
            page=page, size=size)
        return {'items': [_run_to_api(item) for item in data['items']],
                'total': data['total'], 'page': page, 'pageSize': size}

    def get_run(self, run_id: str, actor: str) -> dict[str, Any]:
        row = self._repo.get_run(run_id, actor)
        if row is None:
            raise Text2SqlNotFound('查询记录不存在')
        return _run_to_api(row)

    def delete_run(self, run_id: str, actor: str) -> None:
        if not self._repo.delete_run(run_id, actor):
            raise Text2SqlNotFound('查询记录不存在')

    def clear_runs(self, actor: str, datasource_id: Optional[str] = None) -> None:
        self._repo.clear_runs(actor, datasource_id)

    def create_favorite(self, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        fields = models.parse_favorite_create(payload)
        created = self._repo.create_favorite(actor_id=actor, **fields)
        rows = self._repo.list_favorites(actor)
        row = next((item for item in rows if str(item['id']) == str(created['id'])), None)
        if row is None:
            raise Text2SqlNotFound('常用查询不存在')
        return models.favorite_to_api(row)

    def list_favorites(self, actor: str) -> dict[str, Any]:
        items = [models.favorite_to_api(row) for row in self._repo.list_favorites(actor)]
        return {'items': items, 'total': len(items)}

    def update_favorite(self, favorite_id: str, payload: dict[str, Any],
                        actor: str) -> dict[str, Any]:
        fields = models.parse_favorite_update(payload)
        if fields and not self._repo.update_favorite(favorite_id, actor, fields):
            raise Text2SqlNotFound('常用查询不存在')
        rows = self._repo.list_favorites(actor)
        row = next((item for item in rows if str(item['id']) == favorite_id), None)
        if row is None:
            raise Text2SqlNotFound('常用查询不存在')
        return models.favorite_to_api(row)

    def delete_favorite(self, favorite_id: str, actor: str) -> None:
        if not self._repo.delete_favorite(favorite_id, actor):
            raise Text2SqlNotFound('常用查询不存在')

    def create_feedback(self, run_id: str, payload: dict[str, Any],
                        actor: str) -> dict[str, Any]:
        run = self._repo.get_run(run_id, actor)
        if run is None:
            raise Text2SqlNotFound('查询记录不存在')
        fields = models.parse_feedback_create(payload)
        row = self._repo.create_feedback(
            run_id=run_id, datasource_id=str(run['datasource_id']),
            actor_id=actor, **fields)
        return models.feedback_to_api({**row, 'run_id': run_id})

    def list_feedback(self, datasource_id: str) -> dict[str, Any]:
        items = [models.feedback_to_api(row)
                 for row in self._repo.list_feedback(datasource_id)]
        return {'items': items, 'total': len(items)}

    def get_workspace(self, actor: str) -> dict[str, Any]:
        row = self._repo.get_workspace(actor)
        return models.workspace_to_api(row) if row else {
            'datasourceId': None, 'questionDraft': '', 'sqlDraft': '',
            'preferences': {}, 'updatedAt': None}

    def save_workspace(self, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        fields = models.parse_workspace_update(payload)
        self._repo.save_workspace(actor, **fields)
        return self.get_workspace(actor)

    def _external_connection(self, context: dict[str, Any]) -> dict[str, Any]:
        try:
            return {
                'host': context['host'],
                'port': context['port'],
                'database': context['database_name'],
                'username': context['username'],
                'password': decrypt_password(context['credential_ref']),
                'include_schemas': list(context.get('include_schemas') or ['public']),
            }
        except Exception as error:                                 # noqa: BLE001
            raise Text2SqlUpstreamError(
                f'读取数据源凭据失败：{_safe_error(error)}') from error


# ---------------------------------------------------------------------------
# 默认依赖
# ---------------------------------------------------------------------------
def _default_rerank_model() -> Optional[str]:
    """注册表里启用中的重排模型；没配就返回 ``None``（检索跳过重排）。"""
    try:
        from model.resolver import resolve

        endpoint = resolve('rerank')
    except Exception:                                      # noqa: BLE001
        return None
    return endpoint.api_model or None


def _embed_question(question: str, model: Optional[str]) -> list[float]:
    from model.gateway import embed_query

    try:
        return embed_query(question, model)
    except Exception as error:                                     # noqa: BLE001
        raise Text2SqlUpstreamError(f'问题向量化失败：{_safe_error(error)}') from error


def _value_hints(snapshot: dict[str, Any],
                 question: str) -> list[dict[str, Any]]:
    """把问题里的口语说法映射到快照里的存储值（「西安」→「西安市」）。

    只使用文本枚举：数值型 rawValue（状态码等）只认业务名称，避免把
    「支付」这类通用词误判成状态值；问题里已经出现存储值时不再提示。
    """
    text = (question or '').strip()
    if not text:
        return []
    columns = {
        str(column.get('id')): (f"{table.get('schema')}.{table.get('name')}."
                                f"{column.get('name')}")
        for table in snapshot.get('tables') or []
        for column in table.get('columns') or []
    }
    hints: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in snapshot.get('values') or []:
        raw = str(value.get('rawValue') or '').strip()
        if not raw:
            continue
        numeric = raw.isdigit()
        if numeric:
            names = [str(value.get('businessName') or '')]
        else:
            if raw in text:
                continue
            names = [str(value.get('businessName') or '')]
            names += [str(alias) for alias in value.get('aliases') or []]
        names = [name for name in names if name and not name.isdigit()
                 and len(name) >= 2]
        matched = next((name for name in sorted(names, key=len, reverse=True)
                        if name in text), None)
        if matched is None or matched == raw:
            continue
        key = (str(value.get('columnId')), raw)
        if key in seen:
            continue
        seen.add(key)
        hints.append({
            'matched': matched,
            'value': raw,
            'column': columns.get(str(value.get('columnId')), ''),
        })
    return hints


def _generate_sql(*, question: str, snapshot: dict[str, Any],
                  schema_context: str, date_policy: str,
                  resolved_time_range: dict[str, Any], reference_date: str,
                  model: Optional[str],
                  value_hints: Optional[list[dict[str, Any]]] = None,
                  feedback: str = '') -> dict[str, Any]:
    from model.operator_client import invoke_llm
    from model.resolver import resolve

    try:
        target = resolve('llm', model)
    except Exception as error:                                     # noqa: BLE001
        raise QueryFailure('LLM_NOT_CONFIGURED', f'无法解析生成模型：{_safe_error(error)}',
                           'llm', 'SQL Generation Error') from error
    endpoint = {
        'url': target.url,
        'model': target.api_model,
        'api_key': target.api_key,
        'thinking_payload': target.thinking_payload,
        'timeout': target.timeout,
    }
    system = (
        '你是 PostgreSQL 数据分析师。只输出一个 JSON 对象，不要 Markdown，不要解释'
        ' JSON 之外的内容。JSON 字段：sql（字符串，单条只读 SELECT/WITH 查询）、'
        ' explanation（字符串，中文说明口径）、tables_used（字符串数组）、'
        ' confidence（0 到 1）。禁止写入、DDL、事务控制、系统表与多语句。'
        ' 只能使用给定 Schema 中的表和字段；字段名必须带表别名或表名。'
        ' 问题没有限定时间范围时不要自行添加时间过滤条件（不要默认今天/本月）；'
        ' 指标定义里标为 NON_ADDITIVE 的（如去重人数）不可跨期相加，'
        '按同一粒度直接取值，或改用可加指标。'
    )
    hint_text = ''
    if value_hints:
        hint_lines = ['值匹配（用户说法 → 数据库存储值，生成 SQL 时必须使用存储值）：']
        hint_lines += [f"- {hint['matched']} → '{hint['value']}'（{hint['column']}）"
                       for hint in value_hints]
        hint_text = '\n'.join(hint_lines) + '\n'
    user = (
        f'业务问题：{question}\n'
        f'参考日期：{reference_date}\n'
        f'日期策略：{date_policy}；时间范围：{json.dumps(resolved_time_range, ensure_ascii=False)}\n'
        '请使用显式日期字面量（不要依赖数据库 CURRENT_DATE 的时区）。\n\n'
        f'Schema 上下文：\n{schema_context}\n'
        f'{hint_text}'
    )
    if feedback:
        user += f'\n{feedback}\n'
    try:
        content, usage = invoke_llm(
            [{'role': 'system', 'content': system},
             {'role': 'user', 'content': user}],
            model=target.api_model, temperature=0.0, endpoint=endpoint,
            with_usage=True)
    except Exception as error:                                     # noqa: BLE001
        raise QueryFailure('LLM_GENERATE_FAILED',
                           f'模型生成失败：{_safe_error(error)}',
                           'llm', 'SQL Generation Error') from error
    return {**sql_guard.extract_generated(content), 'usage': usage}


# ---------------------------------------------------------------------------
# 响应拼装
# ---------------------------------------------------------------------------
def _response(*, request: dict[str, Any], context: dict[str, Any],
              run: dict[str, Any], reference_date: str,
              timing: dict[str, int], retrieval: dict[str, Any],
              generated: dict[str, Any], final_sql: str,
              validation: dict[str, Any],
              executed: Optional[dict[str, Any]],
              error: Optional[dict[str, Any]],
              stages_override: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    result = None
    if executed is not None:
        result = {'columns': executed['columns'], 'rows': executed['rows'],
                  'row_count': executed['row_count'],
                  'truncated': executed['truncated'],
                  'byte_truncated': executed.get('byte_truncated', False)}
    return {
        'demo': False,
        'reference_date': reference_date,
        'id': str(run['id']),
        'run_id': str(run['id']),
        'request_id': str(run['request_id']),
        'createdAt': datetime.now().isoformat(timespec='seconds'),
        'datasource_id': str(context['id']),
        'datasource_name': context.get('name') or '',
        'question': request['question'],
        'scenario': 'auto',
        'retrieval': retrieval,
        'explanation': {'text': generated.get('explanation') or ''},
        'sql': {'generated': generated.get('sql') or '',
                'final': final_sql},
        'validation': validation,
        'explain': (executed or {}).get('explain'),
        'result': result,
        'error': error,
        'timing': timing,
        'usage': generated.get('usage') or {},
        'stages': stages_override or _stages(timing, None),
    }


def _stages(timing: dict[str, int],
            error_stage: Optional[str]) -> list[dict[str, Any]]:
    error_index = next((index for index, (stage, _, _) in enumerate(STAGE_DEFS)
                        if stage == error_stage), None)
    stages = []
    for index, (stage, label, name) in enumerate(STAGE_DEFS):
        if error_index is not None and index > error_index:
            status = 'skipped'
        elif error_index is not None and index == error_index:
            status = 'error'
        else:
            status = 'success'
        stages.append({
            'id': stage, 'label': label, 'name': name,
            'ms': int(timing.get(f'{stage}_ms') or 0),
            'status': status,
        })
    return stages


def _context_snapshot(result: context_builder.ContextResult) -> dict[str, Any]:
    """落库用的上下文快照：原文 + 取表/省略/回退，用于事后回放。"""
    return {
        'text': result.text,
        'hash': hashlib.sha256(result.text.encode('utf-8')).hexdigest(),
        'tables': result.tables,
        'omitted': result.omitted_tables,
        'fallback': result.fallback,
        'truncated': result.truncated,
    }


def _context_view(result: context_builder.ContextResult) -> dict[str, Any]:
    """把「这次到底给了模型哪些表」写进检索快照，便于回放与排查。"""
    return {
        'tables': result.tables,
        'omitted': result.omitted_tables,
        'relationTables': result.relation_tables,
        'fallback': result.fallback,
        'truncated': result.truncated,
        'chars': len(result.text),
    }


def _retrieval_view(snapshot: dict[str, Any],
                    hits: list[dict[str, Any]]) -> dict[str, Any]:
    tables_by_id = {str(table['id']): table for table in snapshot.get('tables') or []}
    columns_by_id = {str(column['id']): (table, column)
                     for table in snapshot.get('tables') or []
                     for column in table.get('columns') or []}
    values_by_id = {str(value['id']): value for value in snapshot.get('values') or []}
    foreign_columns = set()
    for relation in snapshot.get('relations') or []:
        for pair in relation.get('columnPairs') or []:
            foreign_columns.add(str(pair.get('sourceColumnId')))
            foreign_columns.add(str(pair.get('targetColumnId')))

    tables: dict[str, dict[str, Any]] = {}
    columns: dict[str, dict[str, Any]] = {}
    values: dict[str, dict[str, Any]] = {}
    for hit in hits:
        score = round(float(hit.get('score') or 0), 4)
        object_type = hit.get('object_type')
        key = str(hit.get('object_key') or '')
        if object_type == 'TABLE' and key in tables_by_id:
            table = tables_by_id[key]
            tables[key] = _table_hit(table, score, 'retrieval')
        elif object_type == 'COLUMN' and key in columns_by_id:
            table, column = columns_by_id[key]
            columns[key] = _column_hit(table, column, foreign_columns, score)
            tables.setdefault(str(table['id']),
                              _table_hit(table, None, 'relation'))
        elif object_type == 'VALUE' and key in values_by_id:
            value = values_by_id[key]
            column_pair = columns_by_id.get(str(value.get('columnId')))
            if column_pair:
                table, column = column_pair
                values[key] = {
                    'table': table['name'], 'column': column['name'],
                    'value': value.get('rawValue'),
                    'label': value.get('businessName') or value.get('rawValue'),
                    'score': score,
                }
                tables.setdefault(str(table['id']),
                                  _table_hit(table, None, 'relation'))

    table_names = {key: table['name'] for key, table in tables_by_id.items()}
    relations = []
    for relation in snapshot.get('relations') or []:
        source_id = str(relation.get('sourceTableId'))
        target_id = str(relation.get('targetTableId'))
        if source_id not in tables or target_id not in tables:
            continue
        pair = (relation.get('columnPairs') or [{}])[0]
        source_column = columns_by_id.get(str(pair.get('sourceColumnId')))
        target_column = columns_by_id.get(str(pair.get('targetColumnId')))
        relations.append({
            'from_table': table_names.get(source_id, ''),
            'from_column': source_column[1]['name'] if source_column else '',
            'to_table': table_names.get(target_id, ''),
            'to_column': target_column[1]['name'] if target_column else '',
            'name': relation.get('name'),
        })

    if not tables:
        for table in (snapshot.get('tables') or [])[:12]:
            tables[str(table['id'])] = _table_hit(table, None, 'scope')
    return {
        'tables': list(tables.values()),
        'columns': list(columns.values()),
        'values': list(values.values()),
        'relations': relations,
    }


def _table_hit(table: dict[str, Any], score: Optional[float],
               source: str) -> dict[str, Any]:
    return {
        'name': table.get('name'),
        'fullName': f"{table.get('schema')}.{table.get('name')}",
        'description': (table.get('businessDescription') or table.get('dbComment')
                        or table.get('businessName') or ''),
        'score': score,
        'source': source,
    }


def _column_hit(table: dict[str, Any], column: dict[str, Any],
                foreign_columns: set[str], score: float) -> dict[str, Any]:
    return {
        'table': table.get('name'),
        'name': column.get('name'),
        'type': column.get('dataType'),
        'description': (column.get('businessDescription') or column.get('dbComment')
                        or column.get('businessName') or ''),
        'primaryKey': bool(column.get('primaryKey')),
        'foreignKey': str(column.get('id')) in foreign_columns,
        'score': score,
    }


def _validation_view(sql: str, executed: dict[str, Any],
                     policy: dict[str, Any]) -> dict[str, Any]:
    max_rows = int(policy.get('max_rows') or 1000)
    max_bytes = int(policy.get('max_bytes') or 1024 * 1024)
    warnings: list[str] = []
    if executed.get('byte_truncated'):
        warnings.append(
            f'结果超过 {max_bytes // 1024} KB，已按字节上限截断；请减少查询列或加聚合')
    elif executed.get('truncated'):
        warnings.append(f'结果超过 {max_rows} 行，已截断')
    return {
        'valid': True,
        'checks': [
            {'label': '单条 SELECT', 'detail': '拒绝写入、DDL 与多语句', 'valid': True},
            {'label': 'Schema 白名单', 'detail': '表与字段来自当前发布版本', 'valid': True},
            {'label': 'LIMIT Guard', 'detail': f'最多返回 {max_rows} 行', 'valid': True},
            {'label': '字节 Guard', 'detail': f'最多返回 {max_bytes // 1024} KB', 'valid': True},
            {'label': '只读连接', 'detail': '只读事务 + statement_timeout', 'valid': True},
        ],
        'warnings': warnings,
    }


def _run_to_api(row: dict[str, Any]) -> dict[str, Any]:
    error = None
    if row.get('error_code'):
        error = {'code': row.get('error_code'),
                 'message': row.get('error_message') or '',
                 'stage': row.get('error_stage') or 'execute',
                 'category': 'Query Error'}
    retrieved = row.get('retrieval_snapshot') or {}
    return {
        'id': str(row.get('id')),
        'run_id': str(row.get('id')),
        'request_id': row.get('request_id'),
        'datasource_id': str(row.get('datasource_id')),
        'datasource_name': row.get('datasource_name') or '',
        'question': row.get('question') or '',
        'createdAt': row.get('created_at_text') or row.get('created_at'),
        'status': (row.get('status') or '').lower(),
        'retrieval': retrieved,
        'explanation': row.get('explanation_snapshot') or {},
        'sql': {'generated': row.get('generated_sql') or '',
                'final': row.get('final_sql') or ''},
        'validation': row.get('validation_snapshot') or {},
        'explain': row.get('explain_snapshot'),
        'result': row.get('result_snapshot'),
        'error': error,
        'timing': row.get('timing') or {},
        'usage': row.get('usage') or None,
        'stages': row.get('stages') or [],
        'datePolicy': row.get('date_policy') or 'relative',
    }


def _resolved_time_range(request: dict[str, Any], reference_date: str,
                         timezone: str) -> dict[str, Any]:
    if request['date_policy'] == 'fixed':
        return {
            'policy': 'fixed',
            'referenceDate': reference_date,
            'timezone': timezone,
            'range': request.get('fixed_time_range') or {},
        }
    return {
        'policy': request['date_policy'],
        'referenceDate': reference_date,
        'timezone': timezone,
    }


def _stage_emitter(
        callback: Optional[Callable[[str, str, Optional[int]], None]]
) -> Callable[[str, str, Optional[int]], None]:
    """把阶段回调包成「永不让查询失败」的上报函数。"""
    if callback is None:
        return lambda stage, status, ms=None: None

    def emit(stage: str, status: str, ms: Optional[int] = None) -> None:
        try:
            callback(stage, status, ms)
        except Exception:                                  # noqa: BLE001
            log.warning('text_to_sql stage callback failed at %s/%s',
                        stage, status, exc_info=True)

    return emit


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _safe_error(error: BaseException) -> str:
    text = str(error).strip().splitlines()[0] if str(error).strip() else error.__class__.__name__
    return text[:500]


_query_service: Optional[Text2SqlQueryService] = None


def get_query_service() -> Text2SqlQueryService:
    global _query_service
    if _query_service is None:
        _query_service = Text2SqlQueryService()
    return _query_service
