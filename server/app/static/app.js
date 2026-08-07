const jobs = document.querySelector('#jobs');
const worker = document.querySelector('#worker');
const form = document.querySelector('#form');
const MAX_TTS_TEXT = 6000;

async function apiError(response, fallback) {
  let body;
  try { body = await response.json(); } catch { return fallback; }
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const textError = detail.find(item => item?.loc?.includes?.('text')) || detail[0];
    if (textError?.type === 'string_too_long') return `Текст слишком длинный: максимум ${MAX_TTS_TEXT.toLocaleString('ru-RU')} символов.`;
    if (typeof textError?.msg === 'string') return textError.msg;
  }
  return fallback;
}

async function copyShareLink(job, button) {
  const url = `${location.origin}/share/${job.id}`;
  try {
    await navigator.clipboard.writeText(url);
    button.textContent = 'Ссылка скопирована';
    setTimeout(() => { button.textContent = 'Поделиться'; }, 1800);
  } catch {
    window.prompt('Скопируйте ссылку:', url);
  }
}

const date = value => new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'short', timeStyle: 'short'
}).format(new Date(value));

function card(job) {
  const el = document.createElement('article');
  el.className = 'job';
  const speed = Number(job.speed ?? 1).toFixed(1);
  el.innerHTML = `<div class="meta"><b class="badge ${job.status}">${job.status}</b><span>${job.engine === 'f5' ? 'F5 Russian v2' : 'Silero v5.5'}</span><span>${speed}×</span><time>${date(job.created_at)}</time></div><p class="text"></p>${job.accented_text ? '<p class="accented"></p><button class="quiet accent-fix" type="button">Исправить ударения</button>' : ''}${job.audio_url ? `<audio controls preload="none" src="${job.audio_url}"></audio><button class="quiet share" type="button">Поделиться</button>` : ''}${job.error ? '<p class="failed"></p>' : ''}`;
  el.querySelector('.text').textContent = job.text;
  if (job.accented_text) el.querySelector('.accented').textContent = 'Ударения: ' + job.accented_text;
  if (job.error) el.querySelector('.failed').textContent = job.error;
  if (job.audio_url) el.querySelector('.share').addEventListener('click', event => copyShareLink(job, event.currentTarget));
  if (job.accented_text) el.querySelector('.accent-fix').addEventListener('click', async () => {
    const marked = window.prompt('Поставьте + непосредственно перед ударной гласной. Будет создана новая версия аудио.', job.accented_text);
    if (!marked?.trim()) return;
    const button = el.querySelector('.accent-fix');
    button.disabled = true;
    try {
      const response = await fetch('/api/jobs', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: marked.trim(), engine: job.engine, accent_mode: 'manual', speed: Number(job.speed ?? 1)})
      });
      if (!response.ok) throw new Error(await apiError(response, 'Не удалось создать новую версию'));
      await refresh();
    } catch (error) {
      alert(error.message);
      button.disabled = false;
    }
  });
  return el;
}

function audioIsPlaying() {
  return [...jobs.querySelectorAll('audio')].some(audio => !audio.paused && !audio.ended);
}

function renderJobs(list) {
  // Replacing a live <audio> element aborts its stream and stops playback.
  if (audioIsPlaying()) return;
  jobs.replaceChildren();
  if (!list.length) {
    jobs.innerHTML = '<p class="empty">Заданий пока нет.</p>';
  } else {
    list.forEach(job => jobs.append(card(job)));
  }
}

async function refresh() {
  const [jobsResponse, healthResponse] = await Promise.all([fetch('/api/jobs'), fetch('/api/health')]);
  const list = await jobsResponse.json();
  const health = await healthResponse.json();
  renderJobs(list);
  const seen = health.worker?.last_seen && Date.now() - new Date(health.worker.last_seen) < 90000;
  worker.textContent = seen ? `GPU worker онлайн · очередь: ${health.queued}` : `GPU worker офлайн · очередь: ${health.queued}`;
  worker.style.color = seen ? 'var(--accent)' : '#ffc36d';
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = form.querySelector('button');
  const text = document.querySelector('#text').value.trim();
  if (text.length > MAX_TTS_TEXT) {
    alert(`Текст слишком длинный: максимум ${MAX_TTS_TEXT.toLocaleString('ru-RU')} символов. Сократите его и попробуйте снова.`);
    return;
  }
  button.disabled = true;
  try {
    const response = await fetch('/api/jobs', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        text,
        engine: document.querySelector('#engine').value,
        accent_mode: document.querySelector('#accent').value,
        speed: Number(document.querySelector('#speed').value)
      })
    });
    if (!response.ok) throw new Error(await apiError(response, 'Не удалось поставить задание'));
    form.reset();
    await refresh();
  } catch (error) {
    alert(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector('#refresh').onclick = refresh;
refresh();
setInterval(refresh, 5000);
