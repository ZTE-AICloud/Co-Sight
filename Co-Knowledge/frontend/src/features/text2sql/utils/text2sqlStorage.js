import { demoDatasource, exampleQuestions, demoScenarios } from '../demo-data/text2sql.js'
import { createDemoResponse } from './text2sql.js'
import { clone, effectiveSemantics } from './text2sqlWorkspace.js'
import { sourceTableNames } from '../demo-data/text2sqlScale.js'
import { normalizeDatePolicy } from './text2sqlFlow.js'
import { configurationBinding } from './text2sqlExperience.js'

// Keep the original key so existing browser data migrates without user intervention.
export const TEXT2SQL_STORAGE_KEY = 'co-knowledge-text2sql-v1'
const scenarios = new Set(demoScenarios.map(item => item.id))
const validSource = item => item && ['id', 'name', 'host', 'database', 'schema', 'username'].every(key => typeof item[key] === 'string' && item[key].trim()) &&
  Number.isInteger(item.port) && item.port >= 1 && item.port <= 65535 && ['configured', 'scanned', 'indexed'].includes(item.status)
const string = (value, max = 1000) => (typeof value === 'string' ? value.slice(0, max) : '')
export function cleanSource (item) {
  const value = { ...Object.fromEntries(['id', 'name', 'host', 'database', 'schema', 'username', 'scannedAt', 'indexedAt'].map(key => [key, string(item[key])])),
    port: item.port, type: 'PostgreSQL', status: item.status, passwordConfigured: !!item.passwordConfigured }
  if (item.catalog === 'commerce50') {
    value.catalog = 'commerce50'
  }
  const tableNames = sourceTableNames(value)
  if (Array.isArray(item.selectedTables)) {
    value.selectedTables = [...new Set(item.selectedTables.filter(name => tableNames.includes(name)))]
  }
  if (typeof item.enabled === 'boolean') {
    value.enabled = item.enabled
  }
  if (Number.isInteger(item.revision)) {
    value.revision = item.revision
  }
  if (item.connectionTestedAt) {
    value.connectionTestedAt = string(item.connectionTestedAt)
  }
  if (item.topic) {
    value.topic = { name: string(item.topic.name, 60), description: string(item.topic.description, 200), owner: string(item.topic.owner, 60) }
  }
  if (item.requiresPublication === true) {
    value.requiresPublication = true
  }
  if (item.semantics) {
    const semantics = effectiveSemantics({ ...value, semantics: item.semantics })
    value.semantics = { amountName: string(semantics.amountName, 60), userName: string(semantics.userName, 60), notes: string(semantics.notes),
      tableDescriptions: Object.fromEntries(tableNames.map(name => [name, string(semantics.tableDescriptions[name], 200)])) }
  }
  const binding = configurationBinding(value)
  if (item.qualityReport && Array.isArray(item.qualityReport.cases)) {
    value.qualityReport = {
      binding: item.qualityReport.binding === binding ? binding : '', revision: Number.isInteger(item.qualityReport.revision) ? item.qualityReport.revision : 1,
      checkedAt: string(item.qualityReport.checkedAt, 40), referenceDate: string(item.qualityReport.referenceDate, 20),
      answerable: Number.isInteger(item.qualityReport.answerable) ? Math.max(0, Math.min(6, item.qualityReport.answerable)) : 0,
      cases: item.qualityReport.cases.slice(0, 12).filter(item => item && typeof item.id === 'string')
        .map(item => ({
          id: string(item.id, 60), question: string(item.question, 200), kind: ['answer', 'boundary', 'paraphrase'].includes(item.kind) ? item.kind : 'boundary',
          passed: item.passed === true, available: item.available === true, detail: string(item.detail, 200)
        }))
    }
  }
  if (item.publication) {
    value.publication = { binding: item.publication.binding === binding ? binding : '',
      revision: Number.isInteger(item.publication.revision) ? item.publication.revision : 1,
      checkedAt: string(item.publication.checkedAt, 40), publishedAt: string(item.publication.publishedAt, 40) }
  }
  return value
}
const defaults = () => ({ sources: [{ ...demoDatasource }], sourceId: demoDatasource.id, question: exampleQuestions[2].question,
  scenario: 'auto', activeTab: 'result', workspace: 'query', history: [], response: null, lastAttempt: null, favorites: [], feedback: [], queryDatePolicy: 'relative', guideDismissed: false, viewingHistory: false })
const responseFields = ['demo', 'reference_date', 'request_id', 'datasource_id', 'datasource_name', 'question', 'scenario', 'retrieval', 'sql', 'validation', 'explain', 'result', 'error', 'timing', 'usage', 'stages', 'createdAt', 'intent', 'explanation', 'legacyReconstructed']
function validResponse (value) {
  const list = (items, check) => Array.isArray(items) && items.every(item => item && check(item))
  const fields = (item, keys) => keys.every(key => typeof item[key] === 'string')
  const result = value?.result
  return value?.demo === true && typeof value.request_id === 'string' && typeof value.question === 'string' && validSource(value.source) &&
    scenarios.has(value.scenario) && Number.isFinite(value.timing?.total_ms) && value.timing.total_ms >= 0 && typeof value.sql?.generated === 'string' && typeof value.sql?.final === 'string' &&
    list(value.retrieval?.tables, item => fields(item, ['name', 'description', 'source']) && (item.source === 'relation' || Number.isFinite(item.score))) &&
    list(value.retrieval?.columns, item => fields(item, ['table', 'name', 'description', 'type'])) &&
    list(value.retrieval?.relations, item => fields(item, ['from_table', 'from_column', 'to_table', 'to_column'])) &&
    list(value.retrieval?.values, item => fields(item, ['table', 'column', 'label'])) &&
    list(value.stages, item => fields(item, ['id', 'name', 'status']) && Number.isFinite(item.ms)) &&
    list(value.validation?.checks, item => fields(item, ['label', 'detail']) && typeof item.valid === 'boolean') &&
    (value.error === null || (value.error && fields(value.error, ['code', 'message', 'category', 'stage']))) &&
    (value.explain === null || (value.explain && Number.isFinite(value.explain.total_cost) && list(value.explain.nodes, item => fields(item, ['node', 'detail']) && Number.isFinite(item.rows) && Number.isFinite(item.cost)))) &&
    (result === null || (result && Array.isArray(result.columns) && result.columns.every(column => typeof column === 'string') && Number.isInteger(result.row_count) &&
      Array.isArray(result.rows) && result.rows.length <= 1000 && result.rows.every(row => Array.isArray(row) && row.length === result.columns.length && row.every(cell => cell === null || ['string', 'boolean'].includes(typeof cell) || (typeof cell === 'number' && Number.isFinite(cell))))))
}
export function responseSnapshot (item) {
  if (!validResponse(item)) {
    return null
  }
  const snapshot = Object.fromEntries(responseFields.filter(key => item[key] !== undefined).map(key => [key, clone(item[key])]))
  snapshot.source = cleanSource(item.source)
  return snapshot
}
function normalizeState (value) {
  const state = defaults()
  if (!value || ![1, 2].includes(value.version)) {
    return state
  }
  const ids = new Set()
  const sources = Array.isArray(value.sources) ? value.sources.filter(item => {
    if (!validSource(item) || ids.has(item.id)) {
      return false
    }
    ids.add(item.id); return true
  }).map(cleanSource) : []
  if (sources.length) {
    state.sources = sources
  }
  state.sourceId = state.sources.some(item => item.id === value.sourceId) ? value.sourceId : state.sources[0].id
  state.question = typeof value.question === 'string' ? value.question.slice(0, 1000) : state.question
  state.scenario = scenarios.has(value.scenario) ? value.scenario : 'auto'
  state.activeTab = ['result', 'explanation', 'sql', 'schema', 'plan', 'debug'].includes(value.activeTab) ? value.activeTab : 'result'
  state.workspace = ['query', 'sources', 'history', 'quality'].includes(value.workspace) ? value.workspace : 'query'
  state.qualitySourceId = state.sources.some(item => item.id === value.qualitySourceId) ? value.qualitySourceId : state.sourceId
  state.queryDatePolicy = ['relative', 'fixed', 'all'].includes(value.queryDatePolicy) ? value.queryDatePolicy : 'relative'
  state.guideDismissed = value.guideDismissed === true
  state.viewingHistory = value.viewingHistory === true
  if (Array.isArray(value.history)) {
    state.history = value.history.slice(0, 50).flatMap(item => {
      if (value.version === 2) {
        const snapshot = responseSnapshot(item)
        return snapshot ? [snapshot] : []
      }
      if (!item || !string(item.question).trim() || !scenarios.has(item.scenario) || typeof item.request_id !== 'string' || !validSource(item.source) ||
      !state.sources.some(source => source.id === item.source.id)) {
        return []
      }
      const source = cleanSource(item.source)
      // Version 1 stored replay inputs only. Reconstruct once and explicitly label that limitation.
      const response = createDemoResponse(item.question.slice(0, 1000), source, item.scenario)
      return [{ ...response, request_id: item.request_id, createdAt: typeof item.createdAt === 'string' && Number.isFinite(Date.parse(item.createdAt)) ? item.createdAt : '', source, legacyReconstructed: true }]
    })
  }
  const selected = value.version === 2 ? responseSnapshot(value.response) : state.history.find(item => item.request_id === value.responseId)
  state.response = selected || null
  state.lastAttempt = value.version === 2 ? responseSnapshot(value.lastAttempt) : null
  if (Array.isArray(value.favorites)) {
    state.favorites = value.favorites.slice(0, 100).flatMap(item => (item && typeof item.id === 'string' && string(item.name).trim() && string(item.question).trim() && typeof item.datasource_id === 'string' ? [{
      id: item.id, name: string(item.name, 80), question: string(item.question), datasource_id: item.datasource_id,
      intent: item.intent && exampleQuestions.some(example => example.id === item.intent.id) ? { id: item.intent.id, period: item.intent.id === 'monthly' && item.intent.period === 'all' ? 'all' : 'recent30', datePolicy: normalizeDatePolicy(item.intent.id === 'monthly' ? item.intent.period : 'recent30', item.intent.datePolicy) } : null,
      createdAt: string(item.createdAt), verified: item.verified === true, notes: string(item.notes)
    }] : []))
  }
  if (Array.isArray(value.feedback)) {
    state.feedback = value.feedback.slice(0, 100).flatMap(item => {
      if (!item || typeof item.request_id !== 'string' || !['helpful', 'meaning', 'sql', 'data'].includes(item.category)) {
        return []
      }
      const snapshot = [state.response, ...state.history].find(record => record?.request_id === item.request_id)
      return [{ id: string(item.id || `${item.request_id}-${item.category}`, 150), request_id: item.request_id, category: item.category,
        notes: string(item.notes), createdAt: string(item.createdAt), datasource_id: string(item.datasource_id || snapshot?.datasource_id),
        question: string(item.question || snapshot?.question), status: ['open', 'reviewing', 'resolved'].includes(item.status) ? item.status : 'open',
        intentId: exampleQuestions.some(example => example.id === (item.intentId || snapshot?.intent?.id)) ? item.intentId || snapshot?.intent?.id : '',
        resolution: string(item.resolution), updatedAt: string(item.updatedAt), resolvedRevision: Number.isInteger(item.resolvedRevision) ? item.resolvedRevision : null }]
    })
  }
  return state
}
export function readText2SQLState (storage) {
  try {
    return { ...normalizeState(JSON.parse((storage || window.localStorage).getItem(TEXT2SQL_STORAGE_KEY))), storageError: false }
  } catch {
    return { ...defaults(), storageError: true }
  }
}
export function saveText2SQLState (state, storage) {
  try {
    const value = { version: 2, sources: state.sources.map(cleanSource), sourceId: state.sourceId, question: state.question,
      scenario: state.scenario, activeTab: state.activeTab, workspace: state.workspace, qualitySourceId: state.qualitySourceId, response: responseSnapshot(state.response), lastAttempt: responseSnapshot(state.lastAttempt),
      history: state.history.slice(0, 50).map(responseSnapshot)
        .filter(Boolean), favorites: state.favorites || [], feedback: state.feedback || [], queryDatePolicy: state.queryDatePolicy, guideDismissed: state.guideDismissed, viewingHistory: state.viewingHistory }
    // Normalize user-created records and remove arbitrary properties before writing.
    const normalized = normalizeState(value)
    const payload = { version: 2, ...Object.fromEntries(Object.keys(value).filter(key => key !== 'version')
      .map(key => [key, normalized[key]])) }
    ;(storage || window.localStorage).setItem(TEXT2SQL_STORAGE_KEY, JSON.stringify(payload))
    return true
  } catch {
    return false
  }
}
