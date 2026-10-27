<script setup>
/**
 * Model dropdown for the AI Providers tab. Starts from the built-in list,
 * "Refresh" pulls the live list from the provider with the saved key
 * (GET /api/settings/models/{kind}/{provider}), and any id can be typed - so
 * a newly released model is usable the day it ships, no update needed.
 */
import { computed, ref, watch } from 'vue'
import { api } from '../../lib/api'

const model = defineModel({ type: String, default: '' })
const props = defineProps({
  id: { type: String, required: true },
  kind: { type: String, required: true },        // chat | image | tts | stt
  provider: { type: String, required: true },
  providerLabel: { type: String, default: '' },
  builtin: { type: Array, default: () => [] },
  allowDefault: { type: Boolean, default: false }, // '' = provider default
  defaultLabel: { type: String, default: 'Provider default' },
})

const live = ref([])
const loading = ref(false)
const msg = ref('')
const msgErr = ref(false)
const typing = ref(false)

// A different provider has a different catalogue.
watch(() => props.provider, () => {
  live.value = []
  msg.value = ''
})

const options = computed(() => {
  const list = live.value.length ? live.value : props.builtin
  // Keep the saved value visible even if it isn't in either list.
  return model.value && !list.includes(model.value) ? [model.value, ...list] : list
})

async function refresh() {
  loading.value = true
  msg.value = ''
  msgErr.value = false
  try {
    const res = await api.liveModels(props.kind, props.provider)
    live.value = res.models
    msg.value = res.models.length
      ? `${res.models.length} models available from ${props.providerLabel || props.provider}.`
      : 'The provider returned no matching models.'
  } catch (e) {
    msgErr.value = true
    msg.value = e.message || 'Could not load models.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <div class="flex gap-2">
      <input
        v-if="typing"
        :id="id" v-model.trim="model" class="field font-mono text-sm"
        placeholder="exact model id, e.g. gpt-6.1-terra"
      />
      <select v-else :id="id" v-model="model" class="field">
        <option v-if="allowDefault" value="">{{ defaultLabel }}</option>
        <option v-for="m in options" :key="m" :value="m">{{ m }}</option>
      </select>
      <button
        type="button" class="btn-ghost btn-sm shrink-0" :disabled="loading"
        :title="`Load the current model list from ${providerLabel || provider}`"
        @click="refresh"
      >
        <span v-if="loading" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin"></span>
        <template v-else>Refresh</template>
      </button>
    </div>
    <p class="hint mt-1">
      <span v-if="msg" :class="msgErr ? 'text-red-300' : ''">{{ msg }} </span>
      <button type="button" class="underline hover:text-slate-200" @click="typing = !typing">
        {{ typing ? 'Pick from list' : 'Type a model id' }}
      </button>
    </p>
  </div>
</template>
