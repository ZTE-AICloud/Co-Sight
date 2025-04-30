import { Message } from "@rdkmaster/lui-sdk";

// @getterSetterExclude
export class LuiMessageManusStepType extends Message {
    public initData: {
        title?: string,               // Plan 标题
        steps?: string[],             // 步骤内容数组
        step_statuses?: Record<string, string>, // 步骤状态
        step_notes?: Record<string, string>,    // 步骤备注
        step_details?: Record<string, string>,  // 步骤详细信息
        dependencies?: Record<number, number[]>, // 依赖关系
        step_files?: Record<string, StepFile[]>, // 文件信息
        progress?: {                  // 进度信息
            total: number,
            completed: number,
            in_progress: number,
            blocked: number,
            not_started: number
        },
        isStepActive?: Record<number, boolean>, // 控制步骤展开/收起状态
        result?: string                  // 保留原有的 result 字段
    };
}

export type ManusStepItem = {
    name: string,
    index: number,
    status: string,     // 'completed', 'in_progress', 'blocked', 'not_started'
    notes?: string,     // 步骤备注
    details?: string,   // 步骤详细信息
    dependencies?: number[], // 依赖关系
    isActive?: boolean, // 控制展开/收起
}

export type StepFile = {
    path: string,
    name: string
}