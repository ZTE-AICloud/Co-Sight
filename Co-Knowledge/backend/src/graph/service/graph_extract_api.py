"""抽图链路的共享工具：落临时目录、调算子、读产出、打包。

链路（由 ``graph_extract_v2_service`` 驱动）::

    上传文件 → 落临时目录 → 建任务行 → **异步**：
      调抽图算子（ingestion 模块）→ 产出 entities/edges/schema.json
      → 打包 → ``graph_import_engine.import_from_zip`` → 更新任务状态

算子的调用契约见 ``memory/graph-extract-operator-contract.md`` 记的那份 ——
其中最关键的一条：**``llm`` 必须放在 ``args`` 里、且 argName 叫 ``kwargs``**；
顶层 ``kwargs`` 只管切分参数。

## 路径契约：``diskFileKey`` 必须是**临时目录** ``<uuid>/input``

``diskFileKey`` 是 ``saveTmpDirFileWithOriginalName`` 返回的**目录**
``<pvc>/tmp_preview/<uuid>/input``；ingestion 模块再取它的 ``dirname`` 当工作目录，
于是算子拿到的 ``file_path`` 是 ``<uuid>``，其下 ``input/``
（上传的原文）与 ``output/``（切分产出）**是兄弟**。两个算子的约定都以它为前提：

* ``-6``（通用）读 ``<file_path>/output/document_chunk.jsonl``，产出写回 ``<file_path>/``；
* ``-5``（专业）除了读 ``output/``，还要 ``os.listdir(<file_path>/input)`` 自己按章节切分。

不能改成「按文件逐个调、传文件路径」：那样 ``file_path`` = ``<uuid>/input``，
通用算子（-6）碰巧还能过（它要的 ``output/`` 恰好落在同一层），专业算子（-5）却去找
``<uuid>/input/input`` → ``FileNotFoundError``。**传目录、整目录一次调用**，产出只取
一份。多文件身份不会丢 —— 切分写进 chunk 的 ``source`` 就是原文件名。

``schema`` 参数**只注入给声明了 ``schemaId`` 的专业算子**（见
``operator_consumes_schema``）—— 不能无条件注入：「带 schemaId ⟺ 专业算子」的
假设不成立，通用算子没有 ``schema`` 形参。

``schemaId`` 的解析有一条**窄例外**：``General_Schema``（通用算子产出的
``schema.json`` 自报的 id，也是系统自己写进 ``kb_kbase.schema_id`` 的值）可以直接当
``schemaId`` 传 —— 它不是 ``graph_schema`` 的模板行，schema 对象由算子产出的
``schema.json`` 在导入前补上（与「没给 schemaId」同一条路）。判据与边界见
``is_system_generated_schema_id``：**任何其他**查不到 ``graph_schema`` 的 id
（包括拼写变体）照旧报模板不存在（0004）。
"""

from __future__ import annotations

import json
import os
import uuid
import zipfile
from datetime import datetime

from infrastructure.storage import kb_storage as storage
from knowledge_base.task import operator_runtime
from graph.service import graph_common
from infrastructure.logging.logutil import log

# ``GraphExtractController`` 的长度上限
OPERATOR_ID_MAX = 10

# 没给 schemaId 时塞的字面量（它会落进任务行）
NO_SCHEMA_ID = 'None'

# 通用算子（-6）产出的 ``schema.json`` **自报**的 schema_id；也是系统自己写进
# ``kb_kbase.schema_id`` / ``schema_obj`` 的值。它**不是** ``graph_schema`` 里的
# 模板行 —— 解析时的容忍判据见 :func:`is_system_generated_schema_id`。
GENERAL_SCHEMA_ID = 'General_Schema'

# ----------------------------------------------------------------------
# 落文件
# ----------------------------------------------------------------------


def save_tmp_files(files: list) -> str:
    """``LocalDiskUtil.saveTmpDirFileWithOriginalName``：``<root>/tmp_preview/<uuid>/input``。

    ⚠️ 返回的是 **``input`` 那一层**，异步里拿它的 ``dirname`` 当「产出目录」。

    ⚠️ **空表会抛** ``IllegalArgumentException("File list cannot be null or empty")`` ——
    图谱「更新」时一个文件都没给（既没上传也没有 localFiles）就死在这里，
    控制器把它包成 0005「生成图谱失败」（实测）。
    """
    if not files:
        raise ValueError('File list cannot be null or empty')
    tmp_dir = storage.tmp_preview_dir(uuid.uuid4().hex) / 'input'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for index, item in enumerate(files):
        (tmp_dir / safe_name(item.filename, index)).write_bytes(item.content)
    return str(tmp_dir)


def safe_name(filename: str, index: int) -> str:
    """去掉路径成分；重名或空名时补 ``_<序号>``。"""
    base = os.path.basename((filename or '').replace('\\', '/')).strip()
    if not base or base in ('.', '..'):
        base = f'upload_{index}'
    return base


def operator_consumes_schema(operator_id) -> bool:
    """该算子的 ``graph_extract`` **是否吃 ``schema`` 参数**。

    判据 = 算子自己声明了 ``schemaId`` 参数（``operator_param`` 表）。这正是前端
    渲染「图谱模板下拉框」的那条判据（``CreateKnowledgeGraph.vue`` 里看
    ``arg.argName === 'schemaId'``）：声明了的（专业算子，如 -5）签名里多一个
    ``schema``，没声明的（通用算子，如 -6）没有 —— 其算子包 config.json 的描述
    也写着「不依赖schema信息」。

    **为什么要有这条判据**：不能「只要请求带了 schemaId 就无条件往 ``args`` 里塞
    ``schema``」——「带 schemaId ⟺ 专业算子」的假设不成立。通用算子拿到它就是
    ``TypeError: graph_extract() got an unexpected keyword argument 'schema'``。

    查不到算子行时返回 False：算子不存在时调用链后面本来就会报
    「算子不存在」，不该先炸一个误导人的 TypeError。
    """
    from operators.service import operator_service

    row = operator_service.get_operator_row(operator_id)
    if row is None:
        return False
    operator_pk = row.get('id')
    params = operator_service.list_params_by_operator_ids([operator_pk])
    return any((param or {}).get('arg_name') == 'schemaId'
               for param in params.get(operator_pk) or [])


def is_system_generated_schema_id(schema_id, operator_id) -> bool:
    """这个 ``schemaId`` 是不是**本系统自产**、且这条链路用得上它（``General_Schema``）。

    判据两条，**都要**满足 —— 这就是与「拼错的不存在 id」的分界：

    1. **精确等于** ``GENERAL_SCHEMA_ID``（``'General_Schema'``）。它是通用算子
       （``-6``）产出的 ``schema.json`` **自报**的 id：PVC 上 57 份通用算子包全部含
       ``"schema_id": "General_Schema"``、56 份专业算子包全都不含；也是系统自己写进
       ``kb_kbase.schema_id`` / ``schema_obj`` 的值（库里实有 4 行）。
       大小写/拼写变体（含拼错的兜底 ``General_schema``）**不**放行 ——
       它们与任意不存在的 id 同样是错的。
    2. 本请求的算子**不吃 ``schema`` 参数**（``operator_consumes_schema`` 为 False）。
       这个 id 只在**通用链路**里有意义：算子不接收 ``schema``，schema 完全由它产出的
       ``schema.json`` 提供。专业算子（如 ``-5``，自带模板才有意义）传它仍是错，
       照常报模板不存在（0004）—— 别把这条读成「General_Schema 万能」。

    ``no_such_schema`` 这类拼错/不存在的 id 不受这条例外影响。
    """
    if schema_id is None or str(schema_id) != GENERAL_SCHEMA_ID:
        return False
    return not operator_consumes_schema(operator_id)


def _llm_endpoint_config(dto: dict):
    """把「模型管理页新增的 LLM」解析成算子可用的端点描述（``llmConfig``）。

    为什么要下发而不是让算子自己查：算子在沙箱子进程里跑，环境变量按白名单收敛，
    **数据库凭据被显式剔除**（``ingestion/utility/sandbox_runtime.py`` 的
    ``_DENY_PREFIXES``），子进程连不上注册表。父进程解析、经算子 ``kwargs`` 下发
    是唯一不破那条边界的通道。

    为什么只认 ``source='user'``：抽图这条链路刻意钉在 ``MODEL_GATEWAY_URL``
    （见 ``model/operator_client.py`` 的模块注释 —— 改用默认 LLM 的生成端点会让
    同一篇文档从 7.5s 变成 >8 分钟）。``.env`` 播种的行（``source='env'``）保持
    那条既有行为、**不下发**；用户在模型管理页新增的端点没有 ``.env`` 落点，
    不接注册表就永远用不了 —— 例如新增 ``deepseek-chat-1``
    （``api_model=deepseek-chat``，独立 base_url）后建图，算子把**注册名**当
    模型名打到 llm 网关，404 重试 10 分钟后只落一句「生成失败」。
    """
    name = str((dto.get('kwargs') or {}).get('llm') or '').strip()
    if not name:
        return None

    from model import resolver as model_resolver

    # ``aux``：抽图是逐 chunk 的辅助调用，思考片段按「关闭/最低档」解析。
    endpoint = model_resolver.resolve('llm', name, operation='chat',
                                      thinking_profile='aux')
    if endpoint.origin != 'registry' or endpoint.source != 'user':
        return None

    config = {'url': endpoint.url, 'model': endpoint.api_model}
    # 空 key = 端点不要求鉴权（私网端点常见），别发一个空的 Authorization 头。
    if endpoint.api_key:
        config['api_key'] = endpoint.api_key
    if endpoint.thinking_payload:
        config['thinking_payload'] = endpoint.thinking_payload
    if endpoint.timeout:
        config['timeout'] = endpoint.timeout
    log.info('graph extract resolves llm %s from registry: %s (model=%s)',
             name, endpoint.url, endpoint.api_model)
    return config


def call_operator(dto: dict, operator_id, python_path: str, disk_file_key: str,
                   schema_id: str) -> dict:
    """组装 ``args`` 并调抽图算子。

    ⚠️ 三条必须保持的约束：

    * 有 schemaObj **且算子是专业算子**（声明了 ``schemaId``，见
      ``operator_consumes_schema``）时塞一个 ``schema`` 参数 —— 通用算子没这个
      形参，无条件塞会 TypeError；
    * **总是**塞一个 ``kwargs`` 参数，值取请求的 ``kwargs`` ——
      而 ``llm`` 就在那里，缺了算子直接报「缺少必需参数 'llm'」；
    * 顶层 ``kwargs`` 字段**只**用于切分参数，别混。

    ``disk_file_key`` 传的是 ``save_tmp_files`` 返回的**临时目录**（``<uuid>/input``），
    不是某个文件 —— 见模块头的「路径契约」。
    """
    args = list(dto.get('args') or [])
    if (schema_id and schema_id != NO_SCHEMA_ID
            and operator_consumes_schema(operator_id)):
        from graph.repository import graph_schema_store

        row = graph_schema_store.get_schema_by_id(schema_id)
        obj = graph_common.schema_obj(row) if row else None
        if obj:
            args.append({'argName': 'schema', 'argType': 'object', 'defaultValue': obj})

    # ``_run`` 已经塞过一条 ``kwargs``；``extract_params`` 是「后者胜」，
    # 所以把带上 ``llmConfig`` 的这份追加在最后即可覆盖（不要原地改 dto）。
    operator_kwargs = dict(dto.get('kwargs') or {})
    endpoint_config = _llm_endpoint_config(dto)
    if endpoint_config is not None:
        operator_kwargs['llmConfig'] = endpoint_config
    args.append({'argName': 'kwargs', 'argType': 'object',
                 'defaultValue': operator_kwargs})

    return operator_runtime.graph_extract(
        operator_id=operator_id, args=args, python_path=python_path,
        file_format=dto.get('fileFormat'), kb_id=dto.get('kbId'),
        disk_file_key=disk_file_key, regex_list=dto.get('regexList'),
        kwargs=dto.get('kwargs'))


def read_outputs(disk_file_key: str) -> dict:
    """读算子产出：传 ``disk_file_key``（``<uuid>/input``），产出在它的**父目录**。

    算子的 ``file_path`` = ``dirname(disk_file_key)`` = ``<uuid>``，``entities.jsonl``
    / ``edges.jsonl`` / ``schema.json`` 都写在那一层（与切分的 ``output/`` 同级）。
    """
    folder = os.path.dirname(disk_file_key)
    out = {'entities': b'', 'edges': b'', 'chunks': b'', 'schema': None}
    for name, key in (('entities.jsonl', 'entities'), ('edges.jsonl', 'edges')):
        candidate = os.path.join(folder, name)
        if os.path.exists(candidate):
            out[key] = open(candidate, 'rb').read()
    # ``document_chunk.jsonl`` 是切分那一步写在 ``output/`` 下的
    # （``GraphExtractService.save_processed_data`` 用 ``dirname(corpus_file_path)``），
    # 与 entities/edges 不同层。两处都找一下，也接受自定义算子直接写在根目录。
    for candidate in (os.path.join(folder, 'output', 'document_chunk.jsonl'),
                      os.path.join(folder, 'document_chunk.jsonl')):
        if os.path.exists(candidate):
            out['chunks'] = open(candidate, 'rb').read()
            break
    schema_path = os.path.join(folder, 'schema.json')
    if os.path.exists(schema_path):
        try:
            out['schema'] = json.loads(open(schema_path, encoding='utf-8').read())
        except ValueError as error:
            log.warning('produced schema.json is not valid JSON: %s', error)
    return out


def zip_outputs(tmp_dir: str, produced: list) -> str:
    """把各文件产出的 ``entities.jsonl`` / ``edges.jsonl`` / ``document_chunk.jsonl``
    **合并**成一个 zip。

    导入引擎是按**精确名**取条目的，所以多文件必须合并，不能一个文件一个条目。
    切片（``document_chunk.jsonl``）必须打包：只打包实体/边时，
    图谱库的 ``_chunk`` 表与 ``key_type='chunk'`` 向量会永远为空。
    """
    zip_path = os.path.join(tmp_dir, f'graph_data_{int(datetime.now().timestamp() * 1000)}.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, key in (('entities.jsonl', 'entities'), ('edges.jsonl', 'edges'),
                          ('document_chunk.jsonl', 'chunks')):
            merged = b''.join(item.get(key) or b'' for item in produced)
            if key == 'chunks' and not merged:
                # 没有切片时不建空条目 —— 与导出的「可选文件」语义一致
                continue
            archive.writestr(name, merged)
    return zip_path
