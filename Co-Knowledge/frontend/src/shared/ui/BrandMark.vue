<!-- 公司标识（ZTE 标准 LOGO，蓝底反白方形版；与 public/index.html 的浏览器图标共用）。 -->
<template>
  <img class="brand-mark" :src="brandIcon" alt="" aria-hidden="true" width="200" height="200" draggable="false">
</template>

<script setup>
// 与 public/index.html 的浏览器图标共用同一份资源；拼 BASE_URL 以兼容子路径部署。
// BASE_URL 可能不带结尾斜杠（vue.config.js 的 publicBase 也做同样归一化）。
const brandBase = String(process.env.BASE_URL || '/').replace(/\/?$/, '/')
const brandIcon = `${brandBase}brand/zte-mark.svg`
</script>

<style scoped>
/* 方形版自带蓝底；圆角只裁切图标外框，不影响内部 LOGO。 */
.brand-mark{display:block;flex-shrink:0;object-fit:contain;aspect-ratio:1;border-radius:6px}
</style>
