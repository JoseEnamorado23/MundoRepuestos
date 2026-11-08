// Pitidos con WebAudio (sin archivos de audio). Silenciosos si el navegador no permite audio todavía.
let ctx: AudioContext | null = null

function tono(frecuencia: number, ms: number, inicio = 0) {
  try {
    ctx ??= new AudioContext()
    const o = ctx.createOscillator()
    const g = ctx.createGain()
    o.frequency.value = frecuencia
    o.type = 'square'
    g.gain.value = 0.08
    o.connect(g).connect(ctx.destination)
    const t0 = ctx.currentTime + inicio
    o.start(t0)
    o.stop(t0 + ms / 1000)
  } catch {
    /* sin audio: el destello visual basta */
  }
}

export const sonidoOk = () => tono(1760, 90)
export const sonidoError = () => {
  tono(300, 140)
  tono(220, 200, 0.16)
}
