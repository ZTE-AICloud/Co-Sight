"""v2 抽图的异步执行（``AsyncGraphExtractServiceV2`` 的进度机与接线）。

    调抽图算子 → entities/edges/schema.json → 打包 → 导入引擎 → 收尾状态

## 状态机（两处的进度值**不一样**）

| 步骤 | ``graph_extract_task`` | ``kb_kbase`` |
|---|---|---|
| 开始 | RUNNING / 10 | PARSING(1) / 10，清空 failReason |
| 落临时目录检查通过 | RUNNING / 30 | — |
| 调算子前 | RUNNING / 50 | — |
| 算子失败 | 不动 | GENERATING_FAIL(103) / 100，**直接 return** |
| 打包完 | RUNNING / 70 | STORING(4) / **10（更新是 20）** |
| 导入前 | RUNNING / 90 | — |
| 导入后 | — | 更新时再写 STORING / 90 |
| 全部成功 | SUCCESS / 100 | 等导入终态 → PENDING(5) / 0 |

## 导入之后的向量化

``graph_import_engine.import_from_zip`` 在写图库后同步调用
``graph_index_store.build_index``：实体/边 → ``graph_<uuid>_vector``；zip 里有
``document_chunk.jsonl`` 时同时写 ``graph_<uuid>_chunk`` + chunk 向量。
也就是说实体/边与 chunk 的向量化随导入链路生效。

**文档级向量不写入**：抽取算子只产
entities/edges/schema，不产 ``document_chunk.jsonl``，所以抽图路径没有 chunk
行/向量可写 —— 但**不要把它误报成「实体/边没向量化」**。
``_skip_vector_stages`` 只记录这一点。

## ``updateKbaseStatusRetry`` 那条轮询

导入引擎是**同步**的、返回时任务必为终态，所以这里跑一遍即可得到同样的终态，
不需要无上限循环等待。
"""

from __future__ import annotations

import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from graph.service import graph_extract_api, graph_import_engine
from graph.repository import graph_extract_store, graph_import_store
from knowledge_base.service import kbase_service as kbase_store
from infrastructure.logging.logutil import log

# ``AsyncConfig`` 的 ``GraphExtractExecuteThread``：core 3 / max 5 / queue 100 / CallerRuns
_EXECUTOR = ThreadPoolExecutor(max_workers=5, thread_name_prefix='graph_extract_v2')

# ``KbaseStatusEnum`` 的 code
STATUS_PARSING = 1
STATUS_PARSING_FAIL = 101
STATUS_GENERATING_FAIL = 103
STATUS_STORING = 4
STATUS_STORING_FAIL = 104
STATUS_PENDING = 5

FAIL_REASON_SPLIT = ('切分失败：临时目录为空',
                     'Splitting failed: Temporary directory path is null.')
FAIL_REASON_STORE = ('入库失败：图实体或者边属性向量化入库异常',
                     'Storing failed: Abnormality in vectorizing and storing '
                     'entity or edge attribute data.')
# 算子阶段（解析/切分/LLM 抽取）失败要置 FAIL 并写 failReason；
# 只置 status=103 就 return，列表上只看得到“生成失败”却没有任何原因。
FAIL_REASON_GENERATE = ('生成图谱失败：算子执行异常',
                        'Failed to generate the graph: Operator execution exception.')


def submit_extract(task_id: str, tmp_dir: str, dto: dict, schema_obj: Optional[dict],
                   emp_no: str, org_id: Optional[str]) -> None:
    """建库那条的异步。"""
    _submit(lambda: _run(task_id, tmp_dir, dto, schema_obj, is_update=False))


def submit_update(task_id: str, tmp_dir: str, dto: dict, schema_id: Optional[str],
                  schema_obj: Optional[dict], emp_no: str,
                  org_id: Optional[str]) -> None:
    """更新那条的异步：schema 用库里已有的那份（``cacheSchemaId``/``cacheSchemaObj``）。"""
    _submit(lambda: _run(task_id, tmp_dir, dto, schema_obj, is_update=True,
                         cache_schema_id=schema_id))


def _submit(run) -> None:
    try:
        _EXECUTOR.submit(run)
    except Exception:                                              # noqa: BLE001
        log.warning('graph extract v2 pool rejected the task; running inline')
        run()


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------


def _run(task_id: str, tmp_dir: str, dto: dict, schema_obj: Optional[dict],
         is_update: bool, cache_schema_id: Optional[str] = None) -> None:
    kb_id = dto.get('kbId')
    try:
        graph_extract_store.update_task_status(
            task_id, graph_extract_store.STATUS_RUNNING, 10)
        kbase_store.update_process(kb_id, STATUS_PARSING, 10)
        kbase_store.update_fail_reason(kb_id, '', '')

        if not tmp_dir or not tmp_dir.strip():
            kbase_store.update_process(kb_id, STATUS_PARSING_FAIL, 100)
            kbase_store.update_fail_reason(kb_id, *FAIL_REASON_SPLIT)
            raise ValueError('Temporary directory path is null or empty')

        graph_extract_store.update_task_status(
            task_id, graph_extract_store.STATUS_RUNNING, 30)

        # ``schemaObj`` 注入 args —— **只给专业算子**：通用算子（-6）的
        # ``graph_extract`` 签名里没有 ``schema`` 形参，塞了直接 TypeError。
        # 不能只判 schemaObj / schemaId（「带 schemaId ⟺ 专业算子」的假设不成立），
        # 还要按算子维度判断，见 ``graph_extract_api.operator_consumes_schema``。
        args = list(dto.get('args') or [])
        schema_id = dto.get('schemaId')
        if (schema_obj is not None and schema_id and str(schema_id).strip()
                and graph_extract_api.operator_consumes_schema(dto.get('operatorId'))):
            args.append({'argName': 'schema', 'argType': 'object',
                         'defaultValue': schema_obj,
                         'description': 'Graph schema configuration'})

        # ``txId`` 是**当前事务 id**；RKB 没有那套事务日志，用一个新的 hex 顶上
        kwargs = dict(dto.get('kwargs') or {})
        kwargs['txId'] = uuid.uuid4().hex
        args.append({'argName': 'kwargs', 'argType': 'object', 'defaultValue': kwargs,
                     'description': 'Additional keyword arguments'})
        dto['args'] = args
        dto['kwargs'] = kwargs

        graph_extract_store.update_task_status(
            task_id, graph_extract_store.STATUS_RUNNING, 50)

        try:
            produced = _call_operator(dto, tmp_dir, schema_id)
        except Exception as error:                                  # noqa: BLE001
            log.exception('graph extract task %s: operator stage failed, kbId=%s',
                          task_id, kb_id)
            # 任务行也要落 FAIL；只改库状态就 return，任务行会永远停在
            # RUNNING/50（查询/排障时看不出已经结束）。
            graph_extract_store.update_task_status(
                task_id, graph_extract_store.STATUS_FAIL, 0, str(error))
            kbase_store.update_process(kb_id, STATUS_GENERATING_FAIL, 100)
            kbase_store.update_fail_reason(kb_id, *FAIL_REASON_GENERATE)
            return

        kbase_store.update_process(kb_id, STATUS_STORING, 10 if not is_update else 20)
        kbase_store.update_fail_reason(kb_id, '', '')
        graph_extract_store.update_task_status(
            task_id, graph_extract_store.STATUS_RUNNING, 70)

        zip_path = graph_extract_api.zip_outputs(tmp_dir, produced)
        graph_extract_store.update_task_status(
            task_id, graph_extract_store.STATUS_RUNNING, 90)

        actual_schema_id, schema_obj = _resolve_schema(
            task_id, dto, schema_obj, produced, cache_schema_id)
        kbase_store.update_schema(kb_id, actual_schema_id, schema_obj)

        try:
            import_task_id = graph_import_engine.import_from_zip(
                f'{graph_import_store.KB_ID_PREFIX}{kb_id}', actual_schema_id, zip_path,
                kbase_schema_obj=schema_obj)
        except Exception:                                          # noqa: BLE001
            log.exception('graph extract task %s: import stage failed, kbId=%s',
                          task_id, kb_id)
            kbase_store.update_process(kb_id, STATUS_STORING_FAIL, 100)
            return

        if is_update:
            kbase_store.update_process(kb_id, STATUS_STORING, 90)

        _skip_vector_stages(kb_id, is_update)

        graph_extract_store.update_task_status(
            task_id, graph_extract_store.STATUS_SUCCESS, 100)
        _settle_kbase_status(import_task_id, kb_id)
        log.info('graph extract task %s completed, kbId=%s', task_id, kb_id)

    except Exception as error:                                     # noqa: BLE001
        log.exception('graph extract task %s failed, kbId=%s', task_id, kb_id)
        graph_extract_store.update_task_status(
            task_id, graph_extract_store.STATUS_FAIL, 0, str(error))
        kbase_store.update_process(kb_id, STATUS_STORING_FAIL, 100)
        kbase_store.update_fail_reason(kb_id, *FAIL_REASON_STORE)
    finally:
        if tmp_dir:
            shutil.rmtree(os.path.dirname(tmp_dir), ignore_errors=True)


def _call_operator(dto: dict, tmp_dir: str, schema_id) -> list[dict]:
    """整目录一次调算子，收产出。

    ``tmp_dir`` 是 ``save_tmp_files`` 返回的**临时目录** ``<uuid>/input``，直接当
    ``diskFileKey`` —— 见 ``graph_extract_api`` 模块头的「路径契约」。
    """
    from operators.service import operator_service

    operator_id = dto.get('operatorId')
    python_path = operator_service.operator_python_path(operator_id)
    if not python_path:
        raise RuntimeError(f'算子不存在，算子ID：{operator_id}')

    result = graph_extract_api.call_operator(dto, operator_id, python_path, tmp_dir,
                                             schema_id)
    if str((result or {}).get('code')) != '0':
        raise RuntimeError(f'图提取失败: {(result or {}).get("message")}')
    return [graph_extract_api.read_outputs(tmp_dir)]


# 兜底 schema id，**必须保持这个拼写**
DEFAULT_SCHEMA_ID = 'General_schema'


def _resolve_schema(task_id: str, dto: dict, schema_obj: Optional[dict],
                    produced: list[dict], cache_schema_id: Optional[str]
                    ) -> tuple[str, Optional[dict]]:
    """没带 schema 的（通用图谱）要从算子产出的 ``schema.json`` 导入。

    ⚠️ 这条路上读的键是 **``schema_id``**（下划线），拿不到就用字面量
    ``"General_schema"``；``schema.json`` 整个找不到时**抛异常**（不是返回 null），
    最终把任务判失败 —— 这里同样抛。
    """
    actual = dto.get('schemaId') or ''
    if schema_obj is None:
        schema_obj = _produced_schema(produced)
        if schema_obj is None:
            raise RuntimeError(f'Schema file not found: {tmp_schema_hint(dto)}')
        actual = _extract_schema_id(schema_obj)
        dto['schemaId'] = actual
        graph_extract_store.update_task_schema_id(task_id, actual)
    if not actual:
        actual = cache_schema_id or ''
    if schema_obj is not None and actual:
        _align_schema_id(schema_obj, actual)
    return actual, schema_obj


def tmp_schema_hint(dto: dict) -> str:
    """错误提示里报的路径是 ``<parentDir>/schema.json``。"""
    return f'<tmp>/{dto.get("kbId")}/schema.json'


def _extract_schema_id(schema_obj: dict) -> str:
    value = schema_obj.get('schema_id')
    if value is None or str(value) == '':
        log.warning('no schema_id in the produced schema.json, falling back to %s',
                    DEFAULT_SCHEMA_ID)
        return DEFAULT_SCHEMA_ID
    return str(value)


def _produced_schema(produced: list[dict]) -> Optional[dict]:
    for item in produced:
        if item.get('schema'):
            return item['schema']
    return None


def _align_schema_id(schema_obj: dict, schema_id: str) -> None:
    """``GraphSchemaObjMapUtil.alignSchemaIdInMap``：把 map 里的 schemaId 对齐成实际的。"""
    if not isinstance(schema_obj, dict):
        return
    for key in ('schemaId', 'schema_id'):
        if key in schema_obj and schema_obj[key] != schema_id:
            schema_obj[key] = schema_id


def _skip_vector_stages(kb_id: str, is_update: bool) -> None:
    """记录**文档级向量未写入**这一阶段（实体/边向量已由导入引擎写入）。

    不能在同一句里塞「entity/edge embedding ... are NOT written」——
    与 ``import_from_zip → build_index`` 的实际行为相反，排查时会把
    人直接引向错误方向。真正缺口只有抽取路径没有的 ``document_chunk.jsonl``
    以及文档级向量（``saveDocumentVectorData``）。
    """
    log.info('graph extract (update=%s) kbId=%s: entities/edges are vectorized by the '
             'import engine; document-level vectors are not written by this path '
             '(no document_chunk.jsonl from the extract operator). See '
             'import engine; document-level vectors are not written by this path', is_update, kb_id)


def _settle_kbase_status(import_task_id: str, kb_id: str) -> None:
    """``updateKbaseStatus``：按导入任务的终态把库置成待发布 / 入库失败。"""
    row = graph_import_store.select_task(import_task_id)
    status = (row or {}).get('status')
    if status in ('COMPLETED', 'COMPLETED_WITH_ERRORS'):
        kbase_store.update_process_with_time(kb_id, STATUS_PENDING, 0)
        kbase_store.update_fail_reason(kb_id, '', '')
        return
    if status == 'FAILED':
        error = (row or {}).get('error_message') or ''
        kbase_store.update_process_with_time(kb_id, STATUS_STORING_FAIL, 0)
        kbase_store.update_fail_reason(
            kb_id, '知识图谱入库失败，详情：' + error, 'Knowledge graph storage failed. Details：' + error)
        return
    # 导入是同步的、返回时必为终态，走到这里说明任务行被人动过 —— 记一笔就够了
    log.warning('graph import task %s is not in a terminal state (%s)', import_task_id, status)
