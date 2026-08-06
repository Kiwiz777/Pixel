import { onBeforeUnmount } from 'vue'

/**
 * Gaze-gated face watcher for the kiosk.
 *
 * Polls the video with the fast detector and only fires `onTrigger(descriptor)`
 * once a face has been held in frame, large/centered enough ("looking at the
 * camera"), for `dwellMs` (default 3s). After firing it waits for a cooldown +
 * the face to leave before it can fire again — so one engagement per visitor.
 *
 * In dev mode it draws an overlay on `canvas` with the detection box, score,
 * and (throttled) the recognised name + match distance.
 */
export function useFaceWatch(faceId, {
  onTrigger,
  recognize,            // async (descriptor) => {name, distance}|null  (dev label)
  isDevMode = () => false,
  dwellMs = 3000,
  minFaceRatio = 0.14,  // face width / frame width to count as "close/looking"
  pollMs = 400,
  cooldownMs = 20000,
} = {}) {
  let video = null
  let canvas = null
  let timer = null
  let busy = false
  let dwellStart = 0
  let armed = true
  let lastFire = 0
  let lastLabel = null
  let lastRecogAt = 0

  async function tick() {
    if (busy || !video || !video.videoWidth) return
    busy = true
    try {
      const det = await faceId.detectBox(video)
      const dev = isDevMode()
      if (dev) drawOverlay(det)
      else clearOverlay()

      const big = det && det.box.width / video.videoWidth >= minFaceRatio
      const now = Date.now()

      // Dev label: periodically recognise so the overlay shows who it sees.
      if (dev && big && recognize && now - lastRecogAt > 1500) {
        lastRecogAt = now
        faceId.describe(video).then((d) => d && recognize(d).then((r) => (lastLabel = r)))
      }

      if (big) {
        if (!dwellStart) dwellStart = now
        if (armed && now - dwellStart >= dwellMs && now - lastFire > cooldownMs) {
          armed = false
          lastFire = now
          const desc = await faceId.describe(video)
          if (desc) onTrigger(desc)
        }
      } else {
        dwellStart = 0
        lastLabel = null
        if (now - lastFire > cooldownMs) armed = true
      }
    } catch {
      /* detection hiccup; ignore */
    } finally {
      busy = false
    }
  }

  // ---- overlay (dev mode) -------------------------------------------------
  function drawOverlay(det) {
    if (!canvas || !video.videoWidth) return
    if (canvas.width !== video.videoWidth) canvas.width = video.videoWidth
    if (canvas.height !== video.videoHeight) canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    if (!det) return
    // The <video> is mirrored via CSS; mirror the box X so it lines up.
    const x = canvas.width - det.box.x - det.box.width
    const { y, width, height } = det.box
    const known = lastLabel && lastLabel.name
    ctx.lineWidth = 3
    ctx.strokeStyle = known ? '#34d399' : '#38bdf8'
    ctx.strokeRect(x, y, width, height)
    const label = lastLabel
      ? `${lastLabel.name || 'unknown'}  d=${lastLabel.distance ?? '–'}`
      : `face ${(det.score * 100) | 0}%`
    ctx.font = '600 22px Nunito, sans-serif'
    const tw = ctx.measureText(label).width + 16
    ctx.fillStyle = known ? 'rgba(16,185,129,0.85)' : 'rgba(56,189,248,0.85)'
    ctx.fillRect(x, Math.max(0, y - 30), tw, 28)
    ctx.fillStyle = '#04121f'
    ctx.fillText(label, x + 8, Math.max(20, y - 9))
  }

  function clearOverlay() {
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height)
  }

  function start(videoEl, canvasEl) {
    video = videoEl
    canvas = canvasEl
    stop()
    timer = setInterval(tick, pollMs)
  }
  function stop() {
    if (timer) clearInterval(timer)
    timer = null
  }
  /** Let the watcher re-arm immediately once a flow finishes. */
  function rearmAfter(ms = cooldownMs) {
    lastFire = Date.now() - (cooldownMs - ms)
    dwellStart = 0
  }

  onBeforeUnmount(stop)
  return { start, stop, rearmAfter }
}
