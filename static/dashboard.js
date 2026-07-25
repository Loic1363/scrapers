const consoleEl = document.getElementById("console");
const alarmBadge = document.getElementById("alarm-badge");
const runBadge = document.getElementById("run-badge");
const timerEl = document.getElementById("timer");
const exportBtn = document.getElementById("export-btn");
const consolePanel = document.getElementById("console-panel");
const logsToggleBtn = document.getElementById("logs-toggle-btn");

let logCursor = 0;
let nextRunAt = null;
let backendAvailable = true;

function disableBackendUI() {
  if (!backendAvailable) return;
  backendAvailable = false;
  document.querySelector(".status-bar").style.display = "none";
  consolePanel.classList.remove("open");
  consolePanel.style.display = "none";
  exportBtn.style.display = "none";
}

function isScrolledToBottom() {
  return consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 40;
}

function escapeHtml(str) {
  return str.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function renderLine(line) {
  if (line.includes("ALARM: ")) {
    const escaped = escapeHtml(line.replace("ALARM: ", ""));
    return `<span class="log-alarm">${escaped}</span>`;
  }
  const escaped = escapeHtml(line);
  return escaped.replace(/(\|\s*)(INFO|SUCCESS|WARNING|ERROR)(\s*\|)/, (_match, pre, word, post) => {
    return `${pre}<span class="log-${word.toLowerCase()}">${word}</span>${post}`;
  });
}

async function pollLogs() {
  if (!backendAvailable) return;
  try {
    const stickToBottom = isScrolledToBottom();
    const res = await fetch(`/api/logs?since=${logCursor}`);
    if (!res.ok) throw new Error("logs unavailable");
    const data = await res.json();
    if (data.lines.length) {
      const html = data.lines.map(renderLine).join("\n");
      consoleEl.insertAdjacentHTML("beforeend", (consoleEl.textContent ? "\n" : "") + html);
      logCursor = data.total;
      if (stickToBottom) consoleEl.scrollTop = consoleEl.scrollHeight;
    }
  } catch (e) {
    disableBackendUI();
  }
}

async function pollState() {
  if (!backendAvailable) return;
  try {
    const res = await fetch("/api/state");
    if (!res.ok) throw new Error("state unavailable");
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
  } catch (e) {
    disableBackendUI();
  }
}

function tickTimer() {
  if (!nextRunAt) { timerEl.textContent = "Prochain passage : --:--:--"; return; }
  const diffMs = nextRunAt.getTime() - Date.now();
  if (diffMs <= 0) { timerEl.textContent = "Prochain passage : en cours..."; return; }
  const totalSeconds = Math.floor(diffMs / 1000);
  const h = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const s = String(totalSeconds % 60).padStart(2, "0");
  timerEl.textContent = `Prochain passage : ${h}:${m}:${s}`;
}

exportBtn.addEventListener("click", () => { window.location.href = "/api/export"; });
logsToggleBtn.addEventListener("click", () => {
  const open = consolePanel.classList.toggle("open");
  logsToggleBtn.textContent = open ? "Masquer les logs" : "Afficher les logs";
});

pollLogs(); pollState();
setInterval(pollLogs, 2000);
setInterval(pollState, 3000);
setInterval(tickTimer, 1000);

let sellers = [];
let filters = { status: "all", site: "all", model: "all", search: "" };
let selectedId = null;
let treated = {};
let view = "table";
let map = null;
let markersLayer = null;

const statusDefs = [
  { key: "all", label: "Tous" },
  { key: "normal", label: "Normal" },
  { key: "suspect", label: "Suspects" },
  { key: "multi-site", label: "Multi-sites" },
];

const statusMeta = {
  "normal": { label: "Normal", cls: "status-normal" },
  "suspect": { label: "Suspect", cls: "status-suspect" },
  "multi-site": { label: "Multi-sites", cls: "status-multi-site" },
};

function renderPills() {
  const container = document.getElementById("status-pills");
  container.innerHTML = "";
  statusDefs.forEach(d => {
    const btn = document.createElement("button");
    btn.className = "pill" + (filters.status === d.key ? " active" : "");
    btn.textContent = d.label;
    btn.addEventListener("click", () => { filters.status = d.key; renderPills(); renderTable(); });
    container.appendChild(btn);
  });
}

function fmtDate(iso) {
  return new Date(iso).toLocaleDateString("fr-FR");
}

function flatListings() {
  const q = filters.search.trim().toLowerCase();
  const rows = [];
  sellers.forEach(s => {
    if (filters.status !== "all" && s.status !== filters.status) return;
    s.listings.forEach(l => {
      if (filters.site !== "all" && l.site !== filters.site) return;
      if (filters.model !== "all" && l.model !== filters.model) return;
      if (q && !(l.title.toLowerCase().includes(q) || s.name.toLowerCase().includes(q) || l.model.toLowerCase().includes(q))) return;
      rows.push({ seller: s, listing: l });
    });
  });
  return rows.sort((a, b) => new Date(b.listing.postedAt) - new Date(a.listing.postedAt));
}

function renderTable() {
  const rows = flatListings();
  const container = document.getElementById("table-rows");
  const empty = document.getElementById("empty-state");
  container.innerHTML = "";
  empty.style.display = rows.length ? "none" : "block";

  rows.forEach(({ seller, listing }) => {
    const meta = statusMeta[seller.status] || statusMeta.normal;
    const row = document.createElement("div");
    row.className = "table-row";
    row.innerHTML = `
      <div>${escapeHtml(seller.name)}</div>
      <div class="cell-muted">${escapeHtml(listing.site)}</div>
      <div>${escapeHtml(listing.model)}</div>
      <div class="cell-muted">${escapeHtml(listing.title)}</div>
      <div>${listing.price} €</div>
      <div class="cell-muted">${escapeHtml(listing.city || "")}</div>
      <div class="cell-muted">${fmtDate(listing.postedAt)}</div>
      <div><span class="status-pill ${meta.cls}">${meta.label}</span></div>
    `;
    row.addEventListener("click", () => openPanel(seller.id));
    container.appendChild(row);
  });

  document.getElementById("kpi-total").textContent = sellers.reduce((n, s) => n + s.listingCount, 0);
  document.getElementById("kpi-suspects").textContent = sellers.filter(s => s.status !== "normal").length;
  document.getElementById("kpi-crosssite").textContent = sellers.filter(s => s.status === "multi-site").length;
}

function openPanel(id) {
  selectedId = id;
  const s = sellers.find(x => x.id === id);
  if (!s) return;
  const meta = statusMeta[s.status] || statusMeta.normal;

  document.getElementById("panel-avatar").textContent = s.name.slice(0, 2).toUpperCase();
  document.getElementById("panel-name").textContent = s.name;
  const statusEl = document.getElementById("panel-status");
  statusEl.textContent = meta.label;
  statusEl.className = "status-pill " + meta.cls;
  document.getElementById("panel-id").textContent = s.id;
  document.getElementById("panel-count").textContent = s.listingCount;
  document.getElementById("panel-sites").textContent = s.sitesUsed.join(", ");
  document.getElementById("panel-pattern").textContent =
    s.pattern === "échelonné" ? "Échelonné (plusieurs jours)" :
    s.pattern === "groupé" ? "Groupé (moins de 24h)" : "Insuffisant";

  const noteEl = document.getElementById("panel-note");
  if (s.status !== "normal") {
    noteEl.style.display = "block";
    noteEl.textContent = s.status === "multi-site"
      ? `Même nom de vendeur repéré sur ${s.sitesUsed.length} plateformes différentes — à vérifier manuellement.`
      : "Ce vendeur a publié plusieurs annonces correspondant aux modèles recherchés.";
  } else {
    noteEl.style.display = "none";
  }

  const historyEl = document.getElementById("panel-history");
  historyEl.innerHTML = "";
  s.listings.forEach(l => {
    const card = document.createElement("div");
    card.className = "history-card";
    card.innerHTML = `
      <div class="history-top"><span>${escapeHtml(l.site)} — ${escapeHtml(l.model)}</span><span>${l.price} €</span></div>
      <div class="history-title">${escapeHtml(l.title)}</div>
      <div class="history-meta">${escapeHtml(l.city || "")} · posté le ${fmtDate(l.postedAt)}</div>
      <a class="history-url" href="${l.url}" target="_blank">${l.url}</a>
    `;
    historyEl.appendChild(card);
  });

  const treatedBtn = document.getElementById("panel-treated-btn");
  treatedBtn.textContent = treated[s.id] ? "Marqué comme traité" : "Marquer comme traité";
  treatedBtn.onclick = () => { treated[s.id] = !treated[s.id]; treatedBtn.textContent = treated[s.id] ? "Marqué comme traité" : "Marquer comme traité"; };

  document.getElementById("panel-view-link").href = s.listings[0]?.url || "#";

  document.getElementById("overlay").classList.add("open");
  document.getElementById("detail-panel").classList.add("open");
}

function closePanel() {
  selectedId = null;
  document.getElementById("overlay").classList.remove("open");
  document.getElementById("detail-panel").classList.remove("open");
}

document.getElementById("overlay").addEventListener("click", closePanel);
document.getElementById("panel-close-btn").addEventListener("click", closePanel);
document.getElementById("search-input").addEventListener("input", (e) => { filters.search = e.target.value; renderTable(); });
document.getElementById("site-filter").addEventListener("change", (e) => { filters.site = e.target.value; renderTable(); });
document.getElementById("model-filter").addEventListener("change", (e) => { filters.model = e.target.value; renderTable(); });

function initMap() {
  if (map) return;
  map = L.map("map").setView([50.5, 4.2], 7);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
  markersLayer = L.layerGroup().addTo(map);
}

function renderMap() {
  if (!map) return;
  markersLayer.clearLayers();
  const byCity = {};
  sellers.forEach(s => s.listings.forEach(l => {
    if (!l.lat || !l.lon) return;
    if (!byCity[l.city]) byCity[l.city] = { total: 0, suspect: 0, lat: l.lat, lon: l.lon };
    byCity[l.city].total++;
    if (s.status !== "normal") byCity[l.city].suspect++;
  }));
  Object.entries(byCity).forEach(([city, d]) => {
    const ratio = d.suspect / d.total;
    const color = ratio > 0.5 ? "#d70015" : ratio > 0 ? "#ff9500" : "#0071e3";
    const radius = 8 + Math.sqrt(d.total) * 4;
    const marker = L.circleMarker([d.lat, d.lon], { radius, color: "#fff", weight: 2, fillColor: color, fillOpacity: 0.85 }).addTo(markersLayer);
    marker.bindTooltip(`<b>${city}</b><br>${d.total} annonce(s) — ${d.suspect} suspecte(s)`, { direction: "top", offset: [0, -radius] });
  });
}

const viewTableBtn = document.getElementById("view-table-btn");
const viewMapBtn = document.getElementById("view-map-btn");
viewTableBtn.addEventListener("click", () => {
  view = "table";
  viewTableBtn.classList.add("active"); viewMapBtn.classList.remove("active");
  document.getElementById("table-view").style.display = "block";
  document.getElementById("map-view").style.display = "none";
});
viewMapBtn.addEventListener("click", () => {
  view = "map";
  viewMapBtn.classList.add("active"); viewTableBtn.classList.remove("active");
  document.getElementById("table-view").style.display = "none";
  document.getElementById("map-view").style.display = "block";
  initMap();
  setTimeout(() => { map.invalidateSize(); renderMap(); }, 50);
});

async function loadSellers() {
  try {
    const res = await fetch("/api/sellers");
    if (!res.ok) throw new Error("api unavailable");
    sellers = await res.json();
  } catch (e) {
    try {
      const res = await fetch("/data/sellers.json");
      sellers = await res.json();
    } catch (e2) {
      sellers = [];
      console.error("Impossible de charger les données vendeurs", e2);
    }
  }
  renderPills();
  renderTable();
  if (map) renderMap();
}

loadSellers();
setInterval(loadSellers, 60000);
