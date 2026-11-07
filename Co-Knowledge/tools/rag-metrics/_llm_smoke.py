"""最小冒烟：走产品的 OpenAICompatLLM 调一次指定模型。"""
import os

from engine.custom_llm import get_custom_llm

model = os.environ.get('SMOKE_MODEL', 'deepseek-chat')
llm = get_custom_llm(model, {
    'llm': model,
    'max_token': int(os.environ.get('SMOKE_MAX_TOKENS', '512')),
    'temperature': 0.0,
})
if os.environ.get('SMOKE_RAW'):
    import requests
    endpoint = llm._endpoint()
    print('endpoint:', endpoint.url, 'api_model:', endpoint.api_model)
    response = requests.post(
        endpoint.url,
        json={'model': endpoint.api_model,
              'messages': [{'role': 'user', 'content': '只回复两个字：正常'}],
              'temperature': 0.0, 'max_tokens': 64},
        headers=endpoint.headers(), timeout=60)
    print('HTTP', response.status_code, response.text[:500])
    raise SystemExit(0)
print(llm.complete('只回复两个字：正常').text)
