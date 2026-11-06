/**
 * WebSocket使用示例
 * 展示如何在其他JavaScript文件中使用WebSocket服务
 */

// 使用示例1: 基本消息收发
function basicWebSocketExample() {
    // 订阅主题
    WebSocketService.subscribe('chat', function(response) {
        console.log('收到消息:', response);
        // 处理接收到的消息
        if (response.data && response.data.type === 'rich-text') {
            displayMessage(response.data);
        }
    });

    // 发送消息
    function sendChatMessage(message) {
        WebSocketService.sendMessage('chat', message);
    }

    // 监听连接状态
    WebSocketService.websocketConnected.addEventListener('connected', function() {
        console.log('WebSocket已连接');
        // 连接成功后可以发送初始消息
        sendChatMessage('Hello, WebSocket!');
    });
}

// 使用示例2: 多主题订阅
function multiTopicExample() {
    // 订阅多个主题
    WebSocketService.subscribe('notifications', function(response) {
        console.log('通知消息:', response.data);
        showNotification(response.data);
    });

    WebSocketService.subscribe('updates', function(response) {
        console.log('更新消息:', response.data);
        updateUI(response.data);
    });

    WebSocketService.subscribe('status', function(response) {
        console.log('状态消息:', response.data);
        updateStatus(response.data);
    });
}

// 使用示例3: 错误处理和重连
function errorHandlingExample() {
    // 监听连接状态
    WebSocketService.websocketConnected.addEventListener('connected', function() {
        console.log('WebSocket重连成功');
        // 重新订阅必要的主题
        WebSocketService.subscribe('important-data', handleImportantData);
    });

    // 定期检查连接状态
    setInterval(function() {
        const info = WebSocketService.getConnectionInfo();
        console.log('连接状态:', info);

        if (!info.isOpen) {
            console.warn('WebSocket连接断开，尝试重连...');
            WebSocketService.initWebSocket();
        }
    }, 30000); // 每30秒检查一次
}

// 使用示例4: 在页面加载时初始化
function initializeWebSocket() {
    // 设置语言
    WebSocketService.setLang('zh');

    // 初始化连接
    WebSocketService.initWebSocket();

    // 订阅默认主题
    WebSocketService.subscribe('system', function(response) {
        console.log('系统消息:', response.data);
    });
}

// 使用示例5: 页面卸载时清理
function cleanupWebSocket() {
    // 取消所有订阅
    WebSocketService.unsubscribe();

    // 销毁连接
    WebSocketService.destroy();
}

// 辅助函数示例
function displayMessage(data) {
    // 在页面上显示消息
    const messageContainer = document.getElementById('message-container');
    if (messageContainer) {
        const messageElement = document.createElement('div');
        messageElement.className = 'message';
        messageElement.innerHTML = `
            <div class="message-content">${data.initData || data.content || '未知消息'}</div>
            <div class="message-time">${new Date(data.timestamp).toLocaleString()}</div>
        `;
        messageContainer.appendChild(messageElement);
        messageContainer.scrollTop = messageContainer.scrollHeight;
    }
}

function showNotification(data) {
    // 显示通知
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('新通知', {
            body: data.message || '您有新的通知',
            icon: '/images/notification-icon.png'
        });
    }
}

function updateUI(data) {
    // 更新UI元素
    const statusElement = document.getElementById('status');
    if (statusElement) {
        statusElement.textContent = data.status || '未知状态';
        statusElement.className = `status ${data.status || 'unknown'}`;
    }
}

function updateStatus(data) {
    // 更新状态信息
    console.log('状态更新:', data);
}

function handleImportantData(response) {
    // 处理重要数据
    console.log('重要数据:', response.data);
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initializeWebSocket();

    // 页面卸载时清理
    window.addEventListener('beforeunload', cleanupWebSocket);
});

// 导出函数供其他文件使用
window.WebSocketExamples = {
    basicWebSocketExample,
    multiTopicExample,
    errorHandlingExample,
    initializeWebSocket,
    cleanupWebSocket,
    displayMessage,
    showNotification,
    updateUI,
    updateStatus
};
