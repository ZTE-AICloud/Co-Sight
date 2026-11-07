"""v2 抽图端点：``POST /graph/extract`` 与 ``POST /graph/extract/{kbId}``。

## 与 v1（``/graph/extract``）的三条实质差别

1. **v2 自己先建库**：v1 要求前端先建好库再把 ``kbId`` 传进来；v2 是「给个名字 +
   文件」，服务端建库（复用 ``createKbase``，返回窄 VO）→ 落文件 → 建任务。
2. **校验阶梯另成一套**：名字/描述/props/算子/embedding 模型/kwargs 六项，
   **全是 0004**。同一个「schemaId 查不到」，v2 在这条路上回 0004
   （``validateSchemaId`` 先拦），而 v1 控制器那条是 0001 —— 别统一。
3. **返回 ``KbaseVO``**（v1 返回任务 DTO）；更新那条返回 ``bo=null``。

## 顺序（每步的位置都有理由）

    解析 data → validateGraphExtractRequest → validateSchemaId
      → **fileUploadCheck（在建库之前！）** → createKbase → saveFile
      → try { createGraphExtractTask } catch { 0005 生成图谱失败 }

``fileUploadCheck`` 必须在建库前（避免校验失败时已创建知识库记录）——
挪到后面会在校验失败时留下一个空库。

更新那条的顺序不同：先 ``validateGraphExtractRequest``（**没有** validateSchemaId）
→ 查库存在（不存在 → 0005）→ ``updateKbase`` → 删旧文件 → 落新文件
  → ``localFiles + files`` → ``createUpdateGraphExtractTask``。
"""

from __future__ import annotations

import os
from typing import Any, Optional

from infrastructure.http import binding
from shared.errors.api import KbApiError
from graph.service import graph_common, graph_extract_api, graph_extract_v2_service
from graph.service import lifecycle as graph_lifecycle
from knowledge_base.service import directory_service, file_service, kbase_v2_service
from graph.repository import graph_extract_store, graph_schema_store
from knowledge_base.service import kbase_service as kbase_store
from knowledge_base.service.file_service import UploadedFile
from infrastructure.logging.logutil import log

# 名称校验正则（``\w`` = ``[a-zA-Z0-9_]``）
import re

NAME_PATTERN = re.compile(r'[\w一-龥.\-\s]{2,30}')

# ``KbCategoryEnum.KNOWLEDGE_GRAPH``
CATEGORY_KNOWLEDGE_GRAPH = 10
GRAPH_LIMIT_TYPE = 'graph-document'

DESCRIPTION_MAX = 1000
CHUNK_SIZE_MIN, CHUNK_SIZE_MAX = 512, 10240
OVERLAP_MIN, OVERLAP_MAX = 0, 5120

# 默认文件夹名：请求语言是 zh-CN 才用中文（**精确等于** zh-CN，不是前缀匹配）
DIR_TITLE_ZH = '默认文件夹'
DIR_TITLE_EN = 'Default'

# 两个文件名/字段名
CREATE_FILE_FIELD = 'file'
UPDATE_FILE_FIELD = 'files'

# props 的字段默认值（建库拿的是**绑定后**的对象）
PROPS_FIELDS = {'embeddingModel': binding.STRING,
                'metricType': binding.STRING,
                'splitMethod': binding.STRING,
                'regex': binding.STRING}

# 请求体字段与类型
EXTRACT_V2_FIELDS = {
    'operatorId': binding.INTEGER,          # 整数
    'args': binding.LIST_OF_OBJECTS,
    'pythonPath': binding.STRING,
    'fileFormat': binding.STRING,
    'name': binding.STRING,
    'description': binding.STRING,
    'kbtype': binding.STRING,
    'props': binding.MAP,
    'category': binding.INTEGER,            # DTO 默认值 1
    'regexList': binding.LIST_OF_STRINGS,
    'diskFileKey': binding.STRING,
    'kbId': binding.STRING,
    'schemaId': binding.STRING,
    'coverFlag': binding.BOOLEAN,           # DTO 默认值 false
    'kwargs': binding.MAP,
}


def _default_embedding_model() -> str:
    """``SystemConstantConfig.DEFAULT_EMBEDDING_MODEL``（``embedding.model.default``）。"""
    return (os.environ.get('EMBEDDING_MODEL_NAME') or '').strip() or 'Qwen3-Embedding-0.6B'


# ----------------------------------------------------------------------
# 两个端点
# ----------------------------------------------------------------------


def extract_graph(files: list[UploadedFile], data_json: str, language: str,
                  emp_no: str, org_id: Optional[str]) -> dict:
    """``POST /graph/extract``。返回**窄 ``KbaseVO``**（新库）。"""
    dto = parse_dto(data_json)
    validate_graph_extract_request(dto)
    _validate_schema_id(dto.get('schemaId'), dto.get('operatorId'))
    # ⚠️ 在**建库之前**（避免校验失败时已创建知识库记录）
    file_service.upload_check(files, GRAPH_LIMIT_TYPE)

    kbase_vo = kbase_v2_service.create_kbase(_kbase_payload(dto), emp_no, org_id)
    dto['kbId'] = kbase_vo['id']
    save_files(dto, files, _dir_title(language), emp_no)

    try:
        create_extract_task(dto, files, emp_no, org_id)
    except KbApiError:
        raise
    except Exception as error:                                     # noqa: BLE001
        log.exception('failed to create graph extraction task')
        raise _generate_failed() from error
    return kbase_vo


def update_graph(kb_id: str, files: list[UploadedFile], data_json: str,
                 delete_files_json: str, local_files_json: str, language: str,
                 emp_no: str, org_id: Optional[str]) -> None:
    """``POST /graph/extract/{kbId}``。返回 ``bo=null``。"""
    dto = parse_dto(data_json)
    dto['kbId'] = kb_id

    delete_files = parse_string_list(delete_files_json)
    local_files = parse_string_list(local_files_json)

    validate_graph_extract_request(dto)
    # ⚠️ **没有** validateSchemaId（只有创建那条有）—— 少了会让「模板不存在」
    #    在这条路上差一个错误码
    row = kbase_store.get_kbase_row(kb_id)
    if row is None:
        # 库不存在 → 0005（不是 0004）
        raise KbApiError('graph.extract.kbid.not.exist', kb_id)
    # 只有图谱库能重抽。抽图会往 ``kb_kbase.status`` 写 1/2/3/4/101…104，而文档库的
    # 库行状态恒为 0（文档处理进度记在 ``kb_directory`` 行上）；写进去之后重新解析
    # 文档也不会复原，列表/详情会一直显示「生成失败」。文案键与图谱导出共用同一条
    # （同一句「知识库不是图谱类型」+ 同一个 problem code），别再加一条重复文案。
    if str(row.get('category')) != str(CATEGORY_KNOWLEDGE_GRAPH):
        raise KbApiError('graph.export.kbase.not.graph')

    kbase_v2_service.update_kbase(kb_id, _kbase_payload(dto), org_id, emp_no)

    if delete_files:
        file_service.delete_files(kb_id, delete_files)
    if files:
        save_files(dto, files, _dir_title(language), emp_no)

    try:
        # ``localFiles`` 先、本次上传后 —— 抽图要拿整库重抽
        all_files = file_service.local_files(local_files, kb_id) + list(files)
        create_update_task(dto, all_files, row, emp_no, org_id)
    except KbApiError:
        raise
    except Exception as error:                                     # noqa: BLE001
        log.exception('failed to create graph update task')
        raise _generate_failed() from error


def _dir_title(language: str) -> str:
    """``"zh-CN".equals(language) ? "默认文件夹" : "Default"``。"""
    return DIR_TITLE_ZH if language == 'zh-CN' else DIR_TITLE_EN


def _generate_failed() -> KbApiError:
    """生成图谱失败（0005）。"""
    return KbApiError('Retcode.generate.graph.schema.fail')


def _kbase_payload(dto: dict) -> dict:
    """``createKbase``/``updateKbase`` 前那个 ``KbaseReqDTO``（四个字段，**没有 kbtype**）。"""
    return {'name': dto.get('name'), 'description': dto.get('description'),
            'category': dto.get('category'), 'props': dto.get('props')}


# ----------------------------------------------------------------------
# 入参解析
# ----------------------------------------------------------------------


def parse_dto(data_json: str) -> dict:
    """解析 ``data`` 里的 JSON 请求体。

    ⚠️ 两件容易漏的事：

    * 空串/非对象/字段类型对不上（``operatorId`` 给字符串 ``"abc"`` 这种）
      **全都**算解析失败 → 0004 ``graph.extract.json.parse.failed``；
    * ``PropsDTO`` 的字段有**默认值**，所以 ``props: {}`` 不是「空对象」而是
      ``embeddingModel = 默认模型``（它会被写进 ``kb_kbase.embedding_model``）。
    """
    import json

    try:
        parsed = json.loads(data_json)
    except ValueError as error:
        log.error('failed to parse graph extract dto: %s', error)
        raise _invalid('graph.extract.json.parse.failed')
    if not isinstance(parsed, dict):
        log.error('graph extract dto is not an object: %s', type(parsed).__name__)
        raise _invalid('graph.extract.json.parse.failed')

    try:
        dto = binding.bind(parsed, EXTRACT_V2_FIELDS)
    except (KbApiError, TypeError, ValueError) as error:
        log.error('graph extract dto binding failed: %s', error)
        raise _invalid('graph.extract.json.parse.failed')

    if isinstance(dto.get('props'), dict):
        try:
            props = binding.bind(dto['props'], PROPS_FIELDS)
        except (KbApiError, TypeError, ValueError) as error:
            log.error('graph extract dto props binding failed: %s', error)
            raise _invalid('graph.extract.json.parse.failed')
    else:
        props = {}
    # 字段默认值（构造出来就带着）
    props.setdefault('embeddingModel', _default_embedding_model())
    props.setdefault('metricType', 'Cosine')
    props.setdefault('splitMethod', 'comprehensiveSplitter')
    props.setdefault('regex', '\\n\\n')
    if dto.get('props') is not None:
        dto['props'] = props
    dto.setdefault('category', 1)
    dto.setdefault('coverFlag', False)
    return dto


def parse_string_list(raw: str) -> list[str]:
    """``parseStringList``：空/畸形都**吞掉当空表**（只 warn），不报错。"""
    import json

    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        log.warning('failed to parse JSON array: %s', raw)
        return []
    if not isinstance(parsed, list):
        log.warning('parsed JSON is not an array: %s', raw)
        return []
    return [item for item in parsed if isinstance(item, str)]


def _invalid(key: str, *args) -> KbApiError:
    """这一族几乎全是 **0004**。"""
    return KbApiError(key, *args, code='0004')


# ----------------------------------------------------------------------
# 校验阶梯（``GraphServiceImpl``）—— 全是 0004
# ----------------------------------------------------------------------


def validate_graph_extract_request(dto: dict) -> None:
    """``validateGraphExtractRequest``：库里那条 ``validateKbId`` / ``validateRunningTask``
    是**注释掉的**（两处 ``//``），别照着私有方法名去补。"""
    _validate_kbase(dto)
    _validate_operator_id(dto.get('operatorId'))
    _validate_embedding_model(dto.get('props'))
    _validate_kwargs(dto.get('kwargs'))


def _validate_kbase(dto: dict) -> None:
    name = dto.get('name')
    if name is None or not NAME_PATTERN.fullmatch(str(name)):
        raise _invalid('kbase.name.validation', '')
    if str(name).strip() == '':
        raise _invalid('kbase.name.not.all.whitespace', '')
    description = dto.get('description')
    if description is not None and len(str(description)) > DESCRIPTION_MAX:
        raise _invalid('description.validation', '')
    if dto.get('props') is None:
        # ⚠️ 0004，不是 0001：校验在建库之前拦下
        raise _invalid('kbase.prop.validation', '')


def _validate_operator_id(operator_id) -> None:
    """``validateOperatorId``：null → 空；字符串长度 > 10 → 超长；查不到 → 不存在。

    ⚠️ 与 v1 那条同名方法**不一样**：v1 的 null 是静默放行的。
    """
    if operator_id is None:
        raise _invalid('graph.extract.operatorid.empty')
    text = str(operator_id)
    if len(text) > graph_extract_api.OPERATOR_ID_MAX:
        raise _invalid('graph.extract.operatorid.length.exceed', len(text))
    from operators.service import operator_service

    if operator_service.get_operator_row(operator_id) is None:
        raise _invalid('graph.extract.operatorid.not.exist', operator_id)


def _validate_embedding_model(props: Optional[dict]) -> None:
    """``validateEmbeddingModel``：**查得到列表才校验**，查不到就放行。"""
    if not props:
        return
    model = props.get('embeddingModel')
    if not model or not str(model).strip():
        return
    try:
        # 与建库/建图共用同一条判据（注册表启用行 + .env 回落名，且必须带维度）；
        # 文案键别改 —— 这是对外契约。
        from knowledge_base.service.embedding_dimension import ensure_known_embedding_model

        ensure_known_embedding_model(
            str(model), error_key='graph.extract.embedding.model.invalid')
    except KbApiError:
        raise
    except Exception:                                              # noqa: BLE001
        log.warning('failed to validate embedding model, skip', exc_info=True)


def _validate_kwargs(kwargs: Optional[dict]) -> None:
    """``validateKwargs``：只认这三个键，其余一律不管。"""
    if not kwargs:
        return
    if 'llm' in kwargs:
        _validate_llm(kwargs.get('llm'))
    if 'chunkSize' in kwargs:
        _validate_range(kwargs.get('chunkSize'), 'chunkSize',
                        CHUNK_SIZE_MIN, CHUNK_SIZE_MAX,
                        'graph.extract.chunkSize.range.invalid')
    if 'overlap' in kwargs:
        _validate_range(kwargs.get('overlap'), 'overlap',
                        OVERLAP_MIN, OVERLAP_MAX,
                        'graph.extract.overlap.range.invalid')


def _validate_range(value: Any, label: str, low: int, high: int, key: str) -> None:
    """``validateChunkSize`` / ``validateOverlap`` 的公共部分。

    ⚠️ 解析失败时去取 **``RetCode.graph.extract.<label>.invalid``**，而这个键不存在
    —— 取文案这一步自己抛异常，最终是 **0001**（``chunkSize: "abc"`` 与
    ``{"a":1}`` 都回 0001）。这里刻意**不补**那两条文案，改成显式抛服务器错误。

    数字走 ``Number.intValue()``（``512.7`` → 512，能过），字符串走 ``parseInt``。
    """
    if value is None:
        return
    if isinstance(value, bool):
        text = 'true' if value else 'false'
    elif isinstance(value, (int, float)):
        text = str(int(value))
    else:
        text = str(value)
    try:
        number = int(text)
    except ValueError as error:
        # 取文案这一步自己抛（键不存在），最终是 **0001 + 通用文案**
        # （不是 MissingResource 原文）。
        log.error('no message for RetCode.graph.extract.%s.invalid; reporting 0001', label)
        raise KbApiError('server.error', code='0001') from error
    if number < low or number > high:
        raise _invalid(key, number)


def _validate_llm(llm) -> None:
    """``validateLlm``：拿 ``getLlmList()`` 比对；**取不到就放行**。

    模型列表来自部署配置，没有列表时默认**一律放行**（随便给个不存在的 llm
    也建库成功）。真环境若要恢复校验，设 ``KB_EXTRACT_LLM_LIST``（逗号分隔）即可。
    """
    if llm is None:
        return
    text = str(llm)
    if not text.strip():
        return
    raw = (os.environ.get('KB_EXTRACT_LLM_LIST') or '').strip()
    if not raw:
        log.warning('no LLM list available, skip LLM validation for %r', text)
        return
    allowed = [item.strip() for item in raw.split(',') if item.strip()]
    if text not in allowed:
        raise _invalid('graph.extract.llm.invalid', text)


def _validate_schema_id(schema_id, operator_id) -> None:
    """``validateSchemaId``：空串跳过；给了就查 ``graph_schema``，查不到 → 0004。

    ⚠️ 与 ``createGraphExtractTask`` 里那次查是**同一个原因、不同错误码**：
    控制器先跑到这里，所以 v2 这条路实测是 0004；v1 控制器没有这一步，回 0001。

    例外只有 ``General_Schema`` + 通用算子这条（见
    ``graph_extract_api.is_system_generated_schema_id``）：它不是模板行，schema 由
    算子产出的 ``schema.json`` 提供，不查表。
    """
    if schema_id is None or not str(schema_id).strip():
        log.info('schema id is empty, skipping validation')
        return
    if graph_extract_api.is_system_generated_schema_id(schema_id, operator_id):
        log.info('schemaId %s is the generic operator-produced id; '
                 'schema will come from the produced schema.json', schema_id)
        return
    row = graph_schema_store.get_schema_by_id(str(schema_id))
    obj = graph_common.schema_obj(row) if row else None
    if not obj:
        raise _invalid('graph.extract.schema.not.found', schema_id)


# ----------------------------------------------------------------------
# 落文件 / 建任务
# ----------------------------------------------------------------------


def save_files(dto: dict, files: list[UploadedFile], title: str, emp_no: str) -> None:
    """保存文件：默认文件夹 → 转上传。

    ⚠️ 空文件表在这里就**拦下**（→ 0005
    「文件(夹)不存在」）—— 所以「一个文件都没传」的更新请求会停在建任务之前。
    """
    if not files:
        raise KbApiError('file.not.exist')
    directory_id = directory_service.query_or_create_directory(dto.get('kbId'), title)
    metadata = {
        'kbaseId': dto.get('kbId'),
        'directoryId': directory_id,
        'category': CATEGORY_KNOWLEDGE_GRAPH,
        'splitType': 'system',
        'fileFrom': '1',
        'kType': GRAPH_LIMIT_TYPE,
        'coverFlag': bool(dto.get('coverFlag')),
    }
    # ⚠️ ``run_split_pipeline=False``：抽图建库没有算子链校验，也**不入队**
    # 文件任务（见 ``file_service._save_one``）；文件停在 ``FILE_UPLOAD_CLOUD_DISK``。
    file_service.upload_files(list(files), metadata, dto.get('kbId'), emp_no,
                              run_split_pipeline=False)


def create_extract_task(dto: dict, files: list[UploadedFile], emp_no: str,
                        org_id: Optional[str]) -> str:
    """``GraphServiceImpl.createGraphExtractTask``：落临时目录 → 任务行 → 起异步。"""
    tmp_dir = graph_extract_api.save_tmp_files(files)
    schema_id, schema_obj = _resolve_schema_for_task(dto.get('schemaId'),
                                                     dto.get('operatorId'))

    task_id = graph_extract_store.insert_task(
        kbase_id=dto.get('kbId'), schema_id=schema_id,
        operator_id=dto.get('operatorId'), file_count=len(files),
        created_by='system')                       # **写死 system**，不是当前用户

    kbase_store.update_operator_id(dto.get('operatorId'), dto.get('kbId'))
    kbase_store.update_schema(dto.get('kbId'), schema_id, schema_obj)
    graph_extract_v2_service.submit_extract(
        task_id, tmp_dir, dto, schema_obj, emp_no, org_id)
    return task_id


def create_update_task(dto: dict, files: list[UploadedFile], row: dict, emp_no: str,
                       org_id: Optional[str]) -> str:
    """``createUpdateGraphExtractTask``：schema 取**库里那份**，并先 drop 图谱库。"""
    tmp_dir = graph_extract_api.save_tmp_files(files)

    task_id = graph_extract_store.insert_task(
        kbase_id=dto.get('kbId'), schema_id=row.get('schema_id'),
        operator_id=dto.get('operatorId'), file_count=len(files),
        created_by='system')

    kbase_store.update_operator_id(dto.get('operatorId'), dto.get('kbId'))
    # ⚠️ 更新**不**写 schema（用库里已有的那份）
    graph_lifecycle.delete_graph_database(dto.get('kbId'))
    graph_extract_v2_service.submit_update(
        task_id, tmp_dir, dto, row.get('schema_id'),
        _schema_obj(row), emp_no, org_id)
    return task_id


def _resolve_schema_for_task(schema_id, operator_id) -> tuple[str, Optional[dict]]:
    """建任务时这一次 schema 查询：查不到 → **0004**（被 ``catch`` 包成校验错）。

    ⚠️ 没给 schemaId 时写进任务行的是字面量 ``"None"``。

    ``General_Schema`` + 通用算子 → 返回 ``(id, None)``：任务行记这个 id，schema
    对象留给异步里由算子产出的 ``schema.json`` 补上
    （``graph_extract_v2_service._resolve_schema`` 那条路）。判据见
    ``graph_extract_api.is_system_generated_schema_id``。
    """
    if schema_id is None or not str(schema_id).strip():
        log.info('no schemaId provided, will import schema from schema.json')
        return graph_extract_api.NO_SCHEMA_ID, None
    if graph_extract_api.is_system_generated_schema_id(schema_id, operator_id):
        log.info('schemaId %s is the generic operator-produced id; '
                 'schema will come from the produced schema.json', schema_id)
        return str(schema_id), None
    row = graph_schema_store.get_schema_by_id(str(schema_id))
    obj = graph_common.schema_obj(row) if row else None
    if not obj:
        # 这里的一切异常都变成校验错误 → 0004
        raise _invalid('graph.extract.schema.not.found', schema_id)
    return str(schema_id), obj


def _schema_obj(row: dict) -> Optional[dict]:
    """库里存的 ``schema_obj``（jsonb → dict）。"""
    value = (row or {}).get('schema_obj')
    if isinstance(value, str):
        import json

        try:
            value = json.loads(value)
        except ValueError:
            log.warning('kbase schema_obj is not valid JSON')
            return None
    return value if isinstance(value, dict) else None
