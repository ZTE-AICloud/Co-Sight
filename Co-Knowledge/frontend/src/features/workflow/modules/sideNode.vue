<template>
  <div :class="['side-node', `side-node--${sideNodeId}`]">
    <template v-if="sideNodeId==='preretriever'">
      <img width="24px" src="@/assets/LLMs.svg">
    </template>
    <template v-if="sideNodeId==='retriever'">
      <img width="24px" src="@/assets/branch.svg">
    </template>
    <template v-if="sideNodeId==='postretriever'">
      <img width="24px" src="@/assets/knowledge.svg">
    </template>
    <template v-if="sideNodeId==='responsesynthesizer'">
      <img width="24px" src="@/assets/response.svg">
    </template>
    <div class="node-content">
      {{ sideNodeName }}
    </div>
  </div>
</template>
<script setup lang="ts">
defineProps({
  sideNodeId: {
    type: String,
    default: ''
  },
  sideNodeName: {
    type: String,
    default: ''
  },
})
</script>
<style lang="less" scoped>
/* 左侧节点栏与画布卡片同一套皮肤：白卡 / 1px 浅描边 / 10px 圆角 / 紧凑排版 */
.side-node {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 40px;
  padding: 0 10px;
  background: var(--rs-bg-card, #ffffff);
  border: 1px solid var(--rs-border, #e5ebf4);
  border-radius: 10px;
  box-shadow: 0 4px 14px #19264c06;
  cursor: grab;

  &:hover {
    border-color: var(--rs-primary-border, #a4c8ff);
    box-shadow: 0 6px 16px #19264c10;
  }

  img {
    box-sizing: border-box;
    width: 26px;
    height: 26px;
    margin: 0;
    padding: 5px;
    flex: 0 0 26px;
    border-radius: 7px;
    background: var(--tint, var(--rs-tint-blue, #edf5ff));
    object-fit: contain;
  }
}
.side-node--preretriever {
  --tone: var(--rs-tone-purple, #8045ff);
  --tint: var(--rs-tint-purple, #f4eeff);
}
.side-node--retriever {
  --tone: var(--rs-tone-orange, #ff8619);
  --tint: var(--rs-tint-orange, #fff3e8);
}
.side-node--postretriever {
  --tone: var(--rs-tone-blue, #1677ff);
  --tint: var(--rs-tint-blue, #edf5ff);
}
.side-node--responsesynthesizer {
  --tone: var(--rs-tone-green, #09aa57);
  --tint: var(--rs-tint-green, #eaf9ef);
}
.node-content {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 500;
  color: var(--rs-text-2, #536383);
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
