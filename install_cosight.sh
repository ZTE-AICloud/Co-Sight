#!/bin/bash
###########################################
# Co-Sight 安装与配置脚本
# 用于单独安装/配置 Co-Sight（需先完成 OpenClaw 安装配置）
# 适用于: Linux / macOS / WSL2
###########################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; }
log_error()   { echo -e "${RED}[✗]${NC} $1"; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

# 引入 OpenClaw 脚本中的 start_openclaw_gateway（不执行 install_openclaw 的 main）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=install_openclaw.sh
source "$SCRIPT_DIR/install_openclaw.sh"

# 必须从 Co-Sight 项目根目录运行
check_cosight_dir() {
    if [ ! -f "requirements.txt" ]; then
        log_error "当前目录不是 Co-Sight 项目根目录"
        log_info "请 cd 到 Co-Sight 目录后执行: ./install_cosight.sh"
        exit 1
    fi
}

check_python() {
    log_info "检查 Python 环境..."
    if command_exists python3; then
        PYTHON_VERSION=$(python3 --version | awk '{print $2}')
        PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
        PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
        if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; then
            log_success "Python $PYTHON_VERSION (满足要求 ≥3.11)"
            PYTHON_CMD="python3"
            return 0
        fi
    fi
    log_error "未找到 Python ≥3.11，请先安装"
    exit 1
}

check_uv() {
    log_info "检查 uv 包管理器..."
    if command_exists uv; then
        log_success "uv 已安装"
        USE_UV=true
        return 0
    fi
    log_warning "未安装 uv"
    echo -n "是否安装 uv？(更快的依赖安装) [Y/n]: "
    read -r INSTALL_UV
    if [[ "$INSTALL_UV" =~ ^[Nn]$ ]]; then
        USE_UV=false
        return 0
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME:-/tmp}/.cargo/bin:$PATH"
    if command_exists uv; then
        log_success "uv 安装成功"
        USE_UV=true
    else
        USE_UV=false
    fi
}

install_cosight() {
    log_info "========================================="
    log_info "安装 Co-Sight 依赖"
    log_info "========================================="
    if [ "$USE_UV" = true ]; then
        uv venv
        uv pip install -r requirements.txt --prerelease=allow
    else
        $PYTHON_CMD -m pip install -r requirements.txt
    fi
    log_success "Co-Sight 依赖安装完成"
}

configure_cosight() {
    log_info "配置 Co-Sight..."
    # 从已配置的 OpenClaw 获取 Token（本脚本在 OpenClaw 配置完成后在新终端中运行）
    OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null || true)
    if [ -z "$OPENCLAW_TOKEN" ]; then
        log_warning "未获取到 OpenClaw Token，安装后可运行 ./sync_token.sh 同步"
    fi
    if [ -f ".env" ]; then
        log_warning "发现已存在的 .env"
        echo -n "是否备份并重新配置？[y/N]: "
        read -r RECONFIG
        if [[ ! "$RECONFIG" =~ ^[Yy]$ ]]; then return 0; fi
        BACKUP_NAME=".env.backup.$(date +%Y%m%d_%H%M%S)"
        cp .env "$BACKUP_NAME"
        log_info "已备份到: $BACKUP_NAME"
    fi
    [ ! -f ".env_template" ] && { log_error "找不到 .env_template"; exit 1; }
    cp .env_template .env
    log_success "已创建 .env"
    echo ""
    log_info "========================================="
    log_info "配置向导"
    log_info "========================================="
    echo ""
    log_info "1. LLM 配置（必填）"
    echo -n "请输入 LLM API Key: "
    read -r API_KEY
    echo -n "请输入 API Base URL (默认: https://api.deepseek.com/v1): "
    read -r API_BASE_URL
    API_BASE_URL=${API_BASE_URL:-https://api.deepseek.com/v1}
    echo -n "请输入 Model Name (默认: deepseek-chat): "
    read -r MODEL_NAME
    MODEL_NAME=${MODEL_NAME:-deepseek-chat}
    echo ""
    log_info "2. 搜索引擎配置（可选，按 Enter 跳过）"
    echo -n "Google API Key: "
    read -r GOOGLE_API_KEY
    SEARCH_ENGINE_ID=""
    [ -n "$GOOGLE_API_KEY" ] && { echo -n "Google Search Engine ID: "; read -r SEARCH_ENGINE_ID; }
    echo -n "Tavily API Key: "
    read -r TAVILY_API_KEY
    # sed -i：Linux 用 sed -i，macOS 用 sed -i ''
    if [[ "$OSTYPE" == "darwin"* ]]; then SED_I="sed -i ''"; else SED_I="sed -i"; fi
    $SED_I "s|^API_KEY=.*|API_KEY=$API_KEY|" .env
    $SED_I "s|^API_BASE_URL=.*|API_BASE_URL=$API_BASE_URL|" .env
    $SED_I "s|^MODEL_NAME=.*|MODEL_NAME=$MODEL_NAME|" .env
    $SED_I "s|^OPENCLAW_ENABLED=.*|OPENCLAW_ENABLED=True|" .env
    $SED_I "s|^OPENCLAW_AUTH_TOKEN=.*|OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN|" .env
    [ -n "$GOOGLE_API_KEY" ] && $SED_I "s|^GOOGLE_API_KEY=.*|GOOGLE_API_KEY=$GOOGLE_API_KEY|" .env
    [ -n "$SEARCH_ENGINE_ID" ] && $SED_I "s|^SEARCH_ENGINE_ID=.*|SEARCH_ENGINE_ID=$SEARCH_ENGINE_ID|" .env
    [ -n "$TAVILY_API_KEY" ] && $SED_I "s|^TAVILY_API_KEY=.*|TAVILY_API_KEY=$TAVILY_API_KEY|" .env
    log_success "Co-Sight 配置完成"
    echo ""
    echo "LLM API:        $API_BASE_URL"
    echo "Model:          $MODEL_NAME"
    echo "OpenClaw Token: ${OPENCLAW_TOKEN:-未设置}..."
    echo ""
}

create_startup_scripts() {
    log_info "创建启动脚本..."
    cat > start_cosight.sh << 'STARTCOSIGHT'
#!/bin/bash
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then uv run cosight_server/deep_research/main.py; else python3 cosight_server/deep_research/main.py; fi
STARTCOSIGHT
    chmod +x start_cosight.sh
    cat > stop_cosight.sh << 'STOPCOSIGHT'
#!/bin/bash
pkill -f "cosight_server/deep_research/main.py" 2>/dev/null || true
echo "Co-Sight 已停止"
STOPCOSIGHT
    chmod +x stop_cosight.sh
    # sync_token.sh / restart_all.sh / check_status.sh 使用与 install.sh 相同的逻辑，简化版内联
    if [ ! -f "sync_token.sh" ]; then
        cat > sync_token.sh << 'SYNCTOKEN'
#!/bin/bash
OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null)
[ -z "$OPENCLAW_TOKEN" ] && { echo "无法获取 OpenClaw Token"; exit 1; }
[ -f ".env" ] || { echo "找不到 .env"; exit 1; }
if grep -q "^OPENCLAW_AUTH_TOKEN=" .env; then sed -i "s|^OPENCLAW_AUTH_TOKEN=.*|OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN|" .env; else echo "OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN" >> .env; fi
echo "Token 已同步"
SYNCTOKEN
        chmod +x sync_token.sh
    fi
    if [ ! -f "restart_all.sh" ]; then
        cat > restart_all.sh << 'RESTARTALL'
#!/bin/bash
cd "$(dirname "$0")"
pkill -f "cosight_server/deep_research/main.py" 2>/dev/null || true
openclaw gateway restart 2>/dev/null || true
sleep 2
OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null)
[ -n "$OPENCLAW_TOKEN" ] && [ -f ".env" ] && (grep -q "^OPENCLAW_AUTH_TOKEN=" .env && sed -i "s|^OPENCLAW_AUTH_TOKEN=.*|OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN|" .env || echo "OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN" >> .env)
mkdir -p logs
nohup ./start_cosight.sh > logs/cosight_startup.log 2>&1 &
echo "重启完成。访问: http://localhost:7788/cosight/"
RESTARTALL
        chmod +x restart_all.sh
    fi
    if [ ! -f "check_status.sh" ]; then
        cat > check_status.sh << 'CHECKSTATUS'
#!/bin/bash
echo "OpenClaw:"; openclaw gateway status 2>/dev/null || true
echo "Co-Sight:"; pgrep -f "cosight_server/deep_research/main.py" >/dev/null && echo "运行中" || echo "未运行"
CHECKSTATUS
        chmod +x check_status.sh
    fi
    log_success "已创建 start_cosight.sh / stop_cosight.sh / sync_token.sh / restart_all.sh / check_status.sh"
}

create_uninstall_script() {
    [ -f "uninstall.sh" ] && return 0
    cat > uninstall.sh << 'UNINSTALL'
#!/bin/bash
read -p "确认卸载 Co-Sight 配置？[y/N]: " c
[[ ! "$c" =~ ^[Yy]$ ]] && exit 0
pkill -f "cosight_server/deep_research/main.py" 2>/dev/null || true
[ -f ".env" ] && cp .env ".env.backup.$(date +%Y%m%d_%H%M%S)"
rm -f .env start_cosight.sh stop_cosight.sh sync_token.sh restart_all.sh check_status.sh uninstall.sh
echo "Co-Sight 配置已清理"
UNINSTALL
    chmod +x uninstall.sh
    log_success "已创建 uninstall.sh"
}

start_services() {
    log_info "========================================="
    log_info "启动服务"
    log_info "========================================="
    OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null)
    if [ -n "$OPENCLAW_TOKEN" ] && [ -f ".env" ]; then
        if grep -q "^OPENCLAW_AUTH_TOKEN=" .env; then
            if [[ "$OSTYPE" == "darwin"* ]]; then SED_I="sed -i ''"; else SED_I="sed -i"; fi
            $SED_I "s|^OPENCLAW_AUTH_TOKEN=.*|OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN|" .env
        else
            echo "OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN" >> .env
        fi
        log_success "Token 已同步到 .env"
    fi
    mkdir -p logs
    log_info "启动 Co-Sight 服务..."
    echo -n "是否在后台启动？[Y/n]: "
    read -r START_BG
    if [[ "$START_BG" =~ ^[Nn]$ ]]; then
        log_info "前台运行（Ctrl+C 停止）。访问: http://localhost:7788/cosight/"
        [ "$USE_UV" = true ] && uv run cosight_server/deep_research/main.py || $PYTHON_CMD cosight_server/deep_research/main.py
    else
        nohup ./start_cosight.sh > logs/cosight_startup.log 2>&1 &
        sleep 3
        pgrep -f "cosight_server/deep_research/main.py" >/dev/null && log_success "Co-Sight 已在后台启动" || log_error "启动失败，请查看 logs/cosight_startup.log"
    fi
}

show_summary() {
    echo ""
    log_success "========================================="
    log_success "Co-Sight 安装配置完成"
    log_success "========================================="
    echo ""
    echo "访问: http://localhost:7788/cosight/"
    echo "启动: ./start_cosight.sh  停止: ./stop_cosight.sh  重启: ./restart_all.sh"
    echo "Token: ./sync_token.sh   状态: ./check_status.sh"
    echo ""
}

main() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════╗"
    echo "║   Co-Sight 安装与配置                 ║"
    echo "╚═══════════════════════════════════════╝"
    echo -e "${NC}"
    start_openclaw_gateway
    check_cosight_dir
    check_python
    check_uv
    install_cosight
    configure_cosight
    create_startup_scripts
    create_uninstall_script
    start_services
    show_summary
}

trap 'echo ""; log_warning "已中断"; exit 1' INT
main "$@"
