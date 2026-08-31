<script setup>
/**
 * WheelStyleFields - global prize-wheel chrome editor (Admin > Quiz).
 *
 * Controlled, same pattern as RewardFields: never mutates the prop, every
 * edit emits a fresh merged object. Segment fill colors stay per-reward
 * (RewardFields) — this only covers the wheel's shared chrome: pointer, hub,
 * glow, border, label font/color, size/timing, and optional custom art.
 */
import { ref, computed } from 'vue'
import { api } from '../../lib/api'
import PrizeWheel from '../../components/PrizeWheel.vue'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue'])

const r = computed(() => props.modelValue || {})
function patch(obj) {
  emit('update:modelValue', { ...r.value, ...obj })
}

const PRESETS = [
  {
    v: 'brand', label: 'Brand', swatch: '#F97316',
    fields: {
      segment_style: 'glass', pointer_color: '#F97316', hub_color: '#1e293b', hub_accent_color: '#F97316',
      glow_color_1: '#F97316', glow_color_2: '#38BDF8', border_color: '#F8FAFC',
      label_font: 'body', label_color: '#F8FAFC',
    },
  },
  {
    v: 'neon', label: 'Neon', swatch: '#22D3EE',
    fields: {
      segment_style: 'glass', pointer_color: '#22D3EE', hub_color: '#111827', hub_accent_color: '#22D3EE',
      glow_color_1: '#22D3EE', glow_color_2: '#A855F7', border_color: '#22D3EE',
      label_font: 'display', label_color: '#F8FAFC',
    },
  },
  {
    v: 'mono', label: 'Mono', swatch: '#F8FAFC',
    fields: {
      segment_style: 'solid', pointer_color: '#F8FAFC', hub_color: '#111827', hub_accent_color: '#F8FAFC',
      glow_color_1: '#94A3B8', glow_color_2: '#475569', border_color: '#F8FAFC',
      label_font: 'body', label_color: '#0B1120',
    },
  },
]
function applyPreset(p) {
  patch({ preset: p.v, ...p.fields })
}

const COLOR_FIELDS = [
  { key: 'pointer_color', label: 'Pointer' },
  { key: 'hub_color', label: 'Hub' },
  { key: 'hub_accent_color', label: 'Hub accent' },
  { key: 'glow_color_1', label: 'Glow 1' },
  { key: 'glow_color_2', label: 'Glow 2' },
  { key: 'border_color', label: 'Border / rim' },
  { key: 'label_color', label: 'Label text' },
]

// --- image uploads (frame overlay + background) ---------------------------
const uploadingFrame = ref(false)
const uploadingBg = ref(false)
async function uploadImage(kind, e) {
  const file = e.target.files?.[0]
  if (!file) return
  const busy = kind === 'frame' ? uploadingFrame : uploadingBg
  busy.value = true
  try {
    const res = await api.uploadWheelImage(kind, file)
    patch({ [`${kind}_image`]: res.url })
  } catch (err) {
    alert(err.message || 'Upload failed')
  } finally {
    busy.value = false
    e.target.value = ''
  }
}
function clearImage(kind) {
  patch({ [`${kind}_image`]: '' })
}

// --- live preview -----------------------------------------------------------
const PREVIEW_SEGMENTS = [
  { label: 'Free print', color: '#F97316' },
  { label: 'AI photo', color: '#2563EB' },
  { label: 'Try again', color: '#64748B' },
  { label: 'Voucher', color: '#22C55E' },
]
const previewWinner = ref(0)
const previewKey = ref(0)
function spinPreview() {
  previewWinner.value = Math.floor(Math.random() * PREVIEW_SEGMENTS.length)
  previewKey.value++
}
</script>

<template>
  <div class="grid lg:grid-cols-[1fr_auto] gap-6">
    <div class="space-y-5">
      <!-- presets -->
      <div>
        <label class="label">Quick presets</label>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="p in PRESETS" :key="p.v" type="button"
            class="btn-ghost btn-sm inline-flex items-center gap-2"
            :class="r.preset === p.v ? 'border-brand-400/50 text-brand-100' : ''"
            @click="applyPreset(p)"
          >
            <span class="h-3 w-3 rounded-full inline-block" :style="{ background: p.swatch }"></span>
            {{ p.label }}
          </button>
        </div>
        <p class="hint mt-1">Fills in colors/font/segment style below — tweak anything after picking one.</p>
      </div>

      <!-- segment style -->
      <div>
        <label class="label">Segment style</label>
        <div class="flex gap-2">
          <button type="button" class="btn-ghost btn-sm" :class="(r.segment_style || 'glass') === 'glass' ? 'border-brand-400/50 text-brand-100' : ''"
                  @click="patch({ segment_style: 'glass' })">Glass (translucent)</button>
          <button type="button" class="btn-ghost btn-sm" :class="r.segment_style === 'solid' ? 'border-brand-400/50 text-brand-100' : ''"
                  @click="patch({ segment_style: 'solid' })">Solid (opaque)</button>
        </div>
      </div>

      <!-- colors -->
      <div>
        <label class="label">Colors</label>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div v-for="f in COLOR_FIELDS" :key="f.key">
            <label class="hint !mt-0 block mb-1">{{ f.label }}</label>
            <input type="color" class="field h-10 w-full p-1 cursor-pointer" :value="r[f.key] || '#F97316'"
                   @input="patch({ [f.key]: $event.target.value })" />
          </div>
        </div>
      </div>

      <!-- label font -->
      <div>
        <label class="label">Label font</label>
        <select class="field max-w-xs" :value="r.label_font || 'body'" @change="patch({ label_font: $event.target.value })">
          <option value="body">Nunito (body)</option>
          <option value="display">Fredoka (display)</option>
        </select>
      </div>

      <!-- size & timing -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 max-w-2xl">
        <div>
          <label class="label">Size (px)</label>
          <input type="number" min="220" max="460" step="10" class="field" :value="r.size_px ?? 340"
                 @input="patch({ size_px: Number($event.target.value) })" />
        </div>
        <div>
          <label class="label">Preroll (ms)</label>
          <input type="number" min="0" max="8000" step="100" class="field" :value="r.preroll_ms ?? 2000"
                 @input="patch({ preroll_ms: Number($event.target.value) })" />
        </div>
        <div>
          <label class="label">Spin (ms)</label>
          <input type="number" min="1000" max="15000" step="100" class="field" :value="r.spin_ms ?? 5600"
                 @input="patch({ spin_ms: Number($event.target.value) })" />
        </div>
        <div>
          <label class="label">Hold (ms)</label>
          <input type="number" min="0" max="8000" step="100" class="field" :value="r.hold_ms ?? 1300"
                 @input="patch({ hold_ms: Number($event.target.value) })" />
        </div>
      </div>

      <!-- custom art -->
      <div class="grid sm:grid-cols-2 gap-4">
        <div>
          <label class="label">Custom frame / bezel (PNG, transparent center)</label>
          <div class="flex gap-3 items-start">
            <div class="w-20 h-20 rounded-xl border border-dashed border-white/20 grid place-items-center bg-ink-900 overflow-hidden shrink-0">
              <img v-if="r.frame_image" :src="r.frame_image" alt="Frame" class="max-h-full max-w-full object-contain" />
              <span v-else class="hint text-center px-1 text-[10px]">None</span>
            </div>
            <div class="flex-1 space-y-1.5">
              <label class="btn-ghost btn-sm cursor-pointer inline-flex">
                <input type="file" accept="image/png,image/webp" class="hidden" @change="uploadImage('frame', $event)" />
                <span v-if="uploadingFrame" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin mr-1"></span>
                Upload
              </label>
              <button v-if="r.frame_image" class="btn-ghost btn-sm text-red-300 ml-2" @click="clearImage('frame')">Remove</button>
              <p class="hint">Drawn on top of the wheel — e.g. a decorative ring.</p>
            </div>
          </div>
        </div>
        <div>
          <label class="label">Custom background</label>
          <div class="flex gap-3 items-start">
            <div class="w-20 h-20 rounded-xl border border-dashed border-white/20 grid place-items-center bg-ink-900 overflow-hidden shrink-0">
              <img v-if="r.background_image" :src="r.background_image" alt="Background" class="max-h-full max-w-full object-contain" />
              <span v-else class="hint text-center px-1 text-[10px]">None</span>
            </div>
            <div class="flex-1 space-y-1.5">
              <label class="btn-ghost btn-sm cursor-pointer inline-flex">
                <input type="file" accept="image/png,image/webp,image/jpeg" class="hidden" @change="uploadImage('background', $event)" />
                <span v-if="uploadingBg" class="h-4 w-4 rounded-full border-2 border-white border-t-transparent animate-spin mr-1"></span>
                Upload
              </label>
              <button v-if="r.background_image" class="btn-ghost btn-sm text-red-300 ml-2" @click="clearImage('background')">Remove</button>
              <p class="hint">Replaces the default glow/frosted-glass backdrop.</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- live preview -->
    <div class="lg:w-72 shrink-0">
      <div class="glass rounded-2xl p-4 sticky top-4 text-center">
        <p class="hint mb-3">Live preview</p>
        <div class="grid place-items-center">
          <PrizeWheel
            :key="previewKey"
            :segments="PREVIEW_SEGMENTS"
            :winner="previewWinner"
            :theme="r"
            :size="Math.min(r.size_px || 340, 240)"
            :preroll-ms="400"
            :spin-ms="r.spin_ms ?? 5600"
            :hold-ms="r.hold_ms ?? 1300"
          />
        </div>
        <button class="btn-primary btn-sm mt-3" @click="spinPreview">🎡 Preview spin</button>
      </div>
    </div>
  </div>
</template>
