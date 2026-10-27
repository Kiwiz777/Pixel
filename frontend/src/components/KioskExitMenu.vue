<script setup>
/**
 * Staff-only menu behind the hidden top-left hot-corner (5 taps). Closing the
 * kiosk needs the desktop launcher (deploy/pixel-kiosk.sh): a page can't close
 * a --kiosk Chromium itself. Fullscreen here is the page's own (Fullscreen
 * API) - it can't undo --kiosk or F11 either. Dismisses itself if left alone.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { toggleFullscreen } from '../composables/useSecretAccess'

const emit = defineEmits(['close'])

const busy = ref(false)
const msg = ref('')
const isFullscreen = ref(!!document.fullscreenElement)
let idle = null

function armIdle() {
  clearTimeout(idle)
  idle = setTimeout(() => emit('close'), 15000)
}

async function closeKiosk() {
  busy.value = true
  msg.value = ''
  armIdle()
  try {
    const res = await api.kioskExit()
    msg.value = res.launcher
      ? 'Closing the kiosk… Use “Start Pixel Kiosk” on the desktop to open it again.'
      : 'The kiosk launcher isn’t running, so this screen can’t close itself. Press Alt+F4 to close the browser.'
  } catch (e) {
    msg.value = e.message || 'Could not close the kiosk.'
  } finally {
    busy.value = false
  }
}

function onFullscreen() {
  toggleFullscreen()
  emit('close')
}

const syncFs = () => (isFullscreen.value = !!document.fullscreenElement)
onMounted(() => {
  armIdle()
  document.addEventListener('fullscreenchange', syncFs)
})
onBeforeUnmount(() => {
  clearTimeout(idle)
  document.removeEventListener('fullscreenchange', syncFs)
})
</script>

<template>
  <div class="fixed inset-0 z-[60] grid place-items-center p-4" role="dialog" aria-modal="true" aria-labelledby="staff-title">
    <div class="absolute inset-0 bg-ink-950/80 backdrop-blur-md" @click="emit('close')"></div>
    <div class="glass relative w-full max-w-sm p-6 text-center">
      <h2 id="staff-title" class="font-display text-2xl font-semibold">Staff menu</h2>
      <p class="text-slate-300 text-sm mt-1">Guests never see this.</p>

      <div class="mt-5 grid gap-3">
        <button class="btn-danger" :disabled="busy" @click="closeKiosk">
          {{ busy ? 'Closing…' : 'Close kiosk' }}
        </button>
        <button class="btn-ghost" @click="onFullscreen">
          {{ isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen' }}
        </button>
        <button class="btn-ghost" @click="emit('close')">Cancel</button>
      </div>

      <p v-if="msg" class="text-sm text-slate-200 mt-4" role="status">{{ msg }}</p>
    </div>
  </div>
</template>
