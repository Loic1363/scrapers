const REFRESH_MS = 15000;

const state = {
  sellers: [],
  filters: { site: "all", model: "all", status: "all" },
};

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function formatDate(iso) {
  if (!iso) return "?";
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function uniqueSites(sellers) {
  return [...new Set(sellers.map((s) => s.site))].sort();
}

function uniqueModels(sellers) {
  const models = new Set();
  sellers.forEach((s) => s.listings.forEach((l) => {
    if (l.matched_model) models.add(l.matched_model);
  }));
  return [...models].sort();
}

function buildFilterList(container, items, filterKey, allLabel) {
  container.innerHTML = "";
  const allLi = document.createElement("li");
  allLi.className = "filter-item" + (state.filters[filterKey] === "all" ? " active" : "");
  allLi.dataset.filter = filterKey;
  allLi.dataset.value = "all";
  allLi.textContent = allLabel;
  container.appendChild(allLi);

  items.forEach((value) => {
    const li = document.createElement("li");
    li.className = "filter-item" + (state.filters[filterKey] === value ? " active" : "");
    li.dataset.filter = filterKey;
    li.dataset.value = value;
    li.textContent = value;
    container.appendChild(li);
  });
}

function renderFilters() {
  buildFilterList(document.getElementById("site-filters"), uniqueSites(state.sellers), "site", "Toutes");
  buildFilterList(document.getElementById("model-filters"), uniqueModels(state.sellers), "model", "Tous");
}

function renderStats() {
  const total = state.sellers.length;
  const suspects = state.sellers.filter((s) => s.is_suspect).length;
  const crossSite = state.sellers.filter((s) => s.is_cross_site).length;
  const models = uniqueModels(state.sellers).length;

  document.getElementById("stats-row").innerHTML = `
    <div class="stat">
      <span class="stat-label">Vendeurs suivis</span>
      <span class="stat-value">${total}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Suspects (2+ annonces)</span>
      <span class="stat-value alarm">${suspects}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Multi-plateformes</span>
      <span class="stat-value cross">${crossSite}</span>
    </div>
    <div class="stat">
      <span class="stat-label">Modèles ciblés</span>
      <span class="stat-value">${models}</span>
    </div>
  `;
}

function matchesFilters(seller) {
  const { site, model, status } = state.filters;
  if (site !== "all" && seller.site !== site) return false;
  if (model !== "all" && !seller.listings.some((l) => l.matched_model === model)) return false;
  if (status === "suspect" && !seller.is_suspect) return false;
  if (status === "cross-site" && !seller.is_cross_site) return false;
  return true;
}

function renderCard(seller) {
  const badges = [];
  if (seller.is_suspect) badges.push(`<span class="badge badge-suspect">Suspect</span>`);
  if (seller.is_cross_site) {
    badges.push(`<span class="badge badge-cross">${seller.cross_site_platforms.join(" + ")}</span>`);
  }
  if (seller.selling_pattern && seller.selling_pattern !== "insuffisant") {
    badges.push(`<span class="badge badge-pattern">vente ${seller.selling_pattern}</span>`);
  }

  const listingsHtml = seller.listings.map((l) => `
    <div class="listing">
      <div class="listing-title">${escapeHtml(l.title || "Sans titre")}</div>
      <div class="listing-row">
        <span class="listing-price">${escapeHtml(l.price || "?")}</span>
        ${l.location ? `<span>${escapeHtml(l.location)}</span>` : ""}
        <span>${escapeHtml(l.matched_model || "?")}</span>
        <span class="listing-date">${formatDate(l.posted_at)}</span>
      </div>
      <a class="listing-link" href="${l.url}" target="_blank" rel="noopener noreferrer">${escapeHtml(l.url || "")}</a>
    </div>
  `).join("");

  return `
    <div class="card">
      <div class="card-header">
        <div>
          <div class="seller-name">${escapeHtml(seller.seller_name || "Inconnu")}</div>
          <div class="seller-meta">${escapeHtml(seller.site)} · id ${escapeHtml(seller.seller_id)}</div>
        </div>
        <div class="badges">${badges.join("")}</div>
      </div>
      <div class="listings">${listingsHtml}</div>
      <div class="card-footer">
        <span>${seller.listings.length} annonce${seller.listings.length > 1 ? "s" : ""}</span>
        <span class="mono">détecté ${formatDate(seller.first_seen)}</span>
      </div>
    </div>
  `;
}

function renderGrid() {
  const grid = document.getElementById("suspects-grid");
  const filtered = state.sellers
    .filter(matchesFilters)
    .sort((a, b) => b.listings.length - a.listings.length);

  if (filtered.length === 0) {
    grid.innerHTML = `<div class="empty">Aucun vendeur ne correspond aux filtres actuels.</div>`;
    return;
  }
  grid.innerHTML = filtered.map(renderCard).join("");
}

function attachFilterHandlers() {
  document.querySelectorAll(".filter-list").forEach((list) => {
    list.addEventListener("click", (e) => {
      const item = e.target.closest(".filter-item");
      if (!item) return;
      const { filter, value } = item.dataset;
      state.filters[filter] = value;
      renderFilters();
      renderGrid();
    });
  });
}

async function refresh() {
  try {
    const res = await fetch("/api/suspects");
    const data = await res.json();
    state.sellers = data.sellers || [];
    renderFilters();
    renderStats();
    renderGrid();
    document.getElementById("refresh-status").textContent =
      `Actualisé à ${new Date().toLocaleTimeString("fr-FR")}`;
  } catch (err) {
    document.getElementById("refresh-status").textContent = "Erreur de chargement";
  }
}

attachFilterHandlers();
refresh();
setInterval(refresh, REFRESH_MS);
