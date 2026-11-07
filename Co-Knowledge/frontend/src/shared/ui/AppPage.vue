<!--
  页面容器。

  页面根节点是 `.page`：
    <div class="page management-page ...">
      <div class="page-inner">...</div>
    </div>

  `.page` 的滚动、内距、背景和响应式规则全部来自
  `src/styles/base.css` / `management.css`，组件不再写样式。
  父组件传入的 class 会自动合并到根节点（Vue 单根透传）。

  页面统一由 `.page` 整页滚动。
-->
<template>
  <section class="page">
    <slot />
  </section>
</template>

<script setup>
defineProps({})
</script>
