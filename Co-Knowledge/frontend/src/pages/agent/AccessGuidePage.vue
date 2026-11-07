<template>
  <div class="access-guide">
    <section class="protocol-section" aria-labelledby="protocol-heading">
      <h2 id="protocol-heading" class="text-section-title">{{ $t('modules.remoteAccess.selectProtocol') }}</h2>
      <div class="protocol-options" role="group" :aria-label="$t('modules.remoteAccess.selectProtocol')">
        <button
          v-for="protocol in protocols"
          :key="protocol.id"
          type="button"
          :class="['protocol-option', { selected: tab === protocol.id }]"
          :aria-pressed="tab === protocol.id"
          @click="tab = protocol.id"
        >
          <span class="protocol-icon"><component :is="protocol.icon" /></span>
          <span class="protocol-copy">
            <strong class="text-body">{{ protocol.title }}</strong>
            <span class="text-secondary">{{ protocol.description }}</span>
          </span>
          <Check v-if="tab === protocol.id" class="protocol-check" />
        </button>
      </div>
    </section>

    <section class="setup-card" aria-labelledby="setup-heading">
      <div class="setup-heading">
        <h2 id="setup-heading" class="text-section-title">
          {{ tab === 'mcp' ? $t('modules.remoteAccess.setupMcpTitle') : $t('modules.remoteAccess.setupRestTitle') }}
        </h2>
        <span class="text-caption setup-meta">
          {{ tab === 'mcp' ? $t('modules.remoteAccess.setupMcpMeta') : $t('modules.remoteAccess.setupRestMeta') }}
        </span>
      </div>
      <ol class="setup-steps">
        <li class="setup-step">
          <span class="step-number text-secondary" aria-hidden="true">1</span>
          <div class="step-content">
            <h3 class="text-body text-label">
              {{ tab === 'mcp' ? $t('modules.remoteAccess.stepCopyMcpAddress') : $t('modules.remoteAccess.stepCopyRestAddress') }}
            </h3>
            <p class="step-description text-secondary">
              {{ tab === 'mcp' ? $t('modules.remoteAccess.stepCopyMcpDesc') : $t('modules.remoteAccess.stepCopyRestDesc') }}
            </p>
            <div class="endpoint-field">
              <code class="text-code text-secondary">{{ activeEndpoint }}</code>
              <el-button
                class="button-compact"
                :aria-label="$t('modules.remoteAccess.copy')"
                @click="copyHandle(activeEndpoint)"
              >
                <CopyDocument />{{ $t('modules.remoteAccess.copy') }}
              </el-button>
            </div>
          </div>
        </li>

        <li class="setup-step">
          <span class="step-number text-secondary" aria-hidden="true">2</span>
          <div class="step-content">
            <div class="step-heading">
              <h3 class="text-body text-label">{{ $t('modules.remoteAccess.stepAuthTitle') }}</h3>
              <RouterLink to="/keys" class="inline-link text-secondary">
                {{ $t('modules.remoteAccess.manageKeys') }}<ArrowRight />
              </RouterLink>
            </div>
            <i18n-t keypath="modules.remoteAccess.stepAuthDesc" tag="p" class="step-description text-secondary">
              <template #code>
                <code class="text-code">&lt;YOUR_API_KEY&gt;</code>
              </template>
            </i18n-t>
            <code class="auth-header text-code text-secondary">Authorization: Bearer &lt;YOUR_API_KEY&gt;</code>
            <p class="step-note text-caption">{{ authNote }}</p>
          </div>
        </li>

        <li class="setup-step">
          <span class="step-number text-secondary" aria-hidden="true">3</span>
          <div class="step-content">
            <h3 class="text-body text-label">
              {{ tab === 'mcp' ? $t('modules.remoteAccess.stepClientTitle') : $t('modules.remoteAccess.stepRequestTitle') }}
            </h3>
            <p class="step-description text-secondary">
              {{ tab === 'mcp' ? $t('modules.remoteAccess.stepClientDesc') : $t('modules.remoteAccess.stepRequestDesc') }}
            </p>
            <details class="example-disclosure">
              <summary class="example-trigger text-secondary">
                {{ tab === 'mcp' ? $t('modules.remoteAccess.viewConfigExample') : $t('modules.remoteAccess.viewRequestExample') }}
                <ArrowDown class="details-chevron" />
              </summary>
              <div class="example-panel">
                <el-tabs v-if="tab === 'mcp'" v-model="client" :aria-label="$t('modules.remoteAccess.mcpConfigFormat')">
                  <el-tab-pane :label="$t('modules.remoteAccess.mcpCliTab')" name="cli" />
                  <el-tab-pane :label="$t('modules.remoteAccess.mcpJsonTab')" name="json" />
                </el-tabs>
                <div class="example-toolbar">
                  <span class="text-caption">{{ exampleLabel }}</span>
                  <el-button class="button-compact" :aria-label="$t('modules.remoteAccess.copyExample')" @click="copyHandle(activeExample)">
                    <CopyDocument />{{ $t('modules.remoteAccess.copy') }}
                  </el-button>
                </div>
                <pre class="code">{{ activeExample }}</pre>
              </div>
            </details>
          </div>
        </li>
      </ol>
    </section>

    <div class="reference-sections">
      <details class="reference-section">
        <summary>
          <span class="reference-copy">
            <span class="text-body text-label">
              {{ tab === 'mcp' ? $t('modules.remoteAccess.toolsTitle') : $t('modules.remoteAccess.routesTitle') }}
            </span>
            <span class="text-secondary">
              {{ tab === 'mcp' ? $t('modules.remoteAccess.toolsDesc') : $t('modules.remoteAccess.routesDesc') }}
            </span>
          </span>
          <span class="reference-count text-caption">{{ $t('modules.remoteAccess.referenceCount', { count: activeReferenceCount }) }}</span>
          <ArrowDown class="details-chevron" />
        </summary>
        <div class="reference-content">
          <div class="reference-refresh-toolbar">
            <TableRefreshButton :key="tab" :label="tab === 'mcp' ? $t('modules.remoteAccess.refreshMcp') : $t('modules.remoteAccess.refreshRest')" :refresh="refreshReferences" compact />
          </div>
          <div class="table-card">
            <table v-if="tab === 'mcp'" :key="'mcp-' + referenceRevision" class="list-table reference-table">
              <thead>
                <tr>
                  <th scope="col">{{ $t('modules.remoteAccess.colTool') }}</th>
                  <th scope="col">{{ $t('modules.remoteAccess.colPermission') }}</th>
                  <th scope="col">{{ $t('modules.remoteAccess.colPurpose') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="tool in tools" :key="tool.name">
                  <td><code class="text-code">{{ tool.name }}</code></td>
                  <td><code class="text-code">{{ tool.permission }}</code></td>
                  <td>{{ tool.description }}</td>
                </tr>
              </tbody>
            </table>
            <table v-else :key="'rest-' + referenceRevision" class="list-table reference-table">
              <thead>
                <tr>
                  <th scope="col">{{ $t('modules.remoteAccess.colMethod') }}</th>
                  <th scope="col">{{ $t('modules.remoteAccess.colPath') }}</th>
                  <th scope="col">{{ $t('modules.remoteAccess.colPurpose') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="route in routes" :key="route.method + ' ' + route.path">
                  <td>
                    <span :class="['tag-soft', route.method === 'GET' ? 'green' : 'blue']">
                      {{ route.method }}
                    </span>
                  </td>
                  <td><code class="text-code">{{ route.path }}</code></td>
                  <td>{{ route.description }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </details>

      <details class="reference-section">
        <summary>
          <span class="reference-copy">
            <span class="text-body text-label">{{ $t('modules.remoteAccess.serviceConfigTitle') }}</span>
            <span class="text-secondary">{{ $t('modules.remoteAccess.serviceConfigDesc') }}</span>
          </span>
          <ArrowDown class="details-chevron" />
        </summary>
        <div class="reference-content configuration-content">
          <p class="configuration-note text-secondary">{{ $t('modules.remoteAccess.serviceConfigNote') }}</p>
          <dl class="configuration-list text-secondary">
            <div v-for="item in serviceStatuses" :key="item.label">
              <dt>{{ item.label }}</dt>
              <dd>{{ item.value }}</dd>
            </div>
            <div>
              <dt>{{ $t('modules.remoteAccess.statusAuth') }}</dt>
              <dd><code class="text-code">AUTH_MODE={{ authMode }}</code></dd>
            </div>
          </dl>
          <p class="configuration-note text-secondary">{{ $t('modules.remoteAccess.serviceAuthNote') }}</p>
          <p class="configuration-note text-secondary">{{ $t('modules.remoteAccess.serviceGatewayNote') }}</p>
        </div>
      </details>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowRight, Check, Connection, CopyDocument, Link } from '@element-plus/icons-vue'
import { AGENT_BASE, AGENT_MCP_PATH } from '@/shared/api/endpoints'
import {
  absoluteUrl,
  buildClaudeCommand,
  buildMcpJson,
  buildSearchCurl
} from '@/features/agent/lib/helpers'
import { copyText } from '@/shared/lib/clipboard'
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  status: {
    type: Object,
    default: null
  }
})

defineEmits(['go-keys'])

const { t } = useI18n()

/** 当前接入方式：MCP / REST（协议选择卡）。 */
const tab = ref<'mcp' | 'rest'>('mcp')
/** MCP 配置格式：CLI / JSON（一次只展示一种）。 */
const client = ref<'cli' | 'json'>('cli')
const referenceRevision = ref(0)

/** 0.1.7：参考表是站点内置内容，刷新只重渲染一次（不请求接口）。 */
function refreshReferences (): void {
  referenceRevision.value += 1
}

const restBaseUrl = computed(() => absoluteUrl(
  (props.status && props.status.restBasePath) || AGENT_BASE
))
const mcpUrl = computed(() => absoluteUrl(
  (props.status && props.status.mcpPath) || AGENT_MCP_PATH
))
const authMode = computed(() => (props.status && props.status.authMode) || 'none')
/**
 * 鉴权提示必须跟 AUTH_MODE 走：
 * - none：未启用应用层鉴权；
 * - gateway：由前置网关校验；
 * - local：本地账号登录已启用，但 Agent 接口仍要访问密钥。
 * 之前只分 gateway / 其它，local 被误显示成「未启用应用层鉴权」。
 */
const authNote = computed(() => {
  if (authMode.value === 'gateway') {
    return t('modules.remoteAccess.stepAuthGatewayNote')
  }
  if (authMode.value === 'local') {
    return t('modules.remoteAccess.stepAuthLocalNote')
  }
  return t('modules.remoteAccess.stepAuthOpenNote')
})

const protocols = computed(() => ([
  { id: 'mcp', title: 'MCP', description: t('modules.remoteAccess.protocolMcpDesc'), icon: Connection },
  { id: 'rest', title: 'REST API', description: t('modules.remoteAccess.protocolRestDesc'), icon: Link }
]))

const tools = computed(() => ([
  { name: 'list_knowledge_bases', permission: 'kb:list', description: t('modules.remoteAccess.toolListPurpose') },
  { name: 'search_knowledge', permission: 'kb:search', description: t('modules.remoteAccess.toolSearchPurpose') },
  { name: 'ask_knowledge_base', permission: 'kb:answer', description: t('modules.remoteAccess.toolAnswerPurpose') },
  { name: 'list_workflows', permission: 'workflow:read', description: t('modules.remoteAccess.toolListWorkflowsPurpose') },
  { name: 'run_workflow', permission: 'workflow:run', description: t('modules.remoteAccess.toolRunWorkflowPurpose') }
]))

const routes = computed(() => ([
  { method: 'GET', path: '/knowledge-bases', description: t('modules.remoteAccess.endpointListPurpose') },
  { method: 'GET', path: '/knowledge-bases/{kb_id}', description: t('modules.remoteAccess.endpointGetPurpose') },
  { method: 'POST', path: '/search', description: t('modules.remoteAccess.endpointSearchPurpose') },
  { method: 'POST', path: '/answer', description: t('modules.remoteAccess.endpointAnswerPurpose') },
  { method: 'GET', path: '/workflows', description: t('modules.remoteAccess.endpointListWorkflowsPurpose') },
  { method: 'POST', path: '/query', description: t('modules.remoteAccess.endpointQueryPurpose') },
  { method: 'GET', path: '/openapi.json', description: t('modules.remoteAccess.endpointOpenapiPurpose') }
]))

/**
 * 服务状态：只展示接口真实返回的开关，不做「健康度」推断。
 * 拿不到 status（接口失败）时全部显示未获取，而不是假装已启用。
 */
const serviceStatuses = computed(() => {
  const status = props.status
  const loading = !status
  return [
    {
      label: t('modules.remoteAccess.statusApi'),
      value: loading
        ? t('modules.remoteAccess.statusLoading')
        : (status.apiEnabled ? t('modules.remoteAccess.enabled') : t('modules.remoteAccess.disabled')),
      tone: loading ? 'muted' : (status.apiEnabled ? 'success' : 'danger')
    },
    {
      label: 'REST / MCP',
      value: loading
        ? t('modules.remoteAccess.statusLoading')
        : `${status.restEnabled ? t('modules.remoteAccess.enabled') : t('modules.remoteAccess.disabled')} / ${status.mcpEnabled ? t('modules.remoteAccess.enabled') : t('modules.remoteAccess.disabled')}`,
      tone: loading ? 'muted' : (status.restEnabled || status.mcpEnabled ? 'success' : 'warning')
    },
    {
      label: t('modules.remoteAccess.statusPepper'),
      value: loading
        ? t('modules.remoteAccess.statusLoading')
        : (status.pepperConfigured ? t('modules.remoteAccess.configured') : t('modules.remoteAccess.notConfigured')),
      tone: loading ? 'muted' : (status.pepperConfigured ? 'success' : 'warning')
    },
    {
      label: t('modules.remoteAccess.statusKeys'),
      value: loading
        ? t('modules.remoteAccess.statusLoading')
        : (status.keyStoreAvailable ? t('modules.remoteAccess.available') : t('modules.remoteAccess.unavailable')),
      tone: loading ? 'muted' : (status.keyStoreAvailable ? 'success' : 'danger')
    }
  ]
})

const activeEndpoint = computed(() => (tab.value === 'mcp' ? mcpUrl.value : restBaseUrl.value))
const cli = computed(() => buildClaudeCommand(mcpUrl.value))
const mcpConfig = computed(() => buildMcpJson(mcpUrl.value))
const restExample = computed(() => buildSearchCurl(restBaseUrl.value))
const activeExample = computed(() => (
  tab.value === 'rest' ? restExample.value : client.value === 'cli' ? cli.value : mcpConfig.value
))
const exampleLabel = computed(() => {
  if (tab.value === 'rest') {
    return t('modules.remoteAccess.exampleRestLabel')
  }
  return client.value === 'cli'
    ? t('modules.remoteAccess.exampleCliLabel')
    : t('modules.remoteAccess.exampleJsonLabel')
})
const activeReferenceCount = computed(() => (
  tab.value === 'mcp' ? tools.value.length : routes.value.length
))

async function copyHandle (text: string) {
  const ok = await copyText(text)
  if (ok) {
    ElMessage.success(t('modules.remoteAccess.copied'))
  } else {
    ElMessage.error(t('modules.remoteAccess.copyFailed'))
  }
}
</script>

<style scoped>
.protocol-section { margin-bottom: 28px; }
.protocol-section h2 { margin: 0 0 16px; }
.protocol-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.protocol-option { display: flex; align-items: center; gap: 14px; position: relative; text-align: left; padding: 20px; border: 1px solid var(--rs-border); border-radius: var(--rs-radius); background: var(--rs-bg-card); color: var(--rs-text); }
.protocol-option:hover { border-color: var(--rs-primary-border); }
.protocol-option.selected { border-color: var(--rs-primary); background: var(--rs-bg-selected); }
.protocol-icon { width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; background: var(--rs-bg-soft); color: var(--rs-text-2); }
.selected .protocol-icon { background: var(--rs-bg-selected); color: var(--rs-primary); }
.protocol-icon svg { width: 22px; height: 22px; }
.protocol-copy { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.protocol-copy > span { color: var(--rs-text-2); }
.protocol-check { width: 18px; height: 18px; color: var(--rs-primary); margin-left: auto; }
.setup-card { background: var(--rs-bg-card); border: 1px solid var(--rs-border); border-radius: var(--rs-radius); padding: 28px 32px; }
.setup-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding-bottom: 24px; border-bottom: 1px solid var(--rs-border-soft); }
.setup-heading h2 { margin: 0; }
.setup-meta { color: var(--rs-text-3); }
.setup-steps { list-style: none; margin: 0; padding: 0; }
.setup-step { display: flex; gap: 16px; padding: 28px 0; }
.setup-step + .setup-step { border-top: 1px solid var(--rs-border-soft); }
.setup-step:last-child { padding-bottom: 0; }
.step-number { display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; border: 1px solid var(--rs-border); border-radius: 50%; flex-shrink: 0; color: var(--rs-text-2); background: var(--rs-bg-soft); }
.step-content { flex: 1; min-width: 0; padding-top: 3px; }
.step-content h3 { margin: 0; }
.step-description { margin: 6px 0 14px; color: var(--rs-text-2); }
.step-description code { overflow-wrap: anywhere; }
.endpoint-field { display: flex; align-items: center; gap: 16px; background: var(--rs-bg-soft); border: 1px solid var(--rs-border); border-radius: 6px; padding: 12px 14px; }
.endpoint-field code { flex: 1; min-width: 0; overflow-wrap: anywhere; color: var(--rs-text); }
.endpoint-field .el-button { flex-shrink: 0; }
.step-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.inline-link { display: inline-flex; align-items: center; gap: 4px; }
.inline-link svg { width: 12px; height: 12px; }
.auth-header { display: block; overflow-wrap: anywhere; color: var(--rs-text); }
.step-note { margin: 10px 0 0; color: var(--rs-text-3); }
.example-disclosure > summary { display: inline-flex; align-items: center; gap: 8px; color: var(--rs-primary); padding: 4px 0; }
summary { cursor: pointer; list-style: none; }
summary::-webkit-details-marker { display: none; }
summary:focus-visible { outline: 2px solid #8abaff; outline-offset: 4px; border-radius: 4px; }
.details-chevron { width: 14px; height: 14px; flex-shrink: 0; transition: transform .15s; }
details[open] > summary .details-chevron { transform: rotate(180deg); }
.example-panel { margin-top: 16px; min-width: 0; }
.example-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 14px 0 10px; color: var(--rs-text-2); }
.example-panel .code { border: 1px solid var(--rs-border-soft); }
.reference-sections { margin-top: 28px; }
.reference-section { border-bottom: 1px solid var(--rs-border); }
.reference-section > summary { display: flex; align-items: center; gap: 16px; padding: 22px 0; }
.reference-copy { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0; }
.reference-copy > span:last-child, .reference-count, .reference-section > summary > .details-chevron { color: var(--rs-text-3); }
.reference-content { padding: 0 0 24px; }
.reference-refresh-toolbar { display: flex; justify-content: flex-end; margin-bottom: 12px; }
.reference-table { min-width: 620px; }
.configuration-content { max-width: 800px; }
.configuration-list { margin: 20px 0; border-top: 1px solid var(--rs-border-soft); }
.configuration-list > div { display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: 16px; padding: 12px 0; border-bottom: 1px solid var(--rs-border-soft); }
.configuration-list dt { color: var(--rs-text-2); }
.configuration-list dd { margin: 0; overflow-wrap: anywhere; }
.configuration-note { color: var(--rs-text-2); margin: 0 0 12px; }
.configuration-note code { overflow-wrap: anywhere; }
@media (max-width: 800px) {
  .protocol-options { gap: 12px; }
  .protocol-option { padding: 16px; gap: 12px; }
  .setup-card { padding: 24px 20px; }
  .setup-step { gap: 12px; padding: 24px 0; }
  .endpoint-field { gap: 10px; }
  .setup-meta { width: 100%; }
}
@media (max-width: 700px) {
  .protocol-options { grid-template-columns: 1fr; }
  .protocol-option { padding: 14px 16px; }
  .setup-card { padding: 20px 16px; }
  .setup-step { gap: 10px; }
  .step-number { width: 24px; height: 24px; }
  .endpoint-field { align-items: flex-start; flex-wrap: wrap; }
  .endpoint-field code { flex-basis: 100%; }
  .configuration-list > div { grid-template-columns: 100px minmax(0, 1fr); }
}
</style>
