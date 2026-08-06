import { onBeforeUnmount } from 'vue'

/**
 * Client-side "someone is here" detection for auto-interact.
 *
 * Because the kiosk camera now runs in the browser (getUserMedia), the server
 * never sees frames, so server-side OpenCV face detection can't fire on a
 * laptop. This composable detects presence directly from the <video> element:
 *
 *   1. Shape Detection API (`window.FaceDetector`) when available -> true face
 *      detection.
 *   2. Otherwise a lightweight frame-difference motion detector -> fires when
 *      someone steps in front of the camera.
 *
 * It calls `onArrive()` once when a person appears, then arms a cooldown and
 * waits for the scene to clear before it can fire again (so it greets once per
 * visitor, not every frame).
 */
export function usePresence(onArrive, {
  intervalMs = 700,        // how often we sample
  cooldownMs = 15000,      // min gap between greetings
  motionThreshold = 14,    // mean per-pixel delta that counts as "movement"
  requiredHits = 2,        // consecutive positive samples before firing
} = {}) {
  let video = null
  let timer = null
  let detector = null
  const prev = { data: null }
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  canvas.width = 64
  canvas.height = 48

  let hits = 0
  let armed = true
  let lastFire = 0
  let presentStreak = 0

  function tryCreateDetector() {
    if ('FaceDetector' in window) {
      try {
        detector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 1 })
      } catch {
        detector = null
      }
    }
  }

  async function detectFace() {
    try {
      const faces = await detector.detect(video)
      return faces.length > 0
    } catch {
      return false // fall through to motion on a bad frame
    }
  }

  function detectMotion() {
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    const cur = ctx.getImageData(0, 0, canvas.width, canvas.height).data
    let present = false
    if (prev.data) {
      let sum = 0
      // sample the luminance channel (every 4th byte = R) to keep it cheap
      for (let i = 0; i < cur.length; i += 4) {
        sum += Math.abs(cur[i] - prev.data[i])
      }
      const meanDelta = sum / (cur.length / 4)
      present = meanDelta > motionThreshold
    }
    prev.data = cur
    return present
  }

  async function tick() {
    if (!video || !video.videoWidth) return
    let present = false
    if (detector) present = await detectFace()
    else present = detectMotion()

    // Re-arm once the scene has been clear for a couple of samples.
    if (!present) {
      presentStreak = 0
      if (Date.now() - lastFire > cooldownMs) armed = true
      return
    }

    presentStreak += 1
    hits = present ? hits + 1 : 0
    if (armed && presentStreak >= requiredHits && Date.now() - lastFire > cooldownMs) {
      armed = false
      lastFire = Date.now()
      hits = 0
      onArrive()
    }
  }

  function start(videoEl) {
    video = videoEl
    tryCreateDetector()
    stop()
    timer = setInterval(tick, intervalMs)
  }

  function stop() {
    if (timer) clearInterval(timer)
    timer = null
    prev.data = null
  }

  onBeforeUnmount(stop)
  return { start, stop, usingFaceDetector: () => !!detector }
}
