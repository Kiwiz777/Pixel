<script setup>
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  label: { type: String, default: '' },
  hint: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <div class="flex items-start justify-between gap-4 py-2">
    <div>
      <span class="label !mb-0">{{ label }}</span>
      <p v-if="hint" class="hint">{{ hint }}</p>
    </div>
    <button
      type="button"
      class="switch shrink-0"
      :data-on="modelValue"
      role="switch"
      :aria-checked="modelValue"
      :aria-label="label"
      @click="emit('update:modelValue', !modelValue)"
    >
      <span class="switch-knob"></span>
    </button>
  </div>
</template>
