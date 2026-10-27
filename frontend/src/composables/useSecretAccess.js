import { onMounted, onBeforeUnmount } from 'vue'

/**
 * Counts taps on a hidden element and calls `fn` on the Nth within the
 * window. Shared by the kiosk's invisible hot-corners.
 */
export function tapCounter(fn, { taps = 5, windowMs = 3000 } = {}) {
  let count = 0
  let timer = null
  return () => {
    count += 1
    clearTimeout(timer)
    timer = setTimeout(() => (count = 0), windowMs)
    if (count >= taps) {
      count = 0
      fn()
    }
  }
}

/**
 * Hidden fullscreen switch (5 taps). Toggles the Fullscreen API: exits if the
 * page is fullscreen, enters if not. It can't leave fullscreen the BROWSER
 * started (chromium --kiosk, F11) - pages have no control over that.
 */
export function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
  else document.documentElement.requestFullscreen?.().catch(() => {})
}

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

  const tapCorner = tapCounter(onUnlock, { taps, windowMs })

  onMounted(() => window.addEventListener('keydown', onKeydown))
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onKeydown)
    clearTimeout(bufferTimer)
  })

  return { tapCorner }
}
