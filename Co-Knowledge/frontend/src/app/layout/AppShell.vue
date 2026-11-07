<!--
  应用外壳。

  外壳结构：
    <div class="app-shell">
      <AppSidebar />
      <main class="main-shell"><router-view /></main>
    </div>

  `.page` 自己是滚动容器；不再使用 el-container/el-main/.content-router-box，
  也不在壳层加 padding/背景/overflow。侧栏显隐仍由路由 meta.hideNav 控制。
-->
<template>
  <div class="app-shell">
    <AppSidebar v-if="showNav" />
    <main class="main-shell">
      <router-view />
    </main>
  </div>
</template>
<script>
import AppSidebar from '@/app/layout/AppSidebar.vue';

export default {
  components: { AppSidebar },
  computed: {
    // 左侧导航。用路由 meta 表达「本页要不要左栏」，声明式，深链接/硬刷新正确。
    showNav () {
      return !this.$route.meta.hideNav;
    }
  }
};
</script>
