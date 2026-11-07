"""``kb_directory`` 与 ``kb_directory_property`` 的读写。

删除一律是物理 ``DELETE``：查询不过滤 ``is_enabled``，也不存在删除标记行；
手写 SQL 不需要额外的删除条件。
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable, Optional

from infrastructure.db.kb import connection

from infrastructure.db.rows import rows as _rows

TYPE_FOLDER = 'folder'
TYPE_FILE = 'file'

# ``SysGlobalConst``
FLAG_ENABLE = 'Y'
FLAG_DISABLE = 'N'
ROOT_DIRECTORY_SYMBOL = '0'
PATH_SPLIT = '-'
K_TYPE = 'KType'
DOCUMENT_TYPE = 'document'


def new_id() -> str:
    """``@TableId(ASSIGN_UUID)`` —— 32 位无横线 uuid。"""
    return uuid.uuid4().hex


def get_parent_path(cursor, parent_id: Optional[str]) -> str:
    """``getParentPath``：父为空 → ``"0"``；否则 ``父.parent_path + "-" + parentId``。

    顺带把父目录置 ``can_spread = TRUE``。
    """
    if not parent_id:
        return ROOT_DIRECTORY_SYMBOL
    cursor.execute(
        "SELECT parent_path FROM kb_directory WHERE id = %s",
        (parent_id,),
    )
    row = cursor.fetchone()
    if row is None:
        # 父目录不存在时抛同类失败，由上层收敛
        raise LookupError('parent directory not found: %s' % parent_id)
    cursor.execute(
        "UPDATE kb_directory SET can_spread = TRUE WHERE id = %s",
        (parent_id,),
    )
    return '%s%s%s' % (row[0], PATH_SPLIT, parent_id)


def find_folder_by_title(cursor, kbase_id: str, parent_id: Optional[str], title: str) -> Optional[dict]:
    """``checkDirectoryDuplicateName``：同名文件夹判重。"""
    if parent_id:
        cursor.execute(
            "SELECT * FROM kb_directory WHERE kbase_id = %s AND title = %s "
            "AND parent_id = %s LIMIT 1",
            (kbase_id, title, parent_id),
        )
    else:
        cursor.execute(
            "SELECT * FROM kb_directory WHERE kbase_id = %s AND title = %s "
            "AND parent_id IS NULL LIMIT 1",
            (kbase_id, title),
        )
    rows = _rows(cursor)
    return rows[0] if rows else None


def count_children_folders(cursor, kbase_id: str, parent_id: Optional[str]) -> int:
    """``createDirectory`` 里的层级限额判据（``getChildrenDirectoryList`` 的条数）。"""
    if parent_id:
        cursor.execute(
            "SELECT count(*) FROM kb_directory WHERE kbase_id = %s AND parent_id = %s",
            (kbase_id, parent_id),
        )
    else:
        cursor.execute(
            "SELECT count(*) FROM kb_directory WHERE kbase_id = %s AND parent_id IS NULL",
            (kbase_id,),
        )
    return int(cursor.fetchone()[0])


def insert_directory(cursor, kbase_id: str, parent_id: Optional[str], parent_path: str,
                     title: str, dir_type: str, status: Optional[int],
                     directory_id: Optional[str] = None,
                     created_by: Optional[str] = None,
                     file_from: Optional[str] = None) -> str:
    """插一行目录/文件。

    ``created_by``/``updated_by`` 在插入时自动填充；不填的话它们会是 null，
    而前端列表页会显示「创建人」。
    """
    directory_id = directory_id or new_id()
    cursor.execute(
        'INSERT INTO kb_directory '
        '(id, kbase_id, title, parent_id, parent_path, can_spread, type, status, '
        ' created_by, updated_by, file_from) '
        "VALUES (%s, %s, %s, %s, %s, FALSE, %s, %s, %s, %s, %s)",
        (directory_id, kbase_id, title, parent_id, parent_path, dir_type, status,
         created_by, created_by, file_from),
    )
    return directory_id


def update_file_from(cursor, directory_id: str, file_from: Optional[str]) -> None:
    """记录文件来源（``1`` 本地上传；知识库引用为其他值/空）。"""
    cursor.execute('UPDATE kb_directory SET file_from = %s WHERE id = %s',
                   (file_from, directory_id))


def get_children(kbase_id: str, parent_id: Optional[str],
                 dir_type: Optional[str] = None) -> list[dict]:
    """``getChildrenDirectoryList``：按最后修改时间倒序。"""
    sql = "SELECT * FROM kb_directory WHERE kbase_id = %s"
    params: list[Any] = [kbase_id]
    if parent_id:
        sql += ' AND parent_id = %s'
        params.append(parent_id)
    else:
        sql += ' AND parent_id IS NULL'
    if dir_type:
        sql += ' AND type = %s'
        params.append(dir_type)
    sql += ' ORDER BY updated_at DESC'
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return _rows(cursor)


def get_descendants(kbase_id: str, parent_id: Optional[str],
                    dir_type: Optional[str] = None) -> list[dict]:
    """取某目录的全部子孙。

    ``parent_id`` 非空走**递归 CTE**：基础查询 ``parent_id = ?``（**不含自身**），
    ``UNION ALL`` 递归，不追加额外的过滤条件。这个口径是真实的，保持。

    ``parent_id`` 为空走根目录语义。
    """
    if not parent_id:
        sql = "SELECT * FROM kb_directory WHERE kbase_id = %s"
        params: list[Any] = [kbase_id]
        if dir_type:
            sql += ' AND type = %s'
            params.append(dir_type)
        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return _rows(cursor)

    params: list[Any] = [kbase_id, parent_id]
    base_type_filter = recursive_type_filter = ''
    if dir_type:
        base_type_filter = ' AND type = %s'
        recursive_type_filter = ' AND d.type = %s'
        params.append(dir_type)
    params.append(kbase_id)          # 递归那半段也要 kbase_id
    if dir_type:
        params.append(dir_type)

    sql = (
        'WITH RECURSIVE descendants AS ('
        ' SELECT * FROM kb_directory WHERE kbase_id = %s AND parent_id = %s'
        + base_type_filter +
        ' UNION ALL'
        ' SELECT d.* FROM kb_directory d INNER JOIN descendants ds ON d.parent_id = ds.id'
        ' WHERE d.kbase_id = %s' + recursive_type_filter +
        ') SELECT * FROM descendants'
    )
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return _rows(cursor)


def delete_folders(cursor, directory_ids: Iterable[str]) -> int:
    """``deleteBatchIds`` 的等价物：**物理删除**目录行。"""
    ids = list(directory_ids)
    if not ids:
        return 0
    cursor.execute(
        "DELETE FROM kb_directory WHERE id = ANY(%s)",
        (ids,),
    )
    return cursor.rowcount


def titles_by_ids(kbase_id: str, file_ids: Iterable[str]) -> list[str]:
    """取这些文件/目录的 ``title``（= chunk 表里的 ``source``）。

    删文件时必须**在删除之前**取名字：切片表的 ``source`` 存的是文件名，
    先取名字、再 ``deleteBySource`` 清切片；顺序反了就清不到切片。
    """
    ids = list(file_ids)
    if not ids:
        return []
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT title FROM kb_directory WHERE kbase_id = %s AND id = ANY(%s)",
                (kbase_id, ids),
            )
            return [row[0] for row in cursor.fetchall() if row[0]]


def delete_files(cursor, kbase_id: str, file_ids: Iterable[str]) -> int:
    """``KbFileDao.deleteFiles``：物理删除文件行。"""
    ids = list(file_ids)
    if not ids:
        return 0
    cursor.execute(
        "DELETE FROM kb_directory WHERE kbase_id = %s AND id = ANY(%s)",
        (kbase_id, ids),
    )
    return cursor.rowcount


def get_all_folders(kbase_id: str) -> list[dict]:
    """``getAllDirsFromKbases(kbaseId, searchFile=false)``：只取文件夹。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM kb_directory WHERE kbase_id = %s AND type = 'folder'",
                (kbase_id,),
            )
            return _rows(cursor)


def get_files_by_ids(ids: Iterable[str], kbase_id: Optional[str] = None) -> list[dict]:
    """``kbFileDao.getFileList`` / ``queryMultiFiles`` 两个重载。

    ``kbase_id`` 给了就是 ``queryMultiFiles``（按库过滤），不给就是 ``getFileList``
    （**只按 id**，跨库也查得出来）—— 两处调用点不一样，别合并成一个。

    两者都直接按 id 查询。
    """
    wanted = [item for item in ids if item]
    if not wanted:
        return []
    sql = "SELECT * FROM kb_directory WHERE id = ANY(%s)"
    params: list[Any] = [wanted]
    if kbase_id:
        sql += ' AND kbase_id = %s'
        params.append(kbase_id)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return _rows(cursor)


def get_directory(directory_id: str, kbase_id: str,
                  dir_type: Optional[str] = None) -> Optional[dict]:
    """``querySingleFile``：按 id + kbaseId（+ 可选类型）取一行。"""
    sql = "SELECT * FROM kb_directory WHERE id = %s AND kbase_id = %s"
    params: list[Any] = [directory_id, kbase_id]
    if dir_type:
        sql += ' AND type = %s'
        params.append(dir_type)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = _rows(cursor)
    return rows[0] if rows else None


def update_title(cursor, directory_id: str, title: str) -> None:
    cursor.execute(
        "UPDATE kb_directory SET title = %s, updated_at = NOW() WHERE id = %s",
        (title, directory_id),
    )


def count_files(kbase_id: str) -> int:
    """``getFileCount``（见 ``kbase_store.count_files``，这里只是同库内的别名）。"""
    from knowledge_base.repository import kbase as kbase_store

    return kbase_store.count_files(kbase_id)


# ----------------------------------------------------------------------
# kb_directory_property（文件的 KType / file_size 等属性）
#
# 注意属性行挂在 **identifierId** 上而不是 fileId 上（见上传编排的规格）：
# 覆盖同名文件时两者可能不等价，保持不要「修正」。
# ----------------------------------------------------------------------


def get_properties(file_ids: Iterable[str], prop_name: str) -> dict[str, str]:
    """``getFilePropertiesByFileIds``：取指定属性名 → ``{file_id: prop_value}``。"""
    ids = list(file_ids)
    if not ids:
        return {}
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT file_id, prop_value FROM kb_directory_property "
                "WHERE file_id = ANY(%s) AND prop_name = %s",
                (ids, prop_name),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}


def get_all_properties(file_ids: Iterable[str]) -> dict[str, dict[str, str]]:
    """``getAllFilePropertiesByFileIds``：取全部属性 → ``{file_id: {prop: value}}``。"""
    ids = list(file_ids)
    if not ids:
        return {}
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT file_id, prop_name, prop_value FROM kb_directory_property "
                "WHERE file_id = ANY(%s)",
                (ids,),
            )
            result: dict[str, dict[str, str]] = {}
            for file_id, prop_name, prop_value in cursor.fetchall():
                result.setdefault(file_id, {})[prop_name] = prop_value
            return result


def create_property(cursor, kbase_id: str, file_id: str, prop_name: str, prop_value) -> None:
    """``createFileProperty``。"""
    cursor.execute(
        "INSERT INTO kb_directory_property "
        "(id, file_id, kbase_id, prop_name, prop_value) "
        "VALUES (%s, %s, %s, %s, %s)",
        (new_id(), file_id, kbase_id, prop_name, None if prop_value is None else str(prop_value)),
    )


def upsert_property(cursor, kbase_id: str, file_id: str, prop_name: str, prop_value) -> None:
    """写入文件属性：不存在则插入，存在则覆盖。

    覆盖上传会复用同一个 ``file_id``，属性行已在库里；直接 ``INSERT`` 会撞
    ``(file_id, prop_name)`` 唯一键（实测同名文件覆盖返回 500）。
    """
    cursor.execute(
        "INSERT INTO kb_directory_property "
        "(id, file_id, kbase_id, prop_name, prop_value) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (file_id, prop_name) DO UPDATE "
        "SET prop_value = EXCLUDED.prop_value, updated_at = NOW()",
        (new_id(), file_id, kbase_id, prop_name, None if prop_value is None else str(prop_value)),
    )


def update_property(cursor, kbase_id: str, file_id: str, prop_name: str, prop_value) -> None:
    """``updateFileProperty``：按 ``(kbase_id, file_id, prop_name)`` 更新。"""
    cursor.execute(
        "UPDATE kb_directory_property SET prop_value = %s, updated_at = NOW() "
        "WHERE kbase_id = %s AND file_id = %s AND prop_name = %s",
        (None if prop_value is None else str(prop_value), kbase_id, file_id, prop_name),
    )


def delete_properties_by_file_ids(kbase_id: str, file_ids: Iterable[str]) -> int:
    """物理删除这些文件的属性行。

    属性是文件的从属数据，删除文件后必须一并清掉：否则属性行永久残留
    （历史上出现过孤儿属性行），且 ``get_all_properties``
    会查到已删文件。

    ⚠️ 属性行理论上挂在 ``identifierId`` 上（覆盖上传时可能与 ``fileId`` 不等价），
    所以正常删除链只能清「file_id 恰好等于 file_id」的行。
    """
    ids = list(file_ids)
    if not ids:
        return 0
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'DELETE FROM kb_directory_property '
                'WHERE kbase_id = %s AND file_id = ANY(%s)',
                (kbase_id, ids),
            )
            return cursor.rowcount


def search_files_by_page(kbase_id: str, parent_id: Optional[str], keyword: Optional[str],
                         limit: int, offset: int) -> list[dict]:
    """``searchSubFileByPage``：某文件夹下的**文件**分页。"""
    where = ("kbase_id = %s AND type = 'file'"
             + (' AND parent_id = %s' if parent_id else ''))
    params: list[Any] = [kbase_id] + ([parent_id] if parent_id else [])
    if keyword:
        where += " AND title ILIKE '%%' || %s || '%%'"
        params.append(_escape_like(keyword))
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT * FROM kb_directory WHERE {where} '
                'ORDER BY updated_at DESC LIMIT %s OFFSET %s',
                params + [limit, offset],
            )
            return _rows(cursor)


def count_files_by_page(kbase_id: str, parent_id: Optional[str],
                        keyword: Optional[str]) -> int:
    """``searchSubFileCount``：与 :func:`search_files_by_page` 同 where、无 order/limit。"""
    where = ("kbase_id = %s AND type = 'file'"
             + (' AND parent_id = %s' if parent_id else ''))
    params: list[Any] = [kbase_id] + ([parent_id] if parent_id else [])
    if keyword:
        where += " AND title ILIKE '%%' || %s || '%%'"
        params.append(_escape_like(keyword))
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM kb_directory WHERE {where}', params)
            return int(cursor.fetchone()[0])


def search_all_files_by_page(kbase_id: str, keyword: Optional[str],
                             limit: int, offset: int) -> list[dict]:
    """``searchFileByPage``（V2）：整个库下的文件分页，**不带 parent_id 条件**。"""
    where = "kbase_id = %s AND type = 'file'"
    params: list[Any] = [kbase_id]
    if keyword:
        where += " AND title ILIKE '%%' || %s || '%%'"
        params.append(_escape_like(keyword))
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT * FROM kb_directory WHERE {where} ORDER BY updated_at DESC '
                'LIMIT %s OFFSET %s',
                params + [limit, offset],
            )
            return _rows(cursor)


def count_all_files(kbase_id: str, keyword: Optional[str]) -> int:
    where = "kbase_id = %s AND type = 'file'"
    params: list[Any] = [kbase_id]
    if keyword:
        where += " AND title ILIKE '%%' || %s || '%%'"
        params.append(_escape_like(keyword))
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM kb_directory WHERE {where}', params)
            return int(cursor.fetchone()[0])


def query_by_ktype(kbase_id: str, parent_id: Optional[str], k_type: str) -> list[dict]:
    """``queryFilesByKType``：按 ``kb_directory_property`` 的 ``KType`` 反查文件。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT td.id, td.kbase_id, td.title, td.status, td.parent_path, '
                'td.can_spread, td."type" FROM kb_directory td, kb_directory_property tdp '
                "WHERE td.id = tdp.file_id AND tdp.prop_name = 'KType' "
                "AND tdp.prop_value = %s AND td.kbase_id = %s AND td.parent_id = %s",
                (k_type, kbase_id, parent_id),
            )
            return _rows(cursor)


def _escape_like(keyword: str) -> str:
    """转义 LIKE 元字符（``%`` ``_`` ``\\`` ``/``）。"""
    return (keyword.replace('\\', '\\\\').replace('_', '\\_').replace('%', '\\%')
            .replace('/', '\\/'))


def update_file_status(cursor, file_id: str, status: int,
                       fail_reason: Optional[str] = None) -> None:
    """``KbFileDao.updateFileStatus``。

    两条注意的细节：
    * ``fail_reason`` **只有非空白才写** —— 传 null/"" 会**保留旧值**（失败原因跨状态残留）；
      想清空只能显式传别的东西。
    * 行不存在时**查不到就抛**，由上传链保证 fileId 一定存在。
    """
    cursor.execute(
        "SELECT id FROM kb_directory WHERE id = %s", (file_id,))
    if cursor.fetchone() is None:
        raise LookupError('file row not found: %s' % file_id)
    if fail_reason and fail_reason.strip():
        cursor.execute(
            'UPDATE kb_directory SET status = %s, fail_reason = %s, updated_at = NOW() '
            "WHERE id = %s",
            (status, fail_reason, file_id),
        )
    else:
        cursor.execute(
            'UPDATE kb_directory SET status = %s, updated_at = NOW() '
            "WHERE id = %s",
            (status, file_id),
        )


FILE_FAILED_STATUS = 2
FILE_PENDING_STATUS = 0


def claim_file_for_retry(cursor, file_id: str,
                         failed_status: int = FILE_FAILED_STATUS,
                         pending_status: int = FILE_PENDING_STATUS) -> bool:
    """手工重试的原子认领：``status 2 → 0`` 并清空 ``fail_reason``。

    ``WHERE status = 2`` 是关键 —— 连点两次重试只有第一次能认领成功，
    第二次拿不到行（返回 False），不会把同一个文件入队两次。
    ``update_file_status`` 清不掉 fail_reason（空白值会保留旧值），所以这里单开一条。
    """
    cursor.execute(
        'UPDATE kb_directory SET status = %s, fail_reason = NULL, updated_at = NOW() '
        'WHERE id = %s AND status = %s RETURNING id',
        (pending_status, file_id, failed_status))
    return cursor.fetchone() is not None


def get_operator(operator_id) -> Optional[dict]:
    """``operatorDao.selectOperatorById``：取算子行（删除 + 组织维度）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM operator WHERE id = %s", (operator_id,))
            rows = _rows(cursor)
    return rows[0] if rows else None


def get_operator_props(operator_id) -> dict:
    """``operator_prop`` 的 ``prop_name -> prop_value``（``position``/``operator`` 在这里）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT prop_name, prop_value FROM operator_prop "
                "WHERE operator_id = %s",
                (operator_id,),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}


def operator_python_path(operator_id) -> Optional[str]:
    """取算子的 ``operator_path``（执行时要的脚本路径）；查不到返回 None。"""
    operator = get_operator(operator_id)
    return operator.get('operator_path') if operator else None


def operator_authorize(operator_id) -> dict:
    """``AuthorizationService.operatorAuthorize``：算子不存在时**直接报错**。

    算子不存在时抛业务错误 **0005** + "Operator not found"。
    这个检查必须在调用文档处理模块 **之前** —— 否则会带着 ``pythonPath=null`` 去调，
    报出的是另一个（更晚、更含糊的）错误。
    """
    from shared.errors.api import KbApiError

    operator = get_operator(operator_id)
    if operator is None:
        raise KbApiError('RetCode.operator.notfound')
    return operator


def get_all_files(kbase_id: str) -> list[dict]:
    """库内**全部文件**（不分层级）。

    ``KbFileDao.searchFileByKbId`` —— ``GET /kbase/{id}/graph`` 的 ``fileInfo`` 用它。
    实测它**不按层级过滤**：返回值里有 ``parent_id`` 指向某个文件夹的文件，
    所以不能拿 ``get_children(kbase_id, None, ...)``（那只取根下的）来顶。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM kb_directory WHERE kbase_id = %s AND type = 'file'",
                (kbase_id,),
            )
            return _rows(cursor)
