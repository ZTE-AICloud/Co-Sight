// 工作流程步骤配置文件
// 包含所有具体的工作流程执行步骤

// STEP0工作流程配置
const step0Workflow = {
    title: "收集2025年江苏足球联赛参赛球队基本信息",
    tools: [
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025年江苏足球联赛，参赛队伍名单',
            mode: 'sync',
            duration: 7500,
            result: '获取到百度百科关于2025年江苏省城市联赛的基础信息以及对应URL',
            url: 'https://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_4584810038002454030&sourceFrom=search_a'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '信息保存到：检索结果_江苏足球联赛参赛球队_百度.md',
            mode: 'sync',
            duration: 2000,
            result: '文件保存成功',
            path: '/cosight2/workspace/江苏足球联赛参赛球队.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏城市足球联赛 13支球队完整名单',
            mode: 'sync',
            duration: 8500,
            result: '获取到来自江苏13支球队名单的信息',
            url: 'https://www.logonews.cn/2025-jiangsu-football-city-league-logo.html'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '信息保存到：检索结果_江苏13支球队名单_百度.md',
            mode: 'sync',
            duration: 1200,
            result: '文件保存成功',
            path: '/cosight2/workspace/江苏13支球队名单.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏城市足球联赛积分榜 球队排名',
            mode: 'sync',
            duration: 7500,
            result: '获取到2025江苏城市足球联赛排名',
            url: 'https://sports.163.com/caipiao/league/football/7306'
        },
        {
            tool: 'search_google',
            toolName: '谷歌搜索',
            description: '查询内容：2025江苏城市足球联赛积分榜 南通队 南京队 排名',
            mode: 'sync',
            duration: 8800,
            result: '获取到2025江苏城市足球联赛积分榜信息 南通队 南京队 排名相关信息',
            url: 'https://tiyu.baidu.com/al/match?match=江苏城市足球联赛&tab=排名'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：江苏城市足球联赛 南通队 南京队 徐州队 战绩',
            mode: 'sync',
            duration: 7100,
            result: '获取到江苏城市足球联赛 南通队 南京队 徐州队 战绩相关信息',
            url: 'https://tiyu.baidu.com/al/match?match=江苏城市足球联赛&tab=赛程'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '信息保存到：检索结果_江苏联赛战绩数据_百度.md',
            mode: 'sync',
            duration: 1800,
            result: '文件保存成功',
            path: '/cosight2/workspace/江苏联赛战绩数据.md'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '信息保存到：江苏足球联赛球队基本信息汇总.md',
            mode: 'sync',
            duration: 800,
            result: '综合汇总文件创建成功',
            path: '/cosight2/workspace/江苏足球联赛球队基本信息汇总.md'
        }
    ]
};

// STEP1工作流程配置
const step1Workflow = {
    title: "分析各球队历史比赛数据和当前赛季表现",
    tools: [
        {
            tool: 'file_read',
            toolName: '文件读取',
            description: '读取文件：江苏足球联赛球队基本信息汇总.md',
            mode: 'sync',
            duration: 1000,
            result: '读取信息成功',
            path: '/cosight2/workspace/江苏足球联赛球队基本信息汇总.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏足球联赛各队进球失球数据 射门次数 控球率统计',
            mode: 'sync',
            duration: 7500,
            result: '获取到2025江苏足球联赛各队进球失球数据 射门次数 控球率统计相关信息',
            url: 'https://live.leisu.com/shujufenxi-4334265'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_江苏联赛积分榜数据_百度.md',
            mode: 'sync',
            duration: 1500,
            result: '文件保存成功',
            path: '/cosight2/workspace/江苏联赛积分榜数据.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏足球联赛南通队南京队徐州队盐城队技术统计 射门数据控球率',
            mode: 'sync',
            duration: 7200,
            result: '获取到2025江苏足球联赛南通队南京队徐州队盐城队技术统计 射门数据控球率相关信息',
            url: 'https://baijiahao.baidu.com/s?id=1835939067010567197&wfr=spider&for=pc'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '信息保存到：检索结果_各队技术统计数据_百度.md',
            mode: 'sync',
            duration: 1500,
            result: '文件保存成功',
            path: '/cosight2/workspace/各队技术统计数据.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏足球联赛射手榜 核心球员表现 伤病情况 主力阵容',
            mode: 'sync',
            duration: 8600,
            result: '获取到2025江苏足球联赛射手榜 核心球员表现 伤病情况 主力阵容相关信息',
            url: 'https://jsstyj.jiangsu.gov.cn/art/2025/7/7/art_92673_11595807.html'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_射手榜球员数据_百度.md',
            mode: 'sync',
            duration: 1500,
            result: '文件保存成功',
            path: '/cosight2/workspace/射手榜球员数据.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏足球联赛各队战术风格 阵容配置 外援情况 教练团队',
            mode: 'sync',
            duration: 7900,
            result: '获取到2025江苏足球联赛各队战术风格 阵容配置 外援情况 教练团队相关信息',
            url: 'https://baijiahao.baidu.com/s?id=1834777039187094715&wfr=spider&for=pc'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：各球队历史比赛数据和当前赛季表现分析.md',
            mode: 'sync',
            duration: 1800,
            result: '分析报告保存成功',
            path: '/cosight2/workspace/各球队历史比赛数据和当前赛季表现分析.md'
        }
    ]
};

const step2Workflow = {
    title: "评估各球队的战术特点和球员阵容优势",
    tools: [
        {
            tool: 'file_read',
            toolName: '文件读取',
            description: '读取文件：江苏足球联赛球队基本信息汇总.md',
            mode: 'sync',
            duration: 1500,
            result: '读取信息成功',
            path: '/cosight2/workspace/江苏足球联赛球队基本信息汇总.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏足球联赛 南通队 战术特点 球员阵容 技术流打法',
            mode: 'sync',
            duration: 8400,
            result: '获取到2025江苏足球联赛 南通队 战术特点 球员阵容 技术流打法相关信息',
            url: 'https://baijiahao.baidu.com/s?id=1836896193756243631&wfr=spider&for=pc'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '信息保存到：检索结果_南通队战术特点_百度.md',
            mode: 'sync',
            duration: 1500,
            result: '文件保存成功',
            path: '/cosight2/workspace/南通队战术特点.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏足球联赛 南京队 徐州队 盐城队 战术特点 阵容分析',
            mode: 'sync',
            duration: 8700,
            result: '获取到2025江苏足球联赛 南京队 徐州队 盐城队 战术特点 阵容分析相关信息',
            url: 'https://baijiahao.baidu.com/s?id=1840247783018659763&wfr=spider&for=pc'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '信息保存到：检索结果_三强队战术对比_百度.md',
            mode: 'sync',
            duration: 1500,
            result: '文件保存成功',
            path: '/cosight2/workspace/三强队战术对比.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏足球联赛 常州队 苏州队 泰州队 球员阵容 战术特点 黄紫昌',
            mode: 'sync',
            duration: 7900,
            result: '获取到关于黄紫昌和常州队的重要信息',
            url: 'https://js.cnr.cn/tyjk/20250830/t20250830_527347039.shtml'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '信息保存到：检索结果_三强队战术对比_百度.md',
            mode: 'sync',
            duration: 1500,
            result: '文件保存成功',
            path: '/cosight2/workspace/三强队战术对比.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏足球联赛 各队阵型 4-4-2 5-3-2 战术分析 控球率 射门数据',
            mode: 'sync',
            duration: 7300,
            result: '获取到2025江苏足球联赛 各队阵型 4-4-2 5-3-2 战术分析 控球率 射门数据相关信息',
            url: 'https://baijiahao.baidu.com/s?id=1838218638807999980&wfr=spider&for=pc'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_战术数据分析_百度.md',
            mode: 'sync',
            duration: 1500,
            result: '文件保存成功',
            path: '/cosight2/workspace/战术数据分析.md'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：江苏足球联赛各队战术特点与球员阵容优势分析.md',
            mode: 'sync',
            duration: 1800,
            result: '分析报告保存成功',
            path: '/cosight2/workspace/江苏足球联赛各队战术特点与球员阵容优势分析.md'
        }
    ]
};

const step3Workflow = {
    title: "识别各球队的主要弱点和改进空间",
    tools: [
        {
            tool: 'file_read',
            toolName: '文件读取',
            description: '读取文件：各球队历史比赛数据和当前赛季表现分析.md',
            mode: 'sync',
            duration: 1500,
            result: '信息读取成功',
            path: '/cosight2/workspace/各球队历史比赛数据和当前赛季表现分析.md'
        },
        {
            tool: 'file_read',
            toolName: '文件读取',
            description: '读取文件：江苏足球联赛各队战术特点与球员阵容优势分析.md',
            mode: 'sync',
            duration: 1500,
            result: '信息读取成功',
            path: '/cosight2/workspace/江苏足球联赛各队战术特点与球员阵容优势分析.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025年江苏足球联赛最新积分榜 第12轮 第13轮比赛结果',
            mode: 'sync',
            duration: 7600,
            result: '获取到2025年江苏足球联赛最新积分榜 第12轮 第13轮比赛结果相关信息',
            url: 'https://jsstyj.jiangsu.gov.cn/art/2025/9/7/art_92671_11636683.html'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏足球联赛 各队弱点 问题 失球原因 战术缺陷',
            mode: 'sync',
            duration: 7400,
            result: '获取到关于各队弱点的信息',
            url: 'https://baijiahao.baidu.com/s?id=1839446418411084949&wfr=spider&for=pc'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_各队弱点问题分析_百度.md',
            mode: 'sync',
            duration: 1500,
            result: '文件保存成功',
            path: '/cosight2/workspace/各队弱点问题分析.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：南通队弱点 南京队防守问题 盐城队缺点 徐州队短板 江苏联赛',
            mode: 'sync',
            duration: 7800,
            result: '获取到关于具体球队弱点的详细信息',
            url: 'https://baijiahao.baidu.com/s?id=1838166455940634581&wfr=spider&for=pc'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_争冠集团弱点分析_百度.md',
            mode: 'sync',
            duration: 1500,
            result: '文件保存成功',
            path: '/cosight2/workspace/争冠集团弱点分析.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：江苏联赛 泰州队 无锡队 淮安队 连云港队 苏州队 宿迁队 问题 弱点',
            mode: 'sync',
            duration: 8100,
            result: '获取到中下游球队的具体弱点信息',
            url: 'https://baijiahao.baidu.com/s?id=1841509279593297125&wfr=spider&for=pc'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_中下游球队表现问题_百度.md',
            mode: 'sync',
            duration: 1800,
            result: '文件保存成功',
            path: '/cosight2/workspace/中下游球队表现问题.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：江苏联赛球队 改进建议 战术调整 训练强化 青训发展',
            mode: 'sync',
            duration: 7700,
            result: '获取到关于各队改进空间的信息',
            url: 'https://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_2160057049391088135&sourceFrom=search_a'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_淘汰赛对阵表和竞赛规则_百度.md',
            mode: 'sync',
            duration: 1500,
            result: '文件保存成功',
            path: '/cosight2/workspace/淘汰赛对阵表和竞赛规则.md'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_改进建议青训发展_百度.md',
            mode: 'sync',
            duration: 1800,
            result: '文件保存成功',
            path: '/cosight2/workspace/改进建议青训发展.md'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：江苏足球联赛各队弱点与改进空间分析.md',
            mode: 'sync',
            duration: 1800,
            result: '分析报告保存成功',
            path: '/cosight2/workspace/江苏足球联赛各队弱点与改进空间分析.md'
        }
    ]
};

const step4Workflow = {
    title: "基于数据分析进行最终成绩预测",
    tools: [
        {
            tool: 'file_read',
            toolName: '文件读取',
            description: '读取文件：各球队历史比赛数据和当前赛季表现分析.md',
            mode: 'sync',
            duration: 1200,
            result: '信息读取成功',
            path: '/cosight2/workspace/各球队历史比赛数据和当前赛季表现分析.md'
        },
        {
            tool: 'file_read',
            toolName: '文件读取',
            description: '读取文件：江苏足球联赛各队战术特点与球员阵容优势分析.md',
            mode: 'sync',
            duration: 1800,
            result: '信息读取成功',
            path: '/cosight2/workspace/江苏足球联赛各队战术特点与球员阵容优势分析.md'
        },

        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025年江苏足球联赛最新积分榜 第12轮 第13轮比赛结果',
            mode: 'sync',
            duration: 8500,
            result: '获取到2025年江苏足球联赛最新积分榜 第12轮 第13轮比赛结果相关信息',
            url: 'https://jsstyj.jiangsu.gov.cn/art/2025/9/7/art_92672_11636693.html'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：2025江苏足球联赛 各队改进空间 未来趋势 发展潜力',
            mode: 'sync',
            duration: 7600,
            result: '获取到关于各队改进空间的信息',
            url: 'https://baijiahao.baidu.com/s?id=1835225673788876215&wfr=spider&for=pc'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_各队改进空间分析_百度.md',
            mode: 'sync',
            duration: 1500,
            result: '文件保存成功',
            path: '/cosight2/workspace/各队改进空间分析.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：南通队发展潜力 南京队未来规划 盐城队青训体系 徐州队建设方向',
            mode: 'sync',
            duration: 7900,
            result: '获取到关于具体球队未来发展的详细信息',
            url: 'https://baijiahao.baidu.com/s?id=1841167074498763138&wfr=spider&for=pc'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_争冠集团发展前景_百度.md',
            mode: 'sync',
            duration: 1600,
            result: '文件保存成功',
            path: '/cosight2/workspace/争冠集团发展前景.md'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_最新积分榜和比赛结果_百度.md',
            mode: 'sync',
            duration: 1100,
            result: '文件保存成功',
            path: '/cosight2/workspace/最新积分榜和比赛结果.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：江苏联赛 泰州队 无锡队 淮安队 连云港队 苏州队 宿迁队 发展潜力 建设规划',
            mode: 'sync',
            duration: 8200,
            result: '获取到中下游球队的具体发展潜力信息',
            url: 'https://baijiahao.baidu.com/s?id=1836896193756243631&wfr=spider&for=pc'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_中下游球队发展潜力_百度.md',
            mode: 'sync',
            duration: 1800,
            result: '文件保存成功',
            path: '/cosight2/workspace/中下游球队发展潜力.md'
        },
        {
            tool: 'search_baidu',
            toolName: '百度搜索',
            description: '查询内容：江苏联赛球队 未来趋势 发展规划 战略目标 长期建设',
            mode: 'sync',
            duration: 8800,
            result: '获取到关于各队未来趋势的信息',
            url: 'https://mbd.baidu.com/newspage/data/dtlandingsuper?nid=dt_2160057049391088135&sourceFrom=search_a'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_淘汰赛对阵表和竞赛规则_百度.md',
            mode: 'sync',
            duration: 1800,
            result: '文件保存成功',
            path: '/cosight2/workspace/淘汰赛对阵表和竞赛规则.md'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：检索结果_未来趋势发展规划_百度.md',
            mode: 'sync',
            duration: 1200,
            result: '文件保存成功',
            path: '/cosight2/workspace/未来趋势发展规划.md'
        },
        {
            tool: 'file_saver',
            toolName: '文件保存',
            description: '结果保存到：江苏足球联赛各队弱点与改进空间分析.md',
            mode: 'sync',
            duration: 1400,
            result: '分析报告保存成功',
            path: '/cosight2/workspace/江苏足球联赛各队弱点与改进空间分析.md'
        }
    ]
};

const step5Workflow = {
    title: "生成综合分析与预测报告",
    tools: [
        {
            tool: 'file_read',
            toolName: '文件读取',
            description: '读取文件：江苏足球联赛球队基本信息汇总.md',
            mode: 'sync',
            duration: 1200,
            result: '信息读取成功',
            path: '/cosight2/workspace/江苏足球联赛球队基本信息汇总.md'
        },
        {
            tool: 'file_read',
            toolName: '文件读取',
            description: '读取文件：各球队历史比赛数据和当前赛季表现分析.md',
            mode: 'sync',
            duration: 1500,
            result: '信息读取成功',
            path: '/cosight2/workspace/各球队历史比赛数据和当前赛季表现分析.md'
        },
        {
            tool: 'file_read',
            toolName: '文件读取',
            description: '读取文件：江苏足球联赛各队战术特点与球员阵容优势分析.md',
            mode: 'sync',
            duration: 1500,
            result: '信息读取成功',
            path: '/cosight2/workspace/江苏足球联赛各队战术特点与球员阵容优势分析.md'
        },
        {
            tool: 'file_read',
            toolName: '文件读取',
            description: '读取文件：江苏足球联赛各队弱点与改进空间分析.md',
            mode: 'sync',
            duration: 1000,
            result: '信息读取成功',
            path: '/cosight2/workspace/江苏足球联赛各队弱点与改进空间分析.md'
        },
        {
            tool: 'file_read',
            toolName: '文件读取',
            description: '读取文件：2025年江苏足球联赛最终成绩预测分析.md',
            mode: 'sync',
            duration: 1500,
            result: '信息读取成功',
            path: '/cosight2/workspace/2025年江苏足球联赛最终成绩预测分析.md'
        },
        {
            tool: 'execute_code',
            toolName: '代码执行',
            description: '检查HTML报告文件的总行数和一些关键内容',
            mode: 'sync',
            duration: 2500,
            result: '检查HTML报告文件的总行数和一些关键内容',
            path: '/cosight2/workspace/检查HTML报告文件的总行数和一些关键内容.py'
        },
        {
            tool: 'create_html_report',
            toolName: '报告生成',
            description: '结果保存到：2025年江苏足球联赛球队表现分析与预测报告.html',
            mode: 'sync',
            duration: 5000,
            result: 'HTML报告已经成功生成',
            url: '/cosight2/workspace/2025年江苏足球联赛球队表现分析与预测报告.html'
        }
    ]
};

// 导出所有工作流程数据（如果使用模块化）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        step0Workflow,
        step1Workflow,
        step2Workflow,
        step3Workflow,
        step4Workflow,
        step5Workflow
    };
}