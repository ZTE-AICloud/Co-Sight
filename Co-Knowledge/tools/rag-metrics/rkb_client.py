"""RKB HTTP 客户端（评测专用）。

只封装评测需要的路径：建库 / 上传容器文件 / 手工加切片 / 列切片 / 检索 / 删库。
不碰产品内部实现；所有请求都走对外唯一前缀 ``/api/co-knowledge/v1``。

为什么用 ``/chunk/add`` 而不是文件上传流水线：
* DuRetrieval 的评估单元是 **passage**，文件上传会按 512 字重新切片，
  一个 chunk 可能装下多条 passage，passage 级 Recall/NDCG 就失去意义；
* ``/chunk/add`` 是产品自己的「手工切片」能力，仍然走真实 embedding、
  真实向量表、真实 ES 与真实检索路径，只是把「切片」这个变量固定成 1:1。
* embedding 用 ``content``（干净正文），展示/引用用 ``supplement``（带 pid 标记）——
  实测向量路返回 supplement、关键词路返回 content，两边都能映射回 passage。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

import requests

DEFAULT_BASE = 'http://127.0.0.1/api/co-knowledge/v1'
EMBEDDING_MODEL = 'Qwen3-Embedding-0.6B'
# 默认 AUTH_MODE=local：评测客户端要自己登录（见 _login）。
DEFAULT_USERNAME = os.environ.get('RKB_USERNAME', 'admin')
DEFAULT_PASSWORD = os.environ.get('RKB_PASSWORD', 'admin')

_MARKER = '【DURET-{pid}】'


class RkbError(RuntimeError):
    pass


class RkbClient:
    def __init__(self, base_url: str = DEFAULT_BASE, timeout: int = 120,
                 username: str = DEFAULT_USERNAME,
                 password: str = DEFAULT_PASSWORD):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.username = username
        self.password = password
        self._local = threading.local()

    def _session(self) -> requests.Session:
        """每线程一个 Session：requests.Session 的文档不保证跨线程安全。"""
        session = getattr(self._local, 'session', None)
        if session is None:
            session = requests.Session()
            session.headers.update({
                'X-Emp-No': 'admin',
                'Accept-Language': 'zh-CN',
                # CSRF 纵深：带 Cookie 的 unsafe 请求要求 Origin 的 host 等于 Host。
                # 明文脚本没有浏览器 Origin，得自己补上（端口回退见 _login）。
                'Origin': self._origin(),
            })
            self._login(session)
            self._local.session = session
        return session

    def _origin(self, with_port: bool = True) -> str:
        parts = urlsplit(self.base_url)
        host = parts.netloc if with_port else parts.hostname
        return f'{parts.scheme}://{host}'

    @staticmethod
    def _is_csrf_rejected(response: requests.Response) -> bool:
        try:
            return (response.json() or {}).get('code') == 'csrf_rejected'
        except ValueError:
            return 'csrf_rejected' in (response.text or '')

    def _post_login(self, session: requests.Session, origin: str) -> requests.Response:
        return session.post(
            f'{self.base_url}/auth/login',
            json={'username': self.username, 'password': self.password},
            headers={'Origin': origin},
            timeout=self.timeout)

    def _login(self, session: requests.Session) -> None:
        """登录拿会话 Cookie；部署没有本地账号体系时静默跳过。

        三种「不需要登录」的部署：端点不存在（404/405）、``AUTH_MODE`` 不是
        ``local``（409 ``auth_not_enabled``）。后者是当前构建的常态 ——
        ``/auth/login`` 总是注册，非 local 模式返回 409。

        ``Origin`` 还要兼容反向代理：自带 nginx 用 ``Host $host``（剥掉端口），
        带端口的 Origin 会被 CSRF 拒成 403。遇到 ``csrf_rejected`` 时用 host-only
        再试一次，成功则把 Session 的 Origin 固定成该形式 —— 后续 unsafe 请求
        必须用同一个 host 才能通过校验。

        只在本线程的新 Session 上调用一次。失败即抛，不重试 —— 登录失败重试会
        触发服务端的失败计数（5 次/15 分钟）。
        """
        origin = self._origin()
        response = self._post_login(session, origin)
        if response.status_code == 403 and self._is_csrf_rejected(response):
            retry_origin = self._origin(with_port=False)
            if retry_origin != origin:
                response = self._post_login(session, retry_origin)
                if response.status_code == 200:
                    session.headers['Origin'] = retry_origin
        if response.status_code in (404, 405, 409):
            return
        if response.status_code != 200:
            raise RkbError(
                f'登录失败 HTTP {response.status_code}: {response.text[:200]}')
        if not response.cookies.get('ragstudio_session'):
            # 接口存在但没下发会话 Cookie：后续请求会 401，尽早失败。
            raise RkbError(f'登录响应未下发会话 Cookie: {response.text[:200]}')
        if self.base_url.startswith('http://') and 'secure' in (
                response.headers.get('Set-Cookie') or '').lower():
            raise RkbError(
                '会话 Cookie 带 Secure，但 base_url 是 http：requests 不会回传 Cookie；'
                '请改用 https，或把 RKB_AUTH_COOKIE_SECURE 设为 false')

    # ------------------------------------------------------------------
    # 底层
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, *, json_body: Any = None,
                 files: Any = None, data: Any = None, retries: int = 3) -> Any:
        url = f'{self.base_url}{path}'
        last_error: Optional[Exception] = None
        relogin_allowed = True
        for attempt in range(1, retries + 1):
            try:
                response = self._session().request(
                    method, url, json=json_body, files=files, data=data,
                    timeout=self.timeout)
                if (response.status_code == 401 and relogin_allowed
                        and attempt < retries):
                    # 会话过期/被吊销：丢掉线程 Session，下一次循环重新登录再试一次。
                    # 只放行一次，避免口令错误时反复登录触发服务端的失败计数。
                    relogin_allowed = False
                    self._local.session = None
                    continue
                text = response.text
                try:
                    payload = json.loads(text) if text else None
                except ValueError:
                    payload = None
                if response.status_code < 200 or response.status_code >= 300:
                    raise RkbError(f'HTTP {response.status_code} {method} {path}: {text[:300]}')
                if payload is None:
                    # 2xx 但正文不是 JSON（代理登录页、网关错误页）：不能当成「空结果」，
                    # 否则整轮评测会静默变成 0 分。
                    if text.strip():
                        raise RkbError(
                            f'非 JSON 响应 {method} {path}: {text[:200]}')
                    return None
                # 纯 JSON：非 2xx 已在上面抛出，成功体就是 payload
                return payload
            except (requests.RequestException, RkbError) as error:
                last_error = error
                message = str(error)
                # 只重试「服务端明确失败」的 0001/5xx（连接池耗尽等，尚未写入）。
                # 超时/连接错误可能已经在服务端提交，POST 重试会造重复行 —— 不重试，
                # 缺的切片交给 repair_parts.py 按正文对账。
                retryable = (isinstance(error, RkbError)
                             and 'HTTP 5' in message)
                if attempt == retries or not retryable:
                    break
                time.sleep(min(2 ** attempt, 8))
        raise RkbError(f'{method} {path} failed after {retries} tries: {last_error}')

    # ------------------------------------------------------------------
    # 知识库
    # ------------------------------------------------------------------

    def health(self) -> str:
        """全栈唯一健康端点 ``<prefix>/health``（纯文本 ``ok``）。"""
        response = self._session().request(
            'GET', f'{self.base_url}/health', timeout=self.timeout)
        text = response.text.strip()
        if response.status_code != 200 or text != 'ok':
            raise RkbError(f'health failed: HTTP {response.status_code} {text[:200]}')
        return text

    def list_kbs(self) -> List[Dict[str, Any]]:
        result = self._request(
            'GET', '/knowledge-bases?page=1&size=500&keyword=&categories=1,10') or {}
        # API 2.0 的分页字段是 ``items``；``data`` 是一代接口的遗留写法
        return result.get('items') or result.get('data') or []

    def find_kb(self, name: str) -> Optional[Dict[str, Any]]:
        for row in self.list_kbs():
            if row.get('name') == name:
                return row
        return None

    def get_kb(self, kb_id: str) -> Dict[str, Any]:
        """列表接口的 embeddingModel 恒为 null；详情接口才有真实值。"""
        return self._request('GET', f'/knowledge-bases/{kb_id}') or {}

    def create_kb(self, name: str, embedding_model: str = EMBEDDING_MODEL,
                  description: str = 'RAG retrieval metrics') -> Dict[str, Any]:
        return self._request('POST', '/knowledge-bases', json_body={
            'name': name,
            'description': description,
            'props': {'embeddingModel': embedding_model},
        })

    def ensure_kb(self, name: str, embedding_model: str = EMBEDDING_MODEL) -> Dict[str, Any]:
        existing = self.find_kb(name)
        if existing:
            detail = self.get_kb(existing['id'])
            actual = detail.get('embeddingModel')
            if actual and embedding_model and actual != embedding_model:
                raise RkbError(
                    f'KB {existing["id"]} 的 embedding 模型是 {actual}，'
                    f'不是期望的 {embedding_model}；拒绝混用')
            return detail
        return self.create_kb(name, embedding_model)

    def delete_kb(self, kb_id: str) -> Any:
        return self._request('DELETE', f'/knowledge-bases/{kb_id}')

    def default_directory(self, kb_id: str) -> str:
        rows = self._request('GET', f'/knowledge-bases/{kb_id}/directories?type=folder&sort=true') or []
        for row in rows:
            if row.get('id'):
                return row['id']
        raise RkbError(f'知识库 {kb_id} 没有默认目录')

    def list_files(self, kb_id: str) -> List[Dict[str, Any]]:
        page = self._request(
            'GET', f'/knowledge-bases/{kb_id}/documents?page=1&size=100') or {}
        # API 2.0 的分页字段是 ``items``；``data`` 是一代接口的遗留写法
        return list(page.get('items') or page.get('data') or [])

    # ------------------------------------------------------------------
    # 文件 / 切片
    # ------------------------------------------------------------------

    def delete_file(self, kb_id: str, file_id: str) -> Any:
        return self._request('DELETE', f'/knowledge-bases/{kb_id}/documents/{file_id}')

    def upload_container(self, kb_id: str, directory_id: str, filename: str,
                         content: str, file_format: str = 'md',
                         wait_timeout: int = 120) -> str:
        """上传一个「容器文件」；只为拿到 fileId 承载手工切片。"""
        metadata = {
            'kType': 'document',
            'directoryId': directory_id,
            'coverFlag': True,
            'splitType': 'system',
            'parseOperator': {},
            'splitOperator': {
                file_format: {
                    'operatorId': -1,
                    'fileFormat': file_format,
                    'args': [
                        {'argName': 'maxWordCount', 'argType': 'int', 'defaultValue': 512},
                        {'argName': 'overlap', 'argType': 'int', 'defaultValue': 128},
                    ],
                },
            },
        }
        payload = self._request(
            'POST', f'/knowledge-bases/{kb_id}/documents',
            files={'files': (filename, content.encode('utf-8'), 'text/markdown')},
            data={'metadata': json.dumps(metadata, ensure_ascii=False)},
            retries=2,
        )
        file_id = (payload or {}).get(filename)
        if not file_id:
            raise RkbError(f'上传响应里没有 {filename}: {payload}')
        self.wait_for_file(kb_id, filename, wait_timeout)
        return file_id

    def upload_document(self, kb_id: str, directory_id: str, path: str,
                        wait_timeout: int = 600) -> str:
        """上传**真实文件**，走产品的解析 + 切分流水线（评估切分本身时用）。

        与 :meth:`upload_container` 的区别：那个把正文当 markdown 容器文件传，
        切片内容完全由调用方给定；这个传原始字节，切分结果由产品决定。
        """
        name = os.path.basename(path)
        file_format = name.rsplit('.', 1)[-1].lower()
        metadata = {
            'kType': 'document',
            'directoryId': directory_id,
            'coverFlag': True,
            'splitType': 'system',
            'parseOperator': {},
            'splitOperator': {file_format: {
                'operatorId': -1,
                'fileFormat': file_format,
                'args': [
                    {'argName': 'maxWordCount', 'argType': 'int', 'defaultValue': 512},
                    {'argName': 'overlap', 'argType': 'int', 'defaultValue': 128},
                ],
            }},
        }
        with open(path, 'rb') as handle:
            content = handle.read()
        payload = self._request(
            'POST', f'/knowledge-bases/{kb_id}/documents',
            files={'files': (name, content, 'application/octet-stream')},
            data={'metadata': json.dumps(metadata, ensure_ascii=False)},
        )
        file_id = (payload or {}).get(name)
        if not file_id:
            raise RkbError(f'上传响应里没有 {name}: {payload}')
        self.wait_for_file(kb_id, name, wait_timeout)
        return file_id

    def wait_for_file(self, kb_id: str, filename: str, timeout: int = 120) -> None:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            page = self._request(
                'GET', f'/knowledge-bases/{kb_id}/documents?page=1&size=100')
            for row in (page or {}).get('items') or (page or {}).get('data') or []:
                if row.get('title') == filename:
                    last = row
                    if row.get('status') == 1:
                        return
                    if row.get('status') == 2:
                        raise RkbError(
                            f'容器文件导入失败: {filename} '
                            f'{row.get("failReason") or row.get("errorMsg") or ""}')
            time.sleep(1)
        raise RkbError(f'容器文件 {filename} 未在 {timeout}s 内就绪: {last}')

    def add_chunk(self, kb_id: str, file_id: str, content: str,
                  supplement: Optional[str] = None) -> None:
        # 只对 0001/5xx（连接池耗尽等，尚未写入）重试；读超时不会被重试
        # （POST 非幂等，可能已提交）。缺的切片交给 repair_parts.py 按正文对账。
        self._request(
            'POST', f'/knowledge-bases/{kb_id}/chunks',
            json_body={'documentId': file_id, 'content': content,
                       'supplement': supplement if supplement is not None else content},
            retries=3)

    def list_chunks(self, kb_id: str, page_size: int = 500,
                    file_id: Optional[str] = None) -> Iterable[Dict[str, Any]]:
        page = 1
        while True:
            if file_id:
                payload = self._request(
                    'GET', f'/knowledge-bases/{kb_id}/documents/{file_id}/chunks'
                           f'?page={page}&size={page_size}') or {}
                rows = payload.get('items') or []
                total = payload.get('total') or 0
            else:
                payload = self._request(
                    'GET', f'/knowledge-bases/{kb_id}/chunks?page={page}&size={page_size}') or {}
                rows = payload.get('items') or []
                total = payload.get('total') or 0
            for row in rows:
                yield row
            if page * page_size >= total or not rows:
                break
            page += 1

    # 注：不提供「删除容器切片」的便捷方法。实测 `/chunk/delete` 会留下空正文的
    # 孤儿向量行；评测里保留容器切片、按「非语料、非相关」占位更安全。

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def retrieve(self, kb_id: str, question: str, retrieve_type: int,
                 top_k: int = 80, score_threshold: float = 0.0) -> List[Dict[str, Any]]:
        """返回扁平后的 docs，保持产品返回顺序。"""
        groups = self._request('POST', '/retrieval', json_body={
            'question': question,
            'type': retrieve_type,
            'bases': [{
                'baseList': [f'doc_{kb_id}'],
                'priority': 0,
                'top_k': top_k,
                'score_threshold': score_threshold,
            }],
        })
        docs: List[Dict[str, Any]] = []
        for group in groups or []:
            docs.extend(group.get('docs') or [])
        return docs


def marker(pid: str) -> str:
    return _MARKER.format(pid=pid)


def display_text(pid: str, text: str) -> str:
    """写入 chunk 表 / 向量路返回的展示文本。"""
    return f'{marker(pid)}\n{text}'
