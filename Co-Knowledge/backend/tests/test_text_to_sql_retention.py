"""结果预览的保留期清理。"""


from text_to_sql import retention


def test_retention_defaults_to_30_days(monkeypatch):
    monkeypatch.delenv('RKB_TEXT2SQL_RESULT_RETENTION_DAYS', raising=False)
    assert retention.retention_days() == 30


def test_retention_can_be_disabled(monkeypatch):
    monkeypatch.setenv('RKB_TEXT2SQL_RESULT_RETENTION_DAYS', '0')
    assert retention.retention_days() == 0
    assert retention.purge_once() == 0       # 关闭时一次也不跑


def test_invalid_retention_falls_back(monkeypatch):
    monkeypatch.setenv('RKB_TEXT2SQL_RESULT_RETENTION_DAYS', 'soon')
    assert retention.retention_days() == 30


def test_purge_swallows_database_errors(monkeypatch):
    monkeypatch.setenv('RKB_TEXT2SQL_RESULT_RETENTION_DAYS', '7')
    monkeypatch.setattr('text_to_sql.query_repository.purge_expired_results',
                        lambda: (_ for _ in ()).throw(RuntimeError('db down')))
    assert retention.purge_once() == 0


def test_purge_reports_removed_rows(monkeypatch):
    monkeypatch.setenv('RKB_TEXT2SQL_RESULT_RETENTION_DAYS', '7')
    monkeypatch.setattr('text_to_sql.query_repository.purge_expired_results',
                        lambda: 5)
    assert retention.purge_once() == 5
