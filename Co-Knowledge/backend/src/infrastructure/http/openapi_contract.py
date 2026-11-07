"""从 FastAPI 路由生成**全量**对外 OpenAPI 契约（`contracts/openapi/rkb-api.yaml`）。

主应用刻意不暴露 `/openapi.json` / `/docs`（见 ``app.py``），但对外仍需要一份
可交付的 OpenAPI。这里把运行时路由表转成静态契约，并用快照测试钉住：

* 路径 / 方法**全量覆盖**（排除兜底路由与协议端点 ``/mcp``）；
* 所有非 2xx 统一引用 RFC 9457 ``Problem``；
* 已知的 201/202/204、下载流与 `/query` SSE 按真实行为标注；
* 手工接口定义没有 Pydantic 模型时，补一个宽松的 JSON request body（不假装知道字段）。

生成器：``tools/verify/generate-rkb-openapi.py``。
"""
from __future__ import annotations

from typing import Any

from fastapi.openapi.utils import get_openapi

from shared.prefixes import AGENT_MCP_PATH, AGENT_PREFIX, RKB_PREFIX

API_VERSION = '2.3.0'
_PROBLEM_REF = '#/components/schemas/Problem'

#: 成功状态不是 200 的操作。逐键显式，来源是各 router 的 ``ok_status``。
_SUCCESS_STATUS: dict[tuple[str, str], int] = {
    ('post', '/knowledge-bases'): 201,
    ('post', '/knowledge-bases/{kbase_id}/directories'): 201,
    ('post', '/knowledge-bases/{kbase_id}/documents'): 201,
    ('post', '/knowledge-bases/{kbase_id}/chunks'): 201,
    ('delete', '/knowledge-bases/{kbase_id}'): 204,
    ('delete', '/knowledge-bases/{kbase_id}/directories/{directory_id}'): 204,
    ('delete', '/knowledge-bases/{kbase_id}/documents/{document_id}'): 204,
    ('post', '/operators'): 201,
    ('delete', '/operators/{operator_id}'): 204,
    ('post', '/operators/{operator_id}/publish'): 204,
    ('delete', '/operators/{operator_id}/publish'): 204,
    ('put', '/operators/{operator_id}/visibility'): 204,
    ('post', '/graph-schemas'): 201,
    ('post', '/graph-extractions'): 202,
    ('post', '/graph-imports'): 202,
    ('put', '/knowledge-bases/{kbase_id}/graph'): 202,
    ('post', '/knowledge-bases/{kbase_id}/graph/entities'): 201,
    ('post', '/knowledge-bases/{kbase_id}/graph/edges'): 201,
    ('post', '/workflows'): 201,
    ('delete', '/workflows/{workflow_id}'): 204,
    ('post', '/workflows/{workflow_id}/publication'): 201,
    ('delete', '/workflows/{workflow_id}/publication'): 204,
    ('post', '/models'): 201,
    ('post', '/agent-keys'): 201,
    ('post', '/auth/logout'): 204,
    ('post', '/auth/password'): 204,
}

#: 手工解析 multipart 的操作：FastAPI 没生成 requestBody，这里补正确媒体类型。
_MULTIPART_BODIES = frozenset({
    ('post', '/graph-extractions'),
    ('put', '/knowledge-bases/{kbase_id}/graph'),
})

# ----------------------------------------------------------------------
# 显式请求体
#
# 这些端点在 handler 里用 ``request.query_params`` / ``request.form()`` 或
# ``responses.parse_json_body`` 手工解析，FastAPI 推导不出 requestBody，之前的契约
# 只能写 ``additionalProperties: true``（等于没写字段）。下面的 schema 与实际绑定、
# 服务层校验一一对应；改请求体时**两处一起改**。
# ----------------------------------------------------------------------

def _free_object() -> dict[str, Any]:
    """新的自由对象 schema。

    必须每次返回新 dict：``yaml.safe_dump`` 会给同一对象的多处引用打锚点
    （``&id001`` / ``*id001``），契约文件会变得不可读。
    """
    return {'type': 'object', 'additionalProperties': True}

#: 与 ``knowledge_base/service/kbase_write_service.py`` 的 ``KbaseReqDTO`` 对齐。
_KBASE_PROPS = {
    'type': 'object',
    'description': '建库属性；只认 embeddingModel，其余键被丢弃',
    'required': ['embeddingModel'],
    'properties': {'embeddingModel': {'type': 'string', 'description': 'embedding 注册名'}},
}

_REQUEST_SCHEMAS: dict[str, dict[str, Any]] = {
    'KbaseCreateRequest': {
        'type': 'object',
        'required': ['name', 'props'],
        'properties': {
            'name': {'type': 'string', 'minLength': 2, 'maxLength': 30,
                     'description': '允许中文/字母/数字/_ . - 与空白'},
            'description': {'type': 'string', 'maxLength': 1000},
            'headIcon': {'type': 'string', 'maxLength': 255},
            'kbtype': {'type': 'string', 'description': '子类型标识，默认 document'},
            'category': {'type': 'integer', 'enum': [1, 10],
                         'description': '1 文档库 / 10 图谱库；文档库链路忽略此字段'},
            'props': _KBASE_PROPS,
        },
    },
    'KbaseUpdateRequest': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'minLength': 2, 'maxLength': 30},
            'description': {'type': 'string', 'maxLength': 1000,
                            'description': '出现即更新，空串表示清空'},
            'headIcon': {'type': 'string', 'maxLength': 255},
        },
    },
    'DirectoryCreateRequest': {
        'type': 'object',
        'required': ['title'],
        'properties': {
            'title': {'type': 'string', 'minLength': 2, 'maxLength': 30},
            'parentId': {'type': 'string', 'nullable': True,
                         'description': '省略/空串 = 根目录'},
        },
    },
    'DirectoryUpdateRequest': {
        'type': 'object',
        'properties': {'title': {'type': 'string', 'description': '空名或同名时原样返回'}},
    },
    'DocumentMoveRequest': {
        'type': 'object',
        'required': ['ids', 'parentId'],
        'properties': {
            'ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1},
            'parentId': {'type': 'string', 'description': '目标文件夹 ID'},
        },
    },
    'DocumentUploadForm': {
        'type': 'object',
        'required': ['files', 'metadata'],
        'properties': {
            'files': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
            'metadata': {
                'type': 'string',
                'description': 'JSON 字符串：directoryId / kType / splitType 必填，'
                               'splitOperator 缺键走 NPE（500），coverFlag 可选',
            },
        },
    },
    'ChunkCreateRequest': {
        'type': 'object',
        'required': ['documentId', 'content'],
        'properties': {
            'documentId': {'type': 'string', 'description': '所属文档 ID'},
            'content': {'type': 'string', 'description': '切片正文，用于生成向量'},
            'supplement': {'type': 'string', 'description': '补充文本，缺省回落 content'},
        },
    },
    'GraphExtractionForm': {
        'type': 'object',
        'required': ['file', 'data'],
        'properties': {
            'file': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
            'data': {'type': 'string',
                     'description': 'JSON 字符串：name/category/props/operatorId/schemaId 必填'},
        },
    },
    'GraphUpdateForm': {
        'type': 'object',
        'required': ['data', 'deleteFiles', 'localFiles'],
        'properties': {
            'data': {'type': 'string', 'description': 'JSON 字符串，结构同抽图建库'},
            'deleteFiles': {'type': 'string', 'description': 'JSON 数组字符串'},
            'localFiles': {'type': 'string', 'description': 'JSON 数组字符串'},
            'files': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
        },
    },
    'RetrievalRequest': {
        'type': 'object',
        'required': ['question', 'bases'],
        'properties': {
            'question': {'type': 'string', 'description': '检索问题，不能为空白'},
            'type': {'type': 'integer', 'enum': [0, 1],
                     'description': '0 向量（默认）/ 1 关键词'},
            'model': {'type': 'string', 'description': 'embedding 注册名'},
            'bases': {
                'type': 'array', 'minItems': 1,
                'items': {
                    'type': 'object',
                    'required': ['baseList'],
                    'properties': {
                        'baseList': {'type': 'array', 'minItems': 1,
                                     'items': {'type': 'string'},
                                     'description': '文档库 base 名：doc_<kb_id>'},
                        'priority': {'type': 'integer', 'minimum': 0, 'maximum': 10},
                        'top_k': {'type': 'integer', 'minimum': 1, 'maximum': 80,
                                  'default': 8},
                        'score_threshold': {'type': 'number', 'minimum': 0, 'maximum': 1,
                                            'default': 0, 'description': '仅向量路生效'},
                    },
                },
            },
        },
    },
    'GraphQueryRequest': {
        'type': 'object',
        'required': ['query_type'],
        'properties': {
            'query_type': {'type': 'string', 'enum': ['entity', 'edge', 'path', 'sub_graph']},
            'filters': {'type': 'array', 'items': _free_object(),
                        'description': '过滤条件；类型类字段必须是数组'},
            'depth': {'type': 'integer', 'minimum': 1, 'maximum': 100},
            'direction': {'type': 'string', 'enum': ['both', 'in', 'out'], 'default': 'both'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'default': 100},
            'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
            'cursor': {'type': 'string', 'description': '给出时优先于 offset'},
            'keyword': {'type': 'string', 'description': '实体名称/ID/描述模糊匹配'},
        },
    },
    'GraphEntityCreateRequest': {
        'type': 'object',
        'required': ['entityId', 'entityType', 'properties'],
        'properties': {
            'entityId': {'type': 'string', 'description': '格式 {实体类型}_{序号}'},
            'entityType': {'type': 'string', 'description': '必须是模板已声明的实体类型'},
            'properties': {'type': 'object', 'additionalProperties': True},
            'edgeInfo': {'type': 'object', 'description': '可选：同时建一条边',
                         'properties': {
                             'edgeId': {'type': 'string'},
                             'edgeType': {'type': 'string'},
                             'currentEntityId': {'type': 'string'},
                             'direction': {'type': 'string', 'enum': ['in', 'out']},
                             'properties': _free_object(),
                         }},
        },
    },
    'GraphEntityUpdateRequest': {
        'type': 'object',
        'required': ['entityType', 'properties'],
        'properties': {
            'entityType': {'type': 'string'},
            'properties': {'type': 'object', 'additionalProperties': True},
        },
    },
    'GraphEdgeCreateRequest': {
        'type': 'object',
        'required': ['edgeId', 'edgeType', 'sourceId', 'targetId', 'properties'],
        'properties': {
            'edgeId': {'type': 'string', 'description': '格式 {边类型}_{序号}'},
            'edgeType': {'type': 'string'},
            'sourceId': {'type': 'string'},
            'targetId': {'type': 'string'},
            'properties': {'type': 'object', 'additionalProperties': True},
        },
    },
    'GraphEdgeUpdateRequest': {
        'type': 'object',
        'required': ['edgeType', 'properties'],
        'properties': {
            'edgeType': {'type': 'string'},
            'properties': {'type': 'object', 'additionalProperties': True},
        },
    },
    'GraphSchemaRequest': {
        'type': 'object',
        'description': '创建时 schema_id 必填；PATCH 时路径参数覆盖同名字段',
        'required': ['schema_name', 'schema_desc', 'entities', 'edges'],
        'properties': {
            'schema_id': {'type': 'string'},
            'schema_name': {'type': 'string'},
            'schema_desc': {'type': 'string'},
            'entities': {'type': 'array', 'items': _free_object(),
                         'description': '实体类型；不能为空数组'},
            'edges': {'type': 'array', 'items': _free_object(),
                      'description': '必须出现（可为 []）；缺键走 NPE（500）'},
        },
    },
    'OperatorVisibilityRequest': {
        'type': 'object',
        'required': ['public'],
        'properties': {'public': {'type': 'boolean'}},
    },
    'ModelCreateRequest': {
        'type': 'object',
        'required': ['modelKind', 'modelName', 'baseUrl'],
        'properties': {
            'modelKind': {'type': 'string', 'enum': ['llm', 'embedding', 'rerank']},
            'modelName': {'type': 'string', 'description': '注册名，同 kind 下唯一'},
            'displayName': {'type': 'string'},
            'apiModel': {'type': 'string'},
            'baseUrl': {'type': 'string', 'format': 'uri'},
            'apiKey': {'type': 'string', 'description': '加密存储，读取接口不回明文'},
            'chatPath': {'type': 'string'},
            'embeddingsPath': {'type': 'string'},
            'modelsPath': {'type': 'string'},
            'rerankPath': {'type': 'string'},
            'dimension': {'type': 'integer', 'description': 'embedding 必填'},
            'maxTokens': {'type': 'integer'},
            'temperature': {'type': 'number'},
            'timeout': {'type': 'integer', 'description': '秒'},
            'isReasoning': {'type': 'boolean'},
            'thinkingMode': {'type': 'string', 'enum': ['none', 'auto', 'preset', 'custom']},
            'thinkingPreset': {'type': 'string'},
            'thinkingPayload': _free_object(),
            'isDefault': {'type': 'boolean'},
            'enabled': {'type': 'boolean', 'default': True},
            'remark': {'type': 'string'},
        },
    },
    'ModelUpdateRequest': {
        'type': 'object',
        'description': '部分合并；apiKey 缺席/空串保持原值，clearApiKey=true 清空',
        'properties': {
            'modelName': {'type': 'string'},
            'displayName': {'type': 'string'},
            'apiModel': {'type': 'string'},
            'baseUrl': {'type': 'string', 'format': 'uri'},
            'apiKey': {'type': 'string'},
            'clearApiKey': {'type': 'boolean'},
            'chatPath': {'type': 'string'},
            'embeddingsPath': {'type': 'string'},
            'modelsPath': {'type': 'string'},
            'rerankPath': {'type': 'string'},
            'dimension': {'type': 'integer'},
            'maxTokens': {'type': 'integer'},
            'temperature': {'type': 'number'},
            'timeout': {'type': 'integer'},
            'isReasoning': {'type': 'boolean'},
            'thinkingMode': {'type': 'string', 'enum': ['none', 'auto', 'preset', 'custom']},
            'thinkingPreset': {'type': 'string'},
            'thinkingPayload': _free_object(),
            'isDefault': {'type': 'boolean'},
            'enabled': {'type': 'boolean'},
            'remark': {'type': 'string'},
        },
    },
    'ModelTestRequest': {
        'type': 'object',
        'required': ['modelKind', 'baseUrl'],
        'description': '与建模型同形；modelName 缺省用 probe',
        'properties': {
            'modelKind': {'type': 'string', 'enum': ['llm', 'embedding', 'rerank']},
            'modelName': {'type': 'string'},
            'apiModel': {'type': 'string'},
            'baseUrl': {'type': 'string', 'format': 'uri'},
            'apiKey': {'type': 'string'},
            'chatPath': {'type': 'string'},
            'embeddingsPath': {'type': 'string'},
            'modelsPath': {'type': 'string'},
            'rerankPath': {'type': 'string'},
            'dimension': {'type': 'integer'},
        },
    },
    'SavedModelTestRequest': {
        'type': 'object',
        'description': '全部字段可选；不提供 apiKey 时服务端丢弃 baseUrl 与各路径，'
                       '按已保存配置测试（防止用已存密钥请求任意主机）',
        'properties': {
            'baseUrl': {'type': 'string', 'format': 'uri'},
            'apiKey': {'type': 'string'},
            'chatPath': {'type': 'string'},
            'embeddingsPath': {'type': 'string'},
            'modelsPath': {'type': 'string'},
            'rerankPath': {'type': 'string'},
        },
    },
    'WorkflowCreateRequest': {
        'type': 'object',
        'required': ['workFlowId', 'name', 'template'],
        'properties': {
            'workFlowId': {'type': 'string', 'maxLength': 128,
                           'description': '也接受 workflowId / appId；只允许 [A-Za-z0-9_]'},
            'name': {'type': 'string', 'maxLength': 255},
            'template': {'type': 'string', 'maxLength': 64,
                         'enum': ['Sequential', 'Blended', 'Conditional']},
            'knowledgeType': {'type': 'string'},
            'description': {'type': 'string', 'maxLength': 1000},
            'boundInfo': {'type': 'object',
                          'description': '按分组 running/dev 放知识库选项；元素至少带 '
                                         'tableName、embeddingModel、type',
                          'additionalProperties': True},
        },
    },
    'WorkflowUpdateRequest': {
        'type': 'object',
        'required': ['name'],
        'properties': {
            'name': {'type': 'string', 'maxLength': 255},
            'template': {'type': 'string', 'maxLength': 64},
            'knowledgeType': {'type': 'string'},
            'description': {'type': 'string', 'maxLength': 1000},
        },
    },
    'WorkflowCanvasRequest': {
        'type': 'object',
        'required': ['nodeConfigDTOList', 'otherNodeConfigList'],
        'properties': {
            'flowType': {'type': 'string'},
            'version': {'type': 'integer', 'description': '草稿保存不使用，仅发布推进版本'},
            'nodeConfigDTOList': {'type': 'array', 'minItems': 1, 'items': _free_object(),
                                  'description': '可视节点；data.variables 内放算子'},
            'otherNodeConfigList': {'type': 'array', 'items': _free_object(),
                                    'description': '必须包含 QUERY_ENGINE 节点'},
        },
    },
    'AgentKeyCreateRequest': {
        'type': 'object',
        'required': ['name', 'scopes'],
        'properties': {
            'name': {'type': 'string', 'maxLength': 128},
            'description': {'type': 'string', 'maxLength': 200},
            'scopes': {'type': 'array', 'minItems': 1, 'items': {
                'type': 'string',
                'enum': ['kb:list', 'kb:search', 'kb:answer', 'workflow:read', 'workflow:run'],
            }},
            'kbIds': {'type': 'array', 'items': {'type': 'string'},
                      'description': '白名单；空数组 = 全部文档库'},
            'rateLimitPerMin': {'type': 'integer', 'minimum': 0, 'maximum': 100000,
                                'default': 60, 'description': '0 表示不限'},
            'expiresAt': {'type': 'string', 'nullable': True,
                          'description': 'ISO 8601 或 YYYY-MM-DD；null = 永不过期'},
        },
    },
    'AgentKeyUpdateRequest': {
        'type': 'object',
        'description': '部分更新；expiresAt 显式 null 表示清空过期时间',
        'properties': {
            'name': {'type': 'string', 'maxLength': 128},
            'description': {'type': 'string', 'maxLength': 200},
            'scopes': {'type': 'array', 'minItems': 1, 'items': {
                'type': 'string',
                'enum': ['kb:list', 'kb:search', 'kb:answer', 'workflow:read', 'workflow:run'],
            }},
            'kbIds': {'type': 'array', 'items': {'type': 'string'}},
            'rateLimitPerMin': {'type': 'integer', 'minimum': 0, 'maximum': 100000},
            'expiresAt': {'type': 'string', 'nullable': True},
            'enabled': {'type': 'boolean'},
        },
    },
}


def _request_body(component: str, media: str = 'application/json',
                  *, required: bool = True) -> dict[str, Any]:
    return {
        'required': required,
        'content': {media: {'schema': {'$ref': f'#/components/schemas/{component}'}}},
    }


_MULTIPART = 'multipart/form-data'

_REQUEST_BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ('post', '/knowledge-bases'): _request_body('KbaseCreateRequest'),
    ('patch', '/knowledge-bases/{kbase_id}'): _request_body('KbaseUpdateRequest'),
    ('post', '/knowledge-bases/{kbase_id}/directories'): _request_body('DirectoryCreateRequest'),
    ('patch', '/knowledge-bases/{kbase_id}/directories/{directory_id}'):
        _request_body('DirectoryUpdateRequest'),
    ('post', '/knowledge-bases/{kbase_id}/documents'):
        _request_body('DocumentUploadForm', _MULTIPART),
    ('patch', '/knowledge-bases/{kbase_id}/documents'): _request_body('DocumentMoveRequest'),
    ('post', '/knowledge-bases/{kbase_id}/chunks'): _request_body('ChunkCreateRequest'),
    ('post', '/graph-schemas'): _request_body('GraphSchemaRequest'),
    ('patch', '/graph-schemas/{schema_id}'): _request_body('GraphSchemaRequest'),
    ('post', '/graph-extractions'): _request_body('GraphExtractionForm', _MULTIPART),
    ('put', '/knowledge-bases/{kbase_id}/graph'): _request_body('GraphUpdateForm', _MULTIPART),
    ('post', '/knowledge-bases/{kbase_id}/graph/query'): _request_body('GraphQueryRequest'),
    ('post', '/knowledge-bases/{kbase_id}/graph/entities'):
        _request_body('GraphEntityCreateRequest'),
    ('patch', '/knowledge-bases/{kbase_id}/graph/entities/{entity_id}'):
        _request_body('GraphEntityUpdateRequest'),
    ('post', '/knowledge-bases/{kbase_id}/graph/edges'): _request_body('GraphEdgeCreateRequest'),
    ('patch', '/knowledge-bases/{kbase_id}/graph/edges/{edge_id}'):
        _request_body('GraphEdgeUpdateRequest'),
    ('put', '/operators/{operator_id}/visibility'): _request_body('OperatorVisibilityRequest'),
    ('post', '/models'): _request_body('ModelCreateRequest', required=False),
    ('put', '/models/{model_id}'): _request_body('ModelUpdateRequest', required=False),
    ('post', '/models/test'): _request_body('ModelTestRequest', required=False),
    ('post', '/models/{model_id}/test'):
        _request_body('SavedModelTestRequest', required=False),
    ('post', '/workflows'): _request_body('WorkflowCreateRequest'),
    ('patch', '/workflows/{workflow_id}'): _request_body('WorkflowUpdateRequest'),
    ('put', '/workflows/{workflow_id}/flow'): _request_body('WorkflowCanvasRequest'),
    ('post', '/workflows/{workflow_id}/validate'): _request_body('WorkflowCanvasRequest'),
    ('post', '/retrieval'): _request_body('RetrievalRequest'),
    ('post', '/agent-keys'): _request_body('AgentKeyCreateRequest'),
    ('patch', '/agent-keys/{key_prefix}'): _request_body('AgentKeyUpdateRequest'),
}

#: 这些操作不接收请求体（POST 但只是动作）。
_NO_REQUEST_BODY = frozenset({
    ('post', '/operators/{operator_id}/publish'),
    ('post', '/workflows/{workflow_id}/publication'),
    ('post', '/models/{model_id}/test'),
    ('post', '/auth/logout'),
})

#: 公开操作（不需要会话 Cookie）。登录前就要能访问；``/health`` 是探活。
_PUBLIC_OPERATIONS = frozenset({
    ('get', '/health'),
    ('get', '/auth/status'),
    ('post', '/auth/login'),
    ('post', '/auth/logout'),
})

#: 下载/导出类：成功内容是二进制流，不是 JSON。
_DOWNLOAD_PATHS = frozenset({
    '/knowledge-bases/{kbase_id}/documents/{document_id}/content',
    '/knowledge-bases/{kbase_id}/graph/export',
    '/operators/template',
    '/operators/{operator_id}/export',
    '/workflows/{workflow_id}/export',
})

_EXCLUDED_PATHS = frozenset({
    AGENT_MCP_PATH[len(RKB_PREFIX):] if AGENT_MCP_PATH.startswith(RKB_PREFIX) else AGENT_MCP_PATH,
    '/agent',  # Agent 有独立 OpenAPI（contracts/openapi/agent-api.yaml）
})
#: Agent 子应用是 mount，不会出现在主应用路由表；这里只做防御性排除。
_EXCLUDED_PREFIXES = (AGENT_PREFIX[len(RKB_PREFIX):] + '/',)

_PROBLEM_SCHEMA = {
    'type': 'object',
    'required': ['type', 'title', 'status', 'detail', 'code'],
    'properties': {
        'type': {'type': 'string', 'example': 'urn:ragstudio:problem:knowledge_base_not_found'},
        'title': {'type': 'string', 'example': 'Knowledge base not found'},
        'status': {'type': 'integer', 'example': 404},
        'detail': {'type': 'string', 'example': '知识库不存在'},
        'instance': {'type': 'string',
                      'example': '/api/co-knowledge/v1/knowledge-bases/nope'},
        'code': {'type': 'string', 'example': 'knowledge_base_not_found'},
        'errors': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'loc': {'type': 'array', 'items': {'type': 'string'}},
                    'type': {'type': 'string'},
                    'message': {'type': 'string'},
                },
            },
        },
    },
}

_DESCRIPTION = (
    'Knowledge Studio 对外 REST API。成功体是纯 JSON（单资源 / 数组 / '
    '{items,total,page,pageSize}）；错误是真实 HTTP 状态码 + RFC 9457 '
    '`application/problem+json`。\n\n'
    '协议端点（不属于本 REST 契约）：`POST /query` 的流式模式是标准 SSE、'
    '`GET /health` 是纯文本、`/mcp` 是 MCP Streamable HTTP（见 '
    '`contracts/openapi/agent-api.yaml` 之外另有 MCP 规范）。'
)


def normalize_object_schemas(schema: Any) -> Any:
    """Make ``dict[str, Any]`` schemas identical across Pydantic versions.

    Pydantic 2.11 emits ``additionalProperties: true`` for a free-form mapping,
    while 2.9 omits it.  The contract is generated on the newer version, so add
    the missing key (in Pydantic's key order) before comparing or serializing.
    Explicit models (``properties`` present) and constrained maps are untouched.
    """
    def walk(node):
        if isinstance(node, dict):
            if (node.get('type') == 'object' and 'properties' not in node
                    and 'additionalProperties' not in node):
                rebuilt = {'additionalProperties': True, **node}
                node.clear()
                node.update(rebuilt)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return schema


def _tags_for(path: str) -> list[str]:
    first = path.lstrip('/').split('/', 1)[0]
    return [first or 'root']


def _short_path(path: str) -> str:
    if path.startswith(RKB_PREFIX):
        return path[len(RKB_PREFIX):] or '/'
    return path


def _success_response(method: str, path: str, existing: dict[str, Any]) -> tuple[str, dict]:
    status = _SUCCESS_STATUS.get((method, path), 200)
    response = existing.get(str(status)) or existing.get('200') or {
        'description': 'Successful Response'}
    if status == 204:
        return '204', {'description': 'No Content'}
    response = dict(response)
    if path in _DOWNLOAD_PATHS:
        response['content'] = {
            'application/octet-stream': {
                'schema': {'type': 'string', 'format': 'binary'},
            },
        }
    elif path == '/query' and method == 'post':
        response['content'] = {
            'application/json': {'schema': {'type': 'object', 'additionalProperties': True}},
            'text/event-stream': {
                'schema': {'type': 'string'},
                'description': 'event: retrieval|token|done|error，data 为 JSON',
            },
        }
    return str(status), response


def build_rkb_openapi(app, *, version: str = API_VERSION) -> dict:
    """返回可直接写入/比对的全量契约（OpenAPI 3.0.3 结构）。"""

    routes = [
        route for route in app.routes
        if '{unknown_path:path}' not in getattr(route, 'path', '')
    ]
    schema = get_openapi(
        title='Knowledge Studio API',
        version=version,
        description=_DESCRIPTION,
        routes=routes,
    )
    # FastAPI 0.111 生成 3.1 结构；本契约沿用既有的 3.0.3 声明（未使用 3.1 特性）。
    schema['openapi'] = '3.0.3'
    schema['servers'] = [{'url': RKB_PREFIX}]

    paths: dict[str, Any] = {}
    for full_path, path_item in schema.get('paths', {}).items():
        short = _short_path(full_path)
        if not full_path.startswith(RKB_PREFIX):
            continue
        if short in _EXCLUDED_PATHS or short.startswith(_EXCLUDED_PREFIXES):
            continue
        operations: dict[str, Any] = {}
        for method, operation in path_item.items():
            if method not in {'get', 'post', 'put', 'patch', 'delete'}:
                continue
            operation = dict(operation)
            operation['tags'] = _tags_for(short)
            responses = operation.get('responses') or {}
            status, success = _success_response(method, short, responses)
            operation['responses'] = {
                status: success,
                '4XX': {'$ref': '#/components/responses/Problem'},
                '5XX': {'$ref': '#/components/responses/Problem'},
            }
            if (method, short) in _PUBLIC_OPERATIONS:
                operation['security'] = []
            explicit_body = _REQUEST_BODIES.get((method, short))
            if explicit_body is not None:
                operation['requestBody'] = explicit_body
            elif (method in {'post', 'put', 'patch'}
                    and 'requestBody' not in operation
                    and (method, short) not in _NO_REQUEST_BODY
                    and short not in _DOWNLOAD_PATHS):
                media = ('multipart/form-data'
                         if (method, short) in _MULTIPART_BODIES
                         else 'application/json')
                operation['requestBody'] = {
                    'required': False,
                    'content': {
                        media: {
                            'schema': {'type': 'object', 'additionalProperties': True},
                        },
                    },
                }
            operations[method] = operation
        if operations:
            paths[short] = operations

    schema['paths'] = dict(sorted(paths.items()))
    # 全局会话 Cookie；公开操作在上面的循环里用 `security: []` 覆盖。
    schema['security'] = [{'cookieAuth': []}]
    components = schema.setdefault('components', {})
    components.setdefault('securitySchemes', {})['cookieAuth'] = {
        'type': 'apiKey',
        'in': 'cookie',
        'name': 'ragstudio_session',
        'description': '本地账号登录后由服务端下发的 HttpOnly 会话 Cookie。',
    }
    components.setdefault('responses', {})['Problem'] = {
        'description': 'RFC 9457 问题体',
        'content': {'application/problem+json': {'schema': {'$ref': _PROBLEM_REF}}},
    }
    schemas = components.setdefault('schemas', {})
    schemas['Problem'] = _PROBLEM_SCHEMA
    # 手工解析端点的请求体（见 `_REQUEST_SCHEMAS` 的说明）。
    for name, request_schema in _REQUEST_SCHEMAS.items():
        schemas.setdefault(name, request_schema)
    # 这些是 FastAPI 自动加给默认 422 的结构；运行时已统一成 Problem，移除。
    for unused in ('HTTPValidationError', 'ValidationError'):
        schemas.pop(unused, None)
    # 显式 requestBody 取代了 FastAPI 推导的 `Body_*`，把不再被引用的清掉。
    referenced = set(_collect_refs(schema))
    for name in [name for name in schemas if name.startswith('Body_')]:
        if name not in referenced:
            del schemas[name]
    normalize_object_schemas(schema)
    _normalize_upload_schemas(schema)
    return schema


def _normalize_upload_schemas(node: Any) -> None:
    """FastAPI 0.162 用 ``contentMediaType`` 描述二进制上传；3.0.3 契约仍用 ``format: binary``。"""
    if isinstance(node, dict):
        if (node.get('type') == 'string'
                and node.get('contentMediaType') == 'application/octet-stream'):
            node.pop('contentMediaType')
            node['format'] = 'binary'
        for value in node.values():
            _normalize_upload_schemas(value)
    elif isinstance(node, list):
        for value in node:
            _normalize_upload_schemas(value)


def _collect_refs(node: Any) -> list[str]:
    """收集 schema 里所有本地 ``$ref`` 的组件名。"""
    found: list[str] = []
    if isinstance(node, dict):
        ref = node.get('$ref')
        if isinstance(ref, str) and ref.startswith('#/components/schemas/'):
            found.append(ref.rsplit('/', 1)[-1])
        for value in node.values():
            found.extend(_collect_refs(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_collect_refs(value))
    return found
