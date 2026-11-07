<template>
  <CardFrame
    :title="title"
    :label="nodeInfo.label || 'RESPONSE'"
    :tip="nodeInfo.label || 'RESPONSE'"
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
      <Flag />
    </template>
  </CardFrame>
</template>

<script setup>
import CardFrame from './CardFrame.vue'
import { Flag } from '@/shared/lib/icons'
import { RESPONSE_NODE_SHAPE } from '@/features/workflow/lib/workflow'
import { useFlowNodeCard } from './useFlowNodeCard'

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
  componentType: RESPONSE_NODE_SHAPE,
  moduleTitleKey: 'ragFlow.end',
  defaultVariables: null
})

bindEmits({
  edit: (info, id) => emit('editCardHandle', info, id),
  init: info => emit('initCardHandle', info),
  delete: id => emit('deleteCardHandle', id)
})
</script>
