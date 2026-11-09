/**
 * 简体中文词条 —— **本文件是词条形状的唯一真相**。
 *
 * `en-US.ts` 被约束为 `Messages` 类型（即本文件的结构），因此漏翻译一条
 * 会是编译错误，而不是运行期露出一个英文界面里的中文、或直接显示键名。
 * 新增词条一律先加在这里，再补英文。
 *
 * 文案取自 UX 稿的逐字提取（见 docs/design-tokens.md §7），标 `[稿]` 的地方
 * 不要"顺手润色"——那些字是与设计稿的一致性基准。
 */

export const zhCN = {
  app: {
    /** [稿] 侧栏字标 */
    wordmark: 'Co-Sight Harness',
    /** [稿] 侧栏副标题 */
    subtitle: '您的全天候个人秘书',
    /** 折叠/展开侧栏的按钮标题 */
    toggleSidebar: '切换侧栏',
    /** 侧栏与主面板之间那条可拖拽分割线的无障碍名（需求 UX-2）。它没有可见文字，名字就是全部语义。 */
    resizeSidebar: '调整侧栏宽度',
    /**
     * 拖拽手柄的当前值，作为 `aria-valuetext` 播报。裸数字没有单位，读屏用户听不出这是宽度。
     *
     * 不叫 `resizeSidebarValue`：侧栏与「工作区文件」面板两个手柄共用这一条，
     * 而它说的是"多少像素"，与具体是哪一列无关。
     */
    resizeValue: '{width} 像素',
    /** 侧栏 <nav> 的无障碍名称。 */
    navLabel: '主导航',
    skipToContent: '跳到主要内容',
  },

  nav: {
    /** [稿] */
    newChat: '新建对话',
    experts: '专家·技能',
    /** 2026-10-30 起不再按「A·B」拼段，改为与首页一致的产品叫法「Harness工程构建」。 */
    agentDev: 'Harness工程构建',
    knowledge: '知识库',
    observability: '观测',
  },

  /*
   * 侧栏底部的「使用说明」页（`/guide`）。
   *
   * 文案按**上手顺序**组织，而不是按功能清单罗列：先给一个能用的模型、再选工作区、
   * 然后开始对话。三步都带一个能直接跳过去的按钮，页面本身才不只是"又一份文档"。
   * 内容以仓库里的 QUICKSTART.md 与产品实际交互为准；不照搬原始 wiki 的截图与
   * 版本号，那些在界面上会过期。
   */
  guide: {
    /** 侧栏入口与页面的可访问名。 */
    navLabel: '使用说明',
    eyebrow: '使用说明',
    title: '从第一次打开到跑通第一条任务',
    lead: 'Co-Sight Harness 把模型、专家、技能、知识库和观测放进同一个工作台。完成下面三步配置，就可以开始对话。',
    startChat: '开始对话',
    configureModel: '去配置模型',
    previewClose: '关闭预览',
    tocLabel: '本页目录',
    toc: {
      quickstart: '三步上手',
      model: '模型配置',
      workspace: '工作区',
      modules: '功能地图',
      faq: '常见问题',
    },
    quickstart: {
      title: '三步上手',
      lead: '先给工作台一个可用的模型，再告诉它在哪里工作，然后就能开始对话。',
      model: {
        title: '配置模型',
        body: '打开「设置 → 模型设置」，点「新增模型」，填写供应商、模型标识与 API 密钥，并打开「设为当前使用」。',
        action: '去配置模型',
      },
      workspace: {
        title: '选择工作区',
        body: '点侧栏底部的工作区名称，新建工作区并绑定一个目录。默认模型和 Agent 代理可以先跟随全局。',
        action: '打开工作区设置',
      },
      chat: {
        title: '开始对话',
        body: '回到「新建对话」，选好模型直接提问；再选一个智能体，就由对应的专家来回答。',
        action: '新建对话',
      },
    },
    model: {
      title: '模型配置',
      lead: '模型由框架统一管理，所有模块共用同一份配置。',
      fieldsTitle: '新增模型时需要填写',
      fieldSupplier: '供应商：模型的提供方。',
      fieldName: '名称：在工作台里显示的名字，便于区分。',
      fieldId: '模型标识：调用时使用的模型 ID。',
      fieldGateway: '自定义网关地址：走私有网关或代理时填写。',
      fieldKey: 'API 密钥：只保存在本机数据目录，明文不会回传到浏览器。',
      currentTitle: '当前使用',
      currentBody:
        '全局同一时间只有一个「当前使用」模型。新增第一个模型时该开关默认打开，之后新增默认关闭，需要手动指定。',
      paramsTitle: '高级推理参数',
      paramsBody:
        '通常保持默认即可：温度 0.7、Top P 1、超时 120 秒；最大输出 Token 与上下文窗口留空表示使用模型默认值。',
    },
    workspace: {
      title: '工作区',
      lead: '工作区是一个绑定了目录的上下文：对话、文件与 Agent 都在这个目录下工作。',
      itemName: '名称：给这个工作区起一个能认出来的名字。',
      itemDir: '绑定目录：Agent 读写文件的根目录，可点「选择目录」从系统里挑一个。',
      itemModel: '默认模型：跟随全局，或只为这个工作区指定一个。',
      itemProxy: '默认 Agent 代理：通常跟随全局即可。',
      tip: '切换工作区后，依赖上下文的页面会重新加载，避免看到上一个工作区的数据。',
    },
    modules: {
      title: '功能地图',
      lead: '侧栏从上到下就是主要工作流。每张卡片配了入口截图，点开可以看大图。',
      conversationTitle: '新建对话',
      conversationBody:
        '选好模型直接提问，就是与通用 Agent 对话。点开输入框下方的智能体（如图中的「企业知识助手」），同一段对话就交给对应专家来回答。',
      conversationAlt: '新建对话页：输入框里选中「企业知识助手」后，AI 以该专家身份回答',
      expertsTitle: '专家·技能',
      expertsBody:
        '「专家」页按来源、状态、标签筛选内置与自建 Agent：内置的点「使用」直接进对话，自建的可以编辑、设计、评估。「技能」页管理自建 Skill。',
      expertsAlt: '专家·技能页：旅行规划、天气查询、软件开发团队等智能体卡片，以及筛选条件',
      agentDevTitle: 'Harness工程构建',
      agentDevBody:
        '用一句话描述需求就能创建智能体；建好后在同一页做优化（按异常现象或预期目标迭代）和评估（自动跑一轮验证）。技能同样支持创建与优化。',
      agentDevAlt: 'Harness工程构建页：创建、优化、评估智能体与技能五个入口',
      knowledgeTitle: '知识库',
      knowledgeBody:
        '点侧栏「知识库」跳到 Co-Knowledge 知识工程平台：新建知识库、导入文档、配置检索方式。要在工作台里打开它，先在「设置 → 知识库路由设置」新增地址。',
      knowledgeAlt: 'Co-Knowledge 知识库列表：知识库总数、文档数、图谱数与检索健康度',
      observabilityTitle: '观测',
      observabilityBody:
        '所有会话记录都在这里。打开一条就能回放：Agent 页看 events、tools、subagents 与耗时，对话页看主/子 Agent 往来，时间线看每一步发生的先后。',
      observabilityAlt: '观测详情页：Agent 指标卡、工具调用排行和子 Agent 列表',
    },
    faq: {
      title: '常见问题',
      knowledgeQ: '点「知识库」提示还没有配置路由？',
      knowledgeA:
        '去「设置 → 知识库路由设置」新增一条地址并设为当前可用，保存后立即生效。',
      modelQ: '模型列表里没有可用的模型？',
      modelA:
        '先确认它已「设为当前使用」，再检查 API 密钥与网关地址；使用私有网关时，把网关地址一并填上。',
      languageQ: '怎么切换界面语言？',
      languageA: '打开「设置 → 通用设置 → 界面语言」，切换后立即生效，并记录在本机。',
      addressQ: '打不开页面，或者不知道访问地址？',
      addressA:
        '以启动日志打印的地址为准：源码开发默认 http://localhost:4310，分发包默认 http://127.0.0.1:4300。',
    },
    footerHint: '还需要安装、源码启动与出包的细节？查看仓库根目录的 QUICKSTART.md 与 README.md。',
  },

  /*
   * 侧栏「知识库」不是宿主路由，而是「在新标签页打开用户在设置里配的那条地址」。
   * 一条都没配时不能把用户带到一个空页面——只能告诉他在哪里配、配完就生效。
   */
  knowledgeRoute: {
    missingTitle: '还没有配置知识库路由',
    missingHint: '请到「设置 → 知识库路由设置」新增一条地址，并把它设为当前可用。',
    loading: '正在加载知识库',
    loadFailedTitle: '读取知识库路由失败',
    loadFailedHint: '{reason}',
    openSettings: '去设置新增',
    frameTitle: '知识库：{name}',
  },

  /*
   * 侧栏「最近」（0a 需求：显示近期会话、默认 5 条、可展开、点击恢复会话）。
   * `showMore` 的 `{count}` 是可展开的会话总数（取数上限 100）。
   */
  recent: {
    heading: '最近',
    loading: '加载中…',
    empty: '暂无最近会话',
    error: '会话列表加载失败',
    retry: '重新加载',
    untitled: '新会话',
    showMore: '查看更多（{count}）',
    showLess: '收起',
    justNow: '刚刚',
    minutesAgo: '{count} 分钟前',
    hoursAgo: '{count} 小时前',
    daysAgo: '{count} 天前',
  },

  user: {
    /**
     * v1 无登录（D25 本地单用户），底部那一行就**没有用户名可显示**——它现在是「设置」入口
     * （齿轮 + `settings.title`）。稿里的 `User name` 占位串从来没渲染过：把占位符当数据
     * 渲染出来只会让人以为没加载成功。接上真实账号体系时，在这里补一条 `userName`，
     * 并在 `Sidebar` 的底部把它渲染回去。
     */
    openSettings: '打开设置',
  },

  /*
   * 这里原来有一组 `experts.*` 词条（页标题 / 筛选 / 搜索 / 使用次数 / 空态 / 错误态），
   * 服务的是框架自己渲染的专家页。D44 把专家页交给 smart-factory 的 `/agents` 之后，
   * 那一页连同它的词条一起删掉了——专家列表的界面归模块，宿主不再对它负责。
   * 侧栏标签不在这里，是 `nav.experts`。
   */

  workspace: {
    title: '工作区设置',
    close: '关闭工作区设置',
    current: '当前工作区',
    none: '未选择工作区',
    /** 侧栏底部那个入口的无障碍名称：可见文字是工作区名字，名字本身不足以说明点击后会发生什么。 */
    open: '打开工作区设置',
    /**
     * 入口按钮的可访问名。必须把可见文字（工作区名）包含进去——否则读屏用户看到的
     * 名字与实际显示不一致（WCAG 2.5.3），语音控制念不出这个按钮。
     */
    openNamed: '{name}（打开工作区设置）',
    /** 新建成功但激活失败：两件事都发生了，报错必须把这一点说清楚，不能笼统说"保存失败"。 */
    createdNotActivated: '工作区已创建，但没能切换过去：{reason}',
    listSection: '全部工作区',
    create: '新建工作区',
    createTitle: '新建工作区',
    editTitle: '编辑工作区',
    activeBadge: '当前使用',
    switchTo: '切换到此工作区',
    unboundDirectory: '未绑定目录',
    followsGlobal: '跟随全局',
    /** 删除的正好是当前工作区时的补充说明；服务端会一并清掉当前指针。 */
    deleteActiveNote: '它正是当前使用的工作区，删除后会回到「未选择工作区」。',
    /** 删除带目录的工作区时的补充说明：框架建的目录会删，外部绑定的只解绑。 */
    deleteDirectoryNote:
      '框架创建的工作区目录会连同其中的文件一并删除；外部绑定的目录只解除绑定，不会删除。',
    loading: '正在加载工作区',
    empty: {
      title: '还没有工作区',
      hint: '工作区把「默认模型」与「默认 Agent」绑在一起。点右上角「新建工作区」建一个。',
    },
    error: {
      title: '工作区列表加载失败',
    },
    field: {
      name: '名称',
      namePlaceholder: '例如：周报助手开发',
      directory: '绑定目录',
      directoryPlaceholder: '/home/me/projects/demo（可留空）',
      /**
       * 两句话分别对应两种填法，缺一句话就会出现"我以为留空 = 不绑定"的误解：
       * 留空**会建目录**（D32），这是界面上唯一能说出这件事的地方。
       */
      directoryHint:
        '留空时框架会在数据目录的工作区根下建一个同名文件夹并绑定；填了绝对路径则只绑定，不创建、也不要求已存在。点「选择目录」可以从系统文件管理器里挑一个；输入框为空时点它也会打开选择器。',
      /** 与服务端 absolutePathSchema 同口径（必须以 / 或盘符开头），在前端先拦住，别等服务端 422。 */
      directoryInvalid: '要填绝对路径（以 / 开头，或 D:\\ 这样的盘符）',
      /** 打开系统目录选择器的按钮。 */
      directoryPick: '选择目录',
      /**
       * 等待选择期间按钮上的字。原生窗口可能被浏览器挡在后面，按钮不说话用户会以为没反应。
       */
      directoryPicking: '等待选择…',
      defaultModel: '默认模型',
      defaultAgent: '默认 Agent 代理',
      followGlobalHint: '选「跟随全局」表示用设置里当前生效的那一个。',
    },
  },

  /**
   * 会话区右侧的「工作区文件」面板。
   *
   * 这一组里**没有"文件"这个词的复数与量词**：面板一次只回答"当前工作区里有什么"，
   * 所以每条文案都写成完整的句子，而不是"共 {n} 个文件"这种可拼接的碎片——
   * 中英文的语序与量词不同，拼出来的句子注定有一边别扭。
   */
  files: {
    /** 悬浮按钮的可访问名（可见内容只有图标，名字就是全部语义）。 */
    expand: '打开工作区文件面板',
    /** 面板标题栏上的收起按钮。 */
    collapse: '收起工作区文件面板',
    title: '工作区文件',
    refresh: '刷新工作区文件',
    /**
     * 全屏展示的开关按钮。
     *
     * **一个名字管两种状态**（状态由 `aria-pressed` 说出来），而不是"全屏展示 / 退出全屏"
     * 两条文案：名字随状态变的时候，读屏软件读出来的是"退出全屏，按钮"，听不出这是一个
     * **切换**还是另一个按钮。方向由图标表达（`maximize` ↔ `minimize`），这不违反
     * "信息不能只靠颜色/形状传达"——`aria-pressed` 才是那条信息的载体，图标只是顺带。
     */
    fullscreen: '全屏展示工作区文件面板',
    /** 面板左缘拖拽手柄的无障碍名。 */
    resize: '调整工作区文件面板宽度',
    /** 目录展开/收起按钮的无障碍名，`{name}` 是目录名。 */
    toggleDirectory: '{name}（展开或收起）',
    emptyDirectory: '这个目录是空的',
    /** 条目数被服务端上限截断。 */
    truncatedEntries: '文件太多，只列出前 {count} 项',
    /** 文件太大，只读回了开头一段；`{size}` 是完整体积。 */
    truncatedFile: '文件较大，只显示了开头一部分（完整体积 {size}）',
    /** 软链、设备文件等：列得出来，但点不动。 */
    notOpenable: '这类条目无法预览',
    /**
     * 右栏还没有选中文件时的空态。
     *
     * 这一句是**分栏之后才有的**：以前预览是"盖住目录树"的，没选文件时看到的就是树本身；
     * 现在两栏并排，右栏空着必须说出下一步做什么，否则新用户会以为预览坏了。
     */
    noPreview: {
      title: '还没有选中文件',
      hint: '在左边点一个文件，这里就会显示它的内容。',
    },
    /** 当前没有工作区（或还没选）时的空态。 */
    noWorkspace: {
      title: '还没有工作区',
      hint: '在左下角的工作区设置里新建或选一个，这里就会列出里面的文件。',
    },
    /** 工作区记录读不出来时的失败态。 */
    errorTitle: '读不到工作区信息',
  },

  settings: {
    title: '设置',
    close: '关闭设置',
    nav: {
      general: '通用设置',
      model: '模型设置',
      ragKnowledge: '知识库路由设置',
      agentProxy: 'Agent 代理配置',
      observation: '观测设置',
    },
    general: {
      title: '通用设置',
      language: '界面语言',
      languageHint: '切换后立即生效，并记录在本机。',
      dataSection: '数据与存储',
      dataHome: '数据目录',
      dataHomeHint:
        '业务数据与密钥都写在此目录下的 sqlite.db 与 .credentials.yaml。由服务端环境变量 COSIGHT_HOME 决定。',
      version: '服务端版本',
      aboutSection: '关于',
      about: 'Co-Sight Harness 框架：把各模块的开发、评估与优化串成一个工作台。',
    },
    /**
     * 三个列表型配置面板共用的动作与失败文案。
     *
     * 提到公共层而不是各写一份：删除确认的**措辞必须一样**，用户不该因为删的是
     * 工作区还是模型就看到两种语气的警告；失败文案的句式同理。真正不同的只有
     * 资源名，而资源名由调用方拼进 `{name}`。
     */
    form: {
      save: '保存',
      saving: '保存中…',
      cancel: '取消',
      edit: '编辑',
      delete: '删除',
      saveFailed: '保存失败：{reason}',
      deleteFailed: '删除失败：{reason}',
      actionFailed: '操作失败：{reason}',
      deleteConfirmTitle: '确认删除',
      deleteConfirmMessage: '「{name}」将被永久删除，此操作不可撤销。',
      /*
       * 校验文案也放在公共层：它由**字段名**参数化，而字段名来自上面各资源的
       * `field.*`。这样"请填写名称"和"请填写服务地址"是同一句话，
       * 不会一个说"请填写"、另一个说"不能为空"。
       */
      required: '请填写{field}',
      invalidNumber: '{field}要填一个数字',
      invalidPositiveInteger: '{field}要填一个正整数',
      invalidUrl: '{field}要以 http:// 或 https:// 开头',
      invalidUrlCredentials: '{field}里不要写账号密码',
      /*
       * 表单里有未保存的修改时，Esc 或关闭按钮会先弹这一句，而不是直接把表单丢掉。
       * 三个配置面板（工作区/模型/代理）共用：这不是"额外确认"，是"别把用户刚敲的
       * 东西静默吞掉"，措辞与行为都不该因为改的是哪个资源而不同。
       */
      discardTitle: '放弃未保存的修改？',
      discardMessage: '这个表单里的修改还没有保存，离开后会丢失。',
      discardConfirm: '放弃修改',
    },

    model: {
      title: '模型设置',
      listSection: '模型配置',
      activeBadge: '当前使用',
      keyConfigured: '密钥已配置',
      keyMissing: '未配置密钥',
      activate: '设为当前使用',
      loading: '正在加载模型配置',
      empty: {
        title: '还没有模型配置',
        hint: '点右上角「新增模型」添加一个。被设为「当前使用」的那一个才会真正被使用。',
      },
      error: {
        title: '模型配置加载失败',
      },
      create: '新增模型',
      createTitle: '新增模型',
      editTitle: '编辑模型',
      /**
       * 行内操作的可访问名。
       *
       * 列表里每一行都有「编辑」「删除」，读屏软件挨个念过去只会得到一串一模一样的
       * 词；aria-label 里带上这一行的名字才分得清。可见文字必须原样出现在 aria-label 里
       * （WCAG 2.5.3）：语音控制的用户喊的仍然是屏幕上那两个字的「编辑」。
       */
      action: {
        ariaLabel: '对「{name}」的操作',
        activate: '把「{name}」设为当前使用',
        edit: '编辑「{name}」',
        remove: '删除「{name}」',
        /**
         * 可点标题的可访问名。可见文字是模型名本身，这句话**必须**把它包进去——
         * WCAG 2.5.3 要求可访问名包含可见标签，语音控制的用户喊的是屏幕上那个名字。
         */
        view: '查看「{name}」的详情',
      },
      /** 删掉正在生效的那个模型时追加在确认语之后——不自动切换，所以必须说清后果。 */
      deleteActiveWarning: '删除后不会有任何模型处于「当前使用」。',
      /** 列表行与详情里的地址占位（`baseUrl` 为 null = 用供应商官方地址）。 */
      baseUrlDefault: '跟随供应商默认地址',
      /** 只读详情（点列表行进入）。 */
      detail: {
        title: '模型详情',
        back: '返回列表',
        unset: '跟随默认',
        unlimited: '不限制',
        createdAt: '创建时间',
        updatedAt: '更新时间',
        keyHint: '为安全起见，密钥明文不会回传到浏览器。要更换密钥请点「编辑」重新填一个。',
      },
      /**
       * 模块接入卡：别的模块（另一个本机进程）怎么从框架取模型配置。
       * 这块信息此前只在服务端代码与文档里，界面上看不到 → 模块作者只好往自己的
       * `.env` 里再抄一份密钥，于是密钥散到了第二个地方。
       */
      moduleAccess: {
        title: '模块接入：其他模块如何取模型配置',
        intro: '本机的其他模块进程（如智慧工厂）可以用下面这组接口取到模型配置——列表不含密钥，按 id 查详情会带明文密钥，供它们启动模型客户端使用。',
        baseUrl: '接口基址',
        tokenFile: '令牌文件',
        tokenFileUnknown: '读取中…（路径取自服务端的实际数据目录）',
        copy: '复制',
        copied: '已复制',
        copyFailed: '复制失败，请手动选中',
        copyAriaLabel: '复制{label}',
        /**
         * 键名曾是 `readOnly`，D33 之后这组接口开了写操作，键名跟着改——
         * 一个叫 `readOnly` 的键里放着"这组接口可写"的文案是注释腐烂的一种。
         */
        scope:
          '这组接口可读也可写：新增、修改、删除模型都能做。只需要读一份配置去起客户端的模块，别顺手也调写接口——令牌一旦泄漏，代价会从「配置被读走」变成「配置被改掉」。',
        notEnv: '令牌请让模块进程自己读文件，不要写进 .env——模块会把环境变量透传给模型子进程。',
        localOnly: '接口只接受本机回环地址的请求，浏览器页面拿不到它。',
        curlHint: '验证一下（在终端里执行）：',
      },
      /** 契约里的 `max(64)`/`max(128)` 这些长度上限，在提交前就挡住。 */
      invalidLength: '{field}不能超过 {max} 个字符',
      invalidRange: '{field}要在 {min} 到 {max} 之间',
      field: {
        provider: '供应商',
        providerHint: '当前仅支持 Anthropic，其他供应商类型不提供。',
        label: '名称',
        labelPlaceholder: '例如：内部 Qwen3-32B',
        modelName: '模型标识',
        modelNamePlaceholder: '例如：qwen3-32b',
        modelNameHint: '发给供应商的 model 字段，不是你给它起的显示名。',
        baseUrl: '自定义网关地址',
        baseUrlPlaceholder: 'https://gateway.internal/v1（可留空）',
        baseUrlHint: '留空表示用该供应商的官方地址。',
        apiKey: 'API 密钥',
        apiKeySet: '已配置。为安全起见明文不再回显，留空表示不修改。',
        apiKeyUnset: '尚未配置。留空表示不设置。',
        clearKey: '清除密钥',
        clearKeyPending: '将清除密钥（点此撤销）',
      },
      provider: {
        openai: 'OpenAI',
        anthropic: 'Anthropic',
        'azure-openai': 'Azure OpenAI',
        ollama: 'Ollama（本地）',
        'openai-compatible': 'OpenAI 兼容',
      },
      advanced: {
        title: '推理参数',
        /** 跟在这个标题后面、`<summary>` 之内：收起状态下也要看得到，才解释得了"为什么不用管它"。 */
        collapsedHint: '默认值适用于大多数场景，需要时展开调整',
        temperature: '温度',
        temperatureHint: '0 最确定、2 最随机，默认 0.7。',
        topP: 'Top P',
        topPHint: '与温度二选一调整即可，默认 1。',
        maxOutputTokens: '最大输出 Token',
        maxOutputTokensHint: '留空表示不限制。',
        contextWindow: '上下文窗口',
        contextWindowHint: '留空表示跟随该模型的默认值。',
        timeoutSeconds: '超时（秒）',
        isActive: '设为当前使用',
        isActiveHint:
          '全局同时只有一个模型处于「当前使用」。还没有生效模型时，新增的模型会默认打开这个开关。',
      },
    },

    /**
     * 知识库路由。
     *
     * 与模型/代理不同，这一项**同时**是"给各模块用的配置"：模块从只读接口取「当前可用」
     * 的那一条，把用户导到知识库界面；宿主自己的左侧「知识库」菜单也直接在
     * **新标签页**打开这一条。
     */
    ragKnowledge: {
      title: '知识库路由设置',
      listSection: '知识库跳转路由',
      activeBadge: '当前可用',
      activate: '设为可用',
      loading: '正在加载知识库路由',
      empty: {
        title: '还没有配置知识库路由',
        hint: '点右上角「新增」添加一个地址。被设为「当前可用」的那一条才会用于跳转。',
      },
      error: {
        title: '知识库路由加载失败',
      },
      create: '新增',
      createTitle: '新增知识库路由',
      editTitle: '编辑知识库路由',
      /** 与 `settings.model.action.*` 同理：行内操作要能区分是哪一行。 */
      action: {
        ariaLabel: '对「{name}」的操作',
        activate: '把「{name}」设为可用',
        edit: '编辑「{name}」',
        remove: '删除「{name}」',
      },
      /** 与 `settings.model.invalidLength` 同理。 */
      invalidLength: '{field}不能超过 {max} 个字符',
      invalidRange: '{field}要在 {min} 到 {max} 之间',
      /** 删掉可用项时追加在确认语之后——不自动补位，所以必须说清后果。 */
      deleteActiveWarning: '删除后左侧「知识库」将没有可跳转的地址，各模块也读不到。',
      /** 列表行里显示登录账号；密码永不出现在这里。 */
      metaAccount: '账号：{username}',
      field: {
        name: '名称',
        namePlaceholder: '例如：产品知识库',
        routeUrl: '跳转路由',
        routeUrlPlaceholder: 'https://kb.internal/kb/42',
        routeUrlHint: '以 http:// 或 https:// 开头。不要把账号密码写进地址，请填在下面两栏。',
        username: '用户名',
        usernamePlaceholder: '例如：admin',
        usernameHint: '登录知识库用的账号；不需要登录时可留空。',
        password: '密码',
        passwordSet: '已配置。为安全起见明文不再回显，留空表示不修改。',
        passwordUnset: '尚未配置。留空表示不设置。',
        clearPassword: '清除密码',
        clearPasswordPending: '将清除密码（点此撤销）',
        /**
         * 模块访问知识服务的 Agent API Key，对应 smart-factory 的
         * `CO_KNOWLEDGE_API_KEY`。标签不写环境变量名（太长会挤掉输入框的宽度），
         * 环境变量写在提示语里。
         */
        apiKey: 'API Key',
        apiKeySet: '已配置。为安全起见明文不再回显，留空表示不修改。',
        apiKeyUnset: '尚未配置。留空表示不设置。',
        /** 服务端配了默认值时的"留空"含义——否则用户会以为自己刚保存的东西没生效。 */
        apiKeyUnsetDefault: '尚未配置。留空表示使用服务端预置的默认密钥。',
        apiKeyHint: '模块（如智慧工厂）访问知识服务时用它，对应环境变量 CO_KNOWLEDGE_API_KEY。',
        clearApiKey: '清除 API Key',
        clearApiKeyPending: '将清除 API Key（点此撤销）',
        description: '说明',
        descriptionPlaceholder: '这个知识库收录什么（可留空）',
        isActive: '设为可用',
        isActiveHint: '全局同时只有一条知识库处于「当前可用」。',
      },
    },

    agentProxy: {
      title: 'Agent 代理配置',
      currentSection: '当前 Agent 代理',
      listSection: '代理配置',
      defaultBadge: '默认',
      enabledBadge: '已启用',
      disabledBadge: '已停用',
      setDefault: '设为默认',
      loading: '正在加载 Agent 代理配置',
      engine: {
        claudeAgentSdk: 'Claude Code',
        fake: '测试引擎',
      },
      engineUnavailable: {
        title: '未安装 Claude Code CLI',
        hint: '本发行物不包含 CLI。安装后即可运行智能体：',
      },
      empty: {
        title: '还没有 Agent 代理配置',
        hint: '新增走接口（POST /api/agent-proxies），这里负责查看、编辑、删除与设为默认。框架只把配置存下来并显示，代理怎么跑由各模块自己实现。',
      },
      error: {
        title: 'Agent 代理配置加载失败',
      },
      editTitle: '编辑 Agent 代理',
      /** 与 `settings.model.action.*` 同理：行内操作要能区分是哪一行。 */
      action: {
        ariaLabel: '对「{name}」的操作',
        setDefault: '把「{name}」设为默认',
        edit: '编辑「{name}」',
        remove: '删除「{name}」',
      },
      /** 与 `settings.model.invalidLength` 同理。 */
      invalidLength: '{field}不能超过 {max} 个字符',
      invalidRange: '{field}要在 {min} 到 {max} 之间',
      /** 删掉默认代理时追加在确认语之后——不会自动改选别的代理，所以必须说清后果。 */
      deleteDefaultWarning: '删除后不会再有默认代理。',
      field: {
        engine: '引擎',
        version: '版本',
        name: '名称',
        namePlaceholder: '例如：默认编码代理',
        description: '描述',
        descriptionPlaceholder: '这个代理做什么用（可留空）',
        agentType: '代理类型',
        agentTypeHint: '取值由目标模块定义，框架只透传、不枚举。',
        endpoint: '服务地址',
        endpointPlaceholder: 'https://agent.internal/run（可留空）',
        endpointHint: '留空表示由模块自行决定。',
        token: '访问令牌',
        tokenSet: '已配置。为安全起见明文不再回显，留空表示不修改。',
        tokenUnset: '尚未配置。留空表示不设置。',
        clearToken: '清除令牌',
        clearTokenPending: '将清除令牌（点此撤销）',
      },
      runtime: {
        title: '运行与额度',
        maxIterations: '最大迭代步数',
        maxIterationsHint: '单轮任务最多走多少步，默认 50。',
        parallelism: '并行度',
        parallelismHint: '同时展开的分支数，默认 4。',
        timeoutSeconds: '超时（秒）',
        timeoutSecondsHint: '单轮任务的墙钟上限，默认 600。',
      },
      switches: {
        title: '能力开关',
        enabled: '启用',
        enabledHint: '停用后框架不会把它下发给模块，配置本身仍保留。',
        isDefault: '设为默认代理',
        isDefaultHint: '全局同时只有一个默认代理。',
        memoryEnabled: '启用记忆',
        condensationEnabled: '启用上下文压缩',
        securityAnalyzer: '安全分析器',
        securityAnalyzerHint: '对工具调用做安全审查的方式。',
      },
      analyzer: {
        none: '不审查',
        invariant: '不变量检查',
        llm: '模型审查',
      },
      extra: {
        title: '模块私有配置',
        hint: '这些字段由模块自己读写，框架不解读内容，因此这里只显示、不改。',
      },
    },

    observation: {
      title: '会话清理',
      description: '设置会话自动废弃和清除的时间阈值',
      checking: '正在检测观测服务…',
      serviceUnavailable: '观测服务未连接',
      serviceUnavailableHint: '无法连接到会话观测服务（cosight-viewer）。请先启动服务后再配置。',
      retry: '重试',
      loadFailed: '加载配置失败',
      saveSuccess: '✓ 配置已保存',
      saveFailed: '保存配置失败',
      abandonHours: '废弃小时数',
      abandonHoursHint: '超过指定小时无活动的会话自动标记为废弃',
      purgeDays: '清除天数',
      purgeDaysHint: '自动清理超过指定天数的已完成、错误、废弃会话',
      autoCleanup: '启用自动清理',
      autoCleanupHint: '每 24 小时自动清理超过指定天数的旧会话',
      lastRun: '上次清理',
      lastRunAuto: '自动',
      lastRunManual: '手动',
      lastRunDetail: '清理了 {sessions} 个会话、{events} 条事件、{agents} 个 Agent',
    },

  },

  module: {
    loading: '正在加载模块…',
    /** 模块清单里没有声明该能力时显示。 */
    missing: {
      title: '模块尚未接入',
      hint: '该页面由独立模块提供。把模块的 module.json 放进数据目录的 modules/ 下即可挂载。',
    },
    error: {
      title: '模块未能加载',
      hint: '模块服务可能没有启动，或清单里的 entry 地址不可达。',
    },
    frameTitle: '{name} 模块',
  },

  error: {
    title: '出错了',
    retry: '重试',
    /** 宿主路由没匹配上（用户手改了地址栏）。 */
    notFound: {
      title: '页面不存在',
      hint: '地址可能输错了，或者这个页面已经不在当前版本里。',
      back: '回到首页',
    },
    /** 与服务端 AppError 的 messageKey 一一对应（见 framework/shared/src/errors.ts）。 */
    internal: '服务内部错误',
    /** 分组的第二、三条是工作区文件浏览的：`400` 在这里只可能是"对这个路径做不了这件事"。 */
    bad_request: {
      default: '请求格式不正确',
      workspace_not_a_directory: '这个路径不是一个目录，列不出内容',
      workspace_not_a_file: '这个路径不是一个普通文件，读不了内容',
    },
    not_found: {
      /** 分组兜底：服务端新增了资源类型、词表还没跟上时用这句（见 translate.ts）。 */
      default: '未找到',
      route: '接口不存在',
      workspace: '未找到工作区',
      expert: '未找到专家',
      model: '未找到模型配置',
      agent_proxy: '未找到 Agent 代理配置',
      /** 工作区记录还在，但它绑定的目录在磁盘上没了——与"文件不存在"不是一回事。 */
      workspace_directory: '工作区绑定的目录不存在了',
      workspace_file: '工作区里没有这个文件',
    },
    conflict: {
      default: '操作与现有数据冲突，请检查后重试',
      workspace: '工作区名称已存在',
    },
    validation_failed: '请求参数校验未通过',
    payload_too_large: {
      default: '请求体过大',
      workspace_image: '这张图片超过了预览上限（2 MiB）',
    },
    unsupported_media_type: {
      default: '不支持的内容类型',
      workspace_file: '这个文件不是能预览的文本或图片',
    },
    rate_limited: '请求过于频繁，请稍后再试',
    /*
     * 从字符串改成"分组 + default"：模块面令牌失败回的是 `error.unauthorized.module_token`，
     * 若 `unauthorized` 只是个字符串叶子，`translateApiErrorKey` 会截短到它，
     * 于是"令牌不对"被说成"会话已失效，请重新进入"——用户去重新进一次会话，
     * 什么也不会改变。`not_found` 那个分组早就是这么处理的，理由一样。
     */
    unauthorized: {
      default: '会话已失效，请重新进入',
      module_token: '模块面令牌缺失或无效（模块应读取数据目录下的 .module-token）',
    },
    /*
     * 从字符串改成"分组 + default"，理由与 `unauthorized` 完全相同（那条注释就在上面）：
     * 新增的 `workspace_file` / `loopback_only` 若没有分组可落，`translateApiErrorKey`
     * 会把它截短到 `error.forbidden`，于是"这个路径不在工作区内，已拒绝"被说成
     * "没有权限执行该操作"——用户会去查账号权限，而问题出在他填的路径上。
     */
    forbidden: {
      default: '没有权限执行该操作',
      workspace_file: '这个路径不在工作区里，已拒绝',
      loopback_only: '工作区文件浏览只对本机开放，请从本机访问',
      /** 目录选择会在桌面上弹窗口，所以也只对回环来源开放。 */
      directory_picker: '目录选择只对本机开放，请从本机打开应用',
    },
    not_implemented: {
      default: '该功能尚未实现',
      model_probe: '模型连通性探测尚未实现',
    },
    /*
     * 系统目录选择器（`services/directory-picker.ts`）的三条失败文案。
     * 它们跨了三个 HTTP 状态（501 / 500 / 500），所以按**功能**分组，而不是塞进
     * `not_implemented` 与 `internal` 各自的叶子里——那两组的 default 说的都不是
     * "改用手输"这件事，用户读到"该功能尚未实现"会以为整个绑定目录都坏了。
     */
    directory_picker: {
      default: '打不开系统目录选择器，请手动输入路径',
      unavailable: '这台机器上打不开系统目录选择器（没有可用的图形界面或对话框工具），请手动输入路径',
      failed: '目录选择器异常退出，请手动输入路径',
      timeout: '目录选择器等太久超时了，请手动输入路径',
    },
    upstream_unavailable: '依赖的上游服务不可用',
    /** 网络层失败（请求根本没到达服务端）与上面的服务端错误码不是一回事。 */
    network: '无法连接服务端，请确认后端已启动',
  },
};

/*
 * 刻意不加 `as const`：加了之后每个词条会推成**字面量类型**，
 * `en-US.ts` 就必须逐字复制中文，翻译会变成编译错误。
 * 不加则叶子类型是 string，`Messages` 只约束"结构相同"，这正是我们要的。
 */

