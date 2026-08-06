import * as faceapi from 'face-api.js'

/**
 * Client-side face recognition with face-api.js.
 *
 * Runs entirely in the browser, so it works on the dev laptop AND the Pi's
 * Chromium — no server-side dlib needed. Models are bundled in /public/models.
 *
 *   loadModels()            - lazy-load the TinyFaceDetector + landmark +
 *                             recognition nets once.
 *   describe(videoOrImg)    - return a 128-d Float32Array descriptor (or null
 *                             if no face is found).
 *
 * Enrollment sends the descriptor to the backend; recognition posts a live
 * descriptor to /api/users/match.
 */
let _loaded = null

export function useFaceId() {
  async function loadModels(base = '/models') {
    if (!_loaded) {
      _loaded = Promise.all([
        faceapi.nets.tinyFaceDetector.loadFromUri(base),
        faceapi.nets.faceLandmark68Net.loadFromUri(base),
        faceapi.nets.faceRecognitionNet.loadFromUri(base),
      ])
    }
    await _loaded
  }

  function isReady() {
    return (
      faceapi.nets.tinyFaceDetector.isLoaded &&
      faceapi.nets.faceLandmark68Net.isLoaded &&
      faceapi.nets.faceRecognitionNet.isLoaded
    )
  }

  /** Compute a 128-d descriptor from a <video>/<img>/<canvas>. Returns Array|null. */
  async function describe(input) {
    if (!isReady()) await loadModels()
    const det = await faceapi
      .detectSingleFace(input, new faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.5 }))
      .withFaceLandmarks()
      .withFaceDescriptor()
    if (!det) return null
    return Array.from(det.descriptor)
  }

  /**
   * Fast detection only (no descriptor) for dwell-tracking + the dev overlay.
   * Returns {box:{x,y,width,height}, score} relative to the input's natural
   * size, or null. Much cheaper than describe().
   */
  async function detectBox(input) {
    if (!faceapi.nets.tinyFaceDetector.isLoaded) return null
    const det = await faceapi.detectSingleFace(
      input,
      new faceapi.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.5 }),
    )
    if (!det) return null
    const { x, y, width, height } = det.box
    return { box: { x, y, width, height }, score: det.score }
  }

  return { loadModels, describe, detectBox, isReady }
}
