"""算子导入／导出／模板下载。

**错误语义**：整条导入链包在统一异常处理里 —— 链内**任何**失败（包括本来想表达
0004 的那些）最终都是 **0005**，文案是内层异常已经渲染好的那句话。这里用
``KbApiError(key, code='0005')`` 表达，键与文案由最外层按请求语言渲染，效果相同。

**两个容易写错的点**：

1. ``config.json`` 里的 ``is_published`` 会被**校验但丢弃** —— 三个解析策略都写死
   ``isPublished = 1``。用户传 0 也存成 1。
2. ``operator_param`` / ``operator_prop`` 的批量插入 SQL **不写**
   ``created_by`` / 时间列 —— 靠 DDL 默认值，所以这两张表的 ``created_by`` 是 NULL。
"""

from __future__ import annotations

import ast
import io
import json
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any, Optional


from shared.errors.api import KbApiError
from infrastructure.storage.kb_storage import storage_root
from infrastructure.logging.logutil import log

# ``OperatorConst``
OPERATOR_NAME_LEN_MAX = 50
OPERATOR_DESC_LEN_MAX = 5000
ARGS_DESC_LEN_MAX = 5000
CONFIG_JSON = 'config.json'
OPERATOR_RELATIVE_PATH = 'operator'
OPERATOR_ZIP_PATH = 'operator_zip'
# ``VERSION_USER_REGEX``：x.y.z，每段不以 0 开头，整体不超过 32 字符
VERSION_USER_REGEX = re.compile(r'^(?=.{1,32}$)([1-9][\d]*)(\.(\d|[1-9][\d]*)){2}$')
CN_NAME_PATTERN = re.compile(r'^[一-龥A-Za-z0-9_]+$')
EN_NAME_PATTERN = re.compile(r'^[A-Za-z0-9_]+$')

# ``OperatorType``：注意 file_parse / text_split / graph_extract 三个模块共用「文件算子」这一支
FILE_OPERATOR = 'FILE_OPERATOR'
RAG_OPERATOR = 'RAG_OPERATOR'
FILE_OPERATOR_MODULES = ('file_parse', 'text_split', 'graph_extract')
RAG_OPERATOR_MODULES = ('pre-retriever', 'post-retriever', 'response-synthesizer', 'retriever')

# ``OperatorParamEnum``：**导入期只认这三种**，float/double/json 虽然读路径支持，但传不进来
PARAM_TYPES = {'str': str, 'int': int, 'bool': bool}

VALID_VISIBLE_RANGES = ('public', 'private')

#: 模块 → 进程内代码检查器**函数名**。
#:
#: 存函数名而不是函数对象，是为了**惰性**取 ``ingestion.runtime`` —— 本模块属
#: ``operators``，而 ``tests/`` 刻意保持「不依赖 app.py、在任何装了 fastapi/pytest
#: 的环境都能跑」。``ingestion.runtime`` 会连带拉进 pyaml_env / psycopg2 等 RKB
#: 运行期依赖，模块顶层引入会让宿主机上的用例直接收集失败。
CODE_CHECKERS = {
    'file_parse': 'code_check_file_parse',
    'text_split': 'code_check_text_split',
}
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / 'templates'

#: Top-level packages outside the v2 plugin interface.  The sandbox only exposes the
#: standard library and ``operator_api.*``; reject these imports at import time
#: with a clear error instead of failing later inside the sandbox.
UNSUPPORTED_PLUGIN_TOP_LEVELS = frozenset({
    'client', 'utility', 'service', 'split', 'doc_pipeline',
})


def _imported_top_levels(path: Path) -> set[str]:
    """Return the top-level packages imported by a plugin script."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split('.', 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split('.', 1)[0])
    return names


def validate_plugin_interface(path: Path) -> None:
    """Reject plugins that import modules outside the public interface."""
    unsupported = _imported_top_levels(path) & UNSUPPORTED_PLUGIN_TOP_LEVELS
    if unsupported:
        log.warning('operator plugin uses unsupported plugin imports: %s', sorted(unsupported))
        raise KbApiError('operator.plugin.incompatible', code='0005')


def operator_type_of(module: Optional[str]) -> Optional[str]:
    """``OperatorType.ofWithoutException``：认不出返回 None。"""
    if module in FILE_OPERATOR_MODULES:
        return FILE_OPERATOR
    if module in RAG_OPERATOR_MODULES:
        return RAG_OPERATOR
    return None


# ----------------------------------------------------------------------
# 解包
# ----------------------------------------------------------------------


def _decode_name(info: zipfile.ZipInfo) -> str:
    """zip 条目名解码：固定按 ``GB18030``。

    没置 UTF-8 标志位（0x800）时 Python 按 cp437 解 —— 中文名会成乱码，
    这里改按 gb18030 解。
    """
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode('cp437').decode('gb18030')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def _extract(content: bytes, target: Path) -> None:
    """带 zip-slip 防护地解包到 ``target``。

    跳过「无意义目录」条目、并对逃出目标目录的条目直接报错。
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        raise KbApiError('RetCode.zip.decompress.error', code='0005') from error

    base = target.resolve()
    with archive:
        for info in archive.infolist():
            name = _decode_name(info).replace('\\', '/')
            if info.is_dir() or name in ('', '/', '//'):
                continue
            destination = (base / name).resolve()
            if not str(destination).startswith(str(base) + '/') or destination == base:
                raise KbApiError('RetCode.zip.decompress.error', code='0005')
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                destination.write_bytes(archive.read(info))
            except Exception as error:
                raise KbApiError('RetCode.zip.decompress.error', code='0005') from error


def _files_deep(root: Path) -> list[Path]:
    """所有普通文件（**不排序**，与遍历顺序同性质）。"""
    return [path for path in root.rglob('*') if path.is_file()]


def _by_basename(paths: list[Path]) -> dict[str, Path]:
    """同名（不同目录）**后出现的赢**。"""
    result: dict[str, Path] = {}
    for path in paths:
        result[path.name] = path
    return result


# ----------------------------------------------------------------------
# config.json 解析与校验
# ----------------------------------------------------------------------


def _collect_violations(payload: dict, lang: str) -> list[str]:
    """参数校验，返回**已渲染**的违规消息（已排序）。

    ⚠️ 两处必须保持一致、否则文案对不上：

    1. **排序比的是渲染后的字符串**，不是键名。所以中英两种语言下的顺序**可能不同**
       —— 英文按 ASCII（``L`` < ``d``），中文按码点（``d`` < ``算``）。
       实测同一份 config.json：en 是 ``Length of operator name...;displayname.zh.notblank``，
       zh 是 ``display_name 为空;算子名称...``。用键名排序两边都是同一种顺序，是错的。
    2. **先渲染再 join**：这条消息是把校验器已经解析好的文案塞进
       ``RetCode.operator.configjson.configuration.incorrect`` 的 ``{0}``。
       把键名直接塞进去会原样吐出来。
    """
    problems: list[str] = []
    display_name = payload.get('display_name')
    if display_name is None:
        problems.append('RetCode.operator.displayName.check.notblank')
    elif not isinstance(display_name, dict):
        problems.append('RetCode.operator.displayname.zh.notblank')
    else:
        if not (display_name.get('zh') or '').strip():
            problems.append('RetCode.operator.displayname.zh.notblank')
        zh = display_name.get('zh') or ''
        if not (1 <= len(zh) <= OPERATOR_NAME_LEN_MAX):
            problems.append('RetCode.operator.name.check.len')

    desc = payload.get('desc')
    if desc is None:
        problems.append('RetCode.operator.desc.check.notblank')
    elif not isinstance(desc, dict):
        problems.append('RetCode.operator.desc.zh.notblank')
    elif not (desc.get('zh') or '').strip():
        problems.append('RetCode.operator.desc.zh.notblank')

    if payload.get('is_published') is None:
        problems.append('RetCode.operator.published.check.notnull')
    elif payload['is_published'] not in (0, 1):
        problems.append('isPublished must be either 0 or 1')

    if not payload.get('visibleRange'):
        problems.append('RetCode.operator.visibleRange.check.notnull')

    if not (payload.get('module') or '').strip():
        problems.append('RetCode.operator.module.check.notblank')

    version = payload.get('version')
    if not (version or '').strip():
        problems.append('RetCode.operator.versionUser.check.notblank')
    elif not VERSION_USER_REGEX.match(version):
        problems.append('RetCode.operator.versionUser.check.regex')

    if payload.get('defaultArgs') is None:
        problems.append('RetCode.operator.defaultArgs.check.not.blank')

    if 'supportedFormat' in payload:
        if not payload.get('supportedFormat'):
            problems.append('RetCode.operator.supportedFormat.check')
    else:
        # 文件算子一支才要求 supportedFormat；RAG 算子要求 operator / package
        if not (payload.get('operator') or '').strip():
            problems.append('RetCode.operator.operator.check.notblank')
        if not (payload.get('package') or '').strip():
            problems.append('RetCode.operator.position.check.notblank')
    from shared.i18n.messages import render

    return sorted(render(key, lang) for key in problems)


def _check_params(params) -> None:
    """``OperatorConfigParse.checkParams``：重名、类型、默认值与类型是否匹配。"""
    seen = set()
    for param in params or []:
        name = param.get('argName')
        if name in seen:
            raise KbApiError('RetCode.operator.arg.name.incorrect', code='0005')
        seen.add(name)

        arg_type = param.get('argType')
        if arg_type not in PARAM_TYPES:
            raise KbApiError('RetCode.operator.arg.type.incorrect', code='0005')

        value = param.get('defaultValue')
        if value is not None and not _value_matches(arg_type, value):
            raise KbApiError('RetCode.operator.arg.defaultValue.incorrect', arg_type, code='0005')


def _value_matches(arg_type: str, value: Any) -> bool:
    """``OperatorParamEnum.checkParam``：``class.isInstance(value)``。

    ⚠️ 是**真正的类型判断**，不做字符串转换 —— ``{"argType":"int","defaultValue":"1"}``
    在导入期是**不合法**的，而读路径的 ``convertDefaultValues`` 又会把字符串转成 int。
    两边口径不同，保持。
    """
    expected = PARAM_TYPES[arg_type]
    try:
        return isinstance(value, expected)
    except TypeError:
        return False


def build_manifest(work_dir: Path, lang: str) -> dict:
    """``buildBOFromConfigFile``：定位 config.json、选策略、解析、校验、找 .py。"""
    files = _files_deep(work_dir)
    by_name = _by_basename(files)

    config_path = by_name.get(CONFIG_JSON)
    if config_path is None:
        raise KbApiError('RetCode.operator.configjson.notfound', code='0005')

    # ``getTypeFromJsonFile`` 先单独把 module 抠出来，规则很别扭：
    #   config.json 不是合法 JSON      → module = null        → 「算子类型不支持」
    #   module 键缺失 / 值是 null 与否 → 见下（null 与非 null 走的是两条分支）
    #   顶层不是对象（如 [1,2,3]）     → module = ""          → 「module 为空」
    try:
        payload = json.loads(config_path.read_text(encoding='utf-8'))
    except Exception:
        raise KbApiError('RetCode.operator.type.not.support', code='0005')

    if isinstance(payload, dict):
        if 'module' in payload and payload['module'] is None:
            # 空值节点转成字符串 "null"，非空 → 落到「认不出类型」
            raise KbApiError('RetCode.operator.type.not.support', code='0005')
        module = payload.get('module')
        module = '' if module is None else str(module)
    else:
        module = ''      # ``path("module")`` 命中 MissingNode → ``asText()`` 是空串
    if not module.strip():
        raise KbApiError('RetCode.operator.module.check.notblank', code='0005')
    kind = operator_type_of(module)
    if kind is None:
        raise KbApiError('RetCode.operator.type.not.support', code='0005')

    problems = _collect_violations(payload, lang)
    if problems:
        raise KbApiError('RetCode.operator.configjson.configuration.incorrect',
                         ';'.join(problems), code='0005')

    default_args = payload.get('defaultArgs') or []
    _check_params(default_args)

    visible_range = payload.get('visibleRange')
    if visible_range not in VALID_VISIBLE_RANGES:
        raise KbApiError('RetCode.operator.arg.visibleRange.incorrect', code='0005')

    python_files = [path for path in files if path.name.endswith('.py')]
    if not python_files:
        raise KbApiError('RetCode.operator.python.not.found', code='0005')
    if kind == FILE_OPERATOR and len(python_files) != 1:
        raise KbApiError('RetCode.operator.python.exist.more', code='0005')

    display_name = payload['display_name']
    desc = payload['desc']
    if kind == FILE_OPERATOR:
        prop = {'support_format': payload.get('supportedFormat')}
        operator_id = payload.get('id')
    else:
        prop = {'operator': payload.get('operator'), 'position': payload.get('package')}
        operator_id = None       # RAGOperatorConfigParse **不**搬运 id

    return {
        'id': operator_id,
        'visibleRange': visible_range,
        'version': payload.get('version'),
        'module': module,
        'name': display_name.get('zh'),
        'nameEn': display_name.get('en'),
        'description': desc.get('zh'),
        'descriptionEn': desc.get('en'),
        'isPublished': 1,        # 写死 1，忽略 config.json 里的值
        'defaultArgs': default_args,
        'prop': prop,
        'kind': kind,
        'python_file': python_files[0],
    }


# ----------------------------------------------------------------------
# 名称／描述校验
# ----------------------------------------------------------------------


def validate_operator_name(manifest: dict, org_id: Optional[str]) -> None:
    """``validateOperatorName``：中文名 trim、英文名去掉**所有**空格后再校验。"""
    from operators.repository import operator_store

    name = (manifest.get('name') or '').strip()
    name_en = (manifest.get('nameEn') or '').replace(' ', '')
    if not name or not name_en:
        raise KbApiError('RetCode.operator.name.check.notblank', code='0005')
    if not CN_NAME_PATTERN.match(name) or len(name) > OPERATOR_NAME_LEN_MAX:
        raise KbApiError('RetCode.operator.name.invalid.cn', code='0005')
    if not EN_NAME_PATTERN.match(name_en) or len(name_en) > OPERATOR_NAME_LEN_MAX:
        raise KbApiError('RetCode.operator.name.invalid.en', code='0005')
    # 查重**不带 org 过滤**（只有 name 一个条件）
    if operator_store.select_by_name(name):
        raise KbApiError('RetCode.operator.name.duplicate', code='0005')
    manifest['name'] = name
    manifest['nameEn'] = name_en


def validate_operator_description(manifest: dict) -> None:
    description = manifest.get('description') or ''
    description_en = manifest.get('descriptionEn') or ''
    if not description or not description_en:
        raise KbApiError('RetCode.operator.description.check.notblank', code='0005')
    if len(description) > OPERATOR_DESC_LEN_MAX or len(description_en) > OPERATOR_DESC_LEN_MAX:
        raise KbApiError('RetCode.operator.description.check', code='0005')


# ----------------------------------------------------------------------
# 远端脚本校验
# ----------------------------------------------------------------------


def validate_script(path: Path, manifest: dict) -> None:
    """``validateScript``：先校验插件接口，再按模块做代码检查。

    接口校验适用于所有模块：导入 ``client.*`` / ``utility.*`` 等旧顶层包的脚本
    会以 ``operator_plugin_incompatible`` 拒绝（见 :func:`validate_plugin_interface`）。

    检查改为**进程内直调**
    ``ingestion.runtime``。脚本检查不通过 → 「自定义算子内容校验不通过」。

    ⚠️ 有**两条**失败路径：传输失败 → ``RetCode.operator.parse.error``；
    业务码非 ``0000`` → ``RetCode.operator.textsplit.code.checkNotPass``。
    进程内之后**没有传输层可失败**，两条合并为后者 —— 检查器抛出的任何异常
    （语法错误、签名不符、``ParameterValidationError``…）都归为「校验不通过」，
    与原 HTTP 世界里的表现一致（那时检查器异常经信封回 ``code='0001'``，
    同样落 ``checkNotPass`` 分支）。
    """
    if not path.exists() or not path.is_file():
        raise KbApiError('RetCode.operator.storage.insufficient', code='0005')
    validate_plugin_interface(path)
    checker_name = CODE_CHECKERS.get(manifest['module'])
    if checker_name is None:
        return
    parameters = {param.get('argName'): param.get('argType')
                  for param in manifest.get('defaultArgs') or []}
    from ingestion import runtime  # 惰性，见 CODE_CHECKERS 的说明
    checker = getattr(runtime, checker_name)
    try:
        checker(str(path), parameters)
    except KbApiError:
        raise
    except Exception as error:
        log.warning('operator code-check not passed: %s', error)
        raise KbApiError('RetCode.operator.textsplit.code.checkNotPass', code='0005') from error


# ----------------------------------------------------------------------
# 落盘与入库
# ----------------------------------------------------------------------


def pvc_path(relative: str) -> Path:
    """``PvcAccessService.save`` 的目标绝对路径：``<pvcMainPath>/<relativePath>``。

    ⚠️ 算子包**始终留在本地卷**（即使 ``RKB_STORAGE_BACKEND=minio``）：
    ``operator.operator_path`` 进库的是绝对路径，且执行时要在子进程里直接跑脚本。
    """
    return storage_root() / relative


def write_pvc(content: bytes, relative: str) -> Path:
    """``PvcAccessService.save``：建父目录 + 写文件，返回绝对路径（进库的就是它）。"""
    path = pvc_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def delete_pvc(relative_or_absolute) -> None:
    """``PvcAccessService.deletePvcFiles``：删失败只告警。"""
    if not relative_or_absolute:
        return
    try:
        Path(relative_or_absolute).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        log.warning('failed to delete pvc file %s', relative_or_absolute)


def insert_operator(manifest: dict, zip_path: Path, python_path: Path,
                    emp_no: str, org_id: str, *,
                    operator_id: Optional[int] = None,
                    system: bool = False) -> dict:
    """``saveUploadFiles`` 的三条 INSERT，返回**内存里的** ``OperatorPO``（供装 VO）。

    ``operator_id`` / ``system`` 只给**内置算子播种**用：内置算子沿用内部产品的
    负数 id（``id`` 是 ``GENERATED BY DEFAULT``，可显式指定）。API 导入不传这两个
    参数（id 由序列分配、``system`` 走 DDL 默认 false）。

    ⚠️ 返回的不是「重新查出来的那行」。插入完手里拿的是**刚构造的对象**，
    而 ``INSERT`` 把值为 null 的列整个略过 —— ``system`` 从没进过这张 insert，
    所以 **对象上的 ``system`` 是 null**，响应里也就是 null（哪怕库里实际是 DDL 默认的 0）。
    重新 ``select`` 一次会把 0 读回来，那是**和线上不一样**的。
    """
    from infrastructure.db.kb import connection

    with connection() as conn:
        with conn.cursor() as cursor:
            # 默认不写 ``system``（null 列被跳过）→ 吃 DDL 默认 false
            columns = ['name', 'name_en', 'description', 'description_en', 'module',
                       'version', 'operator_zip_path', 'operator_path', 'visible_range',
                       'is_published', 'org_id', 'created_by', 'updated_by']
            values: list[Any] = [
                manifest['name'], manifest['nameEn'], manifest['description'],
                manifest['descriptionEn'], manifest['module'], manifest['version'],
                str(zip_path), str(python_path), manifest['visibleRange'],
                bool(manifest['isPublished']), org_id or '', emp_no, emp_no]
            if operator_id is not None:
                columns.insert(0, 'id')
                values.insert(0, operator_id)
            if system:
                columns.append('system')
                values.append(True)
            cursor.execute(
                'INSERT INTO operator (' + ', '.join(columns) + ') VALUES ('
                + ', '.join(['%s'] * len(columns))
                + ') RETURNING id, created_at, updated_at',
                tuple(values))
            new_id, created_at, updated_at = cursor.fetchone()

            # 这两张表的批量插入 SQL **不含** created_by / 时间列
            for param in manifest.get('defaultArgs') or []:
                cursor.execute(
                    'INSERT INTO operator_param (operator_id, arg_name, arg_type, '
                    'default_value, description, tips, placeholder) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                    (new_id, param.get('argName'), param.get('argType'),
                     _as_text(param.get('defaultValue')), param.get('description') or '',
                     _json_or_null(param.get('tips')), _json_or_null(param.get('placeholder'))))
            for name, value in (manifest.get('prop') or {}).items():
                cursor.execute(
                    'INSERT INTO operator_prop (operator_id, prop_name, prop_value) '
                    'VALUES (%s,%s,%s)',
                    (new_id, name, _prop_text(value)))

    # 与「刚插进去的那个 PO 对象」对齐：API 导入时 system 没被 insert 过 → null
    return {
        'id': new_id,
        'visible_range': manifest['visibleRange'],
        'version': manifest['version'],
        'module': manifest['module'],
        'name': manifest['name'],
        'name_en': manifest['nameEn'],
        'description': manifest['description'],
        'description_en': manifest['descriptionEn'],
        'is_published': bool(manifest['isPublished']),
        'system': True if system else None,
        'created_at': created_at,
        'created_by': emp_no,
        'updated_at': updated_at,
        'updated_by': emp_no,
        'operator_path': str(python_path),
        'operator_zip_path': str(zip_path),
        'org_id': org_id or '',
    }


def _as_text(value) -> Optional[str]:
    """``defaultValue`` 是 varchar：存的是对象字符串化的结果。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def _json_or_null(value) -> Optional[str]:
    """``tips`` / ``placeholder``：空 Map 存 NULL（只在非空时序列化）。"""
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False)


def _prop_text(value) -> str:
    """``propValue`` 是 varchar，存的是对象字符串化的结果。

    ``support_format`` 是 List —— 列表字符串化是 ``"[md, txt]"``
    （逗号 + 空格），而 ``json.dumps`` 给的是 ``'["md", "txt"]'``。**必须用前一种写法**，
    因为读路径的 ``selectByFormat`` 是拿它做 ``LIKE '%fmt%'`` 子串匹配的。
    """
    if isinstance(value, (list, tuple)):
        return '[' + ', '.join(str(item) for item in value) + ']'
    if value is None:
        return None
    return str(value)


# ----------------------------------------------------------------------
# 模板下载
# ----------------------------------------------------------------------


def template_bytes(operator_type: str) -> tuple[bytes, str]:
    """直接吐模板 zip 字节。

    未知 ``operatorType`` 时找不到资源 → **0005 且 msg 为 null**。
    这里用带键的 0005 表达；文案差异见模块 docstring 的说明。
    """
    path = TEMPLATE_DIR / f'{operator_type}.zip'
    if not path.is_file():
        # key=None → 信封里 msg 是 null（不带文案）
        raise KbApiError(None, code='0005')
    return path.read_bytes(), f'{operator_type}.zip'


def new_relative_path(folder: str) -> str:
    """``OPERATOR_RELATIVE_PATH + / + UUID32``（32 位十六进制，**不带扩展名**）。"""
    return f'{folder}/{uuid.uuid4().hex}'
