function cleanupWebSocket() {
    // 取消所有订阅
    WebSocketService.unsubscribe();
    // 销毁连接
    WebSocketService.destroy();
}

function setupMessageHandling() {
    // 检查是否有pending的请求需要重发
    try {
        const pendingRaw = localStorage.getItem('cosight:pendingRequests');
        if (pendingRaw) {
            const pendings = JSON.parse(pendingRaw);
            Object.entries(pendings).forEach(([topic, data]) => {
                if (data && data.message) {
                    console.log('恢复pending订阅:', topic);
                    // 重新订阅
                    WebSocketService.subscribe(topic, messageService.receiveMessage.bind(messageService));
                    // 仅当明确 stillPending===true 时才重发，避免刷新重复执行
                    if (data.stillPending === true) {
                        console.log('重发pending请求:', topic);
                        WebSocketService.sendMessage(topic, JSON.stringify(data.message));
                    }
                }
            });
        }
    } catch (e) {
        console.warn('处理pending请求失败:', e);
    }
}

document.addEventListener("DOMContentLoaded", function () {
    // 初始化websocket连接
    WebSocketService.initWebSocket();
    
    // 等待WebSocket连接建立后设置消息处理
    WebSocketService.websocketConnected.addEventListener('connected', function() {
        console.log('WebSocket连接已建立，设置消息处理...');
        setupMessageHandling();
    });
    
    // 初始化输入框
    initInputHandler();
    
    // 检查是否有保存的DAG数据需要恢复
    checkAndRestoreDAGData();

    // 监听窗口大小变化
    window.addEventListener("resize", handleResize);

    // 添加全局点击事件，关闭所有验证步骤提示框
    document.addEventListener('click', function (event) {
        // 检查点击的是否是验证步骤图标或全局提示框
        const isVerificationIcon = event.target.closest('.verification-icon');
        const isVerificationTooltip = event.target.id === 'verification-tooltip';

        // 如果点击的不是验证步骤相关元素，关闭所有提示框
        if (!isVerificationIcon && !isVerificationTooltip) {
            closeAllVerificationTooltips();
        }
    });

    // 添加ESC键监听器，关闭所有验证步骤提示框
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            closeAllVerificationTooltips();
        }
    });

    // 为全局验证步骤提示框添加鼠标事件
    const verificationTooltip = document.getElementById('verification-tooltip');
    if (verificationTooltip) {
        verificationTooltip.addEventListener('mouseenter', function () {
            // 清除隐藏定时器，保持提示框显示
            if (verificationTooltipTimeout) {
                clearTimeout(verificationTooltipTimeout);
                verificationTooltipTimeout = null;
            }
        });

        verificationTooltip.addEventListener('mouseleave', function () {
            // 鼠标离开提示框时隐藏
            hideVerificationTooltip();
        });
    }

    // 为tooltip添加鼠标事件，允许用户移动到tooltip上点击链接
    const tooltipElement = document.getElementById('tooltip');
    if (tooltipElement) {
        tooltipElement.addEventListener('mouseenter', function () {
            // 清除隐藏定时器，保持tooltip显示
            if (typeof tooltipTimeout !== 'undefined' && tooltipTimeout) {
                clearTimeout(tooltipTimeout);
                tooltipTimeout = null;
            }
        });

        tooltipElement.addEventListener('mouseleave', function () {
            // 鼠标离开tooltip时隐藏
            if (typeof hideTooltip === 'function') {
                hideTooltip();
            }
        });
    }

    // 为动态标题添加hover事件
    const dynamicTitle = document.getElementById('dynamic-title');
    if (dynamicTitle) {
        dynamicTitle.addEventListener('mouseenter', showStepsTooltip);
        dynamicTitle.addEventListener('mouseleave', hideStepsTooltip);
        dynamicTitle.addEventListener('mousemove', showStepsTooltip);
    }

    // 页面卸载时清理
    window.addEventListener('beforeunload', cleanupWebSocket);
});