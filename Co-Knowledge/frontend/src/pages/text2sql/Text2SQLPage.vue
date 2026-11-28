<template>
  <AppPage class="management-page text2sql-page text-body">
    <div class="page-inner">
      <PageHeader title="Text2SQL" subtitle="用自然语言提问，让业务数据给出答案。" :icon="Coin">
        <template #actions>
          <el-button link :loading="loading" :disabled="busy" @click="loadAll"><Refresh/>刷新</el-button>
        </template>
      </PageHeader>

      <div class="t2s-nav" role="navigation" aria-label="Text2SQL 工作区">
        <button
          v-for="item in workspaceTabs"
          :key="item.id"
          class="text-body"
          :class="{ active: workspace === item.id }"
          :aria-current="workspace === item.id ? 'page' : undefined"
          :disabled="busy"
          @click="switchWorkspace(item.id)"
        >
          <component :is="item.icon"/>{{ item.label }}
          <span v-if="item.id === 'sources'" class="text-secondary">{{ sources.length }}</span>
          <span v-if="item.id === 'history' && history.length" class="text-secondary">{{ history.length }}</span>
        </button>
      </div>

      <el-alert
        v-if="saveState === 'error'"
        class="t2s-storage-warning"
        title="草稿保存失败，当前仍可继续使用。请检查网络连接或稍后重试。"
        type="warning"
        show-icon
        :closable="false"
      />

      <div v-show="workspace === 'query'" class="t2s-workspace">
        <section class="t2s-panel t2s-query-panel" aria-label="自然语言查询">
          <div class="t2s-query-body">
            <div class="toolbar t2s-source-bar">
              <el-select v-model="sourceId" class="t2s-source-picker" aria-label="选择分析主题" :disabled="busy" @change="selectSource">
                <template #prefix><Coin/></template>
                <el-option v-for="item in sources" :key="item.id" :label="topicDetails(item).name + (item.enabled === false ? '（已停用）' : '')" :value="item.id"/>
              </el-select>
              <span class="text-secondary">{{ versionStateText }}</span>
              <el-popover v-model:visible="sourceDetailsOpen" trigger="click" placement="bottom-start" :width="280" popper-class="t2s-source-popover">
                <template #reference><el-button link :disabled="busy">数据源详情</el-button></template>
                <div class="t2s-source-details">
                  <strong class="text-body text-label">{{ source?.name || '尚未选择数据源' }}</strong>
                  <p class="text-secondary">{{ sourceDescription }}</p>
                  <p class="text-caption muted">{{ statusText }} · {{ selectedTableCount }} 张可查询表 · 只读查询</p>
                  <p class="text-caption muted">{{ versionStateText }} · 维护人：{{ sourceOwner }}</p>
                  <el-button v-if="source" link type="primary" :disabled="busy" @click="manageCurrentSource">管理数据源<Right/></el-button>
                </div>
              </el-popover>
            </div>
            <div class="t2s-question-heading">
              <h2 class="text-section-title"><ChatLineSquare aria-hidden="true"/><label for="text2sql-question">你想了解什么？</label></h2>
              <el-button v-if="question || response || activeIssue" link type="primary" :disabled="busy" @click="newQuery">新建查询</el-button>
            </div>
            <el-input
              id="text2sql-question"
              v-model="question"
              type="textarea"
              aria-label="自然语言问题"
              :autosize="{ minRows: 2, maxRows: 6 }"
              maxlength="1000"
              resize="none"
              :disabled="running"
              placeholder="例如：查询最近30天每个城市的支付订单金额"
              @keydown.ctrl.enter.prevent="run()"
              @keydown.meta.enter.prevent="run()"
            />
            <div class="t2s-composer-footer">
              <div v-if="!response && topicExamples.length" class="t2s-topic-questions" role="group" aria-label="推荐业务问题">
                <el-button v-for="item in topicExamples" :key="item.id" class="button-compact" :disabled="busy" @click="selectExample(item)">{{ item.title }}</el-button>
                <el-button link :disabled="busy" @click="examplesOpen = true">更多示例</el-button>
              </div>
              <div class="t2s-composer-actions">
                <div class="t2s-composer-tools" role="group" aria-label="查询选项">
                  <el-button v-if="response || !topicExamples.length" link :disabled="busy" @click="examplesOpen = true">示例问题</el-button>
                  <el-button link :disabled="busy" @click="workspace = 'history'; libraryView = 'favorites'">常用查询</el-button>
                  <el-button :disabled="busy" @click="optionsOpen = true">调整条件</el-button>
                </div>
                <div class="t2s-run-actions">
                  <span class="t2s-shortcut text-caption muted">Ctrl / ⌘ + Enter</span>
                  <el-button type="primary" :disabled="runDisabled" @click="run()">
                    <Loading v-if="running" class="is-loading"/><VideoPlay v-else/>{{ running ? '正在查询…' : '开始查询' }}
                  </el-button>
                </div>
              </div>
            </div>
            <div v-if="!sourceReady" class="t2s-index-warning text-body">
              <Warning/>
              <span>{{ sourceWarning }}</span>
              <el-button v-if="source?.status === 'scanned' && source?.enabled !== false" link type="primary" @click="openQuality(source)">验证与发布<Right/></el-button>
              <el-button v-else link type="primary" @click="workspace = 'sources'; openSource(source)">查看数据状态<Right/></el-button>
            </div>
            <p v-if="datePolicyNote" class="t2s-draft-note text-caption muted">{{ datePolicyNote }}</p>
          </div>
        </section>

        <section ref="outputPanel" class="t2s-panel t2s-output-panel" aria-label="查询输出" :aria-busy="running">
          <div v-if="waitingForQuery" class="t2s-panel-heading">
            <h2 class="text-section-title">查询工作区</h2>
          </div>
          <div v-if="response || running || waitingForQuery" class="t2s-output-controls">
            <el-tabs v-model="activeTab" class="t2s-tabs">
              <el-tab-pane label="结果" name="result"/>
              <el-tab-pane label="答案依据" name="explanation" :disabled="!response"/>
              <el-tab-pane label="SQL" name="sql" :disabled="!response"/>
              <template v-if="response && showTechnical">
                <el-tab-pane label="执行计划" name="plan"/>
                <el-tab-pane label="Debug" name="debug"/>
              </template>
            </el-tabs>
            <el-dropdown v-if="response || running" class="t2s-output-menu" trigger="click" placement="bottom-end" @command="handleResultAction">
              <el-button link aria-label="更多查询操作">
                <span class="t2s-output-menu-label">更多</span><ArrowDown class="t2s-output-menu-label"/><MoreFilled class="t2s-output-menu-icon"/>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <template v-if="response?.result">
                    <el-dropdown-item command="csv">导出查询结果 CSV</el-dropdown-item>
                    <el-dropdown-item command="json">导出查询结果 JSON</el-dropdown-item>
                    <el-dropdown-item command="save" :disabled="busy">保存常用查询</el-dropdown-item>
                    <el-dropdown-item command="conditions" :disabled="busy">调整条件重新查询</el-dropdown-item>
                  </template>
                  <el-dropdown-item command="details" :divided="!!response?.result">{{ showTechnical ? '收起运行详情' : '运行详情' }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div v-if="waitingForQuery" class="t2s-small-empty">
            <Histogram aria-hidden="true"/>
            <h3 class="text-section-title">选择问题，开始分析</h3>
            <p class="text-secondary">查询结果会显示在这里。</p>
          </div>

          <div v-if="activeIssue && !running" class="t2s-issue" :class="activeIssue.tone" role="alert">
            <InfoFilled/>
            <div>
              <strong class="text-body text-label">{{ activeIssue.title }}</strong>
              <p class="text-secondary">{{ response?.error?.message }}</p>
              <p class="text-caption muted">{{ activeIssue.hint }}<span v-if="response?.result"> 下方保留的结果来自“{{ response.question }}”。</span></p>
              <div class="t2s-inline-actions">
                <el-button :disabled="busy" @click="recoverIssue">{{ activeIssue.label }}</el-button>
                <el-button link @click="showTechnical = true; activeTab = 'debug'">查看本次运行详情</el-button>
              </div>
            </div>
          </div>

          <div v-if="response?.result && response.datasource_id !== sourceId" class="t2s-context-strip text-caption">
            <Warning/>当前展示历史数据源的结果；新问题会使用上方选中的数据源。
          </div>

          <section
            v-if="running || flowStages.length"
            class="t2s-flow"
            :class="{
              'is-running': running,
              'is-open': running || flowExpanded,
              'is-failed': !!flowFailure,
              'has-overlay': running && !!response?.result
            }"
          >
            <button
              type="button"
              class="t2s-flow-head"
              :aria-expanded="running || flowExpanded ? 'true' : 'false'"
              :aria-disabled="running ? 'true' : undefined"
              aria-controls="t2s-flow-body"
              @click="toggleFlow"
            >
              <span class="t2s-flow-icon" aria-hidden="true">
                <Loading v-if="running" class="is-loading"/>
                <CircleCloseFilled v-else-if="flowFailure"/>
                <CircleCheckFilled v-else/>
              </span>
              <span class="t2s-flow-title">
                <strong class="t2s-flow-name">查询流程</strong><span class="t2s-flow-sep" aria-hidden="true">·</span><span class="t2s-flow-summary">{{ flowHeadline }}</span>
              </span>
              <span class="t2s-flow-meta">
                <span v-if="!running" class="t2s-flow-ribbon" aria-hidden="true">
                  <i v-for="stage in flowStages" :key="stage.id" :class="`is-${stage.status}`"/>
                </span>
                <span class="t2s-flow-time">{{ flowDurationText }}</span>
                <span v-if="!running" class="t2s-flow-action text-caption">{{ flowExpanded ? '收起' : '展开' }}<ArrowDown class="t2s-flow-chevron" aria-hidden="true"/></span>
              </span>
            </button>
            <div
              v-show="running || flowExpanded"
              id="t2s-flow-body"
              class="t2s-flow-body"
              :class="{ 'is-overlay': running && !!response?.result }"
            >
              <ol class="t2s-stages" aria-label="查询流程">
                <li v-for="stage in flowStages" :key="stage.id" :class="`is-${stage.status}`">
                  <span class="t2s-stage-dot" aria-hidden="true">
                    <CircleCheckFilled v-if="stage.status === 'success'"/>
                    <CircleCloseFilled v-else-if="stage.status === 'error'"/>
                    <i v-else-if="stage.status === 'running'" class="t2s-stage-pulse"/>
                    <i v-else class="t2s-stage-hollow"/>
                  </span>
                  <span class="t2s-stage-name text-caption">{{ stage.name }}</span>
                  <small v-if="stage.status === 'success' && stage.ms != null" class="text-caption">{{ formatStageMs(stage.ms) }}</small>
                  <small v-else-if="stage.status === 'running'" class="text-caption">进行中…</small>
                  <small v-else-if="stage.status === 'error'" class="text-caption">失败<span v-if="stage.ms != null"> · {{ formatStageMs(stage.ms) }}</span></small>
                  <small v-else-if="stage.status === 'skipped'" class="text-caption">未执行</small>
                  <small v-else-if="stage.status === 'pending'" class="text-caption">等待</small>
                </li>
              </ol>
              <p v-if="running && response?.result" class="t2s-flow-hint text-caption muted">下方为上一次的结果</p>
              <p class="t2s-visually-hidden" aria-live="polite">{{ activeStageText }}</p>
            </div>
          </section>

          <div v-if="response && (response.result || activeTab !== 'result' || !activeIssue)" class="t2s-output-body">
            <div v-if="viewingHistory" class="studio-callout text-secondary">
              <InfoFilled/><span>历史快照 · {{ response.datasource_name }} · {{ formatTime(response.createdAt) }}</span>
              <el-button link type="primary" :disabled="busy" @click="run()">按当前配置重新查询</el-button>
            </div>
            <p v-if="!activeIssue && question.trim() !== response.question.trim()" class="t2s-result-question text-caption muted">当前结果对应：{{ response.question }}</p>

            <template v-if="activeTab === 'result'">
              <Text2SQLResults
                v-if="response.result"
                :response="response"
                :busy="busy"
                :context-valid="response.datasource_id === sourceId && sourceReady"
                :feedback-items="requestIssues"
                :feedback-saved="feedbackSaved"
                :metrics="sourceMetrics"
                @continue="focusQuestion"
                @feedback="openFeedback"
                @feedback-progress="workspace = 'quality'"
              />
              <div v-else class="t2s-blocked">
                <InfoFilled/>
                <h3 class="text-section-title">{{ activeIssue?.title || '暂无结果' }}</h3>
                <p class="text-secondary">{{ activeIssue?.hint || '查看 SQL 与校验页签，或调整问题后重试。' }}</p>
                <el-button @click="examplesOpen = true">选择可运行的问题<Right/></el-button>
              </div>
            </template>

            <template v-else-if="activeTab === 'explanation'">
              <h3 class="text-section-title">这次查询如何理解你的问题</h3>
              <p v-if="response.explanation?.text" class="text-secondary t2s-explanation-text">{{ response.explanation.text }}</p>
              <p v-else class="text-secondary">模型没有返回额外的业务说明；可查看下方召回的表、字段、关联与匹配值。</p>

              <div class="t2s-section-heading t2s-spaced"><h3 class="text-section-title">召回与补全的表</h3><span class="text-caption muted">{{ retrieval.tables.length }} 张表</span></div>
              <div v-for="table in retrieval.tables" :key="table.fullName || table.name" class="t2s-table-hit">
                <span :class="['tinted-icon', table.source === 'relation' ? 'purple' : 'blue']"><Grid/></span>
                <div><code class="text-code text-caption">{{ table.fullName || table.name }}</code><small class="text-secondary">{{ table.description || '未填写业务说明' }}</small></div>
                <span v-if="table.source === 'relation'" class="tag-soft purple">关系补全</span>
                <span v-else-if="table.source === 'scope'" class="tag-soft">范围表</span>
                <span v-else class="t2s-score text-caption">{{ Number(table.score || 0).toFixed(2) }}</span>
              </div>
              <p v-if="!retrieval.tables.length" class="t2s-unavailable text-secondary">无已召回的 Schema。</p>

              <div class="t2s-section-heading t2s-spaced"><h3 class="text-section-title">Columns</h3><span class="text-caption muted">{{ retrieval.columns.length }} 个字段</span></div>
              <div class="t2s-context-columns">
                <div v-for="col in retrieval.columns" :key="`${col.table}.${col.name}`" class="text-secondary">
                  <code class="text-code text-caption">{{ col.table }}.<b>{{ col.name }}</b></code>
                  <span>{{ col.description || '—' }}</span>
                  <small class="text-secondary">{{ col.type }}</small>
                </div>
              </div>

              <div class="t2s-section-heading t2s-spaced"><h3 class="text-section-title">Relations</h3><span class="text-caption muted">外键 · 1 hop</span></div>
              <div v-for="rel in retrieval.relations" :key="`${rel.from_table}.${rel.from_column}-${rel.to_table}`" class="t2s-relation">
                <Share/><code class="text-code text-caption">{{ rel.from_table }}.{{ rel.from_column }}<br/><span>↳ {{ rel.to_table }}.{{ rel.to_column }}</span></code>
              </div>
              <p v-if="!retrieval.relations.length" class="text-caption muted">此查询无需跨表关系。</p>

              <div class="t2s-section-heading t2s-spaced"><h3 class="text-section-title">Matched Values</h3><span class="text-caption muted">低基数字段</span></div>
              <div v-for="value in retrieval.values" :key="`${value.table}.${value.column}.${value.value}`" class="t2s-value-hit">
                <code class="text-code text-caption">{{ value.table }}.{{ value.column }}</code>
                <span class="text-secondary"><b>{{ value.value }}</b><span v-if="value.label !== value.value"> ← {{ value.label }}</span></span>
              </div>
              <p v-if="!retrieval.values.length" class="text-caption muted">本次没有命中枚举值。</p>
            </template>

            <template v-else-if="activeTab === 'sql'">
              <div class="t2s-section-heading">
                <h3 class="text-section-title">本次 SQL</h3>
                <el-space>
                  <el-button v-if="response.sql?.generated" link type="primary" @click="copySql"><CopyDocument/>复制 SQL</el-button>
                  <el-button v-if="response.sql?.final" link type="primary" :disabled="busy" @click="sqlDraft = response.sql.final; sqlDialogOpen = true">编辑 SQL 重跑</el-button>
                </el-space>
              </div>
              <div v-if="response.sql?.generated" class="code-card t2s-sql-card">
                <div class="code-head text-secondary"><span>PostgreSQL</span><span>{{ response.sql.final === response.sql.generated ? '生成 SQL' : '人工草稿已提交' }}</span></div>
                <pre class="code"><code>{{ response.sql.generated }}</code></pre>
              </div>
              <p v-else class="t2s-unavailable text-secondary">本次链路未生成 SQL。</p>
              <div v-if="response.sql?.final && response.sql.final !== response.sql.generated" class="code-card t2s-sql-card">
                <div class="code-head text-secondary"><span>PostgreSQL</span><span>实际执行</span></div>
                <pre class="code"><code>{{ response.sql.final }}</code></pre>
              </div>

              <div class="t2s-section-heading t2s-spaced">
                <h3 class="text-section-title">SQL 校验</h3>
                <span :class="['tag-soft', response.validation?.valid ? 'green' : 'orange']">{{ response.validation?.valid === null ? '未运行' : response.validation?.valid ? '通过' : '拒绝' }}</span>
              </div>
              <div class="t2s-checks">
                <div v-for="check in response.validation?.checks || []" :key="check.label">
                  <CircleCheckFilled v-if="check.valid" class="t2s-passed-icon"/><CircleCloseFilled v-else class="t2s-failed-icon"/>
                  <span><strong class="text-secondary text-label">{{ check.label }}</strong><small class="text-secondary">{{ check.detail }}</small></span>
                </div>
              </div>
              <div v-for="warning in response.validation?.warnings || []" :key="warning" class="t2s-limit-note text-caption">
                <Warning/><span>{{ warning }}</span>
              </div>
              <div v-if="response.sql?.final" class="t2s-limit-note text-caption">
                <Lock/><span>只读事务执行；外层 LIMIT 最多 {{ maxRows }} 行，超时 {{ timeoutMs }} ms。</span>
              </div>
            </template>

            <template v-else-if="activeTab === 'plan'">
              <template v-if="response.explain">
                <div class="t2s-plan-callout text-secondary">
                  <Histogram/><span>EXPLAIN (FORMAT JSON)<small class="text-secondary">只读执行前采集，不产生数据修改</small></span>
                  <span class="tag-soft green">通过</span>
                </div>
                <div class="t2s-plan-metrics">
                  <div><span class="text-caption">Total Cost</span><strong class="text-section-title text-label">{{ Number(response.explain.total_cost || 0).toLocaleString() }}</strong><small class="text-caption">估算成本</small></div>
                  <div><span class="text-caption">Plan Rows</span><strong class="text-section-title text-label">{{ Number(response.explain.plan_rows || 0).toLocaleString() }}</strong><small class="text-caption">估算行数</small></div>
                  <div><span class="text-caption">Plan Width</span><strong class="text-section-title text-label">{{ response.explain.plan_width }}</strong><small class="text-caption">bytes</small></div>
                </div>
                <div class="t2s-section-heading"><h3 class="text-section-title">计划节点</h3><span class="text-caption muted">估算值</span></div>
                <div class="t2s-plan-tree">
                  <div v-for="(node, i) in response.explain.nodes" :key="i" :style="{ '--node-depth': node.depth }">
                    <span class="t2s-plan-branch text-secondary">{{ node.depth ? '↳' : '●' }}</span>
                    <span><strong class="text-secondary text-label">{{ node.node }}</strong><code class="text-code text-caption">{{ node.detail }}</code></span>
                    <small class="text-caption">{{ node.rows }} rows<br/>cost {{ node.cost }}</small>
                  </div>
                </div>
                <details class="t2s-json text-secondary"><summary>查看原始计划 JSON <ArrowDown/></summary><pre class="code">{{ JSON.stringify(response.explain, null, 2) }}</pre></details>
              </template>
              <div v-else class="t2s-blocked">
                <Histogram/>
                <h3 class="text-body">暂无执行计划</h3>
                <p class="text-secondary">SQL 通过校验并执行后才会生成执行计划。</p>
              </div>
            </template>

            <template v-else>
              <div class="t2s-section-heading"><h3 class="text-section-title">流水线耗时</h3><span class="tag-soft">只读查询</span></div>
              <div class="t2s-debug-stages">
                <div v-for="stage in response.stages || []" :key="stage.id" :class="stage.status">
                  <CircleCheckFilled v-if="stage.status === 'success'"/><CircleCloseFilled v-else-if="stage.status === 'error'"/><Remove v-else/>
                  <span><strong class="text-secondary text-label">{{ stage.label }}</strong><small class="text-caption">{{ stage.name }}</small></span>
                  <div class="t2s-duration-track"><i :style="{ width: `${Math.max(stage.ms ? 3 : 0, (stage.ms || 0) / Math.max(1, totalMs) * 100)}%` }"/></div>
                  <b class="text-secondary">{{ stage.status === 'skipped' ? '跳过' : `${stage.ms} ms` }}</b>
                </div>
              </div>
              <div class="t2s-duration-total text-secondary"><span>总耗时</span><strong class="text-section-title text-label">{{ totalMs.toLocaleString() }} <small class="text-secondary">ms</small></strong></div>
              <div class="t2s-section-heading t2s-spaced"><h3 class="text-section-title">Token Usage</h3><span class="text-caption muted">未返回</span></div>
              <div class="t2s-token-usage">
                <div><span class="text-secondary">Prompt</span><strong class="text-section-title text-label">{{ response.usage?.prompt_tokens?.toLocaleString() ?? '—' }}</strong></div>
                <div><span class="text-secondary">Completion</span><strong class="text-section-title text-label">{{ response.usage?.completion_tokens?.toLocaleString() ?? '—' }}</strong></div>
                <div><span class="text-secondary">Total</span><strong class="text-section-title text-label">{{ response.usage?.total_tokens?.toLocaleString() ?? '—' }}</strong></div>
              </div>
              <dl class="t2s-debug-meta">
                <div class="text-caption"><dt>Request ID</dt><dd>{{ response.request_id }}</dd></div>
                <div class="text-caption"><dt>Data Source</dt><dd>{{ response.datasource_name }}</dd></div>
                <div class="text-caption"><dt>Operator</dt><dd>Text2SQL · {{ response.sql?.generated ? 'LLM' : 'Manual SQL' }}</dd></div>
                <div class="text-caption"><dt>日期策略</dt><dd>{{ datePolicyLabel }}</dd></div>
                <div class="text-caption"><dt>数据基准</dt><dd>{{ response.reference_date || '—' }}</dd></div>
                <div class="text-caption"><dt>上下文预算</dt><dd>{{ contextSummary }}</dd></div>
              </dl>
              <details class="t2s-json text-secondary"><summary>查看完整响应 JSON <ArrowDown/></summary><pre class="code">{{ JSON.stringify(response, null, 2) }}</pre></details>
            </template>
          </div>

          <div v-if="showTechnical" class="t2s-output-footer text-caption">
            <el-button v-if="response" link aria-label="导出本次调试信息" @click="exportResponse"><Download/>调试 JSON</el-button>
            <span><Lock/>SELECT only · EXPLAIN first</span>
            <span>{{ response ? `Tables ${retrieval.tables.length} · Values ${retrieval.values.length}` : '等待自然语言查询' }}</span>
          </div>
        </section>
      </div>

      <section v-show="workspace === 'sources'" aria-label="数据源列表">
        <div class="t2s-management-heading">
          <div>
            <h2 class="text-section-title">数据源与语义维护</h2>
            <p class="text-secondary">配置连接和查询范围，核对业务定义后到「验证与反馈」发布当前配置。</p>
          </div>
          <el-button :disabled="busy" @click="openQuality(source)">验证与发布<Right/></el-button>
        </div>
        <div class="toolbar">
          <div class="toolbar-left"><el-button type="primary" :disabled="busy" @click="openSourceDialog(null)"><Plus/>新增数据源</el-button></div>
          <div class="toolbar-right"><el-input v-model="sourceSearch" class="search-field" placeholder="搜索名称、数据库或 Schema…" aria-label="搜索数据源" clearable :prefix-icon="Search"/></div>
        </div>
        <div class="table-card">
          <table class="list-table t2s-source-table">
            <thead><tr><th>数据源名称</th><th>类型</th><th>数据库 / Schema</th><th>状态</th><th>表范围</th><th>最近准备</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="item in sourcePageRows" :key="item.id" :data-source-id="item.id">
                <td>
                  <el-button link type="primary" :disabled="busy" @click="openSource(item)">{{ item.name }}</el-button>
                  <div v-if="sourceId === item.id" class="entity-sub"><span class="tag-soft blue">当前查询源</span></div>
                </td>
                <td>{{ item.type || 'PostgreSQL' }}</td>
                <td>{{ item.database }}<div class="entity-sub">{{ item.schema }}</div></td>
                <td><span class="tag-soft" :class="item.enabled === false ? '' : sourceReadyFor(item) ? 'green' : 'orange'">{{ sourceStatusLabel(item) }}</span></td>
                <td>{{ item.status === 'configured' ? '待准备' : `${(item.selectedTables || []).length} 张表` }}</td>
                <td class="nowrap">{{ item.indexedAt || item.scannedAt || '尚未准备' }}</td>
                <td><el-button link type="primary" :disabled="busy" :aria-label="`管理数据源：${item.name}`" @click="openSource(item)">管理<Right/></el-button></td>
              </tr>
              <tr v-if="!filteredSources.length"><td class="empty-row" colspan="7">没有匹配的数据源 <el-button link type="primary" @click="sourceSearch = ''">清除搜索</el-button></td></tr>
            </tbody>
          </table>
        </div>
        <TablePagination v-model:page="sourcePage" v-model:size="sourcePageSize" :total="filteredSources.length"/>
        <p class="studio-inline-note text-caption"><InfoFilled/>点击名称或“管理”查看详情；查看不会切换当前查询数据源。</p>
      </section>

      <Text2SQLRelationDialog
        v-model="relationOpen"
        :datasource-id="sourceId"
        :tables="sourceTables"
        :relations="sourceRelations"
        @refresh="loadAll"
      />

      <Text2SQLAssistDialog
        v-model="assistOpen"
        :datasource-id="sourceId"
        :source="source"
        :tables="sourceTables"
        :values="sourceValues"
        @refresh="loadAll"
      />

      <Text2SQLSourceDrawer
        v-if="managedSource"
        v-model="sourceDrawerOpen"
        :source="managedSource"
        :initial-tab="sourceDrawerTab"
        :tables="managedTables"
        :relations="managedRelations"
        :metrics="managedMetrics"
        :busy="busy"
        :action="sourceAction"
        :can-delete="sources.length > 1"
        :is-query-source="managedSource.id === sourceId"
        @edit="openSourceDialog(managedSource)"
        @prepare="openPreparation($event, managedSource)"
        @scan="scanSource(managedSource)"
        @relations="relationOpen = true"
        @index="buildVersion(managedSource)"
        @toggle="toggleSource(managedSource)"
        @delete="deleteSource(managedSource)"
        @use="useSource(managedSource)"
        @quality="openQuality(managedSource, 'semantics')"
      />

      <Text2SQLQualityCenter
        v-if="workspace === 'quality' && source"
        :key="source.id"
        :source="source"
        :sources="sources"
        :versions="versions"
        :publications="publications"
        :feedback="feedback"
        :tables="sourceTables"
        :values="sourceValues"
        :metrics="sourceMetrics"
        :busy="busy"
        :initial-tab="qualityInitialTab"
        @source="selectSource"
        @prepare="openPreparation($event, source)"
        @scan="scanSource(source)"
        @build="buildVersion(source)"
        @publish="publishLatest"
        @query="workspace = 'query'; focusQuestion()"
        @manage="openSource(source)"
        @create-value="addValue"
        @update-value="editValue"
        @delete-value="removeValue"
        @create-metric="addMetric"
        @delete-metric="removeMetric"
        @set-metric-status="changeMetricStatus"
        @cleanup="cleanupOldVersions"
        @assist="assistOpen = true"
      />

      <section v-if="workspace === 'history'" class="t2s-panel t2s-history-page" aria-label="查询历史">
        <div class="t2s-panel-heading">
          <div>
            <h2 class="text-section-title">查询记录与常用问题</h2>
            <p class="text-secondary">历史保存最近 50 次运行的完整快照；常用查询独立保留。</p>
          </div>
          <div class="t2s-inline-actions">
            <el-button @click="openFavorite()">新建常用查询</el-button>
            <el-button v-if="libraryView === 'history' && history.length" :disabled="busy" @click="clearHistory">清空全部记录</el-button>
          </div>
        </div>
        <el-tabs v-model="libraryView" class="t2s-tabs">
          <el-tab-pane :label="`运行历史 (${history.length})`" name="history"/>
          <el-tab-pane :label="`常用查询 (${favorites.length})`" name="favorites"/>
        </el-tabs>
        <div v-if="libraryHasRecords" class="t2s-history-list">
          <div class="toolbar">
            <div class="toolbar-right">
              <el-input v-model="historySearch" class="search-field" aria-label="搜索历史问题" placeholder="搜索名称、问题或数据源…" clearable :prefix-icon="Search"/>
              <el-select v-model="historySource" aria-label="按数据源筛选记录" style="width: 160px">
                <el-option label="全部数据源" value="all"/>
                <el-option v-for="item in librarySources" :key="item.id" :label="item.name" :value="item.id"/>
              </el-select>
              <template v-if="libraryView === 'history'">
                <el-select v-model="historyStatus" aria-label="按状态筛选历史" style="width: 130px">
                  <el-option label="全部状态" value="all"/><el-option label="查询成功" value="success"/><el-option label="查询未完成" value="error"/>
                </el-select>
                <el-select v-model="historyPeriod" aria-label="按时间筛选历史" style="width: 130px">
                  <el-option label="全部时间" value="all"/><el-option label="今天" value="today"/><el-option label="最近7天" value="week"/>
                </el-select>
              </template>
            </div>
          </div>
        </div>

        <div v-if="libraryView === 'history' && filteredHistory.length" class="t2s-history-list">
          <div class="table-card">
            <table class="list-table t2s-history-table">
              <thead><tr><th>查询问题</th><th>数据源</th><th>运行时间</th><th>状态</th><th class="t2s-history-duration">耗时</th><th class="t2s-history-actions">操作</th></tr></thead>
              <tbody>
                <tr v-for="item in filteredHistory" :key="item.request_id" class="t2s-record t2s-history-row">
                  <td class="t2s-history-question-cell">
                    <button class="t2s-history-question" :disabled="busy" :title="item.question" :aria-label="`查看查询：${item.question}`" @click="restoreHistory(item)">
                      <CircleCheckFilled v-if="item.result" class="t2s-passed-icon"/><InfoFilled v-else/><span>{{ item.question }}</span>
                    </button>
                    <small class="t2s-history-mobile-meta text-caption muted">{{ item.datasource_name }} · {{ formatTime(item.createdAt) }}</small>
                  </td>
                  <td class="t2s-history-source" :title="item.datasource_name"><span>{{ item.datasource_name }}</span></td>
                  <td class="t2s-history-time">{{ formatTime(item.createdAt) }}</td>
                  <td class="t2s-history-outcome">
                    <span class="tag-soft" :class="item.result ? 'green' : 'orange'" :title="item.error?.message">{{ item.result ? '查询成功' : errorTitle(item.error) }}</span>
                    <span class="t2s-history-mobile-duration text-caption muted">{{ totalOf(item).toLocaleString() }} ms</span>
                  </td>
                  <td class="t2s-history-duration">{{ totalOf(item).toLocaleString() }} ms</td>
                  <td class="t2s-history-actions">
                    <div class="t2s-inline-actions">
                      <el-button v-if="item.result" link :disabled="busy" @click="rerunHistory(item)">重新查询</el-button>
                      <el-button v-if="item.result" link :disabled="busy" @click="openFavorite(item)">保存常用</el-button>
                      <el-button class="danger-action" link type="danger" :disabled="busy" @click="deleteHistory(item)">删除记录</el-button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="text-caption muted t2s-history-count">共 {{ filteredHistory.length }} 条{{ filteredHistory.length !== history.length ? `匹配记录 / 全部 ${history.length} 条` : '运行记录' }} · 点击问题查看当时的完整结果</p>
        </div>

        <div v-else-if="libraryView === 'favorites' && filteredFavorites.length" class="t2s-record-list">
          <div v-for="item in filteredFavorites" :key="item.id" class="t2s-record">
            <div class="t2s-record-main">
              <Star/>
              <span>
                <strong class="text-body text-label">{{ item.name }}</strong>
                <p class="text-secondary">{{ item.question }}</p>
                <small class="text-caption muted">{{ favoritesSourceName(item) }} · {{ datePolicyText(item.datePolicy) }} · {{ item.notes || '常用问题' }}</small>
              </span>
            </div>
            <div class="t2s-inline-actions">
              <el-button type="primary" :disabled="busy || !sources.some(source => source.id === item.datasourceId && source.enabled !== false)" @click="runFavorite(item)">填入并运行</el-button>
              <el-button @click="openFavorite(item)">编辑</el-button>
              <el-button class="danger-action" link type="danger" @click="removeFavorite(item)">删除</el-button>
            </div>
          </div>
        </div>

        <div v-else class="t2s-small-empty text-secondary">
          <component :is="libraryView === 'favorites' ? Star : Clock" aria-hidden="true"/>
          <template v-if="libraryHasRecords">
            <h3 class="text-section-title">没有匹配的记录</h3>
            <p class="text-body">可以调整关键词或筛选条件。</p>
            <el-button @click="resetHistoryFilters">重置筛选</el-button>
          </template>
          <template v-else>
            <h3 class="text-section-title">{{ libraryView === 'favorites' ? '还没有常用查询' : '还没有查询记录' }}</h3>
            <p class="text-body">{{ libraryView === 'favorites' ? '运行查询后可命名保存，之后一键复用。' : '完成和失败的查询会分别记录，方便恢复。' }}</p>
            <el-button type="primary" @click="workspace = 'query'">返回查询<Right/></el-button>
          </template>
        </div>
        <div class="t2s-history-footnote text-caption"><InfoFilled/>历史与常用查询按当前账号保存；删除数据源不会删除已保存的运行快照。</div>
      </section>

      <StudioDialog v-model="examplesOpen" dialog-class="t2s-examples-dialog" title="从一个业务问题开始" subtitle="选择一个示例填入提问框，再生成并运行。" :icon="Coin" hint="示例来自当前数据源的表与指标，可自由改写" width="760px">
        <div v-if="exampleList.length" class="studio-form-section">
          <div class="studio-choice-grid two-columns t2s-examples" role="group" aria-label="业务问题示例">
            <button
              v-for="item in exampleList"
              :key="item.id"
              type="button"
              class="studio-choice"
              :class="{ selected: question === item.question }"
              :aria-label="item.question"
              :aria-pressed="question === item.question"
              @click="selectExample(item)"
            >
              <span class="studio-choice-heading text-body">{{ item.title }}</span>
              <span class="text-secondary">{{ item.question }}</span>
              <span class="studio-choice-desc">{{ item.hint }}</span>
            </button>
          </div>
        </div>
        <el-empty v-else description="当前数据源还没有可推荐的示例，直接输入问题即可。"/>
        <template #actions><el-button @click="examplesOpen = false">关闭</el-button></template>
      </StudioDialog>

      <StudioDialog v-model="optionsOpen" title="调整查询条件" subtitle="日期策略会作为查询参数发送，由后端解析为具体时间范围。" :icon="Operation" width="560px">
        <el-form label-position="top" class="studio-form">
          <FormSection number="01" title="日期策略">
            <el-form-item label="统计时间">
              <el-radio-group v-model="datePolicy" aria-label="日期策略">
                <el-radio value="relative">按数据基准取最近 30 天</el-radio>
                <el-radio value="fixed">固定日期范围</el-radio>
                <el-radio value="all">不限制时间</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="datePolicy === 'fixed'" label="固定范围">
              <el-date-picker v-model="fixedRange" type="daterange" value-format="YYYY-MM-DD" aria-label="固定日期范围" start-placeholder="开始日期" end-placeholder="结束日期"/>
            </el-form-item>
            <p class="text-caption muted">固定范围结束日期按当天 24:00（exclusive）解释；实际时区为 {{ source?.businessTimezone || 'UTC' }}。</p>
          </FormSection>
        </el-form>
        <template #actions><el-button @click="optionsOpen = false">完成</el-button><el-button type="primary" :disabled="datePolicy === 'fixed' && !fixedRange" @click="optionsOpen = false; focusQuestion()">应用到提问</el-button></template>
      </StudioDialog>

      <Text2SQLPreparationDialog
        v-if="preparationSource"
        v-model="prepareOpen"
        :source="preparationSource"
        :tables="preparationTables"
        :relations="preparationRelations"
        :confirm-text="preparationOrigin === 'sources' ? '确认并准备' : '准备并开始查询'"
        :preparing="sourceAction === 'prepare'"
        :prepare-stage="prepareStage"
        :initial-step="preparationStep"
        @prepare="prepareData"
      />

      <StudioDialog v-model="favoriteOpen" title="保存常用查询" subtitle="保存问题、数据源与已确认的分析范围，便于重复使用。" :icon="Star" hint="常用查询按当前账号保存" width="680px">
        <el-form label-position="top" class="studio-form" @submit.prevent="saveFavorite">
          <FormSection number="01" title="常用问题">
            <div class="studio-field-grid">
              <el-form-item label="查询名称" required><el-input v-model="favoriteDraft.name" aria-label="常用查询名称" maxlength="80"/></el-form-item>
              <el-form-item label="数据源" required>
                <el-select v-model="favoriteDraft.datasourceId" aria-label="常用查询数据源">
                  <el-option v-for="item in sources" :key="item.id" :label="item.name" :value="item.id"/>
                </el-select>
              </el-form-item>
            </div>
            <el-form-item label="问题" required><el-input v-model="favoriteDraft.question" aria-label="常用查询问题" type="textarea" :rows="2" maxlength="1000"/></el-form-item>
            <el-form-item label="日期策略">
              <el-select v-model="favoriteDraft.datePolicy" aria-label="常用查询日期策略">
                <el-option label="相对当前日期" value="relative"/>
                <el-option label="固定本次日期范围" value="fixed" :disabled="!favoriteFixedRange"/>
                <el-option label="不限制时间" value="all"/>
              </el-select>
              <p v-if="favoriteDraft.datePolicy === 'fixed'" class="studio-field-help text-caption">固定范围：{{ favoriteFixedRange?.start || '—' }} 至 {{ favoriteFixedRange?.endExclusive || '—' }}</p>
            </el-form-item>
            <el-form-item label="备注"><el-input v-model="favoriteDraft.notes" aria-label="常用查询备注" maxlength="1000"/></el-form-item>
            <p v-if="favoriteError" class="text-secondary t2s-failed-icon" role="alert">{{ favoriteError }}</p>
          </FormSection>
        </el-form>
        <template #actions><el-button @click="favoriteOpen = false">取消</el-button><el-button type="primary" :loading="busy" @click="saveFavorite">保存常用查询</el-button></template>
      </StudioDialog>

      <StudioDialog v-model="feedbackOpen" title="反馈查询问题" subtitle="记录这次分析中遇到的问题，作为后续完善业务口径与示例的依据。" :icon="ChatLineSquare" hint="反馈按数据源汇总到「验证与反馈」" width="640px">
        <el-form label-position="top" class="studio-form">
          <FormSection number="01" title="问题说明">
            <el-form-item label="问题类型">
              <el-radio-group v-model="feedbackDraft.category" class="t2s-feedback-categories"><el-radio value="meaning">业务口径有误</el-radio><el-radio value="sql">SQL 有误</el-radio><el-radio value="data">数据不全</el-radio></el-radio-group>
            </el-form-item>
            <el-form-item label="具体说明" required><el-input v-model="feedbackDraft.notes" aria-label="反馈具体说明" type="textarea" :rows="4" maxlength="1000" placeholder="描述预期口径或缺失的数据，便于后续核对。"/></el-form-item>
          </FormSection>
        </el-form>
        <template #actions><el-button @click="feedbackOpen = false">取消</el-button><el-button type="primary" :disabled="!feedbackDraft.notes.trim() || busy" @click="saveFeedback">保存反馈</el-button></template>
      </StudioDialog>

      <StudioDialog v-model="sqlDialogOpen" title="编辑 SQL 重跑" subtitle="SQL 仍会经过只读校验与行数/超时限制。" :icon="EditPen" width="760px">
        <el-input v-model="sqlDraft" class="t2s-sql-editor" type="textarea" :rows="14" aria-label="SQL 草稿"/>
        <template #actions><el-button @click="sqlDialogOpen = false">取消</el-button><el-button type="primary" :disabled="!sqlDraft.trim() || busy" @click="runWithSql">执行 SQL</el-button></template>
      </StudioDialog>

      <Text2SQLSourceDialog
        v-model="sourceDialogOpen"
        :source="editingSource"
        :existing-names="sources.filter(item => item.id !== editingSource?.id).map(item => item.name)"
        @save="saveSource"
      />
    </div>
  </AppPage>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ChatLineSquare,
  CircleCheck,
  CircleCheckFilled,
  CircleCloseFilled,
  Clock,
  Coin,
  CopyDocument,
  Download,
  EditPen,
  Grid,
  Histogram,
  InfoFilled,
  Loading,
  Lock,
  MoreFilled,
  Operation,
  Plus,
  Refresh,
  Remove,
  Right,
  Search,
  Share,
  Star,
  VideoPlay,
  Warning
} from '@element-plus/icons-vue'

import AppPage from '@/shared/ui/AppPage.vue'
import PageHeader from '@/shared/ui/reference/PageHeader.vue'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import FormSection from '@/shared/ui/FormSection.vue'
import TablePagination from '@/shared/ui/reference/TablePagination.vue'
import Text2SQLResults from '@/features/text2sql/components/Text2SQLResults.vue'
import Text2SQLQualityCenter from '@/features/text2sql/components/Text2SQLQualityCenter.vue'
import Text2SQLSourceDialog from '@/features/text2sql/components/Text2SQLSourceDialog.vue'
import Text2SQLSourceDrawer from '@/features/text2sql/components/Text2SQLSourceDrawer.vue'
import Text2SQLAssistDialog from '@/features/text2sql/components/Text2SQLAssistDialog.vue'
import Text2SQLRelationDialog from '@/features/text2sql/components/Text2SQLRelationDialog.vue'
import Text2SQLPreparationDialog from '@/features/text2sql/components/Text2SQLPreparationDialog.vue'
import { useListTable } from '@/features/text2sql/composables/useListTable'
import { exampleQuestions } from '@/features/text2sql/demo-data/text2sql'
import { tableLabel } from '@/features/text2sql/demo-data/text2sqlScale'
import { copyText, downloadText } from '@/features/text2sql/utils/demo'
import { QUERY_STAGES, problemText, stageEventState } from '@/features/text2sql/utils/queryStages'
import { queryAvailable, topicDetails } from '@/features/text2sql/utils/text2sqlExperience'
import { errorPresentation, resultCSV, sourceStatus } from '@/features/text2sql/utils/text2sqlWorkspace'
import {
  buildVersion as buildVersionApi,
  cleanupVersions,
  getVersion,
  setMetricStatus,
  clearRuns,
  createDatasource,
  createFavorite,
  createFeedback,
  createMetric,
  createValue,
  createVersion,
  deleteDatasource,
  deleteFavorite,
  deleteMetric,
  deleteRun,
  deleteValue,
  getWorkspace,
  listDatasources,
  listFavorites,
  listFeedback,
  listMetrics,
  listPublications,
  listRelations,
  listRuns,
  listTables,
  listValues,
  listVersions,
  publishVersion,
  runQueryStream,
  saveWorkspace,
  scanDatasource,
  updateDatasource,
  updateFavorite,
  updateColumn,
  updateTable,
  updateValue
} from '@/features/text2sql/api/text2sql.js'

const workspaceTabs = [
  { id: 'query', label: '查询工作台', icon: ChatLineSquare },
  { id: 'history', label: '查询历史', icon: Clock },
  { id: 'sources', label: '数据源', icon: Coin },
  { id: 'quality', label: '验证与反馈', icon: CircleCheck }
]

const workspace = ref('query')
const libraryView = ref('history')
const saveState = ref('saved')
const loading = ref(false)

const sources = ref([])
const sourceId = ref('')
const sourceSearch = ref('')
const sourceTables = ref([])
const sourceRelations = ref([])
const relationOpen = ref(false)
const assistOpen = ref(false)
const sourceMetrics = ref([])
const sourceValues = ref([])
const versions = ref([])
const publications = ref([])
const feedback = ref([])

const managedSourceId = ref('')
const sourceDrawerOpen = ref(false)
const sourceDrawerTab = ref('overview')
const managedTables = ref([])
const managedRelations = ref([])
const managedMetrics = ref([])

const preparationSourceId = ref('')
const preparationOrigin = ref('query')
const prepareOpen = ref(false)
const prepareStage = ref(0)
const preparationStep = ref(0)
const qualityInitialTab = ref('validation')
const sourceAction = ref('')

const sourceDialogOpen = ref(false)
const editingSource = ref(null)

const question = ref('')
const datePolicy = ref('relative')
const fixedRange = ref(null)
const response = ref(null)
const activeTab = ref('result')
const viewingHistory = ref(false)
const showTechnical = ref(false)
const guideDismissed = ref(false)
const examplesOpen = ref(false)
const sourceDetailsOpen = ref(false)
const optionsOpen = ref(false)
const sqlDialogOpen = ref(false)
const sqlDraft = ref('')
const outputPanel = ref(null)

const running = ref(false)
const stageProgress = ref({})
const flowExpanded = ref(false)
const elapsedMs = ref(0)
let elapsedTimer = null
const history = ref([])
const favorites = ref([])
const historySearch = ref('')
const historySource = ref('all')
const historyStatus = ref('all')
const historyPeriod = ref('all')

const favoriteOpen = ref(false)
const favoriteError = ref('')
const favoriteDraft = reactive({ id: '', name: '', question: '', datasourceId: '', datePolicy: 'relative', fixedTimeRange: null, notes: '' })
const favoriteFixedRange = computed(() => favoriteDraft.fixedTimeRange || (fixedRange.value ? { start: fixedRange.value[0], endExclusive: fixedRange.value[1] } : null))
const feedbackOpen = ref(false)
const feedbackDraft = reactive({ category: 'meaning', notes: '' })

const source = computed(() => sources.value.find(item => item.id === sourceId.value) || sources.value[0] || null)
const managedSource = computed(() => sources.value.find(item => item.id === managedSourceId.value) || null)
const preparationSource = computed(() => sources.value.find(item => item.id === preparationSourceId.value) || source.value)
const preparationTables = computed(() => (preparationSource.value?.id === sourceId.value ? sourceTables.value : managedTables.value))
const preparationRelations = computed(() => (preparationSource.value?.id === sourceId.value ? sourceRelations.value : managedRelations.value))

const filteredSources = computed(() => sources.value.filter(item => `${item.name} ${item.database} ${item.schema}`.toLowerCase().includes(sourceSearch.value.trim().toLowerCase())))
const { page: sourcePage, pageSize: sourcePageSize, pageRows: sourcePageRows } = useListTable(sources, filteredSources, [sourceSearch])

const busy = computed(() => running.value || !!sourceAction.value)
const sourceReady = computed(() => Boolean(source.value) && queryAvailable(source.value))
const sourceOwner = computed(() => (source.value ? topicDetails(source.value).owner : '未指定维护人'))
const selectedTableCount = computed(() => (source.value?.selectedTables || []).length)
const activeVersion = computed(() => versions.value.find(item => item.id === source.value?.activeVersionId) || null)
const latestReady = computed(() => versions.value.find(item => item.status === 'READY') || null)
const totalMs = computed(() => Number(response.value?.timing?.total_ms || 0))
const retrieval = computed(() => response.value?.retrieval || { tables: [], columns: [], values: [], relations: [] })
// 模型实际看到的上下文规模：预算是否触发截断、有没有表被省略。
const contextSummary = computed(() => {
  const context = retrieval.value.context
  if (!context) {
    return '—'
  }
  const parts = [`${(context.tables || []).length} 张表`, `${context.chars || 0} 字符`]
  if (context.truncated) {
    parts.push('已截断')
  }
  if ((context.omitted || []).length) {
    parts.push(`省略 ${context.omitted.length} 张`)
  }
  if (context.fallback) {
    parts.push('基础视图')
  }
  return parts.join(' · ')
})
const requestIssues = computed(() => feedback.value.filter(item => item.runId === response.value?.id))
const feedbackSaved = computed(() => requestIssues.value.length > 0)
const maxRows = computed(() => Number(source.value?.queryPolicy?.max_rows || 1000))
const timeoutMs = computed(() => Number(source.value?.queryPolicy?.timeout_ms || 30000))
const datePolicyLabel = computed(() => datePolicyText(datePolicy.value))
const datePolicyNote = computed(() => (datePolicy.value === 'relative' ? '' : `本次分析：${datePolicyLabel.value}`))
const runDisabled = computed(() => busy.value || !question.value.trim() || !sourceReady.value || (datePolicy.value === 'fixed' && !fixedRange.value))
// 运行中的步骤条：骨架来自 QUERY_STAGES，状态与耗时由 SSE `stage` 帧按 id 覆盖。
const runningStages = computed(() => QUERY_STAGES.map(stage => {
  const progress = stageProgress.value[stage.id]
  return { ...stage, status: progress?.status || 'pending', ms: progress?.ms ?? null }
}))
// 完成后步骤条不消失：折叠成一行摘要，展开时用后端 stages 的真实耗时。
const flowStages = computed(() => {
  if (running.value) {
    return runningStages.value
  }
  const stages = response.value?.stages
  if (!Array.isArray(stages) || !stages.length) {
    return []
  }
  return stages.map(stage => ({
    id: stage.id,
    name: stage.name || QUERY_STAGES.find(item => item.id === stage.id)?.name || stage.id,
    status: stage.status,
    ms: stage.ms
  }))
})
const flowFailure = computed(() => flowStages.value.find(stage => stage.status === 'error') || null)
const flowHeadline = computed(() => {
  if (running.value) {
    return '正在查询数据…'
  }
  if (flowFailure.value) {
    return `${flowFailure.value.name}失败`
  }
  return `${flowStages.value.length} 个阶段已完成`
})
// 运行中与原型一致按「秒 + 一位小数」走；完成后沿用总耗时（毫秒/秒自适应）。
const flowDurationText = computed(() => (running.value
  ? `${(elapsedMs.value / 1000).toFixed(1)} s`
  : formatStageMs(Number(response.value?.timing?.total_ms || 0))))
const activeStage = computed(() => (running.value
  ? runningStages.value.find(stage => stage.status === 'running') || null
  : null))
const activeStageText = computed(() => (activeStage.value ? `正在执行：${activeStage.value.name}` : ''))

const sourceDescription = computed(() => {
  if (!source.value) {
    return '先新增数据源、扫描结构并发布版本，然后即可提问。'
  }
  return topicDetails(source.value).description || source.value.businessDescription || '配置数据源、选择表并发布版本后即可提问。'
})
const statusText = computed(() => {
  if (!source.value) {
    return '未选择数据源'
  }
  if (source.value.enabled === false) {
    return '已停用'
  }
  if (source.value.status === 'indexed') {
    return '数据已就绪'
  }
  return source.value.status === 'scanned' ? '配置待发布' : sourceStatus(source.value)
})
const versionStateText = computed(() => {
  if (!source.value) {
    return '尚无数据源'
  }
  if (source.value.status === 'indexed') {
    return activeVersion.value ? `已发布版本 v${activeVersion.value.revision}` : '已发布'
  }
  if (activeVersion.value) {
    return `配置 v${source.value.revision || 1} 待发布（活动 v${activeVersion.value.revision}）`
  }
  return `配置 v${source.value.revision || 1} · 尚未发布`
})
const sourceWarning = computed(() => {
  if (source.value?.enabled === false) {
    return '当前数据源已停用，请在数据源管理中启用。'
  }
  if (source.value?.status === 'scanned') {
    return '新配置尚未发布，完成验证后即可提问。'
  }
  return '当前主题暂不能查询，可选择其他主题，或由维护者完成数据准备。'
})
const activeIssue = computed(() => errorPresentation(response.value?.error))
const waitingForQuery = computed(() => !response.value && !running.value && !activeIssue.value)

function tableSelected (tableName) {
  const selected = source.value?.selectedTables || []
  return selected.some(name => name === tableName || name.endsWith(`.${tableName}`))
}
const exampleList = computed(() => {
  // AI 生成并保存的示例问题优先：它们是真业务问法，而不是「查询 X 表前 20 条」。
  const saved = (source.value?.queryExamples || []).map((item, index) => ({
    id: `saved-${index}`,
    title: item.question,
    question: item.question,
    hint: item.hint || ''
  }))
  if (saved.length) {
    return saved
  }
  if (['order_info', 'user_info', 'region_info'].every(tableSelected)) {
    return exampleQuestions.map(item => ({ ...item }))
  }
  const metricExamples = sourceMetrics.value.slice(0, 3).map(item => ({
    id: item.id,
    title: item.businessName,
    question: `统计${item.businessName}`,
    hint: item.description || item.expressionSql || '按当前指标定义生成 SQL'
  }))
  const tableExamples = sourceTables.value
    .filter(item => (source.value?.selectedTables || []).length === 0 || tableSelected(item.name))
    .slice(0, 3)
    .map(item => ({
      id: item.id,
      title: tableLabel(item),
      question: `查询${tableLabel(item)}的前 20 条记录`,
      hint: item.fullName || item.name
    }))
  return [...metricExamples, ...tableExamples].slice(0, 6)
})
const topicExamples = computed(() => exampleList.value.slice(0, 3))

const librarySources = computed(() => [...new Map([
  ...sources.value.map(item => [item.id, { id: item.id, name: item.name }]),
  ...history.value.filter(item => !sources.value.some(source => source.id === item.datasource_id)).map(item => [item.datasource_id, { id: item.datasource_id, name: `${item.datasource_name || item.datasource_id}（已删除）` }])
]).values()])

const filteredHistory = computed(() => history.value.filter(item => {
  const now = new Date()
  const timestamp = new Date(item.createdAt)
  const status = item.result ? 'success' : 'error'
  return `${item.question} ${item.datasource_name || ''}`.toLowerCase().includes(historySearch.value.trim().toLowerCase()) &&
    (historySource.value === 'all' || item.datasource_id === historySource.value) &&
    (historyStatus.value === 'all' || status === historyStatus.value) &&
    (historyPeriod.value === 'all' || (historyPeriod.value === 'today' ? timestamp.toDateString() === now.toDateString() : now - timestamp <= 7 * 86400000 && now >= timestamp))
}))
const filteredFavorites = computed(() => favorites.value.filter(item => `${item.name} ${item.question} ${favoritesSourceName(item)}`.toLowerCase().includes(historySearch.value.trim().toLowerCase()) && (historySource.value === 'all' || item.datasourceId === historySource.value)))
const libraryHasRecords = computed(() => (libraryView.value === 'favorites' ? favorites.value : history.value).length > 0)

function datePolicyText (value) {
  return { relative: '最近 30 天（相对数据基准）', fixed: '固定日期范围', all: '不限制时间' }[value] || '最近 30 天'
}
function formatTime (value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '较早的记录'
}
function totalOf (item) {
  return Number(item?.timing?.total_ms || 0)
}
function errorTitle (error) {
  return { SQL_UNSAFE: 'SQL 未通过安全校验', SQL_TABLE_NOT_ALLOWED: '查询了未授权的表', SQL_TIMEOUT: '查询超时', LLM_GENERATE_FAILED: '模型生成失败', SCHEMA_RETRIEVAL_FAILED: 'Schema 检索失败' }[error?.code] || '查询未完成'
}
function sourceStatusLabel (item) {
  if (item.enabled === false) {
    return '已停用'
  }
  if (item.status === 'indexed') {
    return '已发布'
  }
  return item.status === 'scanned' ? '待验证发布' : '待准备'
}
function sourceReadyFor (item) {
  return item.status === 'indexed' && item.enabled !== false
}
function favoritesSourceName (item) {
  return sources.value.find(source => source.id === item.datasourceId)?.name || '数据源已删除，请重新绑定'
}
function relationView (relation, tables) {
  const sourceTable = tables.find(table => table.id === relation.sourceTableId)
  const targetTable = tables.find(table => table.id === relation.targetTableId)
  const sourceName = sourceTable?.fullName || relation.sourceTableId
  const targetName = targetTable?.fullName || relation.targetTableId
  return {
    ...relation,
    sourceTableName: sourceName,
    targetTableName: targetName,
    sourceTable: { fullName: sourceName },
    targetTable: { fullName: targetName }
  }
}
function resetHistoryFilters () {
  historySearch.value = ''
  historySource.value = 'all'
  historyStatus.value = 'all'
  historyPeriod.value = 'all'
}

async function loadAll () {
  loading.value = true
  try {
    const [sourceData, favoriteData, runData] = await Promise.all([
      listDatasources(), listFavorites(), listRuns({ size: 100 })
    ])
    sources.value = (sourceData.items || []).map(item => ({ ...item, schema: item.schema || item.includeSchemas?.[0] || 'public' }))
    favorites.value = favoriteData.items || []
    history.value = runData.items || []
    if (!sources.value.some(item => item.id === sourceId.value)) {
      sourceId.value = sources.value[0]?.id || ''
    }
    await loadSourceDetails(sourceId.value)
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    loading.value = false
  }
}

async function loadSourceDetails (id) {
  if (!id) {
    sourceTables.value = []
    sourceRelations.value = []
    sourceMetrics.value = []
    sourceValues.value = []
    versions.value = []
    publications.value = []
    feedback.value = []
    return
  }
  try {
    const [tables, relations, metrics, valueData, versionData, publicationData, feedbackData] = await Promise.all([
      listTables(id), listRelations(id), listMetrics(id), listValues(id),
      listVersions(id), listPublications(id), listFeedback(id)
    ])
    const foreignColumns = new Set()
    for (const relation of relations.items || []) {
      for (const pair of relation.columnPairs || []) {
        foreignColumns.add(pair.sourceColumnId)
        foreignColumns.add(pair.targetColumnId)
      }
    }
    sourceRelations.value = (relations.items || []).map(item => relationView(item, tables.items || []))
    sourceTables.value = (tables.items || []).map(table => ({
      ...table,
      columns: (table.columns || []).map(column => ({ ...column, foreignKey: foreignColumns.has(column.id) }))
    }))
    sourceMetrics.value = metrics.items || []
    sourceValues.value = valueData.items || []
    versions.value = versionData.items || []
    publications.value = publicationData.items || []
    feedback.value = feedbackData.items || []
    if (managedSourceId.value === id) {
      managedTables.value = sourceTables.value
      managedRelations.value = sourceRelations.value
      managedMetrics.value = sourceMetrics.value
    }
  } catch (error) {
    // 全局 toast 已提示
  }
}

async function selectSource (id) {
  sourceId.value = id
  response.value = null
  viewingHistory.value = false
  activeTab.value = 'result'
  await loadSourceDetails(id)
}

function selectExample (item) {
  question.value = item.question
  examplesOpen.value = false
  contextDismissed()
  focusQuestion()
}

function contextDismissed () {
  viewingHistory.value = false
}

function manageCurrentSource () {
  sourceDetailsOpen.value = false
  if (source.value) {
    openSource(source.value)
  }
}

async function newQuery () {
  question.value = ''
  response.value = null
  viewingHistory.value = false
  activeTab.value = 'result'
  showTechnical.value = false
  await focusQuestion()
}

function handleResultAction (action) {
  if (action === 'details') {
    showTechnical.value = !showTechnical.value
    return
  }
  if (action === 'conditions') {
    optionsOpen.value = true
    return
  }
  const current = response.value
  if (!current?.result) {
    return
  }
  if (action === 'csv') {
    downloadText(`text2sql-result-${current.request_id}.csv`, resultCSV(current.result), 'text/csv;charset=utf-8')
  }
  if (action === 'json') {
    downloadText(`text2sql-result-${current.request_id}.json`, JSON.stringify({ question: current.question, explanation: current.explanation, ...current.result }, null, 2), 'application/json')
  }
  if (action === 'save') {
    openFavorite(current)
  }
}

async function focusQuestion () {
  workspace.value = 'query'
  await nextTick()
  const input = document.getElementById('text2sql-question')
  input?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  input?.focus?.({ preventScroll: true })
}

async function revealOutput () {
  await nextTick()
  const panel = outputPanel.value
  if (!panel) {
    return
  }
  const rect = panel.getBoundingClientRect()
  // 输出区已经在视口里（用户正看着它）就不再滚：完成瞬间再拉一次页面会显得在跳。
  if (rect.top >= 0 && rect.top < window.innerHeight - 120) {
    return
  }
  panel.scrollIntoView?.({ behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' })
}

const ELAPSED_TICK_MS = 100

// 与 UX 原型一致：毫秒级保留原值，秒级最多两位小数并带空格（18 ms / 1.74 s）。
function formatStageMs (ms) {
  const value = Math.max(0, Math.round(Number(ms) || 0))
  if (value < 1000) {
    return `${value} ms`
  }
  return `${(value / 1000).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} s`
}

function toggleFlow () {
  if (running.value) {
    return
  }
  flowExpanded.value = !flowExpanded.value
}

function startElapsed () {
  stopElapsed()
  const startedAt = performance.now()
  elapsedMs.value = 0
  elapsedTimer = window.setInterval(() => {
    elapsedMs.value = performance.now() - startedAt
  }, ELAPSED_TICK_MS)
}

function stopElapsed () {
  if (elapsedTimer) {
    window.clearInterval(elapsedTimer)
    elapsedTimer = null
  }
}

// SSE 帧体是 JSON；单帧坏了就忽略，由终态兜底（没有 result 帧 = 查询未完成）。
function parseFrameData (raw) {
  try {
    return JSON.parse(raw)
  } catch (error) {
    return null
  }
}

function buildPayload (sql = '') {
  return {
    question: question.value.trim(),
    datePolicy: datePolicy.value,
    parameters: {},
    ...(sql ? { sql } : {}),
    ...(datePolicy.value === 'fixed' && fixedRange.value
      ? { fixedTimeRange: { start: fixedRange.value[0], endExclusive: fixedRange.value[1] } }
      : {})
  }
}

async function run (sql = '') {
  if (busy.value || !question.value.trim()) {
    return
  }
  if (datePolicy.value === 'fixed' && !fixedRange.value) {
    optionsOpen.value = true
    ElMessage.info('请先选择固定日期范围')
    return
  }
  if (!source.value) {
    ElMessage.warning('请先新增并准备一个数据源')
    return
  }
  if (!sourceReady.value) {
    if (source.value.status === 'scanned' && source.value.enabled !== false) {
      openQuality(source.value)
    } else {
      workspace.value = 'sources'
      openSource(source.value)
    }
    return
  }
  running.value = true
  viewingHistory.value = false
  activeTab.value = 'result'
  workspace.value = 'query'
  stageProgress.value = {}
  flowExpanded.value = false
  startElapsed()
  let streamed = null
  try {
    const result = await runQueryStream(source.value.id, buildPayload(sql), {
      onEvent: frame => {
        const data = parseFrameData(frame.data)
        if (frame.event === 'stage') {
          stageProgress.value = stageEventState(stageProgress.value, data || {})
        } else if (frame.event === 'result') {
          streamed = data
        }
      }
    })
    if (!result.ok) {
      // 没进入流式：服务端在出第一字节前失败（请求体/鉴权/未发布…）
      ElMessage.warning(problemText(result.errorEnvelope, '查询未完成'))
      return
    }
    if (result.errorEvent) {
      // 流中途失败：HTTP 已是 200，错误在终态 error 帧里
      ElMessage.warning(problemText(result.errorEvent, '查询未完成'))
      return
    }
    if (!streamed) {
      ElMessage.warning('查询未完成')
      return
    }
    // 折叠与结果必须在同一次渲染里完成：先收运行态再挂结果，否则会先看到
    // 「结果出现（流程还展开）→ 流程收起」两次位移，页面连着蹦两下。
    running.value = false
    stopElapsed()
    response.value = streamed
    if (streamed.error) {
      ElMessage.warning(streamed.error.message || '查询未完成')
    } else {
      ElMessage.success('查询完成')
    }
    await revealOutput()
    history.value = (await listRuns({ size: 100 })).items || []
  } catch {
    // fetch 只在网络层失败时抛错；HTTP 错误已经由 result.ok/errorEvent 分支处理
    ElMessage.warning('查询中断，请重试')
  } finally {
    running.value = false
    stopElapsed()
  }
}

async function runWithSql () {
  const sql = sqlDraft.value.trim()
  sqlDialogOpen.value = false
  await run(sql)
}

function recoverIssue () {
  const action = activeIssue.value?.action
  if (action === 'examples') {
    examplesOpen.value = true
    return
  }
  if (action === 'sources') {
    workspace.value = 'sources'
    return
  }
  if (action === 'prepare') {
    workspace.value = 'sources'
    openPreparation(0, source.value)
    return
  }
  if (action === 'quality') {
    openQuality(source.value, 'semantics')
    return
  }
  if (action === 'question') {
    focusQuestion()
    return
  }
  run()
}

function copySql () {
  const sql = response.value?.sql?.final || response.value?.sql?.generated || ''
  copyText(sql)
}

function exportResponse () {
  if (!response.value) {
    return
  }
  downloadText(`text2sql-debug-${response.value.request_id}.json`, JSON.stringify(response.value, null, 2), 'application/json')
}

function restoreHistory (item) {
  if (sources.value.some(source => source.id === item.datasource_id)) {
    sourceId.value = item.datasource_id
  }
  response.value = item
  question.value = item.question || ''
  datePolicy.value = item.datePolicy || 'relative'
  viewingHistory.value = true
  activeTab.value = 'result'
  workspace.value = 'query'
  revealOutput()
}

async function rerunHistory (item) {
  if (sources.value.some(source => source.id === item.datasource_id)) {
    sourceId.value = item.datasource_id
    await loadSourceDetails(item.datasource_id)
  }
  question.value = item.question
  datePolicy.value = item.datePolicy || 'relative'
  viewingHistory.value = false
  await run()
}

async function deleteHistory (item) {
  try {
    await deleteRun(item.id)
    history.value = history.value.filter(row => row.id !== item.id)
  } catch (error) {
    // 全局 toast 已提示
  }
}

async function clearHistory () {
  try {
    await ElMessageBox.confirm('清空最近运行记录。数据源、常用查询与当前已展示的结果会保留。', '清空查询历史', { type: 'warning', confirmButtonText: '确认清空', cancelButtonText: '取消' })
    await clearRuns()
    history.value = []
  } catch (error) {
    // 用户取消或请求失败
  }
}

function openSource (item, tab = 'overview') {
  if (!item) {
    return
  }
  managedSourceId.value = item.id
  sourceDrawerTab.value = tab
  sourceDrawerOpen.value = true
  if (item.id === sourceId.value) {
    managedTables.value = sourceTables.value
    managedRelations.value = sourceRelations.value
    managedMetrics.value = sourceMetrics.value
  } else {
    managedTables.value = []
    managedRelations.value = []
    managedMetrics.value = []
    loadManagedDetails(item.id)
  }
}

async function loadManagedDetails (id) {
  if (!id) {
    return
  }
  try {
    const [tables, relations, metrics] = await Promise.all([listTables(id), listRelations(id), listMetrics(id)])
    const foreignColumns = new Set()
    for (const relation of relations.items || []) {
      for (const pair of relation.columnPairs || []) {
        foreignColumns.add(pair.sourceColumnId)
        foreignColumns.add(pair.targetColumnId)
      }
    }
    if (managedSourceId.value !== id) {
      return
    }
    managedTables.value = (tables.items || []).map(table => ({
      ...table,
      columns: (table.columns || []).map(column => ({ ...column, foreignKey: foreignColumns.has(column.id) }))
    }))
    managedRelations.value = (relations.items || []).map(item => relationView(item, tables.items || []))
    managedMetrics.value = metrics.items || []
  } catch (error) {
    // 全局 toast 已提示
  }
}

function openQuality (item = source.value, tab = 'validation') {
  if (!item) {
    return
  }
  sourceId.value = item.id
  sourceDrawerOpen.value = false
  qualityInitialTab.value = tab
  workspace.value = 'quality'
  loadSourceDetails(item.id)
}

function switchWorkspace (id) {
  if (id === 'quality') {
    qualityInitialTab.value = 'validation'
  }
  workspace.value = id
}

function useSource (item) {
  if (!item || item.enabled === false || item.status !== 'indexed') {
    return
  }
  sourceId.value = item.id
  sourceDrawerOpen.value = false
  workspace.value = 'query'
  loadSourceDetails(item.id)
  focusQuestion()
}

function openSourceDialog (item) {
  editingSource.value = item
  sourceDialogOpen.value = true
}

async function saveSource (values) {
  try {
    if (editingSource.value) {
      await updateDatasource(editingSource.value.id, values)
      ElMessage.success('数据源已更新')
    } else {
      const created = await createDatasource({ ...values, password: values.password })
      ElMessage.success('数据源已创建，下一步请扫描结构')
      sourceId.value = created.id
      sourceDialogOpen.value = false
      await loadAll()
      openQuality(created)
      return
    }
    sourceDialogOpen.value = false
    await loadAll()
  } catch (error) {
    // 全局 toast 已提示
  }
}

async function scanSource (item) {
  if (!item || busy.value) {
    return
  }
  busy.value = true
  sourceAction.value = 'scan'
  try {
    const result = await scanDatasource(item.id)
    const discovered = result?.summary?.valuesDiscovered || 0
    ElMessage.success(discovered
      ? `结构扫描完成，自动收录 ${discovered} 个低基数字段取值`
      : '结构扫描完成')
    await loadAll()
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    busy.value = false
    sourceAction.value = ''
  }
}

// 构建已改为队列任务：接口立即返回 QUEUED，真正的终态要轮询版本详情。
const BUILD_POLL_INTERVAL = 1500
const BUILD_POLL_TIMEOUT = 180000

async function waitForVersion (datasourceId, versionId) {
  const startedAt = Date.now()
  for (;;) {
    const version = await getVersion(datasourceId, versionId)
    if (['READY', 'FAILED', 'CANCELLED', 'ARCHIVED'].includes(version.status)) {
      return version
    }
    if (Date.now() - startedAt > BUILD_POLL_TIMEOUT) {
      throw new Error('构建超时，请到版本历史查看')
    }
    await new Promise(resolve => setTimeout(resolve, BUILD_POLL_INTERVAL))
  }
}

async function buildVersion (item = source.value) {
  if (!item || busy.value) {
    return
  }
  busy.value = true
  sourceAction.value = 'index'
  try {
    const created = await createVersion(item.id)
    const versionId = created.versionId || created.version_id || created.version?.id
    if (!versionId) {
      throw new Error('版本创建失败')
    }
    const result = await buildVersionApi(item.id, versionId)
    const final = result.status === 'QUEUED'
      ? await waitForVersion(item.id, versionId)
      : result
    if (final.status === 'READY') {
      ElMessage.success(`v${created.revision || item.revision || 1} 已构建，请核对后发布`)
    } else {
      ElMessage.warning('版本构建未完成，请查看失败信息')
    }
    await loadAll()
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    busy.value = false
    sourceAction.value = ''
  }
}

async function publishLatest () {
  if (!source.value || busy.value) {
    return
  }
  const version = latestReady.value
  if (!version || version.revision !== (source.value.revision || 1)) {
    ElMessage.warning('没有与当前配置匹配的 READY 版本，请先构建')
    return
  }
  busy.value = true
  try {
    await publishVersion(source.value.id, version.id, source.value.revision || 1)
    ElMessage.success(`已发布版本 v${version.revision}，新查询将使用该版本`)
    await loadAll()
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    busy.value = false
  }
}

async function openPreparation (step = 0, item = source.value) {
  if (!item) {
    return
  }
  preparationSourceId.value = item.id
  preparationOrigin.value = workspace.value === 'sources' ? 'sources' : 'query'
  sourceDrawerOpen.value = false
  preparationStep.value = step
  if (item.id !== sourceId.value) {
    managedSourceId.value = item.id
    await loadManagedDetails(item.id)
  }
  prepareOpen.value = true
}

async function prepareData (values) {
  if (!preparationSource.value || busy.value) {
    return
  }
  busy.value = true
  sourceAction.value = 'prepare'
  prepareStage.value = 0
  try {
    const selected = new Set(values.selectedTables || [])
    for (const table of preparationTables.value) {
      const description = values.semantics?.tableDescriptions?.[table.name]
      await updateTable(preparationSource.value.id, table.id, {
        enabled: selected.has(table.name),
        ...(description ? { businessDescription: description } : {})
      })
    }
    for (const column of values.columns || []) {
      await updateColumn(preparationSource.value.id, column.id, {
        enabled: column.enabled,
        businessDescription: column.businessDescription
      })
    }
    // 取值只为「已启用表 + 已启用列」收集，选完表要再扫一次，
    // 新纳入查询范围的字典值才会进目录和版本快照。
    await scanDatasource(preparationSource.value.id)
    prepareStage.value = 1
    const created = await createVersion(preparationSource.value.id)
    prepareStage.value = 2
    const versionId = created.versionId || created.version_id || created.version?.id
    if (!versionId) {
      throw new Error('版本创建失败')
    }
    const built = await buildVersionApi(preparationSource.value.id, versionId)
    const finalBuilt = built.status === 'QUEUED'
      ? await waitForVersion(preparationSource.value.id, versionId)
      : built
    if (finalBuilt.status === 'READY') {
      ElMessage.success(`配置已冻结为 v${created.revision || preparationSource.value.revision || 1}，请核对后发布`)
    } else {
      ElMessage.warning('版本已创建，但构建未完成，请在版本历史中查看')
    }
    prepareOpen.value = false
    prepareStage.value = 0
    sourceId.value = preparationSource.value.id
    workspace.value = 'quality'
    await loadAll()
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    busy.value = false
    sourceAction.value = ''
    prepareStage.value = 0
  }
}

async function toggleSource (item) {
  try {
    await updateDatasource(item.id, { enabled: item.enabled === false })
    ElMessage.success(item.enabled === false ? '数据源已启用' : '数据源已停用，历史结果仍可查看')
    await loadAll()
  } catch (error) {
    // 全局 toast 已提示
  }
}

async function deleteSource (item) {
  if (!item || sources.value.length < 2 || busy.value) {
    return
  }
  try {
    await ElMessageBox.confirm(`删除数据源“${item.name}”？历史运行快照仍会保留，常用查询需重新绑定。`, '删除数据源', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
    await deleteDatasource(item.id)
    sourceDrawerOpen.value = false
    managedSourceId.value = ''
    ElMessage.success('数据源已删除')
    await loadAll()
  } catch (error) {
    // 用户取消或请求失败
  }
}

function openFavorite (item = null) {
  favoriteError.value = ''
  Object.assign(favoriteDraft, {
    id: item?.id || '',
    name: item?.name || (item?.question ? exampleList.value.find(example => example.question === item.question)?.title || '常用查询' : ''),
    question: item?.question || question.value,
    datasourceId: item?.datasourceId || item?.datasource_id || sourceId.value,
    datePolicy: item?.datePolicy || item?.date_policy || datePolicy.value,
    fixedTimeRange: item?.fixedTimeRange || null,
    notes: item?.notes || ''
  })
  favoriteOpen.value = true
}

async function saveFavorite () {
  if (!favoriteDraft.name.trim() || !favoriteDraft.question.trim() || !favoriteDraft.datasourceId) {
    favoriteError.value = '请填写名称、问题并选择可用的数据源。'
    return
  }
  if (favorites.value.some(item => item.id !== favoriteDraft.id && item.name === favoriteDraft.name.trim() && item.datasourceId === favoriteDraft.datasourceId)) {
    favoriteError.value = '当前数据源下已存在同名常用查询，请换一个名称。'
    return
  }
  busy.value = true
  try {
    if (favoriteDraft.datePolicy === 'fixed' && !favoriteFixedRange.value) {
      favoriteError.value = '固定日期策略需要先选择一个日期范围。'
      busy.value = false
      return
    }
    const payload = {
      name: favoriteDraft.name.trim(),
      question: favoriteDraft.question.trim(),
      datasourceId: favoriteDraft.datasourceId,
      datePolicy: favoriteDraft.datePolicy,
      fixedTimeRange: favoriteDraft.datePolicy === 'fixed' ? favoriteFixedRange.value : null,
      notes: favoriteDraft.notes,
      parameters: {}
    }
    if (favoriteDraft.id) {
      await updateFavorite(favoriteDraft.id, payload)
      ElMessage.success('常用查询已更新')
    } else {
      await createFavorite(payload)
      ElMessage.success('常用查询已保存')
    }
    favoriteOpen.value = false
    favorites.value = (await listFavorites()).items || []
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    busy.value = false
  }
}

async function removeFavorite (item) {
  try {
    await ElMessageBox.confirm(`删除常用查询“${item.name}”？运行历史会保留。`, '删除常用查询', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
    await deleteFavorite(item.id)
    favorites.value = favorites.value.filter(row => row.id !== item.id)
  } catch (error) {
    // 用户取消或请求失败
  }
}

async function runFavorite (item) {
  const selected = sources.value.find(source => source.id === item.datasourceId)
  if (!selected || selected.enabled === false) {
    ElMessage.warning('请先编辑常用查询，绑定可用的数据源')
    return
  }
  sourceId.value = item.datasourceId
  question.value = item.question
  datePolicy.value = item.datePolicy || 'relative'
  fixedRange.value = item.fixedTimeRange ? [item.fixedTimeRange.start, item.fixedTimeRange.endExclusive] : null
  workspace.value = 'query'
  viewingHistory.value = false
  await loadSourceDetails(item.datasourceId)
  await run()
}

function openFeedback (category) {
  if (!response.value?.id) {
    return
  }
  if (category === 'helpful') {
    submitHelpful('helpful')
    return
  }
  feedbackDraft.category = category
  feedbackDraft.notes = ''
  feedbackOpen.value = true
}

async function submitHelpful (category) {
  busy.value = true
  try {
    await createFeedback(response.value.id, { category, helpful: true })
    ElMessage.success('感谢反馈')
    await loadSourceDetails(sourceId.value)
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    busy.value = false
  }
}

async function saveFeedback () {
  if (!response.value?.id || !feedbackDraft.notes.trim()) {
    return
  }
  busy.value = true
  try {
    await createFeedback(response.value.id, { category: feedbackDraft.category, notes: feedbackDraft.notes.trim() })
    feedbackOpen.value = false
    ElMessage.success('反馈已记录，可在「验证与反馈」中查看')
    await loadSourceDetails(sourceId.value)
  } catch (error) {
    // 全局 toast 已提示
  } finally {
    busy.value = false
  }
}

async function addValue (payload) {
  try {
    await createValue(sourceId.value, payload)
    ElMessage.success('枚举值已添加，请构建并发布新版本')
    await loadAll()
  } catch (error) {
    // 全局 toast 已提示
  }
}

async function editValue (item, payload) {
  try {
    await updateValue(sourceId.value, item.id, payload)
    ElMessage.success('枚举值已更新，请构建并发布新版本')
    await loadAll()
  } catch (error) {
    // 全局 toast 已提示
  }
}

async function removeValue (item) {
  try {
    await ElMessageBox.confirm(`删除枚举值“${item.rawValue}”？删除后不再参与新版本，历史版本仍保留引用。`, '删除枚举值', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
    await deleteValue(sourceId.value, item.id)
    ElMessage.success('枚举值已移除，构建并发布新版本后生效')
    await loadAll()
  } catch (error) {
    // 用户取消或请求失败
  }
}

async function addMetric (payload) {
  try {
    await createMetric(sourceId.value, payload)
    ElMessage.success('指标已添加，请构建并发布新版本')
    await loadAll()
  } catch (error) {
    // 全局 toast 已提示
  }
}

async function removeMetric (item) {
  try {
    await ElMessageBox.confirm(`删除指标“${item.businessName}”？`, '删除指标', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
    await deleteMetric(sourceId.value, item.id)
    ElMessage.success('指标已删除，请构建并发布新版本')
    await loadAll()
  } catch (error) {
    // 用户取消或请求失败
  }
}

async function changeMetricStatus ({ metric, status }) {
  try {
    await setMetricStatus(sourceId.value, metric.id, status)
    ElMessage.success(status === 'APPROVED' ? '指标已审核通过' : '指标已停用')
    await loadAll()
  } catch (error) {
    // 全局 toast 已提示
  }
}

async function cleanupOldVersions () {
  try {
    await ElMessageBox.confirm(
      '保留最近 3 个就绪版本，其余归档并回收知识。活动版本与被查询历史引用的版本不会被清理。',
      '清理旧版本', { type: 'warning', confirmButtonText: '开始清理', cancelButtonText: '取消' })
    const result = await cleanupVersions(sourceId.value, 3)
    ElMessage.success(result.archived
      ? `已归档 ${result.archived} 个版本，回收 ${result.purgedKnowledge || 0} 条知识`
      : '没有可归档的版本')
    await loadAll()
  } catch (error) {
    // 用户取消或请求失败
  }
}

let draftTimer = null
async function persistWorkspace () {
  try {
    await saveWorkspace({
      datasourceId: sourceId.value || null,
      questionDraft: question.value,
      sqlDraft: '',
      preferences: { datePolicy: datePolicy.value, guideDismissed: guideDismissed.value }
    })
    saveState.value = 'saved'
  } catch (error) {
    saveState.value = 'error'
  }
}
watch([question, datePolicy, sourceId], () => {
  window.clearTimeout(draftTimer)
  draftTimer = window.setTimeout(persistWorkspace, 800)
})
watch(showTechnical, value => {
  if (!value && ['plan', 'debug'].includes(activeTab.value)) {
    activeTab.value = 'result'
  }
})
watch(sourceId, () => {
  viewingHistory.value = false
  activeTab.value = 'result'
})

onMounted(async () => {
  await loadAll()
  try {
    const saved = await getWorkspace()
    if (saved?.questionDraft && !question.value) {
      question.value = saved.questionDraft
    }
    if (saved?.preferences?.datePolicy) {
      datePolicy.value = saved.preferences.datePolicy
    }
    guideDismissed.value = Boolean(saved?.preferences?.guideDismissed)
    if (saved?.datasourceId && sources.value.some(item => item.id === saved.datasourceId)) {
      sourceId.value = saved.datasourceId
      await loadSourceDetails(sourceId.value)
    }
  } catch (error) {
    // 工作台草稿读取失败不阻塞页面
  }
})

onBeforeUnmount(() => {
  window.clearTimeout(draftTimer)
  stopElapsed()
})
</script>

<!-- 页面样式集中在外部文件，保持单一 scoped 样式块：外部样式按块索引解析，多块会错位。 -->
<style scoped src="../../features/text2sql/styles/text2sql.css"></style>
