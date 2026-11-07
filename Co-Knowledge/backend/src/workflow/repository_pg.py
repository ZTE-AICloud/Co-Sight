"""``flow_*`` 三表的 PostgreSQL 实现。

建表由本模块的 :meth:`PgFlowStore._ensure_schema` 负责（DDL 见
``FLOW_SCHEMA_STATEMENTS``，每进程幂等执行一次）；草案只作存档。
连不上库 / 建表失败时读写会显式抛
:class:`FlowStoreError`，不会静默降级成空画布。

三条 DB 访问方式的取舍，都是为了「错误必须可见」：

1. **不用 ``_db_pool.exec_sql`` / ``exec_ddl``**：``exec_ddl`` 出错只打一条 warn 就返回，
   ``exec_sql`` 把错误折成返回值 —— 用它们做写入会把「表不存在」「唯一键冲突」都变成
   静默失败。这里自己拿连接、自己提交/回滚、**异常一律抛** :class:`FlowStoreError`。
2. **自己管事务**：``_db_pool`` 的每个方法各开一条连接，跨语句事务拼不出来。
   删除工作流要删三张表，必须同一个事务（删一半留下一堆孤儿数据比删不掉更糟）。
3. **时间戳在 SQL 里格式化**（``to_char(..., 'YYYY-MM-DD HH24:MI:SS')``）：
   前端列表页直接显示这个格式（线上实测 ``YYYY-MM-DD HH:MM:SS``），
   格式变了会显示成 ISO 串。

连接来源：RKB 连接池的**业务库**（mode ``'0'``，``_db_pool.get_db_conn()``）。
放哪个库是 data-ownership 的约定范围，真要换库只改 :meth:`_connect` 一处。
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from workflow.errors import FlowStoreError
from workflow.models import (
    FLOW_TYPE_WORKFLOW,
    FlowDraft,
    FlowPublished,
    WorkflowRecord,
)

# 表名固定用 flow_ 前缀（与其它表族区分；SQL 草案里同前缀）
TABLE_WORKFLOW = 'flow_workflow'
TABLE_CONFIG = 'flow_draft'
TABLE_PUBLISHED = 'flow_release'

# ---------------------------------------------------------------------------
# 建表语句（**唯一可执行来源**）
#
# 与该草案完全对齐；那份草案从此只作存档，
# 改动 DDL 必须同时改这里。为什么由本模块自建而不是放启动期建表脚本
# （启动期建表脚本的执行是惰性的、且与
# import 顺序赛跑（详见 ``model/repository_pg.py`` 的 ``_ensure_schema``
# 注释）。单库部署删掉 ``deploy/init/pg`` 后，全新环境也需要靠这里在第一次 flow
# 请求时把三张表建出来。
# ---------------------------------------------------------------------------
FLOW_SCHEMA_STATEMENTS = (
    '''CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$''',
    '''CREATE TABLE IF NOT EXISTS public.flow_workflow (
    id                 BIGSERIAL    PRIMARY KEY,
    workflow_id        VARCHAR(128) NOT NULL,
    name               VARCHAR(255) NOT NULL,
    description        TEXT,
    template           VARCHAR(64),
    knowledge_type     VARCHAR(32),
    publish_type       SMALLINT     NOT NULL DEFAULT 0,
    status             SMALLINT     NOT NULL DEFAULT 1,
    bound_info         JSONB,
    created_by         VARCHAR(255),
    updated_by         VARCHAR(255),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT flow_workflow_workflow_id_uidx UNIQUE (workflow_id)
)''',
    '''CREATE OR REPLACE TRIGGER trg_flow_workflow_updated_at
    BEFORE UPDATE ON public.flow_workflow
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()''',
    '''CREATE INDEX IF NOT EXISTS idx_flow_workflow_name
    ON public.flow_workflow (name)''',
    '''CREATE INDEX IF NOT EXISTS idx_flow_workflow_created_by
    ON public.flow_workflow (created_by)''',
    '''CREATE TABLE IF NOT EXISTS public.flow_draft (
    id                 BIGSERIAL    PRIMARY KEY,
    workflow_id        VARCHAR(128) NOT NULL,
    version            INTEGER      NOT NULL DEFAULT 1,
    flow_type          VARCHAR(32)  NOT NULL DEFAULT 'workflow',
    node_config        JSONB        NOT NULL,
    other_node_config  JSONB        NOT NULL,
    created_by         VARCHAR(255),
    updated_by         VARCHAR(255),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT flow_draft_workflow_id_uidx UNIQUE (workflow_id)
)''',
    '''CREATE OR REPLACE TRIGGER trg_flow_draft_updated_at
    BEFORE UPDATE ON public.flow_draft
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()''',
    '''CREATE TABLE IF NOT EXISTS public.flow_release (
    id                 BIGSERIAL    PRIMARY KEY,
    workflow_id        VARCHAR(128) NOT NULL,
    version            INTEGER      NOT NULL,
    node_config        JSONB        NOT NULL,
    other_node_config  JSONB        NOT NULL,
    created_by         VARCHAR(255),
    updated_by         VARCHAR(255),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT flow_release_workflow_version_uidx UNIQUE (workflow_id, version)
)''',
    '''CREATE OR REPLACE TRIGGER trg_flow_release_updated_at
    BEFORE UPDATE ON public.flow_release
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()''',
    '''CREATE INDEX IF NOT EXISTS idx_flow_release_workflow_version
    ON public.flow_release (workflow_id, version DESC)''',
    '''COMMENT ON TABLE public.flow_workflow
    IS '检索编排工作流元数据（RKB 侧写入）' ''',
    '''COMMENT ON COLUMN public.flow_workflow.publish_type
    IS '0=未发布 1=已发布 2=发布后再改动' ''',
    '''COMMENT ON COLUMN public.flow_workflow.bound_info
    IS '建流时选中的知识库（按发布状态分组，JSON 原样存）' ''',
    '''COMMENT ON TABLE public.flow_draft
    IS '检索编排画布草稿，JSON 原样存；version 为最后一次发布的版本号' ''',
    '''COMMENT ON COLUMN public.flow_draft.node_config
    IS 'nodeConfigDTOList（原样往返）' ''',
    '''COMMENT ON TABLE public.flow_release
    IS '检索编排发布快照，编排运行时只读这里；行不可变（只 INSERT）' ''',
)

#: 本进程是否已经确保过表结构；并发保护用锁，避免两个请求线程同时 CREATE TABLE
_schema_ready = False
_schema_lock = threading.Lock()

_TIMESTAMP_SELECT = "to_char({column}, 'YYYY-MM-DD HH24:MI:SS') AS {column}"

_WORKFLOW_COLUMNS = (
    'workflow_id, name, description, template, knowledge_type, publish_type, status, '
    'bound_info, created_by, '
    + _TIMESTAMP_SELECT.format(column='created_at') + ', '
    + _TIMESTAMP_SELECT.format(column='updated_at')
)


class PgFlowStore:
    """``FlowStore`` 的 PostgreSQL 实现（协议见 ``store.py``）。"""

    # ------------------------------------------------------------------
    # 连接与语句执行
    # ------------------------------------------------------------------

    def _connect(self):
        """取业务库连接（延迟 import，单测环境不需要 psycopg2 也能加载本模块）。"""
        from infrastructure.db.pool import _db_pool

        return _db_pool.get_db_conn()

    def _ensure_schema(self, conn) -> None:
        """确保三张表存在（每进程一次）。

        立即提交建表，而不是等外层事务提交：``_execute`` 的写入可能因唯一键冲突
        回滚，若 DDL 跟着一起回滚而 ``_schema_ready`` 已置 True，下一请求就会撞
        「表不存在」且不再重试。建表是幂等的，单独提交没有副作用。
        """
        global _schema_ready
        if _schema_ready:
            return
        with _schema_lock:
            if _schema_ready:
                return
            with conn.cursor() as cursor:
                for statement in FLOW_SCHEMA_STATEMENTS:
                    cursor.execute(statement)
            conn.commit()
            _schema_ready = True

    def _execute(self, sql: str, params: tuple = (), *, fetch: Optional[str] = None) -> Any:
        """执行一条语句（自动提交）；失败抛 :class:`FlowStoreError`。

        :param fetch: ``'all'`` 取全部行、``'one'`` 取一行；None 表示不取结果
        """
        import psycopg2
        from psycopg2 import errors as pg_errors

        conn = None
        cursor = None
        try:
            conn = self._connect()
            self._ensure_schema(conn)
            cursor = conn.cursor()
            cursor.execute(sql, params)
            result = None
            if fetch == 'all':
                result = cursor.fetchall()
            elif fetch == 'one':
                result = cursor.fetchone()
            conn.commit()
            return result
        except pg_errors.UniqueViolation as e:
            if conn is not None:
                conn.rollback()
            raise FlowStoreError(FlowStoreError.DUPLICATE, str(e), 'duplicate key') from e
        except psycopg2.Error as e:
            if conn is not None:
                conn.rollback()
            # 「表还不存在」是最可能的第一现场：把原始报错带出去，别让它变成一个空结果
            raise FlowStoreError(FlowStoreError.DB_ERROR, str(e).strip()) from e
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    def _execute_transaction(self, statements: list[tuple[str, tuple]]) -> None:
        """把多条语句放进同一事务；任一条失败整体回滚并抛出。"""
        conn = None
        cursor = None
        try:
            conn = self._connect()
            self._ensure_schema(conn)
            cursor = conn.cursor()
            for sql, params in statements:
                cursor.execute(sql, params)
            conn.commit()
        except Exception as e:
            if conn is not None:
                conn.rollback()
            # 与单条路径保持同一异常类型（含唯一键冲突）
            import psycopg2
            from psycopg2 import errors as pg_errors

            if isinstance(e, pg_errors.UniqueViolation):
                raise FlowStoreError(FlowStoreError.DUPLICATE, str(e), 'duplicate key') from e
            if isinstance(e, psycopg2.Error):
                raise FlowStoreError(FlowStoreError.DB_ERROR, str(e).strip()) from e
            raise
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    @staticmethod
    def _json(value) -> Any:
        """JSONB 参数：交给 psycopg2 的 Json 适配器（不要手工 json.dumps 成字符串）。"""
        from psycopg2.extras import Json

        return Json(value)

    # ------------------------------------------------------------------
    # 工作流元数据
    # ------------------------------------------------------------------

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowRecord]:
        row = self._execute(
            f'SELECT {_WORKFLOW_COLUMNS} FROM {TABLE_WORKFLOW} WHERE workflow_id = %s',
            (workflow_id,), fetch='one',
        )
        return _to_workflow(row) if row else None

    def list_workflows(self, name: Optional[str], page: int, size: int,
                       publish_type: Optional[int] = None) -> tuple[list[WorkflowRecord], int]:
        clauses: list[str] = []
        params: list = []
        if name:
            # 列表页的搜索框同时认「名称 / 工作流 ID / 创建人」：
            # 用户复制的是 ID，能按 ID 定位；英文名与大小写混输也能命中
            # （``ILIKE``）。``ESCAPE`` 让用户输入的 ``%`` / ``_`` 按字面匹配，
            # 否则搜 ``wf_1`` 会把 ``wf21`` 也带出来。
            pattern = _like_pattern(name)
            clauses.append(
                "(name ILIKE %s ESCAPE '\\' OR workflow_id ILIKE %s ESCAPE '\\' "
                "OR created_by ILIKE %s ESCAPE '\\')")
            params.extend([pattern, pattern, pattern])
        if publish_type is not None:
            # 0=未发布 / 1=已发布 / 2=已发布但有改动；筛选在 SQL 侧做，
            # 否则「先分页再过滤」会让 total 与当前页条数对不上。
            clauses.append('publish_type = %s')
            params.append(int(publish_type))
        where = f'WHERE {" AND ".join(clauses)}' if clauses else ''
        total_row = self._execute(
            f'SELECT count(*) FROM {TABLE_WORKFLOW} {where}', tuple(params), fetch='one')
        total = int(total_row[0]) if total_row else 0
        rows = self._execute(
            f'SELECT {_WORKFLOW_COLUMNS} FROM {TABLE_WORKFLOW} {where} '
            'ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s',
            tuple(params) + (size, (page - 1) * size), fetch='all',
        )
        return [_to_workflow(row) for row in (rows or [])], total

    def list_workflows_by_creator(self, created_by: str) -> list[WorkflowRecord]:
        rows = self._execute(
            f'SELECT {_WORKFLOW_COLUMNS} FROM {TABLE_WORKFLOW} WHERE created_by = %s',
            (created_by,), fetch='all',
        )
        return [_to_workflow(row) for row in (rows or [])]

    def create_workflow_with_draft(self, record: WorkflowRecord, draft: FlowDraft) -> None:
        """建流 + 播种默认画布，**同一事务**（元数据与草稿要么都在、要么都不在）。

        元数据与草稿必须同一事务：两步之间断电会留下一份「有工作流、没画布」的记录
        —— 那种记录的新建画布打开后是空的，且没有任何错误可查。用事务把窗口关掉。
        """
        self._execute_transaction([
            (
                f'INSERT INTO {TABLE_WORKFLOW} '
                '(workflow_id, name, description, template, knowledge_type, publish_type, status, '
                ' bound_info, created_by, updated_by) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                (record.workflow_id, record.name, record.description, record.template,
                 record.knowledge_type, record.publish_type, record.status,
                 self._json(record.bound_info), record.created_by, record.created_by),
            ),
            (
                f'INSERT INTO {TABLE_CONFIG} (workflow_id, version, flow_type, node_config, '
                ' other_node_config, created_by, updated_by) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                (draft.workflow_id, draft.version, draft.flow_type,
                 self._json(draft.node_config), self._json(draft.other_node_config),
                 draft.created_by, draft.created_by),
            ),
        ])

    def update_workflow(self, workflow_id: str, name: str, template: Optional[str],
                        knowledge_type: Optional[str], description: Optional[str]) -> None:
        self._execute(
            f'UPDATE {TABLE_WORKFLOW} SET name = %s, template = %s, knowledge_type = %s, '
            'description = %s, updated_at = CURRENT_TIMESTAMP '
            'WHERE workflow_id = %s',
            (name, template, knowledge_type, description, workflow_id),
        )

    def update_publish_type(self, workflow_id: str, publish_type: int) -> None:
        self._execute(
            f'UPDATE {TABLE_WORKFLOW} SET publish_type = %s, updated_at = CURRENT_TIMESTAMP '
            'WHERE workflow_id = %s',
            (publish_type, workflow_id),
        )

    def delete_workflow(self, workflow_id: str) -> None:
        """显式按序删三张表（草稿 → 快照 → 元数据），同一事务。

        不依赖 ``ON DELETE CASCADE``：连接池没有声明式外键配套，
        显式删除 + 事务 + 失败抛出，比「删一半静默成功」安全。
        """
        self._execute_transaction([
            (f'DELETE FROM {TABLE_CONFIG} WHERE workflow_id = %s', (workflow_id,)),
            (f'DELETE FROM {TABLE_PUBLISHED} WHERE workflow_id = %s', (workflow_id,)),
            (f'DELETE FROM {TABLE_WORKFLOW} WHERE workflow_id = %s', (workflow_id,)),
        ])

    # ------------------------------------------------------------------
    # 画布草稿
    # ------------------------------------------------------------------

    def get_draft(self, workflow_id: str) -> Optional[FlowDraft]:
        row = self._execute(
            'SELECT workflow_id, version, flow_type, node_config, other_node_config, created_by, '
            + _TIMESTAMP_SELECT.format(column='created_at') + ', '
            + _TIMESTAMP_SELECT.format(column='updated_at')
            + f' FROM {TABLE_CONFIG} WHERE workflow_id = %s',
            (workflow_id,), fetch='one',
        )
        return _to_draft(row) if row else None

    def insert_draft(self, draft: FlowDraft) -> None:
        self._execute(
            f'INSERT INTO {TABLE_CONFIG} (workflow_id, version, flow_type, node_config, '
            ' other_node_config, created_by, updated_by) VALUES (%s, %s, %s, %s, %s, %s, %s)',
            (draft.workflow_id, draft.version, draft.flow_type,
             self._json(draft.node_config), self._json(draft.other_node_config),
             draft.created_by, draft.created_by),
        )

    def update_draft(self, workflow_id: str, flow_type: str, node_config: list,
                     other_node_config: list) -> None:
        # version 故意不更新：草稿保存不推进版本号（只有发布推进）
        self._execute(
            f'UPDATE {TABLE_CONFIG} SET flow_type = %s, node_config = %s, other_node_config = %s, '
            'updated_at = CURRENT_TIMESTAMP WHERE workflow_id = %s',
            (flow_type, self._json(node_config), self._json(other_node_config), workflow_id),
        )

    def update_draft_version(self, workflow_id: str, version: int) -> None:
        self._execute(
            f'UPDATE {TABLE_CONFIG} SET version = %s WHERE workflow_id = %s',
            (version, workflow_id),
        )

    def list_drafts(self, workflow_ids: list[str]) -> list[FlowDraft]:
        if not workflow_ids:
            return []
        rows = self._execute(
            'SELECT workflow_id, version, flow_type, node_config, other_node_config, created_by, '
            + _TIMESTAMP_SELECT.format(column='created_at') + ', '
            + _TIMESTAMP_SELECT.format(column='updated_at')
            + f' FROM {TABLE_CONFIG} WHERE workflow_id = ANY(%s)',
            (list(workflow_ids),), fetch='all',
        )
        return [_to_draft(row) for row in (rows or [])]

    # ------------------------------------------------------------------
    # 发布快照
    # ------------------------------------------------------------------

    _PUBLISHED_COLUMNS = (
        'workflow_id, version, node_config, other_node_config, created_by, '
        + _TIMESTAMP_SELECT.format(column='created_at')
    )

    def get_latest_published(self, workflow_id: str) -> Optional[FlowPublished]:
        row = self._execute(
            f'SELECT {self._PUBLISHED_COLUMNS} FROM {TABLE_PUBLISHED} '
            'WHERE workflow_id = %s ORDER BY version DESC LIMIT 1',
            (workflow_id,), fetch='one',
        )
        return _to_published(row) if row else None

    def get_max_published_version(self, workflow_id: str) -> int:
        row = self._execute(
            f'SELECT COALESCE(MAX(version), 0) FROM {TABLE_PUBLISHED} WHERE workflow_id = %s',
            (workflow_id,), fetch='one',
        )
        return int(row[0]) if row else 0

    def insert_published(self, published: FlowPublished) -> None:
        # 并发发布（两人同时算到同一个 max+1）由 UNIQUE(workflow_id, version) 拦下，
        # _execute 把它转成 FlowStoreError(kind='duplicate')
        self._execute(
            f'INSERT INTO {TABLE_PUBLISHED} (workflow_id, version, node_config, other_node_config, '
            ' created_by, updated_by) VALUES (%s, %s, %s, %s, %s, %s)',
            (published.workflow_id, published.version,
             self._json(published.node_config), self._json(published.other_node_config),
             published.created_by, published.created_by),
        )


def _like_pattern(value: str) -> str:
    """``%value%``，并把 LIKE 的元字符转义成字面量（配合 ``ESCAPE '\\'``）。"""
    escaped = str(value).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


def _to_workflow(row) -> WorkflowRecord:
    return WorkflowRecord(
        workflow_id=row[0],
        name=row[1],
        description=row[2],
        template=row[3],
        knowledge_type=row[4],
        publish_type=row[5] if row[5] is not None else 0,
        status=row[6] if row[6] is not None else 1,
        bound_info=row[7],
        created_by=row[8],
        created_at=row[9],
        updated_at=row[10],
    )


def _to_draft(row) -> FlowDraft:
    return FlowDraft(
        workflow_id=row[0],
        version=row[1] if row[1] is not None else 1,
        flow_type=row[2] or FLOW_TYPE_WORKFLOW,
        node_config=row[3] if row[3] is not None else [],
        other_node_config=row[4] if row[4] is not None else [],
        created_by=row[5],
        created_at=row[6],
        updated_at=row[7],
    )


def _to_published(row) -> FlowPublished:
    return FlowPublished(
        workflow_id=row[0],
        version=row[1],
        node_config=row[2] if row[2] is not None else [],
        other_node_config=row[3] if row[3] is not None else [],
        created_by=row[4],
        created_at=row[5],
    )
