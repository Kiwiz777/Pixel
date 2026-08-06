import { onMounted, onBeforeUnmount } from 'vue'

/**
 * Hidden way into the Admin dashboard from the public kiosk (there is no
 * visible Admin button). Two triggers, both time-boxed so guests can't stumble
 * into it:
 *
 *  1) Type the secret word (default "admin") within 3 seconds.
 *  2) Tap a hidden hot-corner 5 times within 3 seconds (touchscreen-friendly).
 *
 * Call the returned `tapCorner` from a small invisible corner element's @click.
 */
export function useSecretAccess(onUnlock, { word = 'admin', taps = 5, windowMs = 3000 } = {}) {
  let buffer = ''
  let bufferTimer = null
  let tapCount = 0
  let tapTimer = null

  function onKeydown(e) {
    if (e.key.length !== 1) return // ignore modifiers/arrows
    buffer = (buffer + e.key.toLowerCase()).slice(-word.length)
    clearTimeout(bufferTimer)
    bufferTimer = setTimeout(() => (buffer = ''), windowMs)
    if (buffer === word) {
      buffer = ''
      onUnlock()
    }
  }

  function tapCorner() {
    tapCount += 1
    clearTimeout(tapTimer)
    tapTimer = setTimeout(() => (tapCount = 0), windowMs)
    if (tapCount >= taps) {
      tapCount = 0
      onUnlock()
    }
  }

  onMounted(() => window.addEventListener('keydown', onKeydown))
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onKeydown)
    clearTimeout(bufferTimer)
    clearTimeout(tapTimer)
  })

  return { tapCorner }
}
