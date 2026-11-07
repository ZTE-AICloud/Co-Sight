"""知识库域。

知识库 CRUD、目录树、文件导入链、切片、检索、算子元数据与图谱资产，统一挂在
``/api/co-knowledge/v1`` 一个前缀下；响应是纯 JSON + RFC 9457 problem。

分层：router / service / repository / models。DB 访问走 ``db.py`` 的库名窄开关
（默认 ``rag_studio``）。
"""