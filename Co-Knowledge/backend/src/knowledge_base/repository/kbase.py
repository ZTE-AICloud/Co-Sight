"""``kb_kbase`` 的读写。

旧 ``kb_embedding`` 表已不存在；embedding 清单统一由模型注册表提供
（``core.gateway.model_resolver.embedding_models``）。
"""

from __future__ import annotations

import json
import secrets

from typing import Any, Iterable, Optional

import psycopg2

from infrastructure.db.kb import connection
from shared.errors.api import KbStoreError

from infrastructure.db.rows import rows as _rows

# 新库 kbaseId：16 位十六进制（64 bit）。历史库仍是 32 位 uuid，两种长度长期共存。
# 16 位在 100 万库规模下生日碰撞概率约 2.7e-10；生成后仍会查重（含删除行）。
KBASE_ID_BYTES = 8
KBASE_ID_HEX_LENGTH = KBASE_ID_BYTES * 2
_KBASE_ID_MAX_ATTEMPTS = 8

# 搜索只按这几列过滤；``category`` 由调用方给定。
# keyword 先转义 LIKE 元字符，见 :func:`_escape_like`。
_KBASE_COLUMNS = '*'


def _escape_like(keyword: str) -> str:
    """转义 LIKE 元字符（``%`` ``_`` ``\\``）。

    不转义时用户输入的 ``%`` 会变成通配符（``a%b`` 能匹配到 ``axxb``），
    这层转义不能省。
    """
    return keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def new_kbase_id_candidate() -> str:
    """生成一个 16 位十六进制的候选 kbaseId（未查重）。"""
    return secrets.token_hex(KBASE_ID_BYTES)


def generate_kbase_id() -> str:
    """生成新的 kbaseId：16 位十六进制，生成后查重。

    ``kb_kbase.kbase_id`` 只有普通索引（不是唯一约束），所以查重必须在应用层做。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            for _ in range(_KBASE_ID_MAX_ATTEMPTS):
                candidate = new_kbase_id_candidate()
                cursor.execute(
                    'SELECT 1 FROM kb_kbase WHERE kbase_id = %s LIMIT 1', (candidate,))
                if cursor.fetchone() is None:
                    return candidate
    raise RuntimeError(
        f'failed to generate a unique kbaseId after {_KBASE_ID_MAX_ATTEMPTS} attempts')


def select_all_kbases(org_id: Optional[str] = None) -> list[dict]:
    """``KbaseDao.getAuthorityKbases`` 里「有管理权限」那条分支。

    删除策略统一为**物理删除**，不再有 ``is_enabled`` 过滤。
    """
    sql = f"SELECT {_KBASE_COLUMNS} FROM kb_kbase WHERE 1=1"
    params: list[Any] = []
    if org_id:
        sql += ' AND org_id = %s'
        params.append(org_id)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return _rows(cursor)


def select_kbase_by_id(kbase_id: str) -> Optional[dict]:
    """``KbaseDao.getKbase`` / ``getKbaseById``：按 ``kbase_id`` 取单行。

    直接按业务主键取行；删除已是物理删除，无需过滤。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT {_KBASE_COLUMNS} FROM kb_kbase WHERE kbase_id = %s",
                (kbase_id,),
            )
            rows = _rows(cursor)
    return rows[0] if rows else None


def count_files(kbase_id: str) -> int:
    """``DirectoryDao.getFileCount``：``kb_directory`` 下该库的**文件**条目数。

    重传会物理删旧行，所以这里统计到的就是当前真实文件数。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM kb_directory "
                "WHERE kbase_id = %s AND type = 'file'",
                (kbase_id,),
            )
            return int(cursor.fetchone()[0])


def count_files_by_kbase_ids(kbase_ids: Iterable[str]) -> dict[str, int]:
    """按库分组统计文件数。

    与 :func:`count_files` 同口径，分页列表与详情接口报的文件数是同一个值。
    """
    ids = list(kbase_ids)
    if not ids:
        return {}
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT kbase_id, COUNT(id) FROM public.kb_directory '
                "WHERE kbase_id = ANY(%s) AND type = 'file' "
                'GROUP BY kbase_id',
                (ids,),
            )
            return {row[0]: int(row[1]) for row in cursor.fetchall()}


def _search_where(keyword: str, categories, embedding_model, org_id) -> tuple[str, list[Any]]:
    """``fuzzySearch`` / ``countFuzzySearch`` 共用的 WHERE 子句（两边必须一致）。

    ⚠️ ``keyword`` **同时匹配名称、描述与创建人**。界面上的搜索框写的是
    「搜索知识库名称、描述或创建人...」—— 只搜名称时按描述/创建人搜永远是 0 条。
    两边的口径取界面（用户看得到的承诺），并保持两个查询**完全一致**，
    否则 ``countFuzzySearch`` 与 ``fuzzySearch`` 会给出不同的总数。
    """
    sql = " WHERE 1=1"
    params: list[Any] = []
    if keyword:
        sql += (" AND (name ILIKE '%%' || %s || '%%'"
                " OR COALESCE(description, '') ILIKE '%%' || %s || '%%'"
                " OR COALESCE(created_by, '') ILIKE '%%' || %s || '%%')")
        like = _escape_like(keyword)
        params.extend([like, like, like])
    if org_id:
        sql += ' AND org_id = %s'
        params.append(org_id)
    if embedding_model:
        sql += ' AND embedding_model = %s'
        params.append(embedding_model)
    if categories:
        sql += ' AND category = ANY(%s)'
        params.append(list(categories))
    return sql, params


# 前端 key → 排序列。
# ``description`` / ``currentFileCount`` 在枚举里**没有映射**（源码里被注释掉了）
# → ``toQueryOrderEnum`` 过滤掉它们；一个都不剩就回落 ``CREATED_DATE_DESC``。
_ORDER_COLUMNS = {
    'id': 'kbase_id',
    'name': 'name',
    'createdDate': 'created_at',
    'embeddingModel': 'embedding_model',
    'createdBy': 'created_by',
}

DEFAULT_ORDER_BY = 'created_at DESC'      # ``CREATED_DATE_DESC``


def build_order_by(order_list) -> str:
    """排序键 + ``ORDER BY`` 片段。

    * key 与 ascending **同时**匹配才生效；匹配不到的项**丢弃**（不是报错 ——
      枚举绑定期已挡掉非法 key）；
    * 列名只出自白名单 ``_ORDER_COLUMNS``（值域由枚举保证）；
    * ``name`` 套 ``convert_to(name,'GB18030')`` —— 中文按 GB18030 排
      （数据库默认 collation 下顺序不同）；
    * 默认 ``created_at DESC``。
    """
    clauses = []
    for item in order_list or []:
        column = _ORDER_COLUMNS.get(item.get('key'))
        ascending = item.get('ascending')
        if column is None or ascending is None:
            continue
        rendered = "convert_to(name,'GB18030')" if column == 'name' else column
        clauses.append(rendered if ascending else rendered + ' DESC')
    return ', '.join(clauses) if clauses else DEFAULT_ORDER_BY


def search_kbases(keyword: str, categories, embedding_model, org_id,
                  limit: int, offset: int, order_list=None) -> list[dict]:
    """列表/搜索的 SELECT 半段（含 ORDER BY / LIMIT / OFFSET）。

    排序由 ``order_list``（``[{key, ascending}]``）决定，见 :func:`build_order_by`；
    为空时按 ``created_at DESC``。web 点表头排序时**会**传这个清单。
    """
    where, params = _search_where(keyword, categories, embedding_model, org_id)
    sql = (f'SELECT {_KBASE_COLUMNS} FROM kb_kbase{where} '
           f'ORDER BY {build_order_by(order_list)} LIMIT %s OFFSET %s')
    params.extend([limit, offset])
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return _rows(cursor)


def count_search_kbases(keyword: str, categories, embedding_model, org_id) -> int:
    """列表/搜索的总行数。"""
    where, params = _search_where(keyword, categories, embedding_model, org_id)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT count(id) FROM kb_kbase' + where, params)
            return int(cursor.fetchone()[0])


def _stats_where(alias: str, categories, org_id) -> tuple[str, list[Any]]:
    """``GET /knowledge-bases/stats`` 的 WHERE；``alias`` 为空时是单表查询。

    过滤条件与 :func:`count_search_kbases` 保持一致（可选 ``org_id``、可选
    ``categories``），指标卡与列表的总数才对得上。
    """
    sql = " WHERE 1=1"
    params: list[Any] = []
    if org_id:
        sql += f' AND {alias}org_id = %s'
        params.append(org_id)
    if categories:
        sql += f' AND {alias}category = ANY(%s)'
        params.append(list(categories))
    return sql, params


def summarize_kbases(categories, org_id: Optional[str] = None) -> dict[int, dict]:
    """按 ``category`` 汇总知识库数量、状态分布与文件总数（``GET /knowledge-bases/stats``）。

    返回 ``{category: {total, fileTotal, statusCounts}}``，只含库里实际存在的分类；
    请求了但一条都没有的分类由服务层补零（见 ``kbase_service.get_kbase_stats``）。

    ``fileTotal`` 与列表行的 ``currentFileCount`` 同口径：``kb_directory`` 中
    ``type='file'`` 的行数（见 :func:`count_files_by_kbase_ids`）。
    这里用聚合 SQL 一次算完，不再把 ≤500 行列表全量拉回前端自己数。
    """
    status_where, status_params = _stats_where('', categories, org_id)
    file_where, file_params = _stats_where('k.', categories, org_id)

    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT category, status, count(id) FROM kb_kbase'
                + status_where + ' GROUP BY category, status',
                status_params,
            )
            status_rows = cursor.fetchall()
            cursor.execute(
                'SELECT k.category, count(d.id) FROM kb_kbase k '
                "LEFT JOIN kb_directory d ON d.kbase_id = k.kbase_id "
                "AND d.type = 'file'"
                + file_where + ' GROUP BY k.category',
                file_params,
            )
            file_rows = cursor.fetchall()

    summary: dict[int, dict] = {}
    for category, status, count in status_rows:
        item = summary.setdefault(
            int(category), {'total': 0, 'fileTotal': 0, 'statusCounts': {}})
        item['total'] += int(count)
        item['statusCounts'][str(status)] = int(count)
    for category, file_count in file_rows:
        item = summary.setdefault(
            int(category), {'total': 0, 'fileTotal': 0, 'statusCounts': {}})
        item['fileTotal'] = int(file_count)
    return summary


def find_kbases_by_name(name: str, org_id: Optional[str] = None,
                        exclude_id: Optional[str] = None) -> list[dict]:
    """``KbaseDao.queryKbaseByName``：同名判重（建库时 ``exclude_id`` 传 None）。

    删除已是物理删除，同名索引是全表唯一索引，删除后同名可以再建。
    """
    sql = "SELECT * FROM kb_kbase WHERE name = %s"
    params: list[Any] = [name]
    if org_id:
        sql += ' AND org_id = %s'
        params.append(org_id)
    if exclude_id:
        sql += ' AND kbase_id <> %s'
        params.append(exclude_id)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return _rows(cursor)


def insert_kbase(kbase_id: str, name: str, description: str, kbase_type: str,
                 embedding_model: str, table_name: str, es_index_name: str,
                 category: int, status: int, file_count_limit: int,
                 org_id: Optional[str], created_by: str,
                 head_icon: Optional[str] = None) -> int:
    """插一行 ``kb_kbase``，返回自增主键。

    列值约定：

    * ``description`` 用 ``StringUtils.defaultString`` → **null 变空串**（不是 null）
    * ``es_index_name`` = ``doc_<kbase_id>``（文档库，与 ES 索引名、检索基名一致）；
      图谱库为 ``graph_<kbase_id>``（它不建 ES 索引）
    * ``status`` 初值 ``0``
    * 删除是物理删除，没有 ``is_enabled`` 列

    ``head_icon`` 只有 V2 那条路（``createKbaseForGraph``）会写；v1 的
    ``createKbase(CreateKbaseDTO)`` 根本没有这个参数，所以保持默认 ``None``。
    """
    try:
        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO kb_kbase '
                    '(kbase_id, "type", "name", description, head_icon, es_index_name, '
                    ' embedding_model, table_name, category, status, file_count_limit, org_id, '
                    ' created_by, created_at, updated_by, updated_at) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, NOW()) '
                    'RETURNING id',
                    (kbase_id, kbase_type, name, description, head_icon, es_index_name,
                     embedding_model, table_name, category, status, file_count_limit, org_id,
                     created_by, created_by),
                )
                return int(cursor.fetchone()[0])
    except psycopg2.errors.UniqueViolation as error:
        # 唯一索引上线后，极小概率的 kbase_id 碰撞要变成明确的存储层错误，
        # 由服务层翻成业务错误（kbase.exist），不要暴露成 0001。
        raise KbStoreError(KbStoreError.DUPLICATE, str(error).strip(),
                           'kbase_id already exists') from error


def delete_kbase_row(kbase_id: str) -> None:
    """``KbaseDao.deleteKbase``：**物理删除**知识库行。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM kb_kbase WHERE kbase_id = %s', (kbase_id,))


def select_by_ids(ids: Iterable[str]) -> list[dict]:
    """``KbaseDao.getKbaseById(List<String>)``：**按内容分流**。

    数字串查 ``kb_kbase.id``（主键），非数字串查 ``kb_kbase.kbase_id``（uuid）——
    一次调用里两类可以并存（``OR`` 起来）。这条是 workflow 那条链在用的，
    「list/pk/id」的名字只说了主键那一半。

    没有 ``ORDER BY``（顺序由 PG 堆序决定），别顺手加排序。
    """
    numeric, textual = [], []
    for item in ids or []:
        if item is None:
            continue
        text = str(item)
        if text.isdigit():
            numeric.append(int(text))
        else:
            textual.append(text)
    if not numeric and not textual:
        return []

    clauses, params = [], []
    if numeric:
        clauses.append('id = ANY(%s)')
        params.append(numeric)
    if textual:
        clauses.append('kbase_id = ANY(%s)')
        params.append(textual)
    sql = f"SELECT * FROM kb_kbase WHERE {' OR '.join(clauses)}"
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return _rows(cursor)


# ``KbaseStatusEnum``：6 发布中 / 7 已发布 / 8 发布后已修改
STATUS_PUBLISHING = 6
STATUS_PUBLISHED = 7
STATUS_MODIFIED_AFTER_PUBLISH = 8


def set_kbase_status_modified(kbase_id: str) -> None:
    """``KbaseService.setKbaseStatusModified``：导入完成后把已发布/发布中的库标成「已修改」。

    只有 6/7 才动 —— 其余状态（含 8 自己）保持原样，避免把「待发布」也标成「改过」。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM kb_kbase WHERE kbase_id = %s",
                (kbase_id,),
            )
            row = cursor.fetchone()
            if row is None or row[0] not in (STATUS_PUBLISHING, STATUS_PUBLISHED):
                return
            cursor.execute(
                "UPDATE kb_kbase SET status = %s, updated_at = NOW() "
                "WHERE kbase_id = %s",
                (STATUS_MODIFIED_AFTER_PUBLISH, kbase_id),
            )


# ----------------------------------------------------------------------
# 抽图/导入链路的进度与失败原因（``KbaseDao`` 的 LambdaUpdateWrapper 那几条）
# ----------------------------------------------------------------------


def update_process(kbase_id: str, status: str, process: int) -> None:
    """``KbaseDao.updateKbaseProcess``：只改 ``status`` 与 ``process``。

    ⚠️ **不动 ``updated_at``** —— 批量更新形式不会触发自动填充（实测：抽图异步里
    连着调了好几次 ``updateKbaseProcess``，``updated_at`` 仍等于建库那一刻）。
    只有 :func:`update_process_with_time` 会显式写时间。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE kb_kbase SET status = %s, process = %s "
                "WHERE kbase_id = %s",
                (status, str(process), kbase_id),
            )


def update_process_with_time(kbase_id: str, status: str, process: int,
                             emp_no: str = '') -> None:
    """``KbaseDao.updateKbaseProcessWithTime``：**额外**写 ``updated_at`` 与操作人。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE kb_kbase SET status = %s, process = %s, updated_at = NOW(), "
                "updated_by = %s WHERE kbase_id = %s",
                (status, str(process), emp_no, kbase_id),
            )


def update_fail_reason(kbase_id: str, zh_msg: str, en_msg: str) -> None:
    """写 ``fail_reason_obj``。

    删除/更新一律按 ``kbase_id`` 直接执行。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'UPDATE kb_kbase SET fail_reason_obj = %s::jsonb WHERE kbase_id = %s',
                (json.dumps({'zh_CN': zh_msg, 'en_US': en_msg}), kbase_id),
            )


def update_operator_id(operator_id, kbase_id: str) -> None:
    """``KbaseDao.updateKbaseOperatorId``：算子 id 存成**字符串**列。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE kb_kbase SET operator_id = %s WHERE kbase_id = %s",
                (int(operator_id), kbase_id),
            )


def update_schema(kbase_id: str, schema_id: str, schema_obj: Optional[dict]) -> None:
    """把 schema 落到库里（``schema_obj`` 是 jsonb）。"""
    payload = json.dumps(schema_obj) if schema_obj is not None else None
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'UPDATE kb_kbase SET schema_id = %s, schema_obj = %s::jsonb '
                "WHERE kbase_id = %s",
                (schema_id, payload, kbase_id),
            )
