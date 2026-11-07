<!--
  参考项目 components/AppSidebar.vue 的落位。

  真实工程的侧栏实现保留在 `components/nav/LeftNav.vue`（含导航、语言/主题、
  折叠、权限与门户逻辑）；这里提供参考项目命名的入口，App 外壳改用它。
-->
<template>
  <LeftNav />
</template>

<script setup>
import LeftNav from '@/app/layout/nav/LeftNav.vue'
</script>
