"""内置算子清单必须与运行时真实存在的类一一对应。

这条链上最容易出的错是「目录（operator 表 / default_packages_info）
里写了一个算子名，运行时却 import 不到」—— 表现为画布上能选、一跑就 500。
所以这里用反射把清单逐条验一遍。
"""
import importlib

from engine.config_loader import default_packages_info


def test_every_operator_in_catalog_can_be_imported_by_name():
    missing = []
    for operator, package in default_packages_info.operator_packages.items():
        # 登记值仍是 `core.rag.*`（画布契约），导入前翻译一次
        module = importlib.import_module(default_packages_info.to_importable(package))
        if not hasattr(module, operator):
            missing.append(f'{operator} ({package})')
    assert missing == [], f'清单里有运行时导不出来的算子：{missing}'


def test_query_engine_catalog_matches_runtime():
    for engine, package in default_packages_info.query_engine_packages.items():
        module = importlib.import_module(default_packages_info.to_importable(package))
        assert hasattr(module, engine), f'{package} 里没有 {engine}'


# 运行时清单与画布校验清单必须一致；两者的对照在
#     tests/test_operator_catalog_live_pair.py（在 RKB 侧，因为要 import compat）
def test_catalog_contains_the_knowledge_graph_retriever():
    """与文件无关的硬断言：知识图谱检索算子必须在运行时清单里，且清单规模不变。

    清单规模是锚点 —— 增删算子时两处清单必须同批改，只动一边会在上一条或本条上红。
    """
    packages = list(default_packages_info.operator_packages.values())
    assert 'core.rag.retriever.knowledgegraph_retriever' in packages, \
        f'运行时清单里没有知识图谱检索算子：{packages}'
    # 唯一包数是 9。
    assert len(set(packages)) == 9, (
        f'内置算子包数量为 {len(set(packages))}，与期望不一致（增删算子时同步运行时的 '
        f'RUNNABLE_OPERATOR_PACKAGES 与本条期望值）：{packages}')
