const id = location.pathname.split('/').pop();
const result = document.querySelector('#result');
const missing = document.querySelector('#missing');
const meta = document.querySelector('#meta');
const voiceNames = {aidar: 'Айдар', baya: 'Бая', kseniya: 'Ксения', eugene: 'Евгений', xenia: 'Ксения'};

async function copyLink(button) {
  try {
    await navigator.clipboard.writeText(location.href);
    button.textContent = 'Ссылка скопирована';
    setTimeout(() => { button.textContent = 'Копировать ссылку'; }, 1800);
  } catch {
    window.prompt('Скопируйте ссылку:', location.href);
  }
}

fetch(`/api/jobs/${encodeURIComponent(id)}`).then(async response => {
  if (!response.ok) throw new Error();
  return response.json();
}).then(job => {
  if (job.status !== 'complete' || !job.audio_url) throw new Error();
  document.title = `Аудиоистория · ${job.engine === 'f5' ? 'F5 Russian v2' : 'Silero'} · Voice`;
  meta.textContent = `${job.engine === 'f5' ? 'F5 Russian v2' : 'Silero v5.5'} · ${voiceNames[job.voice] || job.voice || 'Ксения'} · ${Number(job.duration_seconds).toFixed(1)} с · ${Number(job.speed ?? 1).toFixed(1)}×`;
  document.querySelector('#audio').src = job.audio_url;
  document.querySelector('#text').textContent = job.text;
  document.querySelector('#fork').href = `/book?from=${encodeURIComponent(job.id)}`;
  document.querySelector('#copy').onclick = event => copyLink(event.currentTarget);
  result.hidden = false;
}).catch(() => {
  meta.textContent = 'Результат не найден';
  missing.hidden = false;
});
