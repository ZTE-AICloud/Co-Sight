"""Stable graph-domain constants shared by repositories and callers."""

#: Graph table / base-name prefix (``ZaeConstant``).
GRAPH_TABLE_PREFIX = 'graph_'

#: 图行里的系统字段：展平/导出/写校验时剔除。PG 后端仍模拟这些字段以保持 API 契约。
GRAPH_ROW_SYSTEM_FIELDS = frozenset((
    '@rid', '@class', '@version', '@type', 'out', 'in',
    '@fieldTypes', '#labels',
))
