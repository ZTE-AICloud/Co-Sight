"""flow_api 的领域逻辑（store 无关，不依赖 FastAPI）。

按对外契约逐条对齐；
两处**有意为之**的语义写在各自方法上，免得后人「顺手优化」掉。
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Optional

from infrastructure.http.pagination import page as paginate
from workflow import canvas as canvas_util
from workflow import template_loader, validation
from workflow.errors import (
    CODE_SERVER_ERROR,
    FlowError,
    FlowStoreError,
    FlowValidationError,
)
from workflow.kbase_provider import GROUP_DEV, GROUP_RUNNING, GROUPS
from workflow.models import (
    DEFAULT_PAGE_SIZE,
    FIRST_VERSION,
    FLOW_TYPE_WORKFLOW,
    MAX_PAGE_SIZE,
    PUBLISH_TYPE_MODIFIED_AFTER_PUBLISH,
    PUBLISH_TYPE_PUBLISHED,
    PUBLISH_TYPE_UNPUBLISHED,
    FlowCanvasInput,
    FlowDraft,
    FlowPublished,
    WorkflowRecord,
)
from model.probe import ModelProbe
from workflow.runtime_config import RuntimeCapabilities, capabilities as capabilities_from_registry
from workflow.repository import FlowStore
from infrastructure.logging.logutil import log

# 工作流 ID 字符集：只允许字母/数字/下划线 —— 与上游 isValidateWorkflowId 一致。
# 不只是"规范"：ID 会进导出文件名、图数据库名与外部调用的 URL。
WORKFLOW_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_]*$')

MAX_WORKFLOW_ID_LENGTH = 128
MAX_NAME_LENGTH = 255
MAX_TEMPLATE_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1000


def _default_kbase_provider():
    """知识库下拉的默认数据源：直接读 ``rag_studio.kb_kbase``。"""
    # 延迟 import：kb_api 依赖 fastapi/pydantic，放在函数内可避免两个接口族在导入期互相牵连
    from knowledge_base.kbase_options import KbaseTableOptionProvider

    return KbaseTableOptionProvider()


class FlowService:
    """编排工作流的领域服务。"""

    def __init__(self, store: FlowStore, capabilities: Optional[RuntimeCapabilities] = None,
                 kbase_provider=None, model_probe=None, kbase_dimension_provider=None):
        self._store = store
        # 生产路径走 runtime_config.capabilities()（注册表优先、回落 .env），
        # 单测直接注入静态 capabilities —— 于是单测不碰数据库。
        #
        # ⚠️ ``_live_capabilities`` 决定**能力快照是活是死**，见 :meth:`_base_capabilities`：
        # 注入了静态 capabilities（单测）就永远用它；没注入（生产）则每次现取。
        self._live_capabilities = capabilities is None
        self._capabilities = capabilities if capabilities is not None else capabilities_from_registry()
        if kbase_provider is None:
            kbase_provider = _default_kbase_provider()
        self._kbase_provider = kbase_provider
        # 探测只在**生产装配路径**（capabilities 是自动装配的）自动创建：
        # 单测直接注入 capabilities，不该有网络行为。
        if model_probe is None and capabilities is None:
            model_probe = ModelProbe()
        self._model_probe = model_probe
        # 物理向量表维度：只在**生产装配路径**自动创建（同 ModelProbe 的理由 ——
        # 单测注入静态 capabilities，不该有 DB 行为）。None = 不做维度校验（无法判定）。
        if kbase_dimension_provider is None and capabilities is None:
            from knowledge_base import kbase_dimensions

            kbase_dimension_provider = kbase_dimensions.dimensions_for
        self._kbase_dimension_provider = kbase_dimension_provider

    def _base_capabilities(self) -> RuntimeCapabilities:
        """当前的能力快照。

        **生产路径必须现取，不能用构造时那份**：本服务是进程内单例
        （``workflow/runtime.py``），构造发生在启动时 —— 拿当时那份的话，
        「模型管理页加了一个模型，画布下拉要重启才看得到」，而这正是本功能要消灭的。
        现取不贵：解析层自己带进程内缓存，模型管理接口写完会让它失效。

        单测注入静态 capabilities 时**不现取** —— 那些用例不该碰数据库。
        """
        if not self._live_capabilities:
            return self._capabilities
        return capabilities_from_registry()

    def _capabilities_for_validation(self) -> RuntimeCapabilities:
        """校验用的能力快照 = 注入的静态能力 + 探测到的可用模型。

        ``RuntimeCapabilities`` 是 frozen 的，所以这里返回一个新实例而不是就地改。
        探测自带 TTL 缓存（:class:`~model.probe.ModelProbe`），
        同一次保存流程内不会重复打端点；探测失败时 ``available_models`` 留空，
        :func:`validation.find_unavailable_models` 会一律放行（无法判定 ≠ 不可用）。
        """
        capabilities = self._base_capabilities()
        if self._model_probe is None:
            return capabilities
        probed = self._model_probe.available()
        if not probed:
            return capabilities
        return replace(capabilities, available_models=frozenset(probed))

    def _kbase_dimensions(self, canvas: FlowCanvasInput) -> dict:
        """画布绑定的知识库 → 物理向量表维度（校验「模型维度 vs 库维度」）。

        读不到就返回空字典（= 无法判定，校验放行）—— 建库还没建成、库抖动、
        名字非法都不该把用户挡在发布之外。真正的一致性判据见
        :func:`validation.find_embedding_dimension_mismatches`。
        """
        provider = self._kbase_dimension_provider
        if provider is None:
            return {}
        names = canvas_util.collect_bound_kbase_names(canvas.node_config_dto_list)
        if not names:
            return {}
        try:
            return provider(names) or {}
        except Exception:                                          # noqa: BLE001
            log.warning('read kbase vector dimensions failed; skipping the dimension check',
                        exc_info=True)
            return {}

    # ------------------------------------------------------------------
    # 画布
    # ------------------------------------------------------------------

    def get_flow_config(self, app_id: str, language: str) -> dict:
        """读画布草稿；从未保存过 → 返回**空画布**（前端据此 ``initDefaultNode()``）。"""
        workflow = self._require_workflow(app_id)
        draft = self._store.get_draft(app_id)
        if draft is None:
            return _flow_config_vo(app_id, workflow.name, workflow.template,
                                   FIRST_VERSION, [], [], workflow.publish_type)
        return _flow_config_vo(app_id, workflow.name, workflow.template,
                               draft.version, draft.node_config, draft.other_node_config,
                               workflow.publish_type)

    def get_published_flow_config(self, app_id: str, language: str) -> dict:
        """读最新发布快照（编排运行时只读这份）；没有发布过 → 显式业务错误。

        运行时拿空配置只会跑出一堆空结果；这里直接失败，让「还没有发布」一眼可辨。
        """
        workflow = self._require_workflow(app_id)
        published = self._store.get_latest_published(app_id)
        if published is None:
            raise FlowError('published.not.exist', app_id)
        return _flow_config_vo(app_id, workflow.name, workflow.template,
                               published.version, published.node_config, published.other_node_config,
                               workflow.publish_type)

    def save_flow_config(self, app_id: str, payload: Any, user: str, language: str) -> int:
        """保存草稿。只做结构性校验 —— **故意不调**可运行性校验。

        前端的保存流程是「preCheck 返回 success=false → 弹二次确认 → 用户确认后照样保存」，
        这里要是硬拒，用户连一个半成品草稿都存不下来，画布等于不可用。
        真正拦「跑不起来」的是 :meth:`publish`。
        """
        self._require_workflow(app_id)
        canvas = FlowCanvasInput.from_payload(payload)
        validation.check_structure(canvas, language)

        existing = self._store.get_draft(app_id)
        if existing is None:
            self._store.insert_draft(FlowDraft(
                workflow_id=app_id,
                node_config=canvas.node_config_dto_list,
                other_node_config=canvas.other_node_config_list,
                version=FIRST_VERSION,
                flow_type=canvas.flow_type or FLOW_TYPE_WORKFLOW,
                created_by=user,
            ))
            log.info('Saved new canvas draft for workflow %s, %d nodes',
                     app_id, len(canvas.node_config_dto_list))
        else:
            # version 故意不设置：草稿保存不推进版本号（只有发布推进）
            self._store.update_draft(app_id, canvas.flow_type or existing.flow_type,
                                     canvas.node_config_dto_list, canvas.other_node_config_list)
            log.info('Overwrote canvas draft for workflow %s, %d nodes',
                     app_id, len(canvas.node_config_dto_list))
        # 已发布的工作流被改动 → 列表页要显示「有未发布的修改」
        self._mark_draft_changed(app_id)
        return existing.version if existing is not None else FIRST_VERSION

    def precheck(self, app_id: str, payload: Any, language: str) -> dict:
        """保存前校验：结构错误 → 业务异常；运行期风险 → ``{success:false, message}``。"""
        self._require_workflow(app_id)
        canvas = FlowCanvasInput.from_payload(payload)
        validation.check_structure(canvas, language)

        warnings = validation.precheck_warnings(
            canvas, language, self._capabilities_for_validation(),
            self._kbase_dimensions(canvas))
        if not warnings:
            return {'success': True, 'message': None}
        log.info('Canvas precheck for workflow %s produced %d warning(s): %s',
                 app_id, len(warnings), warnings)
        return {'success': False, 'message': validation.join_warnings(warnings)}

    def publish(self, app_id: str, user: str, language: str) -> int:
        """发布：硬门槛 + 写**不可变快照** + 版本号 +1 + ``publish_type=1``。

        与上游（zip + 资产中心）不同，这里是**本地快照**：运行时的编排层只读快照，
        草稿之后怎么改都不影响线上。整条链路**零资产中心调用**。
        """
        self._require_workflow(app_id)
        draft = self._store.get_draft(app_id)
        if draft is None:
            raise FlowError('draft.not.exist', app_id)

        # 发布是硬门槛：把 preCheck 里的「警告」全部升级为拒绝
        snapshot = FlowCanvasInput(
            flow_type=draft.flow_type,
            node_config_dto_list=draft.node_config,
            other_node_config_list=draft.other_node_config,
        )
        validation.check_structure(snapshot, language)
        validation.check_runnable(snapshot, self._capabilities_for_validation(),
                                  self._kbase_dimensions(snapshot))

        next_version = self._store.get_max_published_version(app_id) + 1
        try:
            self._store.insert_published(FlowPublished(
                workflow_id=app_id,
                version=next_version,
                node_config=draft.node_config,
                other_node_config=draft.other_node_config,
                created_by=user,
            ))
        except FlowStoreError as e:
            if e.kind == FlowStoreError.DUPLICATE:
                # 两个人同时点发布：都算出同一个 max+1，唯一键 (workflow_id, version) 拦下一个。
                # 给一个可读的业务错误，而不是让它冒成 500。
                log.warning('Concurrent publish of workflow %s collided on version %s', app_id, next_version)
                raise FlowError('publish.conflict', app_id) from e
            raise

        self._store.update_draft_version(app_id, next_version)
        self._store.update_publish_type(app_id, PUBLISH_TYPE_PUBLISHED)
        log.info('Published workflow %s version %s', app_id, next_version)
        return next_version

    def unpublish(self, app_id: str) -> None:
        """取消发布：只把 ``publish_type`` 置 0，保留历史快照。

        与发布不同，这里不删除任何 ``flow_release`` 行：快照是不可变历史，
        之后再次发布会基于草稿生成新版本。列表页与对话测试都以
        ``publish_type != 0`` 作为「可用」判据，置 0 即不再出现在对话工作流下拉里。
        """
        self._require_workflow(app_id)
        self._store.update_publish_type(app_id, PUBLISH_TYPE_UNPUBLISHED)
        log.info('Unpublished workflow %s', app_id)

    def export_flow_config(self, app_id: str, language: str) -> tuple[str, bytes]:
        """导出画布 JSON：(文件名, 内容)。失败必须显式报错（空文件会被当成「空画布」）。"""
        config = self.get_flow_config(app_id, language)
        try:
            content = json.dumps(config, ensure_ascii=False, indent=2).encode('utf-8')
        except (TypeError, ValueError) as e:
            log.error('Failed to export workflow %s: %s', app_id, e)
            raise FlowError('export.failed', app_id, code=CODE_SERVER_ERROR) from e
        return validation.safe_file_name(app_id), content

    def get_flow_knowledge_info(self, app_id: str, language: str) -> list[str]:
        """工作流绑定的知识库（**上游语义**：``List<String>``。

        取草画画布上的库名 → 去 scope 后缀 → 去 ``doc_`` / ``graph_`` / ``data_``
        前缀 → 去重，得到标识 token 列表。

        **注意这是与上游契约的一处有意差异**：上游返回的是
        ``{workFlowId,name,kbPkIds,graphKbPkIds}`` 的 map。本仓 web 的
        ``getFlowKnowledgeList``（``frontend/src/api/rag.js``）全仓无调用者（死代码），
        而 map 形态的信息已由 ``GET /workflow`` 的 ``kbPkIds``/``graphKbPkIds`` 覆盖，
        所以在无外部消费方的前提下按本仓契约返回列表。
        """
        self._require_workflow(app_id)
        draft = self._store.get_draft(app_id)
        if draft is None:
            return []
        names = canvas_util.collect_bound_kbase_names(draft.node_config)
        tokens: dict[str, None] = {}
        for name in names:
            token = canvas_util.strip_kb_prefix(name)
            if token:
                tokens[token] = None
        return list(tokens)

    def all_bound_kbase(self, user: Optional[str], language: str) -> dict[str, list[str]]:
        """全量绑定关系：工作流ID → 绑定的知识库名集合（已去 scope 后缀、去重）。

        与上游一致：只统计**当前用户**的工作流，且只列**有画布草稿**的工作流
        （上游的键来自流程配置表：没有画布的工作流根本不出现）。
        有草稿但一个库都没绑的以**空列表**出现 —— 调用方据此区分「查过、没绑定」与「没查」。
        """
        if not user or not user.strip():
            log.warning('allBoundKbase called without a user id; returning an empty binding map')
            return {}
        workflows = self._store.list_workflows_by_creator(user)
        if not workflows:
            return {}
        workflow_ids = [record.workflow_id for record in workflows if record.workflow_id]
        drafts = self._store.list_drafts(workflow_ids)
        result: dict[str, list[str]] = {}
        for draft in drafts:
            result[draft.workflow_id] = canvas_util.collect_bound_kbase_names(draft.node_config)
        return result

    # ------------------------------------------------------------------
    # 工作流元数据
    # ------------------------------------------------------------------

    def page_workflows(self, current_page: Any, page_size: Any, name: Optional[str],
                       publish_type: Any = None) -> dict:
        page = _positive_int(current_page, 1)
        size = min(_positive_int(page_size, DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE)
        records, total = self._store.list_workflows(
            name, page, size, _publish_type(publish_type))
        return paginate([self._to_vo(record) for record in records],
                        total, page, size)

    def get_workflow(self, app_id: str) -> dict:
        """单个工作流元数据（含 ``publishType`` 与绑定库），不存在时抛业务错误。"""
        return self._to_vo(self._require_workflow(app_id))

    def create_workflow(self, payload: Any, user: str, language: str) -> dict:
        """创建工作流（ID 字符集在入口拒绝；重名显式失败）。

        **建流即播种默认画布**。少了它，新画布打开后只有「开始」「结束」两个孤点
        （前端 ``initDefaultNode()`` 兜底），没有四段算子、也没有连线。

        模板与绑定知识库都在**写库之前**备好：没迁的模板（`Sequential_sql`）、一个知识库
        都没绑、`Sequential`/`Conditional` 绑了图谱库、绑了结构化库、混选不同向量模型的库，
        都在这里显式失败。Blended 绑图谱库不再失败：服务端自动切到带
        `KnowledgeGraphRetriever` 的 `Blended_graph` / `Blended_normal_graph` 变体。
        给一份「存得下、发不出」的画布比报错更糟 —— 用户要走很远才发现它跑不起来。
        """
        payload = payload if isinstance(payload, dict) else {}
        work_flow_id = _first_present(payload, 'workFlowId', 'workflowId', 'appId')
        _validate_workflow_id(work_flow_id, check_charset=True)
        name = _first_present(payload, 'name')
        _validate_name(name)
        template = _optional_str(payload.get('template'))
        _check_length(template, 'template.too.long', MAX_TEMPLATE_LENGTH)
        description = _optional_str(payload.get('description'))
        _check_length(description, 'description.too.long', MAX_DESCRIPTION_LENGTH)
        bound_info = payload.get('boundInfo') if isinstance(payload.get('boundInfo'), dict) else None

        if self._store.get_workflow(work_flow_id) is not None:
            # 显式失败：静默改成更新会让「新建」看起来成功了、实际覆盖了别人的工作流
            raise FlowError('workflow.exist', work_flow_id)

        node_config, other_node_config = template_loader.build_default_canvas(
            template, language, bound_info)

        record = WorkflowRecord(
            workflow_id=work_flow_id,
            name=name,
            description=description,
            template=template,
            knowledge_type=_optional_str(payload.get('knowledgeType')),
            publish_type=PUBLISH_TYPE_UNPUBLISHED,
            status=1,
            bound_info=bound_info,
            created_by=user,
        )
        draft = FlowDraft(
            workflow_id=work_flow_id,
            node_config=node_config,
            other_node_config=other_node_config,
            version=FIRST_VERSION,
            flow_type=FLOW_TYPE_WORKFLOW,
            created_by=user,
        )
        try:
            self._store.create_workflow_with_draft(record, draft)
        except FlowStoreError as e:
            if e.kind == FlowStoreError.DUPLICATE:
                # 并发下可能绕过上面的存在性检查，唯一约束是最后一道闸
                log.warning('Concurrent create of workflow %s rejected by unique constraint', work_flow_id)
                raise FlowError('workflow.exist', work_flow_id) from e
            raise

        created = self._store.get_workflow(work_flow_id)
        if created is None:
            # 写成功但读不到：单库下不该发生，但静默 NPE 会让调用方看到「服务器错误」，
            # 而不是「创建后回读失败」这个能查的事实
            log.error('Workflow %s reported saved but cannot be read back', work_flow_id)
            raise FlowError('workflow.not.exist', work_flow_id, code=CODE_SERVER_ERROR)
        log.info('Created rag workflow %s, name: %s, template: %s, %d default node(s)',
                 work_flow_id, name, template, len(node_config))
        return self._to_vo(created)

    def update_workflow(self, payload: Any, language: str) -> dict:
        """更新名称/模板/知识类型/描述（**不动** ``boundInfo``）。

        不含 boundInfo 是有意的：把它放进请求体会让「没传就等于清空」这种误伤成为可能。
        """
        payload = payload if isinstance(payload, dict) else {}
        work_flow_id = _first_present(payload, 'workFlowId', 'workflowId', 'appId')
        _validate_workflow_id(work_flow_id, check_charset=False)
        name = _first_present(payload, 'name')
        _validate_name(name)
        template = _optional_str(payload.get('template'))
        _check_length(template, 'template.too.long', MAX_TEMPLATE_LENGTH)
        description = _optional_str(payload.get('description'))
        _check_length(description, 'description.too.long', MAX_DESCRIPTION_LENGTH)

        self._require_workflow(work_flow_id)
        self._store.update_workflow(work_flow_id, name, template,
                                    _optional_str(payload.get('knowledgeType')), description)
        log.info('Updated rag workflow %s, name: %s', work_flow_id, name)
        updated = self._store.get_workflow(work_flow_id)
        return self._to_vo(updated)

    def delete_workflow(self, payload: Any, language: str) -> None:
        """删除工作流（草稿与发布快照在 store 层显式按序删，同一事务）。"""
        payload = payload if isinstance(payload, dict) else {}
        work_flow_id = _first_present(payload, 'workflowId', 'workFlowId', 'appId')
        if not work_flow_id or not str(work_flow_id).strip():
            raise FlowValidationError('workflowId.not.null')
        work_flow_id = str(work_flow_id)
        self._require_workflow(work_flow_id)
        self._store.delete_workflow(work_flow_id)
        log.info('Deleted rag workflow %s (draft and published snapshots removed)', work_flow_id)

    def list_llm_models(self) -> list[dict]:
        """画布「大模型」下拉：``[{modelValue, nameZh}]``（配置来源见 runtime_config）。

        走 :meth:`_base_capabilities`（生产路径**现取**）—— 模型管理页加一条，
        这里立刻看得到，不需要重启。
        """
        return [{'modelValue': value, 'nameZh': display}
                for value, display in self._base_capabilities().llm_models]

    def list_all_status_kbases(self, payload: Any) -> dict[str, list[dict]]:
        """知识库下拉：**原样透传数据源的分组**（``running`` = 已发布 7 / 发布后又改 8）。

        分组不在这里重算 —— 数据源的状态码有它自己的含义（``0`` = 待发布），
        拿 RKB 那套 ``kb_info.state``（``0`` = 处理成功）去套会把待发布的库显示成
        「运行中」。数据源与取舍见 ``kbase_provider`` 模块头。
        """
        payload = payload if isinstance(payload, dict) else {}
        embedding = _optional_str(payload.get('embedding'))
        grouped = self._kbase_provider.list_options(embedding) or {}
        result = {group: list(grouped.get(group) or []) for group in GROUPS}
        running, dev = len(result[GROUP_RUNNING]), len(result[GROUP_DEV])
        log.info('allStatusKbase: %d running, %d dev', running, dev)
        if running + dev == 0:
            # 空下拉本身合法（一个库都没建），但也是「按用户过滤后一个都不剩」的表现
            # —— 那种情况与「没建库」从界面上分不出来，至少让日志里看得见
            log.warning('allStatusKbase returned no kbase at all; check that the caller '
                        'identity actually owns kbases (embedding filter: %r)', embedding)
        return result

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _require_workflow(self, app_id: Any) -> WorkflowRecord:
        workflow_id = '' if app_id is None else str(app_id)
        record = self._store.get_workflow(workflow_id) if workflow_id else None
        if record is None:
            raise FlowError('workflow.not.exist', workflow_id)
        return record

    def _mark_draft_changed(self, app_id: str) -> None:
        """已发布的工作流被改动 → ``publish_type`` 1 → 2（从未发布过保持 0）。"""
        workflow = self._store.get_workflow(app_id)
        if workflow is None:
            return
        if workflow.publish_type == PUBLISH_TYPE_PUBLISHED:
            self._store.update_publish_type(app_id, PUBLISH_TYPE_MODIFIED_AFTER_PUBLISH)
            log.info('Workflow %s has unpublished modifications (publish_type 1 -> 2)', app_id)

    @staticmethod
    def _to_vo(record: WorkflowRecord) -> dict:
        """列表项 / 详情。字段名是**前端契约**（``workFlowId`` 大写 F），不能按习惯改。"""
        if record is None:
            # update 后回读不到属于存储异常；这里返回空壳会让前端拿到无名字的工作流，
            # 明确抛服务器错误更利于排查
            raise FlowError('server.error', code=CODE_SERVER_ERROR)
        all_bound = _flatten_bound_kbs(record.bound_info)
        # 与建流弹窗同一套判定：tableName 里含 graph 的算图谱知识库
        graph = [item for item in all_bound if 'graph' in str(item.get('tableName') or '')]
        normal = [item for item in all_bound if 'graph' not in str(item.get('tableName') or '')]
        return {
            'workFlowId': record.workflow_id,
            'name': record.name,
            'template': record.template,
            'knowledgeType': record.knowledge_type,
            'description': record.description,
            'publishType': record.publish_type,
            'status': record.status,
            'createdBy': record.created_by,
            'createdDate': record.created_at,
            'lastUpdatedDate': record.updated_at,
            'kbPkIds': normal,
            'graphKbPkIds': graph,
        }


def _flow_config_vo(app_id: str, name: Optional[str], template: Optional[str],
                    version: int, node_config: list, other_node_config: list,
                    publish_type: int = 0) -> dict:
    """画布 VO。

    ``publishType`` 是**附加字段**（0 未发布 / 1 已发布 / 2 发布后修改）：
    画布要据此提示「保存只改草稿，对话测试跑的是已发布快照」，否则用户会以为
    保存成功就等于线上生效。
    """
    return {
        'appId': app_id,
        'name': name,
        'version': version,
        'flowType': FLOW_TYPE_WORKFLOW,
        'template': template,
        'publishType': publish_type,
        'nodeConfigDTOList': node_config,
        'otherNodeConfigList': other_node_config,
    }


def _flatten_bound_kbs(bound_info: Any) -> list[dict]:
    """``{"running": [...], "dev": [...]}`` → 拍平成一个列表（回显用）。"""
    if not isinstance(bound_info, dict) or not bound_info:
        return []
    result: list[dict] = []
    for value in bound_info.values():
        if isinstance(value, list):
            result.extend(item for item in value if isinstance(item, dict))
    return result


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 1 else fallback


def _publish_type(value: Any) -> Optional[int]:
    """``publishType`` 查询参数 → 0/1/2；缺省返回 None（不筛）。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except (TypeError, ValueError):
        raise FlowValidationError('publishType.invalid')
    if parsed not in (PUBLISH_TYPE_UNPUBLISHED, PUBLISH_TYPE_PUBLISHED,
                      PUBLISH_TYPE_MODIFIED_AFTER_PUBLISH):
        raise FlowValidationError('publishType.invalid')
    return parsed


def _first_present(payload: dict, *keys: str) -> Optional[str]:
    """取第一个非空字段（前端契约里同一个 ID 有 ``workFlowId``/``workflowId``/``appId`` 三种写法）。"""
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _check_length(value: Optional[str], key: str, limit: int) -> None:
    if value is not None and len(value) > limit:
        raise FlowValidationError(key)


def _validate_workflow_id(work_flow_id: Optional[str], check_charset: bool) -> None:
    if not work_flow_id or not work_flow_id.strip():
        raise FlowValidationError('workflowId.not.null')
    if len(work_flow_id) > MAX_WORKFLOW_ID_LENGTH:
        raise FlowValidationError('workflowId.too.long')
    # 字符集只在创建路径校验：上游也只在校验创建路径，更新路径两边都未校验
    if check_charset and not WORKFLOW_ID_PATTERN.match(work_flow_id):
        raise FlowValidationError('workflowId.invalid')


def _validate_name(name: Optional[str]) -> None:
    if not name or not name.strip():
        raise FlowValidationError('name.not.null')
    if len(name) > MAX_NAME_LENGTH:
        raise FlowValidationError('name.too.long')
