<template>
  <aside :class="['sidebar', { collapsed: isCollapsed, 'is-en': !isZh }]">
    <RouterLink to="/knowledge" class="brand">
      <BrandMark />
      <div class="brand-copy">
        <div class="brand-title">Knowledge Studio</div>
        <div class="brand-sub">{{ $t('brand.subtitle') }}</div>
      </div>
    </RouterLink>

    <nav aria-label="主导航">
      <component
        :is="group.single ? 'div' : 'details'"
        v-for="group in menuGroups"
        :key="group.key"
        :class="['group', { single: group.single }]"
        :open="group.single ? undefined : (isCollapsed || expanded[group.key] !== false)"
        @toggle="group.single ? undefined : updateGroup(group.key, $event)"
      >
        <summary v-if="!group.single" class="group-title">
          {{ $t(group.labelKey) }}<ArrowUp />
        </summary>
        <RouterLink
          v-for="item in group.items"
          :key="item.index"
          :to="item.route"
          :class="['nav-item', { 'router-link-active': activeMenu === item.index }]"
          :title="$t(item.labelKey)"
          active-class=""
          exact-active-class=""
        >
          <component :is="item.iconComponent" />
          <span>{{ $t(item.labelKey) }}</span>
        </RouterLink>
      </component>
    </nav>

    <div class="promo">
      <div>{{ $t('nav.promoLine1') }}<br />{{ $t('nav.promoLine2') }}</div>
      <BookIllustration />
    </div>

    <div class="side-footer">
      <div class="footer-preferences">
        <!-- 本地账号已登录时显示用户菜单（修改密码/退出）；否则显示登录入口：
             配置了 VUE_APP_UAC（appState.loginUrl）时外链，没有时指向站内 /login。 -->
        <UserMenu v-if="showUserMenu" />
        <a
          v-else-if="loginUrl"
          :href="loginUrl"
          class="icon-button"
          aria-label="登录入口"
          title="登录入口"
        >
          <User aria-hidden="true" />
        </a>
        <RouterLink
          v-else
          :to="{ name: 'login' }"
          class="icon-button"
          aria-label="登录入口"
          title="登录入口"
        >
          <User aria-hidden="true" />
        </RouterLink>
        <button
          type="button"
          class="icon-button theme-button"
          :aria-label="theme === 'dark' ? $t('nav.switchToLight') : $t('nav.switchToDark')"
          :title="theme === 'dark' ? $t('nav.switchToLight') : $t('nav.switchToDark')"
          :aria-pressed="theme === 'dark'"
          @click="toggleAppTheme"
        >
          <Sunny v-if="theme === 'dark'" aria-hidden="true" />
          <Moon v-else aria-hidden="true" />
        </button>

        <el-popover
          v-model:visible="settingsOpen"
          placement="top-start"
          trigger="click"
          :width="232"
          :offset="10"
          popper-class="sidebar-settings-popover"
        >
          <template #reference>
            <button
              type="button"
              class="icon-button settings-button"
              :aria-label="$t('nav.preferences')"
              :title="$t('nav.preferences')"
              :aria-expanded="settingsOpen"
              aria-controls="sidebar-preferences"
            >
              <Setting aria-hidden="true" />
            </button>
          </template>
          <div id="sidebar-preferences" class="preferences-panel">
            <div class="preferences-title">{{ $t('nav.preferences') }}</div>
            <div class="preferences-label" id="interface-language-label">{{ $t('nav.interfaceLanguage') }}</div>
            <div class="language-options" role="group" aria-labelledby="interface-language-label">
              <button
                type="button"
                :class="['language-option', { 'is-current': isZh }]"
                :aria-label="isZh ? $t('nav.langZhCurrent') : $t('nav.langZh')"
                @click="selectLanguage('zh-CN')"
              >
                <span>{{ $t('nav.langZh') }}</span>
                <Check v-if="isZh" aria-hidden="true" />
              </button>
              <button
                type="button"
                :class="['language-option', { 'is-current': !isZh }]"
                :aria-label="!isZh ? $t('nav.langEnCurrent') : $t('nav.langEn')"
                @click="selectLanguage('en-US')"
              >
                <span>{{ $t('nav.langEn') }}</span>
                <Check v-if="!isZh" aria-hidden="true" />
              </button>
            </div>
          </div>
        </el-popover>
      </div>

      <button
        type="button"
        class="icon-button"
        :aria-label="isCollapsed ? $t('nav.expand') : $t('nav.collapse')"
        :title="isCollapsed ? $t('nav.expand') : $t('nav.collapse')"
        @click="toggleCollapse"
      >
        <DArrowRight v-if="isCollapsed" aria-hidden="true" />
        <DArrowLeft v-else aria-hidden="true" />
      </button>
    </div>
  </aside>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowUp, Check, DArrowLeft, DArrowRight, Moon, Setting, Sunny, User } from '@/shared/lib/icons'
import { useTheme } from '@/shared/lib/theme'
import appState from '@/app/state'
import { NAV_MENUS, resolveActiveMenu } from './menu.config'
import { isChineseLanguage, switchLanguage } from '@/shared/lib/language'
import BrandMark from '@/shared/ui/BrandMark.vue'
import BookIllustration from '@/shared/ui/BookIllustration.vue'
import UserMenu from '@/features/auth/components/UserMenu.vue'
import { isAuthEnabled, isAuthenticated } from '@/features/auth/session'

const { theme, toggleTheme: toggleAppTheme } = useTheme()

const COLLAPSE_STORAGE_KEY = 'ragstudio-nav-collapse'

// 当前生效语言的判定与切换统一走 `@/shared/lib/language`（登录页同源）。
const isZh = isChineseLanguage()
const settingsOpen = ref(false)

// 登录入口：外部 VUE_APP_UAC（或被 qiankun 注入 appState.loginUrl）优先；
// 未配置时指向站内 /login。登录页已恢复，图标不再隐藏。
const loginUrl = ref(appState.loginUrl || '')
onMounted(() => {
  loginUrl.value = appState.loginUrl || ''
})

// 本地账号已登录 → 用户菜单；none/gateway 模式或未登录 → 保留登录入口。
const showUserMenu = computed(() => isAuthEnabled.value && isAuthenticated.value)

function selectLanguage (language) {
  settingsOpen.value = false
  // 写入存储并整页重载（原因见 `@/shared/lib/language`）。
  switchLanguage(language)
}

const route = useRoute()

/**
 * 菜单分组：有 children 的保持一个分组；连续的根级菜单合并成 `.group.single`
 * （「自定义算子 / 模型管理」放在同一个无标题组里）。
 */
const menuGroups = computed(() => {
  const groups = []
  let singles = []
  const flushSingles = () => {
    if (singles.length) {
      groups.push({
        key: `single-${singles[0].index}`,
        single: true,
        items: singles
      })
      singles = []
    }
  }
  for (const entry of NAV_MENUS) {
    if (entry.children) {
      flushSingles()
      groups.push({
        key: entry.index,
        single: false,
        labelKey: entry.labelKey,
        items: entry.children
      })
    } else {
      singles.push(entry)
    }
  }
  flushSingles()
  return groups
})

// 只看 path：拆页后知识库组两个入口各是一条路由，菜单高亮不再依赖 query
const activeMenu = computed(() => resolveActiveMenu(route.path))

const isCollapse = ref(localStorage.getItem(COLLAPSE_STORAGE_KEY) === '1')

/** 分组展开状态（0.1.7）：默认展开；折叠侧栏时不记录，恢复展开后再由用户控制。 */
const expanded = ref({})

function updateGroup (key, event) {
  if (isCollapse.value) {
    return
  }
  const target = event.target
  if (target?.tagName === 'DETAILS') {
    expanded.value = { ...expanded.value, [key]: target.open }
  }
}

// 窄屏不强制折叠，宽度由组件的 @media(max-width:1100px) 收到 206px。
const isCollapsed = computed(() => isCollapse.value)

function toggleCollapse () {
  isCollapse.value = !isCollapse.value
  localStorage.setItem(COLLAPSE_STORAGE_KEY, isCollapse.value ? '1' : '0')
}
</script>

<style scoped>
/* ── 侧栏样式（仅作用在组件内） ─────────────────────────────────────────
   全局设计系统（tokens.css / theme.css 的 --rs-*、base.css 的 .icon-button
   与 `button, input, textarea, select { font: inherit }`、body 的 line-height）
   由 main.js 统一引入 —— 这里不再复制副本。 */
.sidebar{width:240px;flex-shrink:0;background:var(--rs-bg-card);border-right:1px solid var(--rs-border);height:100vh;padding:24px 14px 0;display:flex;flex-direction:column;transition:width .2s;overflow:hidden}.sidebar nav{min-height:0;overflow-y:auto}.brand{display:flex;align-items:center;gap:13px;padding:0 9px 20px;color:var(--rs-text);white-space:nowrap}.brand>.brand-mark{width:40px;height:40px}.brand-title{font-size:18px;font-weight:750;letter-spacing:-.5px}.brand-sub{font-size:10px;color:var(--rs-text-3);margin-top:2px}.group{margin:6px 0 22px}.group-title{display:flex;align-items:center;justify-content:space-between;font-size:13px;color:var(--rs-text-2);padding:0 12px 14px}.group-title svg{width:12px;height:12px;color:var(--rs-text-3)}.nav-item{height:43px;padding:0 22px;display:flex;align-items:center;gap:17px;border-radius:9px;color:var(--rs-text-2);text-decoration:none;font-size:14px;margin:3px 0;position:relative;white-space:nowrap}.nav-item svg{width:20px;height:20px;stroke:currentColor;stroke-width:.3}.nav-item:hover{background:var(--rs-bg-hover)}.nav-item.router-link-active{background:linear-gradient(100deg,var(--rs-bg-selected),var(--rs-bg-selected));color:var(--rs-primary);font-weight:600}.nav-item.router-link-active:before{content:"";position:absolute;left:-2px;width:3px;height:22px;border-radius:3px;background:var(--rs-primary)}.single{margin-top:-4px;margin-bottom:24px}.promo{margin-top:auto;min-height:86px;background:linear-gradient(130deg,var(--rs-bg-selected),var(--rs-bg-selected));border-radius:10px;padding:16px 12px;position:relative;display:flex;align-items:center;font-size:11px;line-height:1.8;color:var(--rs-text-2);font-weight:550;flex-shrink:0}.promo>div{position:relative;z-index:1;white-space:nowrap}.promo>svg{position:absolute;right:-2px;bottom:0;width:84px;height:91px}.side-footer{display:flex;align-items:center;justify-content:space-between;color:var(--rs-text-2);font-size:13px;padding:8px 18px;margin:12px -14px 0;border-top:1px solid var(--rs-border-soft);height:48px;flex-shrink:0}.collapsed{width:78px}.collapsed .brand{padding-left:5px}.collapsed .brand-copy,.collapsed .nav-item span,.collapsed .group-title,.collapsed .promo{display:none}.collapsed .nav-item{padding:0;justify-content:center}.collapsed .group{margin-bottom:20px}.collapsed .side-footer{margin-top:auto;justify-content:center}
@media(max-height:800px){.sidebar{padding-top:20px}.brand{padding-bottom:19px}.group{margin-bottom:18px}.single{margin-bottom:20px}.nav-item{height:40px}}
/* ── 英文界面专用：允许换行，避免长标签把侧栏撑出横向滚动条。
   中文界面必须保持上面的排版；英文标签宽度超出 240px 侧栏，
   只有在此覆盖里才恢复 wrap / 内容撑高。 ─────────────────────────────── */
.sidebar.is-en nav{overflow-x:hidden}
.sidebar.is-en .brand{white-space:normal}
.sidebar.is-en .brand-copy{min-width:0}
.sidebar.is-en .brand-sub{line-height:1.35}
.sidebar.is-en .nav-item{height:auto;min-height:43px;padding:8px 22px;line-height:1.35;white-space:normal}
.sidebar.is-en .nav-item svg{flex-shrink:0}
/* 折叠态只看图标：英文覆盖的 padding 特异性更高，需显式归零（含 ≤1100px 的窄屏档）。 */
.sidebar.is-en.collapsed .nav-item{padding:0}
@media(max-height:800px){.sidebar.is-en .nav-item{height:auto;min-height:40px}}
@media(max-width:1100px){.sidebar{width:206px;padding-left:10px;padding-right:10px}.brand{gap:9px;padding-left:7px}.brand-title{font-size:17px}.brand-sub{font-size:9px}.brand>.brand-mark{width:32px;height:32px}.nav-item{padding-left:16px;gap:12px}.sidebar.is-en .nav-item{padding-left:16px;gap:12px}.promo{font-size:10px}.promo>svg{width:66px}.side-footer{margin-left:-10px;margin-right:-10px}.sidebar.collapsed{width:70px}}
.footer-preferences{display:flex;align-items:center;gap:8px}
.theme-button svg{width:16px;height:16px}
.theme-button[aria-pressed="true"]{color:var(--rs-primary)}
.settings-button svg{width:16px;height:16px}
.settings-button[aria-expanded="true"]{color:var(--rs-primary);background:var(--rs-bg-selected)}
.preferences-title{font-size:var(--rs-font-size-secondary);font-weight:600;color:var(--rs-text);padding:2px 8px 12px;border-bottom:1px solid var(--rs-border-soft)}
.preferences-label{padding:12px 8px 6px;font-size:var(--rs-font-size-caption);color:var(--rs-text-3)}
.language-options{display:flex;flex-direction:column;gap:4px}
.language-option{width:100%;height:36px;padding:0 10px;border:0;border-radius:6px;display:flex;align-items:center;justify-content:space-between;background:transparent;color:var(--rs-text-2);font-size:var(--rs-font-size-secondary);text-align:left}
.language-option.is-current{color:var(--rs-primary);background:var(--rs-bg-selected)}
.language-option.is-current:hover{background:var(--rs-bg-selected)}
.language-option svg{width:15px;height:15px}
.language-option:disabled{cursor:not-allowed;color:var(--rs-text-3)}
.language-pending{font-size:11px;background:var(--rs-bg-soft);padding:2px 6px;border-radius:4px}
.collapsed .side-footer{padding:8px 6px;height:auto;min-height:48px;flex-direction:column;justify-content:center;gap:8px}
.collapsed .footer-preferences{flex-direction:column;gap:4px}
.group-title{cursor:pointer;list-style:none}
.group-title::-webkit-details-marker{display:none}
.group-title:focus-visible{outline:2px solid var(--rs-primary-border);outline-offset:2px;border-radius:4px}
.group:not([open]) .group-title svg{transform:rotate(180deg)}
</style>
