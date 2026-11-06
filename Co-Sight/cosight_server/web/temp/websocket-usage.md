# WebSocket 客户端使用说明

## 概述

这个WebSocket客户端实现基于原生JavaScript，用于与后端WebSocket服务进行通信。后端服务地址为：
`ws://localhost:7788/api/openans-support-chatbot/v1/robot/wss/messages?lang=zh`

## 文件说明

- `websocket.js` - 主要的WebSocket客户端实现
- `websocket-example.js` - 使用示例和辅助函数
- `websocket-usage.md` - 本使用说明文档

## 基本使用

### 1. 引入文件

在HTML文件中引入WebSocket相关脚本：

```html
<script src="websocket.js"></script>
<script src="websocket-example.js"></script>
```

### 2. 基本连接和消息收发

```javascript
// 订阅主题
WebSocketService.subscribe('chat', function(response) {
    console.log('收到消息:', response);
    // 处理接收到的消息
});

// 发送消息
WebSocketService.sendMessage('chat', 'Hello, WebSocket!');

// 监听连接状态
WebSocketService.websocketConnected.addEventListener('connected', function() {
    console.log('WebSocket已连接');
});
```

### 3. 初始化设置

```javascript
// 语言会自动检测浏览器语言，也支持手动设置
WebSocketService.setLang('zh'); // 可选，默认会自动检测

// 初始化连接
WebSocketService.initWebSocket();
```

## API 参考

### 主要方法

#### `subscribe(topic, callback)`
订阅指定主题的消息
- `topic` (string): 主题名称
- `callback` (function): 消息回调函数

#### `unsubscribe(topic)`
取消订阅
- `topic` (string, 可选): 主题名称，为空时取消所有订阅

#### `sendMessage(topic, message)`
发送消息
- `topic` (string): 主题名称
- `message` (string): 消息内容

#### `initWebSocket()`
初始化WebSocket连接

#### `destroy(topic)`
销毁WebSocket服务
- `topic` (string, 可选): 主题名称，为空时销毁所有

### 配置方法

#### `setLang(lang)`
设置语言
- `lang` (string): 语言代码，如 'zh', 'en'
- 注意：如果不手动设置，会自动检测浏览器语言

#### `getConnectionInfo()`
获取连接状态信息
- 返回: 包含连接状态、URL、主题列表等信息的对象

### 属性

#### `isOpen`
检查WebSocket是否已连接
- 返回: boolean

#### `websocketConnected`
连接成功事件对象，可添加事件监听器

## 使用示例

### 示例1: 基本聊天功能

```javascript
// 订阅聊天消息
WebSocketService.subscribe('chat', function(response) {
    const message = response.data;
    displayMessage(message);
});

// 发送聊天消息
function sendChatMessage(text) {
    WebSocketService.sendMessage('chat', text);
}

// 显示消息
function displayMessage(data) {
    const container = document.getElementById('message-container');
    const messageElement = document.createElement('div');
    messageElement.textContent = data.initData || data.content;
    container.appendChild(messageElement);
}
```

### 示例2: 多主题订阅

```javascript
// 订阅多个主题
WebSocketService.subscribe('notifications', function(response) {
    showNotification(response.data);
});

WebSocketService.subscribe('updates', function(response) {
    updateUI(response.data);
});

WebSocketService.subscribe('status', function(response) {
    updateStatus(response.data);
});
```

### 示例3: 错误处理和重连

```javascript
// 监听连接状态
WebSocketService.websocketConnected.addEventListener('connected', function() {
    console.log('WebSocket重连成功');
    // 重新订阅必要的主题
    WebSocketService.subscribe('important-data', handleImportantData);
});

// 定期检查连接状态
setInterval(function() {
    const info = WebSocketService.getConnectionInfo();
    if (!info.isOpen) {
        console.warn('WebSocket连接断开，尝试重连...');
        WebSocketService.initWebSocket();
    }
}, 30000);
```

### 示例4: 页面生命周期管理

```javascript
// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    WebSocketService.initWebSocket();

    // 订阅默认主题
    WebSocketService.subscribe('system', function(response) {
        console.log('系统消息:', response.data);
    });
});

// 页面卸载时清理
window.addEventListener('beforeunload', function() {
    WebSocketService.unsubscribe();
    WebSocketService.destroy();
});
```

## 消息格式

### 发送消息格式

```javascript
{
    "action": "message",        // 固定为 "message"
    "topic": "chat",           // 主题名称
    "data": "Hello World",     // 消息内容
    "lang": "zh"              // 语言设置
}
```

### 接收消息格式

```javascript
{
    "topic": "chat",           // 主题名称
    "data": {                 // 消息数据
        "uuid": "xxx-xxx-xxx", // 消息ID
        "type": "rich-text",   // 消息类型
        "from": "ai",          // 发送方
        "timestamp": 1234567890, // 时间戳
        "initData": "消息内容"   // 实际消息内容
    }
}
```

## 语言自动检测

WebSocket服务会自动检测浏览器的语言设置：

### 检测逻辑
1. 优先获取 `navigator.language` 或 `navigator.userLanguage`
2. 提取语言代码（如 'zh-CN' -> 'zh', 'en-US' -> 'en'）
3. 如果检测到的语言在支持列表中，使用该语言
4. 否则默认使用中文('zh')

### 手动设置语言
```javascript
// 如果需要强制使用特定语言，可以手动设置
WebSocketService.setLang('en');
```

## 注意事项

1. **连接管理**: WebSocket会自动重连，但建议在页面卸载时手动清理资源
2. **错误处理**: 建议监听连接状态变化，处理连接断开的情况
3. **消息格式**: 接收到的消息会自动解析JSON，如果解析失败会使用默认格式
4. **主题管理**: 可以同时订阅多个主题，每个主题独立处理
5. **语言设置**: 支持多语言，会自动检测浏览器语言，也支持手动设置

## 故障排除

### 常见问题

1. **连接失败**: 检查后端服务是否启动，URL是否正确
2. **消息发送失败**: 检查WebSocket连接状态，确保已连接
3. **消息接收异常**: 检查主题订阅是否正确，回调函数是否正常

### 调试方法

```javascript
// 获取连接信息进行调试
const info = WebSocketService.getConnectionInfo();
console.log('连接状态:', info);

// 监听所有WebSocket事件
WebSocketService.websocketConnected.addEventListener('connected', function() {
    console.log('WebSocket连接成功');
});
```

## 更新日志

- v1.0.0: 初始版本，基于TypeScript版本移植到JavaScript
- 支持基本的消息收发、主题订阅、自动重连等功能
