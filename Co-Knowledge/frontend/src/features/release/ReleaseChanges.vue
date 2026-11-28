<template>
  <div class="release-changes">
    <section v-for="group in groups" :key="group.labelKey" class="release-change-group">
      <h3 :class="['release-change-heading', 'text-secondary', group.tone]">
        <component :is="group.icon" aria-hidden="true" />
        {{ $t(group.labelKey) }}
      </h3>
      <ul>
        <li v-for="item in group.items" :key="item">
          {{ item }}
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { Check, Plus } from '@/shared/lib/icons'
import { releaseText } from '@/shared/constants/releases'

/**
 * 一条发布记录的新增功能 / 修复改进。
 * 传入的 `release` 保持数据文件里的原样（中英双语），按当前界面语言取文案；
 * 两组都为空时不渲染任何内容，由调用方决定空态。
 */
const props = defineProps({ release: { type: Object, required: true } })

const { locale } = useI18n()

const groups = computed(() => {
  const text = releaseText(props.release, locale.value)
  return [
    { labelKey: 'modules.release.changesFeatures', icon: Plus, tone: 'blue', items: text.features },
    { labelKey: 'modules.release.changesFixes', icon: Check, tone: 'green', items: text.fixes }
  ].filter(group => group.items?.length)
})
</script>

<style scoped>
.release-changes { display: grid; gap: 18px; }
.release-change-heading {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  margin: 0 0 7px;
  border-radius: 5px;
  background: var(--tint);
  color: var(--rs-text);
  font-weight: 600;
}
.release-change-heading svg { width: 14px; height: 14px; color: var(--tone); }
.release-change-group ul { margin: 0; padding-inline-start: 20px; color: var(--rs-text-2); line-height: 1.75; }
.release-change-group li { overflow-wrap: anywhere; }
.release-change-group li + li { margin-top: 5px; }
.release-change-group li::marker { color: var(--rs-text-3); }
</style>
