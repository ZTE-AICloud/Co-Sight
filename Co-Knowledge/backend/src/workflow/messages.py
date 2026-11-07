"""flow_api 的中英文案。

**文案是对外契约的一部分**：前端把这几句直接弹给用户看，切换时文案变了会让
「同一功能两种提示」，也会让排障时对不上日志。

``render`` 用 ``str.format`` 风格，占位符写成 ``{0}``、``{1}``。

**文案语言 = ``Accept-Language``**（不是 ``language-option``／``X-Lang-Id``）。
归一化规则复用 kb_api（见 :func:`normalize_language`），两套接口对同一请求头必须
给出同一结论。模板变体语言是另一条规则，见 :func:`normalize_template_language`。
"""

from __future__ import annotations

# key -> {语言: 文案}
MESSAGES = {
    'workflowId.not.null': {
        'zh': '知识检索ID不能为空',
        'en': 'Knowledge retrieval ID cannot be empty',
    },
    'workflowId.too.long': {
        'zh': '知识检索ID长度不能超过128',
        'en': 'Knowledge retrieval ID cannot exceed 128 characters',
    },
    'workflowId.invalid': {
        'zh': '知识检索ID只支持数字、字母、下划线',
        'en': 'Knowledge retrieval ID only supports letters, digits and underscores',
    },
    'name.not.null': {
        'zh': '知识检索名称不能为空',
        'en': 'Knowledge retrieval name cannot be empty',
    },
    'name.too.long': {
        'zh': '知识检索名称长度不能超过255',
        'en': 'Knowledge retrieval name cannot exceed 255 characters',
    },
    'publishType.invalid': {
        'zh': '发布状态筛选参数 publishType 只能是 0（未发布）、1（已发布）或 2（已发布有改动）',
        'en': 'publishType must be 0 (unpublished), 1 (published) or 2 (published with changes)',
    },
    'description.too.long': {
        'zh': '描述长度不能超过1000',
        'en': 'Description cannot exceed 1000 characters',
    },
    'template.too.long': {
        'zh': '知识检索模板长度不能超过64',
        'en': 'Knowledge retrieval template cannot exceed 64 characters',
    },
    'workflow.exist': {
        'zh': '知识检索 {0} 已存在',
        'en': 'Knowledge retrieval {0} already exists',
    },
    'template.not.null': {
        'zh': '请先选择知识检索模板',
        'en': 'Select a knowledge retrieval template first',
    },
    'template.unsupported': {
        'zh': '当前版本不支持模板 {0}（可选顺序检索 / 混合检索 / 条件检索）',
        'en': 'Template {0} is not supported in this version '
              '(choose Sequential, Blended or Conditional)',
    },
    'template.not.found': {
        'zh': '知识检索模板 {0} 缺失或损坏，请重新部署后再试',
        'en': 'Knowledge retrieval template {0} is missing or corrupted; redeploy and try again',
    },
    'canvas.no.kbase': {
        'zh': '请至少选择一个知识库后再创建知识检索',
        'en': 'Select at least one knowledge base before creating the knowledge retrieval',
    },
    'kbase.struct.unsupported': {
        'zh': '当前版本不支持结构化（数据库）知识库，请改用文档知识库：{0}',
        'en': 'Structured (database) knowledge bases are not supported in this version; '
              'use document knowledge bases instead: {0}',
    },
    'kbase.graph.unsupported': {
        'zh': '当前版本不支持图谱知识库，请改用文档知识库：{0}',
        'en': 'Graph knowledge bases are not supported in this version; '
              'use document knowledge bases instead: {0}',
    },
    'kbase.embedding.multi': {
        'zh': '检索中选择的知识库包含不同的向量化模型（{0}），请改为选择使用同一向量化模型的知识库',
        'en': 'The knowledge bases selected for retrieval use different embedding models ({0}); '
              'select knowledge bases that share one embedding model',
    },
    'kbase.embedding.unknown': {
        'zh': '未能识别所选知识库的向量化模型，无法创建知识检索',
        'en': 'Cannot determine the embedding model of the selected knowledge bases; '
              'the knowledge retrieval cannot be created',
    },
    'workflow.not.exist': {
        'zh': '知识检索 {0} 不存在',
        'en': 'Knowledge retrieval {0} does not exist',
    },
    'canvas.empty': {
        'zh': '画布为空，请至少添加一个节点后再保存',
        'en': 'The canvas is empty; add at least one node before saving',
    },
    'canvas.no.engine': {
        'zh': '画布缺少编排引擎（QUERY_ENGINE）节点，请重新加载画布后再试',
        'en': 'The canvas has no QUERY_ENGINE node; reload the canvas and try again',
    },
    'canvas.too.large': {
        'zh': '画布内容过大（上限 {0}MB），请精简节点或算子配置',
        'en': 'Canvas is too large (limit {0}MB); trim nodes or operator settings',
    },
    'engine.unsupported': {
        # {1} = 本版本可执行的引擎清单（由 `validation` 按 `canvas.ENGINE_OPERATORS` 填入，
        # 不在文案里写死，免得清单变了文案不跟着变）
        'zh': '编排引擎 {0} 在当前版本不可执行，仅支持 {1}',
        'en': 'Query engine {0} cannot run in this version; supported engines: {1}',
    },
    'operator.unsupported': {
        'zh': '算子 {0} 在当前版本不可执行',
        'en': 'Operator {0} cannot run in this version',
    },
    'rerank.endpoint.missing': {
        'zh': '当前部署未提供重排（rerank）端点，ExternalModelReranker 运行时会失败，建议改用 {0}',
        'en': 'No rerank endpoint is deployed, so ExternalModelReranker will fail at runtime; use {0} instead',
    },
    'rerank.model.unavailable': {
        # 只检查画布上**显式选了**模型的外部重排算子；空值 = 跟随部署默认，不算错。
        'zh': '画布选择的重排模型 {0} 未在模型注册表中配置，知识检索运行时会失败，请重新选择',
        'en': 'The rerank model(s) {0} selected on the canvas are not configured in the model '
              'registry, so the knowledge retrieval will fail at runtime; pick another model',
    },
    'embedding.model.unavailable': {
        # 只检查画布上**显式写了**的向量模型；空值 = 跟随部署默认，不算错。
        # 名字不在清单里时运行期会回落 .env 端点，而那个端点不一定服务这个名字 ——
        # 图谱检索 502 就是这条。
        'zh': '画布选择的向量模型 {0} 未在模型注册表中配置，检索与问答会失败，请重新选择',
        'en': 'The embedding model(s) {0} selected on the canvas are not configured in the '
              'model registry, so retrieval and answering will fail; pick another model',
    },
    'embedding.dimension.mismatch': {
        # 名字能解析、库也能查，但两边的向量维度对不上。{0} = 逐条
        # "库名 (kbase=1024d, model=X 1792d)"，用 "; " 连接。
        'zh': '以下知识库的向量维度与检索器选择的模型不一致，检索结果必然为空，'
              '请改用与知识库一致的向量模型：{0}',
        'en': 'The knowledge bases below were built with a different vector dimension than '
              'the embedding model selected on the canvas, so retrieval will return nothing; '
              'pick a model that matches the knowledge base: {0}',
    },
    'model.unavailable': {
        # 只在**探测成功**时才会出现（拿不到清单就放行），所以文案可以断定「端点确实没有」，
        # 而不是「查不到」。{0} = 画布里用到但端点没有的模型名，逗号分隔。
        'zh': '生成端点未提供模型 {0}，知识检索运行时会失败，请在画布上改选其它模型',
        'en': 'The generation endpoint does not serve model(s) {0}, so the knowledge retrieval will fail '
              'at runtime; pick another model on the canvas',
    },
    'empty.stage': {
        'zh': '环节 {0} 没有配置任何算子，运行时会被跳过',
        'en': 'Stage {0} has no operator configured and will be skipped at runtime',
    },
    'draft.not.exist': {
        'zh': '知识检索 {0} 还没有保存过画布，无法发布',
        'en': 'Knowledge retrieval {0} has no saved canvas yet and cannot be published',
    },
    'published.not.exist': {
        'zh': '知识检索 {0} 还没有已发布的版本，请先在画布上保存并发布',
        'en': 'Knowledge retrieval {0} has no published version; save and publish it first',
    },
    'export.failed': {
        'zh': '导出知识检索 {0} 失败',
        'en': 'Failed to export knowledge retrieval {0}',
    },
    'publish.conflict': {
        'zh': '知识检索 {0} 正在被发布，请稍后重试',
        'en': 'Knowledge retrieval {0} is being published concurrently, please retry',
    },
    'reasoning.model.recommend': {
        'zh': '问题重构算子使用了推理模型 {0}，此类模型重构问题需要较长的时间，是否继续使用？',
        'en': 'The query rewrite operator uses the reasoning model {0}; rewriting a query with '
              'this kind of model takes a long time. Continue anyway?',
    },
    'server.error': {
        'zh': '服务器内部错误，请稍后重试',
        'en': 'Internal server error, please try again later',
    },
    # 请求体畸形 / 缺必填 query 参数（appId）统一用 ``RetCode.illegalArgument``，
    # 文案是 "Argument is illegal, please check and retry." / 「参数不合法，请检查后重试」。
    # 别用 ``request.invalid`` 顶替 —— 文案不一样。
    'RetCode.illegalArgument': {
        'zh': '参数不合法，请检查后重试',
        'en': 'Argument is illegal, please check and retry.',
    },
    # 必填请求体「缺席」（0 字节或字面量 null）走统一的读体失败路径，对含
    # "Required request body is missing" 的消息**特判直接回这句英文**（不查 i18n 表）——
    # zh-CN 请求回的也是英文，所以两种语言写同一句不是笔误。
    'request.body.missing': {
        'zh': 'Required request body is missing',
        'en': 'Required request body is missing',
    },
}

DEFAULT_LANGUAGE = 'en'
SUPPORTED_LANGUAGES = ('zh', 'en')

def normalize_language(language: str | None) -> str:
    """把 ``Accept-Language`` 的主标签归一化成 ``zh`` / ``en``（**文案语言**）。

    ⚠️ **不是「zh 开头就中文」，也不是读 ``language-option``／``X-Lang-Id``。**
    文案语言只认 ``Accept-Language`` 的主标签，``X-Lang-Id`` 不参与判定。

    只有 ``zh-CN``（浏览器发的主标签）与 ``*`` 落中文，其余（含不带这个头）一律英文 ——
    根因是 ``ResourceBundleMessageSource`` 默认 ``fallbackToSystemLocale=true``，
    回落的是服务端默认 locale（en_US），而不是基础包。完整实测表见
    ``infrastructure/http/identity.py`` 的 :func:`~infrastructure.http.identity.language`。

    规则**复用 kb_api 的实现**（延迟 import：与 ``service.py`` 里 import
    ``knowledge_base.kbase_options`` 同一约定，避免两个接口族在导入期互相牵连）：
    两套接口对同一请求头必须给出同一结论，抄一份迟早会漂。
    """
    from shared.i18n.messages import normalize_language as kb_normalize_language

    return kb_normalize_language(language)

def normalize_template_language(language: str | None) -> str:
    """把 ``language-option`` 头归一化成 ``zh`` / ``en``（**模板/内容变体语言**）。

    与 :func:`normalize_language`（文案语言）**不是同一条规则**：这是 RKB 既有的
    ``tool.http.httputil.get_language_option`` —— ``language-option`` 以 ``zh``
    开头即中文、其余英文，用于建流播种时挑中文还是英文模板（算子里的提示词不同）。
    对应 kb_api 里 ``header_language()``（内容命名）与 ``language()``（文案）的二分：
    文案看 ``Accept-Language``，内容变体看 ``language-option``。

    ⚠️ 别拿它渲染错误文案 —— 浏览器不发 ``language-option``，文案会永远回落英文
    （这正是本轮修掉的语义倒置）。
    """
    if language and language.lower().startswith('zh'):
        return 'zh'
    return DEFAULT_LANGUAGE

def _resolve(language: str | None) -> str:
    """把 ``language`` 定成 ``zh`` / ``en``（与 ``kb_api.messages._resolve`` 同规则）。

    ``zh`` 这个值有歧义：作为**归一化结果**它是中文，作为**原始 Accept-Language
    标签**它却是英文。这里的入参一律按「已经是归一化结果」理解 —— 生产路径上
    :func:`normalize_language`（或 kb_api 的 ``identity.language``）在传给
    service/envelope 之前就已经归一化好了。真有人塞了原始标签，也会被
    :func:`normalize_language` 兜住（除 ``zh`` 这一个值以外）。
    """
    value = (language or '').strip().lower()
    if value in SUPPORTED_LANGUAGES:
        return value
    return normalize_language(language)

def render(key: str, language: str, *args) -> str:
    """按语言渲染文案；未知键回落成键名（便于排障，不静默吞掉）。"""
    entry = MESSAGES.get(key)
    if not entry:
        return key
    template = entry.get(_resolve(language)) or entry.get(DEFAULT_LANGUAGE) or key
    if not args:
        return template
    try:
        return template.format(*args)
    except (IndexError, KeyError):
        # 参数个数对不上是编码错误：返回原文案（带占位符）比抛异常更适合线上
        return template
