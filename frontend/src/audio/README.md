# NASMusicBox 音效实现与验证

这套 DSP 是独立实现，未复制汽水的 WASM、SDK、脉冲响应或收费预设。当前 REA 证据确认汽水走 `AudioEffectManager → AudioWorklet → byte_audio_tuner WASM`，配置通过 `loadConfig → prepare(sampleRate, channels) → setEnabled` 生效，空配置/处理异常走原声。没有恢复出原版数值参数，因此不能称为逐位还原或汽水官方音效。

汽水的智能音效使用曲目关联的远程配置；这里的“智能音效”是缓慢频谱自适应均衡与轻动态的独立近似方案。静音时不调参、频谱有效时约每 160 ms 取样，参数用 2.5 秒时间常数变化，避免追随每个鼓点泵动。清澈人声是均衡，不是人声分离。360 环绕是立体声声场扩展，不是多声道编码输出。

## 接入

```js
const engine = new AudioEffectsEngine({ onError, onStatus });
engine.setVolume(volume); // volume: 0..1
await engine.setPreset('off'); // 可以在 attach 之前设置
await engine.attach(audioRef.current); // 一个音频元素只创建一次媒体源
audioRef.current.volume = 1;
await engine.resume(); // 播放按钮的用户手势内调用
```

跨域音源必须经过同源媒体通道，否则浏览器会把 MediaElementAudioSource 的输出置为静音。`attach` 不会自行播放、换源或创建第二个播放器。`dispose` 保留可重用媒体源，并接回带音量的原声通路，适应 React 的再次挂载。

每个预设图独立构建，输出端用 80 ms 线性交叉淡化（相关信号不产生等功率淡化的 3 dB 增益峰）。音量在效果后控制。输出工作线程使用 3 ms 立体声关联前瞻保护、70 ms 释放和 -0.18 dBFS 样本峰上限；不支持 AudioWorklet 时退回原生样本峰限幅。效果链故障恢复原声并通过 `onError` 通知。`status.latency` 是浏览器报告基础/输出延迟加工作线程延迟的估计，不能当作实测端到端延迟；有卷积/过采样的预设还可能增加少量算法延迟。

## 预设与调音假设

| 预设 | 真实处理 | 主要独立调音参数 |
| --- | --- | --- |
| 智能 | 频谱慢速自适应 EQ、轻压缩 | 130 Hz 低架、7.5 kHz 高架，低架最多 -2.5/+1.2 dB |
| 360 环绕 | Mid/Side 矩阵、交叉声道早期反射 | Mid 0.90/Side 1.28，17/23 ms 反射 |
| 超重低音 | 高频通、低架、柔和谐波、压缩 | 28 Hz 低切，105 Hz +6 dB |
| 清澈人声 | 低切、低中频衰减、存在感增强 | 75 Hz 低切，260 Hz -3 dB，2.7 kHz +3 dB |
| 3D | 声场矩阵、短交叉反射、短房间响应 | 7/11 ms 反射，0.26 秒余韵 |
| HIFI 现场 | 确定性双声道房间脉冲、轻 EQ/压缩 | 22 ms 预延迟，0.95 秒衰减，湿声 29% |
| 动感电音 | 两端 EQ、低中频衰减、较快压缩 | 85 Hz +4.5 dB，7.8 kHz +2.2 dB，8 ms attack |
| 摇滚 | 中频/鼓点 EQ、轻饱和、保留起音的压缩 | 1.6 kHz +2.8 dB，25 ms attack |
| 复古唱片 | 频响收窄、柔和饱和、微量 wow/flutter | 90 Hz 低切、6.8 kHz 低通，0.6/5.3 Hz 调制 |

预设使用固定输出补偿降低音量差异；不同曲目的频谱/动态不同，不承诺统一 LUFS。空间预设有意保留原始直达声。所有脉冲由本项目生成，固定随机种子用于可重复测试。

## 样本级测试

在 Vite 同源页面中执行：

```js
const { runAudioEffectsChecks } = await import('/src/audio/effects.checks.js');
const report = await runAudioEffectsChecks();
```

检查真实 OfflineAudioContext 样本：十种输出有限/非静音、样本峰保护、原声保持、九种预设和两两输出有区别、低音/高频/人声频响方向、交叉声道反射、房间响应尾音与过载输入。不把配置值检查当作音频验证。主观“像汽水”仍需要可启用的对应汽水预设、响度匹配的同片段与实际桌面音箱 A/B，报告必须另列未验证项。
