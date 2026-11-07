--
-- PostgreSQL database dump
--
-- 本文件是 **核心静态表的 schema 快照**（22 张业务表 + kb_index schema），
-- 由默认 docker-compose.yml 挂到 /docker-entrypoint-initdb.d/，只在空 PGDATA 上执行。
--
-- 空卷初始化的权威 schema。
-- （pg_dump --schema-only），并经空卷启动验证。动态 doc_* / graph_* 表不在快照内，
-- 仍由应用按需创建。表名、审计列与命名规范见
-- docs/database-schema.md。
--
-- ⚠️ 本文件只在空卷（PGDATA 为空）时执行一次。

-- 动态向量表使用 vector(N)，扩展必须在建表前存在。
CREATE EXTENSION IF NOT EXISTS vector;
-- 可观测性（P1）：慢查询统计；compose 的 command 已 preload。
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- 动态每库表所在 schema（运行时由应用建表）。
CREATE SCHEMA IF NOT EXISTS kb_index;

--
-- PostgreSQL database dump
--


-- Dumped from database version 16.15 (Debian 16.15-1.pgdg12+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg12+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS public;


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_api_key; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_api_key (
    id bigint NOT NULL,
    name character varying(128) NOT NULL,
    key_prefix character varying(32) NOT NULL,
    key_hash character(64) NOT NULL,
    scopes text[] DEFAULT ARRAY[]::text[] NOT NULL,
    kb_ids text[] DEFAULT ARRAY[]::text[] NOT NULL,
    rate_limit_per_min integer DEFAULT 60 NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    expires_at timestamp with time zone,
    last_used_at timestamp with time zone,
    created_by character varying(128),
    description character varying(200),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE agent_api_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.agent_api_key IS 'Agent 接口 API Key（只存 hash）';


--
-- Name: agent_api_key_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_api_key_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_api_key_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_api_key_id_seq OWNED BY public.agent_api_key.id;


--
-- Name: agent_api_key_usage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_api_key_usage (
    key_prefix character varying(32) NOT NULL,
    usage_date date NOT NULL,
    request_count bigint DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE agent_api_key_usage; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.agent_api_key_usage IS 'API Key 调用计数（按 Key 每自然日聚合；删 Key 级联）';


--
-- Name: auth_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_session (
    id bigint NOT NULL,
    token_hash character(64) NOT NULL,
    user_id bigint NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    ip character varying(64),
    user_agent character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE auth_session; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.auth_session IS '登录会话（token_hash 唯一）';


--
-- Name: auth_session_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.auth_session_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: auth_session_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.auth_session_id_seq OWNED BY public.auth_session.id;


--
-- Name: auth_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user (
    id bigint NOT NULL,
    username character varying(64) NOT NULL,
    email character varying(255),
    display_name character varying(128),
    password_hash character varying(255) NOT NULL,
    role character varying(16) DEFAULT 'user'::character varying NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    must_change_password boolean DEFAULT false NOT NULL,
    last_login_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE auth_user; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.auth_user IS '本地账号';


--
-- Name: auth_user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.auth_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: auth_user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.auth_user_id_seq OWNED BY public.auth_user.id;


--
-- Name: chat_query_trace; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_query_trace (
    id bigint NOT NULL,
    trace_id character varying(64) DEFAULT ''::character varying NOT NULL,
    conversation_id character varying(128) DEFAULT ''::character varying NOT NULL,
    workflow_id character varying(128) DEFAULT ''::character varying NOT NULL,
    org_id character varying(128) DEFAULT ''::character varying NOT NULL,
    is_stream boolean DEFAULT false NOT NULL,
    status character varying(24) NOT NULL,
    error_code character varying(128) DEFAULT ''::character varying NOT NULL,
    http_status smallint,
    error_status smallint,
    question_len integer DEFAULT 0 NOT NULL,
    answer_len integer DEFAULT 0 NOT NULL,
    understanding_ms numeric(12,1),
    retrieval_ms numeric(12,1),
    rerank_ms numeric(12,1),
    generate_ms numeric(12,1),
    first_token_ms numeric(12,1),
    total_ms numeric(12,1),
    hit_count integer DEFAULT 0 NOT NULL,
    source_count integer DEFAULT 0 NOT NULL,
    kb_count integer DEFAULT 0 NOT NULL,
    top_score numeric(12,4),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chat_query_trace_status_check CHECK (((status)::text = ANY ((ARRAY['ok'::character varying, 'error'::character varying, 'client_disconnect'::character varying])::text[])))
);


--
-- Name: TABLE chat_query_trace; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.chat_query_trace IS '查询链路指标（append-only，按保留期清理）';


--
-- Name: chat_query_trace_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.chat_query_trace_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: chat_query_trace_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.chat_query_trace_id_seq OWNED BY public.chat_query_trace.id;


--
-- Name: flow_draft; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.flow_draft (
    id bigint NOT NULL,
    workflow_id character varying(128) NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    flow_type character varying(32) DEFAULT 'workflow'::character varying NOT NULL,
    node_config jsonb NOT NULL,
    other_node_config jsonb NOT NULL,
    created_by character varying(255),
    updated_by character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE flow_draft; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.flow_draft IS '工作流草稿（当前编辑态）';


--
-- Name: COLUMN flow_draft.node_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.flow_draft.node_config IS 'nodeConfigDTOList（原样往返）';


--
-- Name: flow_draft_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.flow_draft_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: flow_draft_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.flow_draft_id_seq OWNED BY public.flow_draft.id;


--
-- Name: flow_release; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.flow_release (
    id bigint NOT NULL,
    workflow_id character varying(128) NOT NULL,
    version integer NOT NULL,
    node_config jsonb NOT NULL,
    other_node_config jsonb NOT NULL,
    created_by character varying(255),
    updated_by character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE flow_release; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.flow_release IS '工作流发布快照（不可变版本）';


--
-- Name: flow_release_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.flow_release_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: flow_release_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.flow_release_id_seq OWNED BY public.flow_release.id;


--
-- Name: flow_workflow; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.flow_workflow (
    id bigint NOT NULL,
    workflow_id character varying(128) NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    template character varying(64),
    knowledge_type character varying(32),
    publish_type smallint DEFAULT 0 NOT NULL,
    status smallint DEFAULT 1 NOT NULL,
    bound_info jsonb,
    created_by character varying(255),
    updated_by character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_flow_workflow_publish_type CHECK ((publish_type = ANY (ARRAY[0, 1, 2]))),
    CONSTRAINT ck_flow_workflow_status CHECK ((status >= 0))
);


--
-- Name: TABLE flow_workflow; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.flow_workflow IS '工作流主表';


--
-- Name: COLUMN flow_workflow.publish_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.flow_workflow.publish_type IS '0=未发布 1=已发布 2=发布后再改动';


--
-- Name: COLUMN flow_workflow.bound_info; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.flow_workflow.bound_info IS '建流时选中的知识库（按发布状态分组，JSON 原样存）';


--
-- Name: flow_workflow_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.flow_workflow_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: flow_workflow_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.flow_workflow_id_seq OWNED BY public.flow_workflow.id;


--
-- Name: graph_extract_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.graph_extract_task (
    id character varying(100) NOT NULL,
    kb_id character varying(100) NOT NULL,
    schema_id character varying(100) NOT NULL,
    operator_id integer NOT NULL,
    file_count integer NOT NULL,
    status character varying(20) NOT NULL,
    progress integer DEFAULT 0 NOT NULL,
    error_message text,
    result_file_path text,
    created_by character varying(255),
    start_time timestamp with time zone,
    finish_time timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_graph_extract_task_status CHECK (((status)::text = ANY ((ARRAY['INIT'::character varying, 'RUNNING'::character varying, 'SUCCESS'::character varying, 'FAIL'::character varying])::text[])))
);


--
-- Name: TABLE graph_extract_task; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.graph_extract_task IS '图谱抽取任务（kb_id 为裸 kbase_id）';


--
-- Name: COLUMN graph_extract_task.kb_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.graph_extract_task.kb_id IS '裸 kbase_id（不含 graph_ 前缀）';


--
-- Name: COLUMN graph_extract_task.start_time; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.graph_extract_task.start_time IS '开始时间（timestamptz）';


--
-- Name: COLUMN graph_extract_task.finish_time; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.graph_extract_task.finish_time IS '结束时间（timestamptz）';


--
-- Name: graph_import_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.graph_import_task (
    task_id character varying(100) NOT NULL,
    kb_id character varying(1000) NOT NULL,
    schema_id character varying(100) NOT NULL,
    status character varying(50) NOT NULL,
    progress integer DEFAULT 0,
    entity_total integer DEFAULT 0,
    entity_success integer DEFAULT 0,
    entity_failed integer DEFAULT 0,
    edge_total integer DEFAULT 0,
    edge_success integer DEFAULT 0,
    edge_failed integer DEFAULT 0,
    failed_records jsonb,
    error_message character varying(20000),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_graph_import_task_status CHECK (((status)::text = ANY ((ARRAY['PENDING'::character varying, 'PROCESSING'::character varying, 'COMPLETED'::character varying, 'COMPLETED_WITH_ERRORS'::character varying, 'FAILED'::character varying])::text[])))
);


--
-- Name: TABLE graph_import_task; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.graph_import_task IS '图谱导入任务（文本状态机）';


--
-- Name: COLUMN graph_import_task.kb_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.graph_import_task.kb_id IS 'graph_<kbase_id>';


--
-- Name: graph_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.graph_registry (
    kb_id character varying(1000) NOT NULL,
    schema_id character varying(100) NOT NULL,
    graph_name character varying(100),
    graph_desc character varying(1000),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE graph_registry; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.graph_registry IS '图谱库登记（kb_id = graph_<uuid>）';


--
-- Name: COLUMN graph_registry.kb_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.graph_registry.kb_id IS '图谱库名 graph_<uuid>';


--
-- Name: graph_schema; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.graph_schema (
    schema_id character varying(100) NOT NULL,
    schema_name character varying(100) NOT NULL,
    schema_desc character varying(1000),
    schema_obj jsonb NOT NULL,
    created_by character varying(100),
    updated_by character varying(100),
    status smallint DEFAULT 0,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_graph_schema_status CHECK (((status IS NULL) OR (status = ANY (ARRAY[0, 1]))))
);


--
-- Name: TABLE graph_schema; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.graph_schema IS '图谱 schema 模板与快照';


--
-- Name: kb_directory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kb_directory (
    id character varying(32) NOT NULL,
    kbase_id character varying(32) NOT NULL,
    title character varying(255),
    parent_id character varying(32),
    parent_path character varying(500),
    type character varying(32) NOT NULL,
    created_by character varying(255),
    updated_by character varying(255),
    status smallint,
    fail_reason character varying(1024),
    file_from character varying(10),
    can_spread boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_kb_directory_status CHECK (((status IS NULL) OR (status = ANY (ARRAY['-4'::integer, '-3'::integer, '-2'::integer, '-1'::integer, 0, 1, 2])))),
    CONSTRAINT ck_kb_directory_type CHECK (((type)::text = ANY ((ARRAY['file'::character varying, 'folder'::character varying])::text[])))
);


--
-- Name: TABLE kb_directory; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.kb_directory IS '知识库目录与文件条目（type=file/folder；根目录 parent_id 为 NULL）';


--
-- Name: COLUMN kb_directory.parent_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_directory.parent_id IS '父目录；根目录为 NULL';


--
-- Name: COLUMN kb_directory.parent_path; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_directory.parent_path IS '物化路径：0 或 0-<id>-<id>';


--
-- Name: COLUMN kb_directory.type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_directory.type IS 'file / folder';


--
-- Name: COLUMN kb_directory.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_directory.status IS '文件状态：-4..2；文件夹为 NULL';


--
-- Name: COLUMN kb_directory.file_from; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_directory.file_from IS '文件来源：1=本地上传';


--
-- Name: kb_directory_property; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kb_directory_property (
    id character varying(32) NOT NULL,
    file_id character varying(32) NOT NULL,
    kbase_id character varying(32) NOT NULL,
    prop_name character varying(255),
    prop_value character varying(1024),
    created_by character varying(255),
    updated_by character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE kb_directory_property; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.kb_directory_property IS '文件/目录业务属性（file_id → kb_directory.id）';


--
-- Name: kb_import_task; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kb_import_task (
    id character varying(32) NOT NULL,
    task_type character varying(255),
    related_identifier_id character(32),
    created_by character varying(255),
    updated_by character varying(255),
    status character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_kb_import_task_status CHECK (((status IS NULL) OR ((status)::text = ANY ((ARRAY['PENDING'::character varying, 'RUNNING'::character varying, 'RETRY'::character varying, 'COMPLETED'::character varying, 'FAILED'::character varying])::text[]))))
);


--
-- Name: TABLE kb_import_task; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.kb_import_task IS '知识库导入任务（文本状态机）';


--
-- Name: kb_kbase; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kb_kbase (
    id integer NOT NULL,
    kbase_id character varying(32) NOT NULL,
    type character varying(255) DEFAULT 'document'::character varying NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(1000),
    head_icon character varying(255),
    es_index_name character varying(255),
    embedding_model character varying(255),
    created_by character varying(255),
    updated_by character varying(255),
    file_count_limit integer DEFAULT 3000 NOT NULL,
    org_id character varying(512),
    table_name character varying(255),
    operator_id integer,
    schema_id character varying(100),
    schema_obj jsonb,
    fail_reason_obj jsonb,
    category smallint DEFAULT 1 NOT NULL,
    status smallint DEFAULT 0 NOT NULL,
    process character varying(50),
    process_obj jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_kb_kbase_category CHECK ((category = ANY (ARRAY[1, 10]))),
    CONSTRAINT ck_kb_kbase_status CHECK ((status = ANY (ARRAY[0, 1, 2, 3, 4, 5, 6, 7, 8, 101, 102, 103, 104, 106]))),
    CONSTRAINT ck_kb_kbase_type CHECK (((type)::text = 'document'::text))
);


--
-- Name: TABLE kb_kbase; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.kb_kbase IS '知识库主表（category=1 文档库 / 10 图谱库；kbase_id 是动态表名后缀）';


--
-- Name: COLUMN kb_kbase.kbase_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_kbase.kbase_id IS '业务主键；同时是动态表名后缀（16/32 位 hex）';


--
-- Name: COLUMN kb_kbase.type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_kbase.type IS '子类型标识；当前不参与路由';


--
-- Name: COLUMN kb_kbase.es_index_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_kbase.es_index_name IS '真实 ES 索引名 kb_index_<kbase_id>';


--
-- Name: COLUMN kb_kbase.table_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_kbase.table_name IS '动态表基名：doc_<id>_vector 或 graph_<id>';


--
-- Name: COLUMN kb_kbase.operator_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_kbase.operator_id IS '建库所用的图谱算子 id（→ operator.id）';


--
-- Name: COLUMN kb_kbase.schema_obj; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_kbase.schema_obj IS '建库时的 schema 快照（不随 graph_schema 模板变化）';


--
-- Name: COLUMN kb_kbase.category; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_kbase.category IS '库类型：1=文档库，10=图谱库（路由唯一判据）';


--
-- Name: COLUMN kb_kbase.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.kb_kbase.status IS '知识库状态码：0-8 / 101-104 / 106';


--
-- Name: kb_kbase_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.kb_kbase ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.kb_kbase_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: kb_node_relation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kb_node_relation (
    id bigint NOT NULL,
    kbase_id character varying(32) NOT NULL,
    directory_id character varying(32) NOT NULL,
    node_id character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE kb_node_relation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.kb_node_relation IS '文件切片的节点关系（node_id 指向 doc_*_vector.node_id）';


--
-- Name: kb_node_relation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.kb_node_relation ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.kb_node_relation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: kb_storage_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kb_storage_registry (
    kbase_id character varying(64) NOT NULL,
    name character varying(255) NOT NULL,
    category smallint,
    vector_table character varying(255),
    chunk_table character varying(255),
    graph_vector_table character varying(255),
    embedding_model character varying(255),
    embedding_dim integer,
    state character varying(16) NOT NULL,
    detail text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE kb_storage_registry; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.kb_storage_registry IS '知识库存储生命周期（动态表名、维度、state）';


--
-- Name: model_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_registry (
    model_id character varying(64) NOT NULL,
    model_kind character varying(16) NOT NULL,
    model_name character varying(255) NOT NULL,
    display_name character varying(255),
    api_model character varying(255),
    base_url character varying(1000) NOT NULL,
    api_key character varying(2000),
    chat_path character varying(255),
    embeddings_path character varying(255),
    models_path character varying(255),
    rerank_path character varying(255),
    dimension integer,
    max_tokens integer,
    temperature numeric(6,4),
    timeout integer,
    is_reasoning boolean DEFAULT false NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    source character varying(16) DEFAULT 'user'::character varying NOT NULL,
    remark character varying(500),
    created_by character varying(255),
    thinking_mode character varying(16) DEFAULT 'none'::character varying NOT NULL,
    thinking_preset character varying(64),
    thinking_payload jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_model_registry_kind CHECK (((model_kind)::text = ANY ((ARRAY['llm'::character varying, 'embedding'::character varying, 'rerank'::character varying])::text[]))),
    CONSTRAINT ck_model_registry_source CHECK (((source)::text = ANY ((ARRAY['env'::character varying, 'user'::character varying])::text[]))),
    CONSTRAINT ck_model_registry_thinking_mode CHECK (((thinking_mode)::text = ANY ((ARRAY['none'::character varying, 'auto'::character varying, 'preset'::character varying, 'custom'::character varying])::text[])))
);


--
-- Name: TABLE model_registry; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.model_registry IS '模型注册表（llm/embedding/rerank；api_key 加密存储）';


--
-- Name: COLUMN model_registry.model_kind; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_registry.model_kind IS 'llm / embedding / rerank';


--
-- Name: COLUMN model_registry.source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_registry.source IS 'env / user';


--
-- Name: COLUMN model_registry.thinking_mode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.model_registry.thinking_mode IS 'none / auto / preset / custom';


--
-- Name: operator; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    name_en character varying(255),
    description character varying(1000) NOT NULL,
    description_en character varying(1000),
    module character varying(255) NOT NULL,
    visible_range character varying(255) NOT NULL,
    version character varying(255) NOT NULL,
    is_published boolean DEFAULT false NOT NULL,
    operator_zip_path character varying(512),
    operator_path character varying(512),
    created_by character varying(255),
    updated_by character varying(255),
    system boolean DEFAULT false NOT NULL,
    org_id character varying(512),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE operator; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.operator IS '算子主表（system=true 为内置算子）';


--
-- Name: COLUMN operator.module; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.operator.module IS '算子模块：retriever / pre-retriever / ...';


--
-- Name: COLUMN operator.is_published; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.operator.is_published IS '是否发布';


--
-- Name: COLUMN operator.system; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.operator.system IS '是否内置算子';


--
-- Name: operator_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.operator ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.operator_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: operator_param; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator_param (
    id integer NOT NULL,
    operator_id integer NOT NULL,
    arg_name character varying(255) NOT NULL,
    arg_type character varying(1000) NOT NULL,
    description character varying(1000) NOT NULL,
    default_value character varying(255),
    tips text,
    placeholder text,
    created_by character varying(255),
    updated_by character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE operator_param; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.operator_param IS '算子参数定义（operator_id, arg_name 唯一）';


--
-- Name: operator_param_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.operator_param ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.operator_param_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: operator_prop; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.operator_prop (
    id integer NOT NULL,
    operator_id integer NOT NULL,
    prop_name character varying(255) NOT NULL,
    prop_value character varying(255) NOT NULL,
    created_by character varying(255),
    updated_by character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE operator_prop; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.operator_prop IS '算子属性定义（operator_id, prop_name 唯一）';


--
-- Name: operator_prop_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.operator_prop ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.operator_prop_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: agent_api_key id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_api_key ALTER COLUMN id SET DEFAULT nextval('public.agent_api_key_id_seq'::regclass);


--
-- Name: auth_session id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_session ALTER COLUMN id SET DEFAULT nextval('public.auth_session_id_seq'::regclass);


--
-- Name: auth_user id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user ALTER COLUMN id SET DEFAULT nextval('public.auth_user_id_seq'::regclass);


--
-- Name: chat_query_trace id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_query_trace ALTER COLUMN id SET DEFAULT nextval('public.chat_query_trace_id_seq'::regclass);


--
-- Name: flow_draft id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flow_draft ALTER COLUMN id SET DEFAULT nextval('public.flow_draft_id_seq'::regclass);


--
-- Name: flow_release id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flow_release ALTER COLUMN id SET DEFAULT nextval('public.flow_release_id_seq'::regclass);


--
-- Name: flow_workflow id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flow_workflow ALTER COLUMN id SET DEFAULT nextval('public.flow_workflow_id_seq'::regclass);


--
-- Name: agent_api_key agent_api_key_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_api_key
    ADD CONSTRAINT agent_api_key_pkey PRIMARY KEY (id);


--
-- Name: agent_api_key_usage agent_api_key_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_api_key_usage
    ADD CONSTRAINT agent_api_key_usage_pkey PRIMARY KEY (key_prefix, usage_date);


--
-- Name: auth_session auth_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_session
    ADD CONSTRAINT auth_session_pkey PRIMARY KEY (id);


--
-- Name: auth_user auth_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_pkey PRIMARY KEY (id);


--
-- Name: chat_query_trace chat_query_trace_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_query_trace
    ADD CONSTRAINT chat_query_trace_pkey PRIMARY KEY (id);


--
-- Name: flow_draft flow_draft_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flow_draft
    ADD CONSTRAINT flow_draft_pkey PRIMARY KEY (id);


--
-- Name: flow_draft flow_draft_workflow_id_uidx; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flow_draft
    ADD CONSTRAINT flow_draft_workflow_id_uidx UNIQUE (workflow_id);


--
-- Name: flow_release flow_release_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flow_release
    ADD CONSTRAINT flow_release_pkey PRIMARY KEY (id);


--
-- Name: flow_release flow_release_workflow_version_uidx; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flow_release
    ADD CONSTRAINT flow_release_workflow_version_uidx UNIQUE (workflow_id, version);


--
-- Name: flow_workflow flow_workflow_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flow_workflow
    ADD CONSTRAINT flow_workflow_pkey PRIMARY KEY (id);


--
-- Name: flow_workflow flow_workflow_workflow_id_uidx; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flow_workflow
    ADD CONSTRAINT flow_workflow_workflow_id_uidx UNIQUE (workflow_id);


--
-- Name: graph_extract_task graph_extract_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.graph_extract_task
    ADD CONSTRAINT graph_extract_task_pkey PRIMARY KEY (id);


--
-- Name: graph_import_task graph_import_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.graph_import_task
    ADD CONSTRAINT graph_import_task_pkey PRIMARY KEY (task_id);


--
-- Name: graph_registry graph_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.graph_registry
    ADD CONSTRAINT graph_registry_pkey PRIMARY KEY (kb_id, schema_id);


--
-- Name: graph_schema graph_schema_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.graph_schema
    ADD CONSTRAINT graph_schema_pkey PRIMARY KEY (schema_id);


--
-- Name: kb_directory kb_directory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_directory
    ADD CONSTRAINT kb_directory_pkey PRIMARY KEY (id);


--
-- Name: kb_directory_property kb_directory_property_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_directory_property
    ADD CONSTRAINT kb_directory_property_pkey PRIMARY KEY (id);


--
-- Name: kb_import_task kb_import_task_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_import_task
    ADD CONSTRAINT kb_import_task_pkey PRIMARY KEY (id);


--
-- Name: kb_kbase kb_kbase_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_kbase
    ADD CONSTRAINT kb_kbase_pkey PRIMARY KEY (id);


--
-- Name: kb_node_relation kb_node_relation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_node_relation
    ADD CONSTRAINT kb_node_relation_pkey PRIMARY KEY (id);


--
-- Name: kb_storage_registry kb_storage_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_storage_registry
    ADD CONSTRAINT kb_storage_registry_pkey PRIMARY KEY (kbase_id);


--
-- Name: model_registry model_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_registry
    ADD CONSTRAINT model_registry_pkey PRIMARY KEY (model_id);


--
-- Name: operator_param operator_param_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_param
    ADD CONSTRAINT operator_param_pkey PRIMARY KEY (id);


--
-- Name: operator operator_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator
    ADD CONSTRAINT operator_pkey PRIMARY KEY (id);


--
-- Name: operator_prop operator_prop_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_prop
    ADD CONSTRAINT operator_prop_pkey PRIMARY KEY (id);


--
-- Name: agent_api_key_prefix_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX agent_api_key_prefix_uidx ON public.agent_api_key USING btree (key_prefix);


--
-- Name: idx_agent_api_key_usage_usage_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_api_key_usage_usage_date ON public.agent_api_key_usage USING btree (usage_date);


--
-- Name: auth_session_expires_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_session_expires_at_idx ON public.auth_session USING btree (expires_at);


--
-- Name: auth_session_token_hash_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX auth_session_token_hash_uidx ON public.auth_session USING btree (token_hash);


--
-- Name: auth_session_user_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_session_user_id_idx ON public.auth_session USING btree (user_id);


--
-- Name: auth_user_email_lower_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX auth_user_email_lower_uidx ON public.auth_user USING btree (lower((email)::text)) WHERE (email IS NOT NULL);


--
-- Name: auth_user_username_lower_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX auth_user_username_lower_uidx ON public.auth_user USING btree (lower((username)::text));


--
-- Name: graph_schema_name_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX graph_schema_name_uidx ON public.graph_schema USING btree (schema_name);


--
-- Name: idx_chat_query_trace_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_query_trace_created ON public.chat_query_trace USING btree (created_at DESC, id DESC);


--
-- Name: idx_chat_query_trace_conversation_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_query_trace_conversation_created ON public.chat_query_trace USING btree (conversation_id, created_at DESC, id DESC);


--
-- Name: idx_chat_query_trace_org_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_query_trace_org_created ON public.chat_query_trace USING btree (org_id, created_at DESC, id DESC);


--
-- Name: idx_chat_query_trace_trace_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_query_trace_trace_id ON public.chat_query_trace USING btree (trace_id);


--
-- Name: idx_chat_query_trace_workflow_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_chat_query_trace_workflow_created ON public.chat_query_trace USING btree (workflow_id, created_at DESC, id DESC);


--
-- Name: idx_directory_kbase_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_directory_kbase_parent ON public.kb_directory USING btree (kbase_id, parent_id);


--
-- Name: idx_flow_workflow_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_flow_workflow_created_by ON public.flow_workflow USING btree (created_by);


--
-- Name: idx_flow_workflow_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_flow_workflow_name ON public.flow_workflow USING btree (name);


--
-- Name: idx_graph_extract_task_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_graph_extract_task_created_at ON public.graph_extract_task USING btree (created_at);


--
-- Name: idx_graph_extract_task_kb_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_graph_extract_task_kb_id ON public.graph_extract_task USING btree (kb_id);


--
-- Name: idx_graph_extract_task_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_graph_extract_task_status ON public.graph_extract_task USING btree (status);


--
-- Name: idx_graph_import_task_kb_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_graph_import_task_kb_id ON public.graph_import_task USING btree (kb_id);


--
-- Name: idx_kb_directory_kbase_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_kb_directory_kbase_type ON public.kb_directory USING btree (kbase_id, type);


--
-- Name: kb_directory_folder_title_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX kb_directory_folder_title_uidx ON public.kb_directory USING btree (kbase_id, COALESCE(parent_id, ''::character varying), title) WHERE ((type)::text = 'folder'::text);


--
-- Name: kb_directory_property_file_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kb_directory_property_file_id_idx ON public.kb_directory_property USING btree (file_id);


--
-- Name: kb_directory_property_file_prop_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX kb_directory_property_file_prop_uidx ON public.kb_directory_property USING btree (file_id, prop_name);


--
-- Name: kb_directory_property_kbase_file_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kb_directory_property_kbase_file_idx ON public.kb_directory_property USING btree (kbase_id, file_id);


--
-- Name: kb_import_task_task_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kb_import_task_task_type_idx ON public.kb_import_task USING btree (task_type, related_identifier_id);


--
-- Name: kb_kbase_es_index_name_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX kb_kbase_es_index_name_uidx ON public.kb_kbase USING btree (es_index_name);


--
-- Name: kb_kbase_kbase_id_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX kb_kbase_kbase_id_uidx ON public.kb_kbase USING btree (kbase_id);


--
-- Name: kb_kbase_name_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX kb_kbase_name_uidx ON public.kb_kbase USING btree (name);


--
-- Name: kb_node_relation_directory_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kb_node_relation_directory_id_idx ON public.kb_node_relation USING btree (directory_id);


--
-- Name: kb_node_relation_kbase_node_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX kb_node_relation_kbase_node_uidx ON public.kb_node_relation USING btree (kbase_id, node_id);


--
-- Name: kb_storage_registry_state_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kb_storage_registry_state_idx ON public.kb_storage_registry USING btree (state);


--
-- Name: kb_storage_registry_vector_table_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX kb_storage_registry_vector_table_uidx ON public.kb_storage_registry USING btree (vector_table);


--
-- Name: model_registry_kind_name_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX model_registry_kind_name_uidx ON public.model_registry USING btree (model_kind, model_name);


--
-- Name: operator_module_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX operator_module_idx ON public.operator USING btree (module);


--
-- Name: operator_param_operator_arg_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX operator_param_operator_arg_uidx ON public.operator_param USING btree (operator_id, arg_name);


--
-- Name: operator_param_operator_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX operator_param_operator_id_idx ON public.operator_param USING btree (operator_id);


--
-- Name: operator_prop_operator_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX operator_prop_operator_id_idx ON public.operator_prop USING btree (operator_id);


--
-- Name: operator_prop_operator_prop_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX operator_prop_operator_prop_uidx ON public.operator_prop USING btree (operator_id, prop_name);


--
-- Name: agent_api_key agent_api_key_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER agent_api_key_set_updated_at BEFORE UPDATE ON public.agent_api_key FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: agent_api_key_usage agent_api_key_usage_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER agent_api_key_usage_set_updated_at BEFORE UPDATE ON public.agent_api_key_usage FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: auth_session auth_session_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER auth_session_set_updated_at BEFORE UPDATE ON public.auth_session FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: auth_user auth_user_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER auth_user_set_updated_at BEFORE UPDATE ON public.auth_user FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: chat_query_trace chat_query_trace_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER chat_query_trace_set_updated_at BEFORE UPDATE ON public.chat_query_trace FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: flow_draft flow_draft_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER flow_draft_set_updated_at BEFORE UPDATE ON public.flow_draft FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: flow_release flow_release_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER flow_release_set_updated_at BEFORE UPDATE ON public.flow_release FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: flow_workflow flow_workflow_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER flow_workflow_set_updated_at BEFORE UPDATE ON public.flow_workflow FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: graph_extract_task graph_extract_task_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER graph_extract_task_set_updated_at BEFORE UPDATE ON public.graph_extract_task FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: graph_import_task graph_import_task_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER graph_import_task_set_updated_at BEFORE UPDATE ON public.graph_import_task FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: graph_registry graph_registry_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER graph_registry_set_updated_at BEFORE UPDATE ON public.graph_registry FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: graph_schema graph_schema_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER graph_schema_set_updated_at BEFORE UPDATE ON public.graph_schema FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: kb_directory_property kb_directory_property_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER kb_directory_property_set_updated_at BEFORE UPDATE ON public.kb_directory_property FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: kb_directory kb_directory_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER kb_directory_set_updated_at BEFORE UPDATE ON public.kb_directory FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: kb_import_task kb_import_task_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER kb_import_task_set_updated_at BEFORE UPDATE ON public.kb_import_task FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: kb_kbase kb_kbase_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER kb_kbase_set_updated_at BEFORE UPDATE ON public.kb_kbase FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: kb_node_relation kb_node_relation_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER kb_node_relation_set_updated_at BEFORE UPDATE ON public.kb_node_relation FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: kb_storage_registry kb_storage_registry_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER kb_storage_registry_set_updated_at BEFORE UPDATE ON public.kb_storage_registry FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: model_registry model_registry_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER model_registry_set_updated_at BEFORE UPDATE ON public.model_registry FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: operator_param operator_param_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER operator_param_set_updated_at BEFORE UPDATE ON public.operator_param FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: operator_prop operator_prop_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER operator_prop_set_updated_at BEFORE UPDATE ON public.operator_prop FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: operator operator_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER operator_set_updated_at BEFORE UPDATE ON public.operator FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: agent_api_key_usage fk_agent_api_key_usage_agent_api_key; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_api_key_usage
    ADD CONSTRAINT fk_agent_api_key_usage_agent_api_key FOREIGN KEY (key_prefix) REFERENCES public.agent_api_key(key_prefix) ON DELETE CASCADE;


--
-- Name: graph_extract_task fk_graph_extract_task_kbase; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.graph_extract_task
    ADD CONSTRAINT fk_graph_extract_task_kbase FOREIGN KEY (kb_id) REFERENCES public.kb_kbase(kbase_id) ON DELETE CASCADE;


--
-- Name: kb_directory fk_kb_directory_kbase; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_directory
    ADD CONSTRAINT fk_kb_directory_kbase FOREIGN KEY (kbase_id) REFERENCES public.kb_kbase(kbase_id) ON DELETE CASCADE;


--
-- Name: kb_directory fk_kb_directory_parent; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_directory
    ADD CONSTRAINT fk_kb_directory_parent FOREIGN KEY (parent_id) REFERENCES public.kb_directory(id) ON DELETE CASCADE;


--
-- Name: kb_directory_property fk_kb_directory_property_file; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_directory_property
    ADD CONSTRAINT fk_kb_directory_property_file FOREIGN KEY (file_id) REFERENCES public.kb_directory(id) ON DELETE CASCADE;


--
-- Name: kb_kbase fk_kb_kbase_operator; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_kbase
    ADD CONSTRAINT fk_kb_kbase_operator FOREIGN KEY (operator_id) REFERENCES public.operator(id) ON DELETE SET NULL;


--
-- Name: kb_node_relation fk_kb_node_relation_directory; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_node_relation
    ADD CONSTRAINT fk_kb_node_relation_directory FOREIGN KEY (directory_id) REFERENCES public.kb_directory(id) ON DELETE CASCADE;


--
-- Name: kb_node_relation fk_kb_node_relation_kbase; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_node_relation
    ADD CONSTRAINT fk_kb_node_relation_kbase FOREIGN KEY (kbase_id) REFERENCES public.kb_kbase(kbase_id) ON DELETE CASCADE;


--
-- Name: kb_storage_registry fk_kb_storage_registry_kbase; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kb_storage_registry
    ADD CONSTRAINT fk_kb_storage_registry_kbase FOREIGN KEY (kbase_id) REFERENCES public.kb_kbase(kbase_id) ON DELETE CASCADE;


--
-- Name: operator_param fk_operator_param_operator; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_param
    ADD CONSTRAINT fk_operator_param_operator FOREIGN KEY (operator_id) REFERENCES public.operator(id) ON DELETE CASCADE;


--
-- Name: operator_prop fk_operator_prop_operator; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.operator_prop
    ADD CONSTRAINT fk_operator_prop_operator FOREIGN KEY (operator_id) REFERENCES public.operator(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--



-- 图谱向量检索：pgvector 默认 hnsw.ef_search=40，带 key_type / labels 过滤时
-- 候选先裁到 40 条再过滤，top-10 实体召回只有 48–58%。设为 200 后 MetaQA
-- 实测 topic 召回回到 98/100/94%。
-- 本文件只在空卷时执行；已有部署可手工执行同一条 ALTER DATABASE。
DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I SET hnsw.ef_search = 200',
                   current_database());
END $$;
