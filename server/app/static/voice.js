const form = document.querySelector('#voice-form');
const promptText = document.querySelector('#prompt-text');
const transcript = document.querySelector('#reference-text');
const recordButton = document.querySelector('#record');
const stopButton = document.querySelector('#stop');
const recordingStatus = document.querySelector('#recording-status');
const preview = document.querySelector('#recording-preview');
let audioContext, source, processor, silentGain, stream, samples = [], recordingBlob, recordingSeconds = 0;
let moderationEnabled = false;
let customVoiceRecords = [];

transcript.value = promptText.textContent.trim();

async function apiError(response, fallback) {
  const body = await response.json().catch(() => ({}));
  return typeof body.detail === 'string' ? body.detail : fallback;
}

function renderVoiceModeration() {
  const root = document.querySelector('#custom-voices');
  root.replaceChildren();
  if (!moderationEnabled || !customVoiceRecords.length) return;
  const title = document.createElement('p');
  title.className = 'hint voice-management-title';
  title.textContent = 'Управление сохранёнными F5-голосами';
  root.append(title);
  customVoiceRecords.forEach(voice => {
    const row = document.createElement('div');
    row.className = 'voice-management-row';
    const name = document.createElement('span');
    name.textContent = voice.name;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'quiet delete-voice';
    remove.textContent = 'Удалить голос';
    remove.addEventListener('click', () => deleteVoice(voice, remove));
    row.append(name, remove);
    root.append(row);
  });
}

async function loadCustomVoices() {
  const response = await fetch('/api/voices');
  if (!response.ok) return;
  customVoiceRecords = await response.json();
  renderVoiceModeration();
}

async function deleteVoice(voice, button) {
  if (!confirm(`Удалить голос «${voice.name}»? Его нельзя будет восстановить.`)) return;
  button.disabled = true;
  try {
    const response = await fetch(`/api/voices/${voice.id}`, {method: 'DELETE'});
    if (!response.ok) throw new Error(await apiError(response, 'Не удалось удалить голос'));
    await loadCustomVoices();
  } catch (error) {
    alert(error.message);
    button.disabled = false;
  }
}

async function initModeration() {
  const key = new URLSearchParams(location.hash.slice(1)).get('moderation');
  if (key) {
    history.replaceState(null, '', `${location.pathname}${location.search}`);
    await fetch('/api/moderation/enable', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({key})
    });
  }
  const response = await fetch('/api/moderation/status');
  moderationEnabled = response.ok && (await response.json()).enabled === true;
}

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
  recordingSeconds = seconds;
  preview.src = URL.createObjectURL(recordingBlob); preview.hidden = false;
  recordButton.disabled = false; stopButton.disabled = true;
  recordingStatus.textContent = seconds > 12 ? `Записано ${seconds.toFixed(1)} с — перезапишите короче, нужно до 12 с` : `Записано: ${seconds.toFixed(1)} с`;
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
  if (recordingBlob && !document.querySelector('#reference-file').files.length && recordingSeconds > 12) {
    status.textContent = 'Запишите референс короче: от 5 до 12 секунд'; return;
  }
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

initModeration().then(loadCustomVoices);
