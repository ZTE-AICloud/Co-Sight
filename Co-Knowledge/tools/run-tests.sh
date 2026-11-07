#!/usr/bin/env bash
# =============================================================================
# run-tests.sh —— 全仓单测的单一入口：前端 vitest + 后端 pytest
#
# 为什么有这个脚本：
#   测试必须有人跑，否则用例会悄悄腐烂。这个脚本 + .github/workflows/ci.yml
#   保证任何一次改动，一条命令能跑完全部用例。
#
# 用法：
#   bash tools/run-tests.sh              # 前端 + 后端（默认）
#   bash tools/run-tests.sh --frontend   # 只跑前端（宿主直接跑，~15s）
#   bash tools/run-tests.sh --backend    # 只跑后端（容器内跑，~25s）
#   BACKEND_IMAGE=<image:tag> bash tools/run-tests.sh --backend  # 换镜像
#
# 退出码：0 = 全绿；1 = 有用例失败（含后端 skip > 0）；
#         2 = 环境/用法错误（参数不对、缺 npm/docker/镜像，测试可能没跑起来）。
#   两者都非 0，可直接被 CI 或 pre-push 钩子当门禁用；区分开是为了让人一眼知道
#   该去修测试还是先修环境。
#
# ⚠️ 前端需要 Node >= 22.22（jsdom 30.1.2 的 engines 是 ^22.22.2 || ^24.15.0 ||
#   >=26.0.0；vitest 5 自身要求 ^22.12.0）。Node 20 上跑不出结果：11 个 jsdom
#   组件用例会全部以 "Failed to start forks worker"（undici 8 需要 Node >= 22.19）
#   报错。frontend/Dockerfile 的 node:20-alpine 只用于 **npm run build**（构建不加载
#   jsdom），与本脚本无关。下面的前端分支有一条探针会先把这件事说清楚。
#
# 后端为什么在容器里跑：
#   * 宿主内核 4.19 没有 clone3（glibc 只认 ENOSYS 回退，而 docker 20.10 的
#     seccomp 剖面把 clone3 判成 EPERM，glibc 视为「被拒绝」不回退），所以任何
#     docker run 都要带 --security-opt seccomp=unconfined；
#   * 宿主也不一定装了被钉版本的 fastapi / tiktoken，容器里才是真环境。
#
# ⚠️ 后端必须挂**仓库根**到 /repo：
#   tests/test_flow_templates.py 用 parents[3] 找
#   backend/src/workflow/templates（跨服务契约），
#   **找不到时是 skip 而不是 fail** —— 只挂服务目录会静默少跑 10 条用例。
#   本脚本挂仓库根，并且断言 skip 数 == 0：静默少跑 = 失败。
# =============================================================================
set -uo pipefail   # 不用 -e：每一步的退出码都要自己判断、自己汇报

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

# 后端单测在 **RKB 镜像**里跑（依赖齐全）。
BACKEND_IMAGE="${BACKEND_IMAGE:-ragstudio/rag-knowledge-base:latest}"

RUN_FRONTEND=0
RUN_BACKEND=0

usage() {
    cat <<'EOF'
用法: bash tools/run-tests.sh [--frontend | --backend]

  不带参数        前端 + 后端全跑
  --frontend      只跑前端单测（frontend/ · vitest · 宿主直接跑）
  --backend       只跑后端单测（backend · pytest · 容器内跑）
  -h, --help      显示本帮助

环境变量:
  BACKEND_IMAGE        后端容器镜像，默认 ragstudio/rag-knowledge-base:latest

退出码: 0 = 全绿；1 = 有用例失败（含后端出现 skip）；2 = 用法/环境错误。
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --frontend) RUN_FRONTEND=1 ;;
        --backend)  RUN_BACKEND=1 ;;
        -h|--help)  usage; exit 0 ;;
        *)
            echo "run-tests: 未知参数: $1" >&2
            echo >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

# 默认两边都跑；显式给了任一侧就按给的跑
if [ "$RUN_FRONTEND" -eq 0 ] && [ "$RUN_BACKEND" -eq 0 ]; then
    RUN_FRONTEND=1
    RUN_BACKEND=1
fi

# --- 仓库根自检（脚本自己解析，不写死绝对路径）------------------------------
# 把「仓库根认错了」变成启动即报错，而不是跑出假绿。
if [ ! -f "$REPO_ROOT/frontend/package.json" ] || [ ! -d "$REPO_ROOT/backend/tests" ]; then
    echo "run-tests: 仓库根解析失败（$REPO_ROOT 下找不到 frontend/package.json 或 backend/tests）" >&2
    echo "run-tests: 本脚本假定位于 <repo>/tools/run-tests.sh" >&2
    exit 2
fi
if [ "$RUN_BACKEND" -eq 1 ] && [ ! -d "$REPO_ROOT/backend/src/workflow/templates" ]; then
    echo "run-tests: 缺 backend/src/workflow/templates ——" >&2
    echo "run-tests: 跨服务模板用例（test_flow_templates.py）会静默 skip，先补全工作树再跑后端。" >&2
    exit 2
fi

OUT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ragstudio-run-tests.XXXXXX")"
cleanup() { rm -rf "$OUT_DIR"; }
trap cleanup EXIT

# 两侧的结果汇总（首行是给最终结果表用的）
FRONTEND_SUMMARY="未运行"
BACKEND_SUMMARY="未运行"
FRONTEND_ELAPSED="-"
BACKEND_ELAPSED="-"
OVERALL=0

# 从一行文案里抠出 "N failed" / "N skipped" 的数字（抠不到 = 0）
count_from() {
    local n
    n="$(printf '%s' "$1" | grep -oE "[0-9]+ $2" | grep -oE '[0-9]+' | tail -1 || true)"
    printf '%s' "${n:-0}"
}

# ---------------------------------------------------------------------------
# 前端
# ---------------------------------------------------------------------------
run_frontend() {
    local log="$OUT_DIR/frontend.log"
    echo
    echo "=============================================================================="
    echo "[1/2] 前端单测（frontend/ · vitest）"
    echo "=============================================================================="

    if ! command -v npm >/dev/null 2>&1; then
        echo "!! 找不到 npm。前端测试需要 Node（>= 22.22，见文件头）。" >&2
        FRONTEND_SUMMARY="环境错误: 没有 npm"
        return 2
    fi
    if [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
        echo "!! 缺 frontend/node_modules —— 先在宿主装依赖：" >&2
        echo "     cd frontend && npm ci" >&2
        FRONTEND_SUMMARY="环境错误: 未安装前端依赖（frontend/node_modules 缺失）"
        return 2
    fi

    # 运行环境探针：jsdom（组件测试的环境）必须在当前 Node 上能加载。
    # 反例：Node 20 + lockfile 里的 jsdom 30 / undici 8 —— 直接 require 就抛
    # TypeError: webidl.util.markAsUncloneable is not a function，vitest 侧表现为
    # 11 条 "Failed to start forks worker" + "15 passed (15) / 11 errors"，
    # 退出码 1 但看不出是环境问题。这里先给一句人话，别让人去猜。
    if ! ( cd "$REPO_ROOT/frontend" && node -e "require('jsdom')" ) >/dev/null 2>&1; then
        echo "!! 当前 Node（$(node -v 2>/dev/null || echo 未知)）加载不了 jsdom —— 组件测试起不来。" >&2
        echo "!! lockfile 里的 jsdom 30 要求 Node ^22.22.2 || ^24.15.0 || >=26.0.0" >&2
        echo "!! （vitest 5 自身要求 ^22.12.0）。请换用 Node 22（>= 22.22.2）或更高版本。" >&2
        FRONTEND_SUMMARY="环境错误: Node $(node -v 2>/dev/null || echo 未知) 加载不了 jsdom（需要 >= 22.22.2）"
        return 2
    fi

    local start=$SECONDS
    ( cd "$REPO_ROOT/frontend" && NO_COLOR=1 npm run test:unit ) >"$log" 2>&1
    local rc=$?
    FRONTEND_ELAPSED="$((SECONDS - start))s"
    cat "$log"

    # vitest 摘要行形如： "      Tests  518 passed (518)"
    #                 或： "      Tests  1 failed | 517 passed (518)"
    local tests_line
    tests_line="$(grep -E '^[[:space:]]*Tests[[:space:]]+' "$log" | tail -1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' || true)"

    if [ -z "$tests_line" ]; then
        FRONTEND_SUMMARY="失败: 读不到 vitest 摘要行（rc=$rc，输出格式变了？）"
        return 1
    fi
    FRONTEND_SUMMARY="$tests_line"

    if [ "$rc" -ne 0 ]; then
        echo >&2
        echo "!! 前端有失败用例（npm 退出码 $rc）。FAIL 行如下：" >&2
        grep -E 'FAIL' "$log" | sed 's/^/   /' >&2 || true
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# 后端
# ---------------------------------------------------------------------------
run_backend() {
    local log="$OUT_DIR/backend.log"
    echo
    echo "=============================================================================="
    echo "[2/2] 后端单测（backend · pytest · 容器内）"
    echo "=============================================================================="

    if ! command -v docker >/dev/null 2>&1; then
        echo "!! 找不到 docker —— 后端测试在 $BACKEND_IMAGE 里跑（宿主未必装了钉版本的依赖）。" >&2
        BACKEND_SUMMARY="环境错误: 没有 docker"
        return 2
    fi

    if ! docker image inspect "$BACKEND_IMAGE" >/dev/null 2>&1; then
        cat >&2 <<EOF
!! 本地没有镜像 $BACKEND_IMAGE —— 后端测试在容器里跑，需要先构建：

     docker build -t $BACKEND_IMAGE backend

   本机（内核 4.19 无 clone3）若 docker build 在 RUN pip install 处报
   "can't start new thread"，那是 seccomp 判 clone3=EPERM 的老问题，
   改用 BuildKit 路径（背景见 tools/build-via-buildkit.sh 文件头）：

     tools/build-via-buildkit.sh backend $BACKEND_IMAGE
EOF
        BACKEND_SUMMARY="环境错误: 缺镜像 $BACKEND_IMAGE（先构建，见上方提示）"
        return 2
    fi

    local start=$SECONDS
    # 挂载给**仓库根**（跨服务用例要读 RKB 的算子清单）；工作目录是 RKB 服务根，
    # 它的 pytest.ini 里 pythonpath=src（唯一的 import 根）。
    # ⚠️ 容器以 root 跑，往挂载目录里写的东西在宿主上是 root 属主（实测过）。
    #    所以两处都断掉落盘：PYTHONDONTWRITEBYTECODE=1（不写 __pycache__/*.pyc）、
    #    pytest -p no:cacheprovider（不写 .pytest_cache）——别让跑测试污染工作树。
    docker run --rm --security-opt seccomp=unconfined \
        -v "$REPO_ROOT":/repo \
        -w /repo/backend \
        -e PYTHONPATH=/repo/backend/src \
        -e PYTHONDONTWRITEBYTECODE=1 \
        "$BACKEND_IMAGE" sh -c '
            # 不写路径：范围由服务根 pytest.ini 的 testpaths 决定
            # 架构重构后所有后端用例都收在 backend/tests 下（含 engine/ 子目录）。
            if ! python -m pytest --version >/dev/null 2>&1; then
                pip install -q pytest==9.1.1 || { echo "__RUN_TESTS_PYTEST_INSTALL_FAILED__" >&2; exit 97; }
            fi
            python -m pytest -q -rs -p no:cacheprovider
        ' >"$log" 2>&1
    local rc=$?
    BACKEND_ELAPSED="$((SECONDS - start))s"
    cat "$log"

    case "$rc" in
        97)
            echo "!! 容器内既没有 pytest、pip install 又失败了（网络/镜像源问题）。" >&2
            BACKEND_SUMMARY="环境错误: 容器内装不上 pytest（rc=97）"
            return 2
            ;;
        125|126|127)
            echo "!! docker run 本身没跑起来（rc=$rc：daemon 未运行 / 权限 / 镜像入口问题）。" >&2
            BACKEND_SUMMARY="环境错误: docker run 起不来（rc=$rc）"
            return 2
            ;;
        5)
            echo "!! pytest 没收集到任何用例（rc=5）—— 工作目录或 tests 路径不对？" >&2
            BACKEND_SUMMARY="失败: pytest 没收集到用例（rc=5）"
            return 1
            ;;
    esac

    # pytest -q 的摘要行形如： "174 passed, 6 warnings in 7.30s"
    #             有失败时被 "=====" 包着："===== 1 failed, 173 passed in 7.30s ====="
    local summary_line
    summary_line="$(grep -E '[0-9]+ (passed|failed|error|errors|skipped)' "$log" | tail -1 \
        | tr -d '=' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' || true)"
    if [ -z "$summary_line" ]; then
        BACKEND_SUMMARY="失败: 读不到 pytest 摘要行（rc=$rc，输出格式变了？）"
        return 1
    fi
    BACKEND_SUMMARY="$summary_line"

    local skipped_n
    skipped_n="$(count_from "$summary_line" skipped)"

    # ★ skip 断言：跨服务用例被静默跳过 = 失败（本任务最容易坏的一环）。
    if [ "$skipped_n" -ne 0 ]; then
        echo >&2
        echo "!! 后端出现 $skipped_n 条 skip —— 静默少跑，按失败处理。原因：" >&2
        grep -E '^SKIPPED' "$log" | sed 's/^/   /' >&2 || true
        echo "   ↑ test_flow_templates.py 找不到 backend/.../workflow/templates" >&2
        echo "     时会 skip 而不是 fail。本脚本挂了仓库根；改挂载前先想清楚这一点。" >&2
        BACKEND_SUMMARY="失败: $summary_line（skip 必须为 0）"
        return 1
    fi

    if [ "$rc" -ne 0 ]; then
        echo "!! 后端有用例失败（pytest 退出码 $rc）。" >&2
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
echo "仓库根: $REPO_ROOT"
if [ "$RUN_FRONTEND" -eq 1 ] && [ "$RUN_BACKEND" -eq 1 ]; then
    echo "模式:   前端 + 后端"
elif [ "$RUN_FRONTEND" -eq 1 ]; then
    echo "模式:   仅前端"
else
    echo "模式:   仅后端"
fi

FRONTEND_STATUS="未运行"
BACKEND_STATUS="未运行"

if [ "$RUN_FRONTEND" -eq 1 ]; then
    run_frontend
    case $? in
        0) FRONTEND_STATUS="PASS" ;;
        2) FRONTEND_STATUS="ERROR" ;;
        *) FRONTEND_STATUS="FAIL" ;;
    esac
    [ "$FRONTEND_STATUS" = "PASS" ] || OVERALL=1
fi

if [ "$RUN_BACKEND" -eq 1 ]; then
    run_backend
    case $? in
        0) BACKEND_STATUS="PASS" ;;
        2) BACKEND_STATUS="ERROR" ;;
        *) BACKEND_STATUS="FAIL" ;;
    esac
    [ "$BACKEND_STATUS" = "PASS" ] || OVERALL=1
fi

echo
echo "=============================================================================="
echo "结果汇总"
echo "=============================================================================="
if [ "$RUN_FRONTEND" -eq 1 ]; then
    printf '  前端  %-5s  %s   [%s]\n' "$FRONTEND_STATUS" "$FRONTEND_SUMMARY" "$FRONTEND_ELAPSED"
fi
if [ "$RUN_BACKEND" -eq 1 ]; then
    printf '  后端  %-5s  %s   [%s]\n' "$BACKEND_STATUS" "$BACKEND_SUMMARY" "$BACKEND_ELAPSED"
fi
echo "------------------------------------------------------------------------------"
if [ "$OVERALL" -eq 0 ]; then
    echo "  => 全绿"
    exit 0
fi
# 环境/用法错误优先于用例失败：ERROR 意味着测试可能根本没跑起来。
if [ "$FRONTEND_STATUS" = "ERROR" ] || [ "$BACKEND_STATUS" = "ERROR" ]; then
    echo "  => 环境/用法错误（测试可能没跑起来），脚本退出码 2"
    exit 2
fi
echo "  => 有用例失败（见上方日志），脚本退出码 1"
exit 1
