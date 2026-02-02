#!/bin/bash

###########################################
# Co-Sight + OpenClaw 一键安装脚本
# 适用于: Linux / macOS / WSL2
# 版本: 1.0.0
###########################################

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[⚠]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# 显示欢迎信息
show_banner() {
    echo -e "${BLUE}"
    cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   Co-Sight + OpenClaw 一键安装脚本                        ║
║                                                           ║
║   Co-Sight:  深度研究引擎                                 ║
║   OpenClaw:  AI 助手框架                                  ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
}

# 检测操作系统
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="linux"
        log_info "检测到操作系统: Linux"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
        log_info "检测到操作系统: macOS"
    else
        log_error "不支持的操作系统: $OSTYPE"
        exit 1
    fi
}

# 检查命令是否存在
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# 检查 Python 版本
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
        else
            log_warning "Python 版本 $PYTHON_VERSION 过低，需要 ≥3.11"
        fi
    fi
    
    log_error "未找到合适的 Python 版本"
    log_info "请先安装 Python 3.11 或更高版本"
    log_info "安装方式: https://www.python.org/downloads/"
    exit 1
}

# 检查 Node.js 版本
check_nodejs() {
    log_info "检查 Node.js 环境..."
    
    if command_exists node; then
        NODE_VERSION=$(node --version | cut -d'v' -f2)
        NODE_MAJOR=$(echo $NODE_VERSION | cut -d. -f1)
        
        if [ "$NODE_MAJOR" -ge 22 ]; then
            log_success "Node.js v$NODE_VERSION (满足要求 ≥22)"
            return 0
        else
            log_warning "Node.js 版本 v$NODE_VERSION 过低，需要 ≥22"
        fi
    fi
    
    log_warning "未找到合适的 Node.js 版本，将自动安装"
    return 1
}

# 安装 Node.js（使用 nvm）
install_nodejs() {
    log_info "开始安装 Node.js 22..."
    
    # 检查是否已安装 nvm
    if [ ! -d "$HOME/.nvm" ]; then
        log_info "安装 nvm..."
        curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
        
        # 加载 nvm
        export NVM_DIR="$HOME/.nvm"
        [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    else
        log_success "nvm 已安装"
        export NVM_DIR="$HOME/.nvm"
        [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    fi
    
    # 安装 Node.js 22
    nvm install 22
    nvm use 22
    nvm alias default 22
    
    log_success "Node.js 22 安装完成"
}

# 检查 uv（Python 包管理器）
check_uv() {
    log_info "检查 uv 包管理器..."
    
    if command_exists uv; then
        UV_VERSION=$(uv --version | awk '{print $2}')
        log_success "uv $UV_VERSION 已安装"
        USE_UV=true
        return 0
    else
        log_warning "未安装 uv（推荐的 Python 包管理器）"
        echo -n "是否安装 uv？(更快的依赖安装) [Y/n]: "
        read -r INSTALL_UV
        
        if [[ "$INSTALL_UV" =~ ^[Yy]$ ]] || [[ -z "$INSTALL_UV" ]]; then
            log_info "安装 uv..."
            curl -LsSf https://astral.sh/uv/install.sh | sh
            
            # 添加到 PATH
            export PATH="$HOME/.cargo/bin:$PATH"
            
            if command_exists uv; then
                log_success "uv 安装成功"
                USE_UV=true
                return 0
            else
                log_warning "uv 安装失败，将使用 pip"
                USE_UV=false
            fi
        else
            log_info "跳过 uv 安装，将使用 pip"
            USE_UV=false
        fi
    fi
}

# 检查 CMake 版本
check_cmake() {
    if command_exists cmake; then
        CMAKE_VERSION=$(cmake --version | head -1 | awk '{print $3}')
        CMAKE_MAJOR=$(echo $CMAKE_VERSION | cut -d. -f1)
        CMAKE_MINOR=$(echo $CMAKE_VERSION | cut -d. -f2)
        
        log_info "检测到 CMake 版本: $CMAKE_VERSION"
        
        # 检查是否满足 3.19+
        if [ "$CMAKE_MAJOR" -gt 3 ] || ([ "$CMAKE_MAJOR" -eq 3 ] && [ "$CMAKE_MINOR" -ge 19 ]); then
            log_success "CMake 版本满足要求 (≥3.19)"
            return 0
        else
            log_warning "CMake 版本 $CMAKE_VERSION 低于推荐版本 3.19"
            log_info "OpenClaw 的本地 LLM 功能需要 CMake ≥3.19"
            log_info "将跳过本地 LLM 支持（不影响核心功能）"
            
            # 设置环境变量跳过 llama.cpp 编译
            export NODE_LLAMA_CPP_SKIP_BUILD=true
            SKIP_LOCAL_LLM=true
            return 1
        fi
    else
        log_info "未检测到 CMake"
        log_info "将跳过 OpenClaw 本地 LLM 支持（不影响核心功能）"
        
        # 设置环境变量跳过 llama.cpp 编译
        export NODE_LLAMA_CPP_SKIP_BUILD=true
        SKIP_LOCAL_LLM=true
        return 1
    fi
}

# 检查并配置 npm 镜像源
configure_npm_registry() {
    log_info "检查 npm 网络连接..."
    
    # 获取当前 registry
    CURRENT_REGISTRY=$(npm config get registry 2>/dev/null || echo "")
    
    # 测试官方源连接
    if curl -s --connect-timeout 3 --max-time 5 https://registry.npmjs.org/ > /dev/null 2>&1; then
        log_success "npm 官方源可访问"
        return 0
    else
        log_warning "npm 官方源无法访问"
        
        # 测试国内镜像源
        log_info "测试国内镜像源..."
        if curl -s --connect-timeout 3 --max-time 5 https://registry.npmmirror.com/ > /dev/null 2>&1; then
            log_info "检测到网络环境需要使用国内镜像"
            
            echo -n "是否切换到淘宝镜像源？[Y/n]: "
            read -r USE_MIRROR
            
            if [[ "$USE_MIRROR" =~ ^[Nn]$ ]]; then
                log_warning "保持当前配置，但安装可能失败"
                return 1
            fi
            
            log_info "配置淘宝镜像源..."
            npm config set registry https://registry.npmmirror.com
            
            if [ $? -eq 0 ]; then
                log_success "镜像源配置成功"
                NPM_REGISTRY_CHANGED=true
                return 0
            else
                log_error "镜像源配置失败"
                return 1
            fi
        else
            log_error "网络连接异常，请检查网络配置或代理设置"
            log_info "如需配置代理，请运行:"
            log_info "  npm config set proxy http://your-proxy:port"
            log_info "  npm config set https-proxy http://your-proxy:port"
            return 1
        fi
    fi
}

# 安装 OpenClaw
install_openclaw() {
    log_info "========================================="
    log_info "第一步：安装 OpenClaw Gateway"
    log_info "========================================="
    
    if command_exists openclaw; then
        OPENCLAW_VERSION=$(openclaw --version 2>/dev/null | head -1 || echo "未知")
        log_success "OpenClaw 已安装: $OPENCLAW_VERSION"
        
        echo -n "是否重新安装 OpenClaw？[y/N]: "
        read -r REINSTALL_OPENCLAW
        
        if [[ ! "$REINSTALL_OPENCLAW" =~ ^[Yy]$ ]]; then
            log_info "跳过 OpenClaw 安装"
            return 0
        fi
    fi
    
    # 检查 CMake 版本（决定是否跳过本地 LLM）
    # 允许 check_cmake 返回非 0 值，不退出脚本
    check_cmake || true
    
    # 配置 npm 镜像源（如需要）
    configure_npm_registry || true
    
    log_info "开始安装 OpenClaw..."
    
    # 准备 npm 安装选项（使用新版 npm 参数）
    NPM_INSTALL_OPTS=""
    if [ "$SKIP_LOCAL_LLM" = true ]; then
        log_info "跳过本地 LLM 支持（CMake < 3.19）"
        # 使用新版 npm 参数：--omit=optional（替代已废弃的 --no-optional）
        # 同时使用 --ignore-scripts 彻底跳过所有编译脚本
        NPM_INSTALL_OPTS="--omit=optional --ignore-scripts"
    fi
    
    # 使用官方安装脚本
    if curl -fsSL https://openclaw.ai/install.sh | bash; then
        log_success "OpenClaw 安装成功"
    else
        log_error "OpenClaw 官方安装脚本失败，尝试使用 npm 直接安装..."
        
        # 回退到 npm 全局安装
        if command_exists npm; then
            log_info "使用 npm 安装 OpenClaw..."
            
            # 显示当前使用的 registry
            CURRENT_REGISTRY=$(npm config get registry)
            log_info "当前 npm registry: $CURRENT_REGISTRY"
            
            if [ -n "$NPM_INSTALL_OPTS" ]; then
                log_info "使用选项: $NPM_INSTALL_OPTS"
            fi
            
            if npm install -g openclaw@latest $NPM_INSTALL_OPTS; then
                log_success "OpenClaw 通过 npm 安装成功"
                
                if [ "$SKIP_LOCAL_LLM" = true ]; then
                    log_info "注意: 已跳过本地 LLM 功能（不影响 Co-Sight 集成）"
                fi
            else
                log_error "npm 安装失败"
                log_info ""
                log_info "可能的原因和解决方案："
                log_info "1. CMake 版本过低 - 尝试跳过本地 LLM："
                log_info "   export NODE_LLAMA_CPP_SKIP_BUILD=true"
                log_info "   npm install -g openclaw@latest --omit=optional --ignore-scripts"
                log_info ""
                log_info "2. 网络问题 - 请检查网络连接或配置代理"
                log_info "3. 权限问题 - 可能需要 sudo 权限"
                log_info "4. 镜像源问题 - 尝试切换镜像源："
                log_info "   npm config set registry https://registry.npmmirror.com"
                log_info ""
                exit 1
            fi
        else
            log_error "npm 未找到，无法安装 OpenClaw"
            exit 1
        fi
    fi
    
    # 验证安装
    if command_exists openclaw; then
        log_success "OpenClaw 安装验证成功"
        OPENCLAW_VERSION=$(openclaw --version 2>/dev/null | head -1 || echo "未知版本")
        log_info "OpenClaw 版本: $OPENCLAW_VERSION"
    else
        log_error "OpenClaw 安装验证失败"
        log_info "请手动运行:"
        log_info "  export NODE_LLAMA_CPP_SKIP_BUILD=true"
        log_info "  npm install -g openclaw@latest --omit=optional --ignore-scripts"
        exit 1
    fi
}

# 配置 OpenClaw
configure_openclaw() {
    log_info "配置 OpenClaw Gateway..."
    
    # 检查是否已配置
    if openclaw config get gateway.auth.token >/dev/null 2>&1; then
        log_success "OpenClaw 已配置"
        OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token)
        
        echo -n "是否重新运行配置向导？[y/N]: "
        read -r RECONFIG
        
        if [[ ! "$RECONFIG" =~ ^[Yy]$ ]]; then
            log_info "使用现有配置"
            return 0
        fi
    fi
    
    log_info "运行 OpenClaw 配置向导..."
    log_warning "请按照向导提示完成配置（消息通道、LLM 等）"
    
    # 运行 onboarding（会自动安装 daemon）
    if openclaw onboard --install-daemon; then
        log_success "OpenClaw 配置完成"
        
        # 获取 Token
        OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token)
        if [ -z "$OPENCLAW_TOKEN" ]; then
            log_error "无法获取 OpenClaw Token"
            exit 1
        fi
        
        log_success "OpenClaw Token: ${OPENCLAW_TOKEN:0:20}..."
    else
        log_error "OpenClaw 配置失败"
        exit 1
    fi
}

# 启动 OpenClaw Gateway
start_openclaw_gateway() {
    log_info "启动 OpenClaw Gateway..."
    
    # 若本机有 clawdbot-gateway 占用 18789，先停掉以免端口冲突（方案二：只用 openclaw）
    if systemctl --user is-active --quiet clawdbot-gateway 2>/dev/null; then
        log_warning "检测到 clawdbot-gateway 正在运行（与 OpenClaw 同端口 18789）"
        log_info "停止并禁用 clawdbot-gateway，以便仅使用 OpenClaw Gateway..."
        systemctl --user stop clawdbot-gateway 2>/dev/null || true
        systemctl --user disable clawdbot-gateway 2>/dev/null || true
        log_success "已停用 clawdbot-gateway"
        sleep 2
    fi
    
    # 检查 Gateway 状态
    if openclaw gateway status >/dev/null 2>&1; then
        log_success "OpenClaw Gateway 已在运行"
    else
        # 启动 Gateway
        if openclaw gateway start >/dev/null 2>&1; then
            log_success "OpenClaw Gateway 启动成功"
            sleep 2
        else
            log_warning "Gateway 可能已在运行或需要手动启动"
        fi
    fi
    
    # 验证健康状态
    if openclaw health >/dev/null 2>&1; then
        log_success "OpenClaw Gateway 健康检查通过"
    else
        log_warning "Gateway 健康检查未通过，可能需要配置消息通道"
    fi
    
    # 同步当前 Gateway Token，供后续 configure_cosight 写入 .env（避免 token 不一致导致 Co-Sight 报「OpenClaw未连接」）
    OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null)
    if [ -n "$OPENCLAW_TOKEN" ]; then
        log_success "已获取 Gateway Token 供 Co-Sight 使用"
    else
        log_warning "无法获取 Gateway Token，请稍后运行 ./sync_token.sh"
    fi
}

# 安装 Co-Sight
install_cosight() {
    log_info "========================================="
    log_info "第二步：安装 Co-Sight"
    log_info "========================================="
    
    # 检查是否在 Co-Sight 目录
    if [ ! -f "requirements.txt" ]; then
        log_error "当前目录不是 Co-Sight 项目根目录"
        log_info "请在 Co-Sight 目录下运行此脚本"
        exit 1
    fi
    
    log_info "安装 Python 依赖..."
    
    if [ "$USE_UV" = true ]; then
        log_info "使用 uv 安装依赖（更快）..."
        uv pip install -r requirements.txt
    else
        log_info "使用 pip 安装依赖..."
        $PYTHON_CMD -m pip install -r requirements.txt
    fi
    
    log_success "Co-Sight 依赖安装完成"
}

# 配置 Co-Sight
configure_cosight() {
    log_info "配置 Co-Sight..."
    
    # 检查是否已有配置文件
    if [ -f ".env" ]; then
        log_warning "发现已存在的 .env 文件"
        echo -n "是否备份并重新配置？[y/N]: "
        read -r RECONFIG_COSIGHT
        
        if [[ "$RECONFIG_COSIGHT" =~ ^[Yy]$ ]]; then
            BACKUP_NAME=".env.backup.$(date +%Y%m%d_%H%M%S)"
            cp .env "$BACKUP_NAME"
            log_info "已备份到: $BACKUP_NAME"
        else
            log_info "保留现有配置"
            return 0
        fi
    fi
    
    # 复制模板
    if [ ! -f ".env_template" ]; then
        log_error "找不到 .env_template 文件"
        exit 1
    fi
    
    cp .env_template .env
    log_success "已创建 .env 配置文件"
    
    # 交互式配置
    echo ""
    log_info "========================================="
    log_info "配置向导"
    log_info "========================================="
    
    # LLM 配置
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
    
    # 搜索引擎配置
    echo ""
    log_info "2. 搜索引擎配置（可选，按 Enter 跳过）"
    echo -n "Google API Key: "
    read -r GOOGLE_API_KEY
    
    if [ -n "$GOOGLE_API_KEY" ]; then
        echo -n "Google Search Engine ID: "
        read -r SEARCH_ENGINE_ID
    fi
    
    echo -n "Tavily API Key: "
    read -r TAVILY_API_KEY
    
    # 更新 .env 文件
    sed -i "s|^API_KEY=.*|API_KEY=$API_KEY|" .env
    sed -i "s|^API_BASE_URL=.*|API_BASE_URL=$API_BASE_URL|" .env
    sed -i "s|^MODEL_NAME=.*|MODEL_NAME=$MODEL_NAME|" .env
    
    # OpenClaw 配置
    sed -i "s|^OPENCLAW_ENABLED=.*|OPENCLAW_ENABLED=True|" .env
    sed -i "s|^OPENCLAW_AUTH_TOKEN=.*|OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN|" .env
    
    if [ -n "$GOOGLE_API_KEY" ]; then
        sed -i "s|^GOOGLE_API_KEY=.*|GOOGLE_API_KEY=$GOOGLE_API_KEY|" .env
        [ -n "$SEARCH_ENGINE_ID" ] && sed -i "s|^SEARCH_ENGINE_ID=.*|SEARCH_ENGINE_ID=$SEARCH_ENGINE_ID|" .env
    fi
    
    if [ -n "$TAVILY_API_KEY" ]; then
        sed -i "s|^TAVILY_API_KEY=.*|TAVILY_API_KEY=$TAVILY_API_KEY|" .env
    fi
    
    log_success "Co-Sight 配置完成"
    
    # 显示配置摘要
    echo ""
    log_info "========================================="
    log_info "配置摘要"
    log_info "========================================="
    echo "LLM API:        ${API_BASE_URL}"
    echo "Model:          ${MODEL_NAME}"
    echo "OpenClaw Token: ${OPENCLAW_TOKEN:0:20}..."
    [ -n "$GOOGLE_API_KEY" ] && echo "Google Search:  已配置"
    [ -n "$TAVILY_API_KEY" ] && echo "Tavily Search:  已配置"
    echo ""
}

# 创建启动脚本
create_startup_scripts() {
    log_info "创建启动脚本..."
    
    # Co-Sight 启动脚本
    cat > start_cosight.sh << 'EOF'
#!/bin/bash
# Co-Sight 启动脚本

cd "$(dirname "$0")"

# 检查 uv 是否可用
if command -v uv >/dev/null 2>&1; then
    echo "使用 uv 启动 Co-Sight..."
    uv run cosight_server/deep_research/main.py
else
    echo "使用 python 启动 Co-Sight..."
    python3 cosight_server/deep_research/main.py
fi
EOF
    chmod +x start_cosight.sh
    log_success "已创建 start_cosight.sh"
    
    # 停止脚本
    cat > stop_cosight.sh << 'EOF'
#!/bin/bash
# Co-Sight 停止脚本

echo "停止 Co-Sight..."
pkill -f "cosight_server/deep_research/main.py"
echo "Co-Sight 已停止"
EOF
    chmod +x stop_cosight.sh
    log_success "已创建 stop_cosight.sh"
    
    # Token 同步脚本
    cat > sync_token.sh << 'EOF'
#!/bin/bash
# 同步 OpenClaw Token 到 Co-Sight

echo "========================================="
echo "同步 OpenClaw Token"
echo "========================================="

# 获取最新的 OpenClaw Token
echo "获取 OpenClaw Token..."
OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null)

if [ -z "$OPENCLAW_TOKEN" ]; then
    echo "✗ 无法获取 OpenClaw Token"
    echo "请检查 OpenClaw 是否已正确配置"
    exit 1
fi

echo "✓ 获取到 Token: ${OPENCLAW_TOKEN:0:20}..."

# 备份现有配置
if [ -f ".env" ]; then
    BACKUP_NAME=".env.backup.$(date +%Y%m%d_%H%M%S)"
    cp .env "$BACKUP_NAME"
    echo "✓ 已备份现有配置: $BACKUP_NAME"
    
    # 更新 Token
    if grep -q "^OPENCLAW_AUTH_TOKEN=" .env; then
        sed -i "s|^OPENCLAW_AUTH_TOKEN=.*|OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN|" .env
        echo "✓ Token 已更新到 .env 文件"
    else
        echo "OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN" >> .env
        echo "✓ Token 已添加到 .env 文件"
    fi
else
    echo "✗ 找不到 .env 文件"
    exit 1
fi

echo ""
echo "========================================="
echo "Token 同步完成！"
echo "========================================="
echo ""
echo "下一步："
echo "1. 重启 Co-Sight: ./restart_all.sh"
echo "   或者: pkill -f cosight && ./start_cosight.sh"
echo ""
echo "2. 检查连接状态: tail -f logs/openclaw_client.log"
echo ""
EOF
    chmod +x sync_token.sh
    log_success "已创建 sync_token.sh (Token同步脚本)"
    
    # 重启脚本（改进版，自动同步 token）
    cat > restart_all.sh << 'EOF'
#!/bin/bash
# 重启所有服务

echo "========================================="
echo "重启 Co-Sight + OpenClaw"
echo "========================================="

cd "$(dirname "$0")"

# 停止服务
echo "停止 Co-Sight..."
pkill -f "cosight_server/deep_research/main.py"

# 若存在 clawdbot-gateway，先停掉以免与 openclaw 抢 18789
if systemctl --user is-active --quiet clawdbot-gateway 2>/dev/null; then
    echo "停用 clawdbot-gateway（避免端口冲突）..."
    systemctl --user stop clawdbot-gateway 2>/dev/null || true
    sleep 2
fi

echo "重启 OpenClaw Gateway..."
openclaw gateway restart

sleep 3

# 同步最新的 Token
echo "同步 OpenClaw Token..."
OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null)

if [ -n "$OPENCLAW_TOKEN" ]; then
    echo "✓ 获取到 Token: ${OPENCLAW_TOKEN:0:20}..."
    
    if [ -f ".env" ]; then
        # 备份并更新
        BACKUP_NAME=".env.backup.$(date +%Y%m%d_%H%M%S)"
        cp .env "$BACKUP_NAME"
        
        if grep -q "^OPENCLAW_AUTH_TOKEN=" .env; then
            sed -i "s|^OPENCLAW_AUTH_TOKEN=.*|OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN|" .env
            echo "✓ Token 已自动更新"
        else
            echo "OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN" >> .env
            echo "✓ Token 已自动添加"
        fi
    fi
else
    echo "⚠ 无法获取 Token，使用现有配置"
fi

sleep 2

# 启动 Co-Sight
echo "启动 Co-Sight..."
nohup ./start_cosight.sh > logs/cosight_startup.log 2>&1 &

sleep 3

# 验证服务
echo ""
echo "验证服务状态..."
openclaw gateway status
echo ""

if pgrep -f "cosight_server/deep_research/main.py" > /dev/null; then
    echo "✓ Co-Sight 运行中"
    curl -s http://localhost:7788/cosight/ > /dev/null && echo "✓ Web 服务可访问" || echo "⚠ Web 服务暂未就绪"
else
    echo "✗ Co-Sight 未启动"
fi

echo ""
echo "========================================="
echo "重启完成！"
echo "访问: http://localhost:7788/cosight/"
echo ""
echo "查看日志:"
echo "  OpenClaw 连接: tail -f logs/openclaw_client.log"
echo "  WebSocket: tail -f logs/websocket.log"
echo "========================================="
EOF
    chmod +x restart_all.sh
    log_success "已创建 restart_all.sh (自动同步token)"
    
    # 状态检查脚本
    cat > check_status.sh << 'EOF'
#!/bin/bash
# 检查服务状态

echo "========================================="
echo "服务状态检查"
echo "========================================="
echo ""

echo "1. OpenClaw Gateway:"
openclaw gateway status
echo ""

echo "2. Co-Sight:"
if pgrep -f "cosight_server/deep_research/main.py" > /dev/null; then
    echo "✓ Co-Sight 运行中"
    curl -s http://localhost:7788/cosight/ > /dev/null && echo "✓ Web 服务可访问" || echo "✗ Web 服务不可访问"
else
    echo "✗ Co-Sight 未运行"
fi
echo ""

echo "3. 日志:"
echo "Co-Sight 日志:     logs/co-sight.log"
echo "OpenClaw 日志:     openclaw logs"
echo ""
echo "========================================="
EOF
    chmod +x check_status.sh
    log_success "已创建 check_status.sh"
}

# 启动服务
start_services() {
    log_info "========================================="
    log_info "第三步：启动服务"
    log_info "========================================="
    
    # 启动前同步 Token 到 .env，确保 Co-Sight 能连上网关（一键安装成功关键）
    log_info "同步 OpenClaw Token 到 .env..."
    OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null)
    if [ -n "$OPENCLAW_TOKEN" ] && [ -f ".env" ]; then
        if grep -q "^OPENCLAW_AUTH_TOKEN=" .env; then
            sed -i "s|^OPENCLAW_AUTH_TOKEN=.*|OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN|" .env
            log_success "Token 已同步到 .env"
        else
            echo "OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN" >> .env
            log_success "Token 已写入 .env"
        fi
    elif [ ! -f ".env" ]; then
        log_warning "未找到 .env，请先完成配置向导"
    else
        log_warning "无法获取 Token，Co-Sight 可能报「OpenClaw未连接」，安装后可运行 ./sync_token.sh 后重启"
    fi
    
    # 确保 logs 目录存在
    mkdir -p logs
    
    # 启动 Co-Sight
    log_info "启动 Co-Sight 服务..."
    
    echo -n "是否在后台启动 Co-Sight？[Y/n]: "
    read -r START_BACKGROUND
    
    if [[ "$START_BACKGROUND" =~ ^[Nn]$ ]]; then
        log_info "前台运行 Co-Sight（Ctrl+C 停止）..."
        log_info "访问地址: http://localhost:7788/cosight/"
        echo ""
        
        if [ "$USE_UV" = true ]; then
            uv run cosight_server/deep_research/main.py
        else
            $PYTHON_CMD cosight_server/deep_research/main.py
        fi
    else
        log_info "后台启动 Co-Sight..."
        nohup ./start_cosight.sh > logs/cosight_startup.log 2>&1 &
        
        sleep 3
        
        if pgrep -f "cosight_server/deep_research/main.py" > /dev/null; then
            log_success "Co-Sight 已在后台启动"
        else
            log_error "Co-Sight 启动失败，请查看日志: logs/cosight_startup.log"
            exit 1
        fi
    fi
}

# 显示安装总结
show_summary() {
    echo ""
    log_success "========================================="
    log_success "安装完成！🎉"
    log_success "========================================="
    echo ""
    
    echo "📍 访问地址:"
    echo "   Co-Sight Web:  http://localhost:7788/cosight/"
    echo ""
    
    echo "🔧 常用命令:"
    echo "   启动 Co-Sight:     ./start_cosight.sh"
    echo "   停止 Co-Sight:     ./stop_cosight.sh"
    echo "   重启所有服务:      ./restart_all.sh (自动同步token)"
    echo "   同步 Token:        ./sync_token.sh"
    echo "   检查服务状态:      ./check_status.sh"
    echo ""
    
    echo "🔍 OpenClaw 命令:"
    echo "   Gateway 状态:      openclaw gateway status"
    echo "   健康检查:          openclaw health"
    echo "   查看日志:          openclaw logs --follow"
    echo "   重启 Gateway:      openclaw gateway restart"
    echo ""
    
    echo "📋 配置文件:"
    echo "   Co-Sight:          .env"
    echo "   OpenClaw:          ~/.openclaw/openclaw.json"
    echo ""
    echo "📦 OpenClaw 安装位置（本机）:"
    OPENCLAW_BIN=$(command -v openclaw 2>/dev/null)
    OPENCLAW_ROOT=$(npm root -g 2>/dev/null)
    if [ -n "$OPENCLAW_BIN" ]; then
        echo "   可执行文件:        $OPENCLAW_BIN"
    fi
    if [ -n "$OPENCLAW_ROOT" ] && [ -d "$OPENCLAW_ROOT/openclaw" ]; then
        echo "   包目录:            $OPENCLAW_ROOT/openclaw"
    fi
    echo "   查看: which openclaw 或 npm root -g"
    echo ""
    
    echo "📝 日志文件:"
    echo "   Co-Sight:          logs/co-sight.log"
    echo "   WebSocket:         logs/websocket.log"
    echo "   OpenClaw Client:   logs/openclaw_client.log"
    echo ""
    
    echo "🧪 快速测试:"
    echo "   1. 访问: http://localhost:7788/cosight/"
    echo "   2. 输入: /openclaw 你好"
    echo "   3. 查看响应来自 OpenClaw"
    echo "   若提示「OpenClaw未连接」: 运行 ./sync_token.sh 后 ./restart_all.sh"
    echo ""
    
    echo "📚 文档:"
    echo "   部署指南:          QUICK_DEPLOY.md"
    echo "   使用说明:          OPENCLAW_COMMAND_USAGE.md"
    echo "   网络问题:          网络问题解决方案.md"
    echo "   网关 Token 冲突:   fix_gateway_token.md"
    echo ""
    
    # 如果修改了 npm registry，显示提示
    if [ "$NPM_REGISTRY_CHANGED" = true ]; then
        echo "🌐 npm 镜像源:"
        CURRENT_REGISTRY=$(npm config get registry)
        echo "   当前使用:          $CURRENT_REGISTRY"
        echo "   恢复官方源:        npm config set registry https://registry.npmjs.org"
        echo ""
    fi
    
    # 如果跳过了本地 LLM，显示说明
    if [ "$SKIP_LOCAL_LLM" = true ]; then
        echo "💡 说明:"
        echo "   本地 LLM 功能:     已跳过（CMake < 3.19）"
        echo "   核心功能:          完全正常"
        echo "   Co-Sight 集成:     不受影响"
        echo ""
    fi
    
    log_warning "提示: 如需卸载，运行: ./uninstall.sh"
    echo ""
}

# 创建卸载脚本
create_uninstall_script() {
    cat > uninstall.sh << 'EOF'
#!/bin/bash
# Co-Sight + OpenClaw 卸载脚本

echo "========================================="
echo "卸载 Co-Sight + OpenClaw"
echo "========================================="
echo ""

echo "⚠️  警告: 此操作将："
echo "  - 停止所有服务"
echo "  - 删除 Co-Sight 配置文件"
echo "  - 卸载 OpenClaw（可选）"
echo ""

read -p "确认卸载？[y/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
fi

# 停止服务
echo "停止服务..."
pkill -f "cosight_server/deep_research/main.py" 2>/dev/null || true
openclaw gateway stop 2>/dev/null || true

# 备份配置
if [ -f ".env" ]; then
    BACKUP=".env.backup.$(date +%Y%m%d_%H%M%S)"
    cp .env "$BACKUP"
    echo "✓ 配置已备份到: $BACKUP"
fi

# 删除 Co-Sight 相关文件
echo "清理 Co-Sight 文件..."
rm -f .env
rm -f start_cosight.sh stop_cosight.sh restart_all.sh check_status.sh
echo "✓ Co-Sight 配置已清理"

# 询问是否卸载 OpenClaw
echo ""
read -p "是否同时卸载 OpenClaw？[y/N]: " UNINSTALL_OPENCLAW
if [[ "$UNINSTALL_OPENCLAW" =~ ^[Yy]$ ]]; then
    openclaw gateway uninstall
    npm uninstall -g openclaw
    echo "✓ OpenClaw 已卸载"
fi

echo ""
echo "========================================="
echo "卸载完成！"
echo "========================================="
EOF
    chmod +x uninstall.sh
    log_success "已创建 uninstall.sh"
}

# 主函数
main() {
    show_banner
    
    # 检测系统
    detect_os
    
    # 环境检查
    check_python
    check_uv
    
    if ! check_nodejs; then
        install_nodejs
    fi
    
    echo ""
    
    # 安装 OpenClaw
    install_openclaw
    configure_openclaw
    start_openclaw_gateway
    
    echo ""
    
    # 安装 Co-Sight
    install_cosight
    configure_cosight
    
    echo ""
    
    # 创建辅助脚本
    create_startup_scripts
    create_uninstall_script
    
    echo ""
    
    # 启动服务
    start_services
    
    # 显示总结
    show_summary
}

# 捕获 Ctrl+C
trap 'echo ""; log_warning "安装已中断"; exit 1' INT

# 执行主函数
main "$@"
