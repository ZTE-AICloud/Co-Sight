"""算子域（``/operator`` 与 ``/operator``）。

五处「写错就会错」的地方：

1. **``module`` 会被改写**：只认四个枚举值，
   其余一律 ``rag_operator``。所以 ``retriever`` / ``pre-retriever`` 这些**环节名**在
   分页列表与 ``/operator/list`` 里全都显示成 ``rag_operator``。
   **但 ``GET /operator/{id}`` 不改写** —— 那条路径直接吐库里的原值。
2. **``args`` 可能是 ``null``**：分组 map 只含「有参数的算子」的键。
   写 ``[]`` 会让前端把「没有参数」和「参数列表为空」当成两回事（其实同义，但形状要对得上）。
3. **``defaultValue`` 的出口转换只发生在三处**：``/operator/support``、画布那条
   ``/rag_workflow/supported``、以及 ``/operator/import`` 的返回值。分页列表与
   ``/operator/list`` 吐的是**库里的原始字符串**（``"defaultValue": "100"``）。
   转换的规则见 :func:`convert_default_value`，**遇到不认识的 argType 显式报错**。
4. **系统算子不在库里**。``/operator/system`` 与 ``/operator/support`` 的第二段来自
   内置系统算子的固定清单（见 :mod:`system_operator`），不是 ``operator`` 表。
5. **``POST /operator`` 不做参数校验**，``currentPage`` /
   ``pageSize`` 缺一个就是 0001。而 ``POST /operator/support`` **有**参数校验，
   ``module`` 缺失在构造期就炸 → 0004 + ``RetCode.illegalArgument``（**默认语言**，
   不是请求语言）。

  **权限**：``GET /operator/{id}`` 与写状态那几条还有一层创建者校验
  （要求调用者就是 ``created_by``）。这里不加鉴权 ——
  后果是「非本人创建的算子」会正常返回数据，而不是
  0005「没有权限或已被删除」。这是**刻意行为**。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from infrastructure.http.pagination import page as paginate
from shared.errors.api import KbApiError, KbServerError
from operators.service import operator_import, system_operator
from operators.repository import operator_store
from infrastructure.logging.logutil import log

# ``OperatorTypeNameEnum``：顺序即 ``GET /operator/types`` 的返回顺序
OPERATOR_TYPES = (
    ('File parse operator', '文本解析算子', 'file_parse'),
    ('Text split operator', '文本切分算子', 'text_split'),
    ('Graph extract operator', '图提取算子', 'graph_extract'),
    ('RAG operator', 'RAG算子', 'rag_operator'),
)
DEFAULT_TYPE = 'rag_operator'

# ``OperatorPublicEnum``
PUBLISH = 1
UN_PUBLISH = 0

# ``OperatorVisibleRange``
VISIBLE_PUBLIC = 'public'
VISIBLE_PRIVATE = 'private'

# ``OperatorService.getOperators(String)`` 里写死的分页
V2_PAGE_SIZE = 5000

_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def normalize_module(module: Optional[str]) -> str:
    """``getOperatorType``：只认四类，其余一律 ``rag_operator``。"""
    for _label_en, _label_zh, value in OPERATOR_TYPES:
        if value == module:
            return value
    return DEFAULT_TYPE


# ----------------------------------------------------------------------
# VO 装配
# ----------------------------------------------------------------------


def _format_datetime(value):
    return value.strftime(_DATE_FORMAT) if value is not None else None


def _param_vo(param: dict) -> dict:
    """``OperatorParam``。键序固定（``placeholder`` 在 ``tips`` 之前）。"""
    return {
        'argName': param.get('arg_name'),
        'argType': param.get('arg_type'),
        'defaultValue': param.get('default_value'),
        'description': param.get('description'),
        'placeholder': _parse_json_map(param.get('placeholder')),
        'tips': _parse_json_map(param.get('tips')),
    }


def _parse_json_map(raw):
    """``tips`` / ``placeholder`` 库里存 JSON 文本，**解析失败只告警、字段留空**。

    注意与 ``convertDefaultValues`` 的区别：那里解析失败要抛，这里解析失败只是 log.warn。
    """
    if raw is None or raw == '':
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        log.warning('failed to parse operator param json: %s', str(raw)[:100])
        return None


def _operator_vo(row: dict, params, *, rewrite_module: bool, with_prop: bool = False) -> dict:
    """算子 VO 全字段（含 null），按固定声明顺序。

    :param params: ``None`` 表示「库里没有这个算子的参数行」—— 出口就是 ``args: null``；
                   传 ``[]`` 才是空列表。两者在 JSON 里不同。
    :param rewrite_module: 只有 ``GET /operator/{id}`` 是 ``False``。
    """
    vo = {
        'id': row.get('id'),
        'visibleRange': row.get('visible_range'),
        'version': row.get('version'),
        'module': normalize_module(row.get('module')) if rewrite_module else row.get('module'),
        'name': row.get('name'),
        'nameEn': row.get('name_en'),
        'description': row.get('description'),
        'descriptionEn': row.get('description_en'),
        'isPublished': 1 if row.get('is_published') else 0,
        'args': [_param_vo(p) for p in params] if params is not None else None,
        'prop': None,
        'system': None if row.get('system') is None else (1 if row.get('system') else 0),
        'createdDate': _format_datetime(row.get('created_at')),
        'createdBy': row.get('created_by'),
        'lastUpdatedDate': _format_datetime(row.get('updated_at')),
        'lastUpdatedBy': row.get('updated_by'),
    }
    if with_prop:
        # ``getOperator`` 会带上 prop（``{prop_name: prop_value}``），**空表给 null 不给 {}**
        props = operator_store.list_props_by_operator_id(row.get('id'))
        vo['prop'] = props or None
    return vo


def _vos_for_rows(rows: list[dict], *, rewrite_module: bool) -> list[dict]:
    """批量装配（分页列表 / v2 列表共用）。``args`` 保持 ``map.get(id)`` 的 null 语义。"""
    params = operator_store.list_params_by_operator_ids([row['id'] for row in rows])
    return [_operator_vo(row, params.get(row['id']), rewrite_module=rewrite_module)
            for row in rows]


def list_params_by_operator_ids(operator_ids: list[int]) -> dict:
    """Public read for other domains that inspect an operator's declared args."""
    return operator_store.list_params_by_operator_ids(operator_ids)


# ----------------------------------------------------------------------
# 分页列表
# ----------------------------------------------------------------------


def list_operators(payload: dict, emp_no: str, org_id: Optional[str]) -> dict:
    """``POST /operator``：``PageDTO<OperatorVO>``。

    ⚠️ 这两个参数**必填**，**不能**兜底 —— 缺值是 0001。给默认值会把一个暴露成
    500 的客户端错误悄悄变成 200。
    """
    current_page = payload.get('currentPage')
    page_size = payload.get('pageSize')
    if current_page is None or page_size is None:
        raise KbServerError('currentPage/pageSize is required')
    current_page = int(current_page)
    page_size = int(page_size)

    keyword = payload.get('keyword') or ''
    module = payload.get('module') or ''
    visible_range = payload.get('visibleRange')
    fmt = payload.get('format')

    # ``format`` 先查 operator_prop 拿 id 集合。查不到 → 空列表；而分页版
    # 对空列表是「不加 IN 条件」，于是 format 过滤**整个失效**、
    # 退化成全量查询。这是**真实的线上行为**（另一个重载遇到空列表才返回空）。
    operator_ids = operator_store.select_ids_by_format(fmt) if fmt else None

    total = operator_store.count_operators(
        operator_ids, visible_range, keyword, module, org_id, emp_no)
    if total == 0:
        return paginate([], 0, current_page, page_size)

    rows = operator_store.search_operators(
        operator_ids, visible_range, keyword, module, org_id, emp_no,
        limit=page_size, offset=(current_page - 1) * page_size)
    return paginate(_vos_for_rows(rows, rewrite_module=True),
                    total, current_page, page_size)


def list_by_module(module: str, emp_no: str, org_id: Optional[str]) -> list[dict]:
    """``GET /operator/list/{operatorType}``（真身路径是 ``/operator/list/...``）。

    走的是**分页重载** ``selectByCondition(空列表, null, "", module, page)``，
    所以**会**套可见性过滤（公开的 + 我私有的）。``module`` 会被改写。
    """
    rows = operator_store.search_operators(
        None, None, '', module, org_id, emp_no, limit=V2_PAGE_SIZE, offset=0)
    return _vos_for_rows(rows, rewrite_module=True)


def list_system_operators() -> list[dict]:
    """``GET /operator/system``：内置系统算子清单（不是库里的）。"""
    return system_operator.all_system_operators()


# ----------------------------------------------------------------------
# 画布：按环节取可运行算子
# ----------------------------------------------------------------------


def rag_workflow_supported(fmt: Optional[str], org_id: Optional[str]) -> list[dict]:
    """``GET /operator/rag_workflow/supported?format=``。

    这里的 ``format`` 参数**其实是 ``module``**（环节名）。**不校验 is_published、
    不做可见性过滤**（画布要能看到未发布的自定义算子）。``prop`` 缺失时
    ``position``/``operator`` 是字符串 ``"null"``（按字符串化口径，保持一致）。
    """
    rows = operator_store.select_by_module(fmt or '', org_id)
    if not rows:
        return []
    params = operator_store.list_params_by_operator_ids([row['id'] for row in rows])
    props = operator_store.list_props_by_operator_ids([row['id'] for row in rows])

    result = []
    for row in rows:
        prop = props.get(row['id']) or {}
        operator_params = params.get(row['id']) or []
        result.append({
            'id': row.get('id'),
            'position': _string_value_of(prop.get('position')),
            'operator': _string_value_of(prop.get('operator')),
            'operatorName': row.get('name'),
            'defaultArgs': {param['arg_name']: convert_default_value(
                param.get('arg_type'), param.get('default_value'))
                for param in operator_params},
        })
    return result


def _string_value_of(value):
    """字符串化：**null 变成字符串 ``"null"``**，而 Python 的
    ``str(None)`` 给的是 ``"None"``。画布直接读这两个字段，四个字符的差异会让它认不出算子。
    """
    return 'null' if value is None else str(value)


def convert_default_value(arg_type, value) -> Any:
    """按 ``argType`` 把库里的字符串转回真类型。

    ``argType`` 或值任一为空 → **原样返回**。认不出的 ``argType`` →
    **0004 + 那句英文原话**（这条消息不走 i18n，中英文都一样）。

    ``json`` 解析失败同理（``Invalid json default for arg ...``）。
    """
    if arg_type is None or value is None:
        return value
    kind = str(arg_type).lower()
    if kind == 'int':
        return int(value)
    if kind == 'str':
        return str(value)
    if kind == 'bool':
        # 布尔转换：非 "true" 一律 false
        return str(value).strip().lower() == 'true'
    if kind in ('float', 'double'):
        return float(value)
    if kind == 'json':
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            raise KbApiError(
                f'Invalid json default for arg {arg_type}: {value}',
                code='0004')
    raise KbApiError(f'Unsupported argType: {arg_type}', code='0004')


# ----------------------------------------------------------------------
# 单条查询
# ----------------------------------------------------------------------


def get_operator_row(operator_id) -> Optional[dict]:
    """Public row read for other domains (does not build a VO)."""
    return operator_store.select_by_id(operator_id)


def operator_python_path(operator_id) -> Optional[str]:
    """Execution path stored on the operator row; ``None`` when it is absent."""
    row = operator_store.select_by_id(operator_id)
    return row.get('operator_path') if row else None


def get_operator(operator_id) -> dict:
    """``GET /operator/{operatorId}``。

    **不改写 module**、带 ``prop``；查不到报「算子未找到」（0005）。
    这里不做创建者鉴权，见模块 docstring。
    """
    row = operator_store.select_by_id(operator_id)
    if row is None:
        raise KbApiError('RetCode.operator.notfound')
    params = operator_store.list_params_by_operator_id(operator_id)
    return _operator_vo(row, params, rewrite_module=False, with_prop=True)


# ----------------------------------------------------------------------
# 状态翻转
# ----------------------------------------------------------------------


def flip_publish(operator_id, emp_no: str, target: int) -> None:
    """``/publish`` 与 ``/un_publish``。

    **只有创建者本人**能操作（``selectOperatorByCreator``）；已经是目标状态时报
    「算子已发布，不能再发布」（取消发布时报的是**同一条**文案）。
    """
    row = operator_store.select_by_creator(operator_id, emp_no)
    if row is None:
        raise KbApiError('RetCode.operator.notfound')
    if bool(row.get('is_published')) == bool(target):
        raise KbApiError('RetCode.operator.publish.repeat')
    operator_store.set_publish_status(operator_id, bool(target), emp_no)


def flip_public(operator_id, emp_no: str, target: str) -> None:
    """``/public`` 与 ``/un_public``：同样只有创建者本人，重复设置报同一条文案。"""
    row = operator_store.select_by_creator(operator_id, emp_no)
    if row is None:
        raise KbApiError('RetCode.operator.notfound')
    if row.get('visible_range') == target:
        raise KbApiError('RetCode.operator.publish.repeat')
    operator_store.set_public_status(operator_id, target, emp_no)


def mark_system(operator_id, emp_no: str) -> None:
    """``POST /operator/system/{id}``。

    **没有创建者校验、没有重复校验** —— 但更新前先确认行存在，
    **查不到就是 0001**（不是 0005）。这条容易写错。
    """
    operator_store.update_system(operator_id, emp_no)


def delete_operator(operator_id, org_id: Optional[str]) -> None:
    """``POST /operator/delete/{id}``。

    ⚠️ 这道门用的是 ``selectOperatorByOrgId``，**不校验创建者**：``org_id`` 为空时
    任何人都能删任何算子（本实现不加权限）。

    顺序：先删 PVC 上的 python 脚本与 zip（失败只告警），再**删除除**三张表
    —— 是**物理删除**（连同 param/prop）。
    """
    row = operator_store.select_by_org_id(operator_id, org_id)
    if row is None:
        raise KbApiError('RetCode.operator.notfound')
    for column in ('operator_path', 'operator_zip_path'):
        _delete_pvc_file(row.get(column), operator_id, column)
    operator_store.delete_operator(operator_id)


def _delete_pvc_file(path: Optional[str], operator_id, column: str) -> None:
    """``PvcAccessService.delete``：删一个**绝对路径**文件，失败只告警不报错。"""
    if not path or not str(path).strip():
        return
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        log.warning('failed to delete operator file, operatorId=%s, %s=%s',
                    operator_id, column, path)


# ----------------------------------------------------------------------
# 类型列表与 support
# ----------------------------------------------------------------------


def operator_types() -> list[dict]:
    """``GET /operator/types``：四条固定枚举，字段名是 ``label_en``/``label_zh``/``value``。"""
    return [{'label_en': en, 'label_zh': zh, 'value': value}
            for en, zh, value in OPERATOR_TYPES]


def support(payload: dict, emp_no: str, org_id: Optional[str]) -> Optional[dict]:
    """``POST /operator/support``：``{format: [OperatorVO, ...]}``。

    ``formats`` 为空/缺失 → **``bo`` 是 null**（不是空 map）。

    每个 format 下 = 「库里声明支持该格式的已发布算子」**后接**「内置系统算子」。
    两段的行为差异：
    * 库里的那段**会**改写 ``module``、**会**做 ``convertDefaultValues``；
    * 系统算子那段已经是 VO 了，``convertDefaultValues`` 也会跑（对 ``int`` 的
      ``512`` 调 ``toString`` 再 parse，等于原值）。
    * 库里那段为空时**不**走 ``addAll``，但仍然只有系统算子 —— 结果一样。

    ``module`` 缺失/为 null → 0004 + ``RetCode.illegalArgument``。这里在入口显式检查。
    """
    module = payload.get('module')
    if module is None:
        raise KbApiError('RetCode.illegalArgument', code='0004')
    formats = payload.get('formats') or []
    if not formats:
        return None

    keyword = payload.get('keyword')
    result: dict[str, list[dict]] = {}
    for fmt in formats:
        ids = operator_store.select_ids_by_format(fmt)
        rows = operator_store.select_published_by_condition(ids, keyword, module, org_id, emp_no)
        vos = _vos_for_rows(rows, rewrite_module=True)
        vos.extend(system_operator.matching_system_operators(fmt, module))
        for vo in vos:
            for param in vo.get('args') or []:
                param['defaultValue'] = convert_default_value(
                    param.get('argType'), param.get('defaultValue'))
        result[fmt] = vos
    return result


# ----------------------------------------------------------------------
# 导入 / 导出 / 模板
# ----------------------------------------------------------------------

# ``spring.servlet.multipart`` 没设，用的是 ``operator.import.file-size-limit.rag_workflow``
IMPORT_LIMIT_BYTES = 2097152


# ``FileUtil`` 的分档常量：**1024 进制**（``KI_B = BYTE << 10``），不是 1000 也不是 2048
_SIZE_STEPS = (
    (1 << 60, 'EB'), (1 << 50, 'PB'), (1 << 40, 'TB'),
    (1 << 30, 'GB'), (1 << 20, 'MB'), (1 << 10, 'KB'),
)


def _readable_size(size: int) -> str:
    """``FileUtil.getReadableFileSize``：1024 分档 + ``DecimalFormat("#.##")``。

    这个字符串会直接拼进「算子包大小应限制在 {0} 以内」的文案里，所以格式要对得上：
    最多两位小数、**不留尾随零**；不足 1KB 时的单位是 ``Bytes``（不是 ``B``）。
    2097152 → ``"2 MB"``，512 → ``"512 Bytes"``。
    """
    for divider, unit in _SIZE_STEPS:
        if size >= divider:
            return f'{_decimal2(size / divider)} {unit}'
    return f'{_decimal2(size)} Bytes'


def _decimal2(value: float) -> str:
    """``new DecimalFormat("#.##").format(v)``：最多两位小数，尾随零去掉。"""
    text = f'{value:.2f}'
    return text.rstrip('0').rstrip('.') if '.' in text else text


def import_operator(filename: str, content: bytes, emp_no: str, org_id: str,
                    lang: str, *, operator_id: Optional[int] = None,
                    system: bool = False) -> dict:
    """``POST /operator/import``（multipart ``file``）。

    ``operator_id`` / ``system`` 只给内置算子播种用（见 ``operators.bootstrap``）；
    接口层不传，保持同一套 id 分配与 ``system`` 默认值。

    整条链**所有**失败都以 0005 + 内层文案返回（``OperatorService.importOperator``
    的 ``catch (Exception)`` 包装），见 :mod:`operator_import` 的模块说明。

    落盘顺序也要紧：``.py`` 在**名称校验之前**就写进了 PVC，zip 在校验**之后**才写。
    失败时把两个路径都删掉。
    """
    import tempfile

    if not filename or not filename.lower().endswith('.zip'):
        raise KbApiError('RetCode.operator.type.incorrect', code='0005')
    if len(content) > IMPORT_LIMIT_BYTES:
        raise KbApiError('RetCode.operator.workflow.import.sizecheck',
                         _readable_size(IMPORT_LIMIT_BYTES), code='0005')

    zip_relative = operator_import.new_relative_path(operator_import.OPERATOR_ZIP_PATH)
    python_relative = operator_import.new_relative_path(operator_import.OPERATOR_RELATIVE_PATH)

    with tempfile.TemporaryDirectory(prefix='prefix') as work_dir:
        operator_import._extract(content, Path(work_dir))
        manifest = operator_import.build_manifest(Path(work_dir), lang)
        python_path = operator_import.write_pvc(
            manifest['python_file'].read_bytes(), python_relative)
        try:
            operator_import.validate_script(python_path, manifest)
            operator_import.validate_operator_name(manifest, org_id)
            operator_import.validate_operator_description(manifest)
            zip_path = operator_import.write_pvc(content, zip_relative)
            row = operator_import.insert_operator(
                manifest, zip_path, python_path, emp_no, org_id,
                operator_id=operator_id, system=system)
        except Exception:
            operator_import.delete_pvc(python_relative)
            operator_import.delete_pvc(zip_relative)
            raise
    return _operator_vo(row, None, rewrite_module=False)


def export_operator(operator_id, org_id: Optional[str]) -> tuple[bytes, str]:
    """``GET /operator/export/{id}``：**原样吐上传时那个 zip**，不重新打包。

    文件名是 ``{id}-{module}-{yyyyMMddHHmmss}.zip``，``module`` 取库里的原值
    （不改写）。这里不做鉴权。
    """
    row = operator_store.select_by_org_id(operator_id, org_id)
    if row is None:
        raise KbApiError('RetCode.operator.notfound')
    return _stream_stored_zip(row)


def export_operator_by_name(operator_name: str, position: str,
                            org_id: Optional[str]) -> tuple[bytes, str]:
    """``GET /operator/exportByName``：按名字取**第一行**，再核对 ``position``。

    ``position`` 是 yml/画布里的算子在库里的 ``operator_prop.position``；
    对不上就报「算子未找到」。没有 ``operator`` 类型的算子（比如 text_split）
    也没有 ``position`` 这个 prop，所以传任何值都匹配不上。

    两处与路由层约定的次序：

    * ``operatorName`` 缺席 → 拿 null 去 ``name = NULL`` 查库 → 空 → 0005
      （**不是** 0004「参数不合法」，该参数是可选的）；
    * ``operatorName`` 命中、``position`` 缺席 → 对 null 调 ``.equals``
      → **NPE → 0001**。props 为空 Map 不算 NPE → 走 0005。
    """
    rows = operator_store.select_by_name(operator_name)
    if not rows:
        raise KbApiError('RetCode.operator.notfound')
    row = rows[0]
    props = operator_store.list_props_by_operator_id(row['id'])
    if position is None:
        # ``position`` 缺席按空指针处理 → 0001。显式抛比让 Python 自己 TypeError 清楚。
        raise KbServerError('exportByName: position is required by source-side NPE')
    if position != props.get('position'):
        raise KbApiError('RetCode.operator.notfound')
    return _stream_stored_zip(row)


def _stream_stored_zip(row: dict) -> tuple[bytes, str]:
    path = row.get('operator_zip_path')
    if not path:
        # 路径为 NULL → 0001
        raise KbServerError(f"operator {row.get('id')} has no zip path")
    try:
        content = Path(path).read_bytes()
    except OSError as error:
        # 库里路径在、盘上文件缺失（历史遗留数据）。
        #
        # 这里回 **0005「文件(夹)不存在」**：通用文案会劝用户「稍后重试」，
        # 而缺文件重试永远无用、只会掩盖数据问题。
        # 路径为 NULL（上一支）仍回 0001，那一支不动。
        log.error('operator zip unreadable: %s', path)
        raise KbApiError('RetCode.file.not.exist') from error
    from datetime import datetime

    filename = '%s-%s-%s.zip' % (row.get('id'), row.get('module'),
                                 datetime.now().strftime('%Y%m%d%H%M%S'))
    return content, filename


def operator_template_download(operator_type: str) -> tuple[bytes, str]:
    """``GET /operator/template/download``：classpath 上的模板 zip。"""
    return operator_import.template_bytes(operator_type)
