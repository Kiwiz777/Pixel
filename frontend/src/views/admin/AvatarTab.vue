<script setup>
/**
 * Avatar & Welcome tab: pick the kiosk character, preview its animations,
 * and set what happens when a guest steps up to the camera (wave + welcome
 * line, or a full voice chat), including the welcome lines and timing.
 *
 * Welcome voice can be "saved": each line is synthesised once into an MP3 on
 * the kiosk (POST /api/ai/voice-clips) and replayed offline at no token cost.
 */
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../../lib/api'
import BotFace from '../../components/BotFace.vue'
import ToggleSwitch from '../../components/ToggleSwitch.vue'
import WelcomeLinesEditor from './WelcomeLinesEditor.vue'
import { AVATARS } from '../../components/avatars'

const props = defineProps({ settings: Object })
const emit = defineEmits(['save', 'reload'])

const form = reactive({
  avatar_style: 'robot',
  avatar_name: 'Pixel',
  video_avatar_shape: 'rounded',
  video_avatar_scale: 1.6,
  auto_interact_style: 'welcome',
  welcome_messages: '',
  welcome_back_messages: '',
  welcome_speak: true,
  welcome_voice_mode: 'live',
  greet_dwell_seconds: 2,
  greet_cooldown_seconds: 20,
})

watch(
  () => props.settings,
  (s) => s && Object.keys(form).forEach((k) => (form[k] = s[k] ?? form[k])),
  { immediate: true, deep: true },
)

// Preview: cycle the selected avatar through each state.
const PREVIEW_STATES = [
  { id: 'idle', label: 'Idle' },
  { id: 'listening', label: 'Listening' },
  { id: 'thinking', label: 'Thinking' },
  { id: 'speaking', label: 'Speaking' },
  { id: 'wave', label: 'Welcome wave' },
]
const preview = ref('idle')
let waveTimer = null
function setPreview(id) {
  preview.value = id
  clearTimeout(waveTimer)
  if (id === 'wave') waveTimer = setTimeout(() => (preview.value = 'idle'), 2400)
}

// ---- saved voice clips -------------------------------------------------------
const generating = ref(false)
const voiceMsg = ref('')
const voiceErr = ref(false)

const linesOf = (text) => String(text || '').split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
const allLines = computed(() => [...new Set([...linesOf(form.welcome_messages), ...linesOf(form.welcome_back_messages)])])
const currentVoice = computed(() => {
  const s = props.settings || {}
  return (s.tts_provider || 'openai') === 'elevenlabs' ? s.tts_voice_id || '' : s.openai_tts_voice || 'alloy'
})
const clips = computed(() => props.settings?.welcome_voice_clips || {})

/** saved | stale (older voice) | missing | dynamic ({name}, can't be saved) */
function lineStatus(line) {
  if (line.includes('{name}')) return 'dynamic'
  const c = clips.value[line]
  if (!c) return 'missing'
  return c.voice === currentVoice.value ? 'saved' : 'stale'
}
const toGenerate = computed(() => allLines.value.filter((l) => ['missing', 'stale'].includes(lineStatus(l))).length)

async function generateVoice() {
  generating.value = true
  voiceMsg.value = ''
  voiceErr.value = false
  try {
    const res = await api.saveVoiceClips(allLines.value)
    const failed = Object.keys(res.errors || {}).length
    voiceErr.value = failed > 0
    voiceMsg.value = failed
      ? `${failed} line(s) couldn't be generated: ${Object.values(res.errors)[0]}`
      : `Voice saved — ${Object.keys(res.clips).length} line(s) ready offline (${res.created} newly generated).`
    save() // persist the lines + mode alongside the new clips
  } catch (e) {
    voiceErr.value = true
    voiceMsg.value = e.message || 'Generating failed. Check the TTS key in AI Providers.'
  } finally {
    generating.value = false
  }
}

// ---- real-person video avatar ---------------------------------------------------
const VIDEO_SLOTS = [
  { id: 'idle', label: 'Idle', required: true, hint: '5–10 s loop: standing, smiling, blinking, small natural moves.' },
  { id: 'talking', label: 'Talking', hint: '5–10 s loop of her speaking (sound is ignored). Plays while the voice talks.' },
  { id: 'wave', label: 'Welcome wave', hint: '2–4 s: a friendly wave or "hello" gesture. Plays once per guest.' },
  { id: 'listening', label: 'Listening', hint: 'Optional loop: attentive, slight nod. Chat mode only.' },
  { id: 'thinking', label: 'Thinking', hint: 'Optional loop: looking aside, thoughtful. Chat mode only.' },
]
const videoFiles = computed(() => props.settings?.video_avatar || {})
const videoProp = computed(() => ({
  clips: Object.fromEntries(
    Object.entries(videoFiles.value).filter(([, f]) => f).map(([k, f]) => [k, `/media/avatar/${f}`]),
  ),
  shape: form.video_avatar_shape,
}))
const videoBusy = ref('')
const videoMsg = ref('')

async function uploadClip(state, e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  videoBusy.value = state
  videoMsg.value = ''
  try {
    await api.uploadAvatarVideo(state, file)
    emit('reload')
  } catch (err) {
    videoMsg.value = err.message || 'Upload failed.'
  } finally {
    videoBusy.value = ''
  }
}

async function removeClip(state) {
  videoBusy.value = state
  try {
    await api.deleteAvatarVideo(state)
    emit('reload')
  } catch (err) {
    videoMsg.value = err.message || 'Could not remove the clip.'
  } finally {
    videoBusy.value = ''
  }
}

function save() {
  emit('save', {
    ...form,
    avatar_name: form.avatar_name.trim() || 'Pixel',
    video_avatar_scale: Math.min(2.5, Math.max(1, Number(form.video_avatar_scale) || 1.6)),
    greet_dwell_seconds: Math.max(0.5, Number(form.greet_dwell_seconds) || 2),
    greet_cooldown_seconds: Math.max(5, Number(form.greet_cooldown_seconds) || 20),
  })
}
</script>

<template>
  <section>
    <header class="mb-6">
      <h1 class="font-display text-3xl font-semibold">Avatar &amp; Welcome</h1>
      <p class="text-slate-400 mt-1">Choose who greets your guests, and how.</p>
    </header>

    <!-- Character -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <h2 class="font-display text-lg font-semibold mb-4">Character</h2>
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3" role="radiogroup" aria-label="Kiosk avatar">
        <button
          v-for="a in AVATARS" :key="a.id"
          type="button" role="radio" :aria-checked="form.avatar_style === a.id"
          class="rounded-2xl border p-3 text-left transition-colors"
          :class="form.avatar_style === a.id ? 'border-brand-400/60 bg-brand-500/10' : 'border-white/10 hover:bg-white/5'"
          @click="form.avatar_style = a.id"
        >
          <div class="h-32 grid place-items-center">
            <BotFace :avatar="a.id" :size="a.video ? 84 : 104" :video="videoProp" />
          </div>
          <p class="font-display font-semibold mt-2">{{ a.label }}</p>
          <p class="hint">{{ a.description }}</p>
        </button>
      </div>

      <div class="mt-6 grid md:grid-cols-[auto,1fr] gap-6 items-center">
        <div class="h-56 w-56 mx-auto grid place-items-center rounded-3xl bg-ink-950/60 border border-white/10">
          <BotFace
            :avatar="form.avatar_style"
            :state="preview === 'wave' ? 'idle' : preview"
            :waving="preview === 'wave'"
            :size="150"
            :video="videoProp"
          />
        </div>
        <div>
          <p class="label">Preview</p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="p in PREVIEW_STATES" :key="p.id"
              type="button" class="btn-ghost btn-sm"
              :class="preview === p.id ? 'ring-2 ring-brand-400' : ''"
              :aria-pressed="preview === p.id"
              @click="setPreview(p.id)"
            >{{ p.label }}</button>
          </div>
          <div class="mt-5 max-w-xs">
            <label class="label" for="avatar-name">Name on the speech bubble</label>
            <input id="avatar-name" v-model="form.avatar_name" class="field" maxlength="24" placeholder="Pixel" />
            <p class="hint">Shows as "{{ form.avatar_name || 'Pixel' }} says". To change how it talks, edit the persona in General.</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Real person: video clips -->
    <div v-if="form.avatar_style === 'video'" class="glass-card p-5 sm:p-6 mb-5">
      <h2 class="font-display text-lg font-semibold">Real person — video clips</h2>
      <p class="hint !mt-0.5">
        Short muted clips of the same person, same framing and background. The kiosk switches between
        them as she listens, talks and waves; her voice is still your text-to-speech. MP4 (H.264) or WebM, up to 80 MB each.
      </p>

      <ul class="mt-4 grid sm:grid-cols-2 gap-3">
        <li v-for="slot in VIDEO_SLOTS" :key="slot.id" class="flex gap-3 rounded-2xl border border-white/10 bg-ink-900/50 p-3">
          <div class="h-28 w-20 shrink-0 overflow-hidden rounded-xl bg-ink-950 grid place-items-center">
            <video
              v-if="videoFiles[slot.id]"
              :src="`/media/avatar/${videoFiles[slot.id]}`"
              class="h-full w-full object-cover" muted loop autoplay playsinline
            ></video>
            <span v-else class="hint !mt-0 text-center px-1">No clip</span>
          </div>
          <div class="min-w-0 flex-1">
            <p class="font-display font-semibold">
              {{ slot.label }}
              <span v-if="slot.required" class="text-xs text-amber-300 font-sans font-normal ml-1">required</span>
            </p>
            <p class="hint">{{ slot.hint }}</p>
            <div class="mt-2 flex gap-2">
              <label class="btn-ghost btn-sm cursor-pointer">
                <input type="file" accept="video/mp4,video/webm,.m4v" class="hidden" @change="uploadClip(slot.id, $event)" />
                <span v-if="videoBusy === slot.id" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
                {{ videoFiles[slot.id] ? 'Replace' : 'Upload' }}
              </label>
              <button v-if="videoFiles[slot.id]" type="button" class="btn-ghost btn-sm" :disabled="videoBusy === slot.id" @click="removeClip(slot.id)">Remove</button>
            </div>
          </div>
        </li>
      </ul>
      <p v-if="videoMsg" class="hint text-red-300 mt-2" role="alert">{{ videoMsg }}</p>

      <div class="mt-5 grid sm:grid-cols-2 gap-4">
        <div>
          <label class="label" for="va-shape">Show her as</label>
          <select id="va-shape" v-model="form.video_avatar_shape" class="field">
            <option value="rounded">Rounded card</option>
            <option value="circle">Circle</option>
            <option value="cutout">Cut-out (transparent WebM)</option>
          </select>
          <p class="hint">Cut-out needs clips exported with a transparent background.</p>
        </div>
        <div>
          <label class="label" for="va-scale">Size on the kiosk ({{ Number(form.video_avatar_scale).toFixed(1) }}×)</label>
          <input id="va-scale" v-model.number="form.video_avatar_scale" type="range" min="1" max="2.5" step="0.1" class="w-full accent-brand-500" />
        </div>
      </div>

      <details class="mt-5 rounded-2xl border border-white/10 bg-ink-900/40 p-4">
        <summary class="font-display font-semibold cursor-pointer">Where do the clips come from?</summary>
        <div class="hint space-y-2 mt-2 text-slate-300">
          <p><span class="text-slate-100">Film a real host:</span> phone on a tripod, portrait, plain or green background,
            even light. Record her idle (just standing, smiling), talking (say anything), and a wave. Trim each to the lengths above.</p>
          <p><span class="text-slate-100">Or generate one:</span> AI avatar services (e.g. HeyGen, Synthesia, D-ID) make
            photoreal presenters — export the same states as short clips. Many can export a transparent WebM for the cut-out look.</p>
          <p>Keep framing, lighting and position identical across clips so the switches are seamless.
            Make loops start and end in the same pose. 720p is plenty for the Pi.</p>
          <p>Use footage only of people who have agreed to it, and check the service's licence for commercial events.</p>
        </div>
      </details>
    </div>

    <!-- Welcome on arrival -->
    <div class="glass-card p-5 sm:p-6 mb-5 divide-y divide-white/10">
      <div class="pb-4">
        <h2 class="font-display text-lg font-semibold">When a guest steps up</h2>
        <p class="hint !mt-0.5">
          Runs once a face has been held in front of the camera. Needs Face Recognition and
          Auto-Interact on (General tab) and the camera running.
        </p>
      </div>

      <div class="py-4 grid sm:grid-cols-2 gap-3" role="radiogroup" aria-label="Greeting style">
        <button
          v-for="m in [
            { id: 'welcome', label: 'Welcome only', hint: 'Avatar waves and says one welcome line. No chat, no microphone.' },
            { id: 'chat', label: 'Welcome + chat', hint: 'Greets, then starts a voice conversation (and learns new faces).' },
          ]"
          :key="m.id" type="button" role="radio" :aria-checked="form.auto_interact_style === m.id"
          class="rounded-2xl border p-4 text-left transition-colors"
          :class="form.auto_interact_style === m.id ? 'border-brand-400/60 bg-brand-500/10' : 'border-white/10 hover:bg-white/5'"
          @click="form.auto_interact_style = m.id"
        >
          <span class="font-display font-semibold">{{ m.label }}</span>
          <span class="hint block">{{ m.hint }}</span>
        </button>
      </div>

      <template v-if="form.auto_interact_style === 'welcome'">
        <ToggleSwitch
          v-model="form.welcome_speak"
          label="Say it out loud"
          hint="Speaks the line with the configured text-to-speech voice. Off = speech bubble only."
        />
        <div v-if="form.welcome_speak" class="py-4">
          <p class="label">Voice source</p>
          <div class="grid sm:grid-cols-2 gap-3" role="radiogroup" aria-label="Welcome voice source">
            <button
              v-for="m in [
                { id: 'saved', label: 'Saved voice', hint: 'Generated once, played from the kiosk. Works offline, no token cost.' },
                { id: 'live', label: 'Live voice', hint: 'Generated every time (internet + API key). Falls back to a saved clip if that fails.' },
              ]"
              :key="m.id" type="button" role="radio" :aria-checked="form.welcome_voice_mode === m.id"
              class="rounded-2xl border p-4 text-left transition-colors"
              :class="form.welcome_voice_mode === m.id ? 'border-brand-400/60 bg-brand-500/10' : 'border-white/10 hover:bg-white/5'"
              @click="form.welcome_voice_mode = m.id"
            >
              <span class="font-display font-semibold">{{ m.label }}</span>
              <span class="hint block">{{ m.hint }}</span>
            </button>
          </div>
        </div>

        <div class="py-4 space-y-5">
          <WelcomeLinesEditor
            v-model="form.welcome_messages"
            label="Welcome lines (a random one is used each time)"
            placeholder="Hi there! Come snap a photo with me!"
            :show-voice="form.welcome_speak"
            :status="lineStatus"
            :clips="clips"
            :saved-mode="form.welcome_voice_mode === 'saved'"
          />
          <div>
            <WelcomeLinesEditor
              v-model="form.welcome_back_messages"
              label="Welcome-back lines (recognised guests)"
              placeholder="Welcome back, {name}!"
              :show-voice="form.welcome_speak"
              :status="lineStatus"
              :clips="clips"
              :saved-mode="form.welcome_voice_mode === 'saved'"
            />
            <p class="hint">
              Use <code class="text-slate-200">{name}</code> for their name. Lines with {name} can't be saved as voice —
              add a nameless one (e.g. "Great to see you again!") for Saved voice. Empty = the lines above for everyone.
            </p>
          </div>

          <div v-if="form.welcome_speak">
            <div class="flex flex-wrap items-center gap-3">
              <button class="btn-accent btn-sm" :disabled="generating || !allLines.length" @click="generateVoice">
                <span v-if="generating" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
                {{ generating ? 'Generating…' : 'Generate & save voice' }}
              </button>
              <span class="hint !mt-0">
                {{ toGenerate ? `${toGenerate} line(s) to generate — uses the voice set in AI Providers.` : 'All saveable lines are ready.' }}
              </span>
            </div>
            <p v-if="voiceMsg" class="hint mt-2" :class="voiceErr ? 'text-red-300' : 'text-emerald-300'" role="status">{{ voiceMsg }}</p>
            <p v-if="form.welcome_voice_mode === 'saved' && !Object.keys(clips).length" class="hint text-amber-300">
              Saved voice is on but nothing is generated yet — the kiosk will show the bubble without sound.
            </p>
          </div>
        </div>
      </template>

      <div class="pt-4 grid sm:grid-cols-2 gap-4">
        <div>
          <label class="label" for="dwell">Greet after the face is held for</label>
          <div class="flex items-center gap-2">
            <input id="dwell" v-model.number="form.greet_dwell_seconds" type="number" min="0.5" max="10" step="0.5" class="field max-w-[8rem]" />
            <span class="hint !mt-0">seconds</span>
          </div>
          <p class="hint">Shorter feels snappier; longer avoids greeting passers-by.</p>
        </div>
        <div>
          <label class="label" for="cooldown">Wait between greetings</label>
          <div class="flex items-center gap-2">
            <input id="cooldown" v-model.number="form.greet_cooldown_seconds" type="number" min="5" max="600" class="field max-w-[8rem]" />
            <span class="hint !mt-0">seconds</span>
          </div>
          <p class="hint">The same guest also has to step away before being greeted again.</p>
        </div>
      </div>
    </div>

    <div class="flex justify-end">
      <button class="btn-primary" @click="save">Save changes</button>
    </div>
  </section>
</template>
