"""
Co-Sight 最小测试后端服务器
提供简单的 HTTP API 和静态文件服务
"""

import json
import os
import asyncio
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

# 数据存储
DATA_FILE = os.path.join(os.path.dirname(__file__), 'data', 'chat_data.json')

# 确保数据目录存在
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)


def load_data():
    """加载数据"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'threads': {},
        'folders': []
    }


def save_data(data):
    """保存数据"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# 初始化数据
chat_data = load_data()


class ChatHandler(SimpleHTTPRequestHandler):
    """自定义 HTTP 请求处理器"""
    
    def __init__(self, *args, **kwargs):
        # 设置静态文件根目录为 web 目录
        super().__init__(*args, directory=os.path.dirname(__file__), **kwargs)
    
    def do_GET(self):
        """处理 GET 请求"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        # API 路由
        if path == '/api/threads':
            self.send_json_response(chat_data['threads'])
            return
        elif path == '/api/folders':
            self.send_json_response(chat_data['folders'])
            return
        elif path.startswith('/api/thread/'):
            thread_id = path.split('/')[-1]
            thread = chat_data['threads'].get(thread_id)
            if thread:
                self.send_json_response(thread)
            else:
                self.send_error_response(404, 'Thread not found')
            return
        elif path == '/':
            self.path = '/index-new.html'
        elif path == '/index.html' or path == '/index':
            self.path = '/index-new.html'
        
        return super().do_GET()
    
    def do_POST(self):
        """处理 POST 请求"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        # 读取请求体
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
            return
        
        # API 路由
        if path == '/api/chat':
            self.handle_chat(data)
        elif path == '/api/thread':
            self.handle_create_thread(data)
        elif path == '/api/folder':
            self.handle_create_folder(data)
        else:
            self.send_error_response(404, 'Not found')
    
    def do_PUT(self):
        """处理 PUT 请求"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_error_response(400, 'Invalid JSON')
            return
        
        if path.startswith('/api/thread/'):
            thread_id = path.split('/')[-1]
            self.handle_update_thread(thread_id, data)
        else:
            self.send_error_response(404, 'Not found')
    
    def do_DELETE(self):
        """处理 DELETE 请求"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path.startswith('/api/thread/'):
            thread_id = path.split('/')[-1]
            self.handle_delete_thread(thread_id)
        elif path.startswith('/api/folder/'):
            folder_id = path.split('/')[-1]
            self.handle_delete_folder(folder_id)
        else:
            self.send_error_response(404, 'Not found')
    
    def handle_chat(self, data):
        """处理聊天请求"""
        message = data.get('message', '')
        thread_id = data.get('threadId')
        
        if not message:
            self.send_error_response(400, 'Message is required')
            return
        
        # 生成简单的响应
        response_text = self.generate_response(message)
        
        # 保存到线程
        if thread_id:
            if thread_id not in chat_data['threads']:
                chat_data['threads'][thread_id] = {
                    'id': thread_id,
                    'title': message[:50] + '...' if len(message) > 50 else message,
                    'messages': [],
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
            
            # 添加用户消息
            chat_data['threads'][thread_id]['messages'].append({
                'role': 'user',
                'content': message,
                'timestamp': datetime.now().isoformat()
            })
            
            # 添加助手响应
            chat_data['threads'][thread_id]['messages'].append({
                'role': 'assistant',
                'content': response_text,
                'timestamp': datetime.now().isoformat()
            })
            
            chat_data['threads'][thread_id]['updated_at'] = datetime.now().isoformat()
            save_data(chat_data)
        
        self.send_json_response({'response': response_text})
    
    def generate_response(self, message):
        """生成简单的响应"""
        # 简单的关键词匹配响应
        message_lower = message.lower()
        
        if '你好' in message or 'hello' in message:
            return '你好！有什么我可以帮助你的吗？'
        elif '天气' in message:
            return '我无法获取实时天气信息，但你可以查看天气预报网站获取最新天气情况。'
        elif '时间' in message:
            return f'现在的时间是 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
        elif '日期' in message:
            return f'今天的日期是 {datetime.now().strftime("%Y 年%m 月%d 日")}'
        elif '分析' in message:
            return f'我来帮你分析这个问题。\n\n根据你提供的信息："**{message}**"，我需要收集更多相关数据来进行全面分析。\n\n让我先搜索相关信息...'
        elif '代码' in message or 'code' in message:
            return '我可以帮你编写或审查代码。请提供具体的代码需求或问题描述。\n\n```python\n# 示例代码\ndef hello_world():\n    print("Hello, World!")\n```'
        else:
            return f'收到你的消息："{message}"\n\n这是一个测试响应。在实际应用中，这里会显示 AI 助手的智能回复。'
    
    def handle_create_thread(self, data):
        """处理创建线程请求"""
        title = data.get('title', '新对话')
        folder_id = data.get('folderId')
        
        thread_id = f'thread-{int(datetime.now().timestamp() * 1000)}'
        thread = {
            'id': thread_id,
            'title': title,
            'folderId': folder_id,
            'messages': [],
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        chat_data['threads'][thread_id] = thread
        save_data(chat_data)
        
        self.send_json_response(thread)
    
    def handle_update_thread(self, thread_id, data):
        """处理更新线程请求"""
        if thread_id not in chat_data['threads']:
            self.send_error_response(404, 'Thread not found')
            return
        
        thread = chat_data['threads'][thread_id]
        
        if 'title' in data:
            thread['title'] = data['title']
        if 'folderId' in data:
            thread['folderId'] = data['folderId']
        
        thread['updated_at'] = datetime.now().isoformat()
        save_data(chat_data)
        
        self.send_json_response(thread)
    
    def handle_delete_thread(self, thread_id):
        """处理删除线程请求"""
        if thread_id in chat_data['threads']:
            del chat_data['threads'][thread_id]
            save_data(chat_data)
            self.send_json_response({'success': True})
        else:
            self.send_error_response(404, 'Thread not found')
    
    def handle_create_folder(self, data):
        """处理创建文件夹请求"""
        name = data.get('name', '新文件夹')
        
        folder_id = f'folder-{int(datetime.now().timestamp() * 1000)}'
        folder = {
            'id': folder_id,
            'name': name,
            'thread_ids': [],
            'created_at': datetime.now().isoformat()
        }
        
        chat_data['folders'].append(folder)
        save_data(chat_data)
        
        self.send_json_response(folder)
    
    def handle_delete_folder(self, folder_id):
        """处理删除文件夹请求"""
        folder_index = next((i for i, f in enumerate(chat_data['folders']) if f['id'] == folder_id), None)
        
        if folder_index is not None:
            chat_data['folders'].pop(folder_index)
            save_data(chat_data)
            self.send_json_response({'success': True})
        else:
            self.send_error_response(404, 'Folder not found')
    
    def send_json_response(self, data):
        """发送 JSON 响应"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def send_error_response(self, status_code, message):
        """发送错误响应"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'error': message}, ensure_ascii=False).encode('utf-8'))
    
    def do_OPTIONS(self):
        """处理 OPTIONS 请求（CORS 预检）"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {args[0]}")


def run_server(port=8000):
    """运行服务器"""
    server_address = ('', port)
    httpd = HTTPServer(server_address, ChatHandler)
    print(f'=' * 50)
    print(f'Co-Sight 测试服务器已启动')
    print(f'=' * 50)
    print(f'访问地址：http://localhost:{port}/index-new.html')
    print(f'API 地址：http://localhost:{port}/api/chat')
    print(f'=' * 50)
    print(f'按 Ctrl+C 停止服务器')
    print()
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n正在关闭服务器...')
        httpd.shutdown()


if __name__ == '__main__':
    run_server()