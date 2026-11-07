"""数据库/ES 环境变量契约：只认 ``RKB_*``，旧名硬切。"""

from __future__ import annotations

import importlib

from infrastructure.db import connection_info
from infrastructure.db import kb as kb_db


def test_db_conn_info_reads_rkb_names(monkeypatch):
    monkeypatch.setenv('RKB_DB_HOST', 'db.internal')
    monkeypatch.setenv('RKB_DB_PORT', '5544')
    monkeypatch.setenv('RKB_DB_NAME', 'custom_db')
    monkeypatch.setenv('RKB_DB_USER', 'custom_user')
    monkeypatch.setenv('RKB_DB_PASSWORD', 'custom_pwd')

    info = connection_info.get_db_conn_info()

    assert info == {
        'driver': 'psycopg2',
        'host': 'db.internal',
        'port': '5544',
        'database': 'custom_db',
        'user': 'custom_user',
        'password': 'custom_pwd',
    }


def test_db_conn_info_defaults(monkeypatch):
    for name in ('RKB_DB_HOST', 'RKB_DB_PORT', 'RKB_DB_NAME', 'RKB_DB_USER', 'RKB_DB_PASSWORD'):
        monkeypatch.delenv(name, raising=False)

    info = connection_info.get_db_conn_info()

    assert info['host'] is None
    assert info['port'] is None
    assert info['database'] == 'rag_studio'
    assert info['user'] is None
    assert info['password'] == ''


def test_legacy_openpalette_names_are_ignored(monkeypatch):
    for name in ('RKB_DB_HOST', 'RKB_DB_NAME', 'RKB_DB_USER', 'RKB_DB_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('OPENPALETTE_GP_ADDRESS', 'legacy-host')
    monkeypatch.setenv('OPENPALETTE_GP_DBNAME', 'legacy-db')
    monkeypatch.setenv('OPENPALETTE_GP_USERNAME', 'legacy-user')
    monkeypatch.setenv('OPENPALETTE_GP_PASSWORD', 'legacy-pwd')

    info = connection_info.get_db_conn_info()

    assert info['host'] is None
    assert info['database'] == 'rag_studio'
    assert info['user'] is None
    assert info['password'] == ''


def test_es_dict_reads_rkb_names(monkeypatch):
    from infrastructure.config import constants

    monkeypatch.setenv('RKB_ES_HOST', 'es.internal')
    monkeypatch.setenv('RKB_ES_PORT', '9300')
    monkeypatch.setenv('RKB_ES_USERNAME', 'es-user')
    monkeypatch.setenv('RKB_ES_PASSWORD', 'es-pwd')
    try:
        importlib.reload(constants)
        assert constants.ES_DICT == {
            'host': 'es.internal',
            'port': '9300',
            'user': 'es-user',
            'password': 'es-pwd',
        }
    finally:
        monkeypatch.undo()
        importlib.reload(constants)


def test_kbase_db_name_uses_rkb_db_name(monkeypatch):
    monkeypatch.setenv(kb_db.ENV_DB_NAME, 'shadow_db')
    assert kb_db.get_kbase_db_name() == 'shadow_db'

    monkeypatch.setenv(kb_db.ENV_DB_NAME, '   ')
    assert kb_db.get_kbase_db_name() == 'rag_studio'
