/**
 * 预置专家种子数据（D13 = A：`预置` 作为第四个页签，由后端种子标记区分）。
 *
 * 这些是**随框架分发的内置内容**，不是测试假数据——`预置` 页签在没有它们的时候
 * 永远是空的，页签本身也就失去了意义。
 *
 * 名称与描述写中文而不做双语：`Expert.name` / `description` 在契约里是普通字符串
 * （用户内容），不是 `LocalizedText`（UI 文案）。混进 i18n 体系会让"用户创建的专家"
 * 和"内置专家"两种数据形状分叉，得不偿失。
 */

import type { CreateExpertInput } from 'harness-shared';

/** 内置专家的统一署名，前端卡片上显示为"上传者"。 */
export const PRESET_AUTHOR = 'ZTE AI Lab';

export const PRESET_EXPERTS: CreateExpertInput[] = [
  {
    name: '需求分析专家',
    author: PRESET_AUTHOR,
    description: '把模糊的业务诉求拆解为可验收的功能点，输出结构化需求清单与验收标准。',
    avatarUrl: null,
    tags: ['需求分析', '文档产出'],
    isPreset: true,
  },
  {
    name: '架构设计专家',
    author: PRESET_AUTHOR,
    description: '基于需求给出系统分层、模块边界与关键取舍，产出架构决策记录。',
    avatarUrl: null,
    tags: ['架构设计', '技术选型'],
    isPreset: true,
  },
  {
    name: '代码审查专家',
    author: PRESET_AUTHOR,
    description: '按正确性、安全性、可维护性三个维度审查变更，逐条给出可执行的修改建议。',
    avatarUrl: null,
    tags: ['代码审查', '质量保障'],
    isPreset: true,
  },
  {
    name: '测试用例生成专家',
    author: PRESET_AUTHOR,
    description: '依据接口契约与业务规则生成覆盖边界与异常路径的测试用例。',
    avatarUrl: null,
    tags: ['测试', '用例设计'],
    isPreset: true,
  },
  {
    name: '缺陷定位专家',
    author: PRESET_AUTHOR,
    description: '从堆栈、日志与复现步骤出发缩小问题范围，给出根因假设与验证路径。',
    avatarUrl: null,
    tags: ['调试', '根因分析'],
    isPreset: true,
  },
  {
    name: '标书撰写专家',
    author: PRESET_AUTHOR,
    description: '按招标文件要求组织技术标结构，输出符合评分点覆盖的投标文档。',
    avatarUrl: null,
    tags: ['标书', '办公'],
    isPreset: true,
  },
  {
    name: '办公文档专家',
    author: PRESET_AUTHOR,
    description: '撰写与润色汇报材料、会议纪要与周报，统一口径与格式。',
    avatarUrl: null,
    tags: ['办公', '文档产出'],
    isPreset: true,
  },
  {
    name: '数据分析专家',
    author: PRESET_AUTHOR,
    description: '从原始数据出发完成清洗、指标计算与结论提炼，输出图表与解读。',
    avatarUrl: null,
    tags: ['数据分析', '指标'],
    isPreset: true,
  },
  {
    name: '知识库问答专家',
    author: PRESET_AUTHOR,
    description: '基于团队知识库检索并作答，回答附带出处，无法支撑时明确拒答。',
    avatarUrl: null,
    tags: ['知识库', '检索增强'],
    isPreset: true,
  },
  {
    name: 'Agent 评估专家',
    author: PRESET_AUTHOR,
    description: '设计评估测试集与评分标准，对 Agent 的结果与过程给出可复现的评估结论。',
    avatarUrl: null,
    tags: ['评估', '测试集'],
    isPreset: true,
  },
  {
    name: '提示词优化专家',
    author: PRESET_AUTHOR,
    description: '诊断提示词中的歧义与冗余，按目标行为改写并给出前后效果对比。',
    avatarUrl: null,
    tags: ['提示词', '优化'],
    isPreset: true,
  },
  {
    name: '流程编排专家',
    author: PRESET_AUTHOR,
    description: '把多步骤任务拆成可并行的阶段，设计依赖关系与失败回退路径。',
    avatarUrl: null,
    tags: ['编排', '工作流'],
    isPreset: true,
  },
];
