/**
 * 回放初始化脚本
 * 检测URL参数中是否包含回放请求,如果有则自动启动回放
 */

// 检查URL参数是否包含回放请求
function checkReplayRequest() {
    const urlParams = new URLSearchParams(window.location.search);
    const isReplay = urlParams.get('replay') === 'true';
    const workspacePath = urlParams.get('workspace');
    
    if (isReplay && workspacePath) {
        console.log('检测到回放请求:', workspacePath);
        
        // 清除URL参数,避免刷新时重复触发
        // window.history.replaceState({}, document.title, window.location.pathname);
        
        // 切换到主界面
        if (typeof hideInitialInputAndShowMain === 'function') {
            hideInitialInputAndShowMain('');
        }
        
        // 显示回放状态提示
        showReplayStatus();
        
        // 延迟启动回放,确保WebSocket已连接
        setTimeout(() => {
            startReplayFromWorkspace(workspacePath);
        }, 1000);
        
        return true;
    }
    
    return false;
}

// 从工作区启动回放
function startReplayFromWorkspace(workspacePath) {
    console.log('========== 开始回放 ==========');
    console.log('工作区路径:', workspacePath);
    console.log('当前URL:', window.location.href);
    console.log('WebSocket状态:', window.WebSocketService ? window.WebSocketService.isOpen : 'WebSocket未初始化');
    
    // 清理现有状态
    try {
        if (typeof window.resetSessionCaches === 'function') {
            window.resetSessionCaches();
            console.log('✓ 会话缓存已清理');
        }
    } catch (e) {
        console.warn('清理状态失败:', e);
    }
    
    // 提取replayPlanId (如果需要的话)
    let replayPlanId = null;
    try {
        // 从localStorage中查找该workspace对应的planId
        const planIdMap = localStorage.getItem('cosight:planIdByTopic');
        if (planIdMap) {
            const map = JSON.parse(planIdMap);
            // 查找与该workspace匹配的planId
            for (const [topic, planId] of Object.entries(map)) {
                replayPlanId = planId;
                break;
            }
        }
        console.log('replayPlanId:', replayPlanId || '(未找到)');
    } catch (e) {
        console.warn('获取planId失败:', e);
    }
    
    // 发送回放请求
    if (window.messageService && typeof window.messageService.sendReplay === 'function') {
        console.log('✓ messageService可用，准备发送回放请求');
        console.log('回放参数:', {
            workspacePath: workspacePath,
            replayPlanId: replayPlanId
        });
        
        try {
            window.messageService.sendReplay(workspacePath, replayPlanId);
            console.log('✓ 回放请求已发送');
        } catch (e) {
            console.error('✗ 发送回放请求失败:', e);
            alert('发送回放请求失败: ' + e.message);
        }
    } else {
        console.error('✗ messageService不可用');
        console.log('messageService:', window.messageService);
        alert('消息服务未初始化，请刷新页面重试');
    }
    
    console.log('========== 回放请求完成 ==========');
}

// 显示回放状态
function showReplayStatus() {
    // 在标题旁边显示回放标识
    const header = document.querySelector('.header h1');
    if (header && !document.querySelector('.replay-badge')) {
        const badge = document.createElement('span');
        badge.className = 'replay-badge';
        badge.innerHTML = '<i class="fas fa-history"></i> 回放模式';
        header.appendChild(badge);
    }
}

// 页面加载完成后检查回放请求
window.addEventListener('DOMContentLoaded', () => {
    // 等待WebSocket连接
    if (window.WebSocketService && window.WebSocketService.websocketConnected) {
        window.WebSocketService.websocketConnected.addEventListener('connected', () => {
            setTimeout(() => {
                checkReplayRequest();
            }, 500);
        }, { once: true });
    } else {
        // 如果WebSocket还未初始化,延迟检查
        setTimeout(() => {
            checkReplayRequest();
        }, 1500);
    }
});

// 导出函数供其他模块使用
if (typeof window !== 'undefined') {
    window.checkReplayRequest = checkReplayRequest;
    window.startReplayFromWorkspace = startReplayFromWorkspace;
}

