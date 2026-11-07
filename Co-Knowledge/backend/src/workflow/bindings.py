"""Which knowledge bases a workflow canvas is bound to.

Used by the knowledge-base deletion precheck.  Keeping this query in the
workflow domain lets ``knowledge_base`` depend on workflow through an injected
provider instead of importing ``workflow.repository`` directly.
"""

from __future__ import annotations

from typing import Optional

from workflow import canvas as canvas_util
from workflow.repository import create_default_store

#: Prefixes a canvas may use when naming a knowledge base.
KBASE_NAME_PREFIXES = ('doc_', 'graph_', 'data_')
#: Physical vector-table suffix (``doc_<uuid>_vector``).
KBASE_NAME_SUFFIXES = ('_vector',)
#: Draft/publish scope suffixes appended to canvas knowledge-base names.
SCOPE_SUFFIXES = ('|#|dev', '|#|publish')


def identity_token(bound_name: Optional[str]) -> Optional[str]:
    """Strip the scope suffix and any leading storage prefixes."""
    if bound_name is None or not str(bound_name).strip():
        return None
    name = str(bound_name).strip()
    for suffix in SCOPE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    stripped = True
    while stripped:
        stripped = False
        for prefix in KBASE_NAME_PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix):]
                stripped = True
    for suffix in KBASE_NAME_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name or None


def bound_kbase_names(emp_no: str) -> dict:
    """``allBoundKbase(empNo)``: workflow id -> bound knowledge-base names."""
    store = create_default_store()
    workflows = store.list_workflows_by_creator(emp_no)
    if not workflows:
        return {}
    ids = [record.workflow_id for record in workflows if record.workflow_id]
    result = {}
    for draft in store.list_drafts(ids):
        result[draft.workflow_id] = canvas_util.collect_bound_kbase_names(draft.node_config)
    return result


def workflow_ids_binding(kbase_id: str, pk_id: int, emp_no: str) -> list[str]:
    """Workflow ids whose canvas binds this knowledge base."""
    bound = bound_kbase_names(emp_no)
    pk_token = str(pk_id)
    hit = []
    for flow_id, names in (bound or {}).items():
        for bound_name in names or ():
            token = identity_token(bound_name)
            if token and token in (kbase_id, pk_token):
                hit.append(flow_id)
                break
    return hit
