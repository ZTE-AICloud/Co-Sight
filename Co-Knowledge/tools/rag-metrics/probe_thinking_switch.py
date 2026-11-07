"""对比 deepseek-chat 关闭 thinking 的几种请求写法。"""
import json
import os
import time

import requests

base = os.environ['GENERATION_GATEWAY_URL'].rstrip('/')
model = os.environ.get('GENERATION_MODEL', 'deepseek-chat')
key = os.environ.get('GENERATION_API_KEY', '')
headers = {'Content-Type': 'application/json'}
if key:
    headers['Authorization'] = f'Bearer {key}'

variants = [
    ('thinking=false + effort=high',
     {'chat_template_kwargs': {'thinking': False, 'reasoning_effort': 'high'}}),
    ('thinking=false',
     {'chat_template_kwargs': {'thinking': False}}),
    ('reasoning_effort=none',
     {'reasoning_effort': 'none'}),
    ('default', {}),
]

for label, extra in variants:
    body = {
        'model': model,
        'messages': [{'role': 'user', 'content': '只回复两个字：正常'}],
        'max_tokens': 64,
        'temperature': 0,
        **extra,
    }
    started = time.time()
    try:
        response = requests.post(base + '/chat/completions', json=body,
                                 headers=headers, timeout=120,
                                 proxies={'http': None, 'https': None})
        elapsed = time.time() - started
        payload = response.json()
        message = ((payload.get('choices') or [{}])[0].get('message') or {})
        content = message.get('content') or ''
        reasoning = message.get('reasoning_content') or message.get('reasoning') or ''
        print(json.dumps({
            'variant': label,
            'status': response.status_code,
            'elapsed_s': round(elapsed, 2),
            'content': content[:80],
            'reasoning_chars': len(reasoning),
            'usage': payload.get('usage'),
        }, ensure_ascii=False))
    except Exception as error:                                    # noqa: BLE001
        print(json.dumps({'variant': label, 'error': str(error)[:300]}, ensure_ascii=False))
