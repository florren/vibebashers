/** Микрофон → PCM16 LE 16 кГц (1 или 2 канала interleaved) кадрами ~100 мс. AudioWorklet собирается из Blob, внешних файлов не нужно. */

export type MicHandle = { stop: () => void; level: () => number; sampleRate: number; channels: 1 | 2 }

const WORKLET = `
class PcmWorklet extends AudioWorkletProcessor {
  constructor(opts) {
    super()
    this.target = opts.processorOptions.targetRate
    this.channels = opts.processorOptions.channels
    this.ratio = sampleRate / this.target
    this.frame = Math.round(this.target / 10)
    this.acc = [[], []]
    this.pos = 0
  }
  process(inputs) {
    const inp = inputs[0]
    if (!inp || !inp[0]) return true
    const n = inp[0].length
    const chs = this.channels === 2 && inp[1] ? 2 : 1
    for (let i = 0; i < n; i++) {
      this.pos += 1
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio
        for (let c = 0; c < chs; c++) this.acc[c].push(inp[c][i])
      }
    }
    if (this.acc[0].length >= this.frame) {
      const len = this.acc[0].length
      const out = new Int16Array(len * this.channels)
      let peak = 0
      for (let i = 0; i < len; i++) {
        for (let c = 0; c < this.channels; c++) {
          const v = Math.max(-1, Math.min(1, (this.acc[c][i] ?? this.acc[0][i]) || 0))
          peak = Math.max(peak, Math.abs(v))
          out[i * this.channels + c] = v < 0 ? v * 0x8000 : v * 0x7fff
        }
      }
      this.acc = [[], []]
      this.port.postMessage({ pcm: out.buffer, peak }, [out.buffer])
    }
    return true
  }
}
registerProcessor('pcm-worklet', PcmWorklet)
`

export async function startMic(opts: { channels: 1 | 2; onFrame: (pcm: ArrayBuffer) => void; targetRate?: number }): Promise<MicHandle> {
  const targetRate = opts.targetRate ?? 16000
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: opts.channels, echoCancellation: opts.channels === 1, noiseSuppression: true, autoGainControl: true },
    video: false,
  })
  const ctx = new AudioContext()
  const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
  await ctx.audioWorklet.addModule(url)
  URL.revokeObjectURL(url)
  const src = ctx.createMediaStreamSource(stream)
  const realChannels: 1 | 2 = opts.channels === 2 && stream.getAudioTracks()[0]?.getSettings().channelCount === 2 ? 2 : 1
  const node = new AudioWorkletNode(ctx, 'pcm-worklet', {
    numberOfInputs: 1,
    numberOfOutputs: 0,
    channelCount: realChannels,
    channelCountMode: 'explicit',
    processorOptions: { targetRate, channels: realChannels },
  })
  let level = 0
  node.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; peak: number }>) => {
    level = e.data.peak
    opts.onFrame(e.data.pcm)
  }
  src.connect(node)
  if (ctx.state === 'suspended') await ctx.resume()
  return {
    sampleRate: targetRate,
    channels: realChannels,
    level: () => level,
    stop: () => {
      node.port.onmessage = null
      try {
        src.disconnect()
        node.disconnect()
      } catch {
        /* уже отключено */
      }
      stream.getTracks().forEach((t) => t.stop())
      void ctx.close()
    },
  }
}

export function micSupported(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof AudioWorkletNode !== 'undefined'
}
