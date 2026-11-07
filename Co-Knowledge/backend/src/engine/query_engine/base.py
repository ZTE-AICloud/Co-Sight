from abc import abstractmethod

from engine.primitives.interfaces import RagQueryEngine

from engine.context.rag_context import RagContext


class BaseRagQueryEngine(RagQueryEngine):

    @abstractmethod
    def as_query_engine(self, rag_context: RagContext) -> "RagQueryEngine":
        ...
