import json
import logging
import os
import shutil

import ingestion

from ingestion.split.node_transfer import parse_md_to_nodes, rewrite_source_metadata
from ingestion.utility.manager import PGClientManager
from ingestion.utility.operator_zip_action import execute_operator_module

# 

# 图谱抽取进度回写仍复用这个单例（``ingestion/client/graph_process.py`` 与
# ``graph_extract_service`` 都从这里 import）。
pg_manager = PGClientManager()


def _service_root() -> str:
    """服务根（import 根）—— 系统算子包所在的位置。

    推导方式：**跟着 ``ingestion`` 包本身走**（其父目录就是算子入口所在的
    import 根 ``src/``）。刻意不用「本文件上溯 N 层」——那在目录结构变化时会静默
    指错；也不用 ``get_project_dir()``：它指向 ``ingestion/`` 包目录，而算子包在
    import 根。这里也刻意不依赖 ``parsing`` 这类通用包名，避免 site-packages 同名包抢占。
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(ingestion.__file__)))


def _operator_module_path(module_name: str) -> str:
    """系统算子入口的 ``main.py`` 路径。

    ``module_name`` 是**相对 import 根的路径**（如 ``operators/text_split``），
    由注册表的 ``operator_module`` 给出。**按文件路径解析** ——
    算子入口是被 ``execute_operator_module`` 用 ``spec_from_file_location`` 按路径
    加载的，**不要求是常规包**：算子目录可以没有 ``__init__.py``
    （只是目录 + ``main.py``）。不能用 ``importlib.util.find_spec``：
    它会因缺 ``__init__.py`` 返回 ``origin=None``（命名空间包）被判为不可导入，
    还凭空引入包结构要求。
    """
    module_path = os.path.join(_service_root(), module_name, "main.py")
    if not os.path.isfile(module_path):
        raise ValueError(f"System operator module not found: {module_path}")
    return module_path


def segment_file(file_path: str, category: int, split_preview: bool, **kwargs):
    logging.info(f"file_path: {file_path}, category: {category}, split_preview: {split_preview}, kwargs: {str(kwargs)}")
    operator = find_operator_by_id(category)
    if operator is None:
        raise ValueError("Unknown category for text segmentation")
    module_name = operator.get("operator_module")
    if not module_name:
        raise ValueError(f"Operator {category} has no operator_module")
    module_path = _operator_module_path(module_name)
    # -1 / -2 共用 operators/text_split，用注册表的 operator_function 区分入口。
    function_name = operator.get("operator_function") or "file_split"
    valid_args = ["emp_no", "kbase_id", "format"]
    operator_params = {k: v for k, v in kwargs.items() if k not in valid_args}
    doc_name = os.path.basename(file_path)
    source = os.path.splitext(doc_name)[1].lstrip('.')
    file_format = kwargs.get("format", "")
    flag = file_format == source
    if not flag and file_format:  # 当格式不匹配且 format_ 不为空时修改
        old_file_path = file_path
        file_path = os.path.splitext(file_path)[0] + '.' + file_format
        shutil.copy(old_file_path, file_path)
    operator_params["file_path"] = file_path
    docs = execute_operator_module(module_path, function_name, **operator_params)
    if not flag:
        docs = rewrite_source_metadata(docs, doc_name)
    nodes = parse_md_to_nodes(docs)
    if split_preview:
        return nodes
    if kwargs.get("kbase_id", '123') is None:
        raise ValueError("Unknown kbase_id")

    return nodes


def _load_operators() -> list:
    file_path = os.path.join(os.path.dirname(__file__), "operator_all.json")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_operator_by_id(search_id):
    """按 id 取完整注册项（含 ``operator_module`` / ``operator_function``）。"""
    for item in _load_operators():
        if item.get("id") == search_id:
            return item
    return None


# 支持两种调用签名：只取 operator_module
def find_operator_module_by_id(search_id):
    item = find_operator_by_id(search_id)
    return item.get("operator_module") if item else None


if __name__ == '__main__':
    file_path = '/tmp/large_document_part2.md'
    result = segment_file(file_path, -1, False, **{'maxWordCount': 512, 'overlap': 20})
    # result = segment_file(file_path, -2, False)
    for res in result:
        print(res)
