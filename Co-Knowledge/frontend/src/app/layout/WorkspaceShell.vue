<!--
  参考项目 components/WorkspaceShell.vue。

  编排详情 / 图谱详情共用的全幅工作区外壳：面包屑、图标+标题、副标题、右侧操作、
  专注模式按钮与默认插槽。页面只需传标题/图标/返回路径，并把业务工具条与画布放进
  默认插槽。
-->
<template>
  <section class="workspace-page" :class="{ 'is-focused': focused }">
    <header class="workspace-header">
      <nav class="workspace-breadcrumb text-secondary" aria-label="页面路径">
        <RouterLink :to="back">
          <ArrowLeft />{{ parent }}
        </RouterLink>
        <ArrowRight />
        <span>{{ context }}</span>
      </nav>
      <div class="workspace-title-row">
        <div class="workspace-heading">
          <span class="workspace-icon"><component :is="icon" /></span>
          <div>
            <h1 :title="title">
              {{ title }}
            </h1>
            <div class="workspace-subtitle text-secondary">
              <slot name="subtitle" />
            </div>
          </div>
        </div>
        <div class="workspace-actions">
          <slot name="actions" />
          <!-- 0.1.11：详情页可用 focus-action 替换默认的专注模式按钮（图谱页改走沉浸画布）。
               0.1.12：showFocusAction=false 时连默认按钮也不渲染（图谱页只保留画布内入口）。 -->
          <slot v-if="showFocusAction" name="focus-action">
            <el-button
              class="button-compact"
              :aria-label="focused ? exitFocusText : focusText"
              :title="focused ? exitFocusText : focusText"
              @click="$emit('toggle-focus')"
            >
              <FullScreen />
            </el-button>
          </slot>
        </div>
      </div>
    </header>
    <div class="workspace-body">
      <slot />
    </div>
  </section>
</template>

<!--
  样式全部来自 `src/styles/workspaces.css`。
  不要在这里放 scoped 副本：写死的浅色回退值在深色主题下恒为浅色文字色（#0c1538），
  标题/面包屑在深底上不可见。这里用纯全局样式，并保留 `.workspace-body` 容器。
-->
<script setup>
import { ArrowLeft, ArrowRight, FullScreen } from '@/shared/lib/icons'

defineProps({
  back: { type: [String, Object], default: '' },
  parent: { type: String, default: '' },
  context: { type: String, default: '' },
  title: { type: String, default: '' },
  icon: { type: [Object, Function], default: null },
  focused: { type: Boolean, default: false },
  focusText: { type: String, default: '专注模式' },
  exitFocusText: { type: String, default: '退出专注模式' },
  showFocusAction: { type: Boolean, default: true }
})

defineEmits(['toggle-focus'])
</script>