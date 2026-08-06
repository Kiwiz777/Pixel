<script setup>
/**
 * AI Providers tab: secure API key entry (masked previews) + active
 * provider/model selection for Chat and Image Enhancement, plus the
 * ElevenLabs voice picker.
 */
import { reactive, ref, watch, computed } from 'vue'

const props = defineProps({ settings: Object, providers: Object })
const emit = defineEmits(['save'])

// Secret fields. We show whether a key is already set, and only send a new
// value if the admin types one (blank = keep existing).
const KEY_FIELDS = [
  { key: 'api_key_openai', label: 'OpenAI API Key', ph: 'sk-…' },
  { key: 'api_key_anthropic', label: 'Anthropic (Claude) API Key', ph: 'sk-ant-…' },
  { key: 'api_key_gemini', label: 'Google Gemini API Key', ph: 'AIza…' },
  { key: 'api_key_deepseek', label: 'DeepSeek API Key', ph: 'sk-…' },
  { key: 'api_key_elevenlabs', label: 'ElevenLabs API Key', ph: 'xi-…' },
]

const keys = reactive({})
const reveal = reactive({})
const form = reactive({
  active_chat_provider: 'anthropic', active_chat_model: '',
  active_image_provider: 'openai', active_image_model: '',
  tts_provider: 'openai', openai_tts_model: 'gpt-4o-mini-tts',
  openai_tts_voice: 'alloy', tts_voice_id: '',
})
const OPENAI_TTS_MODELS = ['gpt-4o-mini-tts', 'tts-1', 'tts-1-hd']
const OPENAI_VOICES = ['alloy', 'ash', 'ballad', 'coral', 'echo', 'fable', 'onyx', 'nova', 'sage', 'shimmer']
const voices = ref({
  openai: OPENAI_VOICES.map((v) => ({ voice_id: v, name: v[0].toUpperCase() + v.slice(1) })),
  elevenlabs: [],
})
const voiceMsg = ref('')

watch(
  () => props.settings,
  (s) => {
    if (!s) return
    Object.keys(form).forEach((k) => (form[k] = s[k] ?? form[k]))
    KEY_FIELDS.forEach((f) => (keys[f.key] = '')) // never prefill secrets
  },
  { immediate: true, deep: true },
)

const chatModels = computed(() => props.providers?.chat?.[form.active_chat_provider]?.models || [])
const imageModels = computed(() => props.providers?.image?.[form.active_image_provider]?.models || [])

function isSet(key) {
  return props.settings?.[`${key}__set`]
}

async function loadVoices() {
  voiceMsg.value = 'Loading voices…'
  try {
    const { api } = await import('../../lib/api')
    const res = await api.voices()
    voices.value = res.voices
    voiceMsg.value =
      form.tts_provider === 'elevenlabs' && !res.voices.elevenlabs.length
        ? 'No ElevenLabs voices found (check the key).'
        : ''
  } catch (e) {
    voiceMsg.value = e.message || 'Could not load voices.'
  }
}

function save() {
  const patch = { ...form }
  // include only secrets the admin actually typed
  KEY_FIELDS.forEach((f) => {
    if (keys[f.key]) patch[f.key] = keys[f.key]
  })
  emit('save', patch)
  KEY_FIELDS.forEach((f) => (keys[f.key] = ''))
}
</script>

<template>
  <section>
    <header class="mb-6">
      <h1 class="font-display text-3xl font-semibold">AI Providers</h1>
      <p class="text-slate-400 mt-1">Keys are encrypted at rest and never shown again after saving.</p>
    </header>

    <!-- API keys -->
    <div class="glass-card p-5 sm:p-6 mb-5">
      <h2 class="font-display text-lg font-semibold mb-4">API Keys</h2>
      <div class="space-y-4">
        <div v-for="f in KEY_FIELDS" :key="f.key">
          <div class="flex items-center justify-between">
            <label class="label" :for="f.key">{{ f.label }}</label>
            <span v-if="isSet(f.key)" class="text-xs text-emerald-300 flex items-center gap-1">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              Saved · {{ settings[f.key] }}
            </span>
            <span v-else class="text-xs text-slate-500">Not set</span>
          </div>
          <div class="relative">
            <input
              :id="f.key" v-model="keys[f.key]" :type="reveal[f.key] ? 'text' : 'password'"
              class="field pr-20" :placeholder="isSet(f.key) ? 'Enter a new key to replace' : f.ph"
              autocomplete="off"
            />
            <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 btn-ghost btn-sm" @click="reveal[f.key] = !reveal[f.key]">
              {{ reveal[f.key] ? 'Hide' : 'Show' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Active providers -->
    <div class="grid sm:grid-cols-2 gap-5">
      <div class="glass-card p-5 sm:p-6">
        <h2 class="font-display text-lg font-semibold mb-1">Chat Brain</h2>
        <p class="hint !mt-0 mb-4">Which LLM answers guests.</p>
        <label class="label" for="chatprov">Provider</label>
        <select id="chatprov" v-model="form.active_chat_provider" class="field mb-3">
          <option v-for="(p, id) in providers.chat" :key="id" :value="id">{{ p.label }}</option>
        </select>
        <label class="label" for="chatmodel">Model</label>
        <select id="chatmodel" v-model="form.active_chat_model" class="field">
          <option value="">Provider default</option>
          <option v-for="m in chatModels" :key="m" :value="m">{{ m }}</option>
        </select>
      </div>

      <div class="glass-card p-5 sm:p-6">
        <h2 class="font-display text-lg font-semibold mb-1">Image Enhance</h2>
        <p class="hint !mt-0 mb-4">Which model runs "AI Enhance".</p>
        <label class="label" for="imgprov">Provider</label>
        <select id="imgprov" v-model="form.active_image_provider" class="field mb-3">
          <option v-for="(p, id) in providers.image" :key="id" :value="id">{{ p.label }}</option>
        </select>
        <label class="label" for="imgmodel">Model</label>
        <select id="imgmodel" v-model="form.active_image_model" class="field">
          <option value="">Provider default</option>
          <option v-for="m in imageModels" :key="m" :value="m">{{ m }}</option>
        </select>
      </div>
    </div>

    <!-- Voice / TTS -->
    <div class="glass-card p-5 sm:p-6 mt-5">
      <div class="flex items-center justify-between mb-3">
        <div>
          <h2 class="font-display text-lg font-semibold">Voice (Text-to-Speech)</h2>
          <p class="hint !mt-0">Multilingual speech for all six languages.</p>
        </div>
        <button class="btn-ghost btn-sm" @click="loadVoices">Load voices</button>
      </div>

      <label class="label" for="ttsprov">TTS provider</label>
      <select id="ttsprov" v-model="form.tts_provider" class="field max-w-xs mb-4">
        <option value="openai">OpenAI (uses your OpenAI key)</option>
        <option value="elevenlabs">ElevenLabs</option>
      </select>

      <!-- OpenAI TTS -->
      <div v-if="form.tts_provider === 'openai'" class="grid sm:grid-cols-2 gap-4">
        <div>
          <label class="label" for="otmodel">Model</label>
          <select id="otmodel" v-model="form.openai_tts_model" class="field">
            <option v-for="m in OPENAI_TTS_MODELS" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
        <div>
          <label class="label" for="otvoice">Voice</label>
          <select id="otvoice" v-model="form.openai_tts_voice" class="field">
            <option v-for="v in voices.openai" :key="v.voice_id" :value="v.voice_id">{{ v.name }}</option>
          </select>
        </div>
      </div>

      <!-- ElevenLabs TTS -->
      <div v-else>
        <label class="label" for="elvoice">ElevenLabs voice</label>
        <select v-if="voices.elevenlabs.length" id="elvoice" v-model="form.tts_voice_id" class="field max-w-md">
          <option value="">Select a voice…</option>
          <option v-for="v in voices.elevenlabs" :key="v.voice_id" :value="v.voice_id">{{ v.name }}</option>
        </select>
        <input v-else v-model="form.tts_voice_id" class="field max-w-md" placeholder="Voice ID (or click Load voices)" />
      </div>

      <p v-if="voiceMsg" class="hint">{{ voiceMsg }}</p>
    </div>

    <div class="mt-5 flex justify-end">
      <button class="btn-primary" @click="save">Save changes</button>
    </div>
  </section>
</template>
