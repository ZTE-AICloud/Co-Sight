<template>
  <CardFrame
    :title="title"
    :label="nodeInfo.label"
    :tip="nodeInfo.label"
    :theme="tone"
    :fixed="fixed"
    :operators="operators"
    :inputs="inputs"
    :output-field="outputField"
    :source-summary="sourceSummary"
    :fixed-direction="fixedDirection"
    :fixed-field="fixedField"
    @editCardHandle="editCardHandle"
    @deleteCardHandle="deleteCardHandle"
  >
    <template #icon>
      <ChatDotRound />
    </template>
  </CardFrame>
</template>

<script setup>
import CardFrame from '../CardFrame.vue'
import { ChatDotRound } from '@/shared/lib/icons'
import { ComponentEnum } from '@/features/workflow/types'
import { useFlowNodeCard } from '../useFlowNodeCard'
import { createDefaultVariables } from '../flowNodeDefaults'

const emit = defineEmits(['editCardHandle', 'initCardHandle', 'deleteCardHandle'])

const {
  nodeInfo,
  title,
  tone,
  fixed,
  operators,
  inputs,
  outputField,
  fixedDirection,
  fixedField,
  sourceSummary,
  editCardHandle,
  deleteCardHandle,
  bindEmits
} = useFlowNodeCard({
  componentType: ComponentEnum.RESPONSE_SYNTHESIZER,
  moduleTitleKey: 'ragFlow.responsesynthesizerTitle',
  defaultVariables: createDefaultVariables(ComponentEnum.RESPONSE_SYNTHESIZER)
})

bindEmits({
  edit: (info, id) => emit('editCardHandle', info, id),
  init: info => emit('initCardHandle', info),
  delete: id => emit('deleteCardHandle', id)
})
</script>
