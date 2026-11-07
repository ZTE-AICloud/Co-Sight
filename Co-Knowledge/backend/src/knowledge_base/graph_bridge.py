"""Graph lifecycle hooks used by knowledge-base cleanup paths.

The knowledge-base domain must purge graph artifacts when documents or graph
knowledge bases are deleted, but it must not import the graph domain directly
(that would create a package cycle).  The application assembly installs the
graph implementation once via :func:`install`; callers use the hook names
directly (``graph_bridge.delete_graph_database`` etc.).
"""

from __future__ import annotations

from types import ModuleType
from typing import Optional

_implementation: Optional[ModuleType] = None


def install(implementation: ModuleType) -> None:
    """Install the graph lifecycle module (called by the HTTP assembly)."""
    global _implementation
    _implementation = implementation


def _require() -> ModuleType:
    if _implementation is None:
        raise RuntimeError(
            'graph lifecycle is not installed; call graph_bridge.install() '
            'during application assembly')
    return _implementation


def __getattr__(name: str):
    return getattr(_require(), name)
