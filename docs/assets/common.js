// Shared helpers for index.html and job.html
window.MFJ = (() => {
  const DATA = "data/";

  async function load() {
    const [jobs, meta] = await Promise.all([
      fetch(DATA + "jobs.json", { cache: "no-cache" }).then(r => (r.ok ? r.json() : [])).catch(() => []),
      fetch(DATA + "meta.json", { cache: "no-cache" }).then(r => (r.ok ? r.json() : {})).catch(() => ({})),
    ]);
    return { jobs, meta };
  }

  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Dates in the data are plain YYYY-MM-DD (no time zone): parse as local dates.
  const toDate = iso => (iso ? new Date(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) : null);
  const fmt = iso => (iso ? toDate(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "");
  const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
  const daysFrom = iso => (iso ? Math.round((toDate(iso) - today()) / 86400000) : null);
  const isNew = job => job.first_seen && daysFrom(job.first_seen) >= -7;

  function relative(iso) {
    const n = daysFrom(iso);
    if (n === null) return "";
    if (n === 0) return "today";
    if (n === 1) return "tomorrow";
    if (n === -1) return "yesterday";
    return n > 0 ? `in ${n} days` : `${-n} days ago`;
  }

  function place(job, withRegion = false) {
    const l = job.location || {};
    const parts = [l.city, withRegion || l.country_code === "US" || l.country_code === "CA" ? l.region : null, l.country_code === "US" ? null : l.country];
    return parts.filter(Boolean).join(", ") || l.country || "Location not stated";
  }

  function domainColor(meta, key) {
    return (meta.domains && meta.domains[key] && meta.domains[key].color) || "#64748b";
  }
  function domainLabel(meta, key) {
    return (meta.domains && meta.domains[key] && meta.domains[key].label) || key;
  }

  function priorityBadge(job) {
    if (job.status === "closed") return `<span class="badge closed">Closed</span>`;
    if (job.priority === "low") return `<span class="badge low" title="${esc(job.priority_reason)}">Low priority</span>`;
    if (job.priority === "soon") return `<span class="badge soon" title="${esc(job.priority_reason)}">Review soon</span>`;
    return "";
  }

  // Light/dark toggle (remembers the choice in this browser only).
  function initTheme(btn) {
    const root = document.documentElement;
    let saved = null;
    try { saved = localStorage.getItem("mfj-theme"); } catch (e) { /* storage blocked */ }
    if (saved) root.dataset.theme = saved;
    const label = () => {
      const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      btn.textContent = dark ? "Light mode" : "Dark mode";
      return dark;
    };
    label();
    btn.addEventListener("click", () => {
      root.dataset.theme = label() ? "light" : "dark";
      try { localStorage.setItem("mfj-theme", root.dataset.theme); } catch (e) { /* ignore */ }
      label();
      document.dispatchEvent(new CustomEvent("themechange"));
    });
  }

  function isDark() {
    const t = document.documentElement.dataset.theme;
    return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  }

  // OpenStreetMap's standard tiles: no API key; attribution required.
  function tiles(L) {
    return L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      className: isDark() ? "tiles-dark" : "",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    });
  }

  function pinIcon(L, color, low) {
    return L.divIcon({ className: "", html: `<div class="pin${low ? " low" : ""}" style="background:${color}"></div>`, iconSize: [14, 14], iconAnchor: [7, 7], popupAnchor: [0, -8] });
  }

  function repoUrl(meta) { return meta.repo ? `https://github.com/${meta.repo}` : null; }

  return { load, esc, fmt, toDate, daysFrom, relative, isNew, place, domainColor, domainLabel, priorityBadge, initTheme, tiles, pinIcon, repoUrl };
})();
