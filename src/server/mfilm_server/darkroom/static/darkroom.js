"use strict";
/* M-Film Web Darkroom UI. All text goes through textContent: file names and metadata are untrusted. */
const API = "/api/v1/darkroom";
const $ = (s, r = document) => r.querySelector(s);
function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
}
let toastT;
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("on"), 4500); }
async function api(path, opts = {}) {
  const r = await fetch(API + path, { credentials: "same-origin", ...opts,
    headers: { "X-MFilm-CSRF": "1", ...(opts.json ? { "Content-Type": "application/json" } : {}), ...(opts.headers || {}) },
    body: opts.json ? JSON.stringify(opts.json) : opts.body });
  if (r.status === 401 && !path.startsWith("/login")) { showLogin(); throw new Error("login required"); }
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : null;
  if (!r.ok) { const e = new Error(data ? `${data.error_code}: ${data.detail || ""}` : r.statusText); e.code = data && data.error_code; e.status = r.status; throw e; }
  return data;
}

/* ---------------- state ---------------- */
const S = { catalog: null, assets: [], selected: new Set(), current: null,
  look: "neutral", film: null, strength: 1, grain: 1, halation: 1, softness: 1, quality: 92, seed: 0, wb: "daylight",
  width: 0, height: 0, filmQuery: "" };
const STEPS = ["Material", "Camera look", "Film stock", "Optical effects", "Preview · Develop"];

function recipe() {
  const r = { schema_version: 2,
    camera_look: { id: S.look, version: "1.0.0", strength: S.look === "neutral" ? 1 : S.strength },
    film: { id: S.film, grain_scale: S.grain, halation_scale: S.halation, softness_scale: S.softness },
    optical: { preset_id: "none", strength: 0, stack: [] },
    render: { output_format: "jpeg", output_color_space: "srgb", quality: S.quality },
    seed: S.seed, extensions: { white_balance: S.wb } };
  if (S.width && S.height) { r.render.width = S.width; r.render.height = S.height; }
  return r;
}

/* ---------------- login ---------------- */
function showLogin() {
  $("#logout").hidden = true; $("#steps").replaceChildren();
  const pw = h("input", { type: "password", id: "pw", autocomplete: "current-password", required: true });
  const form = h("form", { class: "step login", onsubmit: async ev => {
    ev.preventDefault();
    try { await api("/login", { method: "POST", json: { password: pw.value } }); boot(); }
    catch (e) { toast(e.message); }
  } }, h("h2", {}, "Safelight on"), h("label", { for: "pw" }, "Operator password"), pw,
    h("div", { class: "bar" }, h("button", { class: "primary" }, "Enter the darkroom")));
  $("#app").replaceChildren(form); pw.focus();
}

/* ---------------- layout ---------------- */
function step(n, title, hint, ...body) {
  return h("section", { class: "step", id: "s" + n }, h("h2", {}, h("span", { class: "n" }, n), title, hint ? h("span", { class: "hint" }, hint) : null), body);
}
async function boot() {
  try { S.catalog = await api("/catalog"); } catch (e) { if (e.status !== 401) toast(e.message); return; }
  if (!S.film) S.film = S.catalog.films.find(f => f.id === "portra400") ? "portra400" : S.catalog.films[0].id;
  $("#logout").hidden = false;
  $("#steps").replaceChildren(...STEPS.map((t, i) => h("a", { href: "#s" + (i + 1) }, h("b", {}, i + 1), t)));
  $("#app").replaceChildren(
    step(1, "Source material", "RAW only · originals are never modified", materialPanel()),
    step(2, "Camera look", "independent of the camera that shot the frame", looksPanel()),
    step(3, "Film stock", `${S.catalog.films.length} profiles from the shared M-Film engine`, filmPanel()),
    step(4, "Optical effects", "optional", opticsPanel()),
    step(5, "Preview, develop", "", previewPanel(), developPanel()));
  await refreshAssets(); refreshJobs(); renderLooks(); renderFilms();
}
$("#logout").addEventListener("click", async () => { try { await api("/logout", { method: "POST" }); } finally { showLogin(); } });

/* ---------------- step 1: material ---------------- */
function materialPanel() {
  const tabs = h("div", { class: "tabs", role: "tablist" },
    h("button", { role: "tab", "aria-selected": "true" }, "Upload RAW"),
    h("button", { role: "tab", disabled: true, title: "PhotoPrism source browser: not available yet" }, "PhotoPrism"),
    h("button", { role: "tab", disabled: true, title: "Camera rolls: not available yet" }, "M-Film rolls"));
  const input = h("input", { type: "file", multiple: true, accept: ".dng,.nef,.DNG,.NEF", hidden: true, id: "file" });
  const drop = h("div", { class: "drop", tabindex: "0", role: "button", "aria-label": "Choose RAW files" },
    h("p", {}, "Drop .DNG / .NEF files here, or press to choose"), h("small", {}, "multiple files · resumable chunks · duplicates are recognised"));
  const pick = () => input.click();
  drop.addEventListener("click", pick);
  drop.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
  ["dragenter", "dragover"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => uploadFiles([...e.dataTransfer.files]));
  input.addEventListener("change", () => { uploadFiles([...input.files]); input.value = ""; });
  return h("div", {}, tabs, drop, input, h("div", { class: "uplist", id: "uplist" }),
    h("div", { class: "bar" }, h("button", { onclick: () => selectAll(true) }, "Select all"), h("button", { onclick: () => selectAll(false) }, "Clear"),
      h("span", { class: "dim", id: "selcount" })), h("div", { class: "assets", id: "assets" }));
}
async function sha256(file) {
  if (!(window.crypto && crypto.subtle)) return null;       // plain-http LAN: no SubtleCrypto, server hashes instead
  if (file.size > 256 * 1048576) return null;
  const buf = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}
async function uploadFiles(files) {
  const list = $("#uplist");
  for (const f of files) {
    const bar = h("i"), msg = h("span", {}, "waiting");
    const row = h("div", {}, h("div", { class: "row" }, h("span", {}, f.name, " · ", (f.size / 1048576).toFixed(1), " MB"), msg), h("div", { class: "prog" }, bar));
    list.prepend(row);
    try {
      msg.textContent = "hashing"; const sha = await sha256(f);
      const init = await api("/sources/uploads", { method: "POST", json: { filename: f.name, size_bytes: f.size, ...(sha ? { sha256: sha } : {}) } });
      let src;
      if (init.state === "COMPLETE") src = init.source;
      else {
        let off = init.next_offset; const CH = Math.min(init.chunk_size, 4 << 20);
        while (off < f.size) {
          msg.textContent = `uploading ${Math.round(100 * off / f.size)}%`; bar.style.width = (100 * off / f.size) + "%";
          const piece = f.slice(off, off + CH);
          const r = await api(`/sources/uploads/${init.upload_id}/chunk`, { method: "PUT", body: piece, headers: { "X-Upload-Offset": String(off), "Content-Type": "application/octet-stream" } });
          off = r.next_offset;
        }
        msg.textContent = "checking RAW"; bar.style.width = "100%";
        src = (await api(`/sources/uploads/${init.upload_id}/complete`, { method: "POST" })).source;
      }
      msg.textContent = init.duplicate ? "already on the server" : "ready"; msg.className = "okc";
      S.selected.add(src.asset_id);
      await refreshAssets();
    } catch (e) { msg.textContent = e.message; msg.className = "err"; }
  }
}
async function refreshAssets() {
  const r = await api("/sources?count=500");
  S.assets = r.items;
  if (!S.current || !S.assets.find(a => a.asset_id === S.current)) S.current = S.assets.length ? S.assets[0].asset_id : null;
  renderAssets(); schedulePreview();
}
function selectAll(on) { S.selected = new Set(on ? S.assets.filter(a => a.eligible).map(a => a.asset_id) : []); renderAssets(); updateDevelop(); }
const thumbs = {};
function renderAssets() {
  const box = $("#assets"); if (!box) return;
  box.replaceChildren(...S.assets.map(a => {
    const m = a.meta || {}, sel = S.selected.has(a.asset_id);
    const th = h("div", { class: "th" }, thumbs[a.asset_id] ? null : "…");
    if (thumbs[a.asset_id]) th.style.backgroundImage = `url(${thumbs[a.asset_id]})`;
    else if (!(a.asset_id in thumbs)) loadThumb(a.asset_id);
    const el = h("div", { class: "asset" + (S.current === a.asset_id ? " cur" : ""), role: "button", tabindex: "0", "aria-pressed": String(sel),
      title: "Click: select · double-click: use for preview" },
      th, h("span", { class: "tick" }, sel ? "✓" : ""),
      h("div", { class: "meta" }, h("b", {}, a.filename), [m.model, m.width && `${m.width}×${m.height}`, m.iso && `ISO ${m.iso}`].filter(Boolean).join(" · "),
        (m.warnings || []).length ? h("span", { class: "err" }, " ⚠ " + m.warnings[0]) : null));
    const toggle = () => { sel ? S.selected.delete(a.asset_id) : S.selected.add(a.asset_id); renderAssets(); updateDevelop(); };
    el.addEventListener("click", toggle);
    el.addEventListener("dblclick", () => { S.current = a.asset_id; renderAssets(); schedulePreview(true); });
    el.addEventListener("keydown", e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); toggle(); } if (e.key === "p") { S.current = a.asset_id; renderAssets(); schedulePreview(true); } });
    return el;
  }));
  $("#selcount").textContent = `${S.selected.size} of ${S.assets.length} selected · double-click a frame to preview it`;
  updateDevelop();
}
async function loadThumb(id) {
  thumbs[id] = thumbs[id] || "";   // mark in flight
  try {                            // the RAW's own embedded preview: instant, and never competes with real previews
    const r = await fetch(`${API}/sources/${id}/thumbnail`, { credentials: "same-origin" });
    if (r.ok) { thumbs[id] = URL.createObjectURL(await r.blob()); renderAssets(); }
  } catch (e) { /* thumbnails are best effort */ }
}
async function imgUrl(pid) {
  const r = await fetch(`${API}/previews/${pid}/image`, { credentials: "same-origin" });
  if (!r.ok) throw new Error("image " + r.status);
  return URL.createObjectURL(await r.blob());
}
async function pollPreview(pid, tries = 400) {
  for (let i = 0; i < tries; i++) {
    const st = await api("/previews/" + pid);
    if (["DONE", "FAILED", "SUPERSEDED"].includes(st.status)) return st;
    await new Promise(r => setTimeout(r, i < 5 ? 250 : 600));
  }
  return { status: "FAILED", error_code: "TIMEOUT" };
}

/* ---------------- step 2: camera look ---------------- */
function looksPanel() { return h("div", {}, h("div", { class: "cards", id: "looks" }),
  h("div", { class: "grid2", style: "margin-top:1rem" }, h("div", {}, h("label", { for: "strength" }, "Look intensity"), h("input", { type: "range", id: "strength", min: 0, max: 100, value: 100, disabled: true,
    oninput: e => { S.strength = e.target.value / 100; schedulePreview(); } })))); }
function renderLooks() {
  $("#looks").replaceChildren(...S.catalog.camera_looks.map(l => {
    const b = h("button", { class: "card", "aria-pressed": String(S.look === l.id), "aria-disabled": String(!l.supported),
      title: l.supported ? "" : "Not implemented in this engine yet", onclick: () => {
        if (!l.supported) return toast(`${l.name}: not implemented in this engine yet`);
        S.look = l.id; $("#strength").disabled = l.id === "neutral"; renderLooks(); schedulePreview(); } },
      h("strong", {}, l.name), h("small", {}, l.evidence_tier), h("br"), h("span", { class: "tag" }, l.supported ? "available" : "not yet implemented"));
    return b;
  }));
}

/* ---------------- step 3: film ---------------- */
function filmPanel() {
  const q = h("input", { type: "text", placeholder: "Search 72 film stocks…", "aria-label": "Search films", oninput: e => { S.filmQuery = e.target.value; renderFilms(); } });
  const sl = (label, key) => h("div", {}, h("label", {}, label, " ", h("span", { id: "v_" + key }, "1.00")),
    h("input", { type: "range", min: 0, max: 200, value: 100, "aria-label": label, oninput: e => { S[key] = e.target.value / 100; $("#v_" + key).textContent = S[key].toFixed(2); schedulePreview(); } }));
  return h("div", {}, q, h("div", { class: "filmlist", id: "films", role: "listbox" }),
    h("div", { class: "row3", style: "margin-top:1rem" }, sl("Grain", "grain"), sl("Halation (film)", "halation"), sl("Softness", "softness")));
}
function renderFilms() {
  const q = S.filmQuery.toLowerCase();
  $("#films").replaceChildren(...S.catalog.films.filter(f => !q || (f.name + f.id).toLowerCase().includes(q)).map(f =>
    h("button", { role: "option", "aria-pressed": String(S.film === f.id), onclick: () => { S.film = f.id; renderFilms(); schedulePreview(); } },
      f.name, h("span", {}, [f.kind, f.iso && "ISO " + f.iso].filter(Boolean).join(" · ")))));
}

/* ---------------- step 4: optics ---------------- */
function opticsPanel() {
  return h("div", {}, h("p", { class: "dim" }, "These effects are part of the spec but not implemented in the film engine yet, so they are shown disabled. A recipe that asks for one is rejected rather than rendered without it."),
    h("div", { class: "cards" }, [...S.catalog.optical_effects, ...S.catalog.optical_presets.filter(p => p.id !== "none")].map(o => h("div", { class: "card", "aria-disabled": "true" }, h("strong", {}, o.name), h("span", { class: "tag" }, "not yet implemented")))));
}

/* ---------------- step 5: preview ---------------- */
let pvSeq = 0, pvTimer = null, pvShown = null;
function previewPanel() {
  const treated = h("img", { alt: "Treated preview", id: "pv_t", hidden: true });
  const before = h("img", { alt: "Original, neutral development", id: "pv_b", hidden: true });
  const cut = h("div", { class: "cut", id: "cut", tabindex: "0", role: "slider", "aria-label": "Before / after", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": 50 });
  const stage = h("div", { class: "stage", id: "stage" }, h("div", { class: "layer" }, treated), h("div", { class: "layer", id: "beforeLayer" }, before), cut,
    h("span", { class: "busy", id: "busy" }), h("span", { class: "dim", id: "empty" }, "Upload a RAW to see a preview"));
  let pos = 50;
  const setCut = p => { pos = Math.max(0, Math.min(100, p)); cut.style.left = pos + "%"; $("#beforeLayer").style.clipPath = `inset(0 ${100 - pos}% 0 0)`; cut.setAttribute("aria-valuenow", Math.round(pos)); };
  setTimeout(() => setCut(50));
  const move = ev => { const r = stage.getBoundingClientRect(); setCut(100 * (ev.clientX - r.left) / r.width); };
  cut.addEventListener("pointerdown", e => { cut.setPointerCapture(e.pointerId); cut.addEventListener("pointermove", move); });
  cut.addEventListener("pointerup", () => cut.removeEventListener("pointermove", move));
  cut.addEventListener("keydown", e => { if (e.key === "ArrowLeft") setCut(pos - 3); if (e.key === "ArrowRight") setCut(pos + 3); });
  return h("div", {}, h("div", { class: "bar", style: "margin:0 0 .7rem" },
    h("label", { for: "pvsize", style: "margin:0" }, "Preview size"), h("select", { id: "pvsize", style: "width:auto", onchange: () => schedulePreview(true) },
      h("option", { value: 1280 }, "1280 px (default)"), h("option", { value: 720 }, "720 px"), h("option", { value: 2048 }, "2048 px")),
    h("button", { onclick: () => schedulePreview(true) }, "Refresh preview"), h("span", { class: "dim", id: "wipelabel" }, "left of the line: original (neutral) · right: treated")),
    stage, h("div", { class: "pvinfo", id: "pvinfo" }, "Previews are real renders at reduced size and are not export quality."));
}
function schedulePreview(now) {
  const t = $("#pv_t"); if (!t) return;
  if (t.src) t.classList.add("stale");
  clearTimeout(pvTimer);
  pvTimer = setTimeout(runPreview, now ? 0 : 450);
}
async function runPreview() {
  if (!S.current) { $("#empty").hidden = false; return; }
  const seq = ++pvSeq, edge = Number($("#pvsize").value), busy = $("#busy");
  busy.textContent = "rendering…"; $("#empty").hidden = true;
  try {
    const [pt, pb] = await Promise.all([
      api("/previews", { method: "POST", json: { asset_id: S.current, recipe: recipe(), max_edge: edge, stream: "main" } }),
      api("/previews", { method: "POST", json: { asset_id: S.current, kind: "before", max_edge: edge, stream: "main", white_balance: S.wb } })]);
    const [st, sb] = await Promise.all([pollPreview(pt.preview_id), pollPreview(pb.preview_id)]);
    if (seq !== pvSeq) return;                         // a newer edit superseded this one: never show it as current
    if (st.status !== "DONE") { busy.textContent = ""; $("#pvinfo").textContent = `Preview failed: ${st.error_code || st.status} ${st.detail || ""}`; return; }
    const [u1, u2] = await Promise.all([imgUrl(pt.preview_id), sb.status === "DONE" ? imgUrl(pb.preview_id) : null]);
    if (seq !== pvSeq) return;
    const t = $("#pv_t"), b = $("#pv_b");
    t.src = u1; t.hidden = false; t.classList.remove("stale");
    if (u2) { b.src = u2; b.hidden = false; }
    busy.textContent = "";
    $("#pvinfo").replaceChildren(h("span", {}, "recipe ", pt.recipe_hash.slice(0, 12)), h("span", {}, `${st.width}×${st.height}px preview`),
      h("span", {}, `${st.elapsed_s}s${st.cached ? " (cached)" : ""}`), h("span", {}, "not export quality"));
  } catch (e) { if (seq === pvSeq) { busy.textContent = ""; $("#pvinfo").textContent = "Preview: " + e.message; } }
}

/* ---------------- develop + jobs ---------------- */
function developPanel() {
  const sizeSel = h("select", { id: "outsize", onchange: e => { const v = e.target.value; [S.width, S.height] = v ? v.split("x").map(Number) : [0, 0]; schedulePreview(); } },
    h("option", { value: "" }, "Original size"), h("option", { value: "3000x2000" }, "3000 × 2000 (3:2)"), h("option", { value: "2000x1333" }, "2000 × 1333 (3:2)"), h("option", { value: "1600x1200" }, "1600 × 1200 (4:3)"));
  return h("div", { style: "margin-top:1.6rem" }, h("h3", { style: "font-size:.95rem;margin:0 0 .6rem" }, "Develop (full size, from the original RAW)"),
    h("div", { class: "row3" }, h("div", {}, h("label", { for: "outsize" }, "Output size (never upscaled)"), sizeSel),
      h("div", {}, h("label", { for: "q" }, "JPEG quality"), h("input", { type: "number", id: "q", min: 1, max: 100, value: 92, onchange: e => { S.quality = Number(e.target.value); } })),
      h("div", {}, h("label", { for: "wb" }, "White balance"), h("select", { id: "wb", onchange: e => { S.wb = e.target.value; schedulePreview(); } },
        h("option", { value: "daylight" }, "Daylight (M-Film default)"), h("option", { value: "as-shot" }, "As shot")))),
    h("p", { class: "dim", style: "font:.72rem var(--mono)" }, "Publishing to PhotoPrism is not available yet: results are kept in the M-Film library and can be downloaded."),
    h("div", { class: "bar" }, h("button", { class: "primary", id: "develop", onclick: develop }, "Develop selected"), h("span", { class: "dim", id: "devinfo" })),
    h("h3", { style: "font-size:.95rem;margin:1.6rem 0 .6rem" }, "Jobs"), h("div", { class: "jobs", id: "jobs" }));
}
function updateDevelop() { const b = $("#develop"); if (!b) return; b.disabled = S.selected.size === 0; $("#devinfo").textContent = S.selected.size ? `${S.selected.size} frame(s) → ${S.selected.size} JPEG` : "select at least one frame"; }
async function develop() {
  try {
    const j = await api("/jobs", { method: "POST", json: { schema_version: 1, source: { kind: "upload", assets: [...S.selected].map(asset_id => ({ asset_id })) },
      recipe: recipe(), output: { format: "jpeg", quality: S.quality, publish: false } } });
    toast(`Job queued (${j.total} frame${j.total === 1 ? "" : "s"})`); refreshJobs();
  } catch (e) { toast(e.message); }
}
let jobsTimer;
async function refreshJobs() {
  clearTimeout(jobsTimer);
  let list; try { list = await api("/jobs?count=15"); } catch (e) { return; }
  const full = await Promise.all(list.items.map(j => api("/jobs/" + j.job_id)));
  const box = $("#jobs"); if (!box) return;
  box.replaceChildren(...full.map(jobCard));
  if (full.some(j => ["QUEUED", "RUNNING"].includes(j.state))) jobsTimer = setTimeout(refreshJobs, 2500);
  else jobsTimer = setTimeout(refreshJobs, 15000);
}
const COLOR = { COMPLETE: "var(--ok)", FAILED: "var(--bad)", PARTIAL: "var(--safe2)", RUNNING: "var(--safe)", QUEUED: "var(--dim)", CANCELLED: "var(--dim)" };
function jobCard(j) {
  const st = h("span", { class: "st", style: `color:${COLOR[j.state] || "inherit"}` }, j.state);
  const acts = h("div", { class: "acts" });
  if (["QUEUED", "RUNNING"].includes(j.state)) acts.append(h("button", { onclick: async () => { await api(`/jobs/${j.job_id}/cancel`, { method: "POST" }); refreshJobs(); } }, "Cancel"));
  if (j.counts.FAILED || j.counts.CANCELLED) acts.append(h("button", { onclick: async () => { await api(`/jobs/${j.job_id}/retry`, { method: "POST" }); refreshJobs(); } }, "Retry failed / cancelled"));
  if (j.counts.COMPLETE) acts.append(h("a", { class: "btn", href: `${API}/jobs/${j.job_id}/zip`, download: "" }, `Download ZIP (${j.counts.COMPLETE})`));
  return h("div", { class: "job" }, h("header", {}, st, h("b", {}, j.film), h("span", { class: "dim" }, `${j.camera_look} · recipe ${j.recipe_hash.slice(0, 10)} · ${j.created_at.slice(0, 19).replace("T", " ")}`)),
    h("div", { class: "items" }, j.items.map(i => h("div", {}, h("span", {}, i.filename),
      i.render ? h("a", { href: `${API}/renders/${i.render.render_id}/file`, style: "color:var(--ok)" }, `${i.render.width}×${i.render.height} ↓`)
        : h("span", { class: i.state === "FAILED" ? "err" : "dim", title: i.error_detail || "" }, i.error_code || i.state)))), acts);
}

boot();
