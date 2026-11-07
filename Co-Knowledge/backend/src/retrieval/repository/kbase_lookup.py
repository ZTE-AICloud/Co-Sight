"""Knowledge-base metadata lookup used to resolve ES index names.

The retrieval domain must not import ``knowledge_base`` (that would create a
package cycle).  The application assembly installs a provider that reads a
knowledge-base row by id; retrieval code calls :func:`get_kbase_row`.
"""

from __future__ import annotations

from typing import Callable, Optional

RowProvider = Callable[[str], Optional[dict]]

_provider: Optional[RowProvider] = None


def set_kbase_row_provider(provider: RowProvider) -> None:
    """Install the knowledge-base row lookup (called by the HTTP assembly)."""
    global _provider
    _provider = provider


def get_kbase_row(kbase_id: str) -> Optional[dict]:
    if _provider is None:
        raise RuntimeError(
            'knowledge-base row provider is not installed; call '
            'retrieval.repository.kbase_lookup.set_kbase_row_provider() '
            'during application assembly')
    return _provider(kbase_id)
