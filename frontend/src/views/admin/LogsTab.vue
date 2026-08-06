<script setup>
/**
 * Logs tab: browse conversations, captures, prints and system events.
 */
import { ref, onMounted } from 'vue'
import { api } from '../../lib/api'

const FILTERS = [
  { id: '', label: 'All' },
  { id: 'conversation', label: 'Conversations' },
  { id: 'capture', label: 'Captures' },
  { id: 'enhance', label: 'Enhancements' },
  { id: 'print', label: 'Prints' },
  { id: 'face', label: 'Face sightings' },
  { id: 'error', label: 'Errors' },
]

const TYPE_STYLES = {
  conversation: 'bg-electric-500/15 text-electric-300',
  capture: 'bg-brand-500/15 text-brand-300',
  enhance: 'bg-fuchsia-500/15 text-fuchsia-300',
  print: 'bg-emerald-500/15 text-emerald-300',
  face: 'bg-sky-500/15 text-sky-300',
  error: 'bg-red-500/15 text-red-300',
  system: 'bg-slate-500/15 text-slate-300',
}

const active = ref('')
const logs = ref([])
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    logs.value = (await api.logs(active.value || undefined, 200)).logs
  } finally {
    loading.value = false
  }
}

function setFilter(id) {
  active.value = id
  load()
}

async function clearAll() {
  if (!confirm('Clear logs for this filter?')) return
  await api.clearLogs(active.value || undefined)
  await load()
}

function fmt(ts) {
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

onMounted(load)
</script>

<template>
  <section>
    <header class="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="font-display text-3xl font-semibold">Logs</h1>
        <p class="text-slate-400 mt-1">Conversations, photos and print history.</p>
      </div>
      <button class="btn-ghost btn-sm" @click="clearAll">Clear current</button>
    </header>

    <!-- filter chips -->
    <div class="flex flex-wrap gap-2 mb-5">
      <button
        v-for="f in FILTERS" :key="f.id"
        class="chip" :class="{ 'chip--active': active === f.id }"
        @click="setFilter(f.id)"
      >{{ f.label }}</button>
    </div>

    <div v-if="loading" class="space-y-3">
      <div v-for="i in 5" :key="i" class="skeleton h-16"></div>
    </div>
    <div v-else-if="!logs.length" class="glass-card p-10 text-center">
      <p class="font-display text-lg">Nothing here yet</p>
      <p class="hint">Activity will appear as guests interact with Pixel.</p>
    </div>
    <ul v-else class="space-y-3">
      <li v-for="l in logs" :key="l.id" class="glass-card p-4">
        <div class="flex items-start gap-3">
          <span class="text-[10px] uppercase tracking-wide px-2 py-1 rounded-full shrink-0" :class="TYPE_STYLES[l.type] || TYPE_STYLES.system">
            {{ l.type }}
          </span>
          <div class="min-w-0 flex-1">
            <p v-if="l.message" class="text-slate-100 break-words"><span class="text-slate-400">› </span>{{ l.message }}</p>
            <p v-if="l.response" class="text-slate-300 break-words mt-1"><span class="text-brand-300">Pixel: </span>{{ l.response }}</p>
            <p v-if="l.meta?.provider" class="text-xs text-slate-500 mt-1">{{ l.meta.provider }}<span v-if="l.meta.model"> · {{ l.meta.model }}</span></p>
          </div>
          <time class="text-xs text-slate-500 shrink-0 tabular-nums">{{ fmt(l.created_at) }}</time>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.chip {
  @apply glass rounded-full px-4 py-1.5 text-sm text-slate-300 cursor-pointer transition hover:text-white hover:bg-white/10;
}
.chip--active {
  @apply bg-brand-500/20 text-brand-200 border border-brand-400/30;
}
</style>
