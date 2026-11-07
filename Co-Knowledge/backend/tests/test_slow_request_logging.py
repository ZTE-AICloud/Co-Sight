"""慢请求埋点（ISSUE-OPS-002）。

单进程后端在后台抽取/入库并发时，偶发把简单只读接口拖过客户端超时。
``app.py`` 的 HTTP 中间件按 ``RKB_SLOW_REQUEST_LOG_MS`` 阈值打 warning：
method + path + status + 耗时，便于按路径对账。

这里直接跑真实中间件 + 真实 ``/health`` 端点（不连 DB、不跑 lifespan）。
"""
import logging

from fastapi.testclient import TestClient

import app as app_module

HEALTH = '/api/co-knowledge/v1/health'


def _slow_messages (caplog) -> list[str]:
    return [
        record.getMessage() for record in caplog.records
        if record.getMessage().startswith('slow request:')
    ]


def test_request_at_or_above_threshold_is_logged (monkeypatch, caplog):
    # Arrange：阈值 0 → 每个请求都算「慢」，断言不依赖真实耗时
    monkeypatch.setattr(app_module, 'SLOW_REQUEST_LOG_MS', 0)
    client = TestClient(app_module.app)

    # Act
    with caplog.at_level(logging.WARNING):
        response = client.get(HEALTH)

    # Assert
    assert response.status_code == 200
    messages = _slow_messages(caplog)
    assert any(HEALTH in message and 'GET' in message and '200' in message for message in messages), messages


def test_fast_request_is_not_logged (monkeypatch, caplog):
    # Arrange：阈值调到 1 小时，健康检查不可能命中
    monkeypatch.setattr(app_module, 'SLOW_REQUEST_LOG_MS', 3_600_000)
    client = TestClient(app_module.app)

    # Act
    with caplog.at_level(logging.WARNING):
        response = client.get(HEALTH)

    # Assert
    assert response.status_code == 200
    assert _slow_messages(caplog) == []
