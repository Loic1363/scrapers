const consoleEl = document.getElementById("console");
const alarmBadge = document.getElementById("alarm-badge");
const runBadge = document.getElementById("run-badge");
const timerEl = document.getElementById("timer");
const exportBtn = document.getElementById("export-btn");

let logCursor = 0;
let nextRunAt = null;

function isScrolledToBottom() {
  return consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 40;
}

async function pollLogs() {
  const stickToBottom = isScrolledToBottom();
  const res = await fetch(`/api/logs?since=${logCursor}`);
  const data = await res.json();
  if (data.lines.length) {
    consoleEl.textContent += (consoleEl.textContent ? "\n" : "") + data.lines.join("\n");
    logCursor = data.total;
    if (stickToBottom) {
      consoleEl.scrollTop = consoleEl.scrollHeight;
    }
  }
}

async function pollState() {
  const res = await fetch("/api/state");
  const state = await res.json();

  if (state.alarm) {
    alarmBadge.textContent = `Alerte : ${state.alarm_count} annonce(s) suspecte(s)`;
    alarmBadge.className = "badge badge-alarm";
  } else {
    alarmBadge.textContent = "Aucune alerte";
    alarmBadge.className = "badge badge-ok";
  }

  if (state.running) {
    runBadge.textContent = state.current_stage ? `En cours : ${state.current_stage}` : "Recherche en cours...";
    runBadge.className = "badge badge-running";
  } else {
    runBadge.textContent = "En attente";
    runBadge.className = "badge badge-idle";
  }

  nextRunAt = state.next_run_at ? new Date(state.next_run_at) : null;
}

function tickTimer() {
  if (!nextRunAt) {
    timerEl.textContent = "Prochain passage : --:--:--";
    return;
  }
  const diffMs = nextRunAt.getTime() - Date.now();
  if (diffMs <= 0) {
    timerEl.textContent = "Prochain passage : en cours...";
    return;
  }
  const totalSeconds = Math.floor(diffMs / 1000);
  const h = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const s = String(totalSeconds % 60).padStart(2, "0");
  timerEl.textContent = `Prochain passage : ${h}:${m}:${s}`;
}

exportBtn.addEventListener("click", () => {
  window.location.href = "/api/export";
});

pollLogs();
pollState();
setInterval(pollLogs, 2000);
setInterval(pollState, 3000);
setInterval(tickTimer, 1000);
