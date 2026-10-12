// A 3 ms look-ahead peak guard. One gain is shared by both channels, so the
// stereo image does not move when one channel contains a louder transient.
class NasPeakGuard extends AudioWorkletProcessor {
  constructor() {
    super();
    this.lookahead = Math.max(1, Math.ceil(sampleRate * 0.003));
    this.buffers = [];
    this.cursor = 0;
    this.gain = 1;
    this.hold = 0;
    this.release = Math.exp(-1 / (sampleRate * 0.07));
  }

  process(inputs, outputs) {
    const input = inputs[0];
    const output = outputs[0];
    if (!output.length) return true;
    while (this.buffers.length < output.length) {
      this.buffers.push(new Float32Array(this.lookahead));
    }
    for (let frame = 0; frame < output[0].length; frame += 1) {
      let peak = 0;
      for (let channel = 0; channel < output.length; channel += 1) {
        const source = input[channel] || input[0];
        peak = Math.max(peak, Math.abs(source?.[frame] || 0));
      }
      const wanted = peak > 0.98 ? 0.98 / peak : 1;
      if (wanted < 1) {
        this.gain = Math.min(this.gain, wanted);
        this.hold = this.lookahead;
      } else if (this.hold > 0) {
        this.hold -= 1;
      } else {
        this.gain = 1 - (1 - this.gain) * this.release;
      }
      for (let channel = 0; channel < output.length; channel += 1) {
        const source = input[channel] || input[0];
        const delayed = this.buffers[channel][this.cursor];
        this.buffers[channel][this.cursor] = source?.[frame] || 0;
        const value = delayed * this.gain;
        output[channel][frame] = Number.isFinite(value)
          ? Math.max(-0.98, Math.min(0.98, value)) : 0;
      }
      this.cursor = (this.cursor + 1) % this.lookahead;
    }
    return true;
  }
}

registerProcessor('nas-peak-guard', NasPeakGuard);
