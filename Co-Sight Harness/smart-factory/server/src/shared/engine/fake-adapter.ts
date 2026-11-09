import type { SessionEffort, SessionMode } from '../types/index.js';
import type {
  EngineAdapter,
  EngineContext,
  EngineEvent,
  EngineInfo,
  EngineModel,
  EngineSlashCommand,
  MessageDraft,
  SubagentMeta,
} from './port.js';

const CHUNK_SIZE = 8;
/** 等待中止信号的轮询间隔；只用于带超时的等待，不用于事件同步 */
const ABORT_POLL_INTERVAL_MS = 10;

/**
 * 触发审批 / 交互 / 内容形态的提示词标记。
 *
 * 桩适配器靠它决定是否调用 `requestInput` 或落哪几种消息，端到端脚本直接复用这些常量。
 */
export const FAKE_TRIGGER = {
  approval: '需要审批',
  /** 同一 run 内先后请求两次审批，第二次在第一次应答之后发出：覆盖 approved_all 短路 */
  approvalTwice: '连续审批',
  interactive: '需要提问',
  thinking: '带思考',
  tool: '带工具',
  /** 触发一次引擎会话标识回调，覆盖宿主落库 resume 标识的链路 */
  session: '带会话',
  /** 触发一次子代理委派：父 Task 工具、子 run 内容、task 生命周期与父 Task 结果 */
  subagent: '带子代理',
  /** 子代理以 failed 收尾：覆盖失败映射与 error 透传 */
  subagentFail: '子代理失败',
  /** 子代理以 stopped 收尾：覆盖宿主把 stopped 映射为 aborted */
  subagentStop: '子代理停止',
  /** 子代理先 stopped 再以同一 task_id 恢复：覆盖 worker 重启与子 run 重建 */
  subagentResume: '子代理恢复',
  /** 子代理挂起后等待中止：覆盖子 run 级联中止与迟到事件丢弃 */
  subagentAbort: '子代理中止',
  /** 嵌套子代理：内层 task_started 带 parentTaskId 且不给 spawn_depth，由宿主按父深度补齐 */
  subagentNested: '嵌套子代理',
} as const;

/** 子代理流程的固定标识：测试按这些值对照子 run 与消息归属 */
const SUBAGENT = {
  taskId: 'task_fake_1',
  runId: 'run_fake_1',
  toolUseId: 'toolu_fake_task_1',
  toolCallId: 'toolu_fake_child_1',
  subagentType: 'general-purpose',
} as const;

/** 恢复后的同一 task：task_id 不变、run_id 变，宿主必须新建子 run */
const RESUMED = { ...SUBAGENT, runId: 'run_fake_1_resumed' } as const;

/** 嵌套子代理的内层任务标识 */
const NESTED = {
  taskId: 'task_fake_2',
  runId: 'run_fake_2',
  toolUseId: 'toolu_fake_task_2',
  toolCallId: 'toolu_fake_child_2',
  subagentType: 'general-purpose',
} as const;

/** 中止后迟到的子代理内容：宿主必须丢弃，不得写进已终态子 run */
const LATE_SUBAGENT_TEXT = '子代理中止后的迟到消息';

/** 「带思考」的思考正文：先流式发增量，再落一条终稿，与真机两步同形 */
const THINKING_TEXT = '桩适配器思考了一段';

/** 「带工具」的一对调用与结果：字段名与 4.04 消息 §3 的 content 形状一致 */
const TOOL_CALL = { toolCallId: 'toolu_fake_1', toolName: 'Bash', input: { command: 'echo hi' } };
const TOOL_RESULT = { toolCallId: 'toolu_fake_1', output: 'hi', isError: false };

/** 父 run 的 Task 调用与结果：toolCallId 与子代理 task_started 的 toolUseId 对应 */
const TASK_CALL = {
  toolCallId: SUBAGENT.toolUseId,
  toolName: 'Task',
  input: { subagent_type: SUBAGENT.subagentType, description: '桩子代理任务' },
};
const TASK_RESULT = { toolCallId: SUBAGENT.toolUseId, output: '子代理完成', isError: false };

/** 一次 run 的流程形态：由提示词标记决定。 */
interface FlowPlan {
  aborting: boolean;
  subagent: boolean;
  nested: boolean;
  approvalCount: number;
  thinking: boolean;
  tool: boolean;
  interactive: boolean;
}

/** 引擎任务标识：task 与 state 共用。 */
interface TaskIds {
  taskId: string;
  runId: string;
  toolUseId: string;
  subagentType: string;
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * 桩引擎：把输入分段回显，按提示词标记可选触发审批（可连续两次）与一次交互，以及思考 / 工具消息落库。
 *
 * 不依赖任何外部服务，供端到端验证使用。
 */
export class FakeAdapter implements EngineAdapter {
  readonly engine = 'fake';

  /** 近一次 run 收到的模型配置：集成测试断言「切换后下个 run 用新值」用 */
  static lastModel: EngineModel | null = null;
  /** 近一次 run 收到的会话级参数：集成测试断言转发是否正确用 */
  static lastResumeSessionId: string | null = null;
  static lastMode: SessionMode | null = null;
  static lastEffort: SessionEffort | null = null;
  /** 测试观测：中止流程是否真的收到了宿主的中止信号 */
  static lastAborted = false;
  /** 测试观测：中止流程已发出迟到内容（宿主已处理该事件） */
  static lateContentEmitted = false;

  /** 桩引擎的会话标题：只给「带会话」产出的那个标识，覆盖宿主补会话名的链路 */
  async sessionTitle(resumeSessionId: string): Promise<string | null> {
    return resumeSessionId === 'fake-sdk-session' ? '桩会话标题' : null;
  }

  /** 桩引擎的 `/` 清单：固定两条（一条自带、一条用户），不启动子进程；自带项应被端点过滤。 */
  async commands(_cwd: string): Promise<EngineSlashCommand[]> {
    return [
      { name: 'fake-command', description: '桩引擎的固定命令', argumentHint: '' },
      { name: 'fake-builtin', description: '桩引擎的自带命令', argumentHint: '', builtin: true },
    ];
  }

  /** 桩引擎的信息：固定值，断言不随开发机环境漂。 */
  async info(cwd: string): Promise<EngineInfo> {
    return { engine: this.engine, cwd, version: '0.0.0-fake', commandCount: 1 };
  }

  async run(ctx: EngineContext): Promise<{ output: string }> {
    this.recordContext(ctx);
    if (ctx.prompt.includes(FAKE_TRIGGER.session)) await ctx.onSessionId?.('fake-sdk-session');

    const output = `收到：${ctx.prompt}`;
    await this.stream(ctx, output.slice(0, CHUNK_SIZE));

    if (await this.runFlow(ctx, this.planOf(ctx.prompt))) return { output: '' };

    await this.stream(ctx, output.slice(CHUNK_SIZE));
    await this.message(ctx, output);
    return { output };
  }

  /** 按流程形态执行；返回 true 表示已中止，调用方不再产出收尾内容。 */
  private async runFlow(ctx: EngineContext, plan: FlowPlan): Promise<boolean> {
    if (plan.aborting) {
      await this.subagentAbortFlow(ctx);
      return true;
    }
    if (plan.subagent) await this.subagentFlow(ctx, plan);
    if (plan.thinking) await this.thinkingFlow(ctx);
    if (plan.tool) await this.toolFlow(ctx);
    // 子代理流程已覆盖审批链路：避免同一条提示词再走一遍顶层审批
    if (!plan.subagent && plan.approvalCount > 0 && (await this.approvalFlow(ctx, plan.approvalCount))) return true;
    if (plan.interactive) await this.interactiveFlow(ctx);
    return false;
  }

  private recordContext(ctx: EngineContext): void {
    FakeAdapter.lastModel = ctx.model;
    FakeAdapter.lastResumeSessionId = ctx.resumeSessionId;
    FakeAdapter.lastMode = ctx.mode;
    FakeAdapter.lastEffort = ctx.effort;
  }

  private planOf(prompt: string): FlowPlan {
    const resume = prompt.includes(FAKE_TRIGGER.subagentResume);
    const aborting = prompt.includes(FAKE_TRIGGER.subagentAbort);
    const nested = prompt.includes(FAKE_TRIGGER.subagentNested);
    return {
      aborting,
      nested,
      subagent:
        aborting ||
        nested ||
        resume ||
        prompt.includes(FAKE_TRIGGER.subagent) ||
        prompt.includes(FAKE_TRIGGER.subagentFail) ||
        prompt.includes(FAKE_TRIGGER.subagentStop),
      approvalCount: prompt.includes(FAKE_TRIGGER.approvalTwice) ? 2 : prompt.includes(FAKE_TRIGGER.approval) ? 1 : 0,
      thinking: prompt.includes(FAKE_TRIGGER.thinking),
      tool: prompt.includes(FAKE_TRIGGER.tool),
      interactive: prompt.includes(FAKE_TRIGGER.interactive),
    };
  }

  private async thinkingFlow(ctx: EngineContext): Promise<void> {
    await this.stream(ctx, THINKING_TEXT, 'thinking');
    await this.draft(ctx, { role: 'assistant', type: 'thinking', content: { text: THINKING_TEXT } });
  }

  private async toolFlow(ctx: EngineContext): Promise<void> {
    await this.draft(ctx, { role: 'assistant', type: 'tool_use', content: TOOL_CALL });
    await this.draft(ctx, { role: 'assistant', type: 'tool_result', content: TOOL_RESULT });
  }

  /** 顶层审批：连续审批时第二次在第一次应答后再请求，用于验证 approved_all 短路。 */
  private async approvalFlow(ctx: EngineContext, times: number): Promise<boolean> {
    for (let i = 0; i < times; i += 1) {
      const decision = await ctx.requestInput({
        kind: 'approval',
        toolCallId: 'toolu_fake_approval',
        toolName: 'Bash',
        title: '执行 Bash：echo hi',
        description: '桩适配器请求一次工具审批',
        input: { command: 'echo hi' },
      });
      if (decision.decision === 'aborted') return true;
      await this.message(ctx, `审批结果：${decision.decision ?? 'unknown'}`);
    }
    return false;
  }

  private async interactiveFlow(ctx: EngineContext): Promise<void> {
    const decision = await ctx.requestInput({
      kind: 'tool_interactive',
      toolName: 'AskUserQuestion',
      title: '需要澄清',
      questions: [
        {
          header: '格式',
          question: '要处理什么格式？',
          options: [{ label: 'JSON' }, { label: 'CSV' }],
          multiSelect: false,
        },
      ],
    });
    await this.message(ctx, `回答：${JSON.stringify(decision.answers ?? {})}`);
  }

  /** 子代理正常流程：父 Task 调用、子 run 内容、可选子审批、task 生命周期与父 Task 结果。 */
  private async subagentFlow(ctx: EngineContext, plan: FlowPlan): Promise<void> {
    await this.draft(ctx, { role: 'assistant', type: 'tool_use', content: TASK_CALL });
    await this.taskStarted(ctx, SUBAGENT, 1, null, '桩子代理任务');
    await this.childTool(ctx, { parentToolUseId: SUBAGENT.toolUseId }, SUBAGENT.toolCallId);
    if (await this.childApprovals(ctx, plan.approvalCount)) return;
    if (plan.nested) await this.nestedFlow(ctx);
    if (ctx.prompt.includes(FAKE_TRIGGER.subagentResume)) await this.resumeFlow(ctx);
    else await this.taskFinished(ctx, this.taskStatusOf(ctx.prompt));
    await this.draft(ctx, { role: 'assistant', type: 'tool_result', content: TASK_RESULT });
  }

  /** 子代理收尾状态：失败 / 停止 / 正常完成。 */
  private taskStatusOf(prompt: string): 'completed' | 'failed' | 'stopped' {
    if (prompt.includes(FAKE_TRIGGER.subagentFail)) return 'failed';
    if (prompt.includes(FAKE_TRIGGER.subagentStop)) return 'stopped';
    return 'completed';
  }

  /** 嵌套子代理：内层任务的 delegationDepth 传 0，宿主按父 run 深度补成 2。 */
  private async nestedFlow(ctx: EngineContext): Promise<void> {
    await this.taskStarted(ctx, NESTED, 0, SUBAGENT.taskId, '桩嵌套子代理任务');
    // 内层工具消息同时带 agent_id 与 parent_tool_use_id：覆盖宿主优先按 agent_id 归位
    await this.childTool(ctx, { parentToolUseId: NESTED.toolUseId, agentId: NESTED.taskId }, NESTED.toolCallId);
    await this.taskNotified(ctx, NESTED, 'completed', '嵌套子代理完成', null);
  }

  /** worker 重启恢复：同一 task_id 先 stopped，再以新 run_id 重新 started 并完成。 */
  private async resumeFlow(ctx: EngineContext): Promise<void> {
    await this.taskNotified(ctx, SUBAGENT, 'stopped', 'worker 重启', null);
    await this.taskStarted(ctx, RESUMED, 1, null, '桩子代理恢复');
    await this.childTool(ctx, { parentToolUseId: RESUMED.toolUseId }, RESUMED.toolCallId);
    await this.taskNotified(ctx, RESUMED, 'completed', '子代理恢复完成', null);
  }

  private async taskFinished(ctx: EngineContext, status: 'completed' | 'failed' | 'stopped'): Promise<void> {
    const summary = status === 'completed' ? '子代理完成' : status === 'failed' ? '子代理失败' : '子代理已停止';
    const error = status === 'failed' ? '桩子代理异常' : null;
    await this.taskNotified(ctx, SUBAGENT, status, summary, error);
  }

  /** 子 run 的一对工具调用与结果；meta 决定宿主按 agent_id 还是 parent_tool_use_id 归位。 */
  private async childTool(ctx: EngineContext, meta: SubagentMeta, toolCallId: string): Promise<void> {
    await this.draft(ctx, {
      role: 'assistant',
      type: 'tool_use',
      content: { toolCallId, toolName: 'Bash', input: { command: 'echo child' } },
    }, meta);
    await this.draft(ctx, {
      role: 'assistant',
      type: 'tool_result',
      content: { toolCallId, output: 'child', isError: false },
    }, meta);
  }

  /** 子代理审批：返回 true 表示已中止，调用方不再产出后续事件。 */
  private async childApprovals(ctx: EngineContext, times: number): Promise<boolean> {
    for (let i = 0; i < times; i += 1) {
      const decision = await ctx.requestInput({
        kind: 'approval',
        toolCallId: 'toolu_fake_child_approval',
        toolName: 'Bash',
        title: '子代理执行 Bash：echo child',
        description: '桩子代理请求一次工具审批',
        input: { command: 'echo child' },
        agentId: SUBAGENT.taskId,
      });
      if (decision.decision === 'aborted') return true;
      await this.draft(
        ctx,
        { role: 'assistant', type: 'text', content: { text: `子审批结果：${decision.decision ?? 'unknown'}` } },
        { parentToolUseId: SUBAGENT.toolUseId },
      );
    }
    return false;
  }

  /** 子代理中止流程：挂起被宿主结算后立刻发迟到内容，验证终态守卫。 */
  private async subagentAbortFlow(ctx: EngineContext): Promise<void> {
    FakeAdapter.lastAborted = false;
    FakeAdapter.lateContentEmitted = false;
    await this.draft(ctx, { role: 'assistant', type: 'tool_use', content: TASK_CALL });
    await this.taskStarted(ctx, SUBAGENT, 1, null, '桩子代理中止任务');
    await this.childTool(ctx, { parentToolUseId: SUBAGENT.toolUseId }, SUBAGENT.toolCallId);
    await this.awaitAbort(ctx);
    // abortRun 先落子 run 终态再放行挂起：这里返回后发出的内容必然命中终态守卫
    await this.draft(
      ctx,
      { role: 'assistant', type: 'text', content: { text: LATE_SUBAGENT_TEXT } },
      { parentToolUseId: SUBAGENT.toolUseId },
    );
    FakeAdapter.lateContentEmitted = true;
    throw new Error('运行已中止');
  }

  /** 等待挂起被中止结算；记录适配器确实观测到了中止信号，供端到端用例断言。 */
  private async awaitAbort(ctx: EngineContext): Promise<void> {
    const decision = await ctx.requestInput({
      kind: 'approval',
      toolCallId: 'toolu_fake_abort_approval',
      toolName: 'Bash',
      title: '子代理中止前审批',
      description: '等待用户中止',
      input: { command: 'sleep 1' },
      agentId: SUBAGENT.taskId,
    });
    if (!ctx.signal.aborted && decision.decision !== 'aborted') await this.waitForAbort(ctx);
    FakeAdapter.lastAborted = ctx.signal.aborted;
  }

  /** 上限兜底：用例漏掉中止时不让整个测试进程挂死。 */
  private async waitForAbort(ctx: EngineContext, timeoutMs = 10_000): Promise<void> {
    for (let waited = 0; !ctx.signal.aborted; waited += ABORT_POLL_INTERVAL_MS) {
      if (waited >= timeoutMs) throw new Error('子代理中止流程等待超时');
      await sleep(ABORT_POLL_INTERVAL_MS);
    }
    FakeAdapter.lastAborted = true;
  }

  private async taskStarted(
    ctx: EngineContext,
    task: TaskIds,
    delegationDepth: number,
    parentTaskId: string | null,
    description: string,
  ): Promise<void> {
    await ctx.emit({
      type: 'task_started',
      taskId: task.taskId,
      runId: task.runId,
      toolUseId: task.toolUseId,
      parentTaskId,
      subagentType: task.subagentType,
      delegationDepth,
      description,
    });
  }

  private taskNotified(
    ctx: EngineContext,
    task: TaskIds,
    status: 'completed' | 'failed' | 'stopped',
    summary: string,
    error: string | null,
  ): Promise<void> | void {
    return ctx.emit({ type: 'task_notified', taskId: task.taskId, runId: task.runId, status, summary, error });
  }

  private async stream(ctx: EngineContext, text: string, messageType: 'text' | 'thinking' = 'text'): Promise<void> {
    if (messageType === 'thinking') {
      await ctx.emit({ type: 'thinking', phase: 'start' });
      for (let i = 0; i < text.length; i += CHUNK_SIZE) {
        if (ctx.signal.aborted) throw new Error('运行已中止');
        await ctx.emit({ type: 'thinking', phase: 'delta', text: text.slice(i, i + CHUNK_SIZE) });
      }
      await ctx.emit({ type: 'thinking', phase: 'stop' });
      return;
    }
    for (let i = 0; i < text.length; i += CHUNK_SIZE) {
      if (ctx.signal.aborted) throw new Error('运行已中止');
      await ctx.emit({ type: 'delta', messageType: 'text', delta: text.slice(i, i + CHUNK_SIZE) });
    }
  }

  private draft(ctx: EngineContext, draft: MessageDraft, meta?: SubagentMeta): Promise<void> | void {
    const event: EngineEvent = { type: 'message', draft, ...(meta ?? {}) };
    return ctx.emit(event);
  }

  private message(ctx: EngineContext, text: string): Promise<void> | void {
    return this.draft(ctx, { role: 'assistant', type: 'text', content: { text } });
  }
}
