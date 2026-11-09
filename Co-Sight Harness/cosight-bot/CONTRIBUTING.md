# CONTRIBUTING —— CoSightBot PKM 开发约定

> 本目录（`cosightbot-pkm/`）是一个**自包含的 Cosight Harness 专家工作目录**：自有 `.gitignore` / `LICENSE` / `README.md` / `docs` / `runtime` / `.claude`。

## 一、目录自包含原则

- 运行数据一律落在工作目录下 `data/`（`COSIGHTBOT_HOME` 可覆盖），**严禁**写用户级目录（如 `~/`）。状态根的唯一来源是 `runtime/common/port_resolver.py::cosight_state_root()`，任何模块需要状态根都必须委托它。
- 技能脚本一律走 bootstrap：解析工作目录 → `sys.path` 注入 `runtime/` → 重入 `.venv`→ 加载 `data/.env` → preflight 自检（失败 `exit 3` + `{"hint": "please_run_install"}`）。
- 写范围限定 `data/` 与用户显式指定的路径；应答回填一律另存新文件，不覆盖原件。
- `data/.env` 存放本机 API key，已被 `.gitignore` 排除，**严禁**提交。

## 二、姊妹包共享文件的双份维护

本目录与姊妹专家包（cosightbot-soc）各自冗余携带同一份共享内核（`runtime/common/` 与 `runtime/watch_dog/file_watcher/` 的公共模块，约 24 个文件）——这是"目录即专家"自包含原则的有意取舍。**改动任一共享文件时必须双包同步修改，并分别跑通各自的 `scripts/smoke_test.py`**；只改一包会造成两份内核漂移，且漂移在各自冒烟中都不会报错（两包互不可见）。

## 三、行为契约（开发时必须保持）

- **零兜底**：检索不就绪、LLM 未配置、构建失败一律非零退出 + 结构化错误，严禁产出占位产物或目测结论；
- **检索不构建**：检索路径只读，文档增删（bind/add/delete）才触发增量构建，不做 watch 式实时监控；
- **判定程序化**：索引状态以脚本退出码/结构化输出为准；
- **环境变量**：新增配置项统一 `COSIGHTBOT_*` 前缀，并登记进 README 环境变量表；
- **进度/文件信息**：用 stdout `[progress]` 后端 + `common.index_api` 落盘，不得引入常驻进程/IPC 假设；
- 首装为显式动作：`python scripts/install.py`（幂等、非交互、无 hook）。

## 四、验证命令

```bash
# 首装 + preflight
python scripts/install.py

# PKM 链状态/索引对账
python .claude/skills/cosightbot-material/scripts/material_cli.py status

# 语法全量自检
python -m compileall -q runtime/
```

端到端验收用例见 `evaluation/pass-criteria.md`；回归冒烟 `scripts/smoke_test.py`。
