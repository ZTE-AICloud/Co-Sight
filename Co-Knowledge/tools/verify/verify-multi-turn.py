#!/usr/bin/env python3
"""多轮对话验收：同一会话里「追问」能接上，换个新会话问同一句则接不上。

为什么需要**对照组**：追问接不接得上，光看多轮那次的答案不够 —— 模型有可能自己
蒙对（把「它的缺点」当成泛泛而谈）。本脚本每次都同时跑两组：

  A. 同一 `conversation_id`：先问 T1（主题句），再问 T2（**带指代、单独看没有意义**的追问）
     → 期望 T2 的答案**在讲 T1 的主题**；
  B. 全新 `conversation_id`：只问 T2
     → 期望答非所问（模型反问「您说的『它』指什么」）。

B 组答不出来，才证明 A 组是**多轮**带来的，而不是模型碰巧答上了。

机制（供排查用）：编排侧 `LLMQueryRewriter` 在 pre-retriever 槽位里，改写提示词带
`{last_question}`。有两条来源：

1. **请求里的 `chat_history`**（问答对列表，前端每次都带最近 8 轮）—— 与服务重启/换浏览器
   无关；画布上的 `multi_chat_limit` 为 0 时按默认 8 轮处理；
2. 进程内 TTL 缓存（`core/cache/chat_memory.py`，键 `conversation_id`）—— 旧客户端不带
   `chat_history` 时的回落，仍是单副本约束。

所以**同一会话必须复用同一个 `conversation_id`**（服务端 history 缓存与日志关联都按它），
换会话就是换键。

用法（仓库根目录）::

    python3 tools/verify/verify-multi-turn.py
    python3 tools/verify/verify-multi-turn.py --workflow RAG_Workflow_a4e4
    python3 tools/verify/verify-multi-turn.py --attempts 3      # 见下方「抖动」

退出码：0 = 两组都符合预期；1 = 有不符合（见输出里的 ❌）。

⚠️ **改写算子是 LLM，会有采样抖动**：实测同一上下文重复跑，偶有一轮改写没把代词
解析出来（那一次就会反问）。所以偶发失败先 `--attempts` 重跑几次再下结论 ——
脚本不会替你重试，也不会把重试结果伪装成一次通过。
"""
# 编排与 RKB 同进程：对外只有一个前缀，见
# backend/src/shared/prefixes.py
RKB_PREFIX = '/api/co-knowledge/v1'
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

# 宿主若配了 http_proxy，去容器网段的请求会被代理截胡（实测表现为超时）。本脚本一律绕过。
os.environ['no_proxy'] = '*'
os.environ['NO_PROXY'] = '*'

TIMEOUT = 300

# 默认的 T1/T2：T2 单独看没有意义，只能在 T1 的上下文中被理解 —— 这才测得出多轮。
DEFAULT_TOPIC = '向量检索是什么？'
DEFAULT_FOLLOW_UP = '那它的缺点呢？'

# 「接上了」的判据：答案里出现足够多的主题词（缺点的常见说法）
DEFAULT_KEYWORDS = ['内存', '存储', '精度', '召回', '维度', 'embedding', 'Embedding',
                    '算力', '成本', '近似', '延迟']
# 「答非所问」的判据：反问的常见措辞
CLARIFY_MARKERS = ['具体指什么', '具体指什么呢', '指的是什么', '指什么呢',
                   '补充一下', '请补充', '哪一个', '哪个对象']


def call(url, body):
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status, resp.read().decode('utf-8', 'replace')


def ask(rkb, workflow, question, conversation_id, stream):
    """一次提问。stream=True 时拼 SSE 的正文帧，返回纯文本答案。"""
    status, raw = call(rkb + '/query', {
        'question': question, 'conversation_id': conversation_id,
        'workflow_id': workflow, 'stream': stream,
    })
    if status != 200:
        return f'[HTTP {status}] {raw[:200]}'
    if not stream:
        payload = json.loads(raw)
        answer = payload.get('answer') if isinstance(payload, dict) else None
        return answer if isinstance(answer, str) else json.dumps(payload, ensure_ascii=False)
    # SSE：`event: token` + `data: {"content": ...}`，终态 `done`
    parts = []
    event = 'message'
    data = []
    for line in raw.split('\n'):
        if line.endswith('\r'):
            line = line[:-1]
        if not line:
            if event == 'token' and data:
                try:
                    parts.append(json.loads('\n'.join(data)).get('content', ''))
                except ValueError:
                    pass
            event, data = 'message', []
            continue
        field, _, value = line.partition(':')
        if value.startswith(' '):
            value = value[1:]
        if field == 'event':
            event = value
        elif field == 'data':
            data.append(value)
    return ''.join(parts)


def strip_reasoning(text):
    """去掉模型自己写在 content 里的 <think>…</think>（编排侧是原样透传的）。"""
    return re.sub(r'<think>[\s\S]*?</think>', '', text).strip()


def classify(answer, keywords):
    """粗判：接上了 / 答非所问 / 存疑。判据是**关键词启发式**，不是语义判定。"""
    hits = sum(1 for kw in keywords if kw in answer)
    clarify = any(marker in answer for marker in CLARIFY_MARKERS)
    if clarify and hits < 2:
        return '答非所问', hits
    if hits >= 2:
        return '接上了', hits
    if clarify:
        return '答非所问', hits
    return '存疑', hits


def resolve_rkb(explicit):
    if explicit:
        return explicit
    try:
        ip = subprocess.check_output(
            ['docker', 'inspect', '-f',
             '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',
             'rag-studio-rag-knowledge-base-1'], text=True).strip()
        if ip:
            print(f'   （自动解析到 RKB 容器 IP：{ip}）')
            return f'http://{ip}:8091{RKB_PREFIX}'
    except Exception:
        pass
    return 'http://127.0.0.1:8091' + RKB_PREFIX


def resolve_workflow(web, explicit):
    """挑一条**已发布**的工作流。未发布的跑不起来（会明确报「没有已发布的版本」）。"""
    if explicit:
        return explicit
    url = web + RKB_PREFIX + '/workflows?page=1&size=50'
    with urllib.request.urlopen(url, timeout=60) as resp:
        payload = json.loads(resp.read().decode('utf-8', 'replace'))
    rows = payload.get('items') or []
    published = [row for row in rows if row.get('publishType')]
    if not published:
        print('❌ 没有已发布的工作流：先在「检索编排」里保存并发布一条，再跑本脚本')
        return None
    picked = published[0]
    print(f"   用已发布工作流：{picked.get('name')}（{picked.get('workFlowId')}）")
    return picked.get('workFlowId')


def run_once(rkb, workflow, stream, topic, follow_up, keywords):
    mode = '流式  ' if stream else '非流式'
    # A 组：同一会话 T1 → T2
    multi_conversation = 'verify-mt-' + uuid.uuid4().hex[:8]
    ask(rkb, workflow, topic, multi_conversation, stream)
    multi_answer = strip_reasoning(ask(rkb, workflow, follow_up, multi_conversation, stream))
    multi_verdict, multi_hits = classify(multi_answer, keywords)
    # B 组：新会话只问 T2
    ctrl_conversation = 'verify-ctrl-' + uuid.uuid4().hex[:8]
    ctrl_answer = strip_reasoning(ask(rkb, workflow, follow_up, ctrl_conversation, stream))
    ctrl_verdict, _ = classify(ctrl_answer, keywords)

    print(f'   {mode} 多轮：{multi_verdict}（主题词 {multi_hits}）')
    print(f'            {multi_answer[:110]}')
    print(f'   {mode} 对照：{ctrl_verdict}')
    print(f'            {ctrl_answer[:110]}')
    # 判据：多轮要「接上了」；对照组**不能**也「接上了」（否则这次没有区分度，
    # 可能是模型对这句本来就答得上，这一轮结果不能用来说明多轮生效）
    ok = multi_verdict == '接上了' and ctrl_verdict != '接上了'
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--web', default='http://127.0.0.1', help='web 入口（nginx 反代 RKB）')
    parser.add_argument('--rkb', default='', help='RKB 基址；留空自动解析容器 IP')
    parser.add_argument('--workflow', default='', help='工作流 ID（RAG_Workflow_xxxx）；留空自动挑已发布的')
    parser.add_argument('--topic', default=DEFAULT_TOPIC, help='第一轮的主题句')
    parser.add_argument('--follow-up', default=DEFAULT_FOLLOW_UP,
                        help='第二轮的追问句（必须带指代、单独看没有意义）')
    parser.add_argument('--keywords', default=','.join(DEFAULT_KEYWORDS),
                        help='判定「接上了」的主题关键词，逗号分隔')
    parser.add_argument('--attempts', type=int, default=1,
                        help='重试次数；改写算子是 LLM 有采样抖动，偶发失败可调大（默认 1，不替你重试）')
    args = parser.parse_args()

    web = args.web.rstrip('/')
    rkb = resolve_rkb(args.rkb).rstrip('/')
    keywords = [kw for kw in args.keywords.split(',') if kw]

    print(f'web={web}  RKB={rkb}')
    workflow = resolve_workflow(web, args.workflow)
    if not workflow:
        return 1

    print(f'\nT1 = {args.topic}\nT2 = {args.follow_up}\n')
    passed = True
    for attempt in range(1, args.attempts + 1):
        if args.attempts > 1:
            print(f'--- 第 {attempt}/{args.attempts} 次 ---')
        if not run_once(rkb, workflow, False, args.topic, args.follow_up, keywords):
            passed = False
        if not run_once(rkb, workflow, True, args.topic, args.follow_up, keywords):
            passed = False
        if passed:
            break  # 任一次全绿即通过（失败的那次若在更早轮次，输出里仍看得到）

    print('\n结论：', '✅ 多轮生效（同会话接上、新会话答非所问）' if passed
          else '❌ 见上面的两组对照（先看是「多轮没接上」还是「对照也接上了」）')
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
