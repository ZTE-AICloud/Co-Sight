<!--
  区块标题。

  Element Plus 没有 Title 组件。这里按调用契约补最小实现：
  `level` 决定标题层级（渲染成 h{level}），`type="vertical"` 在左侧加一根竖条。
  调用方：图谱知识库的表单（`:level="2" type="vertical"`）。

  尺寸:
    font-size 12px / font-weight 700 / line-height 22px / color rgb(51,51,51) / margin 0
  竖条来自 `::before` 的 `content:''` + `border-left: 3px solid rgb(25,147,255)`
  （不是背景色的方块，也没有圆角/右边距）。间距由各页 form 自己的 margin 提供。
-->
<template>
  <component
    :is="`h${level}`"
    class="section-title"
    :class="{ 'section-title--vertical': type === 'vertical' }"
  >
    <slot />
  </component>
</template>

<script setup lang="ts">
defineProps({
  /** 标题层级，渲染成 `h{level}` */
  level: { type: Number, default: 2 },
  /** `vertical` = 标题左侧带竖条 */
  type: { type: String, default: '' }
})
</script>

<style lang="less" scoped>
.section-title {
  display: block;
  margin: 0;                 // 线上 margin 0；标题与下方内容的 8px 间距来自各页 form 的 margin
  font-size: 12px;
  font-weight: 700;
  line-height: 22px;
  color: var(--rs-text-primary);

  &--vertical::before {
    content: '';
    display: inline;         // 线上是行内元素 + 左边框，高度随字号（≈14px），不是固定 16px
    border-left: 3px solid var(--el-color-primary);
  }
}
</style>
