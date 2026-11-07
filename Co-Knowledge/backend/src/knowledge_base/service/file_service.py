"""文件域：上传编排、预览、下载、删除。

**上传是全链路里最长的一条**：校验 → 解压 → 判重 → 落盘 → 建 kb_directory 行 →
写属性 → 入队。每一步的顺序都有理由（比如「判重必须在落盘之前」），不要重排。
"""

from __future__ import annotations

import io
import json
import os
import re
import uuid
import zipfile
from pathlib import Path
from typing import Iterable, Optional

from infrastructure.storage import kb_storage as storage
from shared.errors.api import (KbApiError, KbLiteralError, KbServerError, KbValidationError,
                                  KbValidatorError, KbWrappedValidatorError)
from knowledge_base.repository import directory as directory_store
from knowledge_base import graph_bridge as graph_lifecycle
from knowledge_base.task import queue as task_queue
from infrastructure.logging.logutil import log

# ``SysGlobalConst``
K_TYPE = 'KType'
FILE_SIZE_PROP = 'file_size'
SPLIT_TYPE_SYSTEM = 'system'
FILE_RENAME_ERROR_CODE = '1001'

#: 重试时重建任务 handle 所需的处理配置（算子参数 / regexList）。
#: 存在 ``kb_directory_property`` 里，键名与 ``file_size`` / ``KType`` 同表。
TASK_CONFIG_PROP = 'task_config'
#: ``kb_directory_property.prop_value`` 是 varchar(1024)；超长配置不写，
#: 重试会回落到系统算子默认参数（见 ``file_retry_service``）。
TASK_CONFIG_MAX_LENGTH = 1000

#: ``appendFileId`` 必须是服务端生成的 32 位 hex 文件 id。它会被当作落盘路径的
#: 最后一段（``core/<前4位>/<id>``），放过任意字符串会让调用方控制文件名。
APPEND_FILE_ID_RE = re.compile(r'^[0-9a-fA-F]{32}$')

# ``FileUploadStatusEnum``
STATUS_INIT = 0
STATUS_UPLOAD_CLOUD_DISK = -1
STATUS_UPLOAD_FAILURE = 2

# ``OperatorConst``
CUSTOM_OPERATOR_FILE_SIZE = 50.0
ZEDX_OPERATOR_FILE_SIZE = 650.0

# ``FileValidate.checkFileNameLength``：**去扩展名后**的字符数上限
FILE_NAME_MAX = 150

# ``${memory.limit}``（MB）；小于 800 时下面那套压缩逻辑会生效。
# 取值链：显式 ``MEM_LIMIT`` > 容器 cgroup 内存上限
# > 不限（读不到时按大值处理，不压缩）。**不要**再用开发配置里的 8 当默认 —— 那会把
# 任何机器都判成小内存（文档库单次只许传 1 个文件）。
MEMORY_LIMIT_THRESHOLD = 800
UNLIMITED_MEMORY_MB = 2 ** 63 / 1024 / 1024
CGROUP_V2_MEMORY_MAX = Path('/sys/fs/cgroup/memory.max')
CGROUP_V1_MEMORY_LIMIT = Path('/sys/fs/cgroup/memory/memory.limit_in_bytes')

# ``upload.file.maxSizeMap``（application.yml:229-244）
#: 上传白名单 + 单文件大小上限（MB）。
#: ``ofd`` 不在这里：v1 没有 OFD 解析器（``text_split_service`` 里显式拒绝），
#: 放进来只会让用户上传成功、解析时再失败。自定义算子声明 `support_format`
#: 带了 ofd 的，仍会经 ``_custom_operator_formats()`` 重新加进来。
FILE_MAX_SIZE_MAP = {
    'txt': 5.0, 'xlsx': 10.0, 'html': 10.0, 'csv': 10.0,
    'pptx': 20.0, 'md': 100.0, 'docx': 100.0, 'pdf': 150.0,
}

# ``upload.knowledge.maxSizeMap``（:249-253）
KNOWLEDGE_MAX_SIZE_MAP = {
    'document': 10.0, 'QA': 1.0, 'outer-document': 50.0, 'graph-document': 50.0,
}

# ``KbCategoryEnum.getFileLimitTypeByCode``
_CATEGORY_LIMIT_TYPE = {1: 'outer-document', 2: 'code-document', 3: 'database',
                        4: 'api-document', 10: 'graph-document'}

# ``KbCategoryEnum.KNOWLEDGE_GRAPH``
CATEGORY_KNOWLEDGE_GRAPH = 10


# ----------------------------------------------------------------------
# 文件大小限制
# ----------------------------------------------------------------------


def _memory_limited(values: dict) -> dict:
    """``UploadFileConfig.modifyConfig``：``memory.limit < 800``（MB）时压缩各档限制。

    压缩后 ``>10`` 的一律变 5、``<=10`` 的减半（txt 5 -> 2.5）。正常内存的部署
    （cgroup ≥ 800MB）**不走这一支**，返回原始档位。
    """
    limit = _memory_limit_value()
    if limit >= MEMORY_LIMIT_THRESHOLD:
        return values
    return {key: (5.0 if value > 10 else value / 2) for key, value in values.items()}


def _cgroup_memory_mb() -> Optional[float]:
    """``setenv.sh`` 的 cgroup 分支：v2 优先、v1 兜底，字节 /1024/1024 → MB。

    ``max`` 表示容器不限内存 → 返回 :data:`UNLIMITED_MEMORY_MB`；
    两条路径都读不到 → ``None``（由调用方按不限处理）。
    """
    for path in (CGROUP_V2_MEMORY_MAX, CGROUP_V1_MEMORY_LIMIT):
        try:
            raw = path.read_text().strip()
        except OSError:
            continue
        if raw == 'max':
            return UNLIMITED_MEMORY_MB
        try:
            return int(raw) / (1024 * 1024)
        except ValueError:
            continue
    return None


def _memory_limit_value() -> float:
    """``memory.limit``（MB），取值顺序见下。

    1. 显式 ``MEM_LIMIT`` 环境变量（空串视为未设置 —— compose 用 ``${MEM_LIMIT:-}`` 透传时会传空）；
    2. 容器 cgroup 的内存上限（v2 ``memory.max`` / v1 ``memory.limit_in_bytes``）；
    3. 都拿不到 → 视为不限内存（64 位最大值）。

    ⚠️ 不要回落到开发配置的 ``8``：那会把**所有部署**都判成小内存（文档库单次只能
    传 1 个文件、单文件上限被压到 5MB）。只有真正 < 800MB 的容器才该降级。
    """
    raw = os.environ.get('MEM_LIMIT')
    if raw:
        digits = re.sub(r'[^0-9.]', '', raw)
        try:
            return float(digits)
        except ValueError:
            pass  # 非法值按未设置处理
    return _cgroup_memory_mb() or UNLIMITED_MEMORY_MB


def _custom_operator_formats() -> set[str]:
    """``OperatorPropDao.getAllFileFormat``：已发布 text_split 算子声明支持的格式。

    ``prop_value`` 形如 ``["md", "txt"]``，去掉方括号后按逗号分。
    """
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT DISTINCT op.prop_value FROM operator_prop op '
                'INNER JOIN "operator" o ON op.operator_id = o.id '
                "WHERE op.prop_name = 'support_format' "
                "AND o.is_published AND o.module = 'text_split' "
                "AND (o.created_by = %s OR o.visible_range = 'public')",
                ('', ),
            )
            values = [row[0] for row in cursor.fetchall()]
    formats: set[str] = set()
    for value in values:
        for item in (value or '').replace('[', '').replace(']', '').split(','):
            item = item.strip()
            if item:
                formats.add(item)
    return formats


def file_size_limit(category: int = 1) -> dict:
    """``GET /file/size_limit`` 与 ``GET /file/size_limit/{category}`` 的公共体。

    ``category`` 决定「单库文件数」取哪一档。
    """
    sizes = _memory_limited(dict(FILE_MAX_SIZE_MAP))
    for fmt in _custom_operator_formats():
        sizes.setdefault(fmt, ZEDX_OPERATOR_FILE_SIZE if fmt.lower() == 'zedx'
                         else CUSTOM_OPERATOR_FILE_SIZE)

    knowledge = dict(KNOWLEDGE_MAX_SIZE_MAP)
    if _memory_limit_value() < MEMORY_LIMIT_THRESHOLD:
        knowledge['outer-document'] = 1.0

    limit_type = _CATEGORY_LIMIT_TYPE.get(category)
    number = knowledge.get(limit_type) if limit_type else None
    if number is None:
        # category 认不出（0/5/…），或认得但没给档位（code-document / database /
        # api-document，2/3/4）都落这里：结果是 0001，
        # **不是** 0000 + ``number: null``。
        raise KbServerError('file size limit config missing for category %s' % category)
    return {'maxSizeMap': sizes, 'number': int(number)}


# ----------------------------------------------------------------------
# 上传
# ----------------------------------------------------------------------


class UploadedFile:
    """``MultipartFile`` 的最小等价物（zip 解压出来的条目也用它）。"""

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self.content = content

    @property
    def size(self) -> int:
        return len(self.content)


def expand_zip(files: list[UploadedFile]) -> list[UploadedFile]:
    """单个 zip 上传时**展开成内部的文件**。

    只处理「恰好一个文件且是 zip」的情况；其余原样返回。
    """
    if len(files) != 1 or not files[0].filename.lower().endswith('.zip'):
        return files
    try:
        with zipfile.ZipFile(io.BytesIO(files[0].content)) as archive:
            expanded = []
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = Path(info.filename).name       # 只取 basename（按 basename 展平）
                if not name or name.startswith('.'):
                    continue
                expanded.append(UploadedFile(name, archive.read(info)))
            return expanded or files
    except zipfile.BadZipFile:
        log.warning('uploaded file ends with .zip but is not a valid archive')
        return files


# 四个 ``@NotBlank`` 字段与它们的**注解 message**
# （这些键都不在文案表里，所以线上是花括号原文）。
# ``kType`` 复用了 splitType 那条 message，两条都缺时同一句会出现两遍。
REQUIRED_FIELDS = (('directoryId', '{RetCode.upload.directoryId.check}'),
                   ('kbaseId', '{RetCode.upload.kbaseId.check}'),
                   ('kType', '{RetCode.upload.splitType.check}'),
                   ('splitType', '{RetCode.upload.splitType.check}'))


# 目录不存在时抛的键。
# 单测会断言它没被写成 ``file.not.exist``（两者文案不同：「目录不存在」vs「文件(夹)不存在」）。
_DIRECTORY_MISSING_KEY = 'directory.not.exist'


def validate_metadata(metadata: dict) -> None:
    """``UploadFileDTO`` 的 bean validation：必需字段为空 → **0005** 聚合包装文案。

    做法是「**收集全部** violations → 本地化 → 排序 → ``";"`` 拼接 →
    套外层模板 ``RetCode.upload.json.incorrect``」，**不是只报第一条**：

    * **码是 0005**，不是 0004；内层 message 是 ``{RetCode.upload.*.check}`` ——
      **花括号原样出现**，因为注解里引用的那几个键不在文案表里；
    * **排序发生在渲染之后**，所以「谁在前」不写死在调用点 —— 交给
      :class:`~shared.errors.api.KbWrappedValidatorError`（它就是为这条链设计的，
      与 :func:`validate_operator_args` 的聚合风格一致）；
    * ``kType`` 与 ``splitType`` 共用同一条 message，两条都缺时花括号那句会出现
      **两遍** —— 别去重。

    示例（zh 与 en 只差外层模板）::

        metadata={}                          → {RetCode.upload.directoryId.check};\\
                                               {RetCode.upload.splitType.check};{RetCode.upload.splitType.check}
        metadata={"directoryId":"x"}         → {RetCode.upload.splitType.check};{RetCode.upload.splitType.check}
        metadata={"directoryId":"x","kType":"document"} → {RetCode.upload.splitType.check}

    以上三例里都没有 kbaseId 那条：``/file/upload`` 会把查询参数 kbaseId
    **覆盖**进 DTO，而那个参数本身必填 —— 参数**缺了**在解析阶段就 0004，轮不到这里；
    **空串**（``?kbaseId=``）会覆盖成 ``''``，但请求会先回 0005「知识库不存在」
    （早于参数校验），所以聚合里也见不到 kbaseId 那条。
    函数级仍校验四个字段（DTO 上确实有那条 ``@NotBlank``）。
    """
    violations = [KbLiteralError(message) for field, message in REQUIRED_FIELDS
                  if not (metadata.get(field) or '').strip()]
    if violations:
        raise KbWrappedValidatorError('RetCode.upload.json.incorrect', violations)


# ``OperatorReqDTO.args`` 的注解 message —— **内联英文字面量**，与请求语言无关
OPERATOR_PARAMS_NOT_EMPTY = 'OperatorParams list cannot be empty'


def validate_operator_args(metadata: dict) -> None:
    """``UploadFileParamValidate.validateOperators``：两个算子表各自的级联校验。

    对 ``parseOperator``、``splitOperator`` **各调一次**（parseOperator 在前），
    表内每个条目走一次 ``validator.validate(operator)``。字段上有两条约束：

    * ``args`` 的 ``@NotNull(message = "OperatorParams list cannot be empty")``
      —— 内联英文，中英文渲染同一句；
    * ``operatorId`` 的 ``@NotNull`` —— 注解**没写 message**，文案走默认的
      「不能为null / must not be null」。三变体（``''`` / ``null`` / 键缺席）都回 0005
      这句：``''`` 是绑定期把**空串（含全空白串，绑定前先 trim）绑成 null**，
      另两变体本来就是 null → 两条都撞 ``@NotNull``。

    violations 的文案**先本地化、再排序、``";"`` 拼接**，整段塞进外层模板
    ``RetCode.upload.json.incorrect`` 的 ``{0}`` —— 排序键是渲染后的文本，所以
    「渲染 → 排序 → 拼接 → 包装」推迟到最外层渲染
    （:class:`~shared.errors.api.KbWrappedValidatorError`）。

    ⚠️ 表内是**并发遍历**：同一张表里多个条目都不合规时，抛出来的是先算完的那一个
    （非确定）。这里固定取**插入顺序的第一个**。
    """
    def cascaded(name):
        return [value for value in (metadata.get(name) or {}).values()
                if isinstance(value, dict)]

    for name in ('parseOperator', 'splitOperator'):
        for operator in cascaded(name):
            violations = []
            operator_id = operator.get('operatorId')
            if operator_id is None or (isinstance(operator_id, str)
                                       and not operator_id.strip()):
                violations.append(KbValidatorError('validator.notNull'))
            if operator.get('args') is None:
                violations.append(KbLiteralError(OPERATOR_PARAMS_NOT_EMPTY))
            if violations:
                raise KbWrappedValidatorError('RetCode.upload.json.incorrect', violations)


def require_split_operator(metadata: dict) -> None:
    """``convertSplitOperator`` 里的 ``new HashMap<>(splitOperator)``。

    ``splitOperator`` 整个缺席就是 **NPE → 0001**（不做友好判断）。
    """
    if metadata.get('splitOperator') is None:
        raise RuntimeError('Cannot invoke "java.util.Map.size()" because '
                           '"<parameter1>" is null')


def operator_check(parse_operator, split_operator, file_types) -> None:
    """``operatorCheck``：切分算子必须覆盖所有待上传的扩展名。

    三种通过条件：
    解析算子齐了且带了 ``md``，或者切分算子自己覆盖了全部扩展名。
    """
    if not split_operator:
        raise KbApiError('RetCode.split.select.error')
    if parse_operator and set(parse_operator) >= set(file_types):
        if 'md' not in split_operator:
            raise KbApiError('RetCode.split.select.error')
    elif not set(split_operator) >= set(file_types):
        raise KbApiError('RetCode.split.select.error')


# ----------------------------------------------------------------------
# ``FileValidate.fileUploadCheck`` —— 这一批文件**自己**的校验
# ----------------------------------------------------------------------


def _knowledge_file_count_limit(k_type: str) -> float:
    """``upload.knowledge.maxSizeMap`` 上再跑一遍 ``modifyConfig``。

    ⚠️ ``memory.limit < 800``（MB，见 :func:`_memory_limit_value`）时
    ``outer-document`` 会压成 **1** —— 所以小内存容器里文档库一次传 2 个文件就是
    「文件个数超过限制」。正常内存的部署取原值 **50**。
    图谱库取的是 ``graph-document``（**50**，不在压缩之列）。
    """
    limits = dict(KNOWLEDGE_MAX_SIZE_MAP)
    if _memory_limit_value() < MEMORY_LIMIT_THRESHOLD:
        limits['outer-document'] = 1.0
    return limits[k_type]


def _allowed_formats_for(k_type: str) -> set[str]:
    """``checkDocTypeAndSize`` 的格式白名单：配置表 keys + 自定义算子声明的格式。

    自定义算子声明的格式在基础白名单之后并进来，所以 ``zedx`` 这类格式不受影响。
    """
    formats = set(_memory_limited(dict(FILE_MAX_SIZE_MAP)).keys())
    formats |= _custom_operator_formats()
    return formats


def _max_size_for(extension: str) -> float:
    """``fileSizePrecheck``：``zedx`` 特例 650MB，其余查表，查不到按自定义算子 50MB。"""
    if extension.lower() == 'zedx':
        return ZEDX_OPERATOR_FILE_SIZE
    return _memory_limited(dict(FILE_MAX_SIZE_MAP)).get(extension, CUSTOM_OPERATOR_FILE_SIZE)


def _is_encrypted(_content: bytes) -> bool:
    """文档安全加密组件（DRM）的头部识别。

    **这里恒为 False —— 有意留的缺口。** 完整判据需要自带的解码器与 Rijndael 实现，
    本环境既造不出加密样本、也无法验证其是否与标准 AES 逐位一致，补进来只会是
    一段**测不了**的代码。影响面：DRM 加密文件不会被拦下，而是照常入库
    （随后解析/切分阶段会失败）。真需要时再补。
    """
    return False


def _file_extension(name: str) -> str:
    """Guava ``Files.getFileExtension``：最后一个 ``.`` 之后的部分，没有则空串。"""
    base = name.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    return base.rsplit('.', 1)[1] if '.' in base else ''


def _name_without_extension(name: str) -> str:
    """Guava ``Files.getNameWithoutExtension``：先取 basename，再去掉最后一段扩展名。"""
    base = name.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    return base.rsplit('.', 1)[0] if '.' in base else base


def upload_check(files: list[UploadedFile], k_type: str) -> None:
    """``FileValidate.fileUploadCheck``：数量 → 重名 → 名长 → 格式/大小 → 加密。

    **与 ``precheck_upload``（``/file/uploadFilePreCheck`` 端点）不是一条**：
    那条做的是「空文件 + 单库文件数 + 格式」，这条做的是**这一批文件内部**的校验。
    两条都会在 ``/file/upload`` 里跑到（``uploadFile`` 先调 ``uploadFilePreCheck``）。

    错误码**不是同一个**（三类异常的映射）：

    * 数量 / 重名 / 名长 / 加密 → **0005**
    * 格式不支持 → **0004**
    * 超出大小上限 → **0005**
    """
    if len(files) > _knowledge_file_count_limit(k_type):
        raise KbApiError('RetCode.file.count.limit')            # → 0005

    expanded = expand_zip(files)
    names = [item.filename for item in expanded]
    # ``checkSameFileName``：用 distinct 计数比总数
    if len(set(names)) < len(names):
        raise KbApiError('RetCode.upload.file.rename')          # → 0005

    # ``checkFileNameLength``：去掉扩展名后的**basename**不超过 150
    too_long = [name for name in names if len(_name_without_extension(name)) > FILE_NAME_MAX]
    if too_long:
        raise KbApiError('file.name.length.check')              # → 0005

    allowed = _allowed_formats_for(k_type)
    for item in expanded:
        extension = _file_extension(item.filename)
        if extension not in allowed:
            raise KbValidationError('file.type.validation')     # IllegalArgumentException → 0004
        # **内容要与扩展名对得上**。只看后缀会把 exe 改名 .pdf 也收进来，
        # 解析阶段才以「文件未能解析出文本内容」暴露出来，用户与运维都看不出真正原因。
        # 只判**有明确魔数**的格式，txt/md/csv/html/json 这类没有魔数的一律放行。
        if not _content_matches_extension(extension, item.content):
            raise KbValidationError('file.content.type.mismatch')
        limit = _max_size_for(extension)
        if item.size / (1024 * 1024) > limit:
            raise KbApiError('RetCode.file.size.limit.check', str(int(limit)))   # 0005

    # ``checkEncryptedFile``：先过 ``getLegalPath``，再问 DRM（见 _is_encrypted 的说明）
    for item in expanded:
        if '../' in item.filename or '..\\' in item.filename:
            raise KbValidationError('RetCode.illegalArgument')
        if _is_encrypted(item.content):
            raise KbApiError('file.encrypted.check', item.filename)              # 0005


def _content_matches_extension(extension: str, content: bytes) -> bool:
    """内容魔数与扩展名是否一致。**只在有明确魔数时判定**（返回 False 才拒绝）。

    判定范围刻意收窄：只覆盖魔数无歧义、且本服务确实会按该格式解析的几种。
    ``txt`` / ``md`` / ``csv`` / ``html`` / ``json`` 没有魔数，一律放行；
    ``zedx`` 的容器格式本仓没有约定，不做判断（宁可漏判，不可误拒真实文件）。

    空内容放行 —— 「空文件」由 ``file.upload.empty.error`` 那条单独的校验负责，
    这里再拦一次只会把错误码说错。
    """
    head = (content or b'')[:1024]
    if not head:
        return True
    if extension == 'pdf':
        # PDF 规范允许 %PDF 之前有少量杂物，取前 1KB 找标记
        return b'%PDF' in head
    if extension in ('docx', 'xlsx', 'pptx', 'ofd'):
        # OOXML 与 OFD 都是 zip 容器（OFD 规范要求以 PK 开头）
        return head[:4] == b'PK\x03\x04'
    if extension == 'png':
        return head[:8] == b'\x89PNG\r\n\x1a\n'
    if extension in ('jpg', 'jpeg'):
        return head[:3] == b'\xff\xd8\xff'
    return True


def upload_files(files: list[UploadedFile], metadata: dict, kbase_id: str,
                 emp_no: str, queue: Optional[task_queue.FileTaskQueue] = None,
                 run_split_pipeline: bool = True) -> dict:
    """``ImportKbFileService.uploadFile`` 的主流程。

    :return: ``{文件名: fileId}`` —— 就是接口的 ``bo``

    ⚠️ ``run_split_pipeline``：两种调用方的语义不一样，别合成一条。

    * ``True``（默认，``/file/upload``）：额外做算子相关校验 —— 参数校验级联
      （``args`` 不能为空）、转换 ``splitOperator``（缺席会空指针）、
      ``operatorCheck``；落盘后**入队**文件任务。
    * ``False``（抽图建库）：这些**都没有**，请求体是代码里构造出来的
      （不跑参数校验），也没有算子链；且**不入队**。
      按 ``True`` 处理会让抽图建库直接报 0001（实测踩过）。
    """
    validate_metadata(metadata)
    if run_split_pipeline:
        # 参数校验级联只发生在**绑定期**（``/file/upload`` 那条）；V2 是代码里
        # 构造出来的对象，不跑校验
        validate_operator_args(metadata)
    directory_id = metadata['directoryId']
    cover_flag = bool(metadata.get('coverFlag'))
    split_type = metadata.get('splitType')
    k_type = metadata['kType']

    # ``uploadFilePreCheck``：空文件 → 单库文件数 → ``fileUploadCheck``。
    # 抽图建库那条路会在建库**之前**先自己调一次 fileUploadCheck，
    # 这里再跑一遍（``uploadFile`` 内部就是这么串的）。
    _validate_files_present(files)
    _check_kbase_file_count(kbase_id, len(files))
    upload_check(files, k_type)

    if directory_store.get_directory(directory_id, kbase_id, directory_store.TYPE_FOLDER) is None:
        # 目录不存在抛 ``RetCode.directory.not.exist``（「目录不存在」/
        # 'directory not exist'），实际序列化成 0005。
        # ⚠️ 别顺手用 ``file.not.exist``（「文件(夹)不存在」）—— 那是**另一条**检查的文案，
        # 两个键是分开的（上传时目录不存在必须回「目录不存在」）。
        raise KbApiError(_DIRECTORY_MISSING_KEY)

    files = expand_zip(files)
    if not files:
        raise KbApiError('file.not.exist')

    if run_split_pipeline:
        # ``convertSplitOperator`` 在判重**之前**
        require_split_operator(metadata)

    if not cover_flag:
        _reject_duplicate_names(kbase_id, directory_id, [f.filename for f in files])

    # ``fileSaveKBase`` → ``getMultipartFiles``：**图谱库直接 return**，不做算子校验
    if run_split_pipeline and metadata.get('category') != CATEGORY_KNOWLEDGE_GRAPH:
        extensions = {Path(item.filename).suffix.lstrip('.').lower() for item in files}
        operator_check(metadata.get('parseOperator') or {},
                       metadata.get('splitOperator') or {}, extensions)

    manager = queue or _default_queue()
    result: dict[str, str] = {}
    for uploaded in files:
        file_id = _save_one(uploaded, metadata, kbase_id, directory_id, cover_flag,
                            split_type, k_type, emp_no, manager, run_split_pipeline)
        if file_id:
            result[uploaded.filename] = file_id
    return result


def _reject_duplicate_names(kbase_id: str, directory_id: str, names: list[str]) -> None:
    """``hasSameFileInDirectoryThrowException``：目录下已有同名文件时报 1001。

    ⚠️ 判重查询**不筛删除标记** —— 删除掉的旧文件也算「已存在」。
    """
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT title FROM kb_directory WHERE kbase_id = %s AND parent_id = %s "
                "AND type = 'file' AND title = ANY(%s)",
                (kbase_id, directory_id, names),
            )
            duplicates = [row[0] for row in cursor.fetchall()]
    if duplicates:
        raise KbApiError('file.upload.rename', ', '.join(sorted(set(duplicates))),
                         code=FILE_RENAME_ERROR_CODE)


def validate_append_file_id(append_file_id: str, kbase_id: str) -> None:
    """``appendFileId`` 必须是本库已存在的 32 位 hex 文件 id。

    **不能只做字符校验**：这个值会被直接当作落盘路径的最后一段
    （``core/<前4位>/<id>``）和目录行 id。放过任意字符串，调用方就能控制磁盘上的
    文件名，进而配合解析链（例如 pdfminer 的 CMap 反序列化）构造利用链。
    """
    if not append_file_id:
        return
    if not APPEND_FILE_ID_RE.fullmatch(append_file_id):
        raise KbValidationError('RetCode.illegalArgument')
    if directory_store.get_directory(append_file_id, kbase_id, dir_type='file') is None:
        raise KbValidationError('RetCode.illegalArgument')


def _save_one(uploaded: UploadedFile, metadata: dict, kbase_id: str, directory_id: str,
              cover_flag: bool, split_type: str, k_type: str, emp_no: str,
              manager: task_queue.FileTaskQueue, enqueue_task: bool) -> Optional[str]:
    """单个文件的：建行 → 落盘 → 写属性 →（``enqueue_task``）入队。返回 fileId。

    ⚠️ ``enqueue_task=False`` **不入队**：抽图建库到「写 KType 属性」为止，
    图谱库文件停在 ``FILE_UPLOAD_CLOUD_DISK``（-1），不进 parse/split/embedding
    链 —— 无条件入队会让任务链拿到 ``operatorSplitDTO=null`` 后必炸
    （``RetCode.operator.split.error``）。
    """
    append_file_id = (metadata.get('appendFileId') or '').strip()
    validate_append_file_id(append_file_id, kbase_id)
    identifier_id = append_file_id or uuid.uuid4().hex
    file_name = uploaded.filename
    extension = Path(file_name).suffix.lstrip('.').lower()

    existing_row = _find_existing_file(kbase_id, directory_id, file_name) if cover_flag else None
    if existing_row is not None:
        file_id = existing_row['id']
        # 覆盖：属性行必须挂在**真实存在**的 kb_directory 行上。不传 appendFileId 时
        # identifier_id 是刚生成的 uuid，与旧行 id 不等 —— 10-26 给
        # kb_directory_property.file_id 加上 FK 后，这条会直接
        # ForeignKeyViolation（重抽建图时「同一文件第二次上传」必炸）。
        identifier_id = file_id
        _purge_old_file(kbase_id, file_id, file_name)
        with directory_store.connection() as conn:
            with conn.cursor() as cursor:
                # 覆盖：把旧行重置成初始态（按 identifierId 更新属性，见 java 的原样行为）
                directory_store.update_file_status(cursor, file_id, STATUS_INIT)
                directory_store.update_file_from(cursor, file_id, metadata.get('fileFrom'))
                directory_store.upsert_property(cursor, kbase_id, identifier_id,
                                                FILE_SIZE_PROP, uploaded.size)
    else:
        file_id = identifier_id
        with directory_store.connection() as conn:
            with conn.cursor() as cursor:
                directory_store.insert_directory(
                    cursor, kbase_id, directory_id,
                    _parent_path(directory_id), file_name,
                    directory_store.TYPE_FILE, STATUS_INIT,
                    directory_id=file_id, created_by=emp_no,
                    file_from=metadata.get('fileFrom'))
                directory_store.create_property(cursor, kbase_id, identifier_id,
                                                FILE_SIZE_PROP, uploaded.size)

    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            directory_store.upsert_property(cursor, kbase_id, identifier_id, K_TYPE, k_type)

    disk_path = _save_to_disk(uploaded, file_id, cover_flag)
    if disk_path is None:
        return None

    if not enqueue_task:
        # 抽图建库到此为止（见函数头）；文件停在落盘后的 ``FILE_UPLOAD_CLOUD_DISK``。
        return file_id

    handle = {
        'fileId': file_id,
        'kbaseId': kbase_id,
        'diskPath': str(disk_path),
        'format': extension,
        'fileName': file_name,
        'fileSize': uploaded.size,
        'modelName': _embedding_model(kbase_id),
        'regexList': metadata.get('regexList'),
    }
    split_operator = metadata.get('splitOperator') or {}
    parse_operator = metadata.get('parseOperator') or {}
    if split_type == SPLIT_TYPE_SYSTEM:
        handle['operatorSplitDTO'] = split_operator.get(extension)
    else:
        handle['operatorParseDTO'] = parse_operator.get(extension)
        handle['operatorSplitDTO'] = split_operator.get('md')

    # 重试配置先落库再入队：任务失败后仍要能按原参数重新跑。
    _persist_task_config(kbase_id, identifier_id, handle)
    manager.submit_task(handle)
    return file_id


def _persist_task_config(kbase_id: str, file_id: str, handle: dict) -> None:
    """把 ``operatorParseDTO`` / ``operatorSplitDTO`` / ``regexList`` 存进属性表。

    写失败**不影响上传**：配置只是手工重试的输入，丢了还能回落到系统算子默认值。
    """
    payload = json.dumps({
        'operatorParseDTO': handle.get('operatorParseDTO'),
        'operatorSplitDTO': handle.get('operatorSplitDTO'),
        'regexList': handle.get('regexList'),
    }, ensure_ascii=False)
    if len(payload) > TASK_CONFIG_MAX_LENGTH:
        log.warning('task config for %s is too long (%d > %d), skip persistence; '
                    'retry will fall back to the default operator',
                    file_id, len(payload), TASK_CONFIG_MAX_LENGTH)
        return
    try:
        with directory_store.connection() as conn:
            with conn.cursor() as cursor:
                directory_store.upsert_property(cursor, kbase_id, file_id,
                                                TASK_CONFIG_PROP, payload)
    except Exception:
        log.warning('persist task config for %s failed', file_id, exc_info=True)


def _save_to_disk(uploaded: UploadedFile, file_id: str, cover_flag: bool) -> Optional[str]:
    """落盘；失败时把行标成失败并**跳过入队**。

    :return: 存储引用 —— 本地后端是绝对路径，MinIO 后端是对象键。
    """
    try:
        path = storage.save_core_file(uploaded.content, file_id, cover=cover_flag)
        with directory_store.connection() as conn:
            with conn.cursor() as cursor:
                directory_store.update_file_status(cursor, file_id, STATUS_UPLOAD_CLOUD_DISK)
        return str(path)
    except Exception:
        log.exception('save file %s to disk failed', file_id)
        try:
            with directory_store.connection() as conn:
                with conn.cursor() as cursor:
                    directory_store.update_file_status(
                        cursor, file_id, STATUS_UPLOAD_FAILURE, 'RetCode.file.save.error')
        except Exception:
            log.warning('mark file %s as failed also failed', file_id, exc_info=True)
        return None


def _find_existing_file(kbase_id: str, directory_id: str, file_name: str) -> Optional[dict]:
    """``KbFileDao.queryByFileName``：按名取**最新**一条（``created_at DESC LIMIT 1``）。"""
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM kb_directory WHERE kbase_id = %s AND parent_id = %s "
                "AND title = %s AND type = 'file' "
                'ORDER BY created_at DESC LIMIT 1',
                (kbase_id, directory_id, file_name),
            )
            columns = [d[0] for d in cursor.description]
            row = cursor.fetchone()
            return dict(zip(columns, row)) if row else None


def _purge_old_file(kbase_id: str, file_id: str, file_name: str) -> None:
    """覆盖前的清理顺序（``handleFileCreationOrUpdate``）。

    顺序不能换：先按 relation 删向量行与 ES 文档，再按**文件名**删 chunk 行，
    最后删 ES 文档、重置旧行状态。
    """
    from knowledge_base.repository import node_relation as node_relation_store

    row = _kbase_row(kbase_id)
    node_relation_store.delete_by_directory_ids(row['id'], [file_id])
    table_name = row.get('table_name')
    if table_name:
        graph_lifecycle.delete_chunks_by_sources(table_name, [file_name])
    _delete_es_documents(kbase_id, file_id)


def _delete_es_documents(kbase_id: str, file_id: str) -> None:
    from retrieval.service import index as index_service

    index_service.delete_documents_by_file_id(kbase_id, file_id)


def _parent_path(directory_id: str) -> str:
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT parent_path FROM kb_directory WHERE id = %s",
                (directory_id,))
            row = cursor.fetchone()
    return row[0] if row else directory_store.ROOT_DIRECTORY_SYMBOL


def _embedding_model(kbase_id: str) -> Optional[str]:
    return _kbase_row(kbase_id).get('embedding_model')


def _kbase_row(kbase_id: str) -> dict:
    from knowledge_base.repository import kbase as kbase_store

    row = kbase_store.select_kbase_by_id(kbase_id)
    if row is None:
        raise KbApiError('kbase.not.exist')
    return row


# ----------------------------------------------------------------------
# 删除
# ----------------------------------------------------------------------


def delete_files(kbase_id: str, file_ids: Iterable[str]) -> None:
    """``KbFileService.deleteFiles``：清 relation/属性/磁盘 + 删除行。

    与删目录走**同一套**清理（``kbase_write_service._purge_files``），这里只是入口不同。
    """
    from knowledge_base.service import kbase_write_service

    row = _kbase_row(kbase_id)
    kbase_write_service._purge_files(kbase_id, row['id'], list(file_ids), _node_relation_store(),
                                     storage)


def _node_relation_store():
    from knowledge_base.repository import node_relation as node_relation_store

    return node_relation_store


def _default_queue() -> task_queue.FileTaskQueue:
    """取 app 启动时装配的那个队列（见 ``register_rkb_api`` 的装配点）。"""
    from knowledge_base.task import runtime

    return runtime.get_queue()


def _validate_files_present(files: list[UploadedFile]) -> None:
    """``FileUtil.isMultipartFileValid`` 那一段：空内容或空名 → 0005，一次报全部。"""
    empty = [uploaded.filename for uploaded in files
             if not uploaded.content or not (uploaded.filename or '').strip()]
    if empty:
        raise KbApiError('file.upload.empty.error', ', '.join(empty))


def _check_kbase_file_count(kbase_id: str, increased: int) -> None:
    """``isFileCountExceed``：用 **kb_kbase.file_count_limit 这一列**（默认 5000）。

    不是 ``size_limit`` 接口里那个被 MEM_LIMIT 压过的 ``number`` —— 两者容易混。
    """
    if not kbase_id:
        return
    current = directory_store.count_files(kbase_id)
    limit = _kbase_row(kbase_id).get('file_count_limit')
    if limit and current + increased > limit:
        raise KbApiError('kbase.file.count.exceed', current, increased, limit)


def doc_download_file(kbase_id: str, file_id: str) -> bytes:
    """``GET /file/doc/downloadFile``：把上传的原文件流回去。

    路径由 fileId 算出（``generateCoreFilePathStr``），**先确认该 fileId 属于这个库** ——
    按 id 取文件时必须补一层归属校验，避免拿别人的 fileId 越权下载
    （不改变任何合法调用的行为）。

    失败文案矩阵（实测）：库不存在 → 0005「知识库不存在」（切面先报）；
    库在、文件不在 → 0005「文件(夹)不存在」。**先库后文件**（D4）。
    """
    from knowledge_base.service.kbase_service import get_kbase_for_aspect

    get_kbase_for_aspect(kbase_id)
    if directory_store.get_directory(file_id, kbase_id) is None:
        raise KbApiError('file.not.exist')
    try:
        return storage.read_core_file(file_id)
    except FileNotFoundError as error:
        raise KbApiError('file.not.exist') from error


# ----------------------------------------------------------------------
# 「库里的老文件」重新变成上传流 —— 图谱更新的增量重建要用
# ----------------------------------------------------------------------


def local_files(file_ids: Iterable[str], kbase_id: str) -> list[UploadedFile]:
    """``KbFileServiceV2.getLocalMultipartFiles``：把已在库的文件读回内存。

    图谱「更新」时前端只传**这次新增**的文件，历史的靠这个把老文件也带上
    （``files = localFiles + upLoadFiles``）—— 抽图是要把整库重抽一遍的。

    三点注意：``queryMultiFiles`` **不筛 ``type='file'``**（传文件夹 id 也查得出来，
    只是落盘路径不是文件、被跳过）；磁盘上没有实体的静默跳过；名字取 ``title``。
    """
    ids = [item for item in file_ids if item]
    if not ids:
        return []

    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, title FROM kb_directory WHERE id = ANY(%s) AND kbase_id = %s",
                (ids, kbase_id),
            )
            rows = cursor.fetchall()

    files = []
    for file_id, title in rows:
        if not storage.core_file_exists(file_id):
            log.info('local file %s (%s) is missing in storage; skipped', file_id, title)
            continue
        files.append(UploadedFile(title or '', storage.read_core_file(file_id)))
    return files
