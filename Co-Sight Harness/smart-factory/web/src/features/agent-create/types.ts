/**
 * 智能体创建页的共享类型。
 *
 * 三个阶段的组件都按这里的契约写 —— 改这里的字段，`stages/` 下三个面板都要过一遍。
 *
 * **对话相关的类型不在这里**：消息、过程条目、附件路径已经搬到渲染它们的组件旁边
 * （`shared/components/Conversation/types.ts`）。因为那个组件是共享的，而它是被 `features/`
 * 使用的 —— 依赖方向只能是 feature → shared，不能反过来让 shared 去 import features。
 * 这几行只是转出去，好让本页其它文件继续从 './types' 拿、导入路径不用动。
 */

// `export type { … } from` 只转出、不引入本地作用域
import type { InstanceStage } from '../../shared/api/sessions';

export type {
  ConversationMessage,
  ConversationRole,
  MessageFile,
  SkillTraceItem,
  StepStatus,
  TurnEntry,
} from '../../shared/components/Conversation/types';

/**
 * 创建流程的阶段，顺序即顶部进度条的顺序。
 *
 * **不另起一套词，直接用后端的 `InstanceStage`。** 阶段就是目录
 * （development / preview / runtime / evaluation），后端的 `stage` 参数要的就是这四个字面量；
 * 前端另编一个再翻译过去，只会多一处能写错的地方（传错了回来看见的是「会话建了但查不到」）。
 * 所以这里的取法不是再抄一遍字面量，而是**别名** —— 后端改阶段取值，这里编译期就报错，
 * 不会静默漏掉。
 *
 * 显示名（「生成」）是另一回事，在 `stage-meta.ts` 的 `STAGE_TABS` 里，与键分开。
 */
export type StageId = InstanceStage;

// 评估报告的类型在 `shared/api/evaluations.ts`（与后端 DTO 同形）：
// EvalCase / EvalStepId 是旧演示面板的形状，演示内核删除时一起删了。
