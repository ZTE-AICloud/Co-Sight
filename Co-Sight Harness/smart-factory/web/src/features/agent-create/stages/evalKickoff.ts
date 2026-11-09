/**
 * 评估阶段的 kick-off 消息（2026-10-20 改为调用技能）。
 *
 * 不再内联「生成测试集 → 执行 → 评分 → 轨迹审计」的长 prompt，而是发一条
 * `goldeval` 插件的 `agent-eval` slash 命令：四段流程、产物目录结构、裁判口径
 * 都写在技能自己的 SKILL.md 里，前端只负责把父目录指到服务端认得出的位置。
 *
 * **`--output` 是父目录，不是 run 目录**（技能会对以 `e2e-test` 开头的值直接报错）。
 * 编排层每次调用都在父目录下新建 `<父目录>/e2e-test-<时间戳>/`，所以「重新评估」
 * 天然是一轮新目录，前端不用也不该自己算时间戳。
 *
 * **父目录传 `..`**：会话 cwd 是被测副本 `<evaluation>/agent/`（评估沙箱物化时把
 * 被测产物收进 `agent/` 子目录，见服务端 `materialize.ts` 的 `materializeTarget`），
 * `..` 即沙箱根 `<evaluation>/`。服务端只认两种落点 —— `<evaluation>/e2e-test-*`
 * 与 `<evaluation>/eval_results/e2e-test-*`（`evaluation.service.ts` 的
 * `listReportIds` / `resolveReportDir`）；`eval_results/` 那层虽然列表与详情都认，
 * 但用例详情端点 `getCaseDetail` 直接 `join(root, reportId)`，套一层会 404。
 *
 * 副本必须收在 `agent/` 里，不能平铺在沙箱根：`e2e-test-runner` 硬性要求产物目录在
 * 被测目录之外（它会把被测目录整棵复制进每条用例的 workspace，套在一起会递归）。
 * 平铺时 `--agent . --output .` 必然把 run 目录放进 agent_root 内部，runner 直接拒绝。
 *
 * `--agent .`：cwd 就是被测副本，锚点（CLAUDE.md + `.claude/`）在根层命中，技能
 * 不会深挖进历史报告里的用例副本（多锚点会报错）。
 *
 * 轨迹审计批的落点：当前上游 traceaudit 写的是 `<run>/eval_trace_results/` 平铺
 * `batch-summary.json`，而服务端 `findAuditBatch` 只认 `eval_trace_results/` 下的
 * `batch_` 前缀子目录（`AUDIT_BASES` 两项都按该前缀找）。所以报告会显示 `status=partial`、
 * `audit=null` —— 结果分正常，轨迹分待上游对齐目录命名后自动出现。
 *
 * **开跑时机**：一轮评估要跑几分钟、烧不少 token，阶段内的「开始评估」/「重新评估」
 * 仍由用户显式触发。唯一例外是首页「评估智能体」——用户在那里按过发送，交接载荷带
 * `autoSend + newSession`，设计页停掉旧一场、重开一场（同「重新评估」）后立刻发这条
 * 命令（见 `EvaluateStage` 的 `autoStart`）。
 */

/**
 * 命令没有可变部分：run 目录名由技能按调用时刻自己生成。
 * 括号里的技能名以线上安装的 `agent-evaluator` 目录为准，插件缓存里的 1.0.0 是旧契约。
 */
const KICKOFF_MESSAGE = '/goldeval:agent-eval --agent . --output ..';

export function evalKickoffPrompt(): string {
  return KICKOFF_MESSAGE;
}
