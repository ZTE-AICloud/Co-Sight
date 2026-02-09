// 静态数据配置文件
// 包含所有DAG数据、验证步骤、可信度级别、工作流程等静态配置

// DAG数据定义（默认空，等待后端真实任务数据来填充）
// 保留结构，但不提供任何演示任务，避免界面出现与用户无关的示例内容
const dagData = {
  nodes: [],
  edges: [],
};

// 可信验证步骤配置
const verificationSteps = [
  {
    id: "source-trace",
    name: "来源追溯",
    description: "通过file_saver工具保存搜索结果，记录URL、文件路径和验证路径",
    icon: "fas fa-link",
    status: "pending",
    details: {
      urlRecord: "记录所有搜索结果的原始URL",
      fileTracking: "记录下载文件的完整路径和来源",
      verificationPath: "提供其他工具验证结果的具体路径",
    },
  },
  {
    id: "history-trace",
    name: "历史追溯",
    description: "通过WayBack Machine集成和历史快照验证信息的时间一致性",
    icon: "fas fa-history",
    status: "pending",
    details: {
      waybackIntegration: "自动获取历史网页快照",
      domainTracking: "记录网站域名和结构的历史变化",
      timeConsistency: "验证信息在不同时间点的一致性",
    },
  },
  {
    id: "rule-assist",
    name: "规则辅助",
    description: "通过信息源分级和时间相关性评估信息获取时初步判定可信度",
    icon: "fas fa-gavel",
    status: "pending",
    details: {
      sourceGrading: "问题要求 > PDF文件 > Wikipedia > Google搜索 > 网页评论",
      resultGrading: "代码结果 > 文本工具 > 多模态工具 > 模型参数记忆",
      timeRelevance: "信息越接近给定时间点越可信",
      contentRelevance: "最相关搜索结果 > 其他搜索信息 + 推断结果",
    },
  },
  {
    id: "reasoning",
    name: "推理自洽",
    description: "通过扩大搜索范围、增强感知能力和逻辑一致性检查确保推理正确",
    icon: "fas fa-brain",
    status: "pending",
    details: {
      searchExpansion: "当无法获取准确结果时扩大搜索范围",
      perceptionEnhancement: "提升ReACT阶段的感知能力",
      logicConsistency: "确保推理过程符合逻辑",
      timeReasoning: "基于前后时间点的可验证记录进行推理",
    },
  },
  {
    id: "cross-verify",
    name: "交叉验证",
    description: "通过多源数据对比、冲突识别与解决确保信息准确性",
    icon: "fas fa-check-double",
    status: "pending",
    details: {
      dataConsistency: "比较多个来源的数值数据",
      logicConsistency: "验证不同来源信息的逻辑关系",
      conflictResolution: "识别并解决不同来源间的矛盾",
      sourceConsistency: "计算多个来源的一致性程度",
    },
  },
];

// 可信度级别配置 - 按步骤分组
const credibilityLevels = {
  0: [
    {
      level: 1, // 删掉
      title: "常识或者真理",
      credibility: "100%", // 删掉
      description:
        "足球比赛每队上场球员为 11 人、比赛分为上下半场这类足球领域基础且广泛认可的知识。", // 删掉
      color: "#4CAF50",
      items: ["足球比赛每队上场球员为 11 人", "比赛分为上下半场"],
    },
    {
      level: 2,
      title: "给定或者已验证的事实",
      credibility: "90-95%",
      description:
        "百度百科中关于 2025 年江苏省城市联赛的基础信息，如赛事主办方（江苏省体育局与各设区市政府联合主办）、承办方（各设区市体育局、省足协和省体育产业集团共同承办） ，以及赛事开幕式于 2025 年 5 月 10 日在镇江体育会展中心体育场举办等信息；从百度获取到的江苏 13 支球队完整名单信息。",
      color: "#2196F3",
      items: [
        "江苏省体育局与各设区市政府联合主办",
        "江苏 13 支球队完整名单信息",
      ],
    },
    {
      level: 3,
      title: "需要查找的事实",
      credibility: "70-85%",
      description:
        "通过百度搜索获取的 2025 江苏城市足球联赛积分榜、球队排名信息；通过百度搜索获取的江苏城市足球联赛中南通队、南京队、徐州队的战绩信息。",
      color: "#FF9800",
      items: [
        "2025 江苏城市足球联赛积分榜",
        "南通队、南京队、徐州队的战绩信息",
      ],
    },
    {
      level: 4,
      title: "需要推导的事实",
      credibility: "60-80%",
      description:
        "无（从给定流程看，未涉及基于已知事实进行逻辑推理得出结论的情况） 。",
      color: "#9C27B0",
      items: ["无推导事实", "未涉及逻辑推理"],
    },
    {
      level: 5,
      title: "有根据的猜测",
      credibility: "30-60%",
      description:
        "无（整个信息收集流程主要依赖搜索引擎获取信息，未体现基于有限信息做合理推测的内容） 。",
      color: "#f44336",
      items: ["无合理推测", "主要依赖搜索引擎"],
    },
  ],
  1: [
    {
      level: 1,
      title: "常识或者真理",
      credibility: "100%",
      description:
        "足球比赛技术统计包含进球数、失球数、射门次数、控球率等基础指标；球队表现分析需结合历史数据与当前赛季数据。",
      color: "#4CAF50",
      items: ["进球数、失球数、射门次数、控球率", "历史数据与当前赛季数据"],
    },
    {
      level: 2,
      title: "给定或者已验证的事实",
      credibility: "90-95%",
      description:
        '从 "江苏足球联赛球队基本信息汇总.md" 中读取的球队基础信息；百度搜索获取的 2025 江苏足球联赛各队进球失球 / 射门 / 控球率数据、南通队等特定球队技术统计、射手榜信息。',
      color: "#2196F3",
      items: ["江苏足球联赛球队基本信息汇总", "2025 江苏足球联赛各队技术统计"],
    },
    {
      level: 3,
      title: "需要查找的事实",
      credibility: "70-85%",
      description:
        "2025 江苏足球联赛各队净胜球 / 胜率、核心球员表现 / 伤病情况 / 主力阵容、各队战术风格 / 阵容配置 / 外援情况 / 教练团队信息。",
      color: "#FF9800",
      items: ["各队净胜球 / 胜率", "核心球员表现 / 伤病情况"],
    },
    {
      level: 4,
      title: "需要推导的事实",
      credibility: "60-80%",
      description:
        '基于收集的历史比赛数据与当前赛季数据，在 "各球队历史比赛数据和当前赛季表现分析.md" 中形成的各队综合表现结论。',
      color: "#9C27B0",
      items: ["历史比赛数据与当前赛季数据", "各队综合表现结论"],
    },
    {
      level: 5,
      title: "有根据的猜测",
      credibility: "30-60%",
      description:
        "无（流程中所有信息均来自搜索或基于明确数据的分析，未涉及有限信息下的合理推测）。",
      color: "#f44336",
      items: ["无合理推测", "基于明确数据的分析"],
    },
  ],
  2: [
    {
      level: 1,
      title: "常识或者真理",
      credibility: "100%",
      description:
        "足球战术分析需关注阵型（如 4-4-2、5-3-2）、战术体系及控球率、射门数据等指标；球队弱点识别需结合战术特点与球员阵容信息。",
      color: "#4CAF50",
      items: ["阵型（如 4-4-2、5-3-2）", "战术特点与球员阵容信息"],
    },
    {
      level: 2,
      title: "给定或者已验证的事实",
      credibility: "90-95%",
      description:
        '从 "江苏足球联赛球队基本信息汇总.md" 读取的球队基础信息；百度搜索获取的南通队技术流打法、南京队 / 徐州队 / 盐城队战术特点、常州队黄紫昌相关信息。',
      color: "#2196F3",
      items: ["南通队技术流打法", "南京队 / 徐州队 / 盐城队战术特点"],
    },
    {
      level: 3,
      title: "需要查找的事实",
      credibility: "70-85%",
      description:
        "2025 江苏足球联赛各队具体阵型（4-4-2/5-3-2 等）、战术体系细节、苏州队 / 泰州队球员阵容与战术特点。",
      color: "#FF9800",
      items: ["各队具体阵型（4-4-2/5-3-2 等）", "苏州队 / 泰州队球员阵容"],
    },
    {
      level: 4,
      title: "需要推导的事实",
      credibility: "60-80%",
      description:
        '在 "江苏足球联赛各队战术特点与球员阵容优势分析.md" 中，基于各队战术数据与阵容信息推导的球队弱点及改进空间。',
      color: "#9C27B0",
      items: ["各队战术数据与阵容信息", "球队弱点及改进空间"],
    },
    {
      level: 5,
      title: "有根据的猜测",
      credibility: "30-60%",
      description:
        "无（流程信息均来自文件读取或百度搜索，分析基于明确数据，无有限信息下的推测）。",
      color: "#f44336",
      items: ["无有限信息推测", "基于明确数据的分析"],
    },
  ],
  3: [
    {
      level: 1,
      title: "常识或者真理",
      credibility: "100%",
      description:
        "球队弱点分析需结合失球原因、战术缺陷等维度；成绩预测需参考历史数据、当前表现、剩余赛程及淘汰赛规则。",
      color: "#4CAF50",
      items: ["失球原因、战术缺陷", "历史数据、当前表现、剩余赛程"],
    },
    {
      level: 2,
      title: "给定或者已验证的事实",
      credibility: "90-95%",
      description:
        '从 "各球队历史比赛数据和当前赛季表现分析.md""江苏足球联赛各队战术特点与球员阵容优势分析.md" 读取的球队数据与战术信息；百度搜索获取的 2025 江苏联赛最新积分榜、第 12-13 轮赛果、淘汰赛对阵表及竞赛规则。',
      color: "#2196F3",
      items: ["球队数据与战术信息", "2025 江苏联赛最新积分榜"],
    },
    {
      level: 3,
      title: "需要查找的事实",
      credibility: "70-85%",
      description:
        "2025 江苏联赛各队（含争冠集团与中下游球队）具体弱点（如南通队短板、南京队防守问题）、改进建议（战术调整 / 训练强化 / 青训发展）。",
      color: "#FF9800",
      items: ["南通队短板、南京队防守问题", "战术调整 / 训练强化 / 青训发展"],
    },
    {
      level: 4,
      title: "需要推导的事实",
      credibility: "60-80%",
      description:
        '在 "江苏足球联赛各队弱点与改进空间分析.md" 中，基于球队弱点信息与改进建议推导的各队改进方向，及结合赛程与表现推导的最终成绩预测依据。',
      color: "#9C27B0",
      items: ["各队改进方向", "最终成绩预测依据"],
    },
    {
      level: 5,
      title: "有根据的猜测",
      credibility: "30-60%",
      description:
        "无（所有信息均来自文件读取或百度搜索，分析基于明确数据，无有限信息下的推测）。",
      color: "#f44336",
      items: ["无有限信息推测", "基于明确数据的分析"],
    },
  ],
  4: [
    {
      level: 1,
      title: "常识或者真理",
      credibility: "100%",
      description:
        "成绩预测需结合球队历史数据、当前表现、最新赛程 / 赛果及发展潜力；联赛排名以积分榜（含各轮次结果）为核心依据。",
      color: "#4CAF50",
      items: ["球队历史数据、当前表现", "积分榜（含各轮次结果）"],
    },
    {
      level: 2,
      title: "给定或者已验证的事实",
      credibility: "90-95%",
      description:
        '从 "各球队历史比赛数据和当前赛季表现分析.md""江苏足球联赛各队战术特点与球员阵容优势分析.md" 读取的球队数据与战术信息；百度搜索获取的 2025 江苏联赛最新积分榜、第 12-13 轮赛果、淘汰赛对阵表及竞赛规则。',
      color: "#2196F3",
      items: ["球队数据与战术信息", "2025 江苏联赛最新积分榜"],
    },
    {
      level: 3,
      title: "需要查找的事实",
      credibility: "70-85%",
      description:
        "2025 江苏联赛各队（争冠集团与中下游球队）改进空间、发展潜力（如南通队潜力、盐城队青训）、未来规划（如南京队规划、苏州队建设）及长期战略目标。",
      color: "#FF9800",
      items: ["南通队潜力、盐城队青训", "南京队规划、苏州队建设"],
    },
    {
      level: 4,
      title: "需要推导的事实",
      credibility: "60-80%",
      description:
        "基于球队历史数据、当前表现、最新赛果及发展潜力，在最终成绩预测中推导的各队排名走向与淘汰赛晋级概率。",
      color: "#9C27B0",
      items: ["各队排名走向", "淘汰赛晋级概率"],
    },
    {
      level: 5,
      title: "有根据的猜测",
      credibility: "30-60%",
      description:
        "无（信息均来自文件读取或百度搜索，预测基于明确数据，无有限信息下的推测）。",
      color: "#f44336",
      items: ["无有限信息推测", "预测基于明确数据"],
    },
  ],
  5: [
    {
      level: 1,
      title: "常识或者真理",
      credibility: "100%",
      description:
        "综合分析报告需整合基础信息、历史数据、战术特点、弱点分析等核心模块；HTML 报告需具备完整结构以清晰呈现内容。",
      color: "#4CAF50",
      items: ["基础信息、历史数据、战术特点", "HTML 报告需具备完整结构"],
    },
    {
      level: 2,
      title: "给定或者已验证的事实",
      credibility: "90-95%",
      description:
        '从文件读取的 13 支参赛球队基本信息、各队历史比赛数据与当前表现、战术特点与阵容优势、弱点与改进空间；成功生成的 "2025 年江苏足球联赛球队表现分析与预测报告.html" 及其实时性结构完整验证结果。',
      color: "#2196F3",
      items: [
        "13 支参赛球队基本信息",
        "2025 年江苏足球联赛球队表现分析与预测报告.html",
      ],
    },
    {
      level: 3,
      title: "需要查找的事实",
      credibility: "70-85%",
      description: "无（此步骤仅读取已收集的前序分析文件，未新增搜索需求）。",
      color: "#FF9800",
      items: ["无新增搜索需求", "仅读取前序分析文件"],
    },
    {
      level: 4,
      title: "需要推导的事实",
      credibility: "60-80%",
      description:
        "在综合报告中，基于基础信息、历史数据、战术与弱点分析推导的各队最终成绩预测结论。",
      color: "#9C27B0",
      items: ["基础信息、历史数据、战术与弱点分析", "各队最终成绩预测结论"],
    },
    {
      level: 5,
      title: "有根据的猜测",
      credibility: "30-60%",
      description:
        "无（报告内容均基于前序步骤已验证的事实与数据，无有限信息下的推测）",
      color: "#f44336",
      items: ["无有限信息推测", "基于前序步骤已验证的事实"],
    },
  ],
};

// 工具与验证步骤映射关系
const toolVerificationMapping = {
  search_baidu: {
    consistent: ["reasoning", "source-trace"], // 如果自洽，则认为信息高度可信，都具有来源追溯
    inconsistent: ["rule-assist", "source-trace"], // 如果不自洽，对应规则辅助判定初始可信度，都具有来源追溯
  },
  search_google: {
    consistent: ["reasoning", "source-trace"], // 如果自洽，则认为信息高度可信，都具有来源追溯
    inconsistent: ["rule-assist", "source-trace", "cross-verify"], // 如果不自洽，对应规则辅助判定初始可信度，都具有来源追溯，同时涉及交叉验证
  },
  // 新增：Tavily 搜索与 Wiki 搜索的验证步骤映射
  tavily_search: {
    consistent: ["reasoning", "source-trace"],
    inconsistent: ["rule-assist", "source-trace", "cross-verify"],
  },
  search_wiki: {
    consistent: ["reasoning", "source-trace"],
    inconsistent: ["rule-assist", "source-trace", "cross-verify"],
  },
  file_saver: ["source-trace"], // 对应可信验证中来源追溯
  data_analyzer: ["reasoning", "cross-verify"], // 对应推理自洽和交叉验证
  predictor: ["reasoning", "cross-verify"], // 对应推理自洽和交叉验证
  report_generator: ["reasoning", "cross-verify"], // 对应推理自洽和交叉验证
};

// 节点工具映射配置
const nodeToolMappings = {
  0: { name: "create_plan", description: "创建执行计划" },
  1: { name: "search_baidu", description: "搜索百度数据" },
  2: { name: "file_saver", description: "保存文件" },
  3: { name: "data_analyzer", description: "数据分析处理" },
  4: { name: "predictor", description: "预测模型执行" },
  5: { name: "report_generator", description: "生成报告" },
};

// 状态图标映射
const statusIcons = {
  completed: "✓",
  in_progress: "▶",
  blocked: "⚠",
  not_started: "○",
};

// 状态文本映射
const statusTexts = {
  completed: "已完成",
  in_progress: "进行中",
  blocked: "阻塞",
  not_started: "未开始",
};

// 工具调用状态图标映射
const toolCallStatusIcons = {
  running: "fas fa-spinner fa-spin",
  completed: "fas fa-check-circle",
  failed: "fas fa-times-circle",
};

// 工具调用状态文本映射
const toolCallStatusTexts = {
  running: "运行中",
  completed: "已完成",
  failed: "失败",
};

// 模拟进度步骤配置（默认空）
// 实际任务的进度由后端返回的数据驱动
const progressSteps = [];

// 验证步骤执行顺序
const verificationStepOrder = [
  "source-trace",
  "history-trace",
  "rule-assist",
  "reasoning",
  "cross-verify",
];

// 导出所有配置数据（如果使用模块化）
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    dagData,
    verificationSteps,
    credibilityLevels,
    toolVerificationMapping,
    nodeToolMappings,
    statusIcons,
    statusTexts,
    toolCallStatusIcons,
    toolCallStatusTexts,
    progressSteps,
    verificationStepOrder,
  };
}
