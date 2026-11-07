"""kb_api 的存储层：直接读写业务库（默认 ``rag_studio``）。

与 ``workflow`` 的分工一致：store 只管 SQL 与行，不做 VO 组装、不装信封。
连接一律走 ``infrastructure.db.kb.connection()``（带完整事务语义、异常不吞）。

**这些 SQL 的语义被前端与编排层依赖**，包括那些看起来不一致的地方
（删除策略统一为物理删除，不再有 ``is_enabled`` 差异）。若「顺手统一」，
就会变成一次没人要的行为变更。
"""
