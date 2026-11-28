<!--
  应用外壳。

  外壳结构：
    <div class="app-shell">
      <AppSidebar />
      <main class="main-shell"><router-view /></main>
    </div>

  `.page` 自己是滚动容器；不再使用 el-container/el-main/.content-router-box，
  也不在壳层加 padding/背景/overflow。侧栏显隐仍由路由 meta.hideNav 控制。

  版本更新提醒挂在壳层：只有进入业务页（而不是登录/改密）才会评估；
  有本地账号会话时读「该账号当前版本是否已确认」，未确认则弹一次。
-->
<template>
  <div class="app-shell">
    <AppSidebar v-if="showNav" />
    <main class="main-shell">
      <router-view />
    </main>
    <ReleaseNotice />
  </div>
</template>
<script>
import AppSidebar from '@/app/layout/AppSidebar.vue';
import ReleaseNotice from '@/features/release/ReleaseNotice.vue'
import { getUnreadReleaseNotice, releaseNotice } from '@/shared/composables/releaseNotice'
import { currentUser } from '@/features/auth/session'

export default {
  components: { AppSidebar, ReleaseNotice },
  computed: {
    // 左侧导航。用路由 meta 表达「本页要不要左栏」，声明式，深链接/硬刷新正确。
    showNav () {
      return !this.$route.meta.hideNav;
    }
  },
  async mounted () {
    // 无认证 / 网关模式没有本地账号（`/auth/status` 的 user 为 null），不弹提示；
    // 版本历史仍可从左栏「版本更新」进入。
    const account = currentUser.value?.username
    if (!account) {
      return
    }
    releaseNotice.value = await getUnreadReleaseNotice(account)
  }
};
</script>
