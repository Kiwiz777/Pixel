<script setup>
/**
 * Post-capture review modal. Shows the photo and lets the guest
 * Print, AI-Enhance, or Retake. Animates in from centre (scale + fade).
 */
import { ref, computed } from 'vue'
import { api } from '../lib/api'

const props = defineProps({
  capture: { type: Object, required: true }, // { capture_id, raw_url, ... }
  reward: { type: Object, default: null },   // quiz reward context (optional)
  // Shape of the print. The review box matches it so the guest sees the photo
  // at the proportions it will come out of the printer.
  aspect: { type: Number, default: 16 / 9 },
})
const emit = defineEmits(['retake', 'close', 'printed'])

const busy = ref('') // '', 'enhance', 'print', 'frame'
const error = ref('')
const enhancedUrl = ref('')
const framedUrl = ref('')
const toast = ref('')

const shownUrl = computed(() => framedUrl.value || enhancedUrl.value || props.capture.raw_url)

// ---- reward context -------------------------------------------------------
const rewardKind = computed(() => props.reward?.type || null)
const isEnhanceReward = computed(() => rewardKind.value === 'ai_enhance')
const promptMode = computed(() => props.reward?.prompt_mode || 'admin')
const promptChoices = computed(() => props.reward?.prompt_list || [])
const pickedPrompt = ref('')
const typedPrompt = ref('')

const rewardBanner = computed(() => {
  const rw = props.reward
  if (!rw) return ''
  if (rw.type === 'prints') {
    const p = rw.photos_count ?? 1
    const c = rw.prints_count ?? 1
    return `🎁 Reward: ${p} free photo${p > 1 ? 's' : ''}${c ? ` · ${c} print${c > 1 ? 's' : ''} each` : ''}`
  }
  if (rw.type === 'ai_enhance') {
    const n = rw.enhance_count ?? 1
    return `🎁 Reward: ${n} free AI-enhanced photo${n > 1 ? 's' : ''}`
  }
  return ''
})

// The prompt applied when the reward is an AI enhancement.
const resolvedPrompt = computed(() => {
  if (!isEnhanceReward.value) return undefined
  if (promptMode.value === 'list') return pickedPrompt.value || promptChoices.value[0] || undefined
  if (promptMode.value === 'user') return typedPrompt.value?.trim() || undefined
  return props.reward?.prompt || undefined // admin-fixed prompt
})

async function enhance() {
  error.value = ''
  if (isEnhanceReward.value && promptMode.value === 'user' && !typedPrompt.value.trim()) {
    error.value = 'Type how you want your photo enhanced first.'
    return
  }
  busy.value = 'enhance'
  try {
    const res = await api.enhance(props.capture.capture_id, resolvedPrompt.value)
    enhancedUrl.value = res.enhanced_url + `?t=${Date.now()}`
  } catch (e) {
    error.value = e.message || 'Enhance failed. Check the AI provider key in Admin.'
  } finally {
    busy.value = ''
  }
}

async function printPhoto() {
  error.value = ''
  busy.value = 'print'
  try {
    // Composite the frame overlay (if configured) then print.
    try {
      const f = await api.applyFrame(props.capture.capture_id, !!enhancedUrl.value)
      framedUrl.value = f.framed_url + `?t=${Date.now()}`
    } catch {
      /* no frame configured - fine */
    }
    const res = await api.print(props.capture.capture_id)
    toast.value = `Printing on ${res.printer || 'printer'} · job ${res.job_id}`
    emit('printed', res)
    setTimeout(() => (toast.value = ''), 4000)
  } catch (e) {
    error.value = e.message || 'Print failed. Check the printer in Admin.'
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true">
    <!-- scrim -->
    <div class="absolute inset-0 bg-ink-950/70 backdrop-blur-sm" @click="emit('close')"></div>

    <div class="modal glass-card relative w-full max-w-3xl p-5 sm:p-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="font-display text-2xl font-semibold">Looking good!</h2>
        <button class="btn-ghost btn-sm" @click="emit('close')" aria-label="Close">✕</button>
      </div>

      <!-- Reward banner (from a quiz win) -->
      <div v-if="rewardBanner" class="mb-4 rounded-2xl border border-brand-400/30 bg-brand-500/10 px-4 py-3">
        <p class="font-display text-brand-200">{{ rewardBanner }}</p>

        <!-- AI-enhance prompt selection -->
        <div v-if="isEnhanceReward && promptMode === 'list'" class="mt-3">
          <p class="hint !mt-0 mb-1.5">Pick your enhancement style:</p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="(p, i) in promptChoices" :key="i" type="button"
              class="rounded-full px-3.5 py-1.5 text-sm border transition-colors"
              :class="(pickedPrompt || promptChoices[0]) === p
                ? 'bg-brand-500 text-ink-950 border-brand-400'
                : 'border-white/20 text-slate-200 hover:bg-white/5'"
              @click="pickedPrompt = p"
            >{{ p }}</button>
          </div>
        </div>
        <div v-else-if="isEnhanceReward && promptMode === 'user'" class="mt-3">
          <label class="hint !mt-0 mb-1.5 block">Describe how to enhance your photo:</label>
          <input v-model="typedPrompt" class="field" placeholder="e.g. Make it a vibrant cartoon portrait" />
        </div>
      </div>

      <!-- Photo -->
      <div
        class="relative mx-auto rounded-2xl overflow-hidden bg-ink-900 grid place-items-center max-w-full"
        :style="{ aspectRatio: String(aspect), width: `min(100%, ${(52 * aspect).toFixed(2)}vh)` }"
      >
        <img :src="shownUrl" alt="Your photo" class="h-full w-full object-contain" />
        <div v-if="busy === 'enhance'" class="absolute inset-0 grid place-items-center bg-ink-950/60">
          <div class="text-center">
            <div class="mx-auto mb-3 h-10 w-10 rounded-full border-2 border-electric-400 border-t-transparent animate-spin"></div>
            <p class="font-display text-electric-300">AI is enhancing your photo…</p>
          </div>
        </div>
        <span
          v-if="enhancedUrl"
          class="absolute top-3 left-3 rounded-full bg-electric-600/90 text-white text-xs font-semibold px-3 py-1"
        >AI Enhanced</span>
      </div>

      <p v-if="error" class="hint text-red-300 mt-3" role="alert">{{ error }}</p>

      <!-- Actions -->
      <div class="mt-5 grid grid-cols-2 sm:grid-cols-3 gap-3">
        <button class="btn-ghost" :disabled="!!busy" @click="emit('retake')">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 3-6.7L3 8" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 4v4h4" stroke-linecap="round" stroke-linejoin="round"/></svg>
          Retake
        </button>
        <button class="btn-accent" :disabled="!!busy" @click="enhance">
          <span v-if="busy === 'enhance'" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
          <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m12 3 1.9 4.3L18 9l-4.1 1.7L12 15l-1.9-4.3L6 9l4.1-1.7L12 3Z"/><path d="M5 16l.9 2L8 19l-2.1.9L5 22l-.9-2L2 19l2.1-1L5 16Z"/></svg>
          AI Enhance
        </button>
        <button class="btn-primary col-span-2 sm:col-span-1" :disabled="!!busy" @click="printPhoto">
          <span v-if="busy === 'print'" class="h-4 w-4 rounded-full border-2 border-ink-950 border-t-transparent animate-spin"></span>
          <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2M6 14h12v8H6z"/></svg>
          Print
        </button>
      </div>

      <p class="hint text-center mt-3">Enhance uses your configured AI image provider · Print sends to the default CUPS printer.</p>
    </div>

    <!-- toast -->
    <div v-if="toast" class="fixed bottom-6 left-1/2 -translate-x-1/2 glass rounded-2xl px-5 py-3 text-sm" aria-live="polite">
      {{ toast }}
    </div>
  </div>
</template>

<style scoped>
.modal {
  animation: pop 0.28s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes pop {
  from { opacity: 0; transform: scale(0.94) translateY(8px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .modal { animation: none; }
}
</style>
