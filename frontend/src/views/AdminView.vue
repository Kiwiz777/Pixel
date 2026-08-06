<script setup>
/**
 * AdminView - secure dashboard shell.
 *
 *  - Token gate: enter the PB_ADMIN_TOKEN once (stored in localStorage).
 *  - Sidebar tabs: General, AI Providers, Photobooth, Users, Logs.
 *  - Loads settings + provider catalogue once and shares with tabs.
 */
import { ref, onMounted, computed, onErrorCaptured } from 'vue'
import { api, getAdminToken, setAdminToken, clearAdminToken } from '../lib/api'
import GeneralTab from './admin/GeneralTab.vue'
import AiProvidersTab from './admin/AiProvidersTab.vue'
import PhotoboothTab from './admin/PhotoboothTab.vue'
import KioskTab from './admin/KioskTab.vue'
import QuizTab from './admin/QuizTab.vue'
import UsersTab from './admin/UsersTab.vue'
import LogsTab from './admin/LogsTab.vue'

const TABS = [
  { id: 'general', label: 'General', comp: GeneralTab },
  { id: 'ai', label: 'AI Providers', comp: AiProvidersTab },
  { id: 'photobooth', label: 'Photobooth', comp: PhotoboothTab },
  { id: 'kiosk', label: 'Kiosk', comp: KioskTab },
  { id: 'quiz', label: 'Quiz', comp: QuizTab },
  { id: 'users', label: 'Users', comp: UsersTab },
  { id: 'logs', label: 'Logs', comp: LogsTab },
]

const active = ref('general')
const authed = ref(false)
const tokenInput = ref('')
const loginError = ref('')
const loading = ref(false)

const settings = ref({})
const languages = ref([])
const providers = ref({ chat: {}, image: {} })
const savedToast = ref('')

const activeComp = computed(() => TABS.find((t) => t.id === active.value)?.comp)

// Safety net: never let a child render error blank the whole dashboard.
const renderError = ref('')
onErrorCaptured((err) => {
  renderError.value = err?.message || String(err)
  return false
})

async function loadAll() {
  loading.value = true
  try {
    const data = await api.getSettings()
    settings.value = data.settings
    languages.value = data.languages
    providers.value = data.providers
    authed.value = true
  } catch (e) {
    if (e.status === 401) {
      authed.value = false
      clearAdminToken()
    }
    loginError.value = e.message
  } finally {
    loading.value = false
  }
}

async function login() {
  loginError.value = ''
  setAdminToken(tokenInput.value.trim())
  await loadAll()
  if (authed.value) tokenInput.value = ''
}

function logout() {
  clearAdminToken()
  authed.value = false
}

/** Tabs call this to persist a partial settings patch. */
async function saveSettings(patch) {
  const res = await api.saveSettings(patch)
  settings.value = res.settings
  flashSaved()
}

function flashSaved() {
  savedToast.value = 'Saved'
  setTimeout(() => (savedToast.value = ''), 1800)
}

onMounted(() => {
  if (getAdminToken()) loadAll()
})
</script>

<template>
  <!-- Login gate -->
  <div v-if="!authed" class="aurora min-h-dvh grid place-items-center p-4">
    <form class="glass-card w-full max-w-sm p-7" @submit.prevent="login">
      <div class="flex items-center gap-2.5 mb-5">
        <span class="grid place-items-center h-10 w-10 rounded-xl bg-brand-500 shadow-glow font-display font-bold text-ink-950">P</span>
        <div>
          <h1 class="font-display text-xl font-semibold leading-tight">Admin Dashboard</h1>
          <p class="hint !mt-0">Pixel Photobooth Robot</p>
        </div>
      </div>
      <label class="label" for="admintoken">Admin token</label>
      <input
        id="admintoken" v-model="tokenInput" type="password" class="field"
        placeholder="PB_ADMIN_TOKEN" autocomplete="current-password"
      />
      <p v-if="loginError" class="hint text-red-300" role="alert">{{ loginError }}</p>
      <button class="btn-primary w-full mt-4" :disabled="loading || !tokenInput">
        <span v-if="loading" class="h-4 w-4 rounded-full border-2 border-ink-950 border-t-transparent animate-spin"></span>
        Unlock
      </button>
      <router-link to="/" class="block text-center hint mt-4 hover:text-slate-200">← Back to kiosk</router-link>
    </form>
  </div>

  <!-- Dashboard -->
  <div v-else class="aurora min-h-dvh flex flex-col lg:flex-row">
    <!-- Sidebar -->
    <aside class="lg:w-64 lg:min-h-dvh glass border-b lg:border-b-0 lg:border-r border-white/10 p-4 lg:p-5 flex lg:flex-col gap-2">
      <div class="hidden lg:flex items-center gap-2.5 mb-6 px-1">
        <span class="grid place-items-center h-9 w-9 rounded-xl bg-brand-500 shadow-glow font-display font-bold text-ink-950">P</span>
        <span class="font-display font-semibold">Pixel Admin</span>
      </div>
      <nav class="flex lg:flex-col gap-1.5 flex-1 overflow-x-auto scroll-slim">
        <button
          v-for="t in TABS" :key="t.id"
          class="nav-item" :class="{ 'nav-item--active': active === t.id }"
          @click="active = t.id"
        >{{ t.label }}</button>
      </nav>
      <div class="hidden lg:flex flex-col gap-2 mt-auto">
        <router-link to="/" class="btn-ghost btn-sm justify-start">View kiosk</router-link>
        <button class="btn-ghost btn-sm justify-start" @click="logout">Sign out</button>
      </div>
    </aside>

    <!-- Content -->
    <main class="flex-1 p-4 sm:p-7 lg:p-9 overflow-y-auto scroll-slim max-h-dvh">
      <div class="max-w-4xl mx-auto">
        <div v-if="renderError" class="glass-card p-5 border border-red-400/30 mb-5">
          <p class="font-display text-red-300">Something went wrong rendering this tab</p>
          <p class="hint break-words">{{ renderError }}</p>
          <button class="btn-ghost btn-sm mt-3" @click="renderError = ''">Dismiss</button>
        </div>
        <component
          :is="activeComp"
          :settings="settings"
          :languages="languages"
          :providers="providers"
          @save="saveSettings"
          @reload="loadAll"
        />
      </div>
    </main>

    <!-- saved toast -->
    <transition name="bubble">
      <div v-if="savedToast" class="fixed bottom-6 right-6 glass rounded-2xl px-5 py-3 text-sm flex items-center gap-2" aria-live="polite">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5"><path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        {{ savedToast }}
      </div>
    </transition>
  </div>
</template>

<style scoped>
.nav-item {
  @apply text-left rounded-xl px-4 py-2.5 font-display font-medium text-slate-300
         transition-colors cursor-pointer whitespace-nowrap hover:bg-white/5 hover:text-white;
  min-height: 44px;
}
.nav-item--active {
  @apply bg-brand-500/15 text-brand-200 border border-brand-400/30;
}
.bubble-enter-active { transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1); }
.bubble-leave-active { transition: all 0.2s ease-in; }
.bubble-enter-from, .bubble-leave-to { opacity: 0; transform: translateY(8px); }
</style>
