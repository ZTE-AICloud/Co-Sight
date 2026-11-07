"""抽图端到端**快速**验收：提交 → 抽图 → 导入 → 回读，自带分阶段耗时账单。

覆盖 `POST /graph-extractions`（UI 真实路径）整条链：沙箱执行算子 → `read_outputs`
读出产出 → 打 zip → 导入图存储 → `/knowledge-bases/{id}/graph/query` 回读。对比之下
`verify-graph-extract-v2-diff.py` 只发不等、`verify-graph-import-e2e.py` 只覆盖导入半边。

用法（**容器内**，端口 8091 没发布到宿主）::

    docker cp tools/verify/verify-graph-extract-e2e.py <rkb>:/tmp/
    docker cp tools/verify/fixtures/graph-extract <rkb>:/tmp/fixtures/
    docker exec <rkb> python3 -u /tmp/verify-graph-extract-e2e.py [选项]

    --case fast|prof|wide|all   默认 fast（`all` = fast + prof；`wide` 只能显式指定）
    --operator / --schema-id    覆盖 case 的算子与 schema（变异/负向用，会另开一个 -variant 库）
    --no-reuse                  用唯一的库名**真的**新建一个库（对照组，量「类必须建」这条冷路径）
                                ⚠️ 会留下一个新库（跑完用 cleanup-probe-kbs.py 清）
                                ⚠️ 别指望它来量「复用省了多少」—— 那要看 `--no-reset-graph`：
                                   服务端是按**库名**复用的，同名的库只要零文件就一定会被复用，
                                   所以「复用 vs 不复用」在现实里对应的是「图库复位 vs 不动」，
                                   不是「换不换 KB」
    --reset-kb                  跑前把整库删掉（冷路径）
    --no-reset-graph            不清上一轮的实体/边，断言降级为增量
    --json                      额外打一行机器可读的账单
    --keep-files                跳过 finally 里的文件清理

## 为什么要有这个脚本（三条实测结论，别推翻它们）

一次 `-5` + `OntologyGraph` 抽图（提交→完成 16.4 秒）的阶段账单：

| 阶段 | 耗时 | 占比 |
|---|---|---|
| 建库建表 | 0.09s | 0.5% |
| 解析 corpus | 0.02s | 0.1% |
| 空档（切分完成 → 算子开始） | 4.25s | 26% |
| **算子本体（含全部 4 次 LLM 调用）** | **0.55s** | **3.3%** |
| **图存储 导入** | **10.48s** | **64%** |
| 收尾 | 0.06s | 0.4% |

1. **LLM 只占 3%，`mock LLM` 最多省 0.4 秒** —— 不要为提速去 mock LLM，
   那会把「整条链路通不通」这个唯一有价值的信号一起 mock 掉。
2. **导入耗时 ∝ schema 的类数×属性数，不 ∝ 实体数。** `create_schema_classes`
   （`graph_import_engine.py:167-187`）对每个类打一次 `_class_exists`、每个属性一次
   `_property_exists`、每个索引一次 `CREATE INDEX`（`graph/repository/graph_pg.py`），
   全是逐条 REST 往返。`OntologyGraph`（≈280 次往返）→ 10.48s；
   `-6` 自产的小 schema（≈60 次）→ 1.53s。**这 9 秒是选文档/选 schema 选出来的。**
3. **固定间隔轮询的「假延迟」很贵。** 老探针 5s 一轮，任务 16.4s 完成、探针 +20.1s
   才看见 —— 白吞 3.7 秒。这里改成 `POLL_INTERVAL`（0.3s）。

## 固定复用 KB（省的是 DDL 里「建」的那一半）

每 case 一个固定库名（`probe-graph-e2e-<case>`，命中 `cleanup-probe-kbs.py` 的 `probe%`
前缀）。复用前提是**同名且零文件**（`kbase_v2_service.py:182-190` 的 `_reuse_or_raise`），
所以每轮先把该库的文件行删掉。

⚠️ **不能走 update 端点**（`PUT /knowledge-bases/{kbId}/graph`）复用 —— 它在
`graph_extract_v2_api.py:458` 调 `_delete_graph_db`（`kbase_v2_service.py:341-355`）
把 `graph_<kbId>` 整个 drop，建类一分钱省不到。

⚠️ 复用**不是免费的**：`_class_exists`/`_property_exists` 的判存查询每次照打，
`ensure_index` 每次都发一次注定失败的 `CREATE INDEX`（靠异常文案 `'exists'` 兜住）。

## 断言（L1~L4 + 否决项）

- **L1 任务终态**：`status='SUCCESS'` **且 `progress==100`**。`progress==100` 是必需的
  —— v2 的算子阶段失败**不改任务行**（停在 RUNNING/50），这是那个缺陷模式的守卫。
- **L2 导入计数**：`COMPLETED`、`entity_total >= 1`、`success == total`、`failed == 0`、
  `failed_records` 空。`entity_total >= 1` 正好钉住「产出被读出」—— 读不到
  `entities.jsonl` 时 `_for_each_json_line` 当 0 条（`graph_import_engine.py:511-520`）。
- **L3 数据真进去了**：`/knowledge-bases/{id}/graph/query` 回读 `entity_num`；reset 生效时**精确等于**
  `entity_success`（`entity_num` 由 `graph_query_api.py:109-110` 现算，独立于导入引擎自述）。
- **L4 库落位**：`kb_kbase.status='5'`、`schema_id` 符合预期、`schema_obj` 非空。
- **否决项**：`failed_records` 含 `<post-import-verification>`（内容陈旧）。

**不敏感于 LLM 随机性**：一律 `>=` 不写 `==`（`-5`+`OntologyGraph` 是 13 实体/1 边、
`-6` 是 5 实体/4 边，同分支不同轮次也会变）；不断言 entity_type 名与属性值；
边允许为 0，但 `edge_failed == 0` 必须成立。

## 残留

跑完库里留：固定的 KB 若干、每轮一行 `graph_extract_task` + 一行 `graph_import_task`。
文件行在 `finally` 里删掉，**不会留任何新库**（中途失败也不留 —— 处理是 reset-then-run，
下一步跑会自愈）。`cleanup-probe-kbs.py` 仍能扫掉它。

## 明确不做

不 mock LLM · 不改生产代码 · 不碰 `backend/tests/`
· 不往 `graph_schema` 播种模板行 · 不新增后台常驻/不改 compose。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.request

sys.path.insert(0, '/app/src')
sys.path.insert(0, '/app')

RKB = 'http://127.0.0.1:8091/api/co-knowledge/v1'
HDRS = {'X-Emp-No': 'admin'}
BOUNDARY = '----graphexte2e'
LLM = 'deepseek-chat'
EMBEDDING = 'Qwen3-Embedding-0.6B'

POLL_INTERVAL = 0.3          # 老探针是 5s —— 固定间隔的「假延迟」实测能吞掉 3.7s
DEADLINE = 420               # 抽图逐 chunk 调 LLM，给足
KB_SETTLE_GRACE = 15         # 任务终态 → 库状态落 5 之间有个窗口（见 poll_until_terminal）
FIXTURE_DIR = os.environ.get('GRAPH_FIXTURE_DIR', '/tmp/fixtures')
LOG_DIR = os.environ.get('LOG_DIR') or '/data/rkb/logs'

# 算子的两版文件都叫 graph_extract.py（PVC 上专业/通用各一份），行号会变
# （:1287 专业 / :365 通用）—— 所以**按消息文本匹配，不能按 file:line 匹配**。
RE_OP_ENTRY = re.compile(r'>>Start to extract graph')
# ⚠️ 「算子说完」的文案**两个算子不一样**，只认一种就会有一个 case 永远取不到：
#    `-6`（通用）打 `>>Graph extraction completed. Processed N chunks, ...`
#    `-5`（专业）打 `>>Running time: 0.54, Total chunks: N, ...` / `>>End to extract graph`
RE_OP_DONE = re.compile(r'>>Graph extraction completed|>>Running time:|>>End to extract graph')
RE_OP_RUNTIME = re.compile(r'>>Running time: ([\d.]+)')
RE_CHILD_LOG = re.compile(r'^rkb-(\d{17})-\[(\d{6})\]\.log$')

# 子进程日志文件名里的 `[xxxxxx]` 是 **随机串不是 PID**（`logutil.py:_get_rand_str`），
# 所以归属只能靠内容里的 `kb_id=` 匹配。
# 见 docstring 的「固定复用 KB」与 README「抽图快速验收」一节。
CASES = {
    'fast': {
        'kb_name': 'probe-graph-e2e-fast',
        'operator_id': -6,
        'schema_id': None,              # 不传 → schema 由算子产出的 schema.json 兜底
        'expected_schema_id': 'General_Schema',
        'doc': 'mini-general.md',
        'note': '默认；小文档 + 小 schema，导入 ~1.5s',
    },
    'prof': {
        'kb_name': 'probe-graph-e2e-prof',
        'operator_id': -5,
        'schema_id': 'schema-001',      # graph_schema 表里已存在的行（只读引用，不播种）
        'expected_schema_id': 'schema-001',
        'doc': 'prof-people.md',
        'note': '-5 专业算子；schema-001 无 is_embedding 属性，绕开「embedding 属性必须非空」',
    },
    'wide': {
        'kb_name': 'probe-graph-e2e-wide',
        'operator_id': -5,
        'schema_id': 'OntologyGraph',
        'expected_schema_id': 'OntologyGraph',
        'doc': 'prof-ontology-battery.md',
        'note': '对照组（宽 schema）：导入 ~10.5s，只在需要覆盖宽 schema 时跑',
    },
}

failures = []


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def call(path, body=None, method='POST', timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(HDRS)
    if data is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(RKB + path, data=data or (b'' if method == 'POST' else None),
                                     method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b'{}')
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read() or b'{}')
        except ValueError:
            return {'_http': error.code}
    except Exception as error:                                      # noqa: BLE001
        return {'_err': f'{type(error).__name__}: {error}'}


def submit_extract(case, kb_name, doc_bytes, filename):
    """multipart：**文件部件必须在 `data` 之前**（否则一律报 JSON 格式错误）。"""
    payload = {'name': kb_name, 'description': '抽图快速验收靶子', 'category': 10,
               'props': {'embeddingModel': EMBEDDING},
               'operatorId': case['operator_id'], 'kwargs': {'llm': LLM},
               'fileFormat': 'md', 'regexList': None,
               # ⚠️ 必须带 coverFlag：同库同名文件已存在时重名检查会挡回 1001；
               #    带 coverFlag 才走覆盖路径（`_purge_old_file` + 重置旧行）。
               'coverFlag': True}
    if case['schema_id']:
        payload['schemaId'] = case['schema_id']
    head = (f'--{BOUNDARY}\r\n'
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f'Content-Type: text/markdown\r\n\r\n').encode()
    tail = (f'\r\n--{BOUNDARY}\r\nContent-Disposition: form-data; name="data"\r\n\r\n'
            f'{json.dumps(payload)}\r\n--{BOUNDARY}--\r\n').encode()
    request = urllib.request.Request(
        RKB + '/graph-extractions', data=head + doc_bytes + tail, method='POST',
        headers={**HDRS, 'Content-Type': f'multipart/form-data; boundary={BOUNDARY}'})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read() or b'{}')
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read() or b'{}')
        except ValueError:
            return {'_http': error.code}


def code_of(resp):
    """纯 REST：2xx 返回 '0000'；problem / 网络错误返回失败码。"""
    if not isinstance(resp, dict) or resp.get('_http') or resp.get('_err'):
        return 'http_error'
    if 'status' in resp and 'code' in resp:
        return str(resp.get('code'))
    return '0000'


def msg_of(resp):
    if not isinstance(resp, dict):
        return ''
    return str(resp.get('detail') or resp.get('_err') or '')


# ---------------------------------------------------------------------------
# 库状态（进程内直连，不走 HTTP）
# ---------------------------------------------------------------------------
def connection():
    from infrastructure.db.kb import connection as _conn
    return _conn()


def find_kb(name):
    from knowledge_base.repository import kbase as kbase_store
    rows = kbase_store.find_kbases_by_name(name, None)
    return rows[0]['kbase_id'] if rows else None


def file_rows(kb_id):
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT id FROM kb_directory WHERE kbase_id=%s AND type='file'",
                       (kb_id,))
        return [row[0] for row in cursor.fetchall()]


def sweep_files(kb_id):
    """把文件名下的文件行清零 —— 这是 `_reuse_or_raise` 放行的唯一前提。"""
    for file_id in file_rows(kb_id):
        call(f'/knowledge-bases/{kb_id}/documents/{file_id}', method='DELETE')
    from knowledge_base.repository import kbase as kbase_store
    remain = kbase_store.count_files(kb_id)
    if remain:
        raise AssertionError(f'复用前提不成立：库 {kb_id} 还有 {remain} 个文件')


def wipe_graph(kb_id):
    """复位上一轮的图数据：**drop 掉整个图谱库**（下轮导入自己重建）。

    ⚠️ 不能靠「UPSERT 会覆盖」省掉这步：`import_entities` 是
    `UPDATE ... UPSERT WHERE entity_id = ?`（`graph_import_engine.py:254-270`），
    而 entity_id 由 LLM 生成、跨轮不稳定 → 图只增不减 → 链路断了但库里还有上轮数据 = 假绿。

    ⚠️ **也**不能用 `DELETE EDGE E` / `DELETE VERTEX V` 只删数据。实测：

    | 复位方式 | 下一轮导入耗时 |
    |---|---|
    | `DELETE EDGE`+`DELETE VERTEX`（保留类） | **9.82s** |
    | drop 库（本轮） | ~1.7s |
    | 不复位但换新库 | ~1.7s |
    | 什么都不做 | ~1.6s |

    「只删记录」会把库留在一个让后续 DDL 慢 6 倍的状态（记录标记删除但索引/压实没跟上）。
    drop 重建反而更快，代价只是重跑一遍建类 —— 而那本来就只占零点几秒。

    返回 True 表示复位成功（可做精确断言），False 表示降级为增量断言。
    """
    from graph.repository import graph_pg
    dbname = graph_pg.graph_db_name(kb_id)
    client = graph_pg.new_client(dbname)
    try:
        if not graph_pg.is_database_exists(client):
            return True                       # 库还没有，天然干净
        graph_pg.drop_database(client, dbname)
        return True
    except Exception as error:                # noqa: BLE001 - 版本差异不该让验收 fail
        # ⚠️ 这族 EMException 的 `__str__` **只返回 err_code**（`KG008`），真正的原因在
        #    `args` 里 —— 只打 str() 会把图存储 的原始报错吞掉，排查时看不出所以然。
        #
        detail = f'{getattr(error, "err_code", type(error).__name__)} ' \
                 f'{" ".join(str(a) for a in getattr(error, "get_args", lambda: ())() )}'
        print(f'  [warn] 复位失败，降级为增量断言：{type(error).__name__}: {detail}')
        return False


def query_entity_num(kb_id):
    resp = call(f'/knowledge-bases/{kb_id}/graph/query', {'query_type': 'entity'})
    if code_of(resp) != '0000':
        return None, f"{code_of(resp)} {msg_of(resp)}"
    return (resp or {}).get('entity_num'), None


# ---------------------------------------------------------------------------
# 轮询 + 账单
# ---------------------------------------------------------------------------
def _parse(value):
    """DB 时间戳 → datetime。`graph_import_task` 那两列是 varchar（ISO 形状）。"""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(str(value))


def _iso(value):
    value = _parse(value)
    return value.isoformat(sep=' ') if value else None


def newest_task_id(kb_id):
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute('SELECT id FROM graph_extract_task WHERE kb_id=%s '
                       'ORDER BY created_at DESC LIMIT 1', (kb_id,))
        row = cursor.fetchone()
        return row[0] if row else None


def snapshot_task(task_id):
    """一条 SQL 拿全：任务行 + 库构建状态 + 最近一条导入任务。"""
    sql = """
        SELECT t.status, t.progress, t.error_message, t.created_at, t.start_time,
               t.finish_time, t.schema_id,
               k.status AS kb_status, k.process AS kb_process, k.schema_obj,
               i.status AS imp_status, i.created_at AS imp_create, i.updated_at AS imp_update,
               i.entity_total, i.entity_success, i.entity_failed,
               i.edge_total, i.edge_success, i.edge_failed,
               i.failed_records, i.error_message AS imp_error
        FROM graph_extract_task t
        LEFT JOIN kb_kbase k ON k.kbase_id = t.kb_id
        LEFT JOIN LATERAL (
            SELECT * FROM graph_import_task WHERE kb_id = 'graph_' || t.kb_id
            ORDER BY created_at DESC LIMIT 1) i ON TRUE
        WHERE t.id = %s
    """
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(sql, (task_id,))
        names = [d[0] for d in cursor.description]
        row = cursor.fetchone()
    return dict(zip(names, row)) if row else None


def scan_child_log(kb_id, not_before):
    """子进程日志：补 PG 拿不到的两样（算子入口、算子自报耗时）。

    文件名时间戳是该进程**日志 handler 创建时刻**（≈ 进程早期），不是 PID。
    找不到就返回空 dict —— **不影响退出码**。
    """
    marks = {}
    try:
        entries = sorted(os.listdir(LOG_DIR))
    except OSError:
        return marks
    best = None
    for name in entries:
        match = RE_CHILD_LOG.match(name)
        if not match:
            continue
        born = dt.datetime.strptime(match.group(1), '%Y%m%d%H%M%S%f')
        if born < not_before:
            continue
        path = os.path.join(LOG_DIR, name)
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as handle:
                head = handle.read(512 * 1024)
        except OSError:
            continue
        # ⚠️ 归属判据是**裸 kbId 子串**：真实写法是 `kwargs={... 'kb_id': '<uuid>' ...}`
        #    （带引号带空格），写成 `kb_id=<uuid>` 会一条都匹配不上。
        #    注意 kbId 现在是**固定复用**的，所以历史子进程日志也含同一个 id
        #    —— 靠文件名时间戳的 `not_before` 卡住，再靠「含算子入口」挑出本轮那个。
        if kb_id not in head or not RE_OP_ENTRY.search(head):
            continue
        if best is None or born > best[0]:
            best = (born, head)
    if best is None:
        return marks
    born, head = best
    marks['t_child_born'] = born
    for line in head.splitlines():
        stamp = _line_ts(line)
        if RE_OP_ENTRY.search(line) and 't_op_entry' not in marks:
            marks['t_op_entry'] = stamp
        elif RE_OP_DONE.search(line) and 't_op_done' not in marks:
            marks['t_op_done'] = stamp
        runtime = RE_OP_RUNTIME.search(line)
        if runtime:
            marks['op_self_runtime'] = float(runtime.group(1))
    return marks


def _line_ts(line):
    match = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\]', line)
    return dt.datetime.fromisoformat(match.group(1)) if match else None


def poll_until_terminal(task_id, t_wall_start):
    """0.3s 一轮。返回 (快照, 库状态变化记录, 探针看见终态的墙钟)。

    ⚠️ **必须等两个条件**：任务行到终态 **且** 库状态落到 5（PENDING）。
    产品代码里 `graph_extract_v2_service.py:169`（写任务 completed）**早于**
    `:267-273` 的 `_settle_kbase_status`（把库置 5）—— 只等任务行会在两者之间
    的窗口里返回，此时 `/knowledge-bases/{id}/graph/query` 会回 `0005 Knowledge graph is being built`，
    断言随机变红。（这个窗口本身是产品侧的一个观察，见 README。）

    FAIL 终态不等库状态（失败时库状态可能永远不落 5）。
    """
    transitions = {}
    deadline = time.monotonic() + DEADLINE
    last_line = None
    settle_deadline = None            # 任务终态后，再给库状态多久落 5
    while time.monotonic() < deadline:
        snap = snapshot_task(task_id)
        if snap:
            key = f"{snap.get('kb_status')}/{snap.get('kb_process')}"
            transitions.setdefault(key, time.monotonic() - t_wall_start)
            line = f"{snap.get('status')}/{snap.get('progress')} kb={key}"
            if line != last_line:
                print(f'  [+{time.monotonic() - t_wall_start:5.2f}s] {line}')
                last_line = line
            if snap.get('status') in ('SUCCESS', 'FAIL'):
                done = (snap.get('status') == 'FAIL'          # 失败时库状态可能永远不落 5
                        or str(snap.get('kb_status')) == '5')
                if settle_deadline is None:
                    settle_deadline = time.monotonic() + KB_SETTLE_GRACE
                if done or time.monotonic() > settle_deadline:
                    return snap, transitions, time.monotonic() - t_wall_start
        time.sleep(POLL_INTERVAL)
    return None, transitions, time.monotonic() - t_wall_start


def print_bill(case_name, t0, snap, transitions, seen, marks, wall_total):
    """分阶段账单。**必须区分标注精度** —— 轮询是寄存器快照，中间态会被跳过。"""
    created = _parse(snap.get('created_at'))
    started = _parse(snap.get('start_time'))
    finished = _parse(snap.get('finish_time'))
    imp_create = _parse(snap.get('imp_create'))
    imp_update = _parse(snap.get('imp_update'))
    child_born = marks.get('t_child_born')
    op_entry = marks.get('t_op_entry')

    def delta(a, b):
        return f'{(b - a).total_seconds():6.2f}' if (a and b) else '    --'

    def secs(value):
        return f'{value:6.2f}' if value is not None else '    --'

    print('\n=== 阶段账单（秒）===')
    print(f'  提交 → 任务行落库              {delta(dt.datetime.fromtimestamp(t0), created)}'
          '  [PG created_at]')
    print(f'    ├ 切分完成                   {secs(transitions.get("2/100", transitions.get("2/20")))}'
          f'  [PG 轮询，误差 ≤{POLL_INTERVAL}s]')
    print(f'    ├ 算子阶段开始               {secs(transitions.get("3/1"))}  [PG 轮询]')
    if child_born:
        print(f'    │   └ 沙箱子进程诞生          {child_born.strftime("%H:%M:%S.%f")[:-3]}'
              '  [日志文件名 ≈ 进程早期]')
        print(f'    │       └ 空档②（诞生→入口） {delta(child_born, op_entry)}  [日志，ms 级]')
    print(f'    │   └ 算子本体               {delta(op_entry, marks.get("t_op_done"))}'
          f'  [日志，ms 级；算子自报 {marks.get("op_self_runtime") or "--"}]')
    print(f'    ├ 导入阶段开始               {secs(transitions.get("4/10"))}  [PG 轮询]')
    print(f'    │   └ 导入（精确）           {delta(imp_create, imp_update)}'
          '  [PG created_at → updated_at]')
    print(f'    └ 任务终态                   {secs(transitions.get("5/0"))}  [PG 轮询]')
    # 探针「看见」终态墙钟 = t0 + seen；与 DB 的 finish_time 之差就是轮询吞掉的假延迟
    observed = dt.datetime.fromtimestamp(t0 + seen)
    false_lag = (observed - finished).total_seconds() if finished else None
    print(f'  探针看到终态（假延迟）          {secs(false_lag)}  [墙钟 − finish_time]')
    print('  ' + '-' * 44)
    total = (finished - created).total_seconds() if (created and finished) else None
    print(f'  合计 {secs(total)}   /   探针观察到 {wall_total:6.2f}')
    print('  ※ 上一列标 [PG 轮询] 的误差 ≤%.1fs；[日志] 为 ms 级；"--" = 未取到（不影响退出码）'
          % POLL_INTERVAL)
    print(f'  ※ DB 的 start_time={_iso(started)} 实测落在导入阶段附近，**不是**任务开始时刻 —— '
          '别拿它算排队时间')
    return {'case': case_name,
            'total_s': round(total, 2) if total is not None else None,
            'wall_s': round(wall_total, 2),
            'false_lag_s': round(false_lag, 2) if false_lag is not None else None,
            'import_s': round((imp_update - imp_create).total_seconds(), 2)
            if (imp_create and imp_update) else None,
            'op_self_runtime_s': marks.get('op_self_runtime')}


# ---------------------------------------------------------------------------
# 断言
# ---------------------------------------------------------------------------
def check(label, ok, detail=''):
    if ok:
        print(f'  ok    {label}')
        return True
    failures.append(label)
    print(f'FAIL  {label}{"  " + str(detail) if detail else ""}')
    return False


def graph_retrieve(kb_id):
    """``POST /api/co-knowledge/v1/retrieval/graph``：图谱检索索引是否真的能命中。

    导入后把实体/边/切片向量化写 ``graph_<uuid>_vector``；缺这条链时这里
    永远返回空（``relation does not exist`` 被吞成 ``[]``）。
    """
    # ``bases`` 传的是**画布/检索侧的库名** ``graph_<uuid>``（不是裸 uuid）——
    # ``_build_retrieve_sql`` 拼的是 ``kb_index.<base>_vector``，
    # 库名固定是 ``graph_<uuid>``。
    body = {'query': '测试', 'embedding': EMBEDDING, 'bases': [f'graph_{kb_id}'],
            'seed_k': 5, 'depth': 1}
    request = urllib.request.Request(
        RKB + '/retrieval/graph', data=json.dumps(body).encode(), method='POST',
        headers={**HDRS, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read() or b'{}')
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read() or b'{}')
        except ValueError:
            return {'_http': error.code}


def assert_case(case, snap, entity_num, entity_num_err, reset_ok):
    print('\n=== 断言 ===')
    # L1
    check('L1 任务终态 SUCCESS|100',
          snap.get('status') == 'SUCCESS' and snap.get('progress') == 100,
          f"实际 {snap.get('status')}|{snap.get('progress')} {snap.get('error_message') or ''}")
    # L2
    imp_status = snap.get('imp_status')
    check('L2 导入 COMPLETED', imp_status == 'COMPLETED', f'实际 {imp_status} {snap.get("imp_error") or ""}')
    total, success, failed = snap.get('entity_total'), snap.get('entity_success'), snap.get('entity_failed')
    check('L2 实体 ≥1 且全成功', bool(total) and total >= 1 and success == total and failed == 0,
          f'total={total} success={success} failed={failed}')
    edge_failed = snap.get('edge_failed')
    check('L2 边零失败（边数允许为 0）', edge_failed == 0, f'edge_failed={edge_failed}')
    # 否决项
    records = snap.get('failed_records')
    check('否决 failed_records 无陈旧标记',
          not records or '<post-import-verification>' not in str(records), f'{records}')
    # L3
    if entity_num_err:
        check('L3 回读 entity_num', False, entity_num_err)
    elif reset_ok:
        check('L3 回读 entity_num == 本轮导入成功数', entity_num == success,
              f'回读 {entity_num} != 导入 {success}')
    else:
        check('L3 回读 entity_num ≥ 1（增量口径）', bool(entity_num) and entity_num >= 1, f'{entity_num}')
    # L4
    check('L4 库状态 PENDING(5)', str(snap.get('kb_status')) == '5', f"实际 {snap.get('kb_status')}")
    check('L4 schema_id 符合预期', snap.get('schema_id') == case['expected_schema_id'],
          f"实际 {snap.get('schema_id')}，期望 {case['expected_schema_id']}")
    check('L4 schema_obj 非空', bool(snap.get('schema_obj')) and str(snap.get('schema_obj')) not in ('{}', ''))


# ---------------------------------------------------------------------------
# 单个 case
# ---------------------------------------------------------------------------
def run_case(case_name, case, args):
    doc_path = os.path.join(args.fixture_dir, case['doc'])
    if not os.path.exists(doc_path):
        print(f'FAIL  缺少 fixture {doc_path}（见 docstring 的 --fixture-dir）')
        failures.append(f'{case_name}: fixture 缺失')
        return None
    with open(doc_path, 'rb') as handle:
        doc_bytes = handle.read()

    print(f'\n{"=" * 72}\n=== case {case_name}：{case["note"]}\n'
          f'    operator={case["operator_id"]} schemaId={case["schema_id"] or "(不传)"} '
          f'文档={case["doc"]}({len(doc_bytes)}B)')

    # ⚠️ **`--no-reuse` 必须换库名，不能只跳过客户端的查找。**
    #    服务端 `_reuse_or_raise`（`kbase_v2_service.py:182-190`）是**按名字复用**的
    #    （前提是零文件），所以只跳过客户端查找仍会拿到同一个 kbId；更糟的是
    #    kb_id 为 None 时下面会连带跳过 `wipe_graph` → 图库原封不动、类都在，
    #    于是「新建库」这个对照组实际是「复用 + 不清图」，标签还是假的。
    #    （「新建库」若实际复用了旧库，日志里 CREATE CLASS 会是 0 条。）
    previous_kb = find_kb(case['kb_name'])
    if args.no_reuse:
        # ⚠️ 库名有校验：**2~30 字符**，只允许英文/数字/下划线/中文/点/短横/空格，且不能全空格
        #    （实测 `probe-graph-e2e-fast-1791965578` 31 字符被 0004 拒掉）。
        #    所以用短前缀 + 秒级时间戳后 6 位，并留一条长度断言免得再踩。
        kb_name = f'probe-{case_name}-{int(time.time()) % 1000000:06d}'
        assert 2 <= len(kb_name) <= 30, f'生成的库名长度越界: {kb_name!r} ({len(kb_name)})'
        kb_id = None
        print(f'  KB: **新建**（--no-reuse → 库名唯一 {kb_name}）')
        print('      ⚠️ 会留下一个新库，跑完可用 cleanup-probe-kbs.py 清（名字命中 probe% 前缀）')
    else:
        kb_name = case['kb_name']
        kb_id = None if args.reset_kb else previous_kb
        if kb_id and args.reset_kb:
            print(f'  --reset-kb：删除整库 {kb_id}')
            call(f'/knowledge-bases/{kb_id}', method='DELETE')
            kb_id = None
        if kb_id:
            print(f'  KB 复用: 是 ({kb_id})')
            sweep_files(kb_id)
        else:
            print('  KB 复用: 否（首次运行，本轮新建）')

    reset_ok = True
    if kb_id:
        reset_ok = wipe_graph(kb_id) if not args.no_reset_graph else False
    baseline_task = newest_task_id(kb_id) if kb_id else None

    t0 = time.time()
    t_wall = time.monotonic()
    print('  → 提交（multipart：文件部件在 data 之前）')
    resp = submit_extract(case, kb_name, doc_bytes, case['doc'])
    if code_of(resp) != '0000':
        check(f'{case_name} 提交成功', False, f'{code_of(resp)} {msg_of(resp)}')
        return None
    new_kb = (resp or {}).get('id')
    # 两种模式各证各的：复用要证「拿到的是同一个」，--no-reuse 要证「拿到的是新的」
    if args.no_reuse:
        if new_kb == previous_kb:
            check('--no-reuse 自证（kbId 必须是新的）', False,
                  f'仍拿到上一个库 {previous_kb} —— 库名没换干净')
            return None
    elif kb_id and new_kb != kb_id:
        check('复用自证（kbId 与上轮一致）', False, f'上一轮 {kb_id}，本轮 {new_kb}')
        return None
    kb_id = new_kb
    print(f'  kbId = {kb_id}{"（复用已自证）" if baseline_task else "（新建已自证）"}')

    task_id = None
    while task_id is None:
        task_id = newest_task_id(kb_id)
        if task_id == baseline_task:
            task_id = None
            time.sleep(POLL_INTERVAL)
        if time.monotonic() - t_wall > 60:
            check(f'{case_name} 任务行落库', False, '60s 内没等到新任务行')
            return None

    snap, transitions, seen = poll_until_terminal(task_id, t_wall)
    if snap is None:
        check(f'{case_name} 终态', False, f'{DEADLINE}s 内未到终态')
        return None

    wall_total = time.time() - t0
    marks = {} if args.no_log_scan else scan_child_log(kb_id, dt.datetime.fromtimestamp(t0))
    entity_num, entity_num_err = query_entity_num(kb_id)

    assert_case(case, snap, entity_num, entity_num_err, reset_ok and not args.no_reset_graph)

    # L5 图谱检索索引（导入后写 graph_<uuid>_vector；必须能命中种子与切片）
    try:
        retrieve = graph_retrieve(kb_id)
        base_results = (retrieve.get('base_results') or [])
        first = base_results[0] if base_results else {}
        check('L5 图谱检索命中种子实体', bool(first.get('seed_entity_ids')),
              f"seeds={first.get('seed_entity_ids')} err={first.get('error')}")
        check('L5 图谱检索命中切片', bool(first.get('chunk_count')),
              f"chunks={first.get('chunk_count')}")
    except Exception as error:                                       # noqa: BLE001
        check('L5 图谱检索请求', False, str(error))

    bill = print_bill(case_name, t0, snap, transitions, seen, marks, wall_total)

    try:
        if not args.keep_files:
            sweep_files(kb_id)
    except Exception as error:                                       # noqa: BLE001
        print(f'  [warn] 收尾清文件失败（下一轮自愈）：{error}')
    return bill


def main():
    parser = argparse.ArgumentParser(description='抽图端到端快速验收')
    parser.add_argument('--case', default='fast')
    parser.add_argument('--operator', type=int, help='覆盖 case 的 operatorId（变体/负向用）')
    parser.add_argument('--schema-id', help='覆盖 case 的 schemaId（变体/负向用）')
    parser.add_argument('--no-reuse', action='store_true',
                        help='用唯一的库名**真的**新建一个库（对照组；会留下一个新库）')
    parser.add_argument('--reset-kb', action='store_true')
    parser.add_argument('--no-reset-graph', action='store_true')
    parser.add_argument('--no-log-scan', action='store_true')
    parser.add_argument('--keep-files', action='store_true')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--fixture-dir', default=FIXTURE_DIR)
    args = parser.parse_args()

    # `--operator` / `--schema-id` 覆盖：给变异/负向用例用（例如拿 `no_such_schema`
    # 确认提交层真的会红、或拿 `-5` 试 `General_Schema` 确认判据不是万能放行）。
    if args.case in CASES and (args.operator is not None or args.schema_id is not None):
        override = dict(CASES[args.case])
        if args.operator is not None:
            override['operator_id'] = args.operator
        if args.schema_id is not None:
            override['schema_id'] = args.schema_id
            override['expected_schema_id'] = args.schema_id
        override['kb_name'] = f'{override["kb_name"]}-variant'
        CASES[args.case] = override

    if args.case == 'all':
        names = ['fast', 'prof']
    elif args.case in CASES:
        names = [args.case]
    else:
        print(f'未知 case {args.case}；可选 {"|".join(CASES)}|all')
        return 2

    bills = []
    for name in names:
        try:
            bill = run_case(name, CASES[name], args)
        except Exception as error:                                   # noqa: BLE001
            # 不中断后续 case（--case all 时一个炸掉不该让另一个也跑不了），
            # 但要打全栈 —— 静默吞掉异常会让「脚本自己有 bug」伪装成「用例没过」。
            failures.append(f'{name}: {type(error).__name__}: {error}')
            print(f'FAIL  {name} 异常：{type(error).__name__}: {error}')
            traceback.print_exc()
            bill = None
        if bill:
            bills.append(bill)

    if args.json:
        print('\n' + json.dumps(bills, ensure_ascii=False))
    print(f'\n=== {"全部通过" if not failures else f"{len(failures)} 项未通过"} ===')
    for item in failures:
        print('  -', item)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
