const jobs = document.querySelector('#jobs');
const worker = document.querySelector('#worker');
const form = document.querySelector('#form');

const date = value => new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'short', timeStyle: 'short'
}).format(new Date(value));

function card(job) {
  const el = document.createElement('article');
  el.className = 'job';
  el.innerHTML = `<div class="meta"><b class="badge ${job.status}">${job.status}</b><span>${job.engine === 'f5' ? 'F5 Russian v2' : 'Silero v5.5'}</span><time>${date(job.created_at)}</time></div><p class="text"></p>${job.accented_text ? '<p class="accented"></p>' : ''}${job.audio_url ? `<audio controls preload="none" src="${job.audio_url}"></audio>` : ''}${job.error ? '<p class="failed"></p>' : ''}`;
  el.querySelector('.text').textContent = job.text;
  if (job.accented_text) el.querySelector('.accented').textContent = 'Ударения: ' + job.accented_text;
  if (job.error) el.querySelector('.failed').textContent = job.error;
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
  button.disabled = true;
  try {
    const response = await fetch('/api/jobs', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        text: document.querySelector('#text').value,
        engine: document.querySelector('#engine').value,
        accent_mode: document.querySelector('#accent').value
      })
    });
    if (!response.ok) throw new Error((await response.json()).detail);
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
