# Operator plugin interface

Custom operators are Python scripts uploaded as a zip. The public import surface
is `operator_api`; anything else in the backend is an implementation detail and
may move without notice. Interface version: 2.0.

## Package format

```
<operator>/
├── config.json
└── <script>.py
```

`config.json` keeps the existing schema (`display_name`, `desc`, `visibleRange`,
`version`, `supportedFormat`, `defaultArgs`, `is_published`). `is_published` is
validated but stored as `1`, matching the historical behaviour.

## Entry points

| Module | Function | Return |
|---|---|---|
| `file_parse` | `file_parse(file_path, **args)` | cleaned text (`str`) |
| `text_split` | `file_split(file_path, **args)` | `list[operator_api.types.Chunk]` |
| `graph_extract` | `graph_extract(file_path, **kwargs)` | extraction result (JSON-serializable) |

The sandbox calls the function by name with keyword arguments built from
`defaultArgs`; signatures must match the template.

## Public modules

### `operator_api.types`

```python
from operator_api.types import Chunk, ChunkMetadata, OperatorResult
```

`Chunk` is `{"content": str, "metadata": {...}}`. `metadata` accepts
`source`, `content_expand`, and additional keys.

### `operator_api.logging`

```python
from operator_api.logging import TxPrefixedLogger
logger = TxPrefixedLogger(transaction_id)
logger.info('...')
```

### `operator_api.storage`

```python
from operator_api.storage import read_bytes, read_text, write_bytes, write_text
```

Operators receive local file paths; object-storage references are materialized
by the platform before the call.

### `operator_api.llm`

```python
from operator_api.llm import invoke_llm
```

`invoke_llm(messages, model='', temperature=0.1, ...)` calls the deployment's
model gateway. Endpoint configuration comes from `MODEL_GATEWAY_*` environment
variables, which the sandbox allowlists.

### `operator_api.graph`

```python
from operator_api.graph import GraphChecker, GraphProcess
```

`GraphChecker` validates entities/edges against a schema. `GraphProcess`
reports extraction progress for a knowledge base.

## Compatibility

The public import surface is `operator_api.*`. Backend packages such as
`client.*`, `utility.*`, `service.*` and `split.*` are not importable from an
operator; an operator importing them is rejected during upload with the problem
code `operator_plugin_incompatible` (HTTP 422), and the message asks the author
to download the current template and re-export.

The execution rules are unchanged otherwise: the child process is a `forkserver`
context with memory/time limits, a sanitized environment, a dangerous-code AST
scan, and JSON-only result transfer.

These settings control resource use and runtime behavior. Operators are treated
as trusted code; deployment-level isolation provides the security boundary, and
importing an operator requires an administrator.
