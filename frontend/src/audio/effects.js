export const AUDIO_EFFECTS = Object.freeze([
  { id: 'off', name: '原声', description: '关闭音效，保留原始声音' },
  { id: 'smart', name: '智能音效', description: '跟随频谱，缓慢调整均衡与动态' },
  { id: 'surround', name: '360 环绕', description: '拓宽声场，增加环绕空间感' },
  { id: 'bass', name: '超重低音', description: '低频更饱满，鼓点更有力量' },
  { id: 'vocal', name: '清澈人声', description: '减少浑浊，让人声更清晰' },
  { id: 'spatial', name: '3D 音效', description: '营造前后层次与立体空间' },
  { id: 'live', name: 'HIFI 现场', description: '加入房间反射和现场余韵' },
  { id: 'electronic', name: '动感电音', description: '突出低频冲击与高频亮度' },
  { id: 'rock', name: '摇滚音效', description: '加强吉他中频与鼓点力度' },
  { id: 'vintage', name: '复古唱片', description: '温暖饱和，轻微模拟唱片摇摆' },
]);

const effectIds = new Set(AUDIO_EFFECTS.map(({ id }) => id));
const db = (value) => 10 ** (value / 20);
const mediaContexts = new WeakMap();
const workletModules = new WeakMap();
const CROSSFADE_SECONDS = 0.08;

function setSmooth(parameter, value, time, duration = CROSSFADE_SECONDS) {
  if (typeof parameter.cancelAndHoldAtTime === 'function') {
    parameter.cancelAndHoldAtTime(time);
  } else {
    const previous = parameter.value;
    parameter.cancelScheduledValues(time);
    parameter.setValueAtTime(previous, time);
  }
  parameter.linearRampToValueAtTime(value, time + duration);
}

/** Build a standalone graph, also usable with OfflineAudioContext.
 * Presets are independently tuned DSP, not the proprietary Soda WASM model.
 * The caller owns the common output volume and peak guard.
 */
export function createEffectGraph(context, presetId = 'off', options = {}) {
  if (!effectIds.has(presetId)) throw new RangeError(`Unknown audio preset: ${presetId}`);
  const nodes = [];
  const oscillators = [];
  let smartTimer = null;
  let disposed = false;
  const own = (node) => { nodes.push(node); return node; };
  const gain = (value = 1) => {
    const node = own(context.createGain());
    node.gain.value = value;
    return node;
  };
  const filter = (type, frequency, amount = 0, q = 0.707) => {
    const node = own(context.createBiquadFilter());
    node.type = type;
    node.frequency.value = frequency;
    node.gain.value = amount;
    // Low/high-pass Web Audio Q is expressed in dB; peaking Q is linear.
    node.Q.value = (type === 'lowpass' || type === 'highpass') ? 20 * Math.log10(q) : q;
    return node;
  };
  const compressor = (threshold, ratio, attack, release, knee = 12) => {
    const node = own(context.createDynamicsCompressor());
    node.threshold.value = threshold;
    node.ratio.value = ratio;
    node.attack.value = attack;
    node.release.value = release;
    node.knee.value = knee;
    return node;
  };
  const saturation = (drive) => {
    const node = own(context.createWaveShaper());
    const curve = new Float32Array(8193);
    for (let i = 0; i < curve.length; i += 1) {
      const x = 2 * i / (curve.length - 1) - 1;
      curve[i] = Math.tanh(x * drive) / Math.tanh(drive);
    }
    node.curve = curve;
    node.oversample = '4x';
    return node;
  };
  const chain = (start, ...steps) => {
    let end = start;
    for (const node of steps) { end.connect(node); end = node; }
    return end;
  };
  const input = gain();
  input.channelCount = 2;
  input.channelCountMode = 'explicit';
  const output = gain();
  let tailSeconds = 0;

  function stereoSpace(start, { mid = 1, side = 1, leftDelay = 0.017, rightDelay = 0.023, reflection = 0.12 } = {}) {
    const splitter = own(context.createChannelSplitter(2));
    const merger = own(context.createChannelMerger(2));
    start.connect(splitter);
    const direct = (mid + side) / 2;
    const cross = (mid - side) / 2;
    [[0, 0, direct], [1, 1, direct], [0, 1, cross], [1, 0, cross]].forEach(([from, to, amount]) => {
      const matrixGain = gain(amount);
      splitter.connect(matrixGain, from);
      matrixGain.connect(merger, 0, to);
    });
    [[0, 1, leftDelay], [1, 0, rightDelay]].forEach(([from, to, seconds]) => {
      const delay = own(context.createDelay(0.1));
      delay.delayTime.value = seconds;
      const tone = filter('lowpass', 6500);
      const reflectionGain = gain(reflection);
      splitter.connect(delay, from);
      delay.connect(tone);
      tone.connect(reflectionGain);
      reflectionGain.connect(merger, 0, to);
    });
    tailSeconds = Math.max(tailSeconds, leftDelay, rightDelay);
    return merger;
  }

  function room(start, duration, wet, preDelay = 0.02) {
    const convolver = own(context.createConvolver());
    convolver.normalize = false;
    const length = Math.ceil(context.sampleRate * (duration + preDelay));
    const buffer = context.createBuffer(2, length, context.sampleRate);
    let randomState = options.seed ?? 0x4e4153;
    const random = () => {
      randomState = (1664525 * randomState + 1013904223) >>> 0;
      return randomState / 0x100000000 * 2 - 1;
    };
    for (let channel = 0; channel < 2; channel += 1) {
      const data = buffer.getChannelData(channel);
      const first = Math.ceil(preDelay * context.sampleRate);
      let energy = 0;
      for (let i = first; i < length; i += 1) {
        const progress = (i - first) / Math.max(1, length - first);
        data[i] = random() * Math.exp(-6 * progress);
        energy += data[i] ** 2;
      }
      const scale = 1 / Math.sqrt(Math.max(energy, 1));
      for (let i = first; i < length; i += 1) data[i] *= scale;
    }
    convolver.buffer = buffer;
    const mix = gain();
    chain(start, gain(1 - wet * 0.45), mix);
    chain(start, filter('highpass', 140), filter('lowpass', 6200), convolver, gain(wet), mix);
    tailSeconds = Math.max(tailSeconds, duration + preDelay);
    return mix;
  }

  if (presetId === 'off') {
    input.connect(output);
  } else if (presetId === 'smart') {
    const analyser = own(context.createAnalyser());
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.8;
    const low = filter('lowshelf', 130, 0);
    const presence = filter('peaking', 2400, 0.8, 0.7);
    const high = filter('highshelf', 7500, 0);
    chain(input, analyser, low, filter('peaking', 340, -0.8, 0.65), presence, high,
      compressor(-18, 1.65, 0.03, 0.24, 18), gain(db(-1.6)), output);
    const spectrum = new Float32Array(analyser.frequencyBinCount);
    const update = () => {
      if (disposed || context.state !== 'running') return;
      analyser.getFloatFrequencyData(spectrum);
      let total = 0; let bass = 0; let treble = 0;
      for (let i = 1; i < spectrum.length; i += 1) {
        const power = 10 ** (spectrum[i] / 10);
        const frequency = i * context.sampleRate / analyser.fftSize;
        if (frequency < 40 || frequency > 16000) continue;
        total += power;
        if (frequency < 180) bass += power;
        if (frequency > 5000) treble += power;
      }
      if (total < 1e-7) return;
      const bassShare = bass / total;
      const trebleShare = treble / total;
      const bassTarget = Math.max(-2.5, Math.min(1.2, (0.27 - bassShare) * 5));
      const trebleTarget = Math.max(-1.2, Math.min(1.4, (0.09 - trebleShare) * 8));
      low.gain.setTargetAtTime(bassTarget, context.currentTime, 2.5);
      high.gain.setTargetAtTime(trebleTarget, context.currentTime, 2.5);
    };
    if (options.realtime !== false && typeof context.startRendering !== 'function') {
      smartTimer = setInterval(update, 160);
    }
  } else if (presetId === 'surround') {
    chain(stereoSpace(input, { mid: 0.9, side: 1.28, reflection: 0.14 }),
      filter('highpass', 32), gain(db(-0.9)), output);
  } else if (presetId === 'bass') {
    chain(input, filter('highpass', 28, 0, 0.65), filter('lowshelf', 105, 6),
      saturation(1.16), compressor(-17, 2.4, 0.012, 0.18), gain(db(-6.7)), output);
  } else if (presetId === 'vocal') {
    chain(input, filter('highpass', 75), filter('peaking', 260, -3, 0.8),
      filter('peaking', 2700, 3, 0.7), filter('highshelf', 9000, 0.5),
      compressor(-15, 1.55, 0.025, 0.2), gain(db(-0.6)), output);
  } else if (presetId === 'spatial') {
    const space = stereoSpace(input, { mid: 0.96, side: 1.06, leftDelay: 0.007, rightDelay: 0.011, reflection: 0.24 });
    chain(room(space, 0.26, 0.12, 0.012), filter('peaking', 3400, 1.1, 0.65), gain(db(-0.8)), output);
  } else if (presetId === 'live') {
    chain(room(input, 0.95, 0.29, 0.022), filter('lowshelf', 150, 0.8),
      filter('peaking', 2500, 0.8, 0.7), compressor(-18, 1.5, 0.04, 0.25), gain(db(-1.4)), output);
  } else if (presetId === 'electronic') {
    chain(input, filter('highpass', 30), filter('lowshelf', 85, 4.5),
      filter('peaking', 650, -1.2, 0.8), filter('highshelf', 7800, 2.2),
      compressor(-20, 3, 0.008, 0.11), gain(db(-4.4)), output);
  } else if (presetId === 'rock') {
    chain(input, filter('lowshelf', 110, 2.4), filter('peaking', 1600, 2.8, 0.8),
      filter('highshelf', 7000, 0.7), saturation(1.08),
      compressor(-19, 2.1, 0.025, 0.12), gain(db(-6.5)), output);
  } else if (presetId === 'vintage') {
    const wowDelay = own(context.createDelay(0.02));
    wowDelay.delayTime.value = 0.0035;
    [[0.6, 0.00035], [5.3, 0.000025]].forEach(([frequency, amount]) => {
      const oscillator = own(context.createOscillator());
      oscillator.frequency.value = frequency;
      oscillator.connect(gain(amount)).connect(wowDelay.delayTime);
      oscillator.start();
      oscillators.push(oscillator);
    });
    chain(input, filter('highpass', 90), filter('lowpass', 6800),
      filter('lowpass', 9500), filter('peaking', 600, 1.5, 0.65),
      saturation(1.4), compressor(-16, 1.8, 0.02, 0.18), wowDelay, gain(db(-3.8)), output);
    tailSeconds = Math.max(tailSeconds, 0.004);
  }

  return {
    input, output, preset: presetId, tailSeconds,
    dispose() {
      if (disposed) return;
      disposed = true;
      if (smartTimer) clearInterval(smartTimer);
      for (const oscillator of oscillators) { try { oscillator.stop(); } catch { /* already stopped */ } }
      for (const node of nodes) { try { node.disconnect(); } catch { /* detached */ } }
    },
  };
}

/** Native fallback also used by deterministic offline checks. The normal
 * real-time output uses the worklet's stereo-linked 3 ms look-ahead limiter.
 */
export function createSafetyStage(context) {
  const input = context.createGain();
  const clip = context.createWaveShaper();
  const curve = new Float32Array(65537);
  for (let i = 0; i < curve.length; i += 1) {
    const x = i * 2 / (curve.length - 1) - 1;
    curve[i] = Math.max(-0.98, Math.min(0.98, x));
  }
  clip.curve = curve;
  clip.oversample = 'none';
  input.connect(clip);
  return { input, output: clip, dispose() { input.disconnect(); clip.disconnect(); } };
}

function loadPeakGuard(context) {
  if (!context.audioWorklet || typeof AudioWorkletNode === 'undefined') return Promise.resolve(false);
  if (!workletModules.has(context)) {
    workletModules.set(context, context.audioWorklet.addModule(new URL('./limiter.worklet.js', import.meta.url)).then(() => true).catch(() => false));
  }
  return workletModules.get(context);
}

export class AudioEffectsEngine {
  constructor({ onError = () => {}, onStatus = () => {} } = {}) {
    this.onError = onError;
    this.onStatus = onStatus;
    this.preset = 'off';
    this.volume = 1;
    this.context = null;
    this.element = null;
    this.source = null;
    this.master = null;
    this.safety = null;
    this.graph = null;
    this.graphs = new Set();
    this.cleanupTimers = new Set();
    this.attachPromise = null;
    this.disposed = false;
    this.lastError = '';
    this.limiterMode = 'native';
  }

  get latency() {
    return (this.context?.baseLatency || 0) + (this.context?.outputLatency || 0)
      + (this.limiterMode === 'lookahead' ? 0.003 : 0);
  }

  get status() {
    return {
      state: this.disposed ? 'disposed' : (this.context?.state || 'idle'),
      preset: this.preset, limiter: this.limiterMode, latency: this.latency,
      sampleRate: this.context?.sampleRate || null, error: this.lastError,
    };
  }

  notify() { this.onStatus(this.status); }

  async attach(audioElement) {
    if (this.disposed) throw new Error('AudioEffectsEngine is disposed');
    if (this.element && this.element !== audioElement) throw new Error('One engine owns one audio element');
    if (this.attachPromise) return this.attachPromise;
    this.element = audioElement;
    this.attachPromise = this.attachInternal(audioElement);
    try { await this.attachPromise; } catch (error) {
      this.lastError = error.message;
      this.onError(error);
      this.notify();
      throw error;
    }
  }

  async attachInternal(audioElement) {
    let shared = mediaContexts.get(audioElement);
    if (!shared) {
      const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext;
      if (!AudioContextClass) throw new Error('当前播放环境不支持 Web Audio');
      const context = new AudioContextClass({ latencyHint: 'interactive' });
      const source = context.createMediaElementSource(audioElement);
      shared = { context, source, owner: null, fallback: null };
      mediaContexts.set(audioElement, shared);
    }
    if (shared.owner && shared.owner !== this) shared.owner.dispose();
    if (shared.fallback) {
      shared.source.disconnect(shared.fallback);
      shared.fallback.disconnect();
      shared.fallback = null;
    }
    shared.owner = this;
    this.context = shared.context;
    this.source = shared.source;
    this.master = this.context.createGain();
    this.master.gain.value = this.volume;
    this.safety = createSafetyStage(this.context);
    this.master.connect(this.safety.input);
    this.safety.output.connect(this.context.destination);
    this.switchGraph(this.preset, false);
    const loaded = await loadPeakGuard(this.context);
    if (this.disposed) return;
    if (loaded) {
      try {
        const worklet = new AudioWorkletNode(this.context, 'nas-peak-guard', {
          numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [2],
          channelCount: 2, channelCountMode: 'explicit',
        });
        worklet.addEventListener('processorerror', () => this.recoverOutput(new Error('音效输出保护器异常，已恢复原声')));
        this.master.disconnect();
        this.safety.dispose();
        this.safety = { input: worklet, output: worklet, dispose: () => worklet.disconnect() };
        this.master.connect(worklet);
        worklet.connect(this.context.destination);
        this.limiterMode = 'lookahead';
      } catch (error) { this.lastError = error.message; }
    }
    this.context.onstatechange = () => this.notify();
    this.notify();
  }

  switchGraph(id, smooth = true) {
    const next = createEffectGraph(this.context, id);
    const fader = this.context.createGain();
    next.fader = fader;
    fader.gain.value = smooth && this.graph ? 0 : 1;
    this.source.connect(next.input);
    next.output.connect(fader);
    fader.connect(this.master);
    this.graphs.add(next);
    const previous = this.graph;
    this.graph = next;
    if (previous) {
      const time = this.context.currentTime;
      setSmooth(previous.fader.gain, 0, time);
      setSmooth(fader.gain, 1, time);
      const timer = setTimeout(() => {
        this.cleanupTimers.delete(timer);
        this.removeGraph(previous);
      }, CROSSFADE_SECONDS * 1000 + 40);
      this.cleanupTimers.add(timer);
    }
  }

  removeGraph(graph) {
    if (!this.graphs.has(graph)) return;
    try { this.source.disconnect(graph.input); } catch { /* already detached */ }
    graph.dispose();
    graph.fader.disconnect();
    this.graphs.delete(graph);
  }

  async setPreset(id) {
    if (!effectIds.has(id)) throw new RangeError(`Unknown audio preset: ${id}`);
    if (this.disposed) return;
    if (id === this.preset && (!this.context || this.graph?.preset === id)) return;
    this.preset = id;
    if (this.context) {
      try { this.switchGraph(id); this.lastError = ''; } catch (error) { this.recoverOutput(error); }
    }
    this.notify();
  }

  setVolume(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return;
    this.volume = Math.max(0, Math.min(1, parsed));
    if (this.master) setSmooth(this.master.gain, this.volume, this.context.currentTime, 0.025);
  }

  async resume() {
    if (this.context?.state === 'suspended') await this.context.resume();
    this.notify();
  }

  recoverOutput(error) {
    this.lastError = error.message;
    this.preset = 'off';
    try {
      this.master.disconnect();
      this.safety?.dispose();
      this.safety = createSafetyStage(this.context);
      this.master.connect(this.safety.input);
      this.safety.output.connect(this.context.destination);
      this.limiterMode = 'native';
      this.switchGraph('off');
    } catch {
      // Creating a media-element source transfers routing permanently. Keep a
      // direct volume-controlled route if even rebuilding the guard fails.
      for (const graph of [...this.graphs]) this.removeGraph(graph);
      try { this.source.disconnect(); } catch { /* no connections */ }
      this.source.connect(this.master);
      this.master.connect(this.context.destination);
    }
    this.onError(error);
    this.notify();
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    for (const timer of this.cleanupTimers) clearTimeout(timer);
    this.cleanupTimers.clear();
    for (const graph of [...this.graphs]) this.removeGraph(graph);
    this.master?.disconnect();
    this.safety?.dispose();
    const shared = this.element && mediaContexts.get(this.element);
    if (shared?.owner === this) {
      // A later React mount must reuse the same MediaElementAudioSourceNode.
      // Do not close its context; leave ordinary playback working meanwhile.
      const fallback = shared.context.createGain();
      fallback.gain.value = this.volume;
      shared.source.connect(fallback);
      fallback.connect(shared.context.destination);
      shared.fallback = fallback;
      shared.owner = null;
    }
    this.notify();
  }
}
