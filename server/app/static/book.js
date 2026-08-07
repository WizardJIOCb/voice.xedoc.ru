const briefForm = document.querySelector('#brief-form');
const draft = document.querySelector('#draft');
const generationStatus = document.querySelector('#generation-status');
const provider = document.querySelector('#provider');
const voiceStatus = document.querySelector('#voice-status');
const audioResult = document.querySelector('#audio-result');
const accentEditor = document.querySelector('#accent-editor');
const markedText = document.querySelector('#marked-text');

const brief = () => ({
  premise: document.querySelector('#premise').value.trim(),
  genre: document.querySelector('#genre').value,
  mood: document.querySelector('#mood').value,
  hero: document.querySelector('#hero').value.trim(),
  setting: document.querySelector('#setting').value.trim(),
  length: Number(document.querySelector('#length').value)
});

briefForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = briefForm.querySelector('button');
  button.disabled = true;
  generationStatus.textContent = 'Создаю текст…';
  try {
    const response = await fetch('/api/book/generate', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(brief())
    });
    if (!response.ok) throw new Error((await response.json()).detail || 'Не удалось создать текст');
    const result = await response.json();
    draft.value = result.text;
    provider.textContent = result.provider === 'remote' ? 'Текст создан AI‑моделью' : 'Структурный черновик — отредактируйте его перед озвучкой';
    generationStatus.textContent = 'Черновик готов';
  } catch (error) {
    generationStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

async function poll(jobId) {
  const response = await fetch('/api/jobs');
  const job = (await response.json()).find(item => item.id === jobId);
  if (!job || job.status === 'queued' || job.status === 'running') {
    voiceStatus.textContent = job?.status === 'running' ? 'Озвучиваю на локальной RTX 4070 Ti…' : 'В очереди…';
    setTimeout(() => poll(jobId), 2500);
    return;
  }
  if (job.status === 'failed') {
    voiceStatus.textContent = job.error || 'Озвучивание не удалось';
    return;
  }
  voiceStatus.textContent = `Готово · ${Number(job.duration_seconds).toFixed(1)} с · ${Number(job.speed).toFixed(1)}×`;
  const audio = document.createElement('audio');
  audio.controls = true;
  audio.src = job.audio_url;
  audioResult.replaceChildren(audio);
  markedText.value = job.accented_text || job.text;
  accentEditor.hidden = false;
}

document.querySelector('#voice').addEventListener('click', async () => {
  const text = draft.value.trim();
  if (!text) { voiceStatus.textContent = 'Сначала создайте или вставьте текст новеллы'; return; }
  const button = document.querySelector('#voice');
  button.disabled = true;
  voiceStatus.textContent = 'Добавляю в очередь…';
  try {
    const response = await fetch('/api/jobs', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, engine: 'f5', accent_mode: 'auto', speed: Number(document.querySelector('#speed').value)})
    });
    if (!response.ok) throw new Error((await response.json()).detail || 'Не удалось поставить задание');
    poll((await response.json()).id);
  } catch (error) {
    voiceStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

document.querySelector('#revoice').addEventListener('click', async () => {
  const text = markedText.value.trim();
  if (!text) return;
  const button = document.querySelector('#revoice');
  button.disabled = true;
  voiceStatus.textContent = 'Добавляю исправленную версию в очередь…';
  try {
    const response = await fetch('/api/jobs', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, engine: 'f5', accent_mode: 'manual', speed: Number(document.querySelector('#speed').value)})
    });
    if (!response.ok) throw new Error((await response.json()).detail || 'Не удалось поставить задание');
    poll((await response.json()).id);
  } catch (error) {
    voiceStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
