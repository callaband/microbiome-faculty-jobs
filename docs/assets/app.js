// Main page: filters, map and results list.
(async () => {
  const { esc, fmt, relative, isNew, place, domainColor, domainLabel, priorityBadge } = MFJ;
  const { jobs, meta } = await MFJ.load();
  MFJ.initTheme(document.getElementById("theme"));

  const RANKS = [
    ["assistant", "Assistant professor"], ["associate", "Associate professor"], ["full", "Full professor"],
    ["open", "Open rank"], ["lecturer", "Lecturer / Reader"], ["investigator", "Investigator / Group leader"],
    ["unspecified", "Rank not stated"],
  ];
  const TENURE = [
    ["tenure-track", "Tenure-track"], ["tenured", "Tenured"], ["permanent", "Permanent / continuing (intl.)"],
    ["non-tenure-track", "Non-tenure-track"], ["unspecified", "Not stated"],
  ];
  const INST = [
    ["r1", "R1 (very high research)"], ["r2", "R2 (high research)"], ["doctoral", "Doctoral/professional"],
    ["masters", "PUI – master's"], ["baccalaureate", "PUI – baccalaureate"], ["medical", "Medical school/center"],
    ["special", "Other special-focus"], ["associate", "Community/two-year college"], ["ivy", "Ivy League"],
    ["hbcu", "HBCU"], ["womens", "Women's/historically women's"], ["tribal", "Tribal college"],
    ["landgrant", "Land-grant"], ["med_school", "Has a medical school"], ["vet_school", "Has a veterinary school"], ["institute", "Research institute/hospital"],
    ["international", "Outside the US"], ["unknown", "Type not identified"],
  ];
  const FOCUS = [
    ["research", "Research-heavy (≥60% research)"], ["balanced", "Balanced research/teaching"],
    ["teaching", "Teaching-heavy (≥60% teaching)"], ["other", "Mostly extension/clinical"], ["unstated", "Effort % not stated"],
  ];
  const DOMAINS = Object.keys(meta.domains || {});

  // ------------------------------------------------------------------ state <-> URL
  const state = { q: "", dom: new Set(), rank: new Set(), ten: new Set(), inst: new Set(), focus: new Set(), region: "", country: "", posted: "", hideLow: false, closed: false, sort: "newest" };
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    state.q = p.get("q") || "";
    state.dom = new Set((p.get("dom") || "").split(",").filter(Boolean));
    state.rank = new Set((p.get("rank") || "").split(",").filter(Boolean));
    state.ten = new Set((p.get("ten") || "").split(",").filter(Boolean));
    state.inst = new Set((p.get("inst") || "").split(",").filter(Boolean));
    state.focus = new Set((p.get("focus") || "").split(",").filter(Boolean));
    state.region = p.get("region") || "";
    state.country = p.get("country") || "";
    state.posted = p.get("posted") || "";
    state.hideLow = p.get("hidelow") === "1";
    state.closed = p.get("closed") === "1";
    state.sort = p.get("sort") || "newest";
  }
  function writeHash() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.dom.size) p.set("dom", [...state.dom].join(","));
    if (state.rank.size) p.set("rank", [...state.rank].join(","));
    if (state.ten.size) p.set("ten", [...state.ten].join(","));
    if (state.inst.size) p.set("inst", [...state.inst].join(","));
    if (state.focus.size) p.set("focus", [...state.focus].join(","));
    if (state.region) p.set("region", state.region);
    if (state.country) p.set("country", state.country);
    if (state.posted) p.set("posted", state.posted);
    if (state.hideLow) p.set("hidelow", "1");
    if (state.closed) p.set("closed", "1");
    if (state.sort !== "newest") p.set("sort", state.sort);
    const h = p.toString();
    history.replaceState(null, "", h ? "#" + h : location.pathname + location.search);
  }

  // ------------------------------------------------------------------ filtering
  const haystack = j => [j.title, j.institution, place(j, true), j.summary, j.rank_label, j.tenure_label,
    j.inst_type_label, j.carnegie, j.matched_institution, j.effort_label,
    ...(j.domains || []).map(d => domainLabel(meta, d)), ...(j.microbiome_terms || [])].join(" ").toLowerCase();
  jobs.forEach(j => { j._hay = haystack(j); });

  function passes(j, skip) {
    if (!state.closed && j.status === "closed") return false;
    if (state.hideLow && j.priority === "low") return false;
    if (state.q) {
      const words = state.q.toLowerCase().split(/\s+/).filter(Boolean);
      if (!words.every(w => j._hay.includes(w))) return false;
    }
    if (skip !== "dom" && state.dom.size && !(j.domains || []).some(d => state.dom.has(d))) return false;
    if (skip !== "rank" && state.rank.size && !(j.ranks || []).some(r => state.rank.has(r))) return false;
    if (skip !== "ten" && state.ten.size && !(j.tenure || []).some(t => state.ten.has(t))) return false;
    if (skip !== "inst" && state.inst.size && !(j.inst_types || ["unknown"]).some(t => state.inst.has(t))) return false;
    if (skip !== "focus" && state.focus.size && !state.focus.has(j.effort_focus || "unstated")) return false;
    if (skip !== "region" && state.region && (j.location.world_region || "Other") !== state.region) return false;
    if (skip !== "region" && state.country && j.location.country !== state.country) return false;
    if (state.posted) {
      const n = MFJ.daysFrom(j.first_seen);
      if (n === null || -n > +state.posted) return false;
    }
    return true;
  }

  const SORTS = {
    newest: (a, b) => (b.first_seen || "").localeCompare(a.first_seen || "") || (b.date_posted || "").localeCompare(a.date_posted || ""),
    review: (a, b) => (a.review_date || "9999").localeCompare(b.review_date || "9999"),
    deadline: (a, b) => (a.deadline || "9999").localeCompare(b.deadline || "9999"),
    institution: (a, b) => (a.institution || "").localeCompare(b.institution || ""),
  };
  // Low-priority (past review date) and closed postings always sink below the rest.
  const rankOf = j => (j.status === "closed" ? 2 : j.priority === "low" ? 1 : 0);

  // ------------------------------------------------------------------ filter UI
  const $ = id => document.getElementById(id);
  function count(skip, pred) { return jobs.filter(j => passes(j, skip) && pred(j)).length; }

  function renderFilters(syncInputs = true) {
    const ds = (document.activeElement && document.activeElement.dataset) || {};
    const focused = ds.dom || ds.rank || ds.ten || ds.inst || ds.focus;
    const focusAttr = document.activeElement && ["dom", "rank", "ten", "inst", "focus"].find(k => document.activeElement.dataset[k]);
    $("f-dom").innerHTML = DOMAINS.map(d => {
      const n = count("dom", j => (j.domains || []).includes(d));
      return `<button type="button" class="chip" data-dom="${d}" aria-pressed="${state.dom.has(d)}" style="--c:${domainColor(meta, d)}">
        <span class="dot"></span>${esc(domainLabel(meta, d))} <span class="n">${n}</span></button>`;
    }).join("");
    $("f-rank").innerHTML = RANKS.map(([k, label]) =>
      `<label><input type="checkbox" data-rank="${k}" ${state.rank.has(k) ? "checked" : ""}> ${label}
       <span class="n">${count("rank", j => (j.ranks || []).includes(k))}</span></label>`).join("");
    $("f-ten").innerHTML = TENURE.map(([k, label]) =>
      `<label><input type="checkbox" data-ten="${k}" ${state.ten.has(k) ? "checked" : ""}> ${label}
       <span class="n">${count("ten", j => (j.tenure || []).includes(k))}</span></label>`).join("");

    $("f-inst").innerHTML = INST.map(([k, label]) => {
      const n = count("inst", j => (j.inst_types || ["unknown"]).includes(k));
      return n || state.inst.has(k) ? `<label><input type="checkbox" data-inst="${k}" ${state.inst.has(k) ? "checked" : ""}> ${label}
       <span class="n">${n}</span></label>` : "";
    }).join("") || `<span class="n" style="font-size:13px;color:var(--ink-3)">Available after the first run</span>`;
    $("f-focus").innerHTML = FOCUS.map(([k, label]) =>
      `<label><input type="checkbox" data-focus="${k}" ${state.focus.has(k) ? "checked" : ""}> ${label}
       <span class="n">${count("focus", j => (j.effort_focus || "unstated") === k)}</span></label>`).join("");

    const pool = jobs.filter(j => passes(j, "region"));
    const regions = [...new Set(jobs.map(j => j.location.world_region || "Other"))].sort();
    $("f-region").innerHTML = `<option value="">All regions</option>` + regions.map(r =>
      `<option value="${esc(r)}" ${state.region === r ? "selected" : ""}>${esc(r)} (${pool.filter(j => (j.location.world_region || "Other") === r).length})</option>`).join("");
    const countries = [...new Set(jobs.filter(j => !state.region || (j.location.world_region || "Other") === state.region)
      .map(j => j.location.country).filter(Boolean))].sort();
    $("f-country").innerHTML = `<option value="">All countries</option>` + countries.map(c =>
      `<option value="${esc(c)}" ${state.country === c ? "selected" : ""}>${esc(c)}</option>`).join("");
    $("f-posted").value = state.posted;
    $("f-hidelow").checked = state.hideLow;
    $("f-closed").checked = state.closed;
    if (syncInputs) $("q").value = state.q;
    $("sort").value = state.sort;
    if (focused && focusAttr) {
      const el = document.querySelector(`[data-${focusAttr}="${focused}"]`);
      if (el) el.focus();
    }
  }

  document.addEventListener("click", e => {
    const chip = e.target.closest("[data-dom]");
    if (chip) { toggle(state.dom, chip.dataset.dom); update(); }
  });
  document.addEventListener("change", e => {
    const t = e.target;
    if (t.dataset.rank) toggle(state.rank, t.dataset.rank);
    else if (t.dataset.ten) toggle(state.ten, t.dataset.ten);
    else if (t.dataset.inst) toggle(state.inst, t.dataset.inst);
    else if (t.dataset.focus) toggle(state.focus, t.dataset.focus);
    else if (t.id === "f-region") { state.region = t.value; state.country = ""; }
    else if (t.id === "f-country") state.country = t.value;
    else if (t.id === "f-posted") state.posted = t.value;
    else if (t.id === "f-hidelow") state.hideLow = t.checked;
    else if (t.id === "f-closed") state.closed = t.checked;
    else if (t.id === "sort") state.sort = t.value;
    else return;
    update();
  });
  let typing;
  $("q").addEventListener("input", e => { clearTimeout(typing); typing = setTimeout(() => { state.q = e.target.value.trim(); update(false); }, 180); });
  $("reset").addEventListener("click", () => { location.hash = ""; readHash(); update(); });
  $("filters-toggle").addEventListener("click", () => {
    const f = $("filters"); f.classList.toggle("open");
    $("filters-toggle").setAttribute("aria-expanded", f.classList.contains("open"));
  });
  function toggle(set, v) { set.has(v) ? set.delete(v) : set.add(v); }

  // ------------------------------------------------------------------ map
  let map, cluster, tileLayer, fitted = false;
  function initMap() {
    if (!window.L) { $("map").innerHTML = `<p class="empty">Map could not load.</p>`; return; }
    map = L.map("map", { worldCopyJump: true, scrollWheelZoom: false, minZoom: 1 }).setView([25, 5], 2);
    tileLayer = MFJ.tiles(L).addTo(map);
    cluster = L.markerClusterGroup ? L.markerClusterGroup({ showCoverageOnHover: false, maxClusterRadius: 40 }) : L.layerGroup();
    map.addLayer(cluster);
    map.on("focus", () => map.scrollWheelZoom.enable());
    map.on("blur", () => map.scrollWheelZoom.disable());
    document.addEventListener("themechange", () => { map.removeLayer(tileLayer); tileLayer = MFJ.tiles(L).addTo(map); });
  }
  function renderMap(list) {
    if (!map) return;
    cluster.clearLayers();
    const pts = [];
    for (const j of list) {
      const l = j.location;
      if (l.lat == null) continue;
      const m = L.marker([l.lat, l.lon], { icon: MFJ.pinIcon(L, domainColor(meta, j.domains[0]), j.priority === "low" || j.status === "closed"), title: j.title });
      m.bindPopup(`<a class="pop-title" href="job.html?id=${j.id}" target="_blank" rel="noopener">${esc(j.title)}</a>
        <span class="pop-sub">${esc(j.institution)}<br>${esc(place(j))}${j.review_date ? `<br>Review: ${fmt(j.review_date)}` : ""}</span>`);
      cluster.addLayer(m);
      pts.push([l.lat, l.lon]);
    }
    if (!fitted && pts.length) { map.fitBounds(pts, { padding: [30, 30], maxZoom: 5 }); fitted = true; }
    const unmapped = list.length - pts.length;
    $("map-note").textContent = unmapped ? `${unmapped} not on the map (location unknown)` : "";
  }
  function renderLegend() {
    $("legend").innerHTML = DOMAINS.map(d => `<span><i style="background:${domainColor(meta, d)}"></i>${esc(domainLabel(meta, d))}</span>`).join("")
      + `<span id="map-note" style="margin-left:auto"></span>`;
  }

  // ------------------------------------------------------------------ results
  function card(j) {
    const tags = [
      `<span class="tag">${esc(j.rank_label)}</span>`,
      `<span class="tag ${/tenure-track|tenured|permanent/i.test(j.tenure_label) ? "tt" : ""}">${esc(j.tenure_label)}</span>`,
      j.inst_type_label ? `<span class="tag inst" title="${esc(j.carnegie || "")}">${esc(j.inst_type_label)}</span>` : "",
      j.effort_label ? `<span class="tag eff">${esc(j.effort_label)}</span>`
        : `<span class="tag muted">Effort % not stated</span>`,
      j.teaching_load ? `<span class="tag eff">Teaching load ${esc(j.teaching_load)}</span>` : "",
      ...(j.domains || []).map(d => `<span class="tag dom" style="--c:${domainColor(meta, d)}"><i></i>${esc(domainLabel(meta, d))}</span>`),
    ].join("");
    const dates = [
      j.review_date ? `Review <b>${fmt(j.review_date)}</b>` : "",
      j.deadline ? `Deadline <b>${fmt(j.deadline)}</b>` : (j.until_filled ? "Open until filled" : ""),
      `<span title="First seen ${fmt(j.first_seen)}">Posted ${fmt(j.date_posted || j.first_seen)}</span>`,
    ].filter(Boolean).join("<br>");
    const cls = ["job", j.priority === "low" ? "is-low" : "", j.status === "closed" ? "is-closed" : ""].join(" ");
    return `<article class="${cls}" style="--c:${domainColor(meta, (j.domains || [])[0])}">
      <div>
        <h3 class="job-title">${isNew(j) && j.status !== "closed" ? `<span class="badge new">New</span>` : ""}${priorityBadge(j)}<a href="job.html?id=${j.id}" target="_blank" rel="noopener">${esc(j.title)}</a></h3>
        <div class="job-where">${esc(j.institution)} · ${esc(place(j))}</div>
      </div>
      <div class="job-dates">${dates}</div>
      <div class="job-tags">${tags}</div>
    </article>`;
  }

  function update(syncInputs = true) {
    writeHash();
    const list = jobs.filter(j => passes(j)).sort((a, b) => rankOf(a) - rankOf(b) || SORTS[state.sort](a, b));
    $("count").textContent = `${list.length} of ${jobs.filter(j => j.status === "open").length} open`;
    if (!jobs.length) {
      $("results").innerHTML = `<div class="empty"><h3>No positions collected yet</h3>
        The daily collector hasn't run yet. Once the GitHub Action runs, matching positions will appear here.</div>`;
    } else if (!list.length) {
      $("results").innerHTML = `<div class="empty"><h3>No positions match these filters</h3>Try removing a filter or <a href="#" id="clear2">clear all filters</a>.</div>`;
      $("clear2").addEventListener("click", ev => { ev.preventDefault(); $("reset").click(); });
    } else {
      $("results").innerHTML = list.map(card).join("");
    }
    renderFilters(syncInputs);
    renderMap(list);
  }

  // ------------------------------------------------------------------ header & footer
  function renderMeta() {
    const open = jobs.filter(j => j.status === "open");
    $("s-open").textContent = open.length;
    $("s-new").textContent = open.filter(isNew).length;
    $("s-soon").textContent = open.filter(j => j.priority === "soon").length;
    $("s-countries").textContent = new Set(open.map(j => j.location.country).filter(Boolean)).size;
    $("updated").textContent = meta.generated_at
      ? new Date(meta.generated_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "not yet";
    $("sources").innerHTML = (meta.sources || []).map(s => `<tr>
        <td><span class="${s.ok ? "ok" : "bad"}">${s.ok ? "●" : "○"}</span> ${esc(s.name)}${s.ok ? "" : `<br><small class="bad">${esc(s.error || "failed")}</small>`}</td>
        <td>${s.ok ? `${s.listed} listed · ${s.new_matches} new` : "skipped"}</td></tr>`).join("")
      || `<tr><td>Waiting for the first run.</td><td></td></tr>`;
    const repo = MFJ.repoUrl(meta);
    if (repo) {
      document.querySelectorAll("[data-repo]").forEach(a => { a.href = repo + a.dataset.repo; });
    }
  }

  readHash();
  initMap();
  renderLegend();
  renderMeta();
  update();
  window.addEventListener("hashchange", () => { readHash(); update(); });
})();
