import { AUDIO_EFFECTS, AudioEffectsEngine, createEffectGraph, createSafetyStage } from './effects';

const SAMPLE_RATE = 48000;

function fixture(context, duration = 1.6, amplitude = 0.24) {
  const buffer = context.createBuffer(2, Math.ceil(SAMPLE_RATE * duration), SAMPLE_RATE);
  for (let channel = 0; channel < 2; channel += 1) {
    const data = buffer.getChannelData(channel);
    for (let i = 0; i < data.length; i += 1) {
      const t = i / SAMPLE_RATE;
      // Distinct right-channel content tests stereo width instead of only mono EQ.
      const bass = Math.sin(2 * Math.PI * 80 * t) * 0.43;
      const middle = Math.sin(2 * Math.PI * (channel ? 1250 : 1000) * t) * 0.39;
      const top = Math.sin(2 * Math.PI * 10000 * t) * 0.18;
      const drum = Math.exp(-((t % 0.4) * 45)) * Math.sin(2 * Math.PI * 135 * t) * 0.2;
      data[i] = amplitude * (bass + middle + top + drum);
    }
  }
  return buffer;
}

async function render(id, { duration = 1.6, amplitude = 0.24, impulse = false, safety = true } = {}) {
  const context = new OfflineAudioContext(2, SAMPLE_RATE * (duration + 1.1), SAMPLE_RATE);
  const input = impulse ? context.createBuffer(2, SAMPLE_RATE * duration, SAMPLE_RATE) : fixture(context, duration, amplitude);
  if (impulse) input.getChannelData(0)[SAMPLE_RATE * 0.1] = amplitude;
  const source = context.createBufferSource();
  source.buffer = input;
  const graph = createEffectGraph(context, id, { realtime: false, seed: 1234 });
  source.connect(graph.input);
  let guard = null;
  if (safety) {
    guard = createSafetyStage(context);
    graph.output.connect(guard.input);
    guard.output.connect(context.destination);
  } else graph.output.connect(context.destination);
  source.start();
  const buffer = await context.startRendering();
  graph.dispose();
  guard?.dispose();
  return { buffer, input };
}

function energy(buffer, start = 0.25, end = 1.35, channel = null) {
  let sum = 0; let count = 0; let peak = 0;
  const channels = channel === null ? [0, 1] : [channel];
  for (const ch of channels) {
    const data = buffer.getChannelData(ch);
    const first = Math.floor(start * SAMPLE_RATE);
    const last = Math.min(data.length, Math.floor(end * SAMPLE_RATE));
    for (let i = first; i < last; i += 1) {
      if (!Number.isFinite(data[i])) return { rms: NaN, peak: NaN };
      sum += data[i] ** 2;
      peak = Math.max(peak, Math.abs(data[i]));
      count += 1;
    }
  }
  return { rms: Math.sqrt(sum / Math.max(1, count)), peak };
}

function toneMagnitude(buffer, frequency, start = 0.8, end = 1.3) {
  const data = buffer.getChannelData(0);
  let real = 0; let imaginary = 0;
  const first = Math.floor(start * SAMPLE_RATE);
  const last = Math.min(data.length, Math.floor(end * SAMPLE_RATE));
  for (let i = first; i < last; i += 1) {
    const phase = 2 * Math.PI * frequency * i / SAMPLE_RATE;
    real += data[i] * Math.cos(phase);
    imaginary += data[i] * Math.sin(phase);
  }
  return Math.hypot(real, imaginary) * 2 / Math.max(1, last - first);
}

function difference(left, right) {
  let sum = 0; let count = 0;
  for (let channel = 0; channel < 2; channel += 1) {
    const a = left.getChannelData(channel);
    const b = right.getChannelData(channel);
    for (let i = SAMPLE_RATE * 0.3; i < SAMPLE_RATE * 1.3; i += 1) {
      sum += (a[i] - b[i]) ** 2;
      count += 1;
    }
  }
  return Math.sqrt(sum / count);
}

/** Browser automation entrypoint. Checks actual rendered samples, not a copy
 * of the preset definitions. Returns measurements as well as assertions.
 */
export async function runAudioEffectsChecks() {
  const checks = [];
  const measurements = {};
  const assert = (name, ok, detail) => { checks.push({ name, ok: Boolean(ok), detail }); };
  const renders = new Map();
  for (const preset of AUDIO_EFFECTS) {
    const rendered = await render(preset.id);
    renders.set(preset.id, rendered.buffer);
    const stats = energy(rendered.buffer);
    const bass = toneMagnitude(rendered.buffer, 80);
    const mid = toneMagnitude(rendered.buffer, 1000);
    const treble = toneMagnitude(rendered.buffer, 10000);
    measurements[preset.id] = { ...stats, bass, mid, treble, bassMidRatio: bass / mid, trebleMidRatio: treble / mid };
    assert(`${preset.id}: finite audible stereo output`, stats.rms > 0.006 && Number.isFinite(stats.rms), stats);
    assert(`${preset.id}: protected peaks`, stats.peak <= 0.981, stats.peak);
  }

  const dry = renders.get('off');
  const context = new OfflineAudioContext(2, SAMPLE_RATE * 1.6, SAMPLE_RATE);
  const original = fixture(context);
  assert('off: dry path preserves uncompressed input', difference(dry, original) < 0.00001, difference(dry, original));
  for (const preset of AUDIO_EFFECTS.filter(({ id }) => id !== 'off')) {
    const delta = difference(dry, renders.get(preset.id));
    assert(`${preset.id}: changes real audio`, delta > 0.001, delta);
    const changeDb = 20 * Math.log10(measurements[preset.id].rms / measurements.off.rms);
    measurements[preset.id].relativeRmsDb = changeDb;
    assert(`${preset.id}: gain compensation within 2 dB on fixture`, Math.abs(changeDb) < 2, changeDb);
  }
  for (let a = 1; a < AUDIO_EFFECTS.length; a += 1) {
    for (let b = a + 1; b < AUDIO_EFFECTS.length; b += 1) {
      const first = AUDIO_EFFECTS[a].id; const second = AUDIO_EFFECTS[b].id;
      const delta = difference(renders.get(first), renders.get(second));
      assert(`${first}/${second}: distinct rendering`, delta > 0.0003, delta);
    }
  }
  assert('bass: boosts low-frequency balance', measurements.bass.bassMidRatio > measurements.off.bassMidRatio * 1.5, measurements.bass.bassMidRatio);
  assert('vintage: rolls off high frequencies', measurements.vintage.trebleMidRatio < measurements.off.trebleMidRatio * 0.65, measurements.vintage.trebleMidRatio);
  assert('vocal: reduces low-frequency balance', measurements.vocal.bassMidRatio < measurements.off.bassMidRatio * 0.85, measurements.vocal.bassMidRatio);
  assert('electronic: lifts bass and highs relative to middle', measurements.electronic.bassMidRatio > measurements.off.bassMidRatio * 1.3 && measurements.electronic.trebleMidRatio > measurements.off.trebleMidRatio * 1.15, measurements.electronic);

  for (const id of ['surround', 'spatial']) {
    const { buffer } = await render(id, { impulse: true, amplitude: 0.5 });
    const reflected = energy(buffer, 0.105, 0.15, 1).rms;
    assert(`${id}: real cross-channel reflections`, reflected > 0.0001, reflected);
  }
  const { buffer: room } = await render('live', { impulse: true, amplitude: 0.5 });
  const tail = energy(room, 0.16, 0.65).rms;
  assert('live: audible decaying room response', tail > 0.00001, tail);
  const { buffer: loud } = await render('bass', { amplitude: 4 });
  const loudStats = energy(loud, 0, 2.5);
  assert('overload: peak guard holds ceiling without NaN', loudStats.peak <= 0.981 && Number.isFinite(loudStats.rms), loudStats);
  const failed = checks.filter(({ ok }) => !ok);
  return { ok: failed.length === 0, sampleRate: SAMPLE_RATE, checks, measurements, failed };
}

function toWav(buffer) {
  const frames = buffer.length;
  const output = new ArrayBuffer(44 + frames * 4);
  const view = new DataView(output);
  const write = (offset, text) => [...text].forEach((character, index) => view.setUint8(offset + index, character.charCodeAt(0)));
  write(0, 'RIFF'); view.setUint32(4, 36 + frames * 4, true); write(8, 'WAVE');
  write(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 2, true); view.setUint32(24, buffer.sampleRate, true);
  view.setUint32(28, buffer.sampleRate * 4, true); view.setUint16(32, 4, true); view.setUint16(34, 16, true);
  write(36, 'data'); view.setUint32(40, frames * 4, true);
  const left = buffer.getChannelData(0); const right = buffer.getChannelData(1);
  for (let i = 0; i < frames; i += 1) {
    view.setInt16(44 + i * 4, Math.max(-32768, Math.min(32767, Math.round(left[i] * 32767))), true);
    view.setInt16(46 + i * 4, Math.max(-32768, Math.min(32767, Math.round(right[i] * 32767))), true);
  }
  return new Blob([output], { type: 'audio/wav' });
}

const statsProcessor = `class NasTestStats extends AudioWorkletProcessor {
  constructor() { super(); this.pending = null; this.port.onmessage = ({data}) => {
    this.pending = { frames: data.frames, seen: 0, sum: [0, 0], peak: 0, finite: true, minBlockRms: 10 };
  }; }
  process(inputs, outputs) {
    const input = inputs[0]; const output = outputs[0];
    for(let channel=0;channel<output.length;channel++) output[channel].set(input[channel] || input[0] || new Float32Array(output[channel].length));
    const stats = this.pending;
    if (!stats || !input[0]) return true;
    let blockEnergy=0; let blockCount=0;
    for(let i=0;i<input[0].length && stats.seen<stats.frames;i++,stats.seen++) {
      for(let c=0;c<2;c++) {
        const value=(input[c] || input[0])[i];
        if (!Number.isFinite(value)) stats.finite=false;
        stats.sum[c]+=value*value; stats.peak=Math.max(stats.peak,Math.abs(value));
        blockEnergy+=value*value;blockCount++;
      }
    }
    if(blockCount) stats.minBlockRms=Math.min(stats.minBlockRms,Math.sqrt(blockEnergy/blockCount));
    if(stats.seen>=stats.frames) {
      this.port.postMessage({finite:stats.finite,peak:stats.peak,rms:stats.sum.map(s=>Math.sqrt(s/stats.seen)),minBlockRms:stats.minBlockRms});
      this.pending=null;
    }
    return true;
  }
}; registerProcessor('nas-test-stats',NasTestStats);`;

const statsModules = new WeakMap();
async function recorder(context) {
  if (!statsModules.has(context)) {
    const script = URL.createObjectURL(new Blob([statsProcessor], { type: 'text/javascript' }));
    statsModules.set(context, context.audioWorklet.addModule(script).finally(() => URL.revokeObjectURL(script)));
  }
  await statsModules.get(context);
  const node = new AudioWorkletNode(context, 'nas-test-stats', { outputChannelCount: [2] });
  const muted = context.createGain();
  muted.gain.value = 0;
  node.connect(muted).connect(context.destination);
  return {
    node,
    sample(seconds = 0.12) {
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('Audio capture timed out')), 5000);
        node.port.onmessage = ({ data }) => { clearTimeout(timer); resolve(data); };
        node.port.postMessage({ frames: Math.ceil(context.sampleRate * seconds) });
      });
    },
    dispose() { node.disconnect(); muted.disconnect(); },
  };
}

const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

/** Real-time checks exercise the MediaElement source and the shipped worklet.
 * Test audio is routed to a muted sink, so no user's desktop audio is recorded.
 */
export async function runAudioEngineChecks() {
  const checks = []; const measurements = {};
  const assert = (name, ok, detail) => checks.push({ name, ok: Boolean(ok), detail });
  const errors = [];
  const audio = new Audio();
  // Keep the source continuous throughout switching checks. Short HTMLMediaElement
  // loops can insert silent decoder blocks unrelated to the effect crossfade.
  const fixtureContext = new OfflineAudioContext(2, SAMPLE_RATE * 12, SAMPLE_RATE);
  const url = URL.createObjectURL(toWav(fixture(fixtureContext, 12, 0.35)));
  audio.src = url; audio.loop = true;
  let engine = new AudioEffectsEngine({ onError: (error) => errors.push(error.message) });
  let capture = null;
  try {
    await engine.attach(audio);
    const source = engine.source;
    await engine.attach(audio);
    assert('attach: idempotent MediaElement source', engine.source === source);
    assert('runtime: shipped limiter worklet loaded', engine.status.limiter === 'lookahead', engine.status);
    capture = await recorder(engine.context);
    engine.safety.output.disconnect(engine.context.destination);
    engine.safety.output.connect(capture.node);
    await engine.resume();
    await audio.play();
    await pause(100);
    for (const { id } of AUDIO_EFFECTS) {
      await engine.setPreset(id);
      const state = engine.graph;
      await engine.setPreset(id);
      assert(`${id}: repeated selection preserves graph`, state === engine.graph);
      await pause(140);
      const sample = await capture.sample();
      measurements[id] = sample;
      assert(`${id}: real source remains audible and finite`, sample.finite && sample.rms[0] > 0.003, sample);
      assert(`${id}: real-time output is peak protected`, sample.peak <= 0.981, sample.peak);
    }
    await engine.setPreset('off'); await pause(150);
    engine.setVolume(1); await pause(40);
    const fullVolume = await capture.sample();
    engine.setVolume(0.25); await pause(50);
    const quarterVolume = await capture.sample();
    const volumeRatio = quarterVolume.rms[0] / fullVolume.rms[0];
    assert('volume: output gain follows 0.25 setting', volumeRatio > 0.2 && volumeRatio < 0.3, volumeRatio);
    engine.setVolume(1);
    const continuity = capture.sample(0.35);
    await engine.setPreset('bass'); await pause(15);
    await engine.setPreset('vocal'); await pause(15);
    await engine.setPreset('off');
    const switching = await continuity;
    assert('switching: rapid presets have no silent processing blocks', switching.finite && switching.minBlockRms > 0.001, switching);
    engine.safety.input.dispatchEvent(new Event('processorerror'));
    engine.safety.output.disconnect(engine.context.destination);
    engine.safety.output.connect(capture.node);
    await pause(150);
    const recovered = await capture.sample();
    assert('injected worklet failure: returns to dry/native without silence', engine.preset === 'off' && engine.status.limiter === 'native' && errors.length === 1 && recovered.rms[0] > 0.003, { status: engine.status, recovered });
    audio.pause();
    capture.dispose(); capture = null;
    engine.dispose();
    engine = new AudioEffectsEngine();
    await engine.attach(audio);
    assert('remount: original MediaElement source reused', engine.source === source);
    capture = await recorder(engine.context);
    engine.safety.output.disconnect(engine.context.destination);
    engine.safety.output.connect(capture.node);
    await engine.resume(); await audio.play(); await pause(100);
    const remounted = await capture.sample();
    assert('remount: playback still audible', remounted.rms[0] > 0.003, remounted);
  } finally {
    audio.pause();
    capture?.dispose();
    engine.dispose();
    audio.removeAttribute('src'); audio.load();
    URL.revokeObjectURL(url);
  }

  const context = new AudioContext();
  let stats = null;
  try {
    await context.audioWorklet.addModule(new URL('./limiter.worklet.js', import.meta.url));
    const limiter = new AudioWorkletNode(context, 'nas-peak-guard', { outputChannelCount: [2] });
    stats = await recorder(context);
    limiter.connect(stats.node);
    const input = context.createBuffer(2, context.sampleRate, context.sampleRate);
    for (let i = 0; i < input.length; i += 1) {
      const value = (i % 512 < 4) ? 3 : 0.4 * Math.sin(2 * Math.PI * 200 * i / context.sampleRate);
      input.getChannelData(0)[i] = value;
      input.getChannelData(1)[i] = value * 0.5;
    }
    const source = context.createBufferSource(); source.buffer = input; source.loop = true;
    source.connect(limiter); await context.resume(); source.start(); await pause(50);
    const stress = await stats.sample(0.25);
    measurements.workletStress = stress;
    assert('worklet overload: 3x full-scale input held below ceiling', stress.finite && stress.peak > 0.9 && stress.peak <= 0.981, stress);
    assert('worklet overload: stereo-linked gain preserves balance', Math.abs(stress.rms[1] / stress.rms[0] - 0.5) < 0.002, stress.rms);
    source.stop(); source.disconnect(); limiter.disconnect();
  } finally { stats?.dispose(); await context.close(); }
  const failed = checks.filter(({ ok }) => !ok);
  return { ok: failed.length === 0, checks, measurements, failed };
}

function auditionFixture(context, seconds = 8) {
  const buffer = context.createBuffer(2, context.sampleRate * seconds, context.sampleRate);
  const chords = [[130.81, 164.81, 196], [110, 130.81, 164.81], [87.31, 110, 130.81], [98, 123.47, 146.83]];
  const melody = [392, 329.63, 293.66, 329.63, 440, 392, 329.63, 261.63, 349.23, 329.63, 261.63, 293.66, 392, 369.99, 293.66, 261.63];
  let random = 2147;
  for (let i = 0; i < buffer.length; i += 1) {
    const t = i / context.sampleRate;
    const chord = chords[Math.min(3, Math.floor(t / 2))];
    const noteAge = t % 0.5;
    const beatAge = t % 0.5;
    const hatAge = t % 0.25;
    const note = melody[Math.floor(t * 2) % melody.length];
    random = (1664525 * random + 1013904223) >>> 0;
    const noise = random / 0x100000000 * 2 - 1;
    const envelope = Math.min(1, t / 0.02, (seconds - t) / 0.1);
    const bass = Math.sin(2 * Math.PI * chord[0] / 2 * t) * Math.exp(-beatAge * 3) * 0.16;
    const kick = Math.sin(2 * Math.PI * (48 * beatAge + 20 * (1 - Math.exp(-beatAge * 35)) / 35)) * Math.exp(-beatAge * 20) * 0.18;
    const snare = Math.floor(t * 2) % 2 ? noise * Math.exp(-beatAge * 35) * 0.055 : 0;
    const hat = noise * Math.exp(-hatAge * 90) * 0.035;
    for (let channel = 0; channel < 2; channel += 1) {
      const pad = chord.reduce((sum, frequency, index) => sum + Math.sin(2 * Math.PI * frequency * t + channel * (index + 1) * 0.08), 0) * 0.032;
      const lead = (Math.sin(2 * Math.PI * note * t) + Math.sin(4 * Math.PI * note * t) * 0.23 + Math.sin(6 * Math.PI * note * t) * 0.1) * Math.exp(-noteAge * 3) * 0.09;
      buffer.getChannelData(channel)[i] = (pad + lead + bass + kick + snare + hat) * Math.max(0, envelope);
    }
  }
  return buffer;
}

/** Audition exports contain only original procedural test music. RMS matching
 * makes listening comparisons less biased by each preset's gain. This is not
 * a recording of Soda or a perceptual/LUFS fidelity test.
 */
export async function renderAudioEffectsPreviews() {
  const items = [];
  let targetRms = Infinity;
  for (const { id, name } of AUDIO_EFFECTS) {
    const context = new OfflineAudioContext(2, SAMPLE_RATE * 9.1, SAMPLE_RATE);
    const source = context.createBufferSource();
    source.buffer = auditionFixture(context);
    const graph = createEffectGraph(context, id, { realtime: false, seed: 1234 });
    const safety = createSafetyStage(context);
    source.connect(graph.input); graph.output.connect(safety.input); safety.output.connect(context.destination); source.start();
    const buffer = await context.startRendering();
    graph.dispose(); safety.dispose();
    const stats = energy(buffer, 0.2, 7.8);
    const all = energy(buffer, 0, 9.1);
    if (id === 'off') targetRms = stats.rms;
    targetRms = Math.min(targetRms, stats.rms * 0.85 / Math.max(all.peak, 0.01));
    items.push({ id, name, buffer, stats, originalPeak: all.peak });
  }
  const previews = [];
  for (const item of items) {
    const matchGain = targetRms / item.stats.rms;
    for (let channel = 0; channel < item.buffer.numberOfChannels; channel += 1) {
      const data = item.buffer.getChannelData(channel);
      for (let i = 0; i < data.length; i += 1) data[i] *= matchGain;
    }
    const bytes = new Uint8Array(await toWav(item.buffer).arrayBuffer());
    let binary = '';
    for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
    previews.push({ id: item.id, name: item.name, rms: targetRms, originalRms: item.stats.rms, matchGain, peak: item.originalPeak * matchGain, wavBase64: btoa(binary) });
  }
  return { description: 'Original procedural music, 48 kHz stereo 16-bit PCM; RMS matched across all 10 samples. Not Soda recordings or LUFS matching.', previews };
}
