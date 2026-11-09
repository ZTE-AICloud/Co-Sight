"""Public operator plugin interface (v2).

Custom operators may import only the standard library and ``operator_api.*``.
The package is deliberately import-light: importing ``operator_api.llm`` does
not pull in the graph or storage modules.

Submodules:

* :mod:`operator_api.types` — result/chunk type definitions
* :mod:`operator_api.logging` — transaction-prefixed logger
* :mod:`operator_api.storage` — local file helpers
* :mod:`operator_api.llm` — model gateway calls
* :mod:`operator_api.graph` — graph validation and progress helpers
"""

__all__ = ['graph', 'llm', 'logging', 'storage', 'types']

#: Interface version embedded in plugin metadata; bump on incompatible changes.
INTERFACE_VERSION = '2.0'
