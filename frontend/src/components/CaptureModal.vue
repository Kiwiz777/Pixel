<script setup>
/**
 * Post-capture review modal. Shows the photo and lets the guest
 * Print, AI-Enhance, or Retake. Animates in from centre (scale + fade).
 *
 * Soft save (Admin -> Save & Share), from /api/share/options on open:
 *   - manual:  a "Save" split button; its arrow lists Email / WhatsApp when
 *              those are enabled AND their service is connected.
 *   - auto:    saved as soon as the modal opens (and again after AI Enhance),
 *              no Save button; Email / WhatsApp show as plain buttons.
 * Any failure raises a notice with Retry, because the guest is standing
 * right there and can't be sent to a log.
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../lib/api'
import VirtualKeyboard from './VirtualKeyboard.vue'

const props = defineProps({
  capture: { type: Object, required: true }, // { capture_id, raw_url, ... }
  reward: { type: Object, default: null },   // quiz reward context (optional)
  // Shape of the print. The review box matches it so the guest sees the photo
  // at the proportions it will come out of the printer.
  aspect: { type: Number, default: 16 / 9 },
  // Frame overlay preview. Empty string = don't show one here (Admin decides
  // whether the frame appears on the live view, this modal, or both).
  frameUrl: { type: String, default: '' },
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
    // The enhanced photo is a new version: keep the folder copy current.
    savedFile.value = ''
    if (shareOpts.value.auto_save) savePhoto()
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

// ---- soft save + share ------------------------------------------------------
const shareOpts = ref({ soft_save: false, auto_save: false, email: false, whatsapp: false })
const savedFile = ref('')     // folder copy of the CURRENT version ('' = not saved)
const saving = ref(false)
const menuOpen = ref(false)
const sendVia = ref('')       // '' | 'email' | 'whatsapp' -> recipient panel open
const recipient = ref({ email: '', whatsapp: '' })
const sending = ref(false)
const keyboardOpen = ref(false)
// { kind: 'ok'|'error', text, retry?: fn } - errors stay until dismissed/retried.
const notice = ref(null)
let noticeTimer = null

const hasSendOptions = computed(() => shareOpts.value.email || shareOpts.value.whatsapp)
const showSaveButton = computed(() => shareOpts.value.soft_save && !shareOpts.value.auto_save)
const showDirectSend = computed(() => shareOpts.value.auto_save && hasSendOptions.value)
const CHANNEL = {
  email: { label: 'Email it', field: 'Your email address', placeholder: 'name@example.com', layout: 'email' },
  whatsapp: { label: 'WhatsApp it', field: 'Your WhatsApp number', placeholder: '+20 10 1234 5678', layout: 'tel' },
}

function notify(kind, text, retry = null) {
  clearTimeout(noticeTimer)
  notice.value = { kind, text, retry }
  if (kind === 'ok') noticeTimer = setTimeout(() => (notice.value = null), 4000)
}

async function savePhoto() {
  if (saving.value) return
  saving.value = true
  try {
    const res = await api.shareSave(props.capture.capture_id)
    savedFile.value = res.name
    if (!shareOpts.value.auto_save) notify('ok', 'Photo saved.')
  } catch (e) {
    notify('error', `Couldn't save your photo: ${e.message || 'unknown error'}`, savePhoto)
  } finally {
    saving.value = false
  }
}

function openSend(channel) {
  menuOpen.value = false
  sendVia.value = channel
  waTypeNumber.value = false
  if (channel === 'whatsapp' && waUsesQr.value) {
    keyboardOpen.value = false
    startWaCode()
  } else {
    keyboardOpen.value = true
  }
}

function closeSend() {
  sendVia.value = ''
  keyboardOpen.value = false
  stopWaPolling()
}

// ---- WhatsApp QR mode --------------------------------------------------------
// The guest scans a wa.me link that pre-fills a message with a one-time code;
// sending it makes the booth reply with this photo. We poll the code so the
// kiosk can say "sent" - or raise a Retry notice if delivery failed.
const waUsesQr = computed(() => ['qr', 'both'].includes(shareOpts.value.whatsapp_mode || 'qr'))
const waTypeNumber = ref(false)  // 'both' mode: guest chose to type instead
const waCode = ref(null)         // { code, link, qr_svg }
const waLoading = ref(false)
const waSecondsLeft = ref(0)
const waSent = ref(0)
let waExpiresAt = 0
let waPollTimer = null
let waTickTimer = null
let waFailSeen = 0

const waShowQr = computed(() => sendVia.value === 'whatsapp' && waUsesQr.value && !waTypeNumber.value)
const waCountdown = computed(() => {
  const s = waSecondsLeft.value
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
})

async function startWaCode() {
  stopWaPolling()
  waLoading.value = true
  try {
    const res = await api.waCode(props.capture.capture_id)
    waCode.value = res
    waSent.value = res.sent || 0
    waFailSeen = res.failed || 0
    waExpiresAt = Date.now() + res.expires_in * 1000
    tickWa()
    waTickTimer = setInterval(tickWa, 1000)
    waPollTimer = setInterval(pollWa, 2000)
  } catch (e) {
    waCode.value = null
    notify('error', e.message || 'WhatsApp is not available right now.', startWaCode)
  } finally {
    waLoading.value = false
  }
}

function tickWa() {
  waSecondsLeft.value = Math.max(0, Math.round((waExpiresAt - Date.now()) / 1000))
  if (!waSecondsLeft.value) stopWaPolling()
}

async function pollWa() {
  const code = waCode.value?.code
  if (!code) return
  try {
    const st = await api.waCodeStatus(code)
    if (st.sent > waSent.value) {
      notify('ok', st.sent > 1 ? `Photo sent on WhatsApp to ${st.sent} phones` : 'Photo sent on WhatsApp!')
    }
    waSent.value = st.sent
    if (st.failed > waFailSeen && st.error) {
      notify('error', `WhatsApp couldn't deliver the photo: ${st.error}`, retryWaCode)
    }
    waFailSeen = st.failed
  } catch {
    /* transient - next poll */
  }
}

async function retryWaCode() {
  const code = waCode.value?.code
  if (!code) return
  try {
    const st = await api.waCodeRetry(code)
    waFailSeen = st.failed
  } catch (e) {
    notify('error', e.message || 'Retry failed.', startWaCode)
  }
}

function stopWaPolling() {
  clearInterval(waPollTimer)
  clearInterval(waTickTimer)
  waPollTimer = waTickTimer = null
}

async function sendPhoto() {
  const channel = sendVia.value
  const to = recipient.value[channel].trim()
  if (!channel || !to || sending.value) return
  sending.value = true
  keyboardOpen.value = false
  try {
    if (channel === 'email') await api.shareEmail(props.capture.capture_id, to)
    else await api.shareWhatsApp(props.capture.capture_id, to)
    notify('ok', channel === 'email' ? `Sent to ${to}` : `Sent on WhatsApp to ${to}`)
    sendVia.value = ''
  } catch (e) {
    // Panel stays open with what they typed, so a typo is one tap to fix.
    notify('error', e.message || 'Sending failed.', sendPhoto)
  } finally {
    sending.value = false
  }
}

function retryNotice() {
  const fn = notice.value?.retry
  notice.value = null
  fn?.()
}

function onKey(char) {
  recipient.value[sendVia.value] += char
}
function onBackspace() {
  recipient.value[sendVia.value] = recipient.value[sendVia.value].slice(0, -1)
}

function onDocClick(e) {
  if (menuOpen.value && !e.target.closest?.('[data-share-menu]')) menuOpen.value = false
}

onMounted(async () => {
  document.addEventListener('pointerdown', onDocClick)
  try {
    shareOpts.value = { ...shareOpts.value, ...(await api.shareOptions()) }
  } catch {
    return // sharing is optional - the modal works without it
  }
  if (shareOpts.value.auto_save) savePhoto()
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocClick)
  clearTimeout(noticeTimer)
  stopWaPolling()
})
</script>

<template>
  <div class="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true">
    <!-- scrim -->
    <div class="absolute inset-0 bg-ink-950/70 backdrop-blur-sm" @click="emit('close')"></div>

    <div class="modal glass-card relative w-full max-w-3xl p-5 sm:p-6 max-h-[94dvh] overflow-y-auto">
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
        <!-- Skipped once the server has already burned the frame into the photo,
             otherwise it would show twice. -->
        <img
          v-if="frameUrl && !framedUrl"
          :src="frameUrl"
          alt=""
          aria-hidden="true"
          class="absolute inset-0 h-full w-full object-fill pointer-events-none"
        />
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

      <!-- Keep / send your photo (Admin -> Save & Share) -->
      <div
        v-if="showSaveButton || showDirectSend || (shareOpts.auto_save && savedFile)"
        class="mt-3 flex flex-wrap items-center justify-center gap-3"
      >
        <!-- Manual mode: Save + optional arrow for the send options -->
        <div v-if="showSaveButton" class="relative inline-flex" data-share-menu>
          <button
            class="btn-ghost"
            :class="hasSendOptions ? '!rounded-r-none' : ''"
            :disabled="!!busy || saving || !!savedFile"
            @click="savePhoto"
          >
            <span v-if="saving" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
            <svg v-else-if="savedFile" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
            <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/></svg>
            {{ savedFile ? 'Saved' : 'Save' }}
          </button>
          <button
            v-if="hasSendOptions"
            class="btn-ghost !rounded-l-none border-l border-white/15 !px-3"
            :disabled="!!busy || sending"
            aria-haspopup="menu"
            :aria-expanded="menuOpen"
            aria-label="More ways to get your photo"
            @click="menuOpen = !menuOpen"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" :class="menuOpen ? 'rotate-180' : ''" class="transition-transform"><path d="m6 9 6 6 6-6"/></svg>
          </button>
          <div
            v-if="menuOpen"
            role="menu"
            class="absolute bottom-full mb-2 left-0 min-w-[13rem] glass-card p-1.5 z-10 bg-ink-900/95"
          >
            <button
              v-for="ch in ['email', 'whatsapp'].filter((c) => shareOpts[c])"
              :key="ch"
              role="menuitem"
              class="w-full text-left rounded-xl px-4 py-3 font-display hover:bg-white/10"
              @click="openSend(ch)"
            >{{ CHANNEL[ch].label }}</button>
          </div>
        </div>

        <!-- Auto mode: already saved, send options as direct buttons -->
        <template v-if="showDirectSend">
          <button
            v-for="ch in ['email', 'whatsapp'].filter((c) => shareOpts[c])"
            :key="ch"
            class="btn-ghost"
            :class="sendVia === ch ? 'ring-2 ring-electric-400' : ''"
            :disabled="!!busy || sending"
            @click="openSend(ch)"
          >
            <svg v-if="ch === 'email'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><path d="m22 7-10 6L2 7"/></svg>
            <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.4 8.4 0 0 1-12.4 7.4L3 21l2.1-5.4A8.4 8.4 0 1 1 21 11.5z"/></svg>
            {{ CHANNEL[ch].label }}
          </button>
        </template>
        <span v-if="shareOpts.auto_save && savedFile" class="hint !mt-0 inline-flex items-center gap-1.5">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
          Photo saved
        </span>
      </div>

      <!-- WhatsApp QR: guest messages the booth a code, the booth replies with the photo -->
      <div v-if="waShowQr" class="mt-4 rounded-2xl border border-white/10 bg-ink-900/60 p-4 sm:p-5">
        <div class="flex flex-col sm:flex-row items-center gap-5">
          <div class="w-52 h-52 shrink-0 rounded-2xl bg-white grid place-items-center overflow-hidden">
            <img v-if="waCode?.qr_svg && waSecondsLeft" :src="waCode.qr_svg" alt="QR code that opens WhatsApp with your photo code" class="w-full h-full" />
            <div v-else-if="waLoading" class="h-8 w-8 rounded-full border-2 border-ink-950 border-t-transparent animate-spin" aria-label="Loading"></div>
            <p v-else-if="waCode && !waSecondsLeft" class="text-ink-950 text-center px-4 font-display">Code expired</p>
            <p v-else-if="waCode" class="text-ink-950 text-center px-3 text-sm break-all">{{ waCode.link }}</p>
          </div>
          <div class="flex-1 min-w-0 text-center sm:text-left">
            <p class="font-display text-xl">Get it on WhatsApp</p>
            <ol class="mt-2 space-y-1 text-slate-200 list-decimal ml-5 text-left">
              <li>Scan with your phone camera.</li>
              <li>WhatsApp opens with a message. Tap <span class="font-semibold">send</span>.</li>
              <li>Your photo arrives in a few seconds.</li>
            </ol>
            <p v-if="waCode" class="mt-3 text-slate-300">
              Code <span class="font-display text-brand-300 tracking-widest">{{ waCode.code }}</span>
              <template v-if="waSecondsLeft"> · expires in <span class="tabular-nums">{{ waCountdown }}</span></template>
            </p>
            <p v-if="waSent" class="mt-1 text-emerald-300 inline-flex items-center gap-1.5" role="status">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
              Sent to {{ waSent }} {{ waSent === 1 ? 'phone' : 'phones' }} · friends can scan too
            </p>
            <div class="mt-4 flex flex-wrap gap-2 justify-center sm:justify-start">
              <button v-if="waCode && !waSecondsLeft" class="btn-primary btn-sm" :disabled="waLoading" @click="startWaCode">New code</button>
              <button
                v-if="shareOpts.whatsapp_mode === 'both'"
                class="btn-ghost btn-sm"
                @click="waTypeNumber = true; keyboardOpen = true; stopWaPolling()"
              >Type my number instead</button>
              <button class="btn-ghost btn-sm" @click="closeSend">Close</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Recipient panel (email, or WhatsApp in number mode) -->
      <form v-else-if="sendVia" class="mt-4 rounded-2xl border border-white/10 bg-ink-900/60 p-4" @submit.prevent="sendPhoto">
        <label class="label" for="share-to">{{ CHANNEL[sendVia].field }}</label>
        <div class="flex flex-col sm:flex-row gap-2">
          <input
            id="share-to"
            v-model="recipient[sendVia]"
            class="field text-lg"
            :type="sendVia === 'email' ? 'email' : 'tel'"
            :inputmode="sendVia === 'email' ? 'email' : 'tel'"
            :placeholder="CHANNEL[sendVia].placeholder"
            autocomplete="off"
            @focus="keyboardOpen = true"
          />
          <div class="flex gap-2 shrink-0">
            <button type="button" class="btn-ghost" :disabled="sending" @click="closeSend">Cancel</button>
            <button type="submit" class="btn-primary" :disabled="sending || !recipient[sendVia].trim()">
              <span v-if="sending" class="h-4 w-4 rounded-full border-2 border-ink-950 border-t-transparent animate-spin"></span>
              {{ sending ? 'Sending…' : 'Send' }}
            </button>
          </div>
        </div>
        <p v-if="sendVia === 'whatsapp'" class="hint">
          Include your country code. We only send the photo you asked for.
          <button v-if="waUsesQr" type="button" class="underline hover:text-slate-200 ml-1" @click="waTypeNumber = false; keyboardOpen = false; startWaCode()">Scan a QR code instead</button>
        </p>
        <div v-if="keyboardOpen" class="mt-3">
          <VirtualKeyboard
            :layout="CHANNEL[sendVia].layout"
            @key="onKey"
            @backspace="onBackspace"
            @close="keyboardOpen = false"
          />
        </div>
      </form>

      <p class="hint text-center mt-3">Enhance uses your configured AI image provider · Print sends to the default CUPS printer.</p>
    </div>

    <!-- toast -->
    <div v-if="toast" class="fixed bottom-6 left-1/2 -translate-x-1/2 glass rounded-2xl px-5 py-3 text-sm" aria-live="polite">
      {{ toast }}
    </div>

    <!-- save/send notice: errors persist with Retry until handled -->
    <transition name="notice">
      <div
        v-if="notice"
        class="fixed top-6 left-1/2 -translate-x-1/2 z-[60] w-[min(92vw,34rem)] glass-card px-5 py-4 flex items-center gap-4 bg-ink-900/90"
        :class="notice.kind === 'error' ? 'border-red-400/50' : 'border-emerald-400/40'"
        :role="notice.kind === 'error' ? 'alert' : 'status'"
      >
        <svg v-if="notice.kind === 'error'" class="shrink-0" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f87171" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>
        <svg v-else class="shrink-0" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
        <p class="flex-1 text-slate-100">{{ notice.text }}</p>
        <button v-if="notice.retry" class="btn-primary btn-sm shrink-0" @click="retryNotice">Retry</button>
        <button v-if="notice.kind === 'error'" class="btn-ghost btn-sm shrink-0" aria-label="Dismiss" @click="notice = null">✕</button>
      </div>
    </transition>
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
.notice-enter-active { transition: all 0.28s cubic-bezier(0.16, 1, 0.3, 1); }
.notice-leave-active { transition: all 0.18s ease-in; }
.notice-enter-from, .notice-leave-to { opacity: 0; transform: translate(-50%, -10px); }
@media (prefers-reduced-motion: reduce) {
  .modal { animation: none; }
}
</style>
