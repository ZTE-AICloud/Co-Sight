<!--
  路由加载进度条。

  懒加载路由在下载 chunk 期间没有任何界面反馈，窄带链路上表现为「点了没反应」。
  这里在导航开始 120ms 后显示一条顶部进度条（见 `@/shared/lib/route-progress`）。

  只动 `transform`，走合成层，不触发布局；`prefers-reduced-motion` 下退化为静止
  的一条实心条，仍然表示「正在加载」。
-->
<template>
  <div
    v-if="isRoutePending"
    class="route-progress"
    role="progressbar"
    :aria-label="$t('public.routeLoading')"
  >
    <span class="route-progress__bar" />
  </div>
</template>

<script setup>
import { isRoutePending } from '@/shared/lib/route-progress'
</script>

<style scoped>
.route-progress {
  position: fixed;
  inset: 0 0 auto 0;
  height: 2px;
  overflow: hidden;
  /* 盖在 Element Plus 的遮罩/弹层之上：导航期间它必须可见 */
  z-index: 4000;
  pointer-events: none;
}

.route-progress__bar {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 40%;
  background: var(--rs-primary);
  will-change: transform;
  animation: route-progress-slide 1.1s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}

@keyframes route-progress-slide {
  from {
    transform: translateX(-100%);
  }

  to {
    transform: translateX(350%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .route-progress__bar {
    width: 100%;
    animation: none;
  }
}
</style>
