"""模型管理接口的文案（zh / en）。

**刻意不复用 ``shared/i18n/messages.py``**：那个表是基线文案，
渲染还带着 ``MessageFormat`` 的副作用（单引号被吃掉、数字加千分位）。
本接口是**新写的、没有对端契约**，文案不应该继承那些怪癖 ——
所以这里用最朴素的 ``str.replace`` 占位替换，
且**只放本接口自己的键**，不去污染基线表。

语言归一化仍复用 ``infrastructure.http.identity.language``（读 ``Accept-Language``，
``zh-CN`` 才是中文 —— 这条实测结论对整个服务成立，不是 kb_api 私有）。
"""

from __future__ import annotations

DEFAULT_LANGUAGE = 'en'

MESSAGES: dict[str, dict[str, str]] = {
    'model.kind.invalid': {
        'zh': '模型类型不合法，只能是 {0}',
        'en': 'Invalid model kind, expected one of {0}',
    },
    'model.name.required': {
        'zh': '模型名称不能为空',
        'en': 'Model name is required',
    },
    'model.baseurl.required': {
        'zh': '端点地址不能为空',
        'en': 'Endpoint base URL is required',
    },
    'model.baseurl.invalid': {
        'zh': '端点地址必须以 http:// 或 https:// 开头',
        'en': 'Endpoint base URL must start with http:// or https://',
    },
    'model.baseurl.tooLong': {
        'zh': '端点地址长度不能超过 {0} 个字符',
        'en': 'Endpoint base URL must be at most {0} characters',
    },
    'model.field.tooLong': {
        'zh': '{0} 长度不能超过 {1} 个字符',
        'en': '{0} must be at most {1} characters',
    },
    'model.apikey.tooLong': {
        'zh': 'API 密钥过长（最大 {0} 字节）',
        'en': 'API key is too long (max {0} bytes)',
    },
    'model.dimension.required': {
        'zh': 'Embedding 模型必须填写向量维度',
        'en': 'Embedding model requires a vector dimension',
    },
    'model.dimension.invalid': {
        'zh': '向量维度必须是正整数，当前值：{0}',
        'en': 'Vector dimension must be a positive integer, got: {0}',
    },
    'model.not.found': {
        'zh': '模型不存在：{0}',
        'en': 'Model not found: {0}',
    },
    'model.name.duplicate': {
        'zh': '同类型下已存在同名模型：{0}',
        'en': 'A model with the same name already exists in this kind: {0}',
    },
    'model.in.use': {
        'zh': '该模型正被 {0} 个知识库使用，不能删除',
        'en': 'This model is used by {0} knowledge base(s) and cannot be deleted',
    },
    'model.last.default': {
        'zh': '至少要为该类型保留一个默认模型',
        'en': 'At least one default model per kind must be kept',
    },
    'model.endpoint.unreachable': {
        'zh': '端点不可达：{0}',
        'en': 'Endpoint is unreachable: {0}',
    },
    'model.disabled': {
        'zh': '该模型已停用',
        'en': 'This model is disabled',
    },
    'model.thinking.mode.invalid': {
        'zh': '思考模式不合法，只能是 {0}',
        'en': 'Invalid thinking mode, expected one of {0}',
    },
    'model.thinking.preset.required': {
        'zh': '选择预置模式时必须指定预置',
        'en': 'A preset is required when thinking mode is preset',
    },
    'model.thinking.preset.unknown': {
        'zh': '未知的思考预置：{0}',
        'en': 'Unknown thinking preset: {0}',
    },
    'model.thinking.payload.invalid': {
        'zh': '思考配置必须是合法的 JSON 对象',
        'en': 'Thinking config must be a valid JSON object',
    },
    'model.thinking.payload.key': {
        'zh': '思考配置包含不允许的顶层键：{0}',
        'en': 'Thinking config contains a disallowed top-level key: {0}',
    },
    'model.thinking.payload.tooLarge': {
        'zh': '思考配置超过大小上限（{0} 字节）',
        'en': 'Thinking config exceeds the size limit ({0} bytes)',
    },
}


def render(key: str, language: str, *args) -> str:
    """按语言渲染文案；未知键回落成键名（便于排障，不静默吞掉）。

    占位符是 ``{0}`` / ``{1}`` 的**朴素替换**，与 kb_api 的 MessageFormat 语义无关。
    """
    entry = MESSAGES.get(key)
    if not entry:
        return key
    text = entry.get(language) or entry.get(DEFAULT_LANGUAGE) or key
    for index, value in enumerate(args):
        text = text.replace('{%d}' % index, str(value))
    return text
