// Detail page for one position: job.html?id=<id>
(async () => {
  const { esc, fmt, relative, isNew, place, domainColor, domainLabel, priorityBadge } = MFJ;
  MFJ.initTheme(document.getElementById("theme"));
  const id = new URLSearchParams(location.search).get("id");
  const { jobs, meta } = await MFJ.load();
  const j = jobs.find(x => x.id === id);
  const root = document.getElementById("detail");
  const back = `<div class="crumbs"><a href="./">← All positions</a></div>`;

  if (!j) {
    root.innerHTML = back + `<div class="empty"><h3>Position not found</h3>It may have closed more than six months ago and been removed from the list.</div>`;
    return;
  }
  document.title = `${j.title} · ${j.institution} · Microbiome Faculty Jobs`;

  let callout = "";
  if (j.status === "closed") {
    callout = `<div class="callout closed"><b>Closed</b> — ${esc(j.closed_reason || "no longer listed")}. Check the original posting before applying.</div>`;
  } else if (j.priority === "low") {
    callout = `<div class="callout low"><b>Low priority.</b> ${esc(j.priority_reason)}. Searches often continue after the review date, but the committee may already have a shortlist.</div>`;
  } else if (j.priority === "soon") {
    callout = `<div class="callout soon"><b>Apply soon.</b> ${esc(j.priority_reason)} (${relative(j.review_date || j.deadline)}).</div>`;
  }

  const fact = (label, value, evidence) => value
    ? `<div class="fact"><dt>${label}</dt><dd>${value}${evidence ? `<span class="ev">“${esc(evidence)}”</span>` : ""}</dd></div>` : "";
  const datePlus = iso => iso ? `${fmt(iso)} <span style="color:var(--ink-3)">(${relative(iso)})</span>` : "";
  const domainTags = (j.domains || []).map(d =>
    `<span class="tag dom" style="--c:${domainColor(meta, d)}"><i></i>${esc(domainLabel(meta, d))}</span>`).join(" ");
  const others = (j.sources || []).map(s => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a></li>`).join("");
  const repo = MFJ.repoUrl(meta);
  const report = repo ? `${repo}/issues/new?template=report-problem.yml&title=${encodeURIComponent("Problem with: " + j.title + " (" + j.id + ")")}&posting=${encodeURIComponent(location.href)}` : null;

  root.innerHTML = `${back}
    <div class="detail-head">
      <div>${isNew(j) && j.status !== "closed" ? `<span class="badge new">New</span>` : ""}${priorityBadge(j)}</div>
      <h1>${esc(j.title)}</h1>
      <div class="where">${esc(j.institution)} · ${esc(place(j, true))}</div>
    </div>
    <div class="cta-row">
      <a class="btn primary" href="${esc(j.url)}" target="_blank" rel="noopener">Open original posting ↗</a>
      ${report ? `<a class="btn" href="${report}" target="_blank" rel="noopener">Report a problem</a>` : ""}
    </div>
    ${callout}
    <div class="detail-grid">
      <dl class="panel facts">
        ${fact("Rank", esc(j.rank_label))}
        ${fact("Tenure", esc(j.tenure_label))}
        ${fact("Institution type", esc(j.inst_type_label || "Not identified") +
          (j.carnegie || j.control ? `<span class="ev" style="border:0;padding:0">${esc([j.carnegie, j.control].filter(Boolean).join(" · "))}${j.matched_institution && j.matched_institution !== j.institution ? ` — matched to ${esc(j.matched_institution)}` : ""}</span>` : ""))}
        ${fact("Effort split", j.effort_label ? esc(j.effort_label) : `<span style="color:var(--ink-3)">Not stated in the posting</span>`, j.effort_text)}
        ${fact("Teaching load", esc(j.teaching_load))}
        ${fact("Research area", domainTags)}
        ${fact("Review begins", datePlus(j.review_date), j.review_text)}
        ${fact("Application deadline", datePlus(j.deadline) || (j.until_filled ? "Open until filled" : ""), j.deadline_text && !/listed on the posting/.test(j.deadline_text) ? j.deadline_text : "")}
        ${fact("Open until filled", j.until_filled && j.deadline ? "Yes" : "")}
        ${fact("Posted", fmt(j.date_posted))}
        ${fact("First seen here", fmt(j.first_seen))}
        ${fact("Listing ends", fmt(j.listing_expires))}
        ${fact("Employment", esc(j.employment))}
        ${fact("Salary", esc(j.salary))}
      </dl>
      <div>
        <div class="panel side-card">
          <div id="jobmap"></div>
          <div class="body">
            ${esc(place(j, true))}${j.location.precision && j.location.precision !== "institution" ? `<br><small style="color:var(--ink-3)">Map pin at ${esc(j.location.precision)} level</small>` : ""}
          </div>
        </div>
        <div class="panel side-card" style="margin-top:14px"><div class="body">
          <b>Listed on</b><ul style="margin:6px 0 0;padding-left:18px">${others}</ul>
        </div></div>
      </div>
    </div>
    <section class="panel summary">
      <h2>From the posting</h2>
      <p>${esc(j.summary)}</p>
      <div class="terms">${(j.microbiome_terms || []).map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>
      <p class="note">Opening lines only, with the microbiome terms that matched. Read the full description, eligibility and application instructions on the <a href="${esc(j.url)}" target="_blank" rel="noopener">original posting</a>.</p>
    </section>`;

  const mapEl = document.getElementById("jobmap");
  if (window.L && j.location.lat != null) {
    const map = L.map(mapEl, { scrollWheelZoom: false, zoomControl: true }).setView([j.location.lat, j.location.lon], j.location.precision === "country" ? 4 : 9);
    let tl = MFJ.tiles(L).addTo(map);
    L.marker([j.location.lat, j.location.lon], { icon: MFJ.pinIcon(L, domainColor(meta, j.domains[0])) }).addTo(map);
    document.addEventListener("themechange", () => { map.removeLayer(tl); tl = MFJ.tiles(L).addTo(map); });
  } else {
    mapEl.style.display = "none";
  }
})();
