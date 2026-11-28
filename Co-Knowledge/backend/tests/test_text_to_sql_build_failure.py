"""构建失败必须收口：任务与版本都不能留在 RUNNING / BUILDING。

没有收口时，一次异常（例如向量表建表权限不足）会让 ``t2s_index_job`` 永远
停在 RUNNING，``prepare_build`` 之后每次都拒绝重试，界面一直转圈。
"""

from __future__ import annotations

import pytest

from text_to_sql.service import Text2SqlService

DATASOURCE = '11111111-1111-1111-1111-111111111111'
VERSION = '22222222-2222-2222-2222-222222222222'


class _FakeVersions:
    def __init__(self, finish):
        self._finish = finish
        self.failed = []

    def prepare_build(self, datasource_id, version_id, worker_id):
        return {'status': 'BUILDING', 'job_id': 'job-1',
                'pending': [{'id': 'k1', 'content': '订单表'}],
                'total': 1, 'embedding_model': 'test-embedding',
                'embedding_dimensions': 4}

    def finish_build(self, datasource_id, version_id, job_id, embeddings, errors):
        return self._finish(datasource_id, version_id, job_id, embeddings, errors)

    def fail_build(self, datasource_id, version_id, job_id, message):
        self.failed.append((datasource_id, version_id, job_id, message))

    def get_version(self, datasource_id, version_id):
        return {'id': version_id, 'datasource_id': datasource_id, 'revision': 1,
                'status': 'READY', 'content_hash': '0' * 64,
                'expected_knowledge_count': 1, 'indexed_count': 1,
                'failed_count': 0, 'embedding_model': 'test-embedding',
                'embedding_dimensions': 4, 'created_by': 'tester',
                'ready_at': None, 'created_at': None, 'updated_at': None,
                'snapshot': {}}


def _service(versions):
    return Text2SqlService(versions=versions,
                           embed=lambda texts, model: [[0.1] * 4 for _ in texts])


def test_build_failure_marks_job_and_version_failed():
    # Arrange
    def boom(*_args, **_kwargs):
        raise RuntimeError('permission denied for schema text2sql_index')

    versions = _FakeVersions(boom)
    service = _service(versions)

    # Act
    with pytest.raises(RuntimeError, match='permission denied'):
        service.build_version(DATASOURCE, VERSION)

    # Assert
    assert versions.failed == [
        (DATASOURCE, VERSION, 'job-1',
         'permission denied for schema text2sql_index')]


def test_build_success_does_not_mark_failed():
    # Arrange
    def ok(datasource_id, version_id, job_id, embeddings, errors):
        return {'status': 'READY', 'processed': 1, 'failed': 0, 'errors': {}}

    versions = _FakeVersions(ok)
    service = _service(versions)

    # Act
    result = service.build_version(DATASOURCE, VERSION)

    # Assert
    assert result['status'] == 'READY'
    assert versions.failed == []
