"""数据源密码的落库形态：``credential_ref`` 存 ``enc:v1:`` 密文。

真实部署可换成外部密钥服务；这里复用部署级密钥（``RKB_SECRET_KEY`` /
``RKB_SECRET_KEY_FILE``），并用独立 AAD 与模型注册表的 api_key 隔离。
"""

from __future__ import annotations

from infrastructure.secrets import box

_AAD = b'text2sql.t2s_datasource.credential_ref.v1'
_LABEL = 't2s_datasource.credential_ref'


def encrypt_password(password: str | None) -> str:
    return box.encrypt(password, _AAD, label=_LABEL)


def decrypt_password(credential_ref: str | None) -> str:
    return box.decrypt(credential_ref, _AAD, label=_LABEL)
