<script setup>
/**
 * On-screen diagnostics for on-site debugging, toggled from Admin -> General.
 *
 * Two independent panels:
 *   conversation - live mic level, STT transcripts, and what the bot replied
 *   latency      - per-request timings for chat / stt / tts
 *
 * Deliberately a passive reader of the shared diagnostics bus, so it can be
 * mounted or unmounted without affecting anything it reports on.
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { events, micLevel, timings, timingStats, clearDiagnostics } from '../composables/useDiagnostics'

const props = defineProps({
  showConversation: { type: Boolean, default: false },
  showLatency: { type: Boolean, default: false },
})

const collapsed = ref(false)

// SILENCE_RMS in useBot; above this the VAD counts it as speech.
const SPEECH_THRESHOLD = 0.012
// RMS is tiny for normal speech, so scale it into something readable.
const micPercent = computed(() => Math.min(100, Math.round(micLevel.value * 400)))
const speaking = computed(() => micLevel.value >= SPEECH_THRESHOLD)

const recentEvents = computed(() => events.value.slice(-14).reverse())
const recentTimings = computed(() => timings.value.slice(-10).reverse())
const stats = computed(() =>
  ['chat', 'stt', 'tts'].map((label) => ({ label, ...(timingStats(label) || {}) })),
)

const KIND_LABEL = { stt: 'HEARD', user: 'GUEST', bot: 'PIXEL', state: 'STATE', error: 'ERROR' }
const KIND_CLASS = {
  stt: 'text-electric-300',
  user: 'text-slate-200',
  bot: 'text-brand-300',
  state: 'text-slate-500',
  error: 'text-red-300',
}

function clockOf(ts) {
  return new Date(ts).toLocaleTimeString([], { hour12: false })
}

// --- playback of kept STT recordings ---------------------------------------
const playingId = ref(0)
let player = null

function stopPlayback() {
  player?.pause()
  player = null
  playingId.value = 0
}

function togglePlay(e) {
  if (playingId.value === e.id) return stopPlayback()
  stopPlayback() // only ever one clip at a time
  player = new Audio(e.audio)
  player.onended = stopPlayback
  player.onerror = stopPlayback
  playingId.value = e.id
  player.play().catch(stopPlayback)
}

onBeforeUnmount(stopPlayback)
</script>

<template>
  <div
    v-if="showConversation || showLatency"
    class="fixed top-3 left-3 z-40 w-[min(24rem,calc(100vw-1.5rem))] font-mono text-[11px] leading-snug"
  >
    <div class="glass rounded-2xl border border-white/10 overflow-hidden">
      <div class="flex items-center gap-2 px-3 py-2 bg-ink-950/60">
        <span class="h-2 w-2 rounded-full" :class="speaking ? 'bg-brand-400' : 'bg-slate-600'"></span>
        <span class="font-display text-xs font-semibold tracking-wide">DIAGNOSTICS</span>
        <div class="ml-auto flex gap-1">
          <button class="px-2 py-0.5 rounded hover:bg-white/10" @click="clearDiagnostics">clear</button>
          <button class="px-2 py-0.5 rounded hover:bg-white/10" @click="collapsed = !collapsed">
            {{ collapsed ? '▸' : '▾' }}
          </button>
        </div>
      </div>

      <div v-if="!collapsed" class="max-h-[70vh] overflow-y-auto">
        <!-- microphone -->
        <section v-if="showConversation" class="px-3 py-2 border-t border-white/10">
          <div class="flex items-center justify-between text-slate-400 mb-1">
            <span>MIC</span>
            <span class="tabular-nums">{{ micLevel.toFixed(4) }} rms</span>
          </div>
          <div class="h-2 rounded-full bg-white/10 overflow-hidden" role="meter" :aria-valuenow="micPercent" aria-valuemin="0" aria-valuemax="100" aria-label="Microphone level">
            <div
              class="h-full transition-[width] duration-75"
              :class="speaking ? 'bg-brand-400' : 'bg-electric-500/70'"
              :style="{ width: micPercent + '%' }"
            ></div>
          </div>
          <p class="text-slate-500 mt-1">
            {{ speaking ? 'speech detected' : 'below VAD threshold (' + SPEECH_THRESHOLD + ')' }}
          </p>
        </section>

        <!-- latency -->
        <section v-if="showLatency" class="px-3 py-2 border-t border-white/10">
          <div class="text-slate-400 mb-1">AI LATENCY (ms)</div>
          <table class="w-full tabular-nums">
            <thead class="text-slate-500">
              <tr><th class="text-left font-normal">call</th><th class="text-right font-normal">last</th><th class="text-right font-normal">avg</th><th class="text-right font-normal">max</th><th class="text-right font-normal">n</th></tr>
            </thead>
            <tbody>
              <tr v-for="s in stats" :key="s.label">
                <td class="text-slate-300">{{ s.label }}</td>
                <td class="text-right">{{ s.last ?? '–' }}</td>
                <td class="text-right text-slate-400">{{ s.avg ?? '–' }}</td>
                <td class="text-right text-slate-400">{{ s.max ?? '–' }}</td>
                <td class="text-right text-slate-500">{{ s.n ?? 0 }}</td>
              </tr>
            </tbody>
          </table>

          <div v-if="recentTimings.length" class="mt-2 space-y-0.5">
            <div v-for="t in recentTimings" :key="t.id" class="flex gap-2">
              <span class="text-slate-600">{{ clockOf(t.at) }}</span>
              <span :class="t.ok ? 'text-slate-300' : 'text-red-300'">{{ t.label }}</span>
              <span class="ml-auto tabular-nums" :class="t.ms > 2000 ? 'text-amber-300' : 'text-slate-400'">{{ t.ms }}ms</span>
            </div>
          </div>
        </section>

        <!-- conversation -->
        <section v-if="showConversation" class="px-3 py-2 border-t border-white/10">
          <div class="text-slate-400 mb-1">CONVERSATION</div>
          <p v-if="!recentEvents.length" class="text-slate-600">nothing yet — press Talk to Me</p>
          <div v-for="e in recentEvents" :key="e.id" class="mb-1.5">
            <div class="flex items-center gap-2 text-slate-600">
              <span>{{ clockOf(e.at) }}</span>
              <span :class="KIND_CLASS[e.kind]">{{ KIND_LABEL[e.kind] || e.kind }}</span>
              <button
                v-if="e.audio"
                class="px-1.5 rounded hover:bg-white/10"
                :class="playingId === e.id ? 'text-brand-300' : 'text-electric-300'"
                :aria-label="playingId === e.id ? 'Stop playback' : 'Play this recording'"
                @click="togglePlay(e)"
              >{{ playingId === e.id ? '■' : '▶' }}</button>
              <a
                v-if="e.audio"
                :href="e.audio"
                download
                class="px-1 rounded hover:bg-white/10"
                aria-label="Download this recording"
              >⭳</a>
              <span v-if="e.detail" class="ml-auto truncate max-w-[9rem]">{{ e.detail }}</span>
            </div>
            <p class="text-slate-200 break-words whitespace-pre-wrap">{{ e.text }}</p>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
