<script setup>
/**
 * Editable list of welcome lines (Avatar & Welcome tab). One input per line,
 * with its saved-voice status, a play button for its saved clip, remove, and
 * "+ Add line". v-model is the newline-joined string stored in settings.
 */
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  label: { type: String, required: true },
  placeholder: { type: String, default: '' },
  showVoice: { type: Boolean, default: false },
  status: { type: Function, default: () => 'missing' }, // line -> saved|stale|missing|dynamic
  clips: { type: Object, default: () => ({}) },          // line -> { file, voice }
  savedMode: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const MAX_LINES = 20
const norm = (list) => list.map((l) => l.trim()).filter(Boolean).join('\n')
const rows = ref([])

// Only rebuild from the prop when it really differs - otherwise an empty row
// the operator just added would vanish on the next keystroke.
watch(
  () => props.modelValue,
  (v) => {
    if (norm(rows.value) !== norm(String(v || '').split(/\r?\n/))) {
      rows.value = String(v || '').split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
    }
  },
  { immediate: true },
)

function commit() {
  emit('update:modelValue', norm(rows.value))
}
function update(i, value) {
  rows.value[i] = value
  commit()
}
function remove(i) {
  rows.value.splice(i, 1)
  commit()
}
function add() {
  if (rows.value.length < MAX_LINES) rows.value.push('')
}

const STATUS = {
  saved: { dot: 'bg-emerald-400', text: (c) => `Saved · ${c?.voice || ''}` },
  stale: { dot: 'bg-amber-400', text: (c) => `Old voice (${c?.voice || '?'}) · redo` },
  missing: { dot: 'bg-slate-500', text: () => 'Not saved yet' },
  dynamic: { dot: 'bg-electric-400', text: () => '' },
}
function statusText(line) {
  const st = props.status(line.trim())
  if (st === 'dynamic') return props.savedMode ? 'Has {name} — not saved' : 'Has {name} — spoken live'
  return STATUS[st].text(props.clips[line.trim()])
}
function play(line) {
  const c = props.clips[line.trim()]
  if (c) new Audio(`/media/voice/${c.file}`).play().catch(() => {})
}
</script>

<template>
  <div>
    <p class="label">{{ label }}</p>
    <ul class="space-y-2">
      <li v-for="(line, i) in rows" :key="i" class="flex items-center gap-2">
        <input
          :value="line"
          class="field flex-1 min-w-0"
          :placeholder="placeholder"
          :aria-label="`${label} ${i + 1}`"
          maxlength="160"
          @input="update(i, $event.target.value)"
        />
        <template v-if="showVoice && line.trim()">
          <span
            class="hidden sm:inline-flex items-center gap-1.5 hint !mt-0 w-44 shrink-0"
            :title="statusText(line)"
          >
            <span class="h-2 w-2 rounded-full shrink-0" :class="STATUS[status(line.trim())].dot" aria-hidden="true"></span>
            <span class="truncate">{{ statusText(line) }}</span>
          </span>
          <button
            type="button" class="btn-ghost btn-sm shrink-0 !px-2.5"
            :disabled="!clips[line.trim()]"
            :aria-label="`Play saved voice: ${line}`"
            @click="play(line)"
          >▶</button>
        </template>
        <button type="button" class="btn-ghost btn-sm shrink-0 !px-2.5" :aria-label="`Remove: ${line || 'empty line'}`" @click="remove(i)">✕</button>
      </li>
    </ul>
    <button type="button" class="btn-ghost btn-sm mt-2" :disabled="rows.length >= MAX_LINES" @click="add">+ Add line</button>
  </div>
</template>
