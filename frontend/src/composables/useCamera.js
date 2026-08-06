import { ref, onBeforeUnmount } from 'vue'

/**
 * Browser camera via getUserMedia.
 *
 * The kiosk shows the device's own webcam (laptop in dev, USB cam through
 * Chromium on the Pi). This avoids depending on server-side OpenCV for the
 * live feed, which is why the laptop camera now lights up.
 *
 * Usage: bind `videoRef` to a <video> element, call start(), and grab a
 * still with capture() -> Blob (JPEG) to upload to the backend.
 */
export function useCamera() {
  const videoRef = ref(null)
  const active = ref(false)
  const error = ref('')
  let stream = null

  async function start() {
    error.value = ''
    if (!navigator.mediaDevices?.getUserMedia) {
      error.value = 'This browser does not support camera access.'
      return false
    }
    try {
      // 1080p, not 720p: portrait prints centre-crop a wide capture, so a
      // 1280x720 frame leaves only 480x720 for a 10x15 sheet. `ideal` is a
      // soft constraint - cameras that top out lower just return their max.
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1920 }, height: { ideal: 1080 }, facingMode: 'user' },
        audio: false,
      })
      if (videoRef.value) {
        videoRef.value.srcObject = stream
        await videoRef.value.play().catch(() => {})
      }
      active.value = true
      return true
    } catch (e) {
      // NotAllowedError (permission), NotFoundError (no camera), etc.
      error.value =
        e.name === 'NotAllowedError'
          ? 'Camera permission denied. Allow it in the browser, then retry.'
          : e.name === 'NotFoundError'
            ? 'No camera found on this device.'
            : e.message || 'Could not start the camera.'
      active.value = false
      return false
    }
  }

  function stop() {
    stream?.getTracks().forEach((t) => t.stop())
    stream = null
    active.value = false
  }

  /** Capture the current frame as a JPEG Blob. */
  function capture(quality = 0.92) {
    const v = videoRef.value
    if (!v || !v.videoWidth) return Promise.resolve(null)
    const canvas = document.createElement('canvas')
    canvas.width = v.videoWidth
    canvas.height = v.videoHeight
    canvas.getContext('2d').drawImage(v, 0, 0, canvas.width, canvas.height)
    return new Promise((resolve) => canvas.toBlob((b) => resolve(b), 'image/jpeg', quality))
  }

  onBeforeUnmount(stop)

  return { videoRef, active, error, start, stop, capture }
}
