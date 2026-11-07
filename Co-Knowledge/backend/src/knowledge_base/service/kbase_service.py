"""知识库 VO 组装与只读查询。

三个端点各有**互不相同**的装配路径，必须分别实现：

===========================================  ==========================================
端点                                           装配路径
===========================================  ==========================================
``GET /kbase``                                 手写 builder（只设六个字段）
``GET /kbase/{id}``                            全字段 VO + props 覆盖
``POST /kbase/search``                         VO + 显式覆盖（见下）
===========================================  ==========================================

三者的差异是**真实的线上行为**，例如：

* ``GET /kbase`` 不设 ``tableName``（因此恒为 null，编排层的「默认工作流」分支
  拿不到库名 —— 见 :func:`list_authority_kbases` 的注释）；
* ``/kbase/search`` 把 ``failReason``/``schemaName``/``processDetailInfo`` 显式覆盖成
  空串，而 ``GET /kbase/{id}`` 的 ``schemaName`` 保持 null；
* 分页列表与详情的文件数同口径（删除已物理化，无需过滤）。

「顺手统一」这些差异等于一次没人要的行为变更，前端按字段读它们。
"""

from __future__ import annotations

from typing import Optional

from infrastructure.http.pagination import page
from infrastructure.http import binding
from infrastructure.logging.logutil import log
from shared.errors.api import KbApiError, KbValidatorError
from shared.i18n.messages import DEFAULT_LANGUAGE
from knowledge_base.repository import chunk as chunk_store
from knowledge_base.repository import kbase as kbase_store


#: 文档知识库分类（``kb_kbase.category``）。图谱库是 10，切片计数不适用。
CATEGORY_DOCUMENT = 1


def get_kbase_row(kbase_id: str) -> Optional[dict]:
    """Public read used by the retrieval and graph domains."""
    return kbase_store.select_kbase_by_id(kbase_id)


def list_all_kbases(org_id: Optional[str] = None) -> list[dict]:
    """Public list used by the agent domain."""
    return kbase_store.select_all_kbases(org_id)


def update_process(kbase_id: str, status: str, process: int) -> None:
    """Public progress update used by graph extraction."""
    kbase_store.update_process(kbase_id, status, process)


def update_process_with_time(kbase_id: str, status: str, process: int,
                             emp_no: str = '') -> None:
    kbase_store.update_process_with_time(kbase_id, status, process, emp_no)


def update_fail_reason(kbase_id: str, zh_msg: str, en_msg: str) -> None:
    """Public failure-reason update used by graph extraction."""
    kbase_store.update_fail_reason(kbase_id, zh_msg, en_msg)


def update_operator_id(operator_id, kbase_id: str) -> None:
    """Public graph-operator binding update."""
    kbase_store.update_operator_id(operator_id, kbase_id)


def update_schema(kbase_id: str, schema_id: str, schema_obj: Optional[dict]) -> None:
    """Public graph-schema update."""
    kbase_store.update_schema(kbase_id, schema_id, schema_obj)


def set_kbase_status_modified(kbase_id: str) -> None:
    """Public publish-state update used by graph write operations.

    ``c11be27`` moved the persistence layer from ``knowledge_base.store`` to
    ``knowledge_base.repository`` and replaced the module import in
    ``graph_write_service`` with this service module — but forgot to forward
    this function, so every entity/edge write failed *after* its graph storage
    write with an ``AttributeError``. Keep the public surface complete.
    """
    kbase_store.set_kbase_status_modified(kbase_id)


def generate_kbase_id() -> str:
    """Public id generation used by graph import when creating a kbase."""
    return kbase_store.generate_kbase_id()


def count_files(kbase_id: str) -> int:
    """Public file count used by graph import's empty-kbase reuse check."""
    return kbase_store.count_files(kbase_id)


def find_kbases_by_name(name: str, org_id: Optional[str] = None,
                        exclude_id: Optional[str] = None) -> list[dict]:
    """Public name lookup used by graph import's duplicate check."""
    return kbase_store.find_kbases_by_name(name, org_id, exclude_id=exclude_id)


def insert_kbase(kbase_id: str, name: str, description: str, kbase_type: str,
                 embedding_model: str, table_name: str, es_index_name: str,
                 category: int, status: str, file_count_limit: int,
                 org_id: Optional[str], created_by: str,
                 head_icon: Optional[str] = None) -> int:
    """Public insert used by graph import when creating a kbase."""
    return kbase_store.insert_kbase(
        kbase_id=kbase_id,
        name=name,
        description=description,
        kbase_type=kbase_type,
        embedding_model=embedding_model,
        table_name=table_name,
        es_index_name=es_index_name,
        category=category,
        status=status,
        file_count_limit=file_count_limit,
        org_id=org_id,
        created_by=created_by,
        head_icon=head_icon,
    )


# 这两项是**固定的初始值**，不是从库里读的：
#   splitMethod = "comprehensiveSplitter"
#   regex = "\\n\\n"
# metricType 不序列化。详情接口只覆写 embeddingModel。
DEFAULT_SPLIT_METHOD = 'comprehensiveSplitter'
DEFAULT_REGEX = '\\n\\n'

# 「有管理权限」分支的 action 值。本轮不做鉴权/权限，统一按「有管理权限」处理。
ACTION_MANAGER = 'm'

# 日期时间的序列化格式
_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# VO 的字段全集（顺序固定）。
# 每个字段都会出现在响应里（null 也发），
# 前端与编排层都按「字段存在」解析，所以 Python 侧也必须发全集。
# 两条装配路径（详情 / 列表 / 分页）共用这份清单，保证字段集合不会漏。
_KBASE_VO_FIELDS = (
    'id', 'pkId', 'name', 'headIcon', 'type', 'description', 'props', 'esIndexName',
    'embeddingModel', 'currentFileCount', 'fileCountLimit', 'createdBy', 'createdDate',
    'lastUpdatedBy', 'lastUpdatedDate', 'fullName', 'fullNameEn', 'tableName', 'action',
    'operatorId', 'failReason', 'status', 'schemaName', 'schemaObj', 'process',
    'processDetailInfo',
)


def _format_datetime(value) -> Optional[str]:
    if value is None:
        return None
    return value.strftime(_DATE_FORMAT)


def _localized_text(message_map) -> str:
    """取 zh_CN / en_US 文案。

    与 :func:`_localized_string_value` **不同**：那个键缺失时会产出字符串 ``"null"``；
    这个显式判 null 返回空串。别合并两者。
    """
    if message_map is None:
        return ''
    message = message_map.get('zh_CN')
    return '' if message is None else str(message)


def _base_vo(row: dict) -> dict:
    """VO 的字段**全集**，按固定顺序排。

    全字段输出（含 null）是刻意的：响应里每个字段都在，
    前端与编排层也都按「字段存在」解析。
    """
    return {
        'id': row.get('kbase_id'),
        'pkId': row.get('id'),
        'name': row.get('name'),
        'headIcon': row.get('head_icon'),
        'type': row.get('type'),
        'description': row.get('description'),
        'props': None,
        'esIndexName': row.get('es_index_name'),
        'embeddingModel': row.get('embedding_model'),
        'currentFileCount': None,
        'fileCountLimit': row.get('file_count_limit'),
        'createdBy': row.get('created_by'),
        'createdDate': _format_datetime(row.get('created_at')),
        'lastUpdatedBy': row.get('updated_by'),
        'lastUpdatedDate': _format_datetime(row.get('updated_at')),
        'fullName': None,
        'fullNameEn': None,
        'tableName': row.get('table_name'),
        'action': None,
        'operatorId': row.get('operator_id'),
        'failReason': None,
        'status': row.get('status'),
        'schemaName': None,
        'schemaObj': row.get('schema_obj'),
        'process': row.get('process'),
        'processDetailInfo': None,
    }


# ----------------------------------------------------------------------
# GET /kbase —— 列表（检索页的库选择器 +编排层）
# ----------------------------------------------------------------------


def list_authority_kbases(org_id: Optional[str] = None) -> list[dict]:
    """「有管理权限」分支的列表。

    ⚠️ **不设 ``tableName``**：这里的 builder 只有 pkId/id/type/name/esIndexName/
    headIcon/action 六个字段，其余保持 null。编排层的
    ``invoke_list_vector_knowledge_bases()`` 读的正是 ``tableName``，所以那条
    「默认工作流」分支在本栈里恒抛 ``knowledgebase-not-imported`` —— 这是**现存行为**，
    不在这里「修好」：即便填上真实表名 ``doc_<id>_vector``，运行时也会拼成
    ``data_data_...`` 而查不到表（历史遗留的坑）。

    返回按名称排序（中文按拼音/笔画）。
    """
    rows = kbase_store.select_all_kbases(org_id)
    return _sort_by_name([_authority_list_vo(row) for row in rows])


def _authority_list_vo(row: dict) -> dict:
    """这个 builder **只设这六个字段**，其余一律 null。

    逐个列出（而不是「用 :func:`_base_vo` 再清掉几个」）是因为这份清单本身就是契约：
    ``tableName``/``embeddingModel``/``currentFileCount`` 为 null 是前端与编排层
    的依赖输入，看到「这里少设了几个字段」时应当先怀疑是不是又踩了同一个坑。
    """
    vo = {field: None for field in _KBASE_VO_FIELDS}
    vo.update({
        'pkId': row.get('id'),
        'id': row.get('kbase_id'),
        'type': row.get('type'),
        'name': row.get('name'),
        'esIndexName': row.get('es_index_name'),
        'headIcon': row.get('head_icon'),
        'action': ACTION_MANAGER,
    })
    return vo


def _sort_by_name(vos: list[dict]) -> list[dict]:
    """按名称排序，使用**主强度**（大小写折叠）语义。

    主强度忽略大小写，实测顺序是 ``demo-kb, graph-e2e-kb,
    KB_20261011_143412, manual-test-kb``（d < g < K < m）。用码位序排会得到
    ``KB_...`` 在最前（``'K'``(75) < ``'d'``(100)），与线上不一致 —— 这是实测踩过的。

    ⚠️ **已知残差（中文）**：按**拼音**排序需要额外的拼音库，而运行镜像是
    slim 且没有 ``pypinyin``/``PyICU``、glibc 也没装 ``zh_CN`` locale，本函数对汉字
    退化成码位序。影响面是「中文名知识库之间的相对顺序」，不影响任何字段取值；
    真要对齐需给镜像加 ``pypinyin`` 依赖并改这一处。对比时若只有顺序不同，
    先看这里。
    """
    def key(vo: dict):
        name = vo.get('name') or ''
        # 主强度：大小写折叠；次强度：原名（保证同折叠值的顺序稳定可复现）
        return (name.lower(), name)

    return sorted(vos, key=key)


# ----------------------------------------------------------------------
# GET /kbase/{id} —— 详情
# ----------------------------------------------------------------------


def list_kbases_by_ids(ids) -> list[dict]:
    """按一组 id 取 VO（``POST /kbase/list/pk/id``）。

    ⚠️ 与 :func:`list_authority_kbases` 的 VO **不是同一份**：这条的 builder 多设了
    ``embeddingModel`` 与 ``tableName``（那两条线各写各的 builder）。别合并，
    前端/编排层按「字段有没有值」判断。
    """
    if not ids:
        return []
    rows = kbase_store.select_by_ids(ids)
    return [_pk_list_vo(row) for row in rows]


def _pk_list_vo(row: dict) -> dict:
    """这个 builder 设 pkId/id/type/name/esIndexName/headIcon/
    embeddingModel/tableName，其余 null；``action`` 统一补成管理权限。"""
    vo = {field: None for field in _KBASE_VO_FIELDS}
    vo.update({
        'pkId': row.get('id'),
        'id': row.get('kbase_id'),
        'type': row.get('type'),
        'name': row.get('name'),
        'esIndexName': row.get('es_index_name'),
        'headIcon': row.get('head_icon'),
        'embeddingModel': row.get('embedding_model'),
        'tableName': row.get('table_name'),
        'action': ACTION_MANAGER,
    })
    return vo


def get_kbase_or_raise(kbase_id: str) -> dict:
    """取单行，不存在时抛「知识库不存在」业务错误。"""
    row = kbase_store.select_kbase_by_id(kbase_id)
    if row is None:
        raise KbApiError('kbase.not.exist')
    return row


def get_kbase_for_aspect(kbase_id: str) -> dict:
    """按 ``orgId`` 查库的前置检查（不含鉴权）。

    这个检查必须发生在服务层任何入参校验（标题格式、目录存在性…）**之前** ——
    响应文案由它先定，否则会先报别的错。

    * 查到了 → 放行（**不做用户/组织鉴权**，见下）；
    * 查不到、``domainId`` 不是 ``-?\\d+`` → 0005「知识库不存在」；
    * 查不到、``domainId`` 像数字 → 按「查不到库」处理 → 0005「没有权限或已被删除」。

    调用方拿到行就说明「库存在」，可以继续业务逻辑。

    ## 两处有意不实现（与 ``get_kbase_detail`` 同款取舍）

    * 库存在时的用户/组织授权：这里**不增加鉴权**，库存在就放行。
    * 数字分支里「算子存在且 ``createdBy == 当前用户`` → 放行」那条路：要按 ``orgId``
      反查算子并把"当前用户"当契约，等价于把鉴权搬进来。这里统一按「数字 id 查不到库
      → 没有权限」处理 —— 实测的 32 个 ``0`` / ``999999`` 都落这一支。
    """
    row = kbase_store.select_kbase_by_id(kbase_id)
    if row is None:
        raise KbApiError('permission.denied' if _looks_numeric(kbase_id)
                         else 'kbase.not.exist')
    return row


def get_kbase_detail(kbase_id: str) -> dict:
    """知识库详情：VO + 文件数 + props 覆写。

    ## 库不存在时回什么，**取决于 id 像不像数字**

    业务级校验先跑，文案分派见 :func:`get_kbase_for_aspect`：

    * 库不存在、id 匹配 ``-?\\d+`` → 按「查不到库」处理 → 「没有权限或已被删除」；
    * 库不存在、id 不是纯数字 → 直接「知识库不存在」。

    实测两例正好各踩一边：32 个 ``0``（全数字）→ 没有权限；
    500 个 ``a``（非数字）→ 知识库不存在。**别只按其中一个改** ——
    统一回 ``kbase.not.exist`` 对前者错；统一回「没有权限」又对后者错。
    """
    row = get_kbase_for_aspect(kbase_id)
    vo = _base_vo(row)
    # from() 显式格式化的两个字段（schemaName 不在其中 → 保持 null）
    vo['failReason'] = _localized_text(row.get('fail_reason_obj'))
    vo['processDetailInfo'] = _localized_text(row.get('process_obj'))
    vo['currentFileCount'] = kbase_store.count_files(kbase_id)
    if str(row.get('category')) == str(CATEGORY_DOCUMENT):
        # 领域扩展（Knowledge Studio 独有）：详情页的「N 个切片」角标/指标卡直接用这个值，
        # 不再单独发 ``chunks?size=1`` 去拿分页信封里的 total。
        vo['chunkCount'] = _chunk_count(row)
    vo['props'] = {
        'embeddingModel': row.get('embedding_model'),
        'splitMethod': DEFAULT_SPLIT_METHOD,
        'regex': DEFAULT_REGEX,
    }
    return vo


def _chunk_count(row: dict) -> int:
    """文档库的切片总数（含向量表未建的新库 → 0）。

    计数失败只记日志并回 0：详情是主资源，不能因为一个派生聚合打不开。
    """
    try:
        return chunk_store.count_all(row)
    except Exception:                                              # noqa: BLE001
        log.warning('chunk count unavailable for kbase %s',
                    row.get('kbase_id'), exc_info=True)
        return 0


def _looks_numeric(kbase_id: str) -> bool:
    """``domainId.matches("-?\\\\d+")`` —— 权限切面用它决定走算子分支还是直接报不存在。"""
    import re

    return re.fullmatch(r'-?\d+', kbase_id or '') is not None


def is_kbase_empty(kbase_id: str) -> bool:
    """库里还有文件就抛业务错误，否则返回 True。

    库不存在时抛明确的业务错误（不是 500），且不影响任何真实调用方
    （前端只在已有库上点删除）。
    """
    get_kbase_or_raise(kbase_id)
    if kbase_store.count_files(kbase_id) > 0:
        raise KbApiError('kbase.can.not.delete.include.knowledge')
    return True




# ----------------------------------------------------------------------
# POST /kbase/search —— 分页
# ----------------------------------------------------------------------


def _validate_search(dto: dict, language: str = DEFAULT_LANGUAGE) -> None:
    """分页参数的校验（失败 → 0004）。

    ``currentPage`` 与 ``pageSize`` **没有「缺了就取默认值」这回事** —— 缺了就是 0004。

    文案是校验器的默认 message，**随 Accept-Language 走**：zh ``最小不能小于1`` /
    en ``must be greater than or equal to 1``，见 ``messages.py`` 的
    ``validator.*`` 三条（实测取值）。
    一次只可能违反一条（``null`` 只撞 ``@NotNull``；数字只撞上/下界之一）。

    范围是闭区间：``currentPage`` 1-10000、``pageSize`` 1-500。
    """
    current_page = dto.get('currentPage')
    _check_range(current_page, 1, 10000, language)

    page_size = dto.get('pageSize')
    _check_range(page_size, 1, 500, language)


def _check_range(value, minimum: int, maximum: int, language: str) -> None:
    if value is None:
        raise KbValidatorError('validator.notNull')
    if value < minimum:
        raise KbValidatorError('validator.min', minimum)
    if value > maximum:
        raise KbValidatorError('validator.max', maximum)


# 排序 key 的全集 —— 前端 ``orderList[].key`` 只能是这些。
# 未知值在绑定期就失败（0004），不是「忽略这一项」。⚠️ 还有
# ``description`` / ``currentFileCount``，但它们没有排序映射
# → 这两个 key 合法、只是排不上序（会被过滤掉）。
_ORDER_KEYS = frozenset({
    'id', 'name', 'embeddingModel', 'description', 'createdBy', 'createdDate',
    'currentFileCount',
})


def _bind_order_list(raw) -> list:
    """排序项的枚举绑定：``key`` 无效 → ``ValueError`` → 0004。

    两条约定：
    * ``key`` 为 ``null`` 是合法的（匹配不到 → 该项被丢弃，不影响其它项）；
      **非空且不在枚举里**的值才是绑定失败。
    * ``ascending`` 必须是布尔（``ORDER_FIELDS`` 兜底）。
    """
    items = binding.bind_objects(raw, binding.ORDER_FIELDS)
    for item in items or []:
        key = item.get('key')
        if key is not None and key not in _ORDER_KEYS:
            # 同一条 0004 通道
            raise ValueError(f'cannot deserialize KbaseOrderEnum from "{key}"')
    return items or []


def search_kbases(dto: dict, org_id: Optional[str] = None,
                  language: str = DEFAULT_LANGUAGE) -> dict:
    """分页搜索。

    返回 ``PageDTO`` 形态：``{recordsTotal, currentPage, pageSize, data}``。
    """

    # 绑定 → 校验：两者都在进入业务逻辑之前
    dto = binding.bind(dto, binding.SEARCH_FIELDS)
    order_list = _bind_order_list(dto.get('orderList'))
    _validate_search(dto, language)
    current_page = dto.get('currentPage') or DEFAULT_PAGE_NUM
    page_size = dto.get('pageSize') or DEFAULT_PAGE_SIZE
    keyword = dto.get('keyword') or ''
    categories = dto.get('categories')
    embedding_model = dto.get('embeddingModel')

    total = kbase_store.count_search_kbases(keyword, categories, embedding_model, org_id)
    if total == 0:
        return page([], total, current_page, page_size)

    rows = kbase_store.search_kbases(
        keyword, categories, embedding_model, org_id,
        limit=page_size, offset=(current_page - 1) * page_size,
        order_list=order_list,
    )
    counts = kbase_store.count_files_by_kbase_ids([row['kbase_id'] for row in rows])

    data = []
    for row in rows:
        vo = _base_vo(row)
        # 这几步由这里显式覆盖（与 GET /kbase 的列表不同）
        vo['failReason'] = _localized_string_value(row.get('fail_reason_obj'))
        vo['process'] = row.get('process')
        vo['processDetailInfo'] = _localized_string_value(row.get('process_obj'))
        # ⚠️ 列表里这两个字段**恒为空**，不是「有就填」。
        # ``schemaName`` 由「``schema_obj`` 非空 ? ... : ""」得到，
        # 而分页查询**没有加载 ``schema_obj``**，所以那个表达式
        # 永远走 null 分支 → ``schemaName=""``；``schemaObj`` 拷贝同样的 null → ``null``。
        # 带 schema 的图谱库在列表里也是 ``""`` / ``null``，只有详情端点才给真值。
        # 不要按「有就填」实现：``categories=null`` 一带上图谱库就会分叉。
        vo['schemaName'] = ''
        vo['schemaObj'] = None
        vo['currentFileCount'] = counts.get(row['kbase_id'], 0)
        vo['fullName'] = ''
        vo['fullNameEn'] = ''
        vo['action'] = ACTION_MANAGER
        data.append(vo)

    return page(data, total, current_page, page_size)


def get_kbase_stats(dto: dict, org_id: Optional[str] = None) -> dict:
    """``GET /knowledge-bases/stats``：按分类汇总，供列表页指标卡使用。

    返回 ``{'categories': [{category, total, fileTotal, statusCounts}]}``：

    * 请求里出现的分类**一定**有一项，库里没有数据时补全零 —— 前端不必自己兜默认值；
    * ``statusCounts`` 的键是数据库里的状态串（``'0'`` / ``'103'`` …），
      「哪些状态算就绪/进行中/失败」留在前端一处
      （``frontend/src/views/kBase/lib/overview-stats.ts``），避免两端各写一份口径；
    * 不传 ``categories`` 时返回库里现有的全部分类（按分类号升序）。

    指标卡用这个聚合端点：不要让前端用 ``size=500``（接口上限）把两个分类的
    全量列表拉回去自己数，库一多就是两条数百 KB 的响应。
    """
    categories = dto.get('categories')
    summary = kbase_store.summarize_kbases(categories, org_id)
    ordered = list(categories) if categories else sorted(summary)

    result = []
    for category in ordered:
        item = summary.get(category, {})
        result.append({
            'category': category,
            'total': int(item.get('total', 0)),
            'fileTotal': int(item.get('fileTotal', 0)),
            'statusCounts': dict(item.get('statusCounts', {})),
        })
    return {'categories': result}


def _localized_string_value(message_map) -> str:
    """格式化失败原因（**用字符串化语义**）。

    map 为 null 时返回空串；map 非 null 但缺键时，产出字符串 ``"null"``
    （不是空串，也不是 Python 的 ``"None"``）—— 分页列表里会原样出现。
    这是真实行为，别「修」掉：对比时这一处会一直对不上，排查起来更贵。
    """
    if message_map is None:
        return ''
    value = message_map.get('zh_CN')
    return 'null' if value is None else str(value)


DEFAULT_PAGE_NUM = 1
DEFAULT_PAGE_SIZE = 10


def list_embedding_model_names() -> list[str]:
    """本部署可用的 embedding **注册名**清单（建库/建图谱/画布向量检索节点共用的下拉源）。

    数据源 = **模型注册表**（模型管理页可增删，见 ``model``）。
    `kb_embedding` 表已不存在，不再有第二层回落；注册表读不到时返回空清单
    （与「一个都没注册」同义，页面会提示去模型管理页添加）。

    返回的是 ``model_name``（登记名）：``kb_kbase.embedding_model`` 记的是它。
    **不是** ``model_code``（发给端点那个）—— 两者是同一模型的两个命名空间，别混。
    """
    from model.resolver import embedding_models

    return embedding_models() or []


def list_embedding_models() -> list[str]:
    """``GET /embedding/all``。"""
    return list_embedding_model_names()


def is_ais_environment(deploy_plat_type: Optional[str]) -> bool:
    """``GET /kbase/ais``：``DEPLOY_PLAT_TYPE`` 是 AIS 或 V7（忽略大小写）。"""
    value = (deploy_plat_type or '').strip()
    return value.upper() in ('AIS', 'V7')


def deployed_by() -> Optional[str]:
    """``GET /environment``：环境变量 ``DEPLOYED_BY`` 原样返回（可能是 null）。"""
    import os

    return os.environ.get('DEPLOYED_BY')
