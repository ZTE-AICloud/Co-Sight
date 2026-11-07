"""请求头上下文（精简版）。

从入站 HTTP 头里解析三件事：
  * 语言（错误消息与提示词用哪一份）
  * 反馈开关（决定是否把引用/图片信息塞进回答）
  * 传给下游的用户标识（单用户模式，未带头时用默认用户）

保留同名的 `build_rag_request_header` / `set_mode` / `get_mode`，是为了让 vendored 的
检索器（`self.header.set_mode('0')`）一行都不用改。
"""
from dataclasses import dataclass, field


@dataclass
class RagRequestHeaders:
    language_option: str = 'zh'
    feedback: str = ''
    emp_no: str = ''
    # bge reranker 读的是 username（`escape(getattr(headers, 'username', ''))`）
    username: str = ''
    org_id: str = ''
    mode: str = '0'
    # 下面几个字段是为「vendored 代码会读、但没有来源」的属性留的位。
    # 例：simple_summarizer 读 `headers.deepsearch` 来切换「深度检索」的响应形状 ——
    # 少这个属性会在合成阶段直接 AttributeError（整条编排只剩一个 Unknown error）。
    # 没有对应来源时取默认值即可。
    deepsearch: bool = False
    tenant_id: str = ''
    client_ip: str = ''
    authorization: str = ''
    transaction_id: str = ''
    raw: dict = field(default_factory=dict)

    @classmethod
    def build_rag_request_header(cls, headers) -> 'RagRequestHeaders':
        """从入站 HTTP 头构造。缺失一律回落，不抛异常 —— 这个服务不给前端直接用，
        真正的用户上下文由调用方带走。"""
        getter = headers.get if hasattr(headers, 'get') else (lambda *a, **k: None)
        # 归一规则：读 `language-option` 头，以 'zh' 开头算中文，否则英文。
        # i18n 表里的键只有 'zh'/'en'，传 'zh_CN' 会导致错误消息取不到 →
        # 错误分支自己抛异常 → 业务错误被 500 盖掉。
        raw_language = getter('language-option') or getter('Language-Option') or getter('X-Lang-Id') or ''
        language_option = 'zh' if (not raw_language or raw_language.lower().startswith('zh')) else 'en'
        emp_no = getter('X-Emp-No') or getter('x-emp-no') or ''
        return cls(
            language_option=language_option,
            feedback=getter('feedback') or getter('X-Feedback') or '',
            emp_no=emp_no,
            username=emp_no,
            org_id=getter('X-Org-Id') or getter('x-org-id') or '',
            mode=getter('X-Mode') or '0',
            raw={k.lower(): v for k, v in dict(headers).items()} if headers else {},
        )

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def get_mode(self) -> str:
        return self.mode
