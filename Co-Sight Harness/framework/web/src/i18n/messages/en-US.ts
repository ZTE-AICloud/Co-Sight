/**
 * English messages (D28 = B: v1 ships bilingual).
 *
 * 类型标注 `: Messages` 是这段代码里最有价值的一行：它把"漏翻译"从
 * "上线后英文界面里夹一句中文"变成"编译不过"。新增中英之外的语种时，
 * 照抄这个写法即可获得同样的保障。
 *
 * 翻译口径（避免后来者反复争论）：
 * - 产品名、`Co-Sight Harness` 字标、稿中的专有名词不译。
 * - 导航与按钮用**动词短语**而不是名词（`Use` 而不是 `Usage`），
 *   因为它们是可点击的动作，不是标签。
 * - 长度尽量贴近中文：导航项 248×40 的胶囊、卡片 4 个按钮都要在英文下
 *   仍然一屏放得下（卡片按钮行按 4 等分，见 ExpertCard.module.css）。
 */

import type { Messages } from '../types';

export const enUS: Messages = {
  app: {
    wordmark: 'Co-Sight Harness',
    subtitle: 'Your all-day personal assistant',
    toggleSidebar: 'Toggle sidebar',
    /** Accessible name for the draggable divider between sidebar and panel (UX-2); it has no visible text. */
    resizeSidebar: 'Resize sidebar',
    /** `aria-valuetext` for either drag handle (the sidebar's and the workspace files panel's). */
    resizeValue: '{width} pixels',
    navLabel: 'Main navigation',
    skipToContent: 'Skip to main content',
  },

  nav: {
    newChat: 'New chat',
    experts: 'Experts · Skills',
    agentDev: 'Harness Build',
    knowledge: 'Knowledge Base',
    observability: 'Observability',
  },

  /*
   * The "User guide" page at `/guide`, reachable from the sidebar footer.
   *
   * Ordered by onboarding sequence rather than by feature list: get a model,
   * pick a workspace, start chatting. Every step carries a working action so
   * the page is a launcher, not a second copy of the README.
   */
  guide: {
    navLabel: 'User guide',
    eyebrow: 'User guide',
    title: 'From first launch to your first task',
    lead: 'Co-Sight Harness brings models, experts, skills, knowledge bases, and observability into one workbench. Complete the three steps below and start chatting.',
    startChat: 'Start a chat',
    configureModel: 'Configure a model',
    previewClose: 'Close preview',
    tocLabel: 'On this page',
    toc: {
      quickstart: 'Quick start',
      model: 'Models',
      workspace: 'Workspaces',
      modules: 'Feature map',
      faq: 'FAQ',
    },
    quickstart: {
      title: 'Get started in three steps',
      lead: 'Give the workbench a usable model, tell it where to work, then start a conversation.',
      model: {
        title: 'Configure a model',
        body: 'Open Settings → Models, choose Add model, and fill in the provider, model ID, and API key. Turn on Set as current.',
        action: 'Configure a model',
      },
      workspace: {
        title: 'Choose a workspace',
        body: 'Click the workspace name at the bottom of the sidebar, create a workspace, and bind a directory. Leave the default model and agent on Follow global for now.',
        action: 'Open workspace settings',
      },
      chat: {
        title: 'Start a conversation',
        body: 'Go to New chat and pick a model to ask a general agent. Add an expert agent to hand the task to that expert.',
        action: 'New chat',
      },
    },
    model: {
      title: 'Model settings',
      lead: 'Models are managed by the framework and shared by every module.',
      fieldsTitle: 'When adding a model',
      fieldSupplier: 'Provider: who serves the model.',
      fieldName: 'Name: the label shown in the workbench.',
      fieldId: 'Model ID: the identifier used when calling the model.',
      fieldGateway: 'Custom gateway: fill this in when traffic goes through a private gateway or proxy.',
      fieldKey: 'API key: stored in the local data directory; the plaintext value is never sent back to the browser.',
      currentTitle: 'Current model',
      currentBody:
        'Only one model can be current at a time. The switch is on by default for the first model and off afterwards, so you choose explicitly.',
      paramsTitle: 'Advanced inference settings',
      paramsBody:
        'The defaults are usually fine: temperature 0.7, Top P 1, timeout 120 seconds. Leaving max output tokens or context window empty uses the model defaults.',
    },
    workspace: {
      title: 'Workspaces',
      lead: 'A workspace is a context bound to a directory: conversations, files, and agents work under that directory.',
      itemName: 'Name: something you will recognize later.',
      itemDir: 'Bound directory: the root the agent reads and writes. Use Choose directory to pick one.',
      itemModel: 'Default model: follow the global model, or pin one for this workspace.',
      itemProxy: 'Default agent proxy: Follow global is usually right.',
      tip: 'Switching workspaces reloads pages that depend on the context, so you never see data from the previous workspace.',
    },
    modules: {
      title: 'Feature map',
      lead: 'The sidebar, top to bottom, is the main workflow. Each card includes a screenshot of its entry; click one to see it full size.',
      conversationTitle: 'New chat',
      conversationBody:
        'Pick a model and ask: the general agent answers. Pick an agent under the composer (such as Enterprise Knowledge Assistant in the screenshot) to hand the same conversation to that expert.',
      conversationAlt: 'New chat: Enterprise Knowledge Assistant selected under the composer, answering as that expert',
      expertsTitle: 'Experts · Skills',
      expertsBody:
        'The Experts tab filters built-in and custom agents by source, status, or tag: use built-ins directly, or edit, design, and evaluate your own. The Skills tab manages custom skills.',
      expertsAlt: 'Experts tab: cards for a travel planner, weather assistant, software team, and more',
      agentDevTitle: 'Harness Build',
      agentDevBody:
        'Describe your need in one sentence to create an agent, then optimize it (iterate from symptoms or goals) and evaluate it (an automatic verification run) on the same page. Skills work the same way.',
      agentDevAlt: 'Harness Build page: the five entries for creating, optimizing, and evaluating agents and skills',
      knowledgeTitle: 'Knowledge Base',
      knowledgeBody:
        'The sidebar entry opens the Co-Knowledge platform: create a knowledge base, import documents, and configure retrieval. To open it inside the workbench, add its address under Settings → Knowledge Base Route first.',
      knowledgeAlt: 'Co-Knowledge knowledge base list with totals, document and graph counts, and retrieval health',
      observabilityTitle: 'Observability',
      observabilityBody:
        'Every session lands here. Open one to replay it: the Agent tab shows events, tools, subagents, and duration; the Conversation tab shows the main/subagent transcript; the Timeline tab shows the order of every step.',
      observabilityAlt: 'Session detail: agent metric cards, top tool calls, and the subagent list',
    },
    faq: {
      title: 'FAQ',
      knowledgeQ: 'I clicked Knowledge Base and it says no route is configured.',
      knowledgeA:
        'Go to Settings → Knowledge Base Route, add an address, and make it the active one. It takes effect as soon as you save.',
      modelQ: 'No model is available in the list.',
      modelA:
        'Make sure one model is set as current, then check the API key and gateway address. For a private gateway, fill in the gateway address as well.',
      languageQ: 'How do I change the interface language?',
      languageA:
        'Open Settings → General → Interface language. The change applies immediately and is remembered on this machine.',
      addressQ: 'The page will not open, or I do not know the address.',
      addressA:
        'Use the address printed in the startup log: the source dev server defaults to http://localhost:4310, the distribution package to http://127.0.0.1:4300.',
    },
    footerHint: 'For installation, running from source, and packaging, see QUICKSTART.md and README.md in the repository root.',
  },

  /*
   * The sidebar "Knowledge Base" item is not a host route: it opens the address
   * configured in Settings in a new browser tab. With nothing configured there is
   * no page to open, so point the user at the setting instead of a blank module host.
   */
  knowledgeRoute: {
    missingTitle: 'No knowledge-base route configured',
    missingHint:
      'Go to Settings → Knowledge Base Route, add an address, and make it the active one.',
    loading: 'Loading knowledge base',
    loadFailedTitle: 'Could not read the knowledge-base route',
    loadFailedHint: '{reason}',
    openSettings: 'Open settings to add',
    frameTitle: 'Knowledge base: {name}',
  },

  recent: {
    heading: 'Recent',
    loading: 'Loading…',
    empty: 'No recent sessions',
    error: 'Could not load sessions',
    retry: 'Reload',
    untitled: 'New session',
    showMore: 'Show more ({count})',
    showLess: 'Show less',
    justNow: 'Just now',
    minutesAgo: '{count} min ago',
    hoursAgo: '{count} hr ago',
    daysAgo: '{count} d ago',
  },

  user: {
    openSettings: 'Open settings',
  },

  /*
   * The `experts.*` block (title / filters / search / usage count / empty and error
   * states) belonged to the framework's own experts page. D44 moved that page to
   * smart-factory's `/agents`, so the page and its copy are gone — the expert list UI
   * is the module's responsibility now. The sidebar label is `nav.experts`, not this.
   */

  workspace: {
    title: 'Workspace settings',
    close: 'Close workspace settings',
    current: 'Current workspace',
    none: 'No workspace selected',
    /** Accessible name for the sidebar entry: the visible text is the workspace name, which does not say what clicking it does. */
    open: 'Open workspace settings',
    openNamed: '{name} (open workspace settings)',
    createdNotActivated: 'The workspace was created, but switching to it failed: {reason}',
    listSection: 'All workspaces',
    create: 'New workspace',
    createTitle: 'New workspace',
    editTitle: 'Edit workspace',
    activeBadge: 'Active',
    switchTo: 'Switch to this workspace',
    unboundDirectory: 'No directory bound',
    followsGlobal: 'Follows global',
    deleteActiveNote: 'This is the active workspace; deleting it goes back to “no workspace selected”.',
    deleteDirectoryNote:
      'A directory created by the framework will be deleted together with its files; an externally bound directory is only unbound and is not deleted.',
    loading: 'Loading workspaces',
    empty: {
      title: 'No workspaces yet',
      hint: 'A workspace ties a default model and a default agent together. Use “New workspace” in the top right to add one.',
    },
    error: {
      title: 'Could not load the workspace list',
    },
    field: {
      name: 'Name',
      namePlaceholder: 'e.g. Weekly report helper',
      directory: 'Bound directory',
      directoryPlaceholder: '/home/me/projects/demo (optional)',
      directoryHint:
        'Leave it empty and the framework creates a folder named after the workspace under the data directory’s workspaces root. Enter an absolute path to bind only — nothing is created and the directory need not exist. Or click “Choose directory” to pick one in the system file manager; clicking an empty field also opens it.',
      directoryInvalid: 'Use an absolute path (starting with / or a drive letter such as D:\\)',
      /** Opens the OS folder picker (spawned by the server, on this machine). */
      directoryPick: 'Choose directory',
      /** While the native window is open — it may be behind the browser, so the button must say something. */
      directoryPicking: 'Waiting for selection…',
      defaultModel: 'Default model',
      defaultAgent: 'Default agent proxy',
      followGlobalHint: '“Follows global” means whatever is currently active in settings.',
    },
  },

  /** The "Workspace files" panel in the conversation area's right-hand column. */
  files: {
    expand: 'Open the workspace files panel',
    collapse: 'Collapse the workspace files panel',
    title: 'Workspace files',
    refresh: 'Refresh workspace files',
    /** One name for both states (the state itself is spoken via `aria-pressed`). */
    fullscreen: 'Show the workspace files panel full screen',
    resize: 'Resize the workspace files panel',
    toggleDirectory: '{name} (expand or collapse)',
    emptyDirectory: 'This directory is empty',
    truncatedEntries: 'Too many entries — showing the first {count}',
    truncatedFile: 'This file is large, so only the beginning is shown (full size {size})',
    notOpenable: 'This kind of entry cannot be previewed',
    noPreview: {
      title: 'No file selected',
      hint: 'Pick a file on the left and its contents will show up here.',
    },
    noWorkspace: {
      title: 'No workspace yet',
      hint: 'Create or pick one in workspace settings (bottom left) and its files will show up here.',
    },
    errorTitle: 'Could not read the workspace',
  },

  settings: {
    title: 'Settings',
    close: 'Close settings',
    nav: {
      general: 'General',
      model: 'Model',
      ragKnowledge: 'Knowledge Base Route',
      agentProxy: 'Agent proxy',
      observation: 'Observability',
    },
    general: {
      title: 'General',
      language: 'Language',
      languageHint: 'Applies immediately and is remembered on this machine.',
      dataSection: 'Data & storage',
      dataHome: 'Data directory',
      dataHomeHint:
        'Business data and secrets live in sqlite.db and .credentials.yaml under this directory. Set by the server’s COSIGHT_HOME environment variable.',
      version: 'Server version',
      aboutSection: 'About',
      about: 'Co-Sight Harness: one workbench that ties each module’s development, evaluation and optimisation together.',
    },
    /**
     * Actions and failure copy shared by all three list-style configuration panels.
     *
     * Kept in one place rather than repeated per resource: the delete warning must
     * read the same whether the user is deleting a workspace or a model, and so must
     * the failure sentences. Only the resource name differs, and callers interpolate
     * it into `{name}`.
     */
    form: {
      save: 'Save',
      saving: 'Saving…',
      cancel: 'Cancel',
      edit: 'Edit',
      delete: 'Delete',
      saveFailed: 'Could not save: {reason}',
      deleteFailed: 'Could not delete: {reason}',
      actionFailed: 'Action failed: {reason}',
      deleteConfirmTitle: 'Confirm deletion',
      deleteConfirmMessage: '“{name}” will be permanently deleted. This cannot be undone.',
      required: 'Enter {field}',
      invalidNumber: '{field} must be a number',
      invalidPositiveInteger: '{field} must be a positive whole number',
      invalidUrl: '{field} must start with http:// or https://',
      invalidUrlCredentials: 'Do not put a user name or password in {field}',
      discardTitle: 'Discard unsaved changes?',
      discardMessage: 'Your edits in this form have not been saved and will be lost.',
      discardConfirm: 'Discard',
    },

    model: {
      title: 'Model',
      listSection: 'Model configurations',
      activeBadge: 'Active',
      keyConfigured: 'Key configured',
      keyMissing: 'No key',
      activate: 'Make active',
      loading: 'Loading model configurations',
      empty: {
        title: 'No model configurations yet',
        hint: 'Use “Add model” in the top right. Only the one marked active is actually used.',
      },
      error: {
        title: 'Could not load model configurations',
      },
      create: 'Add model',
      createTitle: 'Add model',
      editTitle: 'Edit model',
      /**
       * Accessible names for the row actions.
       *
       * Every row has its own “Edit” and “Delete”; read aloud they are indistinguishable.
       * The visible word is kept verbatim inside the aria-label (WCAG 2.5.3) so voice
       * control users can still say the word they see on screen.
       */
      action: {
        ariaLabel: 'Actions for “{name}”',
        activate: 'Make “{name}” the active model',
        edit: 'Edit “{name}”',
        remove: 'Delete “{name}”',
        /** Accessible name for the clickable row title; must contain the visible model name (WCAG 2.5.3). */
        view: 'View details for “{name}”',
      },
      /** Appended to the delete confirmation when the active model is removed — nothing is switched over automatically, so the consequence has to be stated. */
      deleteActiveWarning: 'No model will be active afterwards.',
      /** Shown wherever a `null` baseUrl would be rendered. */
      baseUrlDefault: 'Uses the provider’s default endpoint',
      /** Read-only detail view (opened from a list row). */
      detail: {
        title: 'Model detail',
        back: 'Back to list',
        unset: 'Follows the default',
        unlimited: 'Unlimited',
        createdAt: 'Created',
        updatedAt: 'Updated',
        keyHint:
          'The plaintext key is never sent back to the browser. To replace it, use “Edit” and type a new one.',
      },
      /**
       * Module access card: how another local process reads model config from the
       * framework. Without it in the UI, module authors re-copy the key into their
       * own `.env` and the key ends up in a second place.
       */
      moduleAccess: {
        title: 'Module access: how other modules read model config',
        intro:
          'Another local module process (e.g. Smart Factory) can read model config through these endpoints — the list carries no key, while the by-id detail carries the plaintext key so the module can start a model client with it.',
        baseUrl: 'Endpoint base',
        tokenFile: 'Token file',
        tokenFileUnknown: 'Loading… (the path comes from the server’s actual data directory)',
        copy: 'Copy',
        copied: 'Copied',
        copyFailed: 'Copy failed — select it manually',
        copyAriaLabel: 'Copy {label}',
        scope:
          'These endpoints both read and write: creating, editing and deleting models all work. A module that only needs to read config to start a client should not call the write endpoints — with a leaked token the cost goes from "config was read" to "config was changed".',
        notEnv:
          'Let the module process read the token file itself instead of putting it in .env — modules pass their environment through to the model subprocess.',
        localOnly:
          'The endpoints only accept requests from the loopback address; browser pages cannot reach them.',
        curlHint: 'To verify, run this in a terminal:',
      },
      /** The contract's `max(64)`/`max(128)` limits, caught before the request goes out. */
      invalidLength: '{field} must be at most {max} characters',
      invalidRange: '{field} must be between {min} and {max}',
      field: {
        provider: 'Provider',
        providerHint: 'Only Anthropic is supported; other provider kinds are not available.',
        label: 'Name',
        labelPlaceholder: 'e.g. Internal Qwen3-32B',
        modelName: 'Model ID',
        modelNamePlaceholder: 'e.g. qwen3-32b',
        modelNameHint: 'The model field sent to the provider — not the display name you chose.',
        baseUrl: 'Custom gateway URL',
        baseUrlPlaceholder: 'https://gateway.internal/v1 (optional)',
        baseUrlHint: 'Leave empty to use the provider’s official endpoint.',
        apiKey: 'API key',
        apiKeySet: 'Already configured. The plaintext is never echoed back; leave empty to keep it.',
        apiKeyUnset: 'Not configured yet. Leave empty to leave it unset.',
        clearKey: 'Clear key',
        clearKeyPending: 'Will be cleared (click to undo)',
      },
      provider: {
        openai: 'OpenAI',
        anthropic: 'Anthropic',
        'azure-openai': 'Azure OpenAI',
        ollama: 'Ollama (local)',
        'openai-compatible': 'OpenAI compatible',
      },
      advanced: {
        title: 'Inference parameters',
        collapsedHint: 'Defaults work for most cases — expand to adjust',
        temperature: 'Temperature',
        temperatureHint: '0 is most deterministic, 2 is most random. Defaults to 0.7.',
        topP: 'Top P',
        topPHint: 'Adjust either this or temperature, not both. Defaults to 1.',
        maxOutputTokens: 'Max output tokens',
        maxOutputTokensHint: 'Leave empty for no limit.',
        contextWindow: 'Context window',
        contextWindowHint: 'Leave empty to follow the model’s own default.',
        timeoutSeconds: 'Timeout (seconds)',
        isActive: 'Make this the active model',
        isActiveHint:
          'Only one model is active globally at a time. When no model is active yet, a newly added model turns this on by default.',
      },
    },

    /**
     * Knowledge-base redirect targets. Unlike models and proxies this doubles as
     * module-facing configuration: modules read the active one through the read-only
     * module API, and the sidebar’s “Knowledge Base” item opens it in a new browser tab.
     */
    ragKnowledge: {
      title: 'Knowledge Base Route',
      listSection: 'Knowledge-base redirects',
      activeBadge: 'Active',
      activate: 'Make active',
      loading: 'Loading knowledge-base routes',
      empty: {
        title: 'No knowledge-base route yet',
        hint: 'Use “Add” in the top right. Only the one marked active is used for redirection.',
      },
      error: {
        title: 'Could not load knowledge-base routes',
      },
      create: 'Add',
      createTitle: 'Add knowledge-base route',
      editTitle: 'Edit knowledge-base route',
      /** Same reasoning as `settings.model.action.*`: row actions must identify their row. */
      action: {
        ariaLabel: 'Actions for “{name}”',
        activate: 'Make “{name}” the active knowledge base',
        edit: 'Edit “{name}”',
        remove: 'Delete “{name}”',
      },
      invalidLength: '{field} must be at most {max} characters',
      invalidRange: '{field} must be between {min} and {max}',
      /** Appended to the delete confirmation for the active one — nothing is promoted automatically. */
      deleteActiveWarning:
        'The sidebar “Knowledge Base” item will have nowhere to go afterwards, and modules cannot read a redirect address.',
      /** Shown in list rows; the password never appears here. */
      metaAccount: 'Account: {username}',
      field: {
        name: 'Name',
        namePlaceholder: 'e.g. Product knowledge base',
        routeUrl: 'Redirect URL',
        routeUrlPlaceholder: 'https://kb.internal/kb/42',
        routeUrlHint:
          'Must start with http:// or https://. Do not embed credentials in the URL — use the two fields below.',
        username: 'User name',
        usernamePlaceholder: 'e.g. admin',
        usernameHint: 'Account used to sign in to the knowledge base; leave empty if none is needed.',
        password: 'Password',
        passwordSet:
          'Already configured. The plaintext is never echoed back; leave empty to keep it.',
        passwordUnset: 'Not configured yet. Leave empty to leave it unset.',
        clearPassword: 'Clear password',
        clearPasswordPending: 'Will be cleared (click to undo)',
        apiKey: 'API key',
        apiKeySet:
          'Already configured. The plaintext is never echoed back; leave empty to keep it.',
        apiKeyUnset: 'Not configured yet. Leave empty to leave it unset.',
        apiKeyUnsetDefault: 'Not configured yet. Leave empty to use the server-side default key.',
        apiKeyHint:
          'Used by modules (such as Smart Factory) to call the knowledge service; maps to CO_KNOWLEDGE_API_KEY.',
        clearApiKey: 'Clear API key',
        clearApiKeyPending: 'Will be cleared (click to undo)',
        description: 'Description',
        descriptionPlaceholder: 'What this knowledge base covers (optional)',
        isActive: 'Make this the active knowledge base',
        isActiveHint: 'Only one knowledge base is active globally at a time.',
      },
    },

    agentProxy: {
      title: 'Agent proxy',
      currentSection: 'Current agent proxy',
      listSection: 'Proxy configurations',
      defaultBadge: 'Default',
      enabledBadge: 'Enabled',
      disabledBadge: 'Disabled',
      setDefault: 'Make default',
      loading: 'Loading agent proxy configurations',
      engine: {
        claudeAgentSdk: 'Claude Code',
        fake: 'Test engine',
      },
      engineUnavailable: {
        title: 'Claude Code CLI is not installed',
        hint: 'This distribution does not ship the CLI. Install it to run agents:',
      },
      empty: {
        title: 'No agent proxy configurations yet',
        hint: 'New entries come in through the API (POST /api/agent-proxies); this page views, edits, deletes and sets the default. The framework only stores and displays them; each module decides how to run its agent.',
      },
      error: {
        title: 'Could not load agent proxy configurations',
      },
      editTitle: 'Edit agent proxy',
      /** Same reasoning as `settings.model.action.*`: row actions must identify their row. */
      action: {
        ariaLabel: 'Actions for “{name}”',
        setDefault: 'Make “{name}” the default proxy',
        edit: 'Edit “{name}”',
        remove: 'Delete “{name}”',
      },
      /** Same reasoning as `settings.model.invalidLength`. */
      invalidLength: '{field} must be at most {max} characters',
      invalidRange: '{field} must be between {min} and {max}',
      /** Appended to the delete confirmation for the default proxy — nothing is switched over automatically. */
      deleteDefaultWarning: 'No proxy will be the default afterwards.',
      field: {
        engine: 'Engine',
        version: 'Version',
        name: 'Name',
        namePlaceholder: 'e.g. Default coding agent',
        description: 'Description',
        descriptionPlaceholder: 'What this proxy is for (optional)',
        agentType: 'Agent type',
        agentTypeHint:
          'Defined by the target module. The framework passes it through without enumerating values.',
        endpoint: 'Endpoint',
        endpointPlaceholder: 'https://agent.internal/run (optional)',
        endpointHint: 'Leave empty to let the module decide.',
        token: 'Access token',
        tokenSet: 'Already configured. The plaintext is never echoed back; leave empty to keep it.',
        tokenUnset: 'Not configured yet. Leave empty to leave it unset.',
        clearToken: 'Clear token',
        clearTokenPending: 'Will be cleared (click to undo)',
      },
      runtime: {
        title: 'Runtime & limits',
        maxIterations: 'Max iterations',
        maxIterationsHint: 'How many steps one run may take. Defaults to 50.',
        parallelism: 'Parallelism',
        parallelismHint: 'How many branches run at once. Defaults to 4.',
        timeoutSeconds: 'Timeout (seconds)',
        timeoutSecondsHint: 'Wall-clock limit for one run. Defaults to 600.',
      },
      switches: {
        title: 'Capability switches',
        enabled: 'Enabled',
        enabledHint:
          'When disabled the framework stops handing it to modules, but keeps the configuration.',
        isDefault: 'Make this the default proxy',
        isDefaultHint: 'Only one proxy is the default globally at a time.',
        memoryEnabled: 'Enable memory',
        condensationEnabled: 'Enable context condensation',
        securityAnalyzer: 'Security analyzer',
        securityAnalyzerHint: 'How tool calls are screened for safety.',
      },
      analyzer: {
        none: 'No screening',
        invariant: 'Invariant checks',
        llm: 'LLM screening',
      },
      extra: {
        title: 'Module-private configuration',
        hint: 'Modules read and write these fields themselves. The framework does not interpret them, so they are shown read-only here.',
      },
    },

    observation: {
      title: 'Session Cleanup',
      description: 'Set time thresholds for automatic session abandonment and cleanup.',
      checking: 'Checking observability service…',
      serviceUnavailable: 'Observability service unavailable',
      serviceUnavailableHint: 'Cannot connect to the session observability service (cosight-viewer). Please start the service before configuring.',
      retry: 'Retry',
      loadFailed: 'Failed to load configuration',
      saveSuccess: '✓ Configuration saved',
      saveFailed: 'Failed to save configuration',
      abandonHours: 'Abandon hours',
      abandonHoursHint: 'Sessions inactive for more than specified hours are automatically marked as abandoned',
      purgeDays: 'Purge days',
      purgeDaysHint: 'Automatically clean up completed, errored, and abandoned sessions older than specified days',
      autoCleanup: 'Enable auto-cleanup',
      autoCleanupHint: 'Automatically clean up old sessions every 24 hours',
      lastRun: 'Last cleanup',
      lastRunAuto: 'Automatic',
      lastRunManual: 'Manual',
      lastRunDetail: 'Cleaned up {sessions} sessions, {events} events, {agents} agents',
    },
  },

  module: {
    loading: 'Loading module…',
    missing: {
      title: 'Module not connected',
      hint: 'This page is served by a separate module. Drop its module.json into modules/ under the data directory to mount it.',
    },
    error: {
      title: 'Module failed to load',
      hint: 'The module service may not be running, or its manifest entry is unreachable.',
    },
    frameTitle: '{name} module',
  },

  error: {
    title: 'Something went wrong',
    retry: 'Retry',
    notFound: {
      title: 'Page not found',
      hint: 'The address may be wrong, or this page is not part of this version.',
      back: 'Back to home',
    },
    internal: 'Internal server error',
    bad_request: {
      default: 'Malformed request',
      workspace_not_a_directory: 'That path is not a directory, so it has no contents to list',
      workspace_not_a_file: 'That path is not a regular file, so it has no contents to read',
    },
    not_found: {
      /** Group-level fallback (see translate.ts): a resource type with no entry yet. */
      default: 'Not found',
      route: 'Endpoint not found',
      workspace: 'Workspace not found',
      expert: 'Expert not found',
      model: 'Model configuration not found',
      agent_proxy: 'Agent proxy configuration not found',
      workspace_directory: 'The directory this workspace points at is gone',
      workspace_file: 'No such file in the workspace',
    },
    conflict: {
      default: 'The operation conflicts with existing data — check and try again',
      workspace: 'A workspace with that name already exists',
    },
    validation_failed: 'Request validation failed',
    payload_too_large: {
      default: 'Request body too large',
      workspace_image: 'That image is over the preview limit (2 MiB)',
    },
    unsupported_media_type: {
      default: 'Unsupported content type',
      workspace_file: 'That file is not text or an image we can preview',
    },
    rate_limited: 'Too many requests, please try again later',
    /*
     * A group with a `default` leaf rather than a plain string: the module face
     * answers `error.unauthorized.module_token`, and without a group the key would
     * be truncated to `error.unauthorized` — reporting a rejected token as an
     * expired session, which re-entering the session would not fix.
     */
    unauthorized: {
      default: 'Session expired, please re-enter',
      module_token:
        'Module token missing or invalid (a module should read .module-token from the data directory)',
    },
    /*
     * Same reasoning as the `unauthorized` group above: the file-browsing keys need
     * somewhere to land, or `error.forbidden.workspace_file` gets truncated to
     * `error.forbidden` and an out-of-workspace path reads as an account-permission
     * problem.
     */
    forbidden: {
      default: 'You are not allowed to perform this action',
      workspace_file: 'That path is outside the workspace, so it was refused',
      loopback_only: 'Workspace file browsing is local-only — open the app on this machine',
      /** The picker opens a window on the desktop, so it is loopback-only too. */
      directory_picker: 'Directory picking is local-only — open the app on this machine',
    },
    not_implemented: {
      default: 'Not implemented yet',
      model_probe: 'Model connectivity probe is not implemented yet',
    },
    /**
     * The three ways the OS folder picker can fail. They span 501 and 500, hence a group
     * named after the feature: the generic defaults there do not tell the user to type
     * the path instead, which is the only thing they can do.
     */
    directory_picker: {
      default: 'Could not open the system folder picker — type the path instead',
      unavailable:
        'This machine cannot open a folder picker (no graphical session or dialog tool) — type the path instead',
      failed: 'The folder picker exited unexpectedly — type the path instead',
      timeout: 'The folder picker waited too long and timed out — type the path instead',
    },
    upstream_unavailable: 'An upstream dependency is unavailable',
    network: 'Cannot reach the server — make sure the backend is running',
  },
};
