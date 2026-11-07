from engine.common import stage_timing
from engine.primitives.components.query_engine import TransformQueryEngine
from engine.primitives.interfaces import RagQueryEngine, RagQueryTransform
from engine.primitives.models import QueryBundle, Response as RESPONSE_TYPE


class MultiTransformQueryEngine(TransformQueryEngine):
    """
    多个query_transforms工作流查询引擎
    支持设置多个query_transform

    内部引用，不对外暴露
    """

    def __init__(self, query_engine: RagQueryEngine, query_transforms: [RagQueryTransform]):
        super().__init__(query_engine, query_transforms)
        self.query_transforms = query_transforms

    def _query(self, query_bundle: QueryBundle) -> RESPONSE_TYPE:
        # 只测改写/选择这一段；内层 query 的检索/重排由 RetrieverQueryEngine 自己记。
        # 列表为空时不记录，让「没有改写算子」和「改写跑了 0ms」在展示层可区分。
        if self.query_transforms:
            with stage_timing.measure(stage_timing.STAGE_UNDERSTANDING):
                for query_transform in self.query_transforms:
                    query_bundle = query_transform.run(
                        query_bundle, metadata=self._transform_metadata
                    )
        return self._query_engine.query(query_bundle)
