<script setup>
/**
 * RewardFields - fully-controlled editor for a single reward config.
 *
 * Reward shape:
 *   { type: 'prints'|'ai_enhance'|'image'|'voucher'|'wheel'|'none',
 *     photos_count, prints_count,                       // prints
 *     enhance_count, prompt_mode, prompt, prompt_list[], // ai_enhance
 *     image_path,                                        // image
 *     voucher_text,                                      // voucher
 *     segments[], weight }                               // wheel / segment odds
 *
 * Controlled: never mutates the prop; every edit emits a fresh merged object.
 * Recurses into itself for prize-wheel segments (allowWheel=false there).
 */
import { computed } from 'vue'
import { api } from '../../lib/api'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  allowWheel: { type: Boolean, default: true },
  showWeight: { type: Boolean, default: false }, // segments carry spin odds
})
const emit = defineEmits(['update:modelValue'])

const r = computed(() => props.modelValue || {})

function patch(obj) {
  emit('update:modelValue', { ...r.value, ...obj })
}

const TYPES = [
  { v: 'prints', label: 'Photos / prints' },
  { v: 'ai_enhance', label: 'AI-enhanced photos' },
  { v: 'image', label: 'Show an image' },
  { v: 'voucher', label: 'Voucher / code' },
]

// prompt_list <-> textarea (one prompt per line)
const promptLinesText = computed({
  get: () => (r.value.prompt_list || []).join('\n'),
  set: (v) => patch({ prompt_list: v.split('\n').map((s) => s.trim()).filter(Boolean) }),
})

// --- prize-wheel segments -------------------------------------------------
function addSegment() {
  patch({ segments: [...(r.value.segments || []), { type: 'prints', photos_count: 1, prints_count: 1, weight: 1 }] })
}
function updateSegment(i, seg) {
  const segments = [...(r.value.segments || [])]
  segments[i] = seg
  patch({ segments })
}
function removeSegment(i) {
  patch({ segments: (r.value.segments || []).filter((_, idx) => idx !== i) })
}

// --- reward image upload --------------------------------------------------
const uploading = computed(() => false)
async function uploadImage(e) {
  const file = e.target.files?.[0]
  if (!file) return
  try {
    const res = await api.uploadRewardImage(file)
    patch({ image_path: res.image_path })
  } catch (err) {
    // surface via a native alert; admin-only, low-traffic path
    alert(err.message || 'Image upload failed')
  } finally {
    e.target.value = ''
  }
}
</script>

<template>
  <div class="space-y-4">
    <!-- reward type -->
    <div>
      <label class="label">Reward type</label>
      <select
        class="field max-w-xs"
        :value="r.type || 'prints'"
        @change="patch({ type: $event.target.value })"
      >
        <option v-for="t in TYPES" :key="t.v" :value="t.v">{{ t.label }}</option>
        <option v-if="allowWheel" value="wheel">🎡 Prize wheel (random)</option>
      </select>
    </div>

    <!-- prints -->
    <div v-if="(r.type || 'prints') === 'prints'" class="grid grid-cols-2 gap-4 max-w-md">
      <div>
        <label class="label">Photos they may take</label>
        <input type="number" min="1" max="20" class="field" :value="r.photos_count ?? 1"
               @input="patch({ photos_count: Number($event.target.value) })" />
      </div>
      <div>
        <label class="label">Prints per photo</label>
        <input type="number" min="0" max="20" class="field" :value="r.prints_count ?? 1"
               @input="patch({ prints_count: Number($event.target.value) })" />
      </div>
    </div>

    <!-- ai_enhance -->
    <div v-else-if="r.type === 'ai_enhance'" class="space-y-4">
      <div class="max-w-[10rem]">
        <label class="label">Enhancements</label>
        <input type="number" min="1" max="10" class="field" :value="r.enhance_count ?? 1"
               @input="patch({ enhance_count: Number($event.target.value) })" />
      </div>
      <div>
        <label class="label">Prompt source</label>
        <select class="field max-w-xs" :value="r.prompt_mode || 'admin'"
                @change="patch({ prompt_mode: $event.target.value })">
          <option value="admin">Fixed prompt (set below)</option>
          <option value="list">Guest picks from a list</option>
          <option value="user">Guest types their own</option>
        </select>
      </div>
      <div v-if="(r.prompt_mode || 'admin') === 'admin'">
        <label class="label">Enhance prompt</label>
        <textarea rows="2" class="field" :value="r.prompt || ''"
                  placeholder="e.g. Turn this into a vibrant cartoon portrait…"
                  @input="patch({ prompt: $event.target.value })"></textarea>
      </div>
      <div v-else-if="r.prompt_mode === 'list'">
        <label class="label">Prompt choices (one per line)</label>
        <textarea rows="4" class="field" v-model="promptLinesText"
                  placeholder="Cartoon portrait&#10;Vintage film look&#10;Neon cyberpunk"></textarea>
        <p class="hint">The guest chooses one of these on the kiosk.</p>
      </div>
      <p v-else class="hint">The guest will type their own enhancement prompt on the kiosk.</p>
    </div>

    <!-- image -->
    <div v-else-if="r.type === 'image'" class="flex gap-4 items-start">
      <div class="w-32 h-32 rounded-2xl border border-dashed border-white/20 grid place-items-center bg-ink-900 overflow-hidden shrink-0">
        <img v-if="r.image_path" :src="`/media/rewards/${r.image_path}`" alt="Reward image" class="max-h-full max-w-full object-contain" />
        <span v-else class="hint text-center px-2">No image</span>
      </div>
      <div class="flex-1">
        <label class="btn-ghost btn-sm cursor-pointer inline-flex">
          <input type="file" accept="image/*" class="hidden" @change="uploadImage" />
          Upload winner image
        </label>
        <p class="hint">Shown full-screen to the winner (e.g. a coupon or a “You won!” graphic).</p>
      </div>
    </div>

    <!-- voucher -->
    <div v-else-if="r.type === 'voucher'" class="space-y-4">
      <div class="grid sm:grid-cols-2 gap-4">
        <div>
          <label class="label">Voucher name / label</label>
          <input class="field" :value="r.label || r.voucher_text || ''"
                 placeholder="Free coffee"
                 @input="patch({ label: $event.target.value })" />
        </div>
        <div>
          <label class="label">Code</label>
          <input class="field" :value="r.code || ''"
                 placeholder="PIX-2024"
                 @input="patch({ code: $event.target.value })" />
        </div>
      </div>
      <div>
        <label class="label">How the guest gets the code</label>
        <select class="field max-w-xs" :value="r.delivery || 'show'"
                @change="patch({ delivery: $event.target.value })">
          <option value="show">Show code on screen</option>
          <option value="email">Send by email</option>
          <option value="print">Print only (never shown on screen)</option>
        </select>
        <p class="hint">Email needs SMTP configured below. Print sends a voucher slip to the default printer.</p>
      </div>
    </div>

    <!-- wheel -->
    <div v-else-if="r.type === 'wheel'" class="space-y-3">
      <p class="hint">The kiosk spins and lands on one segment at random (weighted). Add the possible prizes:</p>
      <div v-for="(seg, i) in (r.segments || [])" :key="i" class="rounded-xl border border-white/10 p-4 bg-white/5">
        <div class="flex items-center justify-between mb-2">
          <span class="font-display text-sm text-electric-300">Segment {{ i + 1 }}</span>
          <button class="btn-ghost btn-sm text-red-300" @click="removeSegment(i)">Remove</button>
        </div>
        <RewardFields
          :model-value="seg"
          :allow-wheel="false"
          :show-weight="true"
          @update:model-value="updateSegment(i, $event)"
        />
      </div>
      <button class="btn-ghost btn-sm" @click="addSegment">+ Add wheel segment</button>
    </div>

    <!-- odds (segments only) -->
    <div v-if="showWeight" class="max-w-[8rem]">
      <label class="label">Odds weight</label>
      <input type="number" min="1" max="100" class="field" :value="r.weight ?? 1"
             @input="patch({ weight: Number($event.target.value) })" />
    </div>
  </div>
</template>
