<script setup>
/**
 * Full-screen kiosk background layer behind the photobooth UI.
 * Supports: none (aurora), solid color, single image, looping video, or an
 * image slideshow with crossfade. Configured from Admin → Kiosk.
 */
import { computed, ref, watch, onBeforeUnmount } from 'vue'

const props = defineProps({
  mode: { type: String, default: 'none' }, // none|color|image|video|slideshow
  color: { type: String, default: '#070b16' },
  media: { type: Array, default: () => [] }, // [{file,type,url}]
  slideshowMs: { type: Number, default: 6000 },
  dim: { type: Number, default: 35 }, // 0-100 darken overlay
})

const images = computed(() => props.media.filter((m) => m.type === 'image'))
const firstVideo = computed(() => props.media.find((m) => m.type === 'video'))
const slide = ref(0)
let timer = null

function startSlideshow() {
  stopSlideshow()
  if (props.mode === 'slideshow' && images.value.length > 1) {
    timer = setInterval(() => {
      slide.value = (slide.value + 1) % images.value.length
    }, Math.max(2000, props.slideshowMs))
  }
}
function stopSlideshow() {
  if (timer) clearInterval(timer)
  timer = null
}

watch(() => [props.mode, props.media, props.slideshowMs], startSlideshow, { immediate: true, deep: true })
onBeforeUnmount(stopSlideshow)

const dimAlpha = computed(() => Math.min(1, Math.max(0, props.dim / 100)))
</script>

<template>
  <div class="absolute inset-0 -z-10 overflow-hidden" :class="{ aurora: mode === 'none' }">
    <!-- solid color -->
    <div v-if="mode === 'color'" class="absolute inset-0" :style="{ background: color }"></div>

    <!-- single image -->
    <img
      v-else-if="mode === 'image' && images[0]"
      :src="images[0].url" alt="" class="absolute inset-0 h-full w-full object-cover"
    />

    <!-- looping muted video -->
    <video
      v-else-if="mode === 'video' && firstVideo"
      :src="firstVideo.url" class="absolute inset-0 h-full w-full object-cover"
      autoplay loop muted playsinline
    ></video>

    <!-- slideshow with crossfade -->
    <template v-else-if="mode === 'slideshow' && images.length">
      <transition-group name="cf">
        <img
          v-for="(m, i) in images" :key="m.file" v-show="i === slide"
          :src="m.url" alt="" class="absolute inset-0 h-full w-full object-cover"
        />
      </transition-group>
    </template>

    <!-- legibility dim overlay (skip for plain aurora) -->
    <div v-if="mode !== 'none'" class="absolute inset-0 bg-ink-950" :style="{ opacity: dimAlpha }"></div>
  </div>
</template>

<style scoped>
.cf-enter-active,
.cf-leave-active {
  transition: opacity 1s ease;
}
.cf-enter-from,
.cf-leave-to {
  opacity: 0;
}
</style>
