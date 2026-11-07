<template>
  <!--
    连接测试结果表（列表行的结果弹窗 / 新建·编辑向导共用）——`ModelTestResult`
    只在这里有一份渲染实现，两个入口不再各写一套文案行、慢慢漂移。
    行序固定：连接状态 → [真实调用] → [端点声明的模型] → [实测向量维度] → 耗时。
    「真实调用」行对 LLM（`chatOk`）、rerank（`rerankOk`）、embedding（`embeddingsOk`）出现：
    清单里有名字不代表能推理，rerank 端点通常压根没有 `/models`，embedding 的判据是维度实测，
    只有真调一次才能判断通没通。
    「端点声明的模型」行只有 LLM 有（embedding / rerank 的端点不保证提供 `/models`，
    后端也不探测），其余类型直接不出这一行。
  -->
  <el-table :data="rows" size="small" class="model-test-result">
    <el-table-column prop="label" :label="$t('modules.modelManagement.testResultItem')" />
    <el-table-column :label="$t('modules.modelManagement.testResultValue')">
      <template #default="{ row }">
        <!-- 状态这行用 tag 的颜色承担「一眼分辨」：绿=到达 / 黄=清单说不准 / 红=不可达 -->
        <el-tag v-if="row.tagType" :type="row.tagType" size="small">
          {{ row.value }}
        </el-tag>
        <span v-else>{{ row.value }}</span>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup lang="ts">
import { computed, getCurrentInstance } from 'vue'
import type { ModelTestResult } from './type'

const props = defineProps({
  result: { type: Object as () => ModelTestResult, required: true },
  /** 登记的向量维度（编辑态表单 / 列表行）—— 只在实测与登记不一致时用来写「登记 X」 */
  registeredDimension: { type: Number, default: null },
  /** 被测行的类型：只有 LLM 探测「端点声明的模型」，embedding / rerank 不出那一行 */
  kind: { type: String, default: '' }
})

const { proxy } = getCurrentInstance() as any

/**
 * 状态文案。LLM / rerank / embedding 都以**真实调用**为准
 * （`chatOk` / `rerankOk` / `embeddingsOk` 是布尔值）：
 * 调通 → 绿；调不通 → 红「模型调用失败」（此时端点其实可达，别写成「端点不可达」）。
 * 只有后端没给这些字段（旧响应）时才回落到 `ok` / `probed` 的旧语义。
 */
const status = computed(() => {
  if (props.result.chatOk === true || props.result.rerankOk === true
    || props.result.embeddingsOk === true) {
    return { text: proxy.$t('modules.modelManagement.testCallSuccess'), tagType: 'success' }
  }
  if (props.result.chatOk === false || props.result.rerankOk === false
    || props.result.embeddingsOk === false) {
    return { text: proxy.$t('modules.modelManagement.testCallFailed'), tagType: 'danger' }
  }
  if (props.result.ok) {
    return { text: proxy.$t('modules.modelManagement.testSuccess'), tagType: 'success' }
  }
  if (props.result.probed === null) {
    return { text: proxy.$t('modules.modelManagement.testPartial'), tagType: 'warning' }
  }
  return { text: proxy.$t('modules.modelManagement.testFailed'), tagType: 'danger' }
})

/** 维度行只在真打了一次最小调用（实测到维度）时出现；显式 null 与字段缺省都按「没有」处理 */
const hasDimension = computed(() => props.result.dimension !== null && props.result.dimension !== undefined)

/** 值 = 实测维度（+ 后端算好的匹配结论）；匹配结论只在后端给了 `dimensionMatches` 时缀上 */
const dimensionText = computed(() => {
  if (!hasDimension.value) {
    return ''
  }
  const { dimension, dimensionMatches } = props.result
  if (dimensionMatches === false) {
    return `${dimension}（${proxy.$t('modules.modelManagement.testResultDimensionMismatch', [props.registeredDimension])}）`
  }
  if (dimensionMatches) {
    return `${dimension}（${proxy.$t('modules.modelManagement.testResultDimensionOk')}）`
  }
  return `${dimension}`
})

const rows = computed(() => {
  const result = props.result
  const list: Array<{ label: string, value: string, tagType?: string }> = [
    {
      label: proxy.$t('modules.modelManagement.testResultStatus'),
      value: status.value.text,
      tagType: status.value.tagType
    }
  ]
  // 真实调用行把失败原因（HTTP 状态 + 端点错误 / 实际请求的 URL）原样摊开，
  // 否则「模型调用失败」只剩一句结论，排查时还要去翻服务端日志。
  const called = result.chatOk === true || result.chatOk === false
    || result.rerankOk === true || result.rerankOk === false
    || result.embeddingsOk === true || result.embeddingsOk === false
  if (called) {
    const failed = result.chatOk === false || result.rerankOk === false
      || result.embeddingsOk === false
    const error = result.chatOk === false
      ? result.chatError
      : (result.rerankOk === false ? result.rerankError : result.embeddingsError)
    list.push({
      label: proxy.$t('modules.modelManagement.testResultCall'),
      value: failed
        ? (error || proxy.$t('modules.modelManagement.testCallFailed'))
        : proxy.$t('modules.modelManagement.testResultCallSucceeded')
    })
  }
  // 只有 LLM 有「端点声明的模型」这条能力（见后端 DEFAULT_PATHS）：embedding 的判据是
  // 维度实测、rerank 的是重排调用。对这两类硬写一行「无法判定」会让人以为端点有问题。
  if (props.kind !== 'rerank' && props.kind !== 'embedding') {
    list.push({
      label: proxy.$t('modules.modelManagement.testResultModels'),
      value: result.models?.length
        ? result.models.join('、')
        : proxy.$t('modules.modelManagement.testResultUndetermined')
    })
  }
  if (hasDimension.value) {
    list.push({ label: proxy.$t('modules.modelManagement.testResultDimension'), value: dimensionText.value })
  }
  list.push({ label: proxy.$t('modules.modelManagement.testResultLatency'), value: `${result.latencyMs}ms` })
  return list
})
</script>
