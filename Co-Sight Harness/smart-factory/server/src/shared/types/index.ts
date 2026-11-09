/**
 * Smart Factory 领域模型与接口 DTO。
 *
 * 与 4.04 消息 §2 同形：时间一律是 ISO 字符串，content 一律是对象（库里是 JSON 字符串，
 * 由 repo 负责解析与序列化）。前端 web/src/shared/types 是对照副本。
 */

export type InstanceStage = 'development' | 'preview' | 'runtime' | 'evaluation';
export type SessionStatus = 'not_started' | 'in_progress' | 'completed';
/** 会话级审批模式；与 cosight-viewer 的 mode 取值一致。 */
export type SessionMode = 'read_only' | 'workspace_write' | 'full_access';
/** 会话级推理强度；与 Claude Code CLI 的 effort 取值一致。 */
export type SessionEffort = 'low' | 'medium' | 'high' | 'xhigh' | 'max';
export type AgentRunStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'aborted';
export type MessageRole = 'user' | 'assistant' | 'system';
export type MessageType =
  | 'text'
  | 'thinking'
  | 'tool_use'
  | 'tool_result'
  | 'approval'
  | 'tool_interactive'
  | 'error'
  | 'status';
export type MessageStatus = 'pending' | 'approved' | 'approved_all' | 'rejected' | 'answered' | 'aborted';
export type ApprovalDecision = 'approved' | 'approved_all' | 'rejected' | 'aborted';
export type DecisionSource = 'user' | 'approved_all_auto' | 'abort' | 'restart';

/** 列表接口的统一分页响应；page / pageSize 回显校验后的请求值。 */
export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

/**
 * 智能体来源：随产品提供（`builtin`）还是用户建出来的（`user`，含首页创建与启动收养）。
 *
 * 它是**事实**，不是权限位：只读、仅 runtime、无工作区都由它派生。
 * 刻意不放 `tags` —— 标签是用户可编辑的展示元数据，来源不能由客户端决定。
 */
export type AgentSource = 'user' | 'builtin';

/** 智能体行（无派生字段）：repo 的返回形状。 */
export interface AgentRow {
  id: string;
  /** 框架工作区 id；建后不可改。内置智能体（source=builtin）恒为 null */
  workspaceId: string | null;
  /** 来源：内置智能体随产品提供（{COSIGHT_HOME}/smart-factory/builtin-agents/{id}/），boot seed 登记，只读、仅 runtime */
  source: AgentSource;
  name: string;
  description: string;
  /**
   * 创建时的第一句需求原文（`POST /agents` 的 `init.input`）；空串 = 没带 `init`。
   *
   * 建后不可改，也**不是**对话内容：它不产生消息、不起 run，只是让原文不再只活在前端
   * 路由 state 里 —— 设计页刷新 / 再次进入时可以据此恢复首轮（见 08-agent.md §3.1）。
   */
  initialInput: string;
  /**
   * 创建时挂的附件（`POST /agents` 的 `init.attachments`），服务端校验后的真实绝对路径；
   * 空数组 = 没带附件。建后不可改，也**不是**对话内容（不产生消息、不起 run）。
   */
  initialAttachments: string[];
  /**
   * 当前绑定的知识检索工作流 id（`RAG_Workflow_xxx`）；空串 = 明确没有 / 已取消。
   *
   * 创建时从 `init.input` 的 `--knowledge-workflow-id` 解析落库，之后由 update 修改。
   * 库里是 `String?`：NULL 只表示本列引入前的存量行，读取时按 `initialInput` 现推 ——
   * 接口层永远归一成字符串，调用方不需要区分 NULL 与空串。
   */
  knowledgeWorkflowId: string;
  /** 标签，缺省 `[]`（不是 null）。库里是一列 JSON 数组串，由 repo 编解码 */
  tags: string[];
  icon: string;
  createdAt: string;
  updatedAt: string;
}

/**
 * 智能体 DTO（契约 5.01）。
 *
 * `dir` / `runtimeDir` 都不入库：先取 `workspaceId`，再经框架工作区记录拿到 `directory`，
 * 拼成 `<directory>/.smart-factory/agents/{id}`。只表示约定的位置，不代表此刻一定存在。
 */
export interface Agent extends AgentRow {
  dir: string;
  /**
   * 运行时工作目录（runtime 会话的 cwd）：内置智能体 = 定义目录本身（与 dir 相同）；
   * 普通智能体 = development 产物中最新版本目录。产物未生成 / 布局不完整 / 门禁未过
   * 时为 null —— null 即「此刻还没有可运行的目录」，判定口径与 runtime 起跑门禁同源。
   */
  runtimeDir: string | null;
  /**
   * 产物状态：普通行与 `GET /agents/{id}/production` 的 `status` **同源**（同一次
   * `readProductionStatus` 派生，不落库）。内置智能体开箱即用，恒为 `completed`。
   * 单条状态读取失败（盘不可读等）才为 null，不拖垮列表 —— 前端一律按不可用处理。
   */
  status: AgentProductionStatus | null;
}

/**
 * 产物里的一条可执行技能（`<runtimeDir>/.claude/skills/<目录名>/SKILL.md`）。
 *
 * 与 `GET /agents/{id}/skills` 的 `items` 同型：详情里的「可执行」清单与装配弹窗看到的是
 * 同一份字段，只是过滤口径不同（那边是管理视图，缺 `SKILL.md` 的坏目录也列出来才能删）。
 */
export interface AgentSkillItem {
  /**
   * `.claude/skills` 下的目录名，也是 `/` 命令名；删除时用它。
   * 定义目录自己打开的插件技能是 `plugin:skill`（如 `drive:drive`），不属于产物、不可删。
   */
  name: string;
  /** SKILL.md frontmatter 的 name；缺失时等于目录名（插件技能回落为去掉前缀的目录名） */
  displayName: string;
  description: string;
  /** frontmatter 的 version（如 `1.0`）；没有则空串 */
  version: string;
  /** 技能目录绝对路径（插件技能指向插件载荷目录） */
  path: string;
  updatedAt: string;
}

/**
 * 产物里的一条可执行斜杠命令（`<runtimeDir>/.claude/commands/` 下的 `.md`，含子目录）。
 *
 * 命令名只取文件名：`commands/ci/build.md` 在引擎里就是 `/build`，子目录只作为
 * `(project:ci)` 分组标签出现在帮助里 —— 因此 `namespace` 只用于展示，不参与命令名。
 * 定义目录自己打开的插件命令是 `plugin:command`（如 `cosightbot:pkm`），不属于产物、不可删。
 */
export interface AgentCommandItem {
  /**
   * 命令名（相对 `.claude/commands` 去掉 `.md`），也是 `/` 菜单里的 `/<name>`。
   * 插件命令带插件前缀（`plugin:command`）。
   */
  name: string;
  /**
   * 所在子目录（用 `/` 连接）；顶层命令为空串。只用于展示分组。
   * 插件命令的 `namespace` 是插件名（如 `cosightbot`），命令名本身已带同一前缀。
   */
  namespace: string;
  /** frontmatter 的 description；无 frontmatter / 读不到为空串 */
  description: string;
  /** 命令文件的绝对路径（插件命令指向插件载荷目录） */
  path: string;
  /** 文件 mtime 的 ISO 串 */
  updatedAt: string;
}

/**
 * 智能体详情（`GET /agents/{agentId}`）。
 *
 * 比列表多两样**当前可执行**的清单：引擎在 `runtimeDir` 的 `.claude` 下会自动发现的
 * 技能与斜杠命令。`runtimeDir === null`（产物未就绪 / 未生成）时两者都是空数组 ——
 * 「为什么空」由 `status` 回答，需要人读原因走 `/production`，详情不重复一份 ready / reasons。
 */
export interface AgentDetail extends Agent {
  skills: AgentSkillItem[];
  commands: AgentCommandItem[];
  /**
   * 当前产物里是否已注入知识检索技能（`rag-knowledge-search`）。
   *
   * 与 `knowledgeWorkflowId` 是两件事：后者是「下次构建要用的配置」，这是「已经生成好的
   * 产物里有没有」。取消配置不会改动产物 —— 前端据此提示「产物仍在使用知识检索」，
   * 并给出「移除并重建」的入口。`runtimeDir` 为 null（还没产物）时恒为 false。
   */
  knowledgeInjected: boolean;
}

export interface Instance {
  id: string;
  /**
   * 智能体实例非空；目录实例为 null。
   *
   * 「是不是目录实例」只看这一列，不看 `stage` —— 工坊的目录实例跑在 `development`，
   * runtime 会话虽然是智能体实例，起 run 时的 cwd 也是一个目录（由产物推导）。
   */
  agentId: string | null;
  stage: InstanceStage;
  /** 目录实例非空（创建时给定的绝对路径）；智能体实例为 null（运行期推导，不落库） */
  cwd: string | null;
  engine: string;
  createdAt: string;
  updatedAt: string;
}

// ── 智能体产物状态（契约 4.10 / 5.03） ──────────────────────────────────────
// 由服务端读 AgentGenesis 的生产过程状态与交付门禁派生；不落库、不下发绝对路径。

export type AgentProductionStatus = 'not_started' | 'building' | 'blocked' | 'failed' | 'completed';
export type ProductionLane = 'full' | 'fast';
export type DeliveryVerdict = 'PASS' | 'CONCERNS' | 'FAIL';

/** `GET /agents/{agentId}/production` 的响应；ready 为 true 才允许进入预览 / 评估。 */
export interface AgentProductionView {
  agentId: string;
  status: AgentProductionStatus;
  /** `status === 'completed'` 的派生布尔，前端直接用。 */
  ready: boolean;
  lane: ProductionLane | null;

  pipeline: {
    /** 原始 pipeline_status（IN_PROGRESS / COMPLETED / BLOCKED / FAILED），排障用。 */
    status: string | null;
    currentStep: string | null;
    completedSteps: number;
    lastUpdate: string | null;
    retryCount: number | null;
    retryBudget: number | null;
  } | null;

  delivery: {
    verdict: DeliveryVerdict | null;
    /** 证据文件名，如 step-4-implementation.json。 */
    source: string | null;
    /** 门禁 concerns（内部诊断信息，不建议原样展示给用户）。 */
    concerns: string[];
  } | null;

  product: {
    /** `output/agents` 下的唯一子目录名（AgentGenesis 的 `{name}`）。 */
    name: string;
    version: string;
    /** 相对 development 目录的路径。 */
    path: string;
    updatedAt: string;
  } | null;

  /** ready=false 时的用户语义原因，不含内部 gate / step 编号。 */
  reasons: string[];
}

/** 会话行（无内联实例）：repo 的返回形状 */
export interface SessionRow {
  id: string;
  instanceId: string;
  name: string;
  status: SessionStatus;
  /** 会话级框架模型 uuid，任何会话都非空；建会话时必填，之后只能切换成另一个非空模型，起 run 时按详情解析，无任何回退 */
  modelId: string;
  /** 引擎接续标识；null = 开新引擎会话 */
  resumeSessionId: string | null;
  /** 会话级审批模式；库列名是 mode，DTO 字段名是 approvalMode */
  approvalMode: SessionMode;
  /** 会话级「允许所有」；用户选 approved_all 时置真，审批模式降级时复位 */
  approvedAll: boolean;
  /** 会话级推理强度 */
  effort: SessionEffort;
  createdAt: string;
  updatedAt: string;
}

/** 会话 DTO：契约要求内联 instance，由 session 层装配 */
export interface Session extends SessionRow {
  instance: Instance;
  /** 派生字段：全部消息条数（所有 type 都计入） */
  messageCount: number;
  /** 派生字段：最新一条 type='text' 消息的 content.text；仅列表填充 */
  lastMessage: string | null;
  /** 派生字段：第一条 role='user' 且 type='text' 消息的 content.text；仅列表填充 */
  firstUserMessage: string | null;
}

/** run 行（无派生字段）：repo 的返回形状 */
export interface RunRow {
  id: string;
  sessionId: string;
  instanceId: string;
  /** 父 run id；null = 顶层 run */
  parentRunId: string | null;
  /** 触发本次委派的父工具调用 id */
  parentToolUseId: string | null;
  /** 子 agent 类型；顶层 run 为 null */
  subagentType: string | null;
  /** 委派深度；顶层 run 为 0 */
  delegationDepth: number;
  /** 引擎任务 id，与 task_started 的 task_id 对应 */
  taskId: string | null;
  status: AgentRunStatus;
  error: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  createdAt: string;
}

/** run DTO：契约要求派生 waiting，由 session 层装配 */
export interface Run extends RunRow {
  waiting: { count: number; since: string } | null;
}

export interface QuestionOption {
  label: string;
  description?: string;
}

export interface QuestionItem {
  header: string;
  question: string;
  options?: QuestionOption[];
  multiSelect?: boolean;
}

/** type='approval'：挂起时只有前半部分，结算后追加 decision / decisionSource */
export interface ApprovalContent {
  toolCallId?: string;
  toolName?: string;
  title: string;
  description?: string;
  input?: unknown;
  /** UI 是否可以提供「本会话全部允许」；仅当引擎明确禁止时给 false，缺省表示可以 */
  allowAll?: boolean;
  decision?: ApprovalDecision;
  decisionSource?: DecisionSource;
}

/** type='tool_interactive'：answers 的 key 是 questions[].question 原文（与 CLI AskUserQuestion 一致） */
export interface InteractiveContent {
  toolCallId?: string;
  toolName?: string;
  questions: QuestionItem[];
  answers?: Record<string, string[]>;
}

/**
 * 用户消息带进来的一份本机文件。
 *
 * 端侧形态下没有上传：`name` 就是**绝对路径**，引擎自己按路径读。
 * `id` 只给前端做列表 key，服务端按顺序生成，不接收客户端的值。
 */
export interface MessageFile {
  id: string;
  name: string;
}

export type MessageContent = ApprovalContent | InteractiveContent | Record<string, unknown>;

export interface Message {
  id: string;
  sessionId: string;
  runId: string | null;
  seq: number;
  role: MessageRole;
  type: MessageType;
  status: MessageStatus | null;
  content: MessageContent;
  createdAt: string;
}

/** messages/list 的响应：seq 升序，nextAfterSeq 仅在返回条数等于 limit 时非 null */
export interface MessagePage {
  items: Message[];
  nextAfterSeq: number | null;
}

/** 产物目录项（契约 §1.6）：size 单字节，dir 恒为 0 */
export type ArtifactEntryType = 'dir' | 'file';
export interface ArtifactEntry {
  name: string;
  type: ArtifactEntryType;
  size: number;
  mtime: string;
}

/** artifacts/file 的响应：content 为 utf-8 全文，超限 413 */
export interface ArtifactFile {
  name: string;
  size: number;
  mtime: string;
  content: string;
}

// ── 评估报告（契约 4.09-评估报告） ──────────────────────────────────────────
// 全部由服务端从评估产物文件归一化而来；字段口径见该文档 §5，此处只声明形状。

export type EvaluationReportStatus = 'pending' | 'running' | 'completed' | 'partial' | 'failed';
export type EvaluationStepState = 'pending' | 'running' | 'done' | 'failed';

export interface EvaluationStep {
  state: EvaluationStepState;
  /** 该步骤完成 / 失败的时间；未完成或无法判断为 null */
  at: string | null;
}

export interface EvaluationAuditSummary {
  /** 审计平均总分 0–5（batch-summary.aggregate.averageTotalScore） */
  average: number | null;
  /** 总分最低那条用例的 grade（「最差一条决定总体等级」，§5.3） */
  grade: string | null;
  /** 参与审计的用例数 */
  evaluated: number;
  /** 审计执行失败的用例数（meta.failed），不是测试失败数 */
  failed: number;
  /** 未通过检查的去重 checkId 数 */
  failedChecks: number;
}

export interface EvaluationReportSummary {
  reportId: string;
  agentId: string;
  /** generated manifest 的 task_id，缺失用 reportId */
  title: string;
  status: EvaluationReportStatus;
  createdAt: string;
  updatedAt: string;
  /** 相对 evaluation 根的目录，直接喂给 /artifacts/* */
  dir: string;

  pipeline: {
    plan: EvaluationStep;
    run: EvaluationStep;
    score: EvaluationStep;
    audit: EvaluationStep;
  };

  counts: {
    total: number;
    /** eval.status === 'ok' 的条数 */
    valid: number;
    /** 已评分但没评出结果（eval.status !== 'ok'） */
    invalid: number;
    /** 还没评分：eval 字段缺失（生成 / 执行阶段） */
    pending: number;
    passed: number;
    failed: number;
    expectedTotal: number;
    expectedHit: number;
    expectedMiss: number;
  };

  scores: {
    /** 逐条 weighted_score 的算术平均，Number(toFixed(2)) */
    weightedAverage: number | null;
    /** passed / valid，0–1 */
    passRate: number | null;
    dimensions: {
      correctness: number | null;
      completeness: number | null;
      formatCompliance: number | null;
      actionability: number | null;
    };
    weights: {
      correctness: number;
      completeness: number;
      formatCompliance: number;
      actionability: number;
    };
  };

  thresholds: {
    weighted: number | null;
    correctness: number | null;
    completeness: number | null;
    met: boolean | null;
  };

  audit: EvaluationAuditSummary | null;

  /** 生成与执行看到的产物 sha 不一致（run-manifest.matches === false） */
  stale: boolean | null;

  /** 非致命问题：缺文件、JSON 解析失败等 */
  warnings: string[];
}

export interface EvaluationToolInfo {
  name: string | null;
  version: string | null;
}

export interface EvaluationReportDetail extends EvaluationReportSummary {
  tools: {
    generate: EvaluationToolInfo;
    evaluate: EvaluationToolInfo;
    audit: EvaluationToolInfo & { rubricVersion: string | null };
  };

  judge: {
    model: string | null;
    mainAgentModel: string | null;
  };

  coverage: {
    tier: string | null;
    target: number | null;
    actual: number | null;
    fromGwt: number | null;
    fromLlm: number | null;
    repairRounds: number | null;
    dimensions: {
      key: string;
      name: string;
      weight: number;
      count: number;
    }[];
    rejected: {
      sourceRef: string;
      reason: string;
    }[];
  } | null;

  auditDetails: {
    dimensions: {
      key: string;
      name: string;
      weight: number;
      average: number | null;
      scoredCount: number;
    }[];
    /** 全部检查项，每条 (caseId, checkId) 一行，通过与未通过都在 */
    checks: {
      caseId: string;
      dimension: string;
      checkId: string;
      passed: boolean;
      severity: string;
      expected: unknown;
      actual: unknown;
      evidence: string | null;
    }[];
  } | null;

  environment: {
    generatedAt: string | null;
    auditedAt: string | null;
    concurrency: number | null;
    rubric: { file: string | null; sha256: string | null };
    inputSeed: string | null;
    agentSha256: string | null;
    agentShaMatches: boolean | null;
    isolation: string | null;
  };

  /** 相对报告目录的文件路径；不存在为 null。前端用 /artifacts/file 读 */
  files: {
    generatedReportMd: string | null;
    reportMd: string | null;
    auditReportMd: string | null;
    seedJsonl: string | null;
  };
}

export type EvaluationCaseStatus = 'passed' | 'failed' | 'invalid';

export interface EvaluationCaseSummary {
  caseId: string;
  /** seed.jsonl 中的顺序，从 0 开始；列表按它升序 */
  index: number;
  dimension: string;
  dimensionLabel: string;
  capabilityRef: string | null;
  input: string;
  status: EvaluationCaseStatus;
  /** false = 还没评分（生成 / 执行阶段），与「评了但失败」的 invalid 区分 */
  scored: boolean;
  weightedScore: number | null;
  scores: {
    correctness: number | null;
    completeness: number | null;
    formatCompliance: number | null;
    actionability: number | null;
  };
  expected: { total: number; hit: number; miss: number };
  run: {
    /** 评估工具单条用例的执行结果，不是服务端 Run.status */
    status: 'passed' | 'failed' | 'error' | 'timeout' | 'unknown' | null;
    elapsedMs: number | null;
    turns: number | null;
    exitCode: number | null;
    attempts: number;
  };
  audit: {
    totalScore: number | null;
    grade: string | null;
  } | null;
  warnings: string[];
}

export interface EvaluationCaseDetail extends EvaluationCaseSummary {
  precondition: string | null;

  expectedItems: {
    text: string;
    verdict: 'hit' | 'miss' | 'unknown';
    note: string | null;
  }[];

  reasoning: string | null;
  /** run 输出预览，超 4000 字符截断 */
  resultPreview: string | null;

  usage: {
    inputTokens: number | null;
    outputTokens: number | null;
    costUsd: number | null;
  } | null;

  auditDetails: {
    verdict: string | null;
    dimensions: {
      key: string;
      name: string | null;
      weight: number | null;
      score: number | null;
      weightedScore: number | null;
      label: string | null;
      summary: string | null;
      failedTasks: string[];
    }[];
    checks: {
      dimension: string;
      checkId: string;
      passed: boolean;
      severity: string;
      expected: unknown;
      actual: unknown;
      evidence: string | null;
    }[];
  } | null;

  /** 相对报告目录的文件路径；前端用 artifacts/file?path={report.dir}/{file} 读 */
  files: {
    result: string | null;
    timing: string | null;
    stdout: string | null;
    stderr: string | null;
    session: string | null;
    auditReportMd: string | null;
    auditReportJson: string | null;
  };
}
