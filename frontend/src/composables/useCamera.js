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
  // Actual width/height the camera delivered, once known. Cameras ignore the
  // resolution hints below freely, so this is the only trustworthy source -
  // and the viewfinder must be shaped to it, or `object-cover` silently crops
  // the preview and the guest sees a tighter shot than the one that prints.
  const videoAspect = ref(0)
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
        const v = videoRef.value
        const readAspect = () => {
          if (v.videoWidth && v.videoHeight) videoAspect.value = v.videoWidth / v.videoHeight
        }
        v.addEventListener('loadedmetadata', readAspect)
        v.srcObject = stream
        await v.play().catch(() => {})
        readAspect() // often already known by here; the listener covers the rest
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
    videoAspect.value = 0
  }

  /**
   * Capture the current frame as a JPEG Blob.
   *
   * `aspect` (width/height) centre-crops the sensor frame to the shape of the
   * print. Webcam sensors are landscape, so a portrait print needs a crop
   * somewhere - doing it here, against the same region the preview shows,
   * means the guest framed themselves for it. Nothing disappears after the
   * shutter, and the backend then has nothing left to crop.
   */
  function capture(quality = 0.92, aspect = null) {
    const v = videoRef.value
    if (!v || !v.videoWidth) return Promise.resolve(null)

    const sw = v.videoWidth
    const sh = v.videoHeight
    let cw = sw
    let ch = sh
    if (aspect > 0) {
      if (sw / sh > aspect) cw = Math.round(sh * aspect)
      else ch = Math.round(sw / aspect)
    }
    const sx = Math.round((sw - cw) / 2)
    const sy = Math.round((sh - ch) / 2)

    const canvas = document.createElement('canvas')
    canvas.width = cw
    canvas.height = ch
    // Source rect -> full canvas. Note the preview is mirrored via CSS only;
    // the capture stays unmirrored so text in the shot reads correctly.
    canvas.getContext('2d').drawImage(v, sx, sy, cw, ch, 0, 0, cw, ch)
    return new Promise((resolve) => canvas.toBlob((b) => resolve(b), 'image/jpeg', quality))
  }

  onBeforeUnmount(stop)

  return { videoRef, active, error, videoAspect, start, stop, capture }
}
