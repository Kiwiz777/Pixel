<script setup>
/**
 * KioskView - the public photobooth screen (no chrome / no nav bar).
 *
 *  - Background layer (color / image / video / slideshow) from Admin.
 *  - Live camera via the BROWSER (getUserMedia) so it works on a laptop and on
 *    the Pi's Chromium. Capture grabs a frame client-side and uploads it.
 *  - Borderless EMO-style <BotFace/> reacting to conversation state.
 *  - "Capture Photo" + conditional "Talk to Me" controls.
 *  - /ws/events drives face-detected auto-interact (when the Pi runs OpenCV).
 *  - Hidden admin access: type "admin" or 5-tap the top-right hot-corner (<3s).
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import BotFace from '../components/BotFace.vue'
import CaptureModal from '../components/CaptureModal.vue'
import ContactModal from '../components/ContactModal.vue'
import DiagnosticsOverlay from '../components/DiagnosticsOverlay.vue'
import QuizModal from '../components/QuizModal.vue'
import KioskBackground from '../components/KioskBackground.vue'
import { api, wsUrl } from '../lib/api'
import { useBot } from '../composables/useBot'
import { useCamera } from '../composables/useCamera'
import { useSecretAccess } from '../composables/useSecretAccess'
import { useFaceId } from '../composables/useFaceId'
import { useFaceWatch } from '../composables/useFaceWatch'

const LANG_NAMES = {
  en: 'English', 'ar-EG': 'Egyptian Arabic', 'ar-GULF': 'Gulf Arabic',
  ru: 'Russian', de: 'German', fr: 'French',
}
const langName = (c) => LANG_NAMES[c] || 'English'

const router = useRouter()
const settings = ref({
  interact_button_visible: true,
  bot_face_visible: true,
  auto_interact_mode: true,
  face_recognition_enabled: true,
  quiz_enabled: true,
  active_quiz_id: null,
  kiosk_camera_autostart: true,
  camera_idle_off_seconds: 0,
  camera_off_after_session: false,
  default_language: 'en',
  dev_mode: false,
  kiosk_bg_mode: 'none',
  kiosk_bg_color: '#070b16',
  kiosk_bg_media: [],
  kiosk_bg_slideshow_ms: 6000,
  kiosk_bg_dim: 35,
  capture_aspect: 16 / 9,
  capture_countdown_seconds: 5,
  frame_overlay_path: '',
  frame_overlay_display: 'both',
  contact_form_enabled: true,
  diag_show_conversation: false,
  diag_show_ai_latency: false,
})
const capture = ref(null)
const capturing = ref(false)
const countdown = ref(0) // seconds left on the "get ready" timer, 0 = not counting
let countdownTimer = null
const showQuiz = ref(false)
const showContact = ref(false)
const rewardSession = ref(null) // reward config applied to the next capture
const quizAvailable = computed(() => settings.value.quiz_enabled && settings.value.active_quiz_id != null)
// Width/height of the paper, from Admin. 0 means "auto" - the printer fits and
// rotates the photo itself, so nothing is cropped and there is no target shape.
const printAspect = computed(() => Number(settings.value.capture_aspect) || 0)
// Passed to capture(): null leaves the sensor frame completely untouched.
const cropAspect = computed(() => printAspect.value || null)
// Layout only. In auto mode nothing is cropped, so the viewfinder takes the
// camera's real shape - anything else makes `object-cover` crop the preview and
// show a tighter shot than the one that actually prints.
const stageAspect = computed(() => printAspect.value || cam.videoAspect.value || 16 / 9)

// ---- photo frame overlay --------------------------------------------------
const frameUrl = computed(() =>
  settings.value.frame_overlay_path ? `/media/frames/${settings.value.frame_overlay_path}` : '',
)
const frameDisplay = computed(() => settings.value.frame_overlay_display || 'both')
const frameOnCapture = computed(
  () => !!frameUrl.value && ['capture', 'both'].includes(frameDisplay.value),
)
const frameInModal = computed(
  () => !!frameUrl.value && ['modal', 'both'].includes(frameDisplay.value),
)
// Height drives the box (aspect-ratio derives the width), capped so a portrait
// stage still fits the screen. min() keeps the ratio exact at any viewport,
// which is what makes the preview a true preview.
const stageStyle = computed(() => ({
  aspectRatio: String(stageAspect.value),
  width: `min(100%, ${(72 * stageAspect.value).toFixed(2)}vh)`,
}))
// Camera intentionally idle (off with no error) — show a welcoming prompt, not a warning.
const cameraIdle = computed(() => !cam.active.value && !cam.error.value)
const greeting = ref('')
const overlayCanvas = ref(null)
const inFlow = ref(false) // a recognition/conversation flow is running

const bot = useBot()
const cam = useCamera()
const faceId = useFaceId()
const { tapCorner } = useSecretAccess(() => router.push('/admin'))
const faceWatch = useFaceWatch(faceId, {
  onTrigger: handleTrigger,
  recognize: (d) => recognizePeek(d),
  isDevMode: () => settings.value.dev_mode,
})

let eventWs = null
let greetTimer = null

// Language pinned by a double-tap for this conversation ('' = auto-detect).
const forcedLang = ref('')

const talkLabel = computed(() => {
  if (bot.isRecording()) {
    return forcedLang.value === 'ar-EG'
      ? 'بسمعك… (اسكت عشان تبعت)'
      : 'Listening… (pause to send)'
  }
  if (bot.conversing.value || inFlow.value) return 'End chat'
  return 'Talk to Me'
})

function flashGreeting(text) {
  greeting.value = text
  clearTimeout(greetTimer)
  greetTimer = setTimeout(() => (greeting.value = ''), 6000)
}

// ---- the structured recognition flow --------------------------------------
// Triggered only after a face has been held in frame ~3s (see useFaceWatch).
async function handleTrigger(descriptor) {
  if (inFlow.value || bot.conversing.value || capture.value) return
  if (!settings.value.auto_interact_mode) return
  inFlow.value = true
  try {
    let matched = null
    try {
      matched = (await api.matchFace(descriptor)).match
    } catch {
      /* match failed; treat as new guest */
    }

    if (matched && matched.is_admin) {
      // Recognised operator: stay quiet, don't spend AI tokens.
      flashGreeting('')
      return
    }
    if (matched) {
      const lang = matched.language || settings.value.default_language
      flashGreeting(`Hi ${matched.name}!`)
      await bot.converse(lang, buildReturningOpener(matched, lang))
    } else {
      await onboardNewUser(descriptor)
    }
  } finally {
    inFlow.value = false
  }
}

// A returning guest: phrase the greeting from how long ago we last saw them.
function buildReturningOpener(m, lang) {
  const ln = langName(lang)
  const interests = m.bio ? ` Their interests/notes: "${m.bio}".` : ''
  let recency = 'You have met them before.'
  if (m.last_seen) {
    const mins = (Date.now() - new Date(m.last_seen).getTime()) / 60000
    if (mins < 2) recency = 'You saw them literally moments ago — playfully note they are back already.'
    else if (mins < 60) recency = `You last saw them about ${Math.round(mins)} minute(s) ago — welcome them back briefly.`
    else if (mins < 1440) recency = `You last saw them about ${Math.round(mins / 60)} hour(s) ago — warmly welcome them back.`
    else recency = `It has been about ${Math.round(mins / 1440)} day(s) — give them a warm welcome back.`
  }
  return `A returning guest named ${m.name} is here. ${recency}${interests} Greet them warmly BY NAME in one short sentence, then ask a friendly question about their interests so they chat. Keep it brief. Reply ONLY in ${ln}.`
}

// A brand-new face: gather name + interests, register them, and acknowledge.
async function onboardNewUser(descriptor) {
  const lang = settings.value.default_language
  const ln = langName(lang)
  flashGreeting('Hello there!')

  // Grab a face snapshot now, while they're framed, for the Admin thumbnail.
  let faceBlob = null
  try {
    faceBlob = await cam.capture(0.92, cropAspect.value)
  } catch {
    /* snapshot is best-effort */
  }

  await bot.ask(`Greet a brand-new guest warmly, say you'd love to get to know them, and ask their name. One or two short sentences. Reply ONLY in ${ln}.`, { direction: true })
  const nameResp = await bot.listenOnce(lang)
  if (!nameResp) return // guest walked off
  const name = await extractName(nameResp)

  await bot.ask(`Nice to meet ${name}. Say it's lovely to meet them by name and ask what they're into — hobbies or interests. Keep it short. Reply ONLY in ${ln}.`, { direction: true })
  const interestsResp = (await bot.listenOnce(lang)) || ''
  const bio = await extractInterests(interestsResp)

  let saved = false
  try {
    await api.enrollFace({ name, bio, language: lang, descriptor, faceBlob })
    saved = true
  } catch {
    /* enrolment failed; still close warmly */
  }

  await bot.ask(
    saved
      ? `You just saved ${name} as a new friend. In a fun, warm way tell them that now you two are friends and you'll recognise them whenever you see them again, then invite them to take a photo. Short. Reply ONLY in ${ln}.`
      : `Thank ${name} warmly and invite them to take a photo. Short. Reply ONLY in ${ln}.`,
    { direction: true },
  )
}

// Pull a clean first name out of a free-form spoken reply (persona-free LLM call).
async function extractName(transcript) {
  try {
    const r = await api.extract(
      transcript,
      "Extract the person's given/first name. Reply with ONLY the name in its original language. If there is clearly no name, reply exactly: Friend",
    )
    let n = (r?.result || '').trim().replace(/^["'.,]+|["'.,]+$/g, '')
    if (!n || /^friend$/i.test(n) || n.length > 40) return n ? n.split(/\s+/)[0] : 'Friend'
    return n.split(/\s+/).slice(0, 2).join(' ') // allow up to two words
  } catch {
    return 'Friend'
  }
}

// Summarise interests into a short note for the bio.
async function extractInterests(transcript) {
  if (!transcript) return ''
  try {
    const r = await api.extract(
      transcript,
      'Summarise this person\'s interests/hobbies as a short comma-separated list (max ~12 words). If none, reply with an empty string.',
    )
    return (r?.result || transcript).trim().slice(0, 200)
  } catch {
    return transcript.slice(0, 200)
  }
}

// Non-mutating match used only to label the dev overlay.
async function recognizePeek(descriptor) {
  try {
    const m = (await api.matchFace(descriptor, true)).match
    return m ? { name: m.name, distance: m.distance } : { name: 'unknown', distance: null }
  } catch {
    return null
  }
}

// ---- server-side face events (Pi OpenCV path) -----------------------------
function connectEvents() {
  eventWs = new WebSocket(wsUrl('/ws/events'))
  eventWs.onmessage = (ev) => {
    const data = JSON.parse(ev.data)
    if (data.type === 'face_detected' && data.auto_interact) onServerFace(data)
  }
  eventWs.onclose = () => setTimeout(connectEvents, 2000)
}

async function onServerFace(data) {
  if (inFlow.value || bot.conversing.value || capture.value) return
  if (!settings.value.auto_interact_mode) return
  const name = data.identity && data.identity !== 'unknown' ? data.identity : null
  inFlow.value = true
  try {
    flashGreeting(name ? `Hi ${name}!` : 'Hello there!')
    await bot.converse(
      settings.value.default_language,
      name
        ? `Greet ${name} warmly BY NAME in one short sentence, then ask a friendly question so they reply.`
        : 'A new guest stepped up. Greet them warmly in one short sentence, then ask a question so they reply.',
    )
  } finally {
    inFlow.value = false
  }
}

// ---- actions --------------------------------------------------------------
/**
 * First press with the camera off only opens the viewfinder - guests need to
 * see their framing before anything is taken. The second press shoots.
 */
async function onCaptureButton() {
  if (!cam.active.value) {
    await startCamera()
    return
  }
  await runCapture()
}

function cancelCountdown() {
  if (countdownTimer) clearInterval(countdownTimer)
  countdownTimer = null
  countdown.value = 0
}

/** Count down (if configured), then grab the frame. */
async function runCapture() {
  if (capturing.value || countdown.value) return

  const seconds = Math.max(0, Math.min(30, Number(settings.value.capture_countdown_seconds) || 0))
  if (seconds > 0) {
    countdown.value = seconds
    const finished = await new Promise((resolve) => {
      countdownTimer = setInterval(() => {
        countdown.value -= 1
        if (countdown.value <= 0) {
          cancelCountdown()
          resolve(true)
        }
      }, 1000)
    })
    // Camera stopped (or the view unmounted) mid-count - don't shoot into nothing.
    if (!finished || !cam.active.value) return
  }

  capturing.value = true
  try {
    const blob = await cam.capture(0.92, cropAspect.value)
    capture.value = await api.capture(blob)
  } catch {
    flashGreeting('Capture failed — try again.')
  } finally {
    capturing.value = false
  }
}

// ---- quiz reward -> capture session ---------------------------------------
// A photo-based reward (prints / ai_enhance) launches a capture with the
// reward context passed to the CaptureModal.
async function onQuizReward(reward) {
  rewardSession.value = reward
  // A reward capture is already "armed" by winning, so open the camera and
  // shoot rather than making them press again.
  if (!cam.active.value) await startCamera()
  if (cam.active.value) await runCapture()
}

function onCaptureClosed() {
  capture.value = null
  rewardSession.value = null
  // On-demand camera: power the webcam back down once the session ends.
  if (settings.value.camera_off_after_session) stopCamera()
}

// ---- camera power management ----------------------------------------------
let idleTimer = null

function stopCamera() {
  faceWatch.stop()
  cam.stop()
  cancelCountdown() // no counting down to a shot the camera can't take
  // The camera going idle means the guest walked away. Clear the thread so the
  // next person doesn't inherit a stranger's conversation.
  bot.resetConversation()
  if (idleTimer) clearTimeout(idleTimer)
}

// Reset the inactivity countdown; turn the camera off after N idle seconds.
function markActivity() {
  if (idleTimer) clearTimeout(idleTimer)
  const secs = Number(settings.value.camera_idle_off_seconds) || 0
  if (secs > 0 && cam.active.value) {
    idleTimer = setTimeout(() => {
      // Never kill the camera mid-conversation or mid-capture.
      if (bot.conversing.value || bot.isRecording() || inFlow.value || capture.value) {
        markActivity()
      } else {
        stopCamera()
      }
    }, secs * 1000)
  }
}

// Tap = start listening with automatic language detection.
// Double-tap (second tap within this window) = pin Egyptian Arabic.
//
// The recording starts on the FIRST tap either way - the language hint isn't
// sent until the clip is uploaded, seconds later, so the second tap only has
// to arrive before the guest stops speaking. That means no artificial delay
// waiting to see whether a double-tap is coming.
const DOUBLE_TAP_MS = 600
const DIALECT_LANG = 'ar-EG'
let talkStartedAt = 0

async function toggleTalk() {
  const active = bot.conversing.value || bot.isRecording() || inFlow.value

  if (active) {
    // Inside the window, a second tap means "this is Egyptian Arabic", not
    // "stop" - otherwise double-tapping would just cancel the turn.
    if (Date.now() - talkStartedAt < DOUBLE_TAP_MS && forcedLang.value !== DIALECT_LANG) {
      forcedLang.value = DIALECT_LANG
      bot.setConversationLanguage(DIALECT_LANG)
      flashGreeting('مصري — اتكلم عادي')
      return
    }
    inFlow.value = false
    forcedLang.value = ''
    bot.endConversation()
    return
  }

  talkStartedAt = Date.now()
  forcedLang.value = ''
  // Auto-detect unless the Admin pinned a language for the venue.
  bot.converse(settings.value.multilingual_autodetect ? null : settings.value.default_language)
}

// Start (or retry) the camera, then face watching once models are ready.
async function startCamera() {
  await cam.start()
  if (cam.active.value && cam.videoRef.value) {
    // Face detection (dwell-watch) is gated by the master switch in Admin.
    if (settings.value.face_recognition_enabled) {
      await faceId.loadModels().catch(() => {})
      faceWatch.start(cam.videoRef.value, overlayCanvas.value)
    } else {
      faceWatch.stop()
    }
    markActivity() // arm the inactivity-off countdown
  }
}

onMounted(async () => {
  try {
    settings.value = { ...settings.value, ...(await api.publicSettings()) }
  } catch {
    /* keep defaults */
  }
  // Auto-start the camera up front unless the admin turned it off (e.g. a
  // quiz-first kiosk that leads with the buttons and starts the camera on demand).
  if (settings.value.kiosk_camera_autostart) {
    await startCamera()
  }
  connectEvents()
  window.addEventListener('pointerdown', markActivity)
})

onBeforeUnmount(() => {
  if (eventWs) {
    eventWs.onclose = null
    eventWs.close()
  }
  faceWatch.stop()
  clearTimeout(greetTimer)
  if (idleTimer) clearTimeout(idleTimer)
  cancelCountdown()
  window.removeEventListener('pointerdown', markActivity)
})
</script>

<template>
  <div class="relative min-h-dvh w-full overflow-hidden">
    <!-- background layer -->
    <KioskBackground
      :mode="settings.kiosk_bg_mode"
      :color="settings.kiosk_bg_color"
      :media="settings.kiosk_bg_media"
      :slideshow-ms="settings.kiosk_bg_slideshow_ms"
      :dim="settings.kiosk_bg_dim"
    />

    <!-- hidden hot-corner for admin (top-right). Invisible, tap 5× in 3s. -->
    <button
      class="fixed top-0 right-0 h-16 w-16 z-50 opacity-0"
      aria-hidden="true" tabindex="-1" @click="tapCorner"
    ></button>

    <!-- video stage -->
    <main class="relative z-10 min-h-dvh grid place-items-center px-4 py-6">
      <!-- With the camera on this is a framed viewfinder. With it off the panel
           would just be an empty glass box, so it becomes a transparent
           full-area layer - the bot face and speech bubble still need somewhere
           to sit, they just sit on the kiosk background instead. -->
      <div
        class="relative overflow-hidden"
        :class="cam.active.value
          ? 'mx-auto max-w-5xl rounded-3xl glass shadow-glass'
          : 'absolute inset-0'"
        :style="cam.active.value ? stageStyle : undefined"
      >
        <!-- browser camera feed (mirrored like a selfie) -->
        <video
          :ref="(el) => (cam.videoRef.value = el)"
          class="absolute inset-0 h-full w-full object-cover"
          style="transform: scaleX(-1)"
          autoplay playsinline muted
          v-show="cam.active.value"
        ></video>

        <!-- Photo frame preview, so guests see the border they'll be printed in -->
        <img
          v-if="frameOnCapture && cam.active.value"
          :src="frameUrl"
          alt=""
          aria-hidden="true"
          class="absolute inset-0 h-full w-full object-fill pointer-events-none z-10"
        />

        <!-- "Get ready" countdown -->
        <transition name="fade">
          <div
            v-if="countdown"
            class="absolute inset-0 z-20 grid place-items-center bg-ink-950/40 backdrop-blur-[2px]"
            role="status"
            aria-live="assertive"
          >
            <div class="text-center">
              <div
                :key="countdown"
                class="font-display font-black text-white leading-none countdown-pop"
                style="font-size: clamp(5rem, 22vh, 12rem)"
              >{{ countdown }}</div>
              <p class="font-display text-xl text-electric-300 mt-2">Get ready!</p>
            </div>
          </div>
        </transition>

        <!-- Developer mode: face-detection / recognition overlay -->
        <canvas
          ref="overlayCanvas"
          v-show="settings.dev_mode && cam.active.value"
          class="absolute inset-0 h-full w-full object-cover pointer-events-none"
        ></canvas>
        <span
          v-if="settings.dev_mode"
          class="absolute top-3 left-3 z-20 text-[11px] font-display bg-ink-950/70 text-electric-300 px-2.5 py-1 rounded-full"
        >DEV · recognition overlay</span>

        <!-- camera error / permission prompt (intentional idle uses the hero dock below) -->
        <div v-if="!cam.active.value && !cameraIdle" class="absolute inset-0 grid place-items-center text-center px-6">
          <div>
            <div class="mx-auto mb-4 h-14 w-14 rounded-2xl glass grid place-items-center">
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#7df0ff" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
            </div>
            <p class="font-display text-xl">Camera is off</p>
            <p class="hint max-w-sm mx-auto">{{ cam.error.value || 'Allow camera access to start the photobooth.' }}</p>
            <button class="btn-accent mt-4" @click="startCamera">Enable camera</button>
          </div>
        </div>

        <!-- vignette (belongs to the viewfinder, not the bare background) -->
        <div v-if="cam.active.value" class="pointer-events-none absolute inset-0" style="background: radial-gradient(120% 80% at 50% 0%, transparent 60%, rgba(7,11,22,0.5) 100%)"></div>

        <!-- floating EMO face -->
        <!-- Sits higher with the camera off: the stage is full-screen then, so
             the bottom-right corner is where the control dock now lives. -->
        <div
          v-if="settings.bot_face_visible"
          class="absolute right-4 sm:right-6 animate-float"
          :class="cam.active.value ? 'bottom-4 sm:bottom-6' : 'bottom-44 sm:bottom-48'"
        >
          <BotFace :state="bot.botState.value" mood="happy" :size="168" />
        </div>

        <!-- speech bubble -->
        <transition name="bubble">
          <div v-if="greeting || bot.lastReply.value" class="absolute left-4 sm:left-6 bottom-6 max-w-sm glass-card px-4 py-3">
            <p class="font-display text-sm text-electric-300">Pixel says</p>
            <p class="text-slate-100">{{ bot.lastReply.value || greeting }}</p>
          </div>
        </transition>
      </div>
    </main>

    <!-- control dock: always at the bottom, camera on or off -->
    <footer class="absolute bottom-0 inset-x-0 z-20 px-4 pb-7 sm:pb-9 grid place-items-center">
      <div class="grid place-items-center gap-4 w-full">
      <transition name="fade">
        <p v-if="!cam.active.value" class="font-display text-lg sm:text-xl text-slate-100 text-center px-6">
          {{ quizAvailable ? 'Ready when you are — take the quiz or snap a photo' : 'Tap Capture Photo to open the camera' }}
        </p>
      </transition>
      <!-- Wraps: with quiz, contact and talk all enabled this is four large
           buttons (~880px), which overflows any screen narrower than a 1080
           portrait panel. -->
      <div class="glass-card px-4 py-3 flex flex-wrap items-center justify-center gap-3 max-w-5xl mx-auto">
        <button
          class="btn-primary text-lg px-7 py-4"
          :disabled="capturing || !!countdown"
          @click="onCaptureButton"
        >
          <span v-if="capturing" class="h-5 w-5 rounded-full border-2 border-ink-950 border-t-transparent animate-spin"></span>
          <svg v-else width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
          {{ countdown ? 'Get ready…' : cam.active.value ? 'Capture Now' : 'Capture Photo' }}
        </button>

        <button
          v-if="quizAvailable"
          class="btn-ghost text-lg px-7 py-4"
          @click="showQuiz = true"
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 17h.01" stroke-linecap="round"/></svg>
          Take the Quiz
        </button>

        <button
          v-if="settings.contact_form_enabled"
          class="btn-ghost text-lg px-7 py-4"
          @click="showContact = true"
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><path d="m22 7-10 6L2 7"/></svg>
          Contact Us
        </button>

        <button
          v-if="settings.interact_button_visible"
          class="btn-accent text-lg px-7 py-4"
          :data-rec="bot.isRecording()"
          @click="toggleTalk"
        >
          <span v-if="bot.isRecording() || bot.conversing.value || inFlow" class="relative flex h-3 w-3">
            <span class="absolute inline-flex h-full w-full rounded-full bg-white/70 animate-ping"></span>
            <span class="relative inline-flex rounded-full h-3 w-3 bg-white"></span>
          </span>
          <svg v-else width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4"/></svg>
          {{ talkLabel }}
        </button>
      </div>
      </div>
      <p v-if="bot.error.value" class="hint text-red-300 mt-2" role="alert">{{ bot.error.value }}</p>
    </footer>

    <!-- on-site diagnostics (Admin -> General) -->
    <DiagnosticsOverlay
      :show-conversation="settings.diag_show_conversation"
      :show-latency="settings.diag_show_ai_latency"
    />

    <!-- contact us -->
    <ContactModal
      v-if="showContact"
      :language="settings.default_language"
      @close="showContact = false"
    />

    <!-- post-capture modal -->
    <CaptureModal
      v-if="capture"
      :capture="capture"
      :reward="rewardSession"
      :aspect="stageAspect"
      :frame-url="frameInModal ? frameUrl : ''"
      @retake="capture = null"
      @close="onCaptureClosed"
      @printed="onCaptureClosed"
    />

    <!-- quiz / MCQ modal -->
    <QuizModal
      v-if="showQuiz"
      :wheel-style="settings.wheel_style"
      @close="showQuiz = false"
      @reward="onQuizReward"
    />
  </div>
</template>

<style scoped>
.bubble-enter-active { transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1); }
.bubble-leave-active { transition: all 0.2s ease-in; }
.bubble-enter-from, .bubble-leave-to { opacity: 0; transform: translateY(10px); }

.fade-enter-active { transition: opacity 0.4s ease 0.15s; }
.fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* Each countdown number punches in — :key on the element restarts it per tick,
   giving the beat a visible pulse instead of a silently changing glyph. */
.countdown-pop {
  animation: countdown-pop 0.9s cubic-bezier(0.16, 1, 0.3, 1);
  text-shadow: 0 0.06em 0.5em rgb(0 0 0 / 0.55);
}
@keyframes countdown-pop {
  0% { opacity: 0; transform: scale(1.5); }
  35% { opacity: 1; transform: scale(1); }
  100% { opacity: 0.9; transform: scale(1); }
}

@media (prefers-reduced-motion: reduce) {
  .countdown-pop { animation: none; }
}
</style>
