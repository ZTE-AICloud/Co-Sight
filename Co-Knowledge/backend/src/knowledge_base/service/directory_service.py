"""目录域（``/directory`` 与 ``/directory``）。

**VO 的字段大多不是直接来自行**：``file_size``/``props``/``kType`` 要回查
``kb_directory_property``，``idChain`` 由 ``parent_path`` 拼出来，``childList`` 是把列表内
按 ``parentId`` 重新挂树得到的，``errorMsg`` 只在 ``status==2`` 时才本地化填充。
这一整套装配顺序是**契约的一部分**，别按「更合理」的顺序重排。
"""

from __future__ import annotations

import re
from typing import Optional

from infrastructure.http.pagination import page as paginate
from infrastructure.http import binding
from shared.errors.api import KbApiError, KbValidationError
from knowledge_base.service.kbase_service import get_kbase_for_aspect
from knowledge_base.repository import chunk as chunk_store
from knowledge_base.repository import directory as directory_store
from infrastructure.logging.logutil import log

# 标题正则：``^[\p{IsHan}a-zA-Z0-9_.\- ]{2,30}$``。
# 用 CJK 统一表意文字的两段码位近似 ``\p{IsHan}``（扩展 A + 基本区）。
_TITLE_PATTERN = re.compile(r'[㐀-䶿一-鿿A-Za-z0-9_.\- ]{2,30}')

FILE = directory_store.TYPE_FILE
FOLDER = directory_store.TYPE_FOLDER

DEFAULT_PAGE_NUM = 1
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

# ``${folder.limit}`` / ``${directory.level.limit}``（application.yml:189-191）
FOLDER_LIMIT = 100
LEVEL_LIMIT = 3

# ``SysGlobalConst``
FILE_FAIL_STATUS = 2
FILE_RUNNING_STATUS = 0
FILE_SUCCESS_STATUS = 1

_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# ``DirectoryService``
TITLE_PATTERN_MIN, TITLE_PATTERN_MAX = 2, 30
_K_TYPE_PROP = 'KType'
_FILE_SIZE_PROP = 'file_size'


# ----------------------------------------------------------------------
# VO 装配
# ----------------------------------------------------------------------


def _format_datetime(value):
    return value.strftime(_DATE_FORMAT) if value is not None else None


def _flag(value):
    """DB boolean → 对外 ``'Y'/'N'``。"""
    if value is None:
        return None
    return directory_store.FLAG_ENABLE if value else directory_store.FLAG_DISABLE


def _base_vo(row: dict) -> dict:
    """按固定声明顺序给出全字段（含 null）。"""
    return {
        'id': row.get('id'),
        'kbaseId': row.get('kbase_id'),
        'title': row.get('title'),
        'parentId': row.get('parent_id'),
        'parentPath': row.get('parent_path'),
        'canSpread': _flag(row.get('can_spread')),
        'type': row.get('type'),
        'createdBy': row.get('created_by'),
        'createdDate': _format_datetime(row.get('created_at')),
        'lastUpdatedBy': row.get('updated_by'),
        'lastUpdatedDate': _format_datetime(row.get('updated_at')),
        'fileSize': None,
        'status': row.get('status'),
        'kType': None,
        'errorMsg': None,
        'childList': None,
        'props': None,
        'fileFrom': row.get('file_from'),
        'failReason': row.get('fail_reason'),
        'idChain': None,
    }


# 各端点的装配组合**互不相同**：
#   children          -> SortUtil + 全套
#   descendants       -> (可选 SortUtil) + 只有 fileSize/props/spreadState
#   search/pageFile   -> 全套但**不排序**
#   queryFilesByType  -> 不装配（只按名拷贝）
#   GET /{id}         -> 不装配
# 所以这里用显式开关，而不是一个「全装配」函数。
FULL_ASSEMBLY = {
    'file_size': True, 'props': True, 'spread_state': True,
    'k_type': True, 'fail_reason': True, 'id_chain': True,
}
DESCENDANTS_ASSEMBLY = {
    'file_size': True, 'props': True, 'spread_state': True,
    'k_type': False, 'fail_reason': False, 'id_chain': False,
}


def assemble(rows: list[dict], localize_error, steps: dict | None = None) -> list[dict]:
    """按端点各自的组合装配 VO。

    :param steps: 见 :data:`FULL_ASSEMBLY` / :data:`DESCENDANTS_ASSEMBLY`；
        不传表示**不装配**（``queryFilesByType`` 与 ``GET /{id}`` 就是这种）
    """
    vos = [_base_vo(row) for row in rows]
    if steps is None:
        return vos

    file_ids = [vo['id'] for vo in vos if vo['type'] == FILE]
    if steps.get('file_size'):
        _set_file_size(vos, file_ids)
    if steps.get('props'):
        _set_props(vos, file_ids)
    if steps.get('spread_state'):
        _reset_spread_state(vos)
    if steps.get('k_type'):
        _set_k_type(vos, file_ids)
    if steps.get('fail_reason'):
        _set_fail_reason(vos, localize_error)
    if steps.get('id_chain'):
        _set_id_chain(vos)
    for vo in vos:
        _reset_status(vo)
    return vos


# ⚠️ 这三个方法有个**反直觉**的共同形状：**只要列表里存在至少一个文件**，
# 就会给**所有**元素（含文件夹）都赋上「查不到就用默认值」的结果 ——
# 因为流程是先筛出文件 id 用于**查询**，再对**整个列表**赋值。
# 所以 descendants 里的文件夹会带着 fileSize=0 / props={} / kType="document"。
# 列表里一个文件都没有时整段跳过，文件夹保持 null（children 的顶层就是这样）。
def _set_file_size(vos: list[dict], file_ids: list[str]) -> None:
    if not file_ids:
        return
    sizes = directory_store.get_properties(file_ids, _FILE_SIZE_PROP)
    for vo in vos:
        # 缺省 '0'；非数字会抛（正常不会发生）
        vo['fileSize'] = int(sizes.get(vo['id'], '0'))


def _set_props(vos: list[dict], file_ids: list[str]) -> None:
    if not file_ids:
        return
    props = directory_store.get_all_properties(file_ids)
    for vo in vos:
        vo['props'] = props.get(vo['id'], {})


def _set_k_type(vos: list[dict], file_ids: list[str]) -> None:
    if not file_ids:
        return
    k_types = directory_store.get_properties(file_ids, _K_TYPE_PROP)
    for vo in vos:
        vo['kType'] = k_types.get(vo['id'], directory_store.DOCUMENT_TYPE)


def _set_fail_reason(vos: list[dict], localize_error) -> None:
    """只在 ``status == 2`` 且 ``failReason`` 有文本时填 ``errorMsg``；查不到就用原文。"""
    for vo in vos:
        if vo['status'] != FILE_FAIL_STATUS or not vo['failReason']:
            continue
        try:
            vo['errorMsg'] = localize_error(vo['failReason'])
        except Exception:
            vo['errorMsg'] = vo['failReason']


def _set_id_chain(vos: list[dict]) -> None:
    for vo in vos:
        vo['idChain'] = '%s-%s' % (vo['parentPath'], vo['id'])


def _reset_spread_state(vos: list[dict]) -> None:
    """把列表内按 ``parentId`` 挂成树，再把没有**文件夹**孩子的节点 ``canSpread`` 置 'N'。

    注意 ``childList`` 里**文件也算孩子**，而 ``canSpread`` 只认文件夹 —— 这个不对称是
    **真实的线上行为**。
    """
    node_map = {vo['id']: vo for vo in vos}
    for vo in vos:
        parent = node_map.get(vo['parentId'])
        if parent is not None:
            if parent['childList'] is None:
                parent['childList'] = []
            parent['childList'].append(vo)
    for vo in vos:
        children = vo['childList'] or []
        if not any(child['type'] == FOLDER for child in children):
            vo['canSpread'] = directory_store.FLAG_DISABLE


def _reset_status(vo: dict) -> None:
    """``resetStatus``：负状态（未完成的中间态）一律显示成 0。"""
    status = vo['status']
    if status is not None and status < FILE_RUNNING_STATUS:
        vo['status'] = FILE_RUNNING_STATUS


def sort_vos(vos: list[dict]) -> list[dict]:
    """排序：**文件夹在前**，然后按标题（大小写不敏感）。

    与 ``kbase_service._sort_by_name`` 同一套大小写折叠口径（主强度）。
    """
    def key(vo: dict):
        title = vo.get('title') or ''
        return (0 if vo.get('type') == FOLDER else 1, title.lower(), title)

    return sorted(vos, key=key)


# ----------------------------------------------------------------------
# 端点
# ----------------------------------------------------------------------


def _validate_title(title: Optional[str]) -> str:
    """标题校验：``^[\p{IsHan}a-zA-Z0-9_.\- ]{2,30}$`` 且不能全空白。

    ⚠️ 抛的是**业务错误（0005）不是校验错误（0004）**：这个校验是手写的，
    抛出的错误统一序列化成 ``0005``（``msgId=RetCode.BusinessError``），
    传进去的 0004 被丢弃。只有参数校验层触发的才走 0004 —— 实测过。
    """


    text = '' if title is None else title
    if not _TITLE_PATTERN.fullmatch(text) or not text.strip():
        raise KbApiError('directory.title.validation')
    return text.strip()


def list_children(kbase_id: str, parent_id: Optional[str], dir_type: Optional[str],
                  localize_error) -> list[dict]:
    """``GET /directory/children``。"""
    # 切面先查库：库不存在时**不会**走到「返回空列表」，而是 0005（见 get_kbase_for_aspect）
    get_kbase_for_aspect(kbase_id)
    vos = assemble(directory_store.get_children(kbase_id, parent_id, dir_type),
                   localize_error, FULL_ASSEMBLY)
    return sort_vos(vos)


def list_descendants(kbase_id: str, parent_id: Optional[str], dir_type: Optional[str],
                     sort: bool, localize_error) -> list[dict]:
    """``GET /directory/descendants``。

    ``sort`` 为真时按标题排；否则保持 SQL 出的顺序。
    """
    get_kbase_for_aspect(kbase_id)
    vos = assemble(directory_store.get_descendants(kbase_id, parent_id, dir_type),
                   localize_error, DESCENDANTS_ASSEMBLY)
    return sort_vos(vos) if sort else vos


def query_or_create_directory(kbase_id: str, title: str) -> str:
    """``DirectoryService.queryOrCreateDirectory``：库里**一个文件夹都没有**时才建。

    三处与 ``create_directory`` 不同，都是 **DAO 层**语义：

    * 不校验 title（``createDirectory`` 直接落库），也不判 ``FOLDER_LIMIT``；
    * 层级/重名判定在 DAO 里，顺序是**先层级后重名**（与 ``create_directory`` 相反）；
    * 根目录 ``parent_id`` 统一为 **NULL**（``parent_path = '0'``），
      重名判定与落库使用同一口径。

    这个方法建出来的就是抽图/导入链路里那个「默认文件夹」/「Default」。
    """
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM kb_directory WHERE kbase_id = %s AND type = %s",
                (kbase_id, FOLDER),
            )
            rows = cursor.fetchall()
            if rows:
                return rows[0][0]

            # 根目录统一用 NULL。
            parent_path = directory_store.get_parent_path(cursor, None)
            if len(parent_path.split(directory_store.PATH_SPLIT)) > LEVEL_LIMIT:
                raise KbApiError('directory.level.limit', LEVEL_LIMIT)
            if directory_store.find_folder_by_title(cursor, kbase_id, None, title):
                raise KbApiError('directory.already.exist', title)
            return directory_store.insert_directory(
                cursor, kbase_id, None, parent_path, title, FOLDER, status=None)


def create_directory(kbase_id: str, parent_id: Optional[str], title: Optional[str],
                     created_by: Optional[str] = None) -> dict:
    """``POST /directory``：建文件夹。

    ## 顺序：权限检查 → 标题 → 落库

    权限检查在标题校验**之前**跑：库不存在时回的是「知识库不存在」而**不是**
    标题校验的报错，更不会落库（顺序反了会把孤儿行写进 ``kb_directory``）。
    权限检查之后才是标题格式校验 → 文件夹数/层级/重名校验。
    """
    get_kbase_for_aspect(kbase_id)
    clean_title = _validate_title(title)
    # 根目录的 parentId 前端会传空串；落库统一成 NULL，和根查询/唯一索引保持同一口径。
    parent_id = parent_id or None

    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            if directory_store.count_children_folders(cursor, kbase_id, parent_id) >= FOLDER_LIMIT:
                raise KbApiError('directory.folder.size.over.limit')

            parent_path = directory_store.get_parent_path(cursor, parent_id)
            # 层级判据用 parent_path 的段数（在拼完路径之后判）
            if len(parent_path.split(directory_store.PATH_SPLIT)) > LEVEL_LIMIT:
                raise KbApiError('directory.level.limit', LEVEL_LIMIT)

            if directory_store.find_folder_by_title(cursor, kbase_id, parent_id, clean_title):
                raise KbApiError('directory.already.exist', clean_title)

            new_id = directory_store.insert_directory(
                cursor, kbase_id, parent_id, parent_path, clean_title, FOLDER, status=None,
                created_by=created_by)
            cursor.execute("SELECT * FROM kb_directory WHERE id = %s", (new_id,))
            columns = [d[0] for d in cursor.description]
            row = dict(zip(columns, cursor.fetchone()))

    # ⚠️ 建目录的响应**只做 resetStatus**，不跑那套 fileSize/props/idChain 装配 ——
    # 返回里 ``idChain`` 是 null。别「顺手」套 FULL_ASSEMBLY。
    vo = assemble([row], lambda key: key, None)[0]
    _reset_status(vo)
    return vo


def update_directory(kbase_id: str, directory_id: str, title: Optional[str]) -> dict:
    """``POST /directory/{id}``：改文件夹名（只能改文件夹）。

    ## 改名的失败文案矩阵

    ==========================  =========================================
    输入                        响应
    ==========================  =========================================
    库不存在                    0005「知识库不存在」（切面，先于一切）
    库在、目录不在              0005「目录不存在」（用户级校验 0005）
    库在、目录在、新名同级重名   0005「文件夹: {name} 在同级目录下已存在…」
    ==========================  =========================================

    「库不存在」这一格是切面给的，必须在 ``get_directory`` 之前判 —— 否则会错报成
    「目录不存在」（D4）。
    """
    get_kbase_for_aspect(kbase_id)
    row = directory_store.get_directory(directory_id, kbase_id, FOLDER)
    if row is None:
        raise KbApiError('directory.not.exist')

    clean_title = '' if title is None else title.strip()
    if not clean_title or clean_title == row.get('title'):
        return assemble([row], lambda key: key, None)[0]    # 空名或没变 → 原样返回

    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            if directory_store.find_folder_by_title(
                    cursor, kbase_id, row.get('parent_id'), clean_title):
                raise KbApiError('directory.already.exist', clean_title)
            directory_store.update_title(cursor, directory_id, clean_title)
            cursor.execute("SELECT * FROM kb_directory WHERE id = %s", (directory_id,))
            columns = [d[0] for d in cursor.description]
            updated = dict(zip(columns, cursor.fetchone()))

    vo = assemble([updated], lambda key: key)[0]
    _reset_status(vo)
    return vo


def move_files(kbase_id: str, file_ids: list[str], parent_id: str,
               emp_no: str = '') -> int:
    """把一批文档移动到同一知识库的目标文件夹。

    与上传时 `_save_one` 的 parent_path 口径一致：文件的 `parent_path` 取**目标文件夹
    自己的** `parent_path`（该值已经包含目标文件夹 id），不是 `get_parent_path()`。

    同目录重名沿用上传的 `file.upload.rename` 错误（409 file_name_conflict），
    前端据此提示「目标目录存在同名文档」。
    """
    get_kbase_for_aspect(kbase_id)

    ids = list(dict.fromkeys(item for item in (file_ids or []) if item))
    if not ids:
        raise KbValidationError('RetCode.illegalArgument')

    target = directory_store.get_directory(parent_id, kbase_id, FOLDER)
    if target is None:
        raise KbApiError('directory.not.exist')

    rows = directory_store.get_files_by_ids(ids, kbase_id)
    if len(rows) != len(ids) or any(row.get('type') != FILE for row in rows):
        raise KbApiError('file.not.exist')

    titles = [row.get('title') for row in rows if row.get('title')]
    if len(set(titles)) != len(titles):
        # 选中的文件来自不同目录，移动到同一目录后可能互相重名。
        raise KbApiError('file.upload.rename', ', '.join(sorted(set(titles))))
    moving_names = set(titles)
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT title FROM kb_directory WHERE kbase_id = %s AND parent_id = %s "
                "AND type = 'file' AND id <> ALL(%s)",
                (kbase_id, parent_id, ids))
            conflicts = moving_names.intersection(row[0] for row in cursor.fetchall() if row[0])
            if conflicts:
                raise KbApiError('file.upload.rename', ', '.join(sorted(conflicts)))

            cursor.execute(
                "UPDATE kb_directory SET parent_id = %s, parent_path = %s, "
                "updated_by = %s, updated_at = NOW() "
                "WHERE kbase_id = %s AND id = ANY(%s)",
                (parent_id, target.get('parent_path'), emp_no or None, kbase_id, ids))
    return len(ids)


def delete_directory_keep_files(kbase_id: str, directory_id: str,
                                emp_no: str = '') -> None:
    """删除文件夹但**保留文档**：文档与子目录中的文档先移到 Default，再删除目录树。

    语义是「仅移除目录，目录中的文档会移至 Default」。与
    :func:`delete_directory` 的递归删除不同，这里不碰 relation / 向量 / 磁盘文件。
    """
    get_kbase_for_aspect(kbase_id)
    row = directory_store.get_directory(directory_id, kbase_id, FOLDER)
    if row is None:
        raise KbApiError('directory.not.exist')
    if not row.get('parent_id'):
        # Default / 根目录不允许删除（UI 同样禁用）。
        raise KbApiError('directory.not.exist')

    descendants = directory_store.get_descendants(kbase_id, directory_id)
    file_rows = [item for item in descendants if item.get('type') == FILE]
    folder_ids = [item.get('id') for item in descendants if item.get('type') != FILE]
    file_ids = [item.get('id') for item in file_rows]

    roots = directory_store.get_children(kbase_id, None, FOLDER)
    default = next((item for item in roots
                    if item.get('title') == 'Default' and item.get('id') != directory_id), None)
    if default is None:
        default = next((item for item in roots if item.get('id') != directory_id), None)
    if default is None:
        raise KbApiError('directory.not.exist')

    titles = [item.get('title') for item in file_rows if item.get('title')]
    if len(set(titles)) != len(titles):
        # 目录树里不同子目录可能有同名文件；一起移到 Default 会冲突。
        raise KbApiError('file.upload.rename', ', '.join(sorted(set(titles))))
    moving_names = set(titles)
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT title FROM kb_directory WHERE kbase_id = %s AND parent_id = %s "
                "AND type = 'file' AND id <> ALL(%s)",
                (kbase_id, default.get('id'), file_ids or ['']))
            conflicts = moving_names.intersection(row[0] for row in cursor.fetchall() if row[0])
            if conflicts:
                raise KbApiError('file.upload.rename', ', '.join(sorted(conflicts)))

            if file_ids:
                cursor.execute(
                    "UPDATE kb_directory SET parent_id = %s, parent_path = %s, "
                    "updated_by = %s, updated_at = NOW() "
                    "WHERE kbase_id = %s AND id = ANY(%s)",
                    (default.get('id'), default.get('parent_path'), emp_no or None,
                     kbase_id, file_ids))
            directory_store.delete_folders(cursor, folder_ids + [directory_id])
    log.info('dissolved directory %s in kbase %s, kept %s files', directory_id,
             kbase_id, len(file_ids))


def delete_directory(kbase_id: str, directory_id: str, localize_error) -> None:
    """``POST /directory/delete/{id}``：删文件夹及其全部子孙。

    ## 成功时 ``bo`` 是 **null**

    被删列表只用于写操作日志，**没有放进响应** —— 所以信封里 ``bo`` 是 null。
    这也意味着装配**不能省**：装配阶段会抛的错误照旧要抛。

    失败文案矩阵与 :func:`update_directory` 相同（先库后目录，D4）：库不存在 →
    「知识库不存在」；库在、目录不在 → 「目录不存在」。
    """
    from knowledge_base.service import kbase_write_service

    get_kbase_for_aspect(kbase_id)
    row = directory_store.get_directory(directory_id, kbase_id, FOLDER)
    if row is None:
        raise KbApiError('directory.not.exist')

    descendants = directory_store.get_descendants(kbase_id, directory_id)
    # 装配结果**不用**（响应 bo 是 null），但必须算 —— 装配期的异常同样会发生。
    assemble(descendants + [row], localize_error, FULL_ASSEMBLY)
    kbase_write_service._delete_one_directory(
        kbase_id, _kbase_pk_id(kbase_id), directory_id, _storage())


def search_page_file(kbase_id: str, folder_id: Optional[str], keyword: Optional[str],
                     current_page: Optional[int], page_size: Optional[int],
                     localize_error) -> dict:
    """``POST /directory/search/pageFile``：某文件夹下的文件分页。

    查库放在 ``_page_params`` **之后**：次序必须是「请求体 DTO 校验（0004）→ 切面
    （0005）」，``_page_params`` 是最接近 DTO 校验的那一段。
    """
    page, size = _page_params(current_page, page_size)
    get_kbase_for_aspect(kbase_id)
    total = directory_store.count_files_by_page(kbase_id, folder_id, keyword)
    if total <= 0:
        return paginate([], 0, page, size)
    rows = directory_store.search_files_by_page(
        kbase_id, folder_id, keyword, limit=size, offset=(page - 1) * size)
    return paginate(assemble(rows, localize_error, FULL_ASSEMBLY),
                    total, page, size)


def search_all_files_page(kbase_id: str, keyword: Optional[str],
                          current_page: Optional[int], page_size: Optional[int],
                          localize_error) -> dict:
    """``POST /directory/search/pageFile/all``：整库文件分页（**不带 parent_id**）。

    次序同 :func:`search_page_file`：DTO 校验在前、切面在后。
    """
    page, size = _page_params(current_page, page_size)
    kbase = get_kbase_for_aspect(kbase_id)
    total = directory_store.count_all_files(kbase_id, keyword)
    if total <= 0:
        return paginate([], 0, page, size)
    rows = directory_store.search_all_files_by_page(
        kbase_id, keyword, limit=size, offset=(page - 1) * size)
    vos = assemble(rows, localize_error, FULL_ASSEMBLY)
    _attach_chunk_counts(kbase, vos)
    return paginate(vos, total, page, size)


def _attach_chunk_counts(kbase: dict, vos: list[dict]) -> None:
    """给「已可用」的文件行补 ``chunkCount``（文档列表「N 个切片」列）。

    一次 ``GROUP BY`` 覆盖整页，替代前端逐个文件发的 ``chunks?size=1`` 计数探针。
    处理中/失败的行不查也不加字段 —— 处理中查出来恒为 0，前端据此显示「—」
    （与 0.1.4 的既有语义一致）。计数失败只记日志，不拖垮文件列表。
    """
    file_ids = [vo['id'] for vo in vos
                if vo.get('type') == FILE
                and vo.get('id')
                and vo.get('status') == FILE_SUCCESS_STATUS]
    if not file_ids:
        return
    try:
        counts = chunk_store.count_by_files(kbase, file_ids)
    except Exception:                                              # noqa: BLE001
        log.warning('failed to count chunks for kbaseId: %s',
                    kbase.get('kbase_id'), exc_info=True)
        return
    for vo in vos:
        if vo.get('type') == FILE and vo.get('status') == FILE_SUCCESS_STATUS:
            vo['chunkCount'] = int(counts.get(vo['id'], 0))


def query_files_by_type(kbase_id: str, parent_id: Optional[str], k_type: Optional[str],
                        localize_error) -> list[dict]:
    """``GET /directory/queryFilesByType``：按 KType 反查，并**剔除运行中(status==0)的行**。"""
    get_kbase_for_aspect(kbase_id)
    rows = directory_store.query_by_ktype(kbase_id, parent_id, k_type or '')
    # ⚠️ 这条**不装配**：idChain/kType/props/fileSize 全是 null ——
    # 看起来「少了什么」，但那是既定行为。
    return assemble([row for row in rows if row.get('status') != FILE_RUNNING_STATUS],
                    localize_error, None)


# ``SysGlobalConst``：``type`` 的白名单（注意全是**字符串**，不是整数）
FILE_STR = 'file'
FOLDER_STR = 'folder'
KBASE_STR = 'kbase'
TYPE_LIST = (FILE_STR, FOLDER_STR, KBASE_STR)
# ``SysGlobalConst.ZERO``
ZERO = '0'
# ``DirectoryService.SPLIT``
ID_CHAIN_SPLIT = '-'

_VECTOR_FORMAT_KEY = 'knowledgeVector.format.incorrect'


def get_name_by_id(payload: dict) -> list[dict]:
    """``POST /directory/getNameById``：返回 ``{name, idChain, id, kbaseId}``。

    ## 入参校验：一条消息兜住所有情况

    底下四件事**回的是同一条 0005**「知识向量格式不正确」，分不出来也**不要**去分：

    * ``type`` 不在 ``["file","folder","kbase"]`` 里（含显式传 ``null``）
    * ``ids`` 是 ``null``
    * 某个 item 的 ``id`` 或 ``kbaseId`` 为空
    * ``type`` 缺席 —— **不算错**：DTO 的字段初始值是 ``"kbase"``，缺省走 kbase 分支

    ## 两处容易写错的地方

    * ``type`` 是 **String**，不是整数；传 ``1`` 会被
      请求体绑定转成 ``"1"`` 然后**照样**走到「不在白名单」那条 0005。
    * ``idChain`` 拼的是 ``parentPath + "-" + 目录行的 id``；而 ``setId`` 用的是
      **请求里的 id**，不是行里的主键。
    """
    from knowledge_base.repository import kbase as kbase_store

    payload = binding.bind(payload, binding.CONTENT_SEARCH_FIELDS)
    payload['ids'] = binding.bind_objects(payload.get('ids'), binding.RETRIEVE_CONTENT_FIELDS)

    # 缺席取 DTO 默认值 "kbase"；显式传 null 则保持 null（会被白名单拦下）
    item_type = payload['type'] if 'type' in payload else KBASE_STR
    if item_type not in TYPE_LIST:
        raise KbApiError(_VECTOR_FORMAT_KEY)

    items = payload.get('ids')
    if not isinstance(items, list):        # None / 非数组 → 同样用这一句兜住
        raise KbApiError(_VECTOR_FORMAT_KEY)
    for item in items:
        if not isinstance(item, dict):
            raise KbApiError(_VECTOR_FORMAT_KEY)
        if not (item.get('id') or '').strip() or not (item.get('kbaseId') or '').strip():
            raise KbApiError(_VECTOR_FORMAT_KEY)

    result = []
    for item in items:
        entry = {'name': None, 'idChain': None, 'id': None, 'kbaseId': None}
        try:
            if item_type in (FILE_STR, FOLDER_STR):
                row = directory_store.get_directory(item.get('id'), item.get('kbaseId'))
                if row:
                    entry.update({
                        'name': row.get('title'),
                        'idChain': f"{row.get('parent_path')}{ID_CHAIN_SPLIT}{row.get('id')}",
                        'id': item.get('id'),
                        'kbaseId': item.get('kbaseId'),
                    })
            elif item_type == KBASE_STR:
                # 查不到就留空条目（只打一条 info 日志）
                row = kbase_store.select_kbase_by_id(item.get('id'))
                if row:
                    entry.update({'name': row.get('name'), 'idChain': ZERO,
                                  'id': item.get('id'), 'kbaseId': item.get('id')})
        except Exception:
            log.warning('getNameById failed for %s', item, exc_info=True)
        result.append(entry)
    return result


def _page_params(current_page, page_size) -> tuple[int, int]:
    page = int(current_page or DEFAULT_PAGE_NUM)
    size = int(page_size or DEFAULT_PAGE_SIZE)
    if page < 1 or size < 1 or size > MAX_PAGE_SIZE:
        raise KbValidationError('request.invalid')
    return page, size


def _kbase_pk_id(kbase_id: str) -> int:
    from knowledge_base.repository import kbase as kbase_store

    row = kbase_store.select_kbase_by_id(kbase_id)
    return int(row['id']) if row else 0


def _storage():
    from infrastructure.storage import kb_storage as storage

    return storage
