const form = document.querySelector('#voice-form');
const promptText = document.querySelector('#prompt-text');
const transcript = document.querySelector('#reference-text');
const recordButton = document.querySelector('#record');
const stopButton = document.querySelector('#stop');
const recordingStatus = document.querySelector('#recording-status');
const preview = document.querySelector('#recording-preview');
let audioContext, source, processor, silentGain, stream, samples = [], recordingBlob;

transcript.value = promptText.textContent.trim();

function mergeSamples(parts) {
  const length = parts.reduce((total, part) => total + part.length, 0);
  const merged = new Float32Array(length);
  let offset = 0;
  parts.forEach(part => { merged.set(part, offset); offset += part.length; });
  return merged;
}

function wavBlob(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset, value) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
  write(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); write(8, 'WAVE'); write(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  write(36, 'data'); view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, index) => view.setInt16(44 + index * 2, Math.max(-1, Math.min(1, sample)) * 0x7fff, true));
  return new Blob([buffer], {type: 'audio/wav'});
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('Браузер не поддерживает запись с микрофона');
  stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false}});
  audioContext = new AudioContext();
  await audioContext.resume();
  source = audioContext.createMediaStreamSource(stream);
  processor = audioContext.createScriptProcessor(4096, 1, 1);
  silentGain = audioContext.createGain(); silentGain.gain.value = 0;
  samples = [];
  processor.onaudioprocess = event => samples.push(new Float32Array(event.inputBuffer.getChannelData(0)));
  source.connect(processor); processor.connect(silentGain); silentGain.connect(audioContext.destination);
  recordButton.disabled = true; stopButton.disabled = false;
  recordingStatus.textContent = 'Идёт запись… читайте текст выше';
}

async function stopRecording() {
  processor.disconnect(); source.disconnect(); silentGain.disconnect(); stream.getTracks().forEach(track => track.stop());
  const rate = audioContext.sampleRate;
  await audioContext.close();
  recordingBlob = wavBlob(mergeSamples(samples), rate);
  const seconds = recordingBlob.size / (rate * 2);
  preview.src = URL.createObjectURL(recordingBlob); preview.hidden = false;
  recordButton.disabled = false; stopButton.disabled = true;
  recordingStatus.textContent = `Записано: ${seconds.toFixed(1)} с`;
}

recordButton.addEventListener('click', () => startRecording().catch(error => { recordingStatus.textContent = error.message; }));
stopButton.addEventListener('click', () => stopRecording().catch(error => { recordingStatus.textContent = error.message; }));

form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = form.querySelector('button[type="submit"]');
  const status = document.querySelector('#create-status');
  const data = new FormData(form);
  if (!data.get('reference')?.size && recordingBlob) data.set('reference', recordingBlob, 'my-f5-voice.wav');
  if (!data.get('reference')?.size) { status.textContent = 'Запишите голос или выберите WAV‑файл'; return; }
  button.disabled = true; status.textContent = 'Сохраняю голос…';
  try {
    const response = await fetch('/api/voices', {method: 'POST', body: data});
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Не удалось создать голос');
    status.textContent = 'Голос готов — открываю озвучку…';
    location.href = `/?voice=${encodeURIComponent(result.id)}`;
  } catch (error) {
    status.textContent = error.message;
    button.disabled = false;
  }
});
