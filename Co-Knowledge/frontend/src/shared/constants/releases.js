/**
 * 发布记录：**最新版本在最前**，第一条即当前版本。
 *
 * 发版时在数组顶部新增一条记录，同时更新 `package.json` 的 `version`：
 *   - `version` 必须唯一，全局用它做「已读」标记的键；
 *   - `date` 用 `YYYY-MM-DD`，未发布可留空（页面上不显示日期）；
 *   - `features` / `fixes` 按需填写，两组都为空时不渲染该区块。
 *
 * 文案中英各一份：界面语言的判定与切换走 `@/shared/lib/language`（切换即整页重载），
 * 组件用 `releaseText(release, locale)` 取当前语言。
 *
 * 登录页页脚、左栏底部与「版本更新」页都读这份清单，改这里即可，组件无需改动。
 */
export const releases = [
  {
    version: '0.2.0',
    date: '2026-11-07',
    title: {
      zh: '开源发布',
      en: 'Open-source release'
    },
    features: {
      zh: [
        '开源发布：一条 Compose 启动前端、后端与存储，模型全部接入自己的 OpenAI 兼容端点。',
        '新增本地账号登录、强制改密与会话管理，同一份构建支持无认证、本地与网关三种模式。',
        '新增统一任务中心，集中查看文件导入、图谱抽图与图谱导入任务，并支持取消与重试。',
        '新增 Text2SQL 分析工作台，维护语义 Schema 与指标后用自然语言提问，查看 SQL、结果与图表。',
        '新增版本更新页与登录更新提醒，左栏和登录页显示当前版本号。',
        '对外 API 统一为纯 REST 与 RFC 9457 错误模型，全部资源收敛到 /api/co-knowledge/v1 前缀。'
      ],
      en: [
        'Open-source release: one Compose stack starts the frontend, backend, and storage, with every model connected to your own OpenAI-compatible endpoint.',
        'Local accounts: sign-in, forced password change, and session management; one build supports none, local, and gateway authentication modes.',
        'Task center: track file imports, graph extraction, and graph imports in one place, with cancel and retry.',
        'Text2SQL workspace: maintain a semantic schema and metrics, ask questions in natural language, and review the SQL, results, and charts.',
        'Release notes page and post-login update reminder; the sidebar and login page show the current version.',
        'The external API now uses plain REST with RFC 9457 errors, with every resource under the /api/co-knowledge/v1 prefix.'
      ]
    },
    fixes: {
      zh: ['修复大图谱画布渲染卡顿与批量导入耗时过长的问题。'],
      en: ['Fixed canvas lag on large graphs and long batch import times.']
    }
  },
  {
    version: '0.1.13',
    date: '2026-10-30',
    title: {
      zh: '检索编排全屏画布',
      en: 'Full-screen workflow canvas'
    },
    features: {
      zh: ['检索编排支持沉浸式全屏，并与图谱画布共用全屏控制。'],
      en: ['Retrieval workflows support an immersive full-screen canvas that shares controls with the graph canvas.']
    },
    fixes: {
      zh: ['修复刷新反馈导致图谱画布工具栏换行的问题。'],
      en: ['Fixed the graph canvas toolbar wrapping when refresh feedback appeared.']
    }
  },
  {
    version: '0.1.12',
    date: '2026-10-29',
    title: {
      zh: '图谱画布操作优化',
      en: 'Graph canvas controls'
    },
    features: {
      zh: [],
      en: []
    },
    fixes: {
      zh: [
        '保留单一全屏入口，修复进出全屏时视口位置和工具栏对齐的问题。',
        '修复侧栏收起时底部控件排列拥挤的问题。'
      ],
      en: [
        'Kept a single full-screen entry and fixed viewport position and toolbar alignment when entering or leaving full screen.',
        'Fixed crowded footer controls when the sidebar was collapsed.'
      ]
    }
  },
  {
    version: '0.1.11',
    date: '2026-10-29',
    title: {
      zh: '图谱查询与沉浸式浏览',
      en: 'Graph queries and immersive browsing'
    },
    features: {
      zh: ['图谱查询可设置返回数量上限，图谱画布支持全屏操作。'],
      en: ['Graph queries can limit the number of returned items, and the graph canvas supports full-screen operation.']
    },
    fixes: {
      zh: [],
      en: []
    }
  },
  {
    version: '0.1.10',
    date: '2026-10-28',
    title: {
      zh: '按知识来源创建检索流程',
      en: 'Create retrieval flows by knowledge source'
    },
    features: {
      zh: [
        '检索流程可选择文档、图谱或数据库来源，并匹配对应流程模板。',
        '新增知识图谱构建算子配置，并更新图谱创建流程。'
      ],
      en: [
        'Retrieval flows can target document, graph, or database sources and match the corresponding template.',
        'Added graph-building operator configuration and updated the graph creation flow.'
      ]
    },
    fixes: {
      zh: ['统一产品标志的透明矢量版本，修正对话头像的显示尺寸。'],
      en: ['Unified the transparent vector brand mark and fixed the chat avatar size.']
    }
  },
  {
    version: '0.1.9',
    date: '2026-10-25',
    title: {
      zh: '图谱实体创建',
      en: 'Create graph entities'
    },
    features: {
      zh: ['支持新增图谱实体、按需创建关系，以及刷新图谱画布。'],
      en: ['Add graph entities, create relations on demand, and refresh the graph canvas.']
    },
    fixes: {
      zh: [],
      en: []
    }
  },
  {
    version: '0.1.8',
    date: '2026-10-24',
    title: {
      zh: '更多操作入口统一',
      en: 'Consistent more-actions menus'
    },
    features: {
      zh: [],
      en: []
    },
    fixes: {
      zh: ['统一列表行与面板的更多操作图标，使两个入口易于区分。'],
      en: ['Unified the more-actions icons on list rows and panels so the two entries are easy to tell apart.']
    }
  },
  {
    version: '0.1.7',
    date: '2026-10-24',
    title: {
      zh: '管理操作与列表刷新',
      en: 'Management actions and list refresh'
    },
    features: {
      zh: ['补齐管理列表操作和刷新入口，并支持管理对话历史。'],
      en: ['Added missing management list actions and refresh entries, plus chat history management.']
    },
    fixes: {
      zh: [],
      en: []
    }
  },
  {
    version: '0.1.6',
    date: '2026-10-23',
    title: {
      zh: '检索编排与连线编辑',
      en: 'Workflow editing and edge wiring'
    },
    features: {
      zh: ['编排节点可配置、排序并保存多个算子，支持通过拖拽、点击或键盘重新连线。'],
      en: ['Workflow nodes can configure, order, and save multiple operators, with rewiring by drag, click, or keyboard.']
    },
    fixes: {
      zh: ['改善节点排布、连线预览和算子配置抽屉的操作体验。'],
      en: ['Improved node layout, edge previews, and the operator configuration drawer.']
    }
  },
  {
    version: '0.1.5',
    date: '2026-10-23',
    title: {
      zh: '图谱信息与实体编辑',
      en: 'Graph info and entity editing'
    },
    features: {
      zh: ['更新图谱信息展示和实体编辑流程。'],
      en: ['Updated the graph info display and the entity editing flow.']
    },
    fixes: {
      zh: [],
      en: []
    }
  },
  {
    version: '0.1.4',
    date: '2026-10-23',
    title: {
      zh: '知识库详情与文档管理',
      en: 'Knowledge base details and document management'
    },
    features: {
      zh: ['更新知识库详情页和文档管理界面。'],
      en: ['Updated the knowledge base detail page and the document management UI.']
    },
    fixes: {
      zh: [],
      en: []
    }
  },
  {
    version: '0.1.3',
    date: '2026-10-22',
    title: {
      zh: '创建流程统一',
      en: 'Unified create dialogs'
    },
    features: {
      zh: [],
      en: []
    },
    fixes: {
      zh: ['统一知识库、检索流程、模型和 API 密钥的创建弹窗。'],
      en: ['Unified the create dialogs for knowledge bases, retrieval workflows, models, and API keys.']
    }
  },
  {
    version: '0.1.2',
    date: '2026-10-21',
    title: {
      zh: '响应式登录页',
      en: 'Responsive login page'
    },
    features: {
      zh: ['新增适配桌面和移动端的登录页。'],
      en: ['Added a login page that adapts to desktop and mobile.']
    },
    fixes: {
      zh: [],
      en: []
    }
  },
  {
    version: '0.1.1',
    date: '2026-10-21',
    title: {
      zh: '站内字体与对话布局',
      en: 'Self-hosted fonts and chat layout'
    },
    features: {
      zh: [],
      en: []
    },
    fixes: {
      zh: ['将字体改为站内加载，并统一对话测试的工作区布局。'],
      en: ['Moved fonts to self-hosted files and unified the chat test workspace layout.']
    }
  },
  {
    version: '0.1.0',
    date: '2026-10-21',
    title: {
      zh: '工作台初版',
      en: 'First workspace release'
    },
    features: {
      zh: ['提供知识库管理、检索编排、知识图谱、模型管理与深色主题。'],
      en: ['Knowledge base management, retrieval workflows, knowledge graphs, model management, and a dark theme.']
    },
    fixes: {
      zh: [],
      en: []
    }
  }
]

/** 当前版本（清单第一条）。 */
export const currentRelease = releases[0]

/**
 * 取一条发布记录在当前界面语言下的文案。
 * 某个语言缺字段时回落到中文，保证任何语言下都不会渲染出空白标题。
 *
 * @param {typeof releases[number]} release
 * @param {string} locale vue-i18n 的 `locale`（`zh` / `en`）
 */
export function releaseText (release, locale) {
  const language = String(locale || '').toLowerCase()
  const key = language.startsWith('en') ? 'en' : 'zh'
  const pick = field => {
    if (field === null || field === undefined) {
      return ''
    }
    if (Object.prototype.hasOwnProperty.call(field, key)) {
      return field[key]
    }
    return field.zh
  }
  return {
    version: release.version,
    date: release.date || '',
    title: pick(release.title),
    features: pick(release.features) || [],
    fixes: pick(release.fixes) || []
  }
}
