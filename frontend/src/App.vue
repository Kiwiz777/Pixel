<script setup>
// Root shell. Each view owns its own full-screen layout, so App stays minimal -
// except for the on-screen keyboard, which is mounted once here so it is
// available on every page (kiosk and admin) without each view wiring it up.
import GlobalKeyboard from './components/GlobalKeyboard.vue'
import { open, toggleKeyboard } from './composables/useGlobalKeyboard'
</script>

<template>
  <router-view v-slot="{ Component }">
    <transition name="fade" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>

  <!-- Launcher. Hidden while the keyboard is up, since that has its own close. -->
  <button
    v-if="!open"
    class="kb-launcher"
    aria-label="Open on-screen keyboard"
    title="On-screen keyboard"
    @click="toggleKeyboard"
  >
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M6 14h12" stroke-linecap="round" />
    </svg>
  </button>

  <GlobalKeyboard />
</template>

<style>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Bottom-left: the kiosk dock owns the bottom centre and the diagnostics
   overlay the top left, so this corner is the one that stays clear. */
.kb-launcher {
  position: fixed;
  left: 0.75rem;
  bottom: 0.75rem;
  z-index: 55;
  display: grid;
  place-items: center;
  height: 2.75rem;
  width: 2.75rem;
  border-radius: 0.9rem;
  color: #cbd5e1;
  background: rgba(15, 23, 42, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(10px);
  opacity: 0.45;
  transition: opacity 0.2s ease, background-color 0.2s ease;
}
/* Kiosk attract mode: nothing but the background until a guest arrives. */
.kiosk-asleep .kb-launcher {
  opacity: 0;
  pointer-events: none;
}
.kb-launcher:hover,
.kb-launcher:focus-visible {
  opacity: 1;
  background: rgba(15, 23, 42, 0.8);
}

@media (prefers-reduced-motion: reduce) {
  .fade-enter-active,
  .fade-leave-active,
  .kb-launcher { transition: none; }
}
</style>
