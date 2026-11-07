/**
 * Theme state for the design-system redesign.
 *
 * - Default is `light` when nothing is stored（设计系统以 #f7f8fa / #1677ff
 *   的浅色为产品默认外观；深色仍是完整支持的可选项）。
 * - The class lives on `<html>` because Element Plus reads `html.dark`.
 * - `index.html` has an inline copy of the storage read to paint the first
 *   frame before this module loads (no white flash). Keep the key and the
 *   default in sync with that script.
 * - A `ragstudio:theme-change` event is dispatched for non-Vue consumers
 *   (X6 / vis-network need to repaint outside the reactivity system).
 */
import { ref } from 'vue'

export type Theme = 'dark' | 'light'

export const THEME_STORAGE_KEY = 'ragstudio-theme'
export const THEME_CHANGE_EVENT = 'ragstudio:theme-change'
export const DEFAULT_THEME: Theme = 'light'

export const theme = ref<Theme>(DEFAULT_THEME)

function isTheme (value: unknown): value is Theme {
  return value === 'dark' || value === 'light'
}

export function readStoredTheme (): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    return isTheme(stored) ? stored : DEFAULT_THEME
  } catch {
    // localStorage can throw in private mode / blocked-cookie contexts
    return DEFAULT_THEME
  }
}

export function applyTheme (next: Theme): Theme {
  const resolved = isTheme(next) ? next : DEFAULT_THEME
  theme.value = resolved
  const root = document.documentElement
  root.classList.toggle('dark', resolved === 'dark')
  root.dataset.theme = resolved
  try {
    localStorage.setItem(THEME_STORAGE_KEY, resolved)
  } catch {
    // persistence is best-effort; the current session still works
  }
  window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: { theme: resolved } }))
  return resolved
}

export function initTheme (): Theme {
  return applyTheme(readStoredTheme())
}

/** Alias kept for existing call sites. */
export const initializeTheme = initTheme

export function toggleTheme (): Theme {
  return applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

/** Composable shape: current theme + toggle. */
export function useTheme () {
  return { theme, toggleTheme }
}
