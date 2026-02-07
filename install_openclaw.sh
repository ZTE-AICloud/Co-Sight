#!/bin/bash
###########################################
# OpenClaw 安装与配置脚本
# 用于单独安装/配置 OpenClaw Gateway
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

detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then OS="linux"; log_info "检测到操作系统: Linux"
    elif [[ "$OSTYPE" == "darwin"* ]]; then OS="macos"; log_info "检测到操作系统: macOS"
    else log_error "不支持的操作系统: $OSTYPE"; exit 1; fi
}

check_nodejs() {
    log_info "检查 Node.js 环境..."
    if command_exists node; then
        NODE_VERSION=$(node --version | cut -d'v' -f2)
        NODE_MAJOR=$(echo $NODE_VERSION | cut -d. -f1)
        if [ "$NODE_MAJOR" -ge 22 ]; then
            log_success "Node.js v$NODE_VERSION (满足要求 ≥22)"
            return 0
        fi
    fi
    log_warning "未找到合适的 Node.js 版本，将尝试安装"
    return 1
}

install_nodejs() {
    log_info "开始安装 Node.js 22..."
    if [ ! -d "$HOME/.nvm" ]; then
        log_info "安装 nvm..."
        curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
        export NVM_DIR="$HOME/.nvm"
        [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    fi
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    nvm install 22
    nvm use 22
    log_success "Node.js 安装完成"
}

check_cmake() {
    if command_exists cmake; then
        CMAKE_VERSION=$(cmake --version | head -1 | awk '{print $3}')
        CMAKE_MAJOR=$(echo $CMAKE_VERSION | cut -d. -f1)
        CMAKE_MINOR=$(echo $CMAKE_VERSION | cut -d. -f2)
        if [ "$CMAKE_MAJOR" -gt 3 ] || ([ "$CMAKE_MAJOR" -eq 3 ] && [ "$CMAKE_MINOR" -ge 19 ]); then
            log_success "CMake 版本满足要求 (≥3.19)"
            return 0
        fi
        export NODE_LLAMA_CPP_SKIP_BUILD=true
        SKIP_LOCAL_LLM=true
        return 1
    fi
    export NODE_LLAMA_CPP_SKIP_BUILD=true
    SKIP_LOCAL_LLM=true
    return 1
}

configure_npm_registry() {
    log_info "检查 npm 网络连接..."
    if curl -s --connect-timeout 3 --max-time 5 https://registry.npmjs.org/ >/dev/null 2>&1; then
        log_success "npm 官方源可访问"
        return 0
    fi
    log_warning "npm 官方源无法访问"
    if curl -s --connect-timeout 3 --max-time 5 https://registry.npmmirror.com/ >/dev/null 2>&1; then
        echo -n "是否切换到淘宝镜像源？[Y/n]: "
        read -r USE_MIRROR
        if [[ ! "$USE_MIRROR" =~ ^[Nn]$ ]]; then
            npm config set registry https://registry.npmmirror.com && log_success "镜像源配置成功" && return 0
        fi
    fi
    return 1
}

install_openclaw() {
    log_info "========================================="
    log_info "安装 OpenClaw Gateway"
    log_info "========================================="
    if command_exists openclaw; then
        log_success "OpenClaw 已安装: $(openclaw --version 2>/dev/null | head -1 || echo '未知')"
        echo -n "是否重新安装？[y/N]: "
        read -r REINSTALL
        if [[ ! "$REINSTALL" =~ ^[Yy]$ ]]; then return 0; fi
    fi
    check_cmake || true
    configure_npm_registry || true
    NPM_INSTALL_OPTS=""
    [ "$SKIP_LOCAL_LLM" = true ] && NPM_INSTALL_OPTS="--omit=optional --ignore-scripts"
    log_info "开始安装 OpenClaw..."
    if curl -fsSL https://openclaw.ai/install.sh | bash; then
        log_success "OpenClaw 安装成功"
    else
        log_warning "官方安装脚本失败，尝试 npm 安装..."
        npm install -g openclaw@latest $NPM_INSTALL_OPTS || { log_error "npm 安装失败"; exit 1; }
    fi
    if ! command_exists openclaw; then
        log_error "OpenClaw 安装验证失败"
        exit 1
    fi
    log_success "OpenClaw 安装验证成功"
}

configure_openclaw() {
    log_info "配置 OpenClaw Gateway..."
    if openclaw config get gateway.auth.token >/dev/null 2>&1; then
        log_success "OpenClaw 已配置"
        echo -n "是否重新运行配置向导？[y/N]: "
        read -r RECONFIG
        if [[ ! "$RECONFIG" =~ ^[Yy]$ ]]; then return 0; fi
    fi
    log_info "运行 OpenClaw 配置向导..."
    log_warning "请按照向导提示完成配置（消息通道、LLM 等）"
    echo ""
    if openclaw onboard --install-daemon; then
        log_success "OpenClaw 配置完成"
        OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null | tr -d '\n\r%')
        [ -z "$OPENCLAW_TOKEN" ] && { log_error "无法获取 OpenClaw Token"; exit 1; }
        log_success "OpenClaw Token: ${OPENCLAW_TOKEN:0:20}..."
    else
        log_error "OpenClaw 配置失败"
        exit 1
    fi
    echo ""
    log_info "========================================="
    log_info "配置向导已结束，接下来将启动 Gateway 并打开控制台"
    log_info "请勿按 Ctrl+C，稍候几秒..."
    log_info "========================================="
    echo ""
}

start_openclaw_gateway() {
    log_info "启动 OpenClaw Gateway..."
    if systemctl --user is-active --quiet clawdbot-gateway 2>/dev/null; then
        log_warning "检测到 clawdbot-gateway，停止以便使用 OpenClaw..."
        systemctl --user stop clawdbot-gateway 2>/dev/null || true
        systemctl --user disable clawdbot-gateway 2>/dev/null || true
        sleep 2
    fi
    # 确保本机模式，避免 health 使用 gateway.remote.token 导致 token mismatch
    openclaw config set gateway.mode local 2>/dev/null || true
    if openclaw gateway status >/dev/null 2>&1; then
        log_success "OpenClaw Gateway 已在运行"
    else
        openclaw gateway start >/dev/null 2>&1 && sleep 2 && log_success "OpenClaw Gateway 启动成功" || log_warning "Gateway 可能需手动启动"
    fi
    # 重启一次以加载最新 config（含 token），避免 onboarding 刚写完配置但 daemon 仍用旧配置
    openclaw gateway restart >/dev/null 2>&1
    sleep 3
    if openclaw health >/dev/null 2>&1; then
        log_success "健康检查通过"
    else
        log_warning "健康检查未通过（若报 token mismatch，可执行: openclaw config set gateway.mode local && openclaw gateway restart）"
    fi
    # 去除换行和 zsh 行尾 %：config get 可能带尾随换行；zsh 在无换行时显示 %，若被复制进 token 会导致 mismatch
    OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null | tr -d '\n\r%')
    GATEWAY_PORT=$(openclaw config get gateway.port 2>/dev/null | tr -d '\n\r%')
    [ -z "$GATEWAY_PORT" ] || ! [[ "$GATEWAY_PORT" =~ ^[0-9]+$ ]] && GATEWAY_PORT=18789
    if [ -n "$OPENCLAW_TOKEN" ]; then
        log_success "已获取 Gateway Token 供 Co-Sight 使用"
        echo ""
        log_info "【推荐】打开控制台请使用官方命令（仅此方式能稳定避免 1008 token 错误）："
        echo -e "  ${GREEN}openclaw dashboard${NC}"
        echo ""
        log_info "Co-Sight 集成时请在 .env 中配置："
        echo -e "  OPENCLAW_AUTH_TOKEN=${GREEN}${OPENCLAW_TOKEN}${NC}"
        echo ""
        log_info "正在使用官方命令打开控制台（openclaw dashboard）..."
        if openclaw dashboard 2>/dev/null; then
            log_success "已通过 openclaw dashboard 打开浏览器"
        else
            log_warning "自动打开失败，请手动执行: openclaw dashboard"
        fi
        echo ""
        log_info "若需仅打印/复制链接而不打开浏览器，可执行: openclaw dashboard --no-open"
    else
        log_warning "未获取到 token。请执行: openclaw config get gateway.auth.token  然后执行: openclaw dashboard  打开控制台"
    fi
}

main() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════╗"
    echo "║   OpenClaw 安装与配置                 ║"
    echo "╚═══════════════════════════════════════╝"
    echo -e "${NC}"
    detect_os
    if ! check_nodejs; then install_nodejs; fi
    install_openclaw
    configure_openclaw
    echo ""
    log_success "OpenClaw 安装配置完成。"
    # 安装完成后再次尝试打开控制台（防止上面某步未打开或用户未看到）
    if openclaw config get gateway.auth.token >/dev/null 2>&1; then
        log_info "正在打开控制台..."
        openclaw dashboard 2>/dev/null && log_success "控制台已打开" || log_info "若未自动打开，请执行: openclaw dashboard"
    fi
    echo ""
    log_info "下一步：在新终端中运行 Co-Sight 配置（install.sh 将自动打开，或手动执行 ./install_cosight.sh）"
    log_info "若前端报 disconnected (1008) gateway token missing：请使用官方命令打开控制台: openclaw dashboard（仅此方式能稳定避免 token 错误）。"
}

# 被 source 时不执行 main（供 install_cosight.sh 调用 start_openclaw_gateway）
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    trap 'echo ""; log_warning "已中断"; exit 1' INT
    main "$@"
fi
