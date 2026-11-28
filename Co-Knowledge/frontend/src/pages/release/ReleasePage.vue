<template>
  <AppPage class="release-page">
    <div class="page-inner">
      <PageHeader
        :icon="CollectionTag"
        :title="$t('modules.release.pageTitle')"
        :subtitle="$t('modules.release.pageSubtitle')"
      />

      <ol v-if="releases.length" class="release-timeline" :aria-label="$t('modules.release.timelineAria')">
        <li v-for="release in releases" :key="release.version" :class="{ 'is-current': release === currentRelease }">
          <div class="release-meta">
            <span class="release-version text-code">v{{ release.version }}</span>
            <time v-if="release.date" :datetime="release.date" class="text-caption">{{ release.date }}</time>
          </div>
          <article class="release-entry">
            <header class="release-entry-header">
              <div class="release-entry-title">
                <h2 class="text-section-title">
                  {{ textOf(release).title }}
                </h2>
                <el-tag v-if="release === currentRelease" size="small" effect="light" round>
                  {{ $t('modules.release.currentVersion') }}
                </el-tag>
              </div>
              <div v-if="release === currentRelease" class="entity-sub">
                {{ $t(buildTimeLabelKey) }} · <time :datetime="buildTimeIso">{{ formattedBuildTime }} (UTC+8)</time>
              </div>
            </header>
            <ReleaseChanges :release="release" />
          </article>
        </li>
      </ol>
      <el-empty v-else :description="$t('modules.release.empty')" />
    </div>
  </AppPage>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import PageHeader from '@/shared/ui/reference/PageHeader.vue'
import AppPage from '@/shared/ui/AppPage.vue'
import ReleaseChanges from '@/features/release/ReleaseChanges.vue'
import { CollectionTag } from '@/shared/lib/icons'
import { currentRelease, releases, releaseText } from '@/shared/constants/releases'

/**
 * 版本更新：按时间倒序展示全部发布记录，第一条为当前版本。
 *
 * 「构建时间」由打包阶段写入（`vue.config.js` 的 `VUE_APP_TIME_STAMP`）：
 * 生产构建是产物生成时间，本地预览是 dev server 的启动时间。
 */
const { locale } = useI18n()

const buildTime = Number(process.env.VUE_APP_TIME_STAMP) || Date.now()
const buildTimeIso = new Date(buildTime).toISOString()
const buildTimeLabelKey = process.env.NODE_ENV === 'development'
  ? 'modules.release.previewTime'
  : 'modules.release.buildTime'

const formattedBuildTime = computed(() => {
  const language = String(locale.value || '').toLowerCase()
  return new Intl.DateTimeFormat(
    language.startsWith('en') ? 'en-US' : 'zh-CN',
    {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23'
    }
  ).format(new Date(buildTime))
})

function textOf (release) {
  return releaseText(release, locale.value)
}
</script>

<style scoped>
.release-timeline {
  display: grid;
  max-width: 960px;
  gap: 16px;
  list-style: none;
  margin: 0;
  padding: 0;
}
.release-timeline > li {
  display: grid;
  grid-template-columns: 114px minmax(0, 1fr);
  gap: 16px;
  position: relative;
}
.release-timeline > li:not(:last-child)::after {
  content: '';
  position: absolute;
  inset-block: 28px -44px;
  inset-inline-start: 5px;
  width: 1px;
  background: var(--rs-border);
}
.release-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
  position: relative;
  padding: 20px 0 0 24px;
  color: var(--rs-text-2);
}
.release-meta::before {
  content: '';
  box-sizing: border-box;
  position: absolute;
  z-index: 1;
  inset-block-start: 23px;
  inset-inline-start: 0;
  width: 11px;
  height: 11px;
  border: 2px solid var(--rs-border);
  border-radius: 50%;
  background: var(--rs-bg-page);
}
.release-version { font-weight: 650; color: var(--rs-text); }
.is-current .release-meta::before { border-color: var(--rs-primary); background: var(--rs-primary); }
.is-current .release-version { color: var(--rs-primary); }
.release-entry {
  min-width: 0;
  padding: 18px 22px 22px;
  border: 1px solid var(--rs-border);
  border-radius: var(--rs-radius);
  background: var(--rs-bg-card);
}
.is-current .release-entry { border-color: var(--rs-primary-border); }
.release-entry-header { margin-bottom: 16px; }
.release-entry-title { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; }
.release-entry-header h2 { margin: 0; overflow-wrap: anywhere; }

@media (max-width: 760px) {
  .release-timeline > li { grid-template-columns: minmax(0, 1fr); gap: 9px; padding-inline-start: 20px; }
  .release-timeline > li:not(:last-child)::after { inset-block: 9px -25px; }
  .release-meta { flex-direction: row; align-items: baseline; flex-wrap: wrap; gap: 6px 12px; padding: 0; }
  .release-meta::before { inset-block-start: 4px; inset-inline-start: -20px; }
  .release-entry { padding: 14px; }
}
</style>
