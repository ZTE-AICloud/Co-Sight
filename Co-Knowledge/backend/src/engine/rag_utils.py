"""算子/引擎实例化与若干工具函数。

`append_dialogue_kb` 保持原语义（多轮对话把上一轮的知识库并进来，带优先级递减），
`instance_operator` / `instance_query_engine` 只把「自定义算子包缓存」替换成
内置包映射（不支持自定义算子，见 `rag_operator_loader`）。
"""
import importlib
from typing import TYPE_CHECKING, Any, Dict, List

from engine.settings import Config
from engine.config_loader import default_packages_info, rag_operator_loader
from engine.logutil import logger

if TYPE_CHECKING:  # 只为注解：不在运行时引入 common.beans（保持原 import 图不变）
    from engine.common.beans.rag_request import RagRequest


def is_dev_mode() -> bool:
    """`Config['dev_mode'] == 'true'`（键定义在 src/config.py，由 DEV_MODE 驱动）。

    ⚠️ 本仓**没有调用点**。日志侧的 dev 行为由 `tools/log/logutil.py` 里**另一份**
    实现决定（那也是本仓唯一的活消费者）。
    """
    return Config.get('dev_mode') == 'true'


def _resolve_package(package: str, operator: str, builtin_map: dict) -> str:
    if operator in builtin_map:
        return builtin_map[operator]
    return rag_operator_loader.find_package_in_custom_operator_cache(package, operator)


def instance_operator(package: str, operator: str, params: Dict[str, Any]) -> Any:
    """按名字实例化一个算子（检索/后处理/合成等，取决于 `operator`）。

    :param package: 画布里的算子包名（内置算子经 `_resolve_package` 映射后不看它，
        只有自定义算子才会拿它去查缓存 —— 自定义算子直接报错）
    :param operator: 算子类名（如 'ExternalModelReranker'），同时在映射表里作为键
    :param params: 画布 `kwargs` 形状的配置 dict，**原样透传**给 `clazz.from_args`
    :return: 算子实例；具体类型由 `operator` 决定（故返回 Any，调用方按接口用）
    """
    resolved = _resolve_package(package, operator, default_packages_info.operator_packages)
    module = importlib.import_module(default_packages_info.to_importable(resolved))
    clazz = getattr(module, operator)
    return clazz.from_args(params)


def instance_query_engine(package: str, operator: str, params: Dict[str, Any]) -> Any:
    """按名字实例化查询引擎（同 `instance_operator`，但走 query_engine 映射表与 `as_query_engine`）。

    :param package: 画布里的包名（同上，内置路径下仅作留痕）
    :param operator: 引擎类名（Sequential/Blended/Conditional/MultiTransform/SelectPrompt）
    :param params: 画布 `kwargs` 形状的配置 dict，原样透传
    :return: 引擎实例（返回 Any，便于替换具体实现）
    """
    resolved = _resolve_package(package, operator, default_packages_info.query_engine_packages)
    module = importlib.import_module(default_packages_info.to_importable(resolved))
    clazz = getattr(module, operator)
    return clazz.as_query_engine(params)


def append_dialogue_kb(bases: List[Dict[str, Any]], user_request: 'RagRequest') -> None:
    """把本轮 conversation_id 追加进每个知识库配置的 `baseList`（多轮检索用）。

    ⚠️ **原地修改入参 `bases`**（调用方拿到的就是改过的对象，没有返回值）：
    `bases` 里每个 dict 若带 int 型 `priority`，会被减 1（下限 0，优先级递减），
    并就地 append `conversation_id`（去掉 '-'）。任一步骤抛异常都只记日志、静默返回 ——
    「尽力而为」语义。

    :param bases: 知识库配置列表，元素形如
        `{'priority': int, 'baseList': [<base 名>, ...], ...}`（原地改）
    :param user_request: 本轮请求，只读其中 `conversation_id`
    :return: None（结果体现在被改写的 `bases` 上）
    """
    try:
        logger.info(f"append base list (before): {bases}")
        conversation_id = user_request.conversation_id

        if not conversation_id:
            logger.warning("No conversation_id found in user_request.")
            return

        for base in bases:
            if 'priority' in base and isinstance(base['priority'], int):
                base['priority'] = max(0, base['priority'] - 1)  # 原地改：调用方可见
                origin_base_list = base['baseList']
                origin_base_list.append(conversation_id.replace("-", ""))  # 原地改：调用方可见
            else:
                logger.warning(f"base {base} priority type error")

        logger.info(f"append base list (after): {bases}")
    except Exception as e:
        logger.error(f"append conversation id error {e}")
        return
