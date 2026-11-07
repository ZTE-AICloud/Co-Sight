"""纯 REST 契约的共享错误模型（RFC 9457 ``application/problem+json``）。

``/api/co-knowledge/v1`` 下由 RKB 自己提供响应的家族
（kb_api / flow_api / model_api / agent-keys / 图谱检索 / Agent REST / 编排问答）不再返回
不再返回 ``{code:{code,msg,msgId}, bo, other}`` 这种信封，也不再「业务错误一律 HTTP 200」：

* 成功：资源对象 / 数组 / ``{items,total,page,pageSize}``；
* 失败：真实 HTTP 状态码 + ``application/problem+json``，正文至少含
  ``type`` / ``title`` / ``status`` / ``detail`` / ``code``。

本模块只负责**错误**这一半：问题规格（状态码 + 稳定机器码 + 英文标题）、旧码/文案键到
新规格的显式映射、以及响应构造。成功响应见 ``infrastructure.http.responses``。

设计约束：

* ``title`` 是**稳定英文**，不随语言变化；``detail`` 才按 ``Accept-Language`` 本地化
  （沿用 ``infrastructure.http.identity.language`` 的既有口径，包括 ``*`` → 中文这种历史行为）。
* 映射表**逐键显式**，不做 ``endswith('.not.exist')`` 之类的后缀猜测 —— 猜错一个键
  就会把一个 500 变成 404，排障成本远高于多写几行。
* 未知业务键回落 400 ``bad_request``，并记录一条 warning；测试会钉住常用键的覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from fastapi.responses import JSONResponse

from shared.prefixes import AGENT_MCP_PATH, RKB_PREFIX

PROBLEM_MEDIA_TYPE = 'application/problem+json'
PROBLEM_TYPE_PREFIX = 'urn:ragstudio:problem:'


@dataclass(frozen=True)
class ProblemSpec:
    """一个问题类型的稳定规格。"""

    status: int
    code: str
    title: str


def title_for(code: str) -> str:
    """由 snake_case 机器码生成稳定英文标题（``knowledge_base_not_found`` → ...）。

    机器码本身是稳定的；标题只是给人看的，不需要单独维护一张同义表。
    个别缩写需要特殊拼写的，在 :data:`TITLE_OVERRIDES` 里覆盖。
    """

    override = TITLE_OVERRIDES.get(code)
    if override:
        return override
    words = code.replace('_', ' ').strip()
    return words[:1].upper() + words[1:]


TITLE_OVERRIDES = {
    'api_key_not_found': 'API key not found',
    'upstream_unavailable': 'Upstream service unavailable',
    'rate_limited': 'Too many requests',
    'llm_unavailable': 'LLM unavailable',
    'llm_gateway_unavailable': 'LLM gateway unavailable',
    'llm_empty_content': 'LLM returned empty content',
    'llm_empty_content_truncated': 'LLM output was truncated',
    'rerank_endpoint_not_configured': 'Rerank endpoint not configured',
    # ---- 本地账号 / 登录 ----
    'invalid_credentials': 'Invalid credentials',
    'account_disabled': 'Account disabled',
    'login_rate_limited': 'Too many login attempts',
    'auth_not_initialized': 'Authentication not initialized',
    'auth_not_enabled': 'Login not enabled',
    'invalid_current_password': 'Current password is incorrect',
    'password_policy': 'Password policy violation',
    'invalid_email': 'Invalid email address',
    'session_expired': 'Session expired',
    'password_change_required': 'Password change required',
    'csrf_rejected': 'CSRF check failed',
    'user_not_found': 'User not found',
}


def _spec(status: int, code: str) -> ProblemSpec:
    return ProblemSpec(status=status, code=code, title=title_for(code))


# ----------------------------------------------------------------------
# 机器码 → 状态码 / 标题
# ----------------------------------------------------------------------

BAD_REQUEST = _spec(400, 'bad_request')
MALFORMED_REQUEST = _spec(400, 'malformed_request')
UNAUTHORIZED = _spec(401, 'unauthorized')
PERMISSION_DENIED = _spec(403, 'permission_denied')
PAYLOAD_TOO_LARGE = _spec(413, 'payload_too_large')
UNSUPPORTED_MEDIA_TYPE = _spec(415, 'unsupported_media_type')
VALIDATION_FAILED = _spec(422, 'validation_failed')
LIMIT_EXCEEDED = _spec(422, 'limit_exceeded')
UNSUPPORTED_FILE_TYPE = _spec(422, 'unsupported_file_type')
IMPORT_FAILED = _spec(422, 'import_failed')
RATE_LIMITED = _spec(429, 'rate_limited')
INTERNAL_ERROR = _spec(500, 'internal_error')
UPSTREAM_UNAVAILABLE = _spec(502, 'upstream_unavailable')
SERVICE_UNAVAILABLE = _spec(503, 'service_unavailable')
NOT_FOUND = _spec(404, 'not_found')
METHOD_NOT_ALLOWED = _spec(405, 'method_not_allowed')
CONFLICT = _spec(409, 'conflict')
FILE_NAME_CONFLICT = _spec(409, 'file_name_conflict')
QUERY_TRACE_NOT_FOUND = _spec(404, 'query_trace_not_found')
QUERY_TRACE_STORE_UNAVAILABLE = _spec(503, 'query_trace_store_unavailable')

# ---- 本地账号 / 登录 ----
INVALID_CREDENTIALS = _spec(401, 'invalid_credentials')
ACCOUNT_DISABLED = _spec(403, 'account_disabled')
LOGIN_RATE_LIMITED = _spec(429, 'login_rate_limited')
AUTH_NOT_INITIALIZED = _spec(503, 'auth_not_initialized')
AUTH_NOT_ENABLED = _spec(409, 'auth_not_enabled')
INVALID_CURRENT_PASSWORD = _spec(422, 'invalid_current_password')
PASSWORD_POLICY = _spec(422, 'password_policy')
INVALID_EMAIL = _spec(422, 'invalid_email')
SESSION_EXPIRED = _spec(401, 'session_expired')
PASSWORD_CHANGE_REQUIRED = _spec(403, 'password_change_required')
CSRF_REJECTED = _spec(403, 'csrf_rejected')
USER_NOT_FOUND = _spec(404, 'user_not_found')


def spec_for_status(status: int) -> ProblemSpec:
    """给「只有 HTTP 状态码、没有业务键」的异常一个通用 problem 规格。"""

    mapping = {
        400: MALFORMED_REQUEST,
        401: UNAUTHORIZED,
        403: PERMISSION_DENIED,
        404: NOT_FOUND,
        405: METHOD_NOT_ALLOWED,
        409: CONFLICT,
        413: PAYLOAD_TOO_LARGE,
        415: UNSUPPORTED_MEDIA_TYPE,
        422: VALIDATION_FAILED,
        429: RATE_LIMITED,
        500: INTERNAL_ERROR,
        502: UPSTREAM_UNAVAILABLE,
        503: SERVICE_UNAVAILABLE,
    }
    if status in mapping:
        return mapping[status]
    if status >= 500:
        return INTERNAL_ERROR
    return ProblemSpec(status, 'http_error', title_for('http_error'))


def _not_found(code: str) -> ProblemSpec:
    return _spec(404, code)


def _conflict(code: str) -> ProblemSpec:
    return _spec(409, code)


def _validation(code: str) -> ProblemSpec:
    return _spec(422, code)


def _build_key_specs() -> dict[str, ProblemSpec]:
    """文案键 → 问题规格。键清单来自 ``backend/src`` 的 raise 点（逐个人工归类）。"""

    groups: list[tuple[ProblemSpec, set[str]]] = [
        # ---- 404 ------------------------------------------------------
        (_not_found('knowledge_base_not_found'), {
            'kbase.not.exist',
            'RetCode.kbase.not.exist',
            'graph.extract.kbid.not.exist',
            'graph.export.kbase.not.found',
        }),
        (_not_found('directory_not_found'), {'directory.not.exist'}),
        (_not_found('file_not_found'), {'file.not.exist'}),
        (_not_found('file_not_found'), {'RetCode.file.not.exist'}),
        (_not_found('dataset_not_found'), {'RetCode.dataSet.not.exist'}),
        (_not_found('operator_not_found'), {
            'RetCode.operator.notfound',
            'RetCode.operator.configjson.notfound',
            'RetCode.operator.python.not.found',
        }),
        (_not_found('schema_not_found'), {
            'RetCode.graph.extract.schema.not.found',
            'graph.export.schema.not.found',
        }),
        (_not_found('entity_not_found'), {
            'RetCode.graph.entity.not.exists',
            'RetCode.graph.schema.edge.entity.not.found',
        }),
        (_not_found('edge_not_found'), {
            'RetCode.graph.edge.not.exists',
            'RetCode.graph.edge.source.not.exists',
            'RetCode.graph.edge.target.not.exists',
        }),
        (_not_found('task_not_found'), {'graph.extract.task.not.exist'}),
        (_not_found('model_not_found'), {'model.not.found'}),
        (_not_found('workflow_not_found'), {
            'workflow.not.exist',
            'draft.not.exist',
        }),
        (_not_found('published_workflow_not_found'), {'published.not.exist'}),
        (_not_found('template_not_found'), {'template.not.found'}),
        (_not_found('api_key_not_found'), {'agent.key.not.found'}),
        # ---- 409 ------------------------------------------------------
        (_conflict('knowledge_base_exists'), {'kbase.exist'}),
        (_conflict('directory_exists'), {'directory.already.exist'}),
        (_conflict('workflow_exists'), {'workflow.exist'}),
        (_conflict('publish_conflict'), {'publish.conflict'}),
        (_conflict('model_name_conflict'), {'model.name.duplicate'}),
        (_conflict('model_in_use'), {'model.in.use'}),
        (_conflict('operator_name_conflict'), {'RetCode.operator.name.duplicate'}),
        (_conflict('operator_already_published'), {'RetCode.operator.publish.repeat'}),
        (_conflict('operator_python_conflict'), {'RetCode.operator.python.exist.more'}),
        (_conflict('graph_entity_exists'), {'RetCode.graph.entity.already.exists'}),
        (_conflict('graph_edge_exists'), {'RetCode.graph.edge.already.exists'}),
        (_conflict('schema_name_conflict'), {'RetCode.graph.schema.name.duplicate'}),
        (_conflict('schema_import_duplicate'), {'RetCode.graph.schema.import.duplicate'}),
        (_conflict('graph_schema_duplicate'), {
            'RetCode.graph.schema.edge.duplicate.type',
            'RetCode.graph.schema.edge.property.duplicate.name',
            'RetCode.graph.schema.entities.duplicate.entity_type',
            'RetCode.graph.schema.entity.property.duplicate.name',
        }),
        (_conflict('knowledge_base_not_empty'), {
            'kbase.can.not.delete.include.knowledge',
        }),
        (_conflict('knowledge_base_in_use'), {'kbase.bound.by.workflow'}),
        (_conflict('task_conflict'), {
            'RetCode.chunk.optimization.no.index.to.rollback',
        }),
        (FILE_NAME_CONFLICT, {'file.upload.rename'}),
        (_conflict('duplicate_file_names'), {'RetCode.upload.file.rename'}),
        # ---- 403 ------------------------------------------------------
        (PERMISSION_DENIED, {
            'permission.denied',
            'Recode.asset.permission.not.allow',
            'agent.key.admin.disabled',
        }),
        # ---- 413 ------------------------------------------------------
        (PAYLOAD_TOO_LARGE, {
            'RetCode.file.size.limit.check',
            'file.size.limit.check',
            'RetCode.file.count.limit',
            'kbase.file.count.exceed',
            'RetCode.operator.workflow.import.sizecheck',
            'RetCode.operator.storage.insufficient',
        }),
        (LIMIT_EXCEEDED, {
            'directory.folder.size.over.limit',
            'directory.level.limit',
        }),
        # ---- 415 ------------------------------------------------------
        (UNSUPPORTED_MEDIA_TYPE, {
            'RetCode.operator.type.incorrect',
        }),
        # ---- 422 ------------------------------------------------------
        (UNSUPPORTED_FILE_TYPE, {'file.type.validation'}),
        (_validation('unsupported_template'), {'template.unsupported'}),
        (_validation('unsupported_engine'), {'engine.unsupported'}),
        (_validation('unsupported_operator'), {'operator.unsupported'}),
        (_validation('operator_plugin_incompatible'), {'operator.plugin.incompatible'}),
        (_validation('unsupported_knowledge_base_type'), {
            'kbase.struct.unsupported',
            'kbase.graph.unsupported',
        }),
        (_validation('unknown_embedding_model'), {'kbase.embedding.unknown'}),
        (_validation('embedding_model_conflict'), {'kbase.embedding.multi'}),
        (_validation('not_a_graph_knowledge_base'), {'graph.export.kbase.not.graph'}),
        (_validation('graph_query_not_ready'), {'RetCode.graph.query.building'}),
        (IMPORT_FAILED, {'Retcode.graph.import.fail'}),
        (_validation('graph_query_failed'), {'RetCode.graph.query.build.failed'}),
        (VALIDATION_FAILED, {
            # 校验 / 语义 / 上传内容
            'RetCode.illegalArgument',
            'request.invalid',
            'request.body.missing',
            'retrieve.type.null',
            'retrieve.type.invalid',
            'retrieve.topK.outOfRange',
            'retrieve.scoreThreshold.outOfRange',
            'retrieve.question.required',
            'retrieve.priority.outOfRange',
            'retrieve.bases.null',
            'retrieve.bases.empty',
            'retrieve.baseList.null',
            'retrieve.baseList.empty',
            'kbase.name.validation',
            'kbase.name.not.all.whitespace',
            'headIcon.validation',
            'description.validation',
            'file.name.length.check',
            'directory.title.validation',
            'graph.extract.taskid.empty',
            'graph.extract.taskid.length.exceed',
            'graph.import.id.format.invalid.char',
            'graph.import.id.format.invalid.length',
            'graph.import.id.format.invalid.prefix',
            'graph.import.edges.file.required',
            'graph.import.entities.file.required',
            'graph.import.illegal',
            'Retcode.graph.import.illegal',
            'Retcode.graph.schema.desc.invalid.chars',
            'Retcode.graph.schema.desc.invalid.length',
            'Retcode.graph.schema.desc.null',
            'Retcode.graph.schema.entities.not.empty',
            'Retcode.graph.schema.entity.property.not.empty',
            'Retcode.graph.schema.entity.property.primary.not.found',
            'Retcode.graph.schema.entity.property.type.invalid',
            'Retcode.graph.schema.entity.property.type.null',
            'Retcode.graph.schema.entity_type.invalid.chars_or_start',
            'Retcode.graph.schema.entity_type.invalid.length',
            'Retcode.graph.schema.entity_type.null',
            'Retcode.graph.schema.entity_type.reserved',
            'Retcode.graph.schema.id.required',
            'Retcode.graph.schema.name.invalid.chars',
            'Retcode.graph.schema.name.invalid.length',
            'RetCode.graph.edge.direction.invalid',
            'RetCode.graph.edge.node.type.pair.mismatch',
            'RetCode.graph.edge.property.not.defined',
            'RetCode.graph.edge.schema.undefined',
            'RetCode.graph.edge.source.node.type.invalid',
            'RetCode.graph.edge.source.node.type.undefined',
            'RetCode.graph.edge.target.node.type.invalid',
            'RetCode.graph.edge.target.node.type.undefined',
            'RetCode.graph.edge.type.not.defined',
            'RetCode.graph.entity.id.invalid',
            'RetCode.graph.entity.property.not.defined',
            'RetCode.graph.entity.schema.undefined',
            'RetCode.graph.entity.type.not.defined',
            'RetCode.graph.query.type.invalid',
            'RetCode.operator.arg.defaultValue.incorrect',
            'RetCode.operator.arg.name.incorrect',
            'RetCode.operator.arg.type.incorrect',
            'RetCode.operator.arg.visibleRange.incorrect',
            'RetCode.operator.configjson.configuration.incorrect',
            'RetCode.operator.description.check',
            'RetCode.operator.description.check.notblank',
            'RetCode.operator.module.check.notblank',
            'RetCode.operator.name.check.notblank',
            'RetCode.operator.name.invalid.cn',
            'RetCode.operator.name.invalid.en',
            'RetCode.operator.textsplit.code.checkNotPass',
            'RetCode.operator.type.not.support',
            'RetCode.split.select.error',
            'RetCode.zip.decompress.error',
            'zip.decompress.error',
            'file.encrypted.check',
            'file.upload.empty.error',
            'workflowId.null',
            'workflowId.not.null',
            'workflowId.too.long',
            'workflowId.invalid',
            'name.not.null',
            'name.too.long',
            'template.not.null',
            'rerank.endpoint.missing',
            'canvas.too.large',
            'canvas.no.kbase',
            'canvas.no.engine',
            'canvas.empty',
            # 模型管理
            'model.baseurl.invalid',
            'model.baseurl.required',
            'model.dimension.invalid',
            'model.dimension.required',
            'model.kind.invalid',
            'model.name.required',
            'model.thinking.payload.invalid',
            'model.thinking.preset.required',
            'model.thinking.preset.unknown',
            # Agent Key 管理
            'agent.key.name.required',
            'agent.key.name.too.long',
            'agent.key.description.invalid',
            'agent.key.description.too.long',
            'agent.key.expires_at.invalid',
            'agent.key.expires_at.past',
            'agent.key.field.unknown',
            'agent.key.kb_ids.invalid',
            'agent.key.kb_ids.too.many',
            'agent.key.no.fields',
            'agent.key.rate_limit.invalid',
            'agent.key.scopes.required',
            'agent.key.scope.unknown',
        }),
        # ---- 502 / 503 / 500 -----------------------------------------
        (UPSTREAM_UNAVAILABLE, {
            'RetCode.embedding.fail',
            'RetCode.zae.get.workflow.fail',
            'model.unavailable',
        }),
        (SERVICE_UNAVAILABLE, {
            'kbase.name.lock.timeout',
            'agent.key.pepper.missing',
            'agent.key.store.unavailable',
        }),
        (INTERNAL_ERROR, {
            'server.error',
            'graph.export.failed',
            'Retcode.generate.graph.schema.fail',
            'RetCode.graph.query.database.operation.failed',
            'file.save.error',
            'kbase.delete.fail',
            'agent.key.create.failed',
        }),
    ]

    specs: dict[str, ProblemSpec] = {}
    for spec, keys in groups:
        for key in keys:
            specs[key] = spec
    return specs


KEY_SPECS = _build_key_specs()

#: 字面量文案（``KbLiteralError``）的显式映射；f-string 形式见 :func:`resolve_problem`
#: 的前缀表。
LITERAL_SPECS: dict[str, ProblemSpec] = {
    '知识库不存在': _not_found('knowledge_base_not_found'),
    '任务不存在': _not_found('task_not_found'),
    '算子不存在': _not_found('operator_not_found'),
    '知识库ID不能为空': MALFORMED_REQUEST,
    '该知识库已有优化任务正在执行': _conflict('task_conflict'),
    '正在处理中的任务不能删除': _conflict('task_conflict'),
    'Required request body is missing': MALFORMED_REQUEST,
    'RetCode.embedding.fail': UPSTREAM_UNAVAILABLE,
}

#: 带参数的 f-string 文案：按前缀归类（参数值不同，无法精确匹配）。
LITERAL_PREFIX_SPECS: tuple[tuple[str, ProblemSpec], ...] = (
    ('算子不存在', _not_found('operator_not_found')),
    ('知识库索引数量已达上限', PAYLOAD_TOO_LARGE),
    ('索引数量已达上限', PAYLOAD_TOO_LARGE),
    ('zae接口调用失败', UPSTREAM_UNAVAILABLE),
)


def resolve_problem(
    *,
    key: Optional[str] = None,
    literal: Optional[str] = None,
    error_code: Optional[str] = None,
    status: Optional[int] = None,
    problem_code: Optional[str] = None,
    default_status: int = 400,
    default_code: str = 'bad_request',
) -> ProblemSpec:
    """把异常携带的信息解析成一个 :class:`ProblemSpec`。

    优先级：显式 ``status`` + ``problem_code`` > 文案键表 > 字面量表 > 数字码 >
    异常类默认值。数字码 ``0001/0004/1001`` 只作为兜底，不参与业务语义判断。
    """

    if status is not None and problem_code:
        return ProblemSpec(status, problem_code, title_for(problem_code))
    if problem_code:
        return ProblemSpec(status or default_status, problem_code, title_for(problem_code))
    if key and key in KEY_SPECS:
        return KEY_SPECS[key]
    if literal:
        spec = LITERAL_SPECS.get(literal)
        if spec:
            return spec
        for prefix, prefix_spec in LITERAL_PREFIX_SPECS:
            if literal.startswith(prefix):
                return prefix_spec
    if error_code == '0001':
        return INTERNAL_ERROR
    if error_code == '0004':
        return VALIDATION_FAILED
    if error_code == '1001':
        return FILE_NAME_CONFLICT
    return ProblemSpec(status or default_status, default_code,
                       title_for(default_code))


# ----------------------------------------------------------------------
# 本地化 detail
# ----------------------------------------------------------------------

GENERIC_DETAILS: dict[str, tuple[str, str]] = {
    # code -> (zh, en)
    'bad_request': ('请求不合法，请检查后重试', 'Bad request; check the request and retry'),
    'malformed_request': ('请求格式不合法，请检查后重试',
                          'Malformed request; check the request and retry'),
    'validation_failed': ('参数不合法，请检查后重试',
                          'Request validation failed; check the parameters and retry'),
    'limit_exceeded': ('请求超出限制', 'Request limit exceeded'),
    'payload_too_large': ('请求内容过大', 'Payload too large'),
    'unsupported_media_type': ('不支持的内容类型', 'Unsupported media type'),
    'unsupported_file_type': ('不支持的文件类型', 'Unsupported file type'),
    'not_found': ('资源不存在', 'Resource not found'),
    'conflict': ('资源冲突', 'Resource conflict'),
    'file_name_conflict': ('同名文件已存在', 'A file with the same name already exists'),
    'permission_denied': ('没有权限执行此操作', 'Permission denied'),
    'unauthorized': ('未认证或登录已失效', 'Unauthorized'),
    'rate_limited': ('请求过于频繁，请稍后重试', 'Too many requests; retry later'),
    # ---- 本地账号 / 登录 ----
    'invalid_credentials': ('账号或密码不正确', 'Incorrect username or password'),
    'account_disabled': ('账号已禁用，请联系管理员', 'Account disabled; contact an administrator'),
    'login_rate_limited': ('尝试次数过多，请稍后再试', 'Too many attempts; try again later'),
    'auth_not_initialized': ('认证服务未初始化，请联系管理员',
                             'Authentication is not initialized; contact an administrator'),
    'auth_not_enabled': ('当前部署未启用登录', 'Login is not enabled in this deployment'),
    'invalid_current_password': ('当前密码不正确', 'Current password is incorrect'),
    'password_policy': ('密码长度必须为 8–128 位，且不能包含控制字符',
                        'Password must be 8–128 characters and contain no control characters'),
    'invalid_email': ('邮箱格式不正确', 'Invalid email address'),
    'session_expired': ('登录已失效，请重新登录', 'Session expired; sign in again'),
    'password_change_required': ('请先修改初始密码', 'Change the initial password first'),
    'csrf_rejected': ('请求来源校验失败，请刷新后重试',
                      'Request origin check failed; refresh and retry'),
    'user_not_found': ('用户不存在', 'User not found'),
    'internal_error': ('服务器内部错误，请稍后重试',
                       'Internal server error; try again later'),
    'upstream_unavailable': ('上游服务不可用，请稍后重试',
                             'Upstream service unavailable; try again later'),
    'service_unavailable': ('服务暂时不可用，请稍后重试',
                            'Service temporarily unavailable; try again later'),
}

#: 常见资源码给更具体的 detail；没有登记的按状态码回落。
SPECIFIC_DETAILS: dict[str, tuple[str, str]] = {
    'knowledge_base_not_found': ('知识库不存在', 'Knowledge base not found'),
    'directory_not_found': ('目录不存在', 'Directory not found'),
    'document_not_found': ('文档不存在', 'Document not found'),
    'file_not_found': ('文件(夹)不存在', 'File not found'),
    'dataset_not_found': ('数据集不存在', 'Dataset not found'),
    'operator_not_found': ('算子不存在', 'Operator not found'),
    'schema_not_found': ('图谱模板不存在', 'Graph schema not found'),
    'entity_not_found': ('图谱实体不存在', 'Graph entity not found'),
    'edge_not_found': ('图谱边不存在', 'Graph edge not found'),
    'task_not_found': ('任务不存在', 'Task not found'),
    'model_not_found': ('模型不存在', 'Model not found'),
    'workflow_not_found': ('工作流不存在', 'Workflow not found'),
    'published_workflow_not_found': ('没有已发布的工作流版本',
                                     'No published workflow version'),
    'template_not_found': ('模板不存在', 'Template not found'),
    'api_key_not_found': ('API Key 不存在', 'API key not found'),
    'query_trace_not_found': ('查询追踪记录不存在', 'Query trace not found'),
    'query_trace_store_unavailable': ('查询追踪存储暂不可用',
                                      'Query trace store unavailable'),
    'knowledge_base_exists': ('同名知识库已存在', 'A knowledge base with that name already exists'),
    'knowledge_base_not_empty': ('知识库内仍有文件，不能删除',
                                 'The knowledge base still contains files'),
    'knowledge_base_in_use': ('知识库已被工作流引用，不能删除',
                              'The knowledge base is referenced by a workflow'),
    'workflow_exists': ('同名工作流已存在', 'A workflow with that name already exists'),
    'publish_conflict': ('发布状态冲突，请刷新后重试',
                         'Publication conflict; refresh and retry'),
    'model_name_conflict': ('同名模型已存在', 'A model with that name already exists'),
    'model_in_use': ('模型正在被使用，不能删除', 'The model is in use'),
    'task_conflict': ('有进行中的任务，暂时不能执行该操作',
                      'A task is still running; retry later'),
    'duplicate_file_names': ('本次上传包含同名文件', 'The upload contains duplicate file names'),
    'graph_entity_exists': ('图谱实体已存在', 'The graph entity already exists'),
    'graph_edge_exists': ('图谱边已存在', 'The graph edge already exists'),
    'schema_name_conflict': ('同名图谱模板已存在', 'A graph schema with that name already exists'),
    'not_a_graph_knowledge_base': ('该知识库不是图谱库', 'Not a graph knowledge base'),
    'graph_query_not_ready': ('图谱正在构建中，暂时不能查询', 'The graph is still being built'),
}

DEFAULT_LANGUAGE = 'en'
SUPPORTED_LANGUAGES = ('zh', 'en')

#: 状态码兜底 detail（code 未登记具体文案时用）。
STATUS_DETAILS: dict[int, tuple[str, str]] = {
    400: GENERIC_DETAILS['bad_request'],
    401: GENERIC_DETAILS['unauthorized'],
    403: GENERIC_DETAILS['permission_denied'],
    404: GENERIC_DETAILS['not_found'],
    409: GENERIC_DETAILS['conflict'],
    413: GENERIC_DETAILS['payload_too_large'],
    415: GENERIC_DETAILS['unsupported_media_type'],
    422: GENERIC_DETAILS['validation_failed'],
    429: GENERIC_DETAILS['rate_limited'],
    500: GENERIC_DETAILS['internal_error'],
    502: GENERIC_DETAILS['upstream_unavailable'],
    503: GENERIC_DETAILS['service_unavailable'],
}


def _normalize_language(language: Optional[str]) -> str:
    value = (language or '').strip().lower()
    if value in SUPPORTED_LANGUAGES:
        return value
    return DEFAULT_LANGUAGE


def generic_detail(spec: ProblemSpec, language: Optional[str] = None) -> str:
    """按语言给出一条通用 detail；保证非空。"""

    lang = _normalize_language(language)
    index = 0 if lang == 'zh' else 1
    specific = SPECIFIC_DETAILS.get(spec.code)
    if specific:
        return specific[index]
    generic = GENERIC_DETAILS.get(spec.code)
    if generic:
        return generic[index]
    status_detail = STATUS_DETAILS.get(spec.status)
    if status_detail:
        return status_detail[index]
    return '请求失败' if lang == 'zh' else 'Request failed'


# ----------------------------------------------------------------------
# 异常基类
# ----------------------------------------------------------------------


class ApiError(Exception):
    """四个家族的异常基类：只携带「文案键 + 参数 + 可选的问题规格」。

    翻译发生在最外层（响应构造时），异常本身不保存已翻译文本。
    ``code`` 保留为**旧数字码**（0001/0004/0005/1001），仅用于过渡期兜底；
    新代码应优先传 ``status`` + ``problem_code``。
    """

    default_status = 400
    default_problem_code = 'bad_request'

    def __init__(self, key: Optional[str] = None, *args,
                 code: Optional[str] = None,
                 status: Optional[int] = None,
                 problem_code: Optional[str] = None):
        super().__init__(key, *args)
        self.key = key
        self.args = args
        self.code = code
        self.status = status
        self.problem_code = problem_code

    def render(self, language: str) -> Optional[str]:
        return None

    def literal_message(self) -> Optional[str]:
        """字面量文案（``KbLiteralError`` 一类）；普通键错误返回 None。"""
        return None

    def problem_spec(self) -> ProblemSpec:
        return resolve_problem(
            key=self.key,
            literal=self.literal_message(),
            error_code=self.code,
            status=self.status,
            problem_code=self.problem_code,
            default_status=self.default_status,
            default_code=self.default_problem_code,
        )

    def problem_detail(self, language: str) -> str:
        detail = self.render(language)
        if detail:
            return detail
        return generic_detail(self.problem_spec(), language)


# ----------------------------------------------------------------------
# 响应
# ----------------------------------------------------------------------


def problem_response(
    spec: ProblemSpec,
    detail: str,
    *,
    instance: Optional[str] = None,
    headers: Optional[Mapping[str, str]] = None,
    extensions: Optional[Mapping[str, Any]] = None,
) -> JSONResponse:
    """构造 ``application/problem+json`` 响应（HTTP 状态码 = ``spec.status``）。"""

    body: dict[str, Any] = {
        'type': PROBLEM_TYPE_PREFIX + spec.code,
        'title': spec.title,
        'status': spec.status,
        'detail': detail or generic_detail(spec),
        'code': spec.code,
    }
    if instance:
        body['instance'] = instance
    if extensions:
        body.update(extensions)
    return JSONResponse(
        status_code=spec.status,
        content=body,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(headers or {}),
    )


def error_response(
    error: ApiError,
    *,
    language: str = DEFAULT_LANGUAGE,
    instance: Optional[str] = None,
    headers: Optional[Mapping[str, str]] = None,
    extensions: Optional[Mapping[str, Any]] = None,
) -> JSONResponse:
    """``ApiError`` → problem 响应；``detail`` 在渲染点按请求语言决定。"""

    spec = error.problem_spec()
    return problem_response(
        spec, error.problem_detail(language), instance=instance,
        headers=headers, extensions=extensions)


# ----------------------------------------------------------------------
# 哪些路径归新契约管
# ----------------------------------------------------------------------

#: 不走 problem+json 的**协议端点**（``/health`` 固定纯文本）。
_NON_PROBLEM_EXACT_PATHS = frozenset({
    f'{RKB_PREFIX}/health',
})


def owns_problem_path(path: str) -> bool:
    """这条路径的 4xx/5xx 是否应转成 problem+json。

    排除的是**协议端点**：``/health``（纯文本）、``/mcp``（MCP 标准语义）。
    其余 ``/api/co-knowledge/v1`` 端点（含 ``/query``、``/agent``、
    ``/retrieval/graph``）都用同一套 ``application/problem+json``。
    """

    if path in _NON_PROBLEM_EXACT_PATHS:
        return False
    if path == AGENT_MCP_PATH or path.startswith(AGENT_MCP_PATH + '/'):
        return False
    return path.startswith(RKB_PREFIX)
