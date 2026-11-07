"""``POST /graph/import``（图谱数据导入，multipart）。

对照 ``GraphImportServiceImpl``（419 行）+ ``GraphImportControllerV2``。

## 流程

解压 → 找 ``desc.json``/``schema.json`` → 校验 → 建库（或复用）→ 写回
``kb_kbase.schema_obj`` → **异步**导入图存储（``graph_import_engine``）→ 立刻返回
``bo=null``。客户端随后轮询库状态或任务表。

## 六处「不照做就会分叉」的地方

1. **解压用 GB18030 条目名**（``ZipUtil.uncompress`` 的 ``new ZipArchiveInputStream(bis,
   "GB18030", ...)``）；而生成的中间 zip 与 JSONL 内容都是 **UTF-8**。一件东西两种编码。
2. **``desc.json`` / ``schema.json`` 是按 ``endsWith`` 找的**，且 ``findFirst()`` ——
   ``xdesc.json``、``mydesc.json`` 都算命中，多个命中时取哪个取决于目录遍历序。
3. **``entities.jsonl`` / ``edges.jsonl`` 必须是解压根目录的直接子文件**
   （``relativize(...).getNameCount() == 1`` + 名字精确相等）；嵌套的副本不算。
4. **校验顺序**：先建库（可能已经写了 ``kb_kbase`` 行）才去看 ``entities.jsonl`` 在不在 ——
   全靠外层事务回滚兜住。这里同样**先做完整的入参校验再落库**，
   但保持「先查 desc/schema、再查两个 jsonl」这个**报错优先级**不变。
5. **``Retcode.graph.import.illegal`` 的 ``Retcode`` 是小写 c**，消息键不能改。
6. **id 格式三条键在基础包里缺席**：``Accept-Language: *`` 落到 base 包时取文案会在
   构造业务异常之前就抛错，逃过业务异常捕获、被外层包装成
   0005（``Retcode.graph.import.fail``）。见
   :func:`import_graph` 的 ``base_bundle`` 分支。

## 异步

异步执行用线程池（core 3 / max 5 / queue 100 / CallerRunsPolicy）。
这里用一个模块级 ``ThreadPoolExecutor`` 同样参数，**不复用文件导入那条队列** ——
那条队列的语义是「文件处理链 + 重试」，与「一次性图谱导入」不是一回事。
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from knowledge_base import name_lock
from shared.errors.api import KbApiError, KbLiteralError, KbStoreError
from shared.i18n.messages import is_base_absent
from graph.service import graph_import_engine, graph_schema_service
from knowledge_base.service import kbase_v2_service
from knowledge_base.service.embedding_dimension import (ensure_known_embedding_model,
                                                        resolve_embedding_dimension)
from graph.repository import graph_import_store
from knowledge_base.service import kbase_service as kbase_store
from knowledge_base.service.kbase_write_service import _validate_name, _validate_sizes
from infrastructure.logging.logutil import log

# ``GraphImportServiceImpl`` 的两个上限
MAX_FILE_SIZE_MB = 500
MAX_EXTRACTED_SIZE_MB = 2048

# ``KbCategoryEnum.KNOWLEDGE_GRAPH``
CATEGORY_KNOWLEDGE_GRAPH = 10

# ``desc.json`` 里 id 的形态：``graph_`` + 十六进制。
# 16 位 = 新建库的 kbaseId；32 位 = 历史 uuid，导入旧导出包时仍要接受。
_ID_PREFIX = 'graph_'
_ID_LENGTHS = (16, 32)
_HEX = re.compile(r'^[0-9a-fA-F]+$')

# 线程池参数
_GRAPH_IMPORT_POOL = ThreadPoolExecutor(
    max_workers=5, thread_name_prefix='graph_import')


def import_graph(filename: str, content: bytes, emp_no: str,
                 org_id: Optional[str], base_bundle: bool = False) -> None:
    """``GraphImportControllerV2.importGraph``：**成功时 ``bo`` 是 null**。

    ``base_bundle`` 来自 ``identity.base_bundle``（``Accept-Language`` 主标签是 ``*``），
    只影响 id 校验段的归宿（见那里与模块头第 6 条）。
    """
    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise KbApiError('file.size.limit.check', MAX_FILE_SIZE_MB)

    entries = _unzip(content)
    total_size = sum(len(payload) for payload in entries.values())
    if total_size > MAX_EXTRACTED_SIZE_MB * 1024 * 1024:
        raise KbApiError('file.size.limit.check', MAX_EXTRACTED_SIZE_MB)

    _, desc = _find_json(entries, 'desc.json')
    if desc is None:
        raise KbApiError('Retcode.graph.import.illegal')
    if not str(desc.get('name') or '').strip() or not str(desc.get('embedding') or '').strip():
        raise KbApiError('Retcode.graph.import.illegal')

    name = desc.get('name')
    # ⚠️ 同一个名称校验，在**建库端点**上是参数校验 → 0004，
    # 在**导入这条路径**上是服务层手动调 → **0005**。
    # 键相同、码不同，别复用同一个异常类。
    _as_business(_validate_name, name)
    _as_business(_validate_sizes, desc.get('desc'), None)
    try:
        kbase_id = _validate_optional_id(desc.get('id'))
    except KbApiError as error:
        # id 三条格式键登记在 ``messages.BASE_ABSENT_KEYS``（base 包没有）。
        # ``*`` 请求下，取文案会在构造业务异常之前抛 ``NoSuchMessageException``，
        # 逃过业务异常捕获，被外层包成
        # 0005（``Retcode.graph.import.fail``）—— base（``*``）是
        # 0005+「知识图谱导入失败」；zh-CN 档仍是 id 文案。
        if base_bundle and is_base_absent(error.key):
            raise KbApiError('Retcode.graph.import.fail')
        raise

    # ⚠️ 这两个必须在 schema.json **之前**报错
    for entry, key in (('entities.jsonl', 'graph.import.entities.file.required'),
                       ('edges.jsonl', 'graph.import.edges.file.required')):
        if entry not in entries:
            raise KbApiError(key)

    found, schema = _find_json(entries, 'schema.json')
    if not found:
        raise KbApiError('Retcode.graph.import.illegal')       # **找不到** → illegal
    if schema is None:
        # **找到了但解析不出来** → fail（与上一条是两回事，别合并）
        raise KbApiError('Retcode.graph.import.fail')
    try:
        graph_schema_service.validate_graph_schema_obj(schema)
    except KbApiError as error:
        # 校验器抛的键保持不变，但码要变成 0005（同 name 那条的理由）
        raise KbApiError(error.key, *error.args)
    except Exception as error:
        log.warning('schema validation failed: %s', error)
        raise KbApiError('Retcode.graph.import.fail')

    kbase = _ensure_kbase(desc, name, kbase_id, emp_no, org_id, schema)
    # 在 202 返回**之前**落「入库中」：导入引擎只在终态回写 5/104，
    # 不先标 4 的话列表刷新看到的是一条静止的「已创建」，自动刷新闸门不启动，
    # 用户必须手动刷新才能看到导入完成。
    _mark_importing(kbase.get('kbase_id'))
    _submit(desc, kbase, schema, entries)


# ----------------------------------------------------------------------
# 解压与查找
# ----------------------------------------------------------------------


def _unzip(content: bytes) -> dict[str, bytes]:
    """解压成 ``{条目名: 内容}``。

    **条目名按 GB18030 解码**；zip 头里带 UTF-8 标志位时
    zipfile 会自己按 UTF-8 解，那种情况下再用 GB18030 会乱码，所以两种都试，
    取能解得通的那个。
    """
    import io

    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        log.warning('graph import: not a zip (%s)', error)
        raise KbApiError('zip.decompress.error')

    entries: dict[str, bytes] = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = _decode_entry_name(info)
        if not name or name.endswith('/') or name.endswith('\\'):
            continue
        if _is_unsafe_entry(name):
            # zip-slip：解压路径逃出根目录
            raise KbApiError('zip.decompress.error')
        try:
            entries[name] = archive.read(info)
        except Exception as error:                                 # noqa: BLE001
            log.warning('graph import: failed to read entry %s: %s', name, error)
            raise KbApiError('zip.decompress.error')
    return entries


def _decode_entry_name(info: zipfile.ZipInfo) -> str:
    """zip 的 UTF-8 标志位置位时按 UTF-8，否则按 **GB18030**。"""
    if info.flag_bits & 0x800:
        return info.filename
    raw = info.filename.encode('cp437', errors='replace')
    for encoding in ('gb18030', 'utf-8'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return info.filename


def _is_unsafe_entry(name: str) -> bool:
    return ('\0' in name or name.startswith('/') or name.startswith('\\')
            or (len(name) > 1 and name[1] == ':')
            or '..' in name.replace('\\', '/').split('/'))


def _find_json(entries: dict[str, bytes], suffix: str) -> tuple[bool, Optional[dict]]:
    """按 ``endsWith`` 找第一个能解析出对象的条目。

    返回 ``(是否找到同名条目, 解析结果)`` —— 两者要分开：**找不到**是
    ``Retcode.graph.import.illegal``，**找到但解析不出来**是 ``Retcode.graph.import.fail``。
    合并成一个 ``None`` 会把这两种报错搞混。
    """
    found = False
    for name in sorted(entries):
        if not name.endswith(suffix):
            continue
        found = True
        try:
            parsed = json.loads(entries[name].decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(parsed, dict):
            return True, parsed
    return found, None


def _as_business(validator, *args) -> None:
    """把校验器的 0004 换成 **0005**（键不变）—— 导入路径上的错误都是业务异常。"""
    try:
        validator(*args)
    except KbApiError as error:
        raise KbApiError(error.key, *error.args)


def _validate_optional_id(raw: Optional[str]) -> Optional[str]:
    """``desc.json.id`` 的格式校验（可选；给了就必须是 ``graph_`` + 16 或 32 位十六进制）。"""
    if raw is None or not str(raw).strip():
        return None
    text = str(raw)
    if not text.startswith(_ID_PREFIX):
        raise KbApiError('graph.import.id.format.invalid.prefix')
    suffix = text[len(_ID_PREFIX):]
    if len(suffix) not in _ID_LENGTHS:
        raise KbApiError('graph.import.id.format.invalid.length', len(suffix))
    for char in suffix:
        if not _HEX.match(char):
            raise KbApiError('graph.import.id.format.invalid.char', char)
    return suffix


# ----------------------------------------------------------------------
# 建库（或复用）
# ----------------------------------------------------------------------


def _ensure_kbase(desc: dict, name: str, kbase_id: Optional[str], emp_no: str,
                  org_id: Optional[str], schema: dict) -> dict:
    """建库或复用，并把 ``schema_id`` / ``schema_obj`` 写回 ``kb_kbase``。

    ``id`` 给了且库存在时，**严格比对 name/desc/embedding**（不一致就报，不只改）。
    ``id`` 给了且库不存在时，用**那个 id** 建（不做额外唯一性检查）。
    """
    if kbase_id:
        existing = kbase_store.get_kbase_row(kbase_id)
        if existing is not None:
            _assert_same_kbase(existing, desc, name)
            return existing

    try:
        with name_lock.acquire(org_id, name):
            conflict = kbase_store.find_kbases_by_name(name, org_id, exclude_id=kbase_id)
            if conflict:
                candidate = conflict[0]
                # 复用前校验 category 与表名前缀：否则文档库会被
                # 图谱导入复用，同一个 KB 出现 doc_<id>_vector / graph_<id>
                # 两套基名，检索/删除各错一边。
                if str(candidate.get('category')) != str(CATEGORY_KNOWLEDGE_GRAPH):
                    raise KbApiError('kbase.exist')
                candidate_table = str(candidate.get('table_name') or '')
                if candidate_table and not candidate_table.startswith(
                        kbase_v2_service.TABLE_PREFIX_GRAPH + '_'):
                    raise KbApiError('kbase.exist')
                if kbase_store.count_files(candidate['kbase_id']) > 0:
                    raise KbApiError('kbase.exist')
                log.info('graph import reusing empty kbase %s named %s',
                         candidate['kbase_id'], name)
                _write_schema(candidate['kbase_id'], schema)
                return candidate

            # 图谱导入也会写 kb_kbase.embedding_model：名字解析不到时写路径会静默换成
            # .env 默认模型，记录与向量分家（历史数据里出现过这种账实不符）。
            ensure_known_embedding_model(desc.get('embedding'))
            new_id = kbase_id or kbase_store.generate_kbase_id()
            table_name = f'{kbase_v2_service.TABLE_PREFIX_GRAPH}_{new_id}'
            try:
                pk_id = kbase_store.insert_kbase(
                    kbase_id=new_id,
                    name=name,
                    description=desc.get('desc') or '',
                    kbase_type='document',
                    embedding_model=desc.get('embedding'),
                    table_name=table_name,
                    es_index_name='graph_' + new_id,
                    category=CATEGORY_KNOWLEDGE_GRAPH,
                    status=0,
                    file_count_limit=kbase_v2_service.V2_FILE_COUNT_LIMIT,
                    org_id=org_id,
                    created_by=emp_no,
                )
            except KbStoreError as error:
                if error.kind == KbStoreError.DUPLICATE:
                    raise KbApiError('kbase.exist') from error
                raise
            kbase_v2_service._create_tables(
                table_name, resolve_embedding_dimension(desc.get('embedding')),
                category=CATEGORY_KNOWLEDGE_GRAPH)
            # 图谱库**不建 ES 索引**
            _write_schema(new_id, schema)
            return {**kbase_store.get_kbase_row(new_id), 'id': pk_id}
    except name_lock.NameLockAcquireException:
        raise KbApiError('kbase.name.lock.timeout')


def _mark_importing(kbase_id: Optional[str]) -> None:
    """把库标成「入库中」（status=4），供列表的自动刷新闸门识别。

    这是本次导入**唯一**的中间态：终态由 ``graph_import_engine._settle_kbase``
    回写（5 成功 / 104 有失败）。缺了它，客户端拿到 202 后刷新到的是一行
    status=0（已创建），而 0 不在前端的「构建中」集合里，页面从此不再轮询。
    """
    if not kbase_id:
        return
    kbase_store.update_process_with_time(kbase_id, '4', 0)


def _assert_same_kbase(existing: dict, desc: dict, name: str) -> None:
    """``id`` 命中已有库时的三方比对，不一致把差异**用「；」连起来**报出来。"""
    problems = []
    # 老调用方/测试夹具可能不带 category；缺省时不拒绝，带了就必须是 10。
    if existing.get('category') is not None \
            and str(existing.get('category')) != str(CATEGORY_KNOWLEDGE_GRAPH):
        problems.append(f'category字段与当前记录不一致：期望值[10]，'
                        f'实际值[{existing.get("category")}]')
    if existing.get('name') != name:
        problems.append(f'name字段与当前记录不一致：期望值[{existing.get("name")}]，'
                        f'实际值[{name}]')
    expected_desc = existing.get('description') or ''
    actual_desc = desc.get('desc') or ''
    if expected_desc != actual_desc:
        problems.append(f'desc字段与当前记录不一致：期望值[{existing.get("description")}]，'
                        f'实际值[{desc.get("desc")}]')
    if existing.get('embedding_model') != desc.get('embedding'):
        problems.append(f'embedding字段与当前记录不一致：期望值'
                        f'[{existing.get("embedding_model")}]，实际值[{desc.get("embedding")}]')
    if problems:
        log.error('graph import: id %s 与已有库不一致', existing.get('kbase_id'))
        raise KbLiteralError('；'.join(problems))


def _write_schema(kbase_id: str, schema: dict) -> None:
    """``updateKbaseSchema``：把 ``schema_id`` / ``schema_obj`` 写回 ``kb_kbase``。

    Uses the public service function so this module never reaches into another
    domain's repository (the c11be27 refactor removed the ``connection`` helper
    from the service surface).
    """
    kbase_store.update_schema(kbase_id, schema.get('schema_id'), schema)


# ----------------------------------------------------------------------
# 异步提交
# ----------------------------------------------------------------------


def _submit(desc: dict, kbase: dict, schema: dict, entries: dict) -> None:
    """把导入丢进线程池：立刻返回，后台跑。

    ``kb_index_name`` 用 ``graph_<kbId>``（``graph_import_task.kb_id``
    列的形状，删库时按它匹配）。
    """
    kbase_id = kbase.get('kbase_id')
    schema_id = schema.get('schema_id')
    zip_path = _write_temp_zip(entries)

    def run() -> None:
        try:
            graph_import_engine.import_from_zip(
                f'{graph_import_store.KB_ID_PREFIX}{kbase_id}',
                schema_id, zip_path, kbase_schema_obj=schema)
        except Exception:                                          # noqa: BLE001
            log.exception('graph import task failed for kbase %s', kbase_id)
        finally:
            # 临时 zip 最大 500MB；成功/失败都必须删，否则每次导入泄漏一份。
            try:
                os.unlink(zip_path)
            except OSError as error:
                log.warning('failed to remove temp graph zip %s: %s', zip_path, error)

    try:
        _GRAPH_IMPORT_POOL.submit(run)
    except Exception:                                              # noqa: BLE001
        # 池满/已关：**同步跑**，别把导入丢了
        log.warning('graph import pool rejected the task; running inline')
        run()


#: 导入引擎真正读取的条目。``document_chunk.jsonl`` 也属于导入条目：
#: 缺了它，导入链不会写图谱切片与 chunk 向量。
_IMPORT_ENTRIES = ('entities.jsonl', 'edges.jsonl', 'document_chunk.jsonl')


def _write_temp_zip(entries: dict) -> str:
    """把解压出来的内容重新打成一个 zip 给导入引擎（引擎按路径读）。

    内容按 **UTF-8** 写；条目名**只保留 basename**，
    因为 ``forEachJsonLine`` 是按精确名查 ``entities.jsonl`` 的。

    只保留 ``_IMPORT_ENTRIES`` 三类；同名 basename 只写一次，且优先使用
    **根目录精确名**（``entities.jsonl``），其次才是任意深度的同后缀条目。
    """
    import tempfile

    handle, path = tempfile.mkstemp(prefix='graph_import_', suffix='.zip')
    os.close(handle)

    ordered: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    for wanted in _IMPORT_ENTRIES:
        payload = entries.get(wanted)
        if payload is not None:
            ordered.append((wanted, payload))
            seen.add(wanted)
    for name, payload in entries.items():
        basename = name.replace('\\', '/').split('/')[-1]
        if basename in _IMPORT_ENTRIES and basename not in seen:
            ordered.append((basename, payload))
            seen.add(basename)

    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for basename, payload in ordered:
            archive.writestr(basename, payload)
    return path
