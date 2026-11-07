<!--
  页面标题区。
  结构与 class 必须保持现状（.page-title / .title-left / .title-icon / h1 / p），
  样式全部来自 src/styles/base.css 与 management.css，组件本身不再写样式。
-->
<template>
  <div class="page-title">
    <div class="title-left">
      <div v-if="icon || $slots.icon" class="title-icon">
        <slot name="icon">
          <component :is="icon" />
        </slot>
      </div>
      <div>
        <h1>
          <slot name="title">{{ title }}</slot>
        </h1>
        <p v-if="description || subtitle || $slots.description">
          <slot name="description">{{ description || subtitle }}</slot>
        </p>
      </div>
    </div>
    <slot name="actions" />
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  /** 参考项目 PageHeader 的命名；与 description 二选一 */
  subtitle: { type: String, default: '' },
  /** 标题左侧线性图标（Element Plus 图标组件或本地线性图标） */
  icon: { type: [Object, Function], default: null }
})
</script>
