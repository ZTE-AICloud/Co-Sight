"""默认画布模板：建流时把四段算子与连线播种进草稿。

**为什么要有这个模块。** 建流之后要立刻按 `template` + 绑定知识库类型选一份模板
JSON，把内容写进 flow/node 表。少了这一步，`GET /flow` 就只能返回空画布，
前端 `initDefaultNode()` 兜底画出的是孤零零的「开始」「结束」两个点 ——
画布上没有算子、也没有连线。

支持**顺序检索 / 混合检索 / 条件检索**三个基础模板，以及 Blended 的两个图谱变体
（`Blended_graph` / `Blended_normal_graph`，服务端按绑定自动选择）。结构化库的
`Sequential_sql` 不支持；差异与取舍见本模块注释。

## 绑定知识库要回填四处

规则：

1. 普通检索器（向量 `knowledge_info_list[].knowledge_base_name` / 关键词 `kwargs.knowledge_base_name`）
   —— **只填普通知识库**；
2. 检索器 `kwargs.embedding` —— 绑定知识库的向量模型（普通库与图谱库共用同一个，
   它们的 `embeddingModel` 混用时同样是静默空命中，见下节）；
3. 图谱检索器 `KnowledgeGraphRetriever.kwargs.knowledge_base_name` —— **只填图谱知识库**。
   图谱库**只能**走这里：把图谱库填进普通检索器是另一场静默失败（见下节）；
4. 合成器 `kwargs.generator-config[].knowledge_base_name` —— **全部**库名（普通 + 图谱）。
   运行期 `SelectPromptQueryEngine` 按命中的库名选 per-KB 的 prompt/llm
   （`simple_summarizer.update_llm_and_prompt`）。**不回填这一处不会报错，只会静默退回
   默认 prompt** —— 画布上写好的提示词被无声忽略，是那种「看起来正常、其实没生效」的故障。

算子的 `kwargs.llm` 一律**留空**：运行期 `openai_llm` 在 llm 为空时回落到部署的
`GENERATION_MODEL`。把某个模型名写死进画布会让「换个部署就得改画布」，而部署默认模型
本来就是部署属性。

## 为什么这里对向量模型与库类型都**硬拒**而不是尽力而为

这两件事都必须抛业务异常（`MULTI_KBASE_EMBEDDING_MODEL` /
`KBASE_ASSET_FROM_UNKNOWN_SOURCE`），不能尽力而为。原因是这条链路的失败**不会响**：

* 检索只带一个 `embedding`，并用这一个模型对**所有**
  `knowledge_base_name` 做检索 —— 混选不同向量模型的库时，维度不匹配的库查不到；
* `embedding` 缺省时会落到旧默认值 `text2vec-base-chinese`，与库里实际写入的向量
  对不上 → 命中为空；
* 检索异常会被 `catch (Exception) → emptyList()` 吞掉，上层编排层拿到的
  就是「0 条切片」，照样合成出一段像模像样的回答。

也就是说：**播种一份向量模型对不上的画布，表现是「问答功能正常、就是答不准」**。
所以宁可建流时就失败，也不给这种画布。

图谱库的绑定走同一条严格度：Blended 会按绑定自动切到带 `KnowledgeGraphRetriever` 的
`Blended_graph` / `Blended_normal_graph` 变体；其余模板（Sequential / Conditional）里没有
图谱检索节点，绑了图谱库就在 `build_default_canvas` 报 `kbase.graph.unsupported`。
**不能退化成「把图谱库填进普通检索器」** —— 普通检索按 `data_<库名>` 查表，图谱库的
库名是 `graph_<uuid>`，查 `data_graph_<uuid>` 必然空命中，又是一次「HTTP 200、答得不对」。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, NamedTuple, Optional

from workflow.errors import FlowError
from workflow.messages import normalize_template_language
from infrastructure.logging.logutil import log

TEMPLATE_DIR = Path(__file__).resolve().parent / 'templates'
TEMPLATE_SUFFIX = '.json'

# 支持的模板。加模板前先确认**引擎与算子都 vendor 了**
# 三个模板对应三个编排引擎（`otherNodeConfigList` 里的 QUERY_ENGINE 伪节点）：
# Sequential → SequentialQueryEngine、Blended → BlendedQueryEngine、
# Conditional → ConditionalQueryEngine，三个引擎都要在编排层的
# `default_packages_info.query_engine_packages` 与 `canvas.ENGINE_OPERATORS` 里对得上。
#
# 「Blended + 图谱库」按规则自动选变体（见 `_resolve_template_variant`）：
#   * 只绑图谱库 → `Blended_graph`；
#   * 普通库 + 图谱库 → `Blended_normal_graph`；
#   * 只有普通库 → `Blended`。
# 前端仍然只暴露三个基础模板名，后缀选择是**服务端**的事，避免前端
# 因为「有没有图谱库」而改变模板下拉。
#
# `Sequential_sql` 不支持（结构化库走 SqlRetriever/SqlExecutor，依赖未提供的
# SQL 能力包），选它会显式报 template.unsupported。
TEMPLATE_SEQUENTIAL = 'Sequential'
TEMPLATE_BLENDED = 'Blended'
TEMPLATE_CONDITIONAL = 'Conditional'
SUPPORTED_TEMPLATES = (TEMPLATE_SEQUENTIAL, TEMPLATE_BLENDED, TEMPLATE_CONDITIONAL)

# Blended 的两个图谱变体（服务端内部名，不暴露给前端）
TEMPLATE_BLENDED_GRAPH = 'Blended_graph'
TEMPLATE_BLENDED_NORMAL_GRAPH = 'Blended_normal_graph'

# 画布里承载绑定关系的字段名
KEY_KWARGS = 'kwargs'
KEY_KNOWLEDGE_INFO_LIST = 'knowledge_info_list'
KEY_KNOWLEDGE_BASE_NAME = 'knowledge_base_name'
KEY_GENERATOR_CONFIG = 'generator-config'
KEY_EMBEDDING = 'embedding'
KEY_TABLE_NAME = 'tableName'
KEY_EMBEDDING_MODEL = 'embeddingModel'
KEY_TYPE = 'type'

# 四段算子在 node.variables 里的键名（本模块只回填其中两段，其余原样）
STAGE_RETRIEVER = 'retriever'
STAGE_RESPONSE_SYNTHESIZER = 'responsesynthesizer'

# 图谱库的判定：与前端（`CreateWorkflow.vue`）和本服务 `_to_vo` 同一条规则 —— 表名含 graph
GRAPH_TABLE_MARKER = 'graph'

# 图谱检索算子（前端 `retriever/Drawer.vue` 写进画布的 operator / package；
# 算子目录表里也是同一对值）
OPERATOR_KNOWLEDGE_GRAPH_RETRIEVER = 'KnowledgeGraphRetriever'
PACKAGE_KNOWLEDGE_GRAPH_RETRIEVER = 'core.rag.retriever.knowledgegraph_retriever'

# 结构化（数据库）知识库的类型标记（`kb_kbase.type`）
TYPE_STRUCT_KNOWLEDGE = 'struct_knowledge'


class Bindings(NamedTuple):
    """播种时要用到的绑定信息（已校验；构造它的函数负责失败即抛）。

    名单**拆成两份**：检索器只吃普通库 —— 图谱库进普通检索器会去查
    `data_graph_<uuid>` 表，必然空命中；图谱库只能进 `KnowledgeGraphRetriever`。
    合成器吃**全部**（图谱库也要有 per-KB prompt），见 `all_names`。
    """

    names: list[str]             # 普通（文档）知识库基名（去重、保序）
    graph_names: list[str]       # 图谱知识库基名（去重、保序）
    embedding: str               # 向量模型（已保证唯一且非空；普通库与图谱库共用）

    @property
    def all_names(self) -> list[str]:
        """全部库名（普通 + 图谱）：合成器的 per-KB 配置要吃全部。"""
        return self.names + self.graph_names


def is_supported(template: Optional[str]) -> bool:
    """模板是否可播种。空值**不算支持**（调用方据此显式报错，而不是悄悄给个默认）。"""
    return template in SUPPORTED_TEMPLATES


def load_template(template: str, language: str) -> dict:
    """按模板名 + 语言读模板 JSON（每次都是新解析出来的对象树，调用方可以随便改）。

    :raises FlowError: 模板缺失、不支持、文件缺失或不是合法 JSON
    """
    if not template:
        # 与「选了个不支持的模板」分开报：空值该说的是「请选一个」，
        # 而不是把空串插进「不支持模板 {0}」里（那会印出 "template  is not supported"）
        raise FlowError('template.not.null')
    if not is_supported(template):
        raise FlowError('template.unsupported', template)
    return _read_template(template, language)


def _read_template(template: str, language: str) -> dict:
    """读 ``{language}_{template}.json``（含服务端内部变体名）。

    与 :func:`load_template` 分开：公开入口只接受三个基础模板名；Blended 的图谱变体
    由 :func:`_resolve_template_variant` 选出后走这里，不对外暴露模板名。
    """
    # 模板变体语言走 language-option 的既有规则（zh 开头 → zh）—— 是「内容变体」，
    # 与错误文案语言（Accept-Language）是两条规则，别混（见 messages 里两个函数）
    language = normalize_template_language(language)
    path = TEMPLATE_DIR / f'{language}_{template}{TEMPLATE_SUFFIX}'
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError as e:
        # 随包发的数据文件不见了属于部署损坏：报业务错误 + 记原始异常，别让它冒成 500
        log.error('Workflow template %s is missing at %s: %s', template, path, e)
        raise FlowError('template.not.found', template) from e
    try:
        return json.loads(raw)
    except ValueError as e:
        log.error('Workflow template %s at %s is not valid JSON: %s', template, path, e)
        raise FlowError('template.not.found', template) from e


def build_default_canvas(template: str, language: str, bound_info: Any) -> tuple[list, list]:
    """建流播种：模板 → ``(nodeConfigDTOList, otherNodeConfigList)``。

    :param bound_info: 建流请求里的 ``boundInfo``（``{分组: [知识库选项, ...]}``）。
        校验失败一律抛 :class:`FlowError`，且**在任何写库动作之前**。
    """
    # 先判模板：它比「绑了什么库」更根本，两个都不对时报出更该先解决的那个。
    # 这里读的是**基础模板**（仅用于校验模板名与文件存在性）；Blended 绑图谱库时
    # 下面会换成 `Blended_graph` / `Blended_normal_graph` 变体。
    canvas = load_template(template, language)
    bindings = resolve_bindings(bound_info)
    template_name = _resolve_template_variant(template, bindings)
    if template_name != template:
        log.info('Template %s + bindings (normal=%d, graph=%d) -> variant %s',
                 template, len(bindings.names), len(bindings.graph_names), template_name)
        canvas = _read_template(template_name, language)

    node_config = _as_list(canvas.get('nodeConfigDTOList'))
    if not node_config:
        # 模板文件存在且是合法 JSON，但里面没有节点 —— 照播就会得到一份空画布，
        # 正是本模块要消灭的症状（前端退回「开始/结束」两个孤点）
        log.error('Workflow template %s is valid JSON but has no nodeConfigDTOList',
                  template_name)
        raise FlowError('template.not.found', template_name)
    other_node_config = _as_list(canvas.get('otherNodeConfigList'))

    if bindings.graph_names and not _has_graph_retriever(node_config):
        # 绑了图谱库、而模板里没有能接收它们的图谱检索节点 —— 图谱库**没有去处**。
        # Blended 的图谱变体会走 `_resolve_template_variant`，正常到不了这里；这条
        # 检查是兜底（例如未来新增了别的模板却忘了放图谱检索器）。显式失败而不是
        # 静默丢弃，更不能退化成填进普通检索器：那是去查不存在的 `data_graph_<uuid>`
        # 表，空命中但 HTTP 200。
        raise FlowError('kbase.graph.unsupported', ', '.join(bindings.graph_names))
    filled = _fill_knowledge_binding(node_config, bindings)
    log.info('Built default canvas from template %s (%s): %d nodes, %d bound kbase(s) '
             '(%d graph), embedding=%r, filled=%s',
             template_name, normalize_template_language(language), len(node_config),
             len(bindings.all_names), len(bindings.graph_names), bindings.embedding, filled)
    return copy.deepcopy(node_config), copy.deepcopy(other_node_config)


def _resolve_template_variant(template: str, bindings: Bindings) -> str:
    """``Blended`` + 图谱库 → ``_graph`` / ``_normal_graph`` 变体。

    后缀选择：

    ======================  ==========================
    绑定的库                模板
    ======================  ==========================
    只有图谱库              ``Blended_graph``
    普通库 + 图谱库          ``Blended_normal_graph``
    只有普通库              ``Blended``
    ======================  ==========================

    其它模板（Sequential / Conditional）不按库类型换文件。
    """
    if template != TEMPLATE_BLENDED:
        return template
    if bindings.graph_names and bindings.names:
        return TEMPLATE_BLENDED_NORMAL_GRAPH
    if bindings.graph_names:
        return TEMPLATE_BLENDED_GRAPH
    return template


def resolve_bindings(bound_info: Any) -> Bindings:
    """``boundInfo`` → 已校验的绑定信息；任何一种「检索必然失效」的组合都显式失败。

    图谱库**不在这里**拒 —— 它由 `build_default_canvas` 按「模板里有没有能接收它的图谱
    检索节点」决定；Blended 模板会先按绑定切换成带 `KnowledgeGraphRetriever` 的变体
    （见 :func:`_resolve_template_variant`）。

    :raises FlowError: 一个库都没绑、绑了结构化库、向量模型不唯一/取不到
    """
    # 只认带表名的条目：没有表名就没有检索目标，后面的判定都不该被它带偏
    bound = [item for item in _iter_bound_items(bound_info)
             if _text(item.get(KEY_TABLE_NAME))]
    names = _unique(item.get(KEY_TABLE_NAME) for item in bound)
    if not names:
        raise FlowError('canvas.no.kbase')

    struct_names = _unique(item.get(KEY_TABLE_NAME) for item in bound
                           if _text(item.get(KEY_TYPE)) == TYPE_STRUCT_KNOWLEDGE)
    if struct_names:
        # 结构化库要走 `Sequential_sql` 模板（SqlRetriever/SqlExecutor），
        # 那套算子依赖未提供的 SQL 能力包 —— 播成文档检索等于建一个永远查不到的流
        raise FlowError('kbase.struct.unsupported', ', '.join(struct_names))

    # 名单拆两份：图谱库（表名含 graph）只能进图谱检索器，其余进普通检索器
    graph_names = [name for name in names if GRAPH_TABLE_MARKER in name.lower()]
    normal_names = [name for name in names if GRAPH_TABLE_MARKER not in name.lower()]

    # 向量模型按**全部**绑定库看（图谱库也有 `embeddingModel`）：检索请求只带一个 model，
    # 图谱检索同样按它做向量召回，混用不同模型的库一样是「查不到但 HTTP 200」
    models = _unique(item.get(KEY_EMBEDDING_MODEL) for item in bound)
    if len(models) > 1:
        # 检索请求只带一个 model，混选不同向量模型的库会让其中一部分查不到，
        # 而检索异常会被吞成空列表 —— 表现是「答得不准」而不是报错
        raise FlowError('kbase.embedding.multi', ', '.join(models))
    if not models:
        # 请求不带 model 时会落到旧默认值 text2vec-base-chinese，
        # 与库里实际写入的向量对不上 → 命中为空。所以取不到模型必须报错，不能留空
        raise FlowError('kbase.embedding.unknown')

    return Bindings(names=normal_names, graph_names=graph_names, embedding=models[0])


def collect_kbase_names(bound_info: Any) -> list[str]:
    """``boundInfo`` → 全部知识库基名（去重、保序、丢弃空值）。

    ``tableName`` 就是**检索侧基名**（``doc_<uuid>`` / ``graph_<uuid>``），
    与画布下拉存进算子的是同一个值 —— 运行期由检索侧按基名解析物理表
    （见 `kbase_options` 模块头）。
    """
    return _unique(item.get(KEY_TABLE_NAME) for item in _iter_bound_items(bound_info))


def _fill_knowledge_binding(node_config: list, bindings: Bindings) -> dict:
    """把绑定关系写进检索器与合成器，返回「写了哪几处」供日志核对。"""
    filled = {'retriever': 0, 'synthesizer': 0}
    for node in node_config:
        for variables in _variable_copies(node):
            for operator in _as_list(variables.get(STAGE_RETRIEVER)):
                filled['retriever'] += _fill_retriever(operator, bindings)
            for operator in _as_list(variables.get(STAGE_RESPONSE_SYNTHESIZER)):
                filled['synthesizer'] += _fill_synthesizer(operator, bindings)
    return {key: value for key, value in filled.items() if value}


def _variable_copies(node: dict) -> list[dict]:
    """节点里承载算子的**两份**副本：``variables`` 与 ``data.variables``（两份都要填）。

    一份画布节点把算子存了两遍 —— 模板里这两份必须相同（`templates/*.json` 亦保持
    相同），但读写的角色不同：

    * ``variables`` 是**服务端**的那份：本模块播种写它，`translator`（编排层）、
      `canvas` 校验、发布快照都读它；
    * ``data.variables`` 是**画布**的那份：前端节点组件从它取值显示，`exportGraph()`
      保存时也按它回写顶层 ``variables``（`item.variables = targetItem.store.data?.data?.variables`）。

    只填一份的后果**不报错**：用户新建完工作流一切正常，但只要在画布上打开再点保存，
    播种结果就被模板里的空值覆盖 —— 检索器变回「没绑知识库」、向量模型变回模板里写死的
    旧值、后检索算子变回没有端点的 ExternalModelReranker。表现是「问答正常，就是答不准」。

    两份副本在解析出来的对象树里是**两个独立对象**（JSON 里各存一次），所以必须各填一份，
    不能靠引用共享。
    """
    copies = [node.get('variables')]
    data = node.get('data')
    if isinstance(data, dict):
        copies.append(data.get('variables'))
    return [copy for copy in copies if isinstance(copy, dict)]


def _is_graph_retriever(operator: dict) -> bool:
    """是不是图谱检索算子。operator 名与包名任一命中即算（两个值前端都会写）。"""
    return (operator.get('operator') == OPERATOR_KNOWLEDGE_GRAPH_RETRIEVER
            or operator.get('package') == PACKAGE_KNOWLEDGE_GRAPH_RETRIEVER)


def _can_receive_graph_names(operator: dict) -> bool:
    """该算子能否接收图谱库：图谱检索器 + ``kwargs.knowledge_base_name`` 是列表。

    两个条件缺一不可：「是图谱检索器」保证库名去的是图谱那条链路（普通检索器拿到图谱库
    只会去查不存在的 `data_graph_<uuid>`）；「字段是列表」保证 `_fill_retriever` 真的写得进去。
    两种缺失都是**静默**丢库，所以 `build_default_canvas` 用同一个判据决定「有没有去处」，
    判据与回填代码永远同源。
    """
    kwargs = operator.get(KEY_KWARGS)
    return (_is_graph_retriever(operator)
            and isinstance(kwargs, dict)
            and isinstance(kwargs.get(KEY_KNOWLEDGE_BASE_NAME), list))


def _has_graph_retriever(node_config: list) -> bool:
    """画布上有没有能接收图谱库的检索节点（扫描范围与 `_fill_knowledge_binding` 完全一致）。"""
    for node in node_config:
        for variables in _variable_copies(node):
            for operator in _as_list(variables.get(STAGE_RETRIEVER)):
                if _can_receive_graph_names(operator):
                    return True
    return False


def _fill_retriever(operator: dict, bindings: Bindings) -> int:
    """检索器：普通库进 ``knowledge_info_list[].knowledge_base_name``、图谱库进图谱检索器。

    KeywordRetriever 把库名放在 `kwargs` 顶层、VectorRetriever 放在 `knowledge_info_list` 里，
    两种形状都认。图谱检索器（``KnowledgeGraphRetriever``）的库名
    同样放在 ``kwargs.knowledge_base_name``，但**只收图谱库**：两边混着填都是静默空命中
    （图谱库进普通检索器 = 查不存在的 `data_graph_<uuid>` 表）。
    """
    kwargs = operator.get(KEY_KWARGS)
    if not isinstance(kwargs, dict):
        return 0
    # 向量模型**无条件**写进每个检索器算子（图谱检索器的同一字段由前端收集）。
    # 多写的那个键会被 KeywordRetriever / FusionRetriever 忽略
    # （它们的 `from_args` 只取自己认识的键），而漏写的代价是两个方向都静默：
    # 请求不带 model 时会落到旧默认值 `text2vec-base-chinese`，与库里写入的向量对不上
    # → 命中为空，但 HTTP 200、答案照出。宁可多写一个没人看的字段。
    kwargs[KEY_EMBEDDING] = bindings.embedding
    if _is_graph_retriever(operator):
        # 图谱库的唯一去处。字段不是列表形状时写不进去 —— `build_default_canvas` 已在
        # 「有没有能接收它们的节点」那一步拦下，这里返回 0 只是兜底。
        if not isinstance(kwargs.get(KEY_KNOWLEDGE_BASE_NAME), list):
            return 0
        kwargs[KEY_KNOWLEDGE_BASE_NAME] = list(bindings.graph_names)
        return 1
    targets = []
    if isinstance(kwargs.get(KEY_KNOWLEDGE_BASE_NAME), list):
        targets.append(kwargs)
    for info in _as_list(kwargs.get(KEY_KNOWLEDGE_INFO_LIST)):
        if isinstance(info.get(KEY_KNOWLEDGE_BASE_NAME), list):
            targets.append(info)
    for target in targets:
        target[KEY_KNOWLEDGE_BASE_NAME] = list(bindings.names)
    return len(targets)


def _fill_synthesizer(operator: dict, bindings: Bindings) -> int:
    """合成器：``kwargs.generator-config[].knowledge_base_name``（**全部**库）。

    「全部」含图谱库 —— 图谱库也要有 per-KB 的 prompt/llm，少填这一处不会报错，只会
    静默退回默认 prompt（见模块头第 4 点）。
    """
    kwargs = operator.get(KEY_KWARGS)
    if not isinstance(kwargs, dict):
        return 0
    count = 0
    for config in _as_list(kwargs.get(KEY_GENERATOR_CONFIG)):
        if isinstance(config.get(KEY_KNOWLEDGE_BASE_NAME), list):
            config[KEY_KNOWLEDGE_BASE_NAME] = list(bindings.all_names)
            count += 1
    return count


def _iter_bound_items(bound_info: Any):
    """``boundInfo`` 里的知识库选项（``{分组: [...]}`` 拍平，**跳过非 dict 元素**）。

    请求体是客户端给的，分组值里出现字符串/数字/None 是可能的；在这里把它过滤掉，
    好过让 ``item.get(...)`` 冒成 AttributeError（那会被顶层兜成 0001 服务器错误，
    调用方看不到「你传的 boundInfo 结构不对」）。
    """
    if not isinstance(bound_info, dict):
        return
    for value in bound_info.values():
        for item in _as_list(value):
            if isinstance(item, dict):
                yield item


def _unique(values) -> list[str]:
    """去重、保序、丢弃空值与非字符串。"""
    seen: dict[str, None] = {}
    for value in values:
        text = _text(value)
        if text:
            seen[text] = None
    return list(seen)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ''


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []
