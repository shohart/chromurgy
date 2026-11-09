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

/* ---------------- popup loading indicator ---------------- */
let loadDepth = 0, loadTimer = null, loadT0 = 0;
function showLoader(title, sub) {
  const box = $("#loader"); if (!box) return;
  if (loadDepth === 0) {
    loadT0 = performance.now();
    box.replaceChildren(h("div", { class: "loader-box" },
      h("div", { class: "spinner", "aria-hidden": "true" }),
      h("div", { class: "loader-title", id: "loader_title" }, title || "Loading source material…"),
      h("div", { class: "loader-sub", id: "loader_sub" }, sub || "Reading RAW frames from archive…"),
      h("div", { class: "loader-bar", "aria-hidden": "true" }),
      h("div", { class: "loader-time", id: "loader_time" }, "0.0 s")));
    box.hidden = false;
    clearInterval(loadTimer);
    loadTimer = setInterval(() => {
      const el = $("#loader_time");
      if (el) el.textContent = ((performance.now() - loadT0) / 1000).toFixed(1) + " s";
    }, 100);
  } else {
    const t = $("#loader_title"), s = $("#loader_sub");
    if (t && title) t.textContent = title;
    if (s && sub) s.textContent = sub;
  }
  loadDepth++;
}
function hideLoader() {
  loadDepth = Math.max(0, loadDepth - 1);
  if (loadDepth === 0) {
    clearInterval(loadTimer); loadTimer = null;
    const box = $("#loader"); if (box) box.hidden = true;
  }
}
async function withLoading(title, sub, fn) {
  showLoader(title, sub);
  try { return await fn(); }
  finally { hideLoader(); }
}

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
const S = { catalog: null, assets: [], allSourceCount: 0, selected: new Set(), current: null,
  dismissed: new Set(JSON.parse(localStorage.getItem("mfilm.dismissed") || "[]")),
  traySort: localStorage.getItem("mfilm.tray_sort") || "default",
  look: "neutral", film: null, strength: 1, grain: 1, halation: 1, softness: 1, quality: 92, seed: 0, wb: "daylight",
  width: 0, height: 0, filmQuery: "", fxPreset: "none", fx: new Set(), fxStrength: 0.5, policy: "film", activePreset: null,
  baseTone: { brightness: 0, contrast: 0, develop: 1, filter: "none", filterStrength: 1 },
  baseWbSel: "daylight", baseWbCustom: { k: 5500, t: 0 },
  tone: { brightness: 0, contrast: 0, develop: 1, filter: "none", filterStrength: 1 }, wbSel: "daylight", wbCustom: { k: 5500, t: 0 }, wbl: null, sliders: [],
  adjustments: JSON.parse(localStorage.getItem("mfilm.adjustments") || "{}"),
  crops: JSON.parse(localStorage.getItem("mfilm.crops") || "{}"),
  rotates: JSON.parse(localStorage.getItem("mfilm.rotates") || "{}"), rotOpen: false,
  aspect: "free", cropMode: false, cropRect: null, cropImg: null };
const STEPS = ["Material", "Camera look", "Film stock", "Optical effects", "My presets", "Preview · Develop"];

function saveDismissed() {
  try { localStorage.setItem("mfilm.dismissed", JSON.stringify([...S.dismissed])); } catch (e) {}
}
function saveTraySort() {
  try { localStorage.setItem("mfilm.tray_sort", S.traySort); } catch (e) {}
}
function getSortedAssets() {
  const list = [...S.assets];
  if (S.traySort === "name_asc") {
    list.sort((a, b) => (a.filename || "").localeCompare(b.filename || "", undefined, { numeric: true, sensitivity: "base" }));
  } else if (S.traySort === "name_desc") {
    list.sort((a, b) => (b.filename || "").localeCompare(a.filename || "", undefined, { numeric: true, sensitivity: "base" }));
  } else if (S.traySort === "date_asc") {
    list.sort((a, b) => {
      const ta = (a.meta && (a.meta.captured_at || a.meta.mtime)) || a.created_at || "";
      const tb = (b.meta && (b.meta.captured_at || b.meta.mtime)) || b.created_at || "";
      return String(ta).localeCompare(String(tb));
    });
  } else if (S.traySort === "date_desc") {
    list.sort((a, b) => {
      const ta = (a.meta && (a.meta.captured_at || a.meta.mtime)) || a.created_at || "";
      const tb = (b.meta && (b.meta.captured_at || b.meta.mtime)) || b.created_at || "";
      return String(tb).localeCompare(String(ta));
    });
  }
  return list;
}
function saveRotates() {
  try { localStorage.setItem("mfilm.rotates", JSON.stringify(S.rotates)); } catch (e) {}
}
function saveAdjustments() {
  try { localStorage.setItem("mfilm.adjustments", JSON.stringify(S.adjustments)); } catch (e) {}
}
function normDeg(d) {
  let v = ((Number(d) || 0) + 180) % 360;
  if (v < 0) v += 360;
  v -= 180;
  if (Math.abs(v + 180) < 0.01) v = 180;
  v = Math.round(v * 100) / 100;
  return Math.abs(v) < 0.01 ? 0 : v;
}
function curRotate() {
  return S.current && S.rotates[S.current] ? normDeg(S.rotates[S.current]) : 0;
}

function loadFrameAdjustments(id) {
  if (!id) return;
  const adj = S.adjustments[id];
  if (adj && adj.tone) {
    Object.assign(S.tone, S.baseTone, adj.tone);
  } else {
    Object.assign(S.tone, S.baseTone);
  }
  if (adj && adj.wbSel !== undefined) {
    S.wbSel = adj.wbSel;
  } else {
    S.wbSel = S.baseWbSel;
  }
  S.wb = S.wbSel === "as-shot" ? "as-shot" : "daylight";
  if (adj && adj.wbCustom) {
    Object.assign(S.wbCustom, S.baseWbCustom, adj.wbCustom);
  } else {
    Object.assign(S.wbCustom, S.baseWbCustom);
  }
}
function markFrameAdjusted() {
  if (!S.current) return;
  const toneDiff = Math.abs(S.tone.brightness - S.baseTone.brightness) > 1e-4 ||
                   Math.abs(S.tone.contrast - S.baseTone.contrast) > 1e-4 ||
                   Math.abs(S.tone.develop - S.baseTone.develop) > 1e-4 ||
                   S.tone.filter !== S.baseTone.filter ||
                   Math.abs(S.tone.filterStrength - S.baseTone.filterStrength) > 1e-4;
  const wbDiff = S.wbSel !== S.baseWbSel ||
                 (S.wbSel === "custom" && (Math.abs(S.wbCustom.k - S.baseWbCustom.k) > 1 || Math.abs(S.wbCustom.t - S.baseWbCustom.t) > 1));
  if (toneDiff || wbDiff) {
    S.adjustments[S.current] = {
      tone: { ...S.tone },
      wbSel: S.wbSel,
      wbCustom: { ...S.wbCustom }
    };
  } else {
    delete S.adjustments[S.current];
  }
  saveAdjustments();
  renderAssets();
}
function getFrameAdjustments(asset_id) {
  const adj = S.adjustments[asset_id];
  const tone = (adj && adj.tone) ? { ...S.baseTone, ...adj.tone } : { ...S.baseTone };
  const wbSel = (adj && adj.wbSel !== undefined) ? adj.wbSel : S.baseWbSel;
  const wbCustom = (adj && adj.wbCustom) ? { ...S.baseWbCustom, ...adj.wbCustom } : { ...S.baseWbCustom };
  return { tone, wbSel, wbCustom, isAdjusted: Boolean(adj) };
}
function frameToneExt(tone) {
  const t = {};
  if (tone.brightness) t.brightness_ev = tone.brightness;
  if (tone.contrast) t.contrast = tone.contrast;
  if (tone.develop !== 1 && S.film !== "none") t.develop_strength = tone.develop;
  if (tone.filter !== "none") {
    t.filter = tone.filter;
    if (tone.filterStrength !== 1) t.filter_strength = tone.filterStrength;
  }
  return t;
}
function frameWbExt(wbSel, wbCustom) {
  if (wbSel.startsWith("builtin:") || wbSel.startsWith("user:")) return wbSel;
  if (wbSel === "custom") return { name: `Custom ${wbCustom.k} K`, kelvin: wbCustom.k, tint: wbCustom.t };
  return null;
}
function resetAllFrameOverrides() {
  S.adjustments = {}; saveAdjustments();
  S.crops = {}; saveCrops();
  S.rotates = {}; saveRotates();
}

function toneExt() {
  return frameToneExt(S.tone);
}
function wbExt() {
  return frameWbExt(S.wbSel, S.wbCustom);
}
function opticalBlock() {
  if (S.fxPreset === "golden_haze") return { preset_id: "golden_haze", strength: S.fxStrength, halation_policy: S.policy, stack: [] };
  const on = [...S.fx];
  if (!on.length) return { preset_id: "none", strength: 0, halation_policy: S.policy === "disabled" ? "disabled" : "film", stack: [] };
  return { preset_id: on[0], strength: S.fxStrength, halation_policy: S.policy, stack: on.map(id => ({ id, enabled: true, parameters: {} })) };
}
function recipe(withCrop = true) {
  const r = { schema_version: 2,
    camera_look: { id: S.look, version: "1.0.0", strength: S.look === "neutral" ? 1 : S.strength },
    film: { id: S.film, grain_scale: S.grain, halation_scale: S.halation, softness_scale: S.softness },
    optical: opticalBlock(),
    render: { output_format: "jpeg", output_color_space: "srgb", quality: S.quality },
    seed: S.seed, extensions: { white_balance: S.wbSel === "as-shot" ? "as-shot" : "daylight" } };
  const tn = toneExt(); if (Object.keys(tn).length) r.extensions.tone = tn;
  const wp = wbExt(); if (wp) r.extensions.wb_profile = wp;
  if (S.width && S.height) { r.render.width = S.width; r.render.height = S.height; }
  if (withCrop && S.crops[S.current]) r.extensions.crop = S.crops[S.current];     // this frame's own framing
  if (withCrop && S.rotates[S.current]) r.extensions.rotate = normDeg(S.rotates[S.current]);
  return r;
}
function baseJobRecipe() {
  const r = { schema_version: 2,
    camera_look: { id: S.look, version: "1.0.0", strength: S.look === "neutral" ? 1 : S.strength },
    film: { id: S.film, grain_scale: S.grain, halation_scale: S.halation, softness_scale: S.softness },
    optical: opticalBlock(),
    render: { output_format: "jpeg", output_color_space: "srgb", quality: S.quality },
    seed: S.seed, extensions: { white_balance: S.baseWbSel === "as-shot" ? "as-shot" : "daylight" } };
  const tn = frameToneExt(S.baseTone); if (Object.keys(tn).length) r.extensions.tone = tn;
  const wp = frameWbExt(S.baseWbSel, S.baseWbCustom); if (wp) r.extensions.wb_profile = wp;
  if (S.width && S.height) { r.render.width = S.width; r.render.height = S.height; }
  return r;
}
function baseRecipe(opts = {}) {
  const r = recipe(true);
  if (r.extensions) delete r.extensions.tone;     // post-tone (brightness, contrast, develop, filter) is applied live on canvas
  if (opts.noFilm) r.film = { id: "none", grain_scale: 1, halation_scale: 1, softness_scale: 1 };
  if (opts.noFx) r.optical = { preset_id: "none", strength: 0, halation_policy: S.policy === "disabled" ? "disabled" : "film", stack: [] };
  if (opts.noLook) r.camera_look = { id: "neutral", version: "1.0.0", strength: 1 };
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
  try { S.wbl = await api("/wb-profiles"); } catch (e) { S.wbl = { builtin: [], imported: [] }; }
  if (!S.film) S.film = S.catalog.films.find(f => f.id === "portra400") ? "portra400" : S.catalog.films[0].id;
  $("#logout").hidden = false;
  $("#steps").replaceChildren(...STEPS.map((t, i) => h("a", { href: "#s" + (i + 1) }, h("b", {}, i + 1), t)));
  const left = h("div", { class: "pane-left", id: "leftPane" },
    step(1, "Source material", "RAW only · originals are never modified", materialPanel()),
    step(2, "Camera look", "independent of the camera that shot the frame", looksPanel()),
    step(3, "Film stock", `${S.catalog.films.length} profiles from the shared M-Film engine`, filmPanel()),
    step(4, "Optical effects", "optional · applied before the look and film", opticsPanel()),
    step(5, "My presets", "the whole setting — look, film, optics, adjustments — saved under a name", presetsPanel()));
  const right = h("div", { class: "pane-right", id: "rightPane" },
    step(6, "Preview, develop", "",
      h("div", { class: "pv-pin" }, previewPanel()),
      h("div", { class: "dev-scroll" }, adjustPanel(), developPanel())));
  $("#app").replaceChildren(h("div", { class: "workspace" }, left, right));
  await refreshAssets(); refreshJobs(); syncControls(); refreshPresets();
}
$("#logout").addEventListener("click", async () => { try { await api("/logout", { method: "POST" }); } finally { showLogin(); } });

/* ---------------- step 1: material ---------------- */
function materialPanel() {
  const upPane = uploadPane(), ppPane = ppPaneEl(), rollPane = rollPaneEl();
  const panes = [upPane, ppPane, rollPane];
  const mk = (label, pane, selected) => h("button", { role: "tab", "aria-selected": String(!!selected), onclick: ev => {
    for (const b of ev.target.parentNode.children) b.setAttribute("aria-selected", String(b === ev.target));
    panes.forEach(x => { x.hidden = x !== pane; });
    if (pane === ppPane) ppInit(); if (pane === rollPane) rollsInit(); } }, label);
  const tabs = h("div", { class: "tabs", role: "tablist" }, mk("Upload RAW", upPane, true), mk("PhotoPrism", ppPane), mk("M-Film rolls", rollPane));
  return h("div", {}, tabs, upPane, ppPane, rollPane,
    h("div", { class: "bar", style: "flex-wrap:wrap;gap:.4rem;align-items:center" },
      h("button", { onclick: () => selectAll(true) }, "Select all"),
      h("button", { id: "deselectbtn", onclick: () => selectAll(false), title: "Uncheck all frames without removing them from the tray" }, "Deselect"),
      h("button", { id: "clearbtn", onclick: clearAssets, title: "Clear loaded photos from the workspace tray and reset the preview" }, "Clear"),
      h("button", { id: "ppsyncbtn", hidden: true, onclick: () => syncPpPreviews(true), title: "Synchronize thumbnails with PhotoPrism" }, "↻ Sync previews"),
      h("button", { id: "restorebtn", hidden: true, onclick: restoreAssets, title: "Restore previously loaded photos from archive" }, "Restore archived"),
      h("label", { style: "display:inline-flex;align-items:center;gap:.3rem;font-size:.78rem;margin-left:auto" },
        "Сортировка ленты: ",
        h("select", { id: "traysort", style: "padding:.2rem .4rem;font-size:.78rem", onchange: e => { S.traySort = e.target.value; saveTraySort(); renderAssets(); } },
          h("option", { value: "default", selected: S.traySort === "default" }, "Исходный порядок"),
          h("option", { value: "date_asc", selected: S.traySort === "date_asc" }, "По дате (сначала старые)"),
          h("option", { value: "date_desc", selected: S.traySort === "date_desc" }, "По дате (сначала новые)"),
          h("option", { value: "name_asc", selected: S.traySort === "name_asc" }, "По имени (A → Z)"),
          h("option", { value: "name_desc", selected: S.traySort === "name_desc" }, "По имени (Z → A)"))),
      h("span", { class: "dim", id: "selcount", style: "width:100%" })),
    h("div", { class: "assets", id: "assets" }));
}
/* ---- camera rolls received from the SX510: their archived originals can be developed again with any recipe ---- */
let rawRolls = [];
function renderRolls() {
  const box = $("#rolllist"); if (!box) return;
  const sort = $("#roll_sort") ? $("#roll_sort").value : "date_desc";
  const list = [...rawRolls];
  if (sort === "date_asc") {
    list.sort((a, b) => String(a.created_at || a.received_at || "").localeCompare(String(b.created_at || b.received_at || "")));
  } else if (sort === "name_asc") {
    list.sort((a, b) => String(a.film_profile_id || "").localeCompare(String(b.film_profile_id || "")));
  } else {
    list.sort((a, b) => String(b.created_at || b.received_at || "").localeCompare(String(a.created_at || a.received_at || "")));
  }
  box.replaceChildren(...list.map(x => h("button", { class: "card", disabled: !x.verified, onclick: () => rollUse(x) },
    h("strong", {}, `${x.roll_id.slice(0, 8)} · ${x.film_profile_id}`), h("small", {}, `${x.verified}/${x.frames} frames on the server · ${(x.created_at || "").slice(0, 10)}`),
    h("span", { class: "tag" }, `use ${x.verified} frame(s)`))));
}
function rollPaneEl() {
  return h("div", { id: "rolls", hidden: true },
    h("div", { class: "bar", style: "margin-top:0;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.4rem" },
      h("p", { class: "dim", id: "rollmsg", style: "margin:0" }, "Loading rolls…"),
      h("label", { style: "display:inline-flex;align-items:center;gap:.3rem;font-size:.78rem" },
        "Сортировка: ",
        h("select", { id: "roll_sort", style: "padding:.2rem .4rem;font-size:.78rem", onchange: () => renderRolls() },
          h("option", { value: "date_desc" }, "По дате (сначала новые)"),
          h("option", { value: "date_asc" }, "По дате (сначала старые)"),
          h("option", { value: "name_asc" }, "По профилю пленки (A–Z)")))),
    h("div", { class: "cards", id: "rolllist" }));
}
async function rollsInit() {
  await withLoading("Loading M-Film rolls…", "Reading archived camera rolls from the server…", async () => {
    try {
      const r = await api("/rolls");
      rawRolls = r.items || [];
      $("#rollmsg").textContent = rawRolls.length ? "Rolls received from the camera. The roll's own archive and history are never changed; renditions are new files." : "No rolls on the server yet.";
      renderRolls();
    } catch (e) { $("#rollmsg").textContent = e.message; }
  });
}
async function rollUse(x) {
  await withLoading(`Loading roll ${x.roll_id.slice(0, 8)}…`, `Inspecting ${x.verified} RAW frame(s) and extracting previews…`, async () => {
    try {
      const r = await api("/rolls/select", { method: "POST", json: { device_id: x.device_id, roll_id: x.roll_id } });
      r.assets.forEach(a => { S.dismissed.delete(a.asset_id); S.selected.add(a.asset_id); });
      saveDismissed();
      S.ppSource = r.source;
      await refreshAssets();
      if (r.assets.length) setCurrent(r.assets[0].asset_id);
      toast(`${r.assets.length} frame(s) ready${r.skipped.length ? `, ${r.skipped.length} skipped: ${r.skipped[0].reason}` : ""}`);
    } catch (e) { toast(e.message); }
  });
}
function uploadPane() {
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
  return h("div", {}, drop, input, h("div", { class: "uplist", id: "uplist" }));
}

/* ---- PhotoPrism source browser: albums and folders are different things; selection survives paging ---- */
const PP = { inst: null, mode: "albums", albumOrder: "name", photoOrder: "newest", src: null, page: [], offset: 0, next: null, prevOffsets: [], stack: [], q: "", chosen: new Map(), sourceKind: null, sourceUid: null };
const ppThumbs = {};
const ppWaiters = {};
function loadPpThumb(url, onReady) {
  if (!url) return;
  if (ppThumbs[url]) { if (onReady) onReady(ppThumbs[url]); return; }
  if (onReady) (ppWaiters[url] = ppWaiters[url] || []).push(onReady);
  if (url in ppThumbs) return;
  ppThumbs[url] = "";
  fetch(url, { credentials: "same-origin" }).then(async r => {
    if (r.ok) {
      const objUrl = URL.createObjectURL(await r.blob());
      ppThumbs[url] = objUrl;
      const cbs = ppWaiters[url] || []; delete ppWaiters[url];
      cbs.forEach(fn => { try { fn(objUrl); } catch (_) {} });
    } else { delete ppThumbs[url]; delete ppWaiters[url]; }
  }).catch(() => { delete ppThumbs[url]; delete ppWaiters[url]; });
}
function ppPaneEl() { return h("div", { id: "pp", hidden: true }, h("div", { class: "bar", style: "margin-top:0;flex-wrap:wrap;gap:.4rem;align-items:center" },
  h("button", { id: "pp_albums", onclick: () => ppMode("albums") }, "Albums"), h("button", { id: "pp_folders", onclick: () => ppMode("folders") }, "Originals folders"),
  h("button", { id: "pp_resync", onclick: () => syncPpPreviews(true), title: "Synchronize and refresh previews from PhotoPrism" }, "↻ Sync previews"),
  h("input", { type: "text", id: "pp_q", placeholder: "Search albums…", style: "max-width:14rem", oninput: e => { PP.q = e.target.value; clearTimeout(PP.t); PP.t = setTimeout(ppList, 300); } }),
  h("label", { id: "pp_album_sort_wrap", style: "display:inline-flex;align-items:center;gap:.3rem;font-size:.78rem" },
    "Сортировка: ",
    h("select", { id: "pp_album_sort", style: "padding:.2rem .4rem;font-size:.78rem", onchange: e => { PP.albumOrder = e.target.value; ppList(); } },
      h("option", { value: "name", selected: PP.albumOrder === "name" }, "По имени (A–Z)"),
      h("option", { value: "newest", selected: PP.albumOrder === "newest" }, "По дате (сначала новые)"),
      h("option", { value: "oldest", selected: PP.albumOrder === "oldest" }, "По дате (сначала старые)"),
      h("option", { value: "count", selected: PP.albumOrder === "count" }, "По числу фото"))),
  h("span", { class: "dim", id: "pp_state" })), h("div", { id: "pp_crumb", class: "dim", style: "font:.75rem var(--mono);margin:.5rem 0" }),
  h("div", { class: "cards", id: "pp_list" }), h("div", { id: "pp_photos" })); }
async function ppInit() {
  if (PP.inst) return;
  await withLoading("Connecting to PhotoPrism…", "Checking library instance and albums…", async () => {
    try {
      const r = await api("/photoprism/instances"); PP.inst = r.items[0];
      if (!PP.inst.configured) { $("#pp_state").textContent = "PhotoPrism is not configured on this server"; return; }
      $("#pp_state").textContent = `${PP.inst.name} ${PP.inst.version || ""}${PP.inst.read.originals ? "" : " · originals not readable from this host"}`;
      await ppMode("albums");
    } catch (e) { $("#pp_state").textContent = e.message; }
  });
}
async function ppMode(m) {
  PP.mode = m; PP.stack = []; PP.src = null;
  $("#pp_photos").replaceChildren();
  $("#pp_q").hidden = m !== "albums";
  if ($("#pp_album_sort_wrap")) $("#pp_album_sort_wrap").hidden = m !== "albums";
  await ppList();
}
async function ppList(keepPhotos = false) {
  const box = $("#pp_list"); box.replaceChildren(); if (!keepPhotos) $("#pp_photos").replaceChildren();
  await withLoading("Loading PhotoPrism catalog…", PP.mode === "albums" ? "Fetching albums…" : "Fetching folders…", async () => {
    try {
      if (PP.mode === "albums") {
        $("#pp_crumb").textContent = "Albums are virtual collections, not folders";
        const r = await api(`/photoprism/${PP.inst.id}/albums?count=200&order=${PP.albumOrder}&q=${encodeURIComponent(PP.q)}`);
        box.replaceChildren(...r.items.map(a => {
          const thEl = a.thumb_url ? h("span", { class: "alb-th" }) : null;
          if (thEl) {
            if (ppThumbs[a.thumb_url]) thEl.style.backgroundImage = `url(${ppThumbs[a.thumb_url]})`;
            else loadPpThumb(a.thumb_url, u => { thEl.style.backgroundImage = `url(${u})`; });
          }
          return h("button", { type: "button", class: "card" + (thEl ? " alb-card" : ""), onclick: () => ppOpen("album", a.uid, a.title, 0) },
            thEl, h("span", {}, h("strong", {}, a.title), h("small", {}, `${a.photo_count} photos${a.manual ? "" : " · smart album"}`)));
        }));
        if (!r.items.length) box.append(h("p", { class: "dim" }, "No albums"));
      } else {
        const parent = PP.stack.join("/");
        $("#pp_crumb").textContent = "Folder under originals: /" + parent;
        const r = await api(`/photoprism/${PP.inst.id}/folders?parent_id=${encodeURIComponent(parent)}`);
        let folders = r.items || [];
        folders.sort((a, b) => (a.title || "").localeCompare(b.title || "", undefined, { numeric: true, sensitivity: "base" }));
        if (PP.stack.length) box.append(h("button", { type: "button", class: "card", onclick: () => { PP.stack.pop(); ppList(); } }, h("strong", {}, "↑ up")));
        box.append(...folders.map(f => h("button", { type: "button", class: "card", onclick: async () => { PP.stack = f.path.split("/"); await ppList(true); await ppOpen("folder", f.path, f.path, 0); } }, h("strong", {}, f.title), h("small", {}, f.path))));
      }
    } catch (e) { box.append(h("p", { class: "err" }, e.message)); }
  });
}
async function ppOpen(kind, uid, title, offset = 0, forceSync = false, keepHistory = false) {
  if (!keepHistory || kind !== PP.sourceKind || uid !== PP.sourceUid || offset === 0) PP.prevOffsets = [];
  PP.sourceKind = kind; PP.sourceUid = uid; PP.title = title;
  const box = $("#pp_photos"); box.replaceChildren(h("p", { class: "dim" }, "loading…"));
  await withLoading(`Loading "${title}"…`, "Synchronizing previews and checking RAW originals in PhotoPrism…", async () => {
    try {
      const r = await api(`/photoprism/${PP.inst.id}/photos?source_kind=${kind}&source_uid=${encodeURIComponent(uid)}&count=60&offset=${offset}&order=${PP.photoOrder}`);
      if (forceSync) {
        r.items.forEach(p => {
          if (p.thumb_url) {
            delete ppThumbs[p.thumb_url];
            p.thumb_url += (p.thumb_url.includes("?") ? "&" : "?") + "sync=1&t=" + Date.now();
          }
        });
      }
      PP.page = r.items; PP.offset = offset; PP.next = r.next_offset; ppRender();
      if (keepHistory && box) box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) { box.replaceChildren(h("p", { class: "err" }, e.message)); }
  });
}
function ppPrevPage() {
  if (PP.offset <= 0) return;
  const prev = PP.prevOffsets.length ? PP.prevOffsets.pop() : Math.max(0, PP.offset - 60);
  ppOpen(PP.sourceKind, PP.sourceUid, PP.title, prev, false, true);
}
function ppNextPage() {
  if (PP.next == null) return;
  PP.prevOffsets.push(PP.offset);
  ppOpen(PP.sourceKind, PP.sourceUid, PP.title, PP.next, false, true);
}
function ppRender() {
  const box = $("#pp_photos"); if (!box) return;
  const pageNum = PP.prevOffsets.length + 1;
  const grid = h("div", { class: "assets" }, PP.page.map(p => {
    const sel = PP.chosen.has(p.photo_uid);
    const turl = p.thumb_url ? ppThumbs[p.thumb_url] : null;
    const statusTxt = h("span", { class: "th-wait" }, turl ? "" : (p.thumb_url ? "…" : (p.eligible ? "RAW" : "no RAW")));
    const th = h("div", { class: "th" },
      statusTxt,
      h("span", { class: "rawtag" + (p.eligible ? "" : " dim") }, p.eligible ? "RAW" : "no RAW"));
    if (turl) th.style.backgroundImage = `url(${turl})`;
    else if (p.thumb_url) loadPpThumb(p.thumb_url, u => { th.style.backgroundImage = `url(${u})`; statusTxt.textContent = ""; });
    const tick = h("span", { class: "tick" }, sel ? "✓" : "");
    const el = h("div", { class: "asset", role: "button", tabindex: p.eligible ? "0" : "-1", "aria-pressed": String(sel), "aria-disabled": String(!p.eligible),
      title: p.eligible ? "" : p.reason, style: p.eligible ? "" : "opacity:.5;cursor:not-allowed" },
      th, tick,
      h("div", { class: "meta" }, h("b", {}, p.name || p.photo_uid), p.eligible ? `${(p.raw.bytes / 1048576).toFixed(1)} MB` : p.reason));
    const tog = () => { if (!p.eligible) return toast(p.reason); PP.chosen.has(p.photo_uid) ? PP.chosen.delete(p.photo_uid) : PP.chosen.set(p.photo_uid, { kind: PP.sourceKind, uid: PP.sourceUid }); ppRender(); };
    el.addEventListener("click", tog); el.addEventListener("keydown", e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); tog(); } });
    return el; }));
  const elig = PP.page.filter(p => p.eligible);
  const pager = () => h("span", { class: "pager" },
    h("button", { type: "button", disabled: PP.offset === 0, onclick: ppPrevPage }, "← Prev"),
    h("span", { class: "dim", style: "font:.74rem var(--mono);padding:0 .3rem" }, `Page ${pageNum}`),
    h("button", { type: "button", disabled: PP.next == null, onclick: ppNextPage }, "Next →"));
  box.replaceChildren(
    h("div", { class: "bar", style: "justify-content:space-between;margin:.8rem 0 .35rem;flex-wrap:wrap;gap:.4rem;align-items:center" },
      h("div", { style: "display:inline-flex;align-items:center;gap:.6rem;flex-wrap:wrap" },
        h("h3", { style: "font-size:.9rem;margin:0" }, PP.title),
        h("label", { style: "display:inline-flex;align-items:center;gap:.3rem;font-size:.78rem;color:var(--dim)" },
          "Сортировка: ",
          h("select", {
            id: "pp_photo_sort",
            style: "padding:.2rem .4rem;font-size:.78rem",
            onchange: e => {
              PP.photoOrder = e.target.value;
              ppOpen(PP.sourceKind, PP.sourceUid, PP.title, 0, false, false);
            }
          },
            h("option", { value: "newest", selected: PP.photoOrder === "newest" }, "По дате съёмки (сначала новые)"),
            h("option", { value: "oldest", selected: PP.photoOrder === "oldest" }, "По дате съёмки (сначала старые)"),
            h("option", { value: "name", selected: PP.photoOrder === "name" }, "По имени файла (A → Z)"),
            h("option", { value: "added", selected: PP.photoOrder === "added" }, "По дате добавления")))),
      pager()),
    h("div", { class: "pvinfo", style: "margin:0 0 .5rem" },
      h("span", {}, `${PP.page.length} on this page`), h("span", {}, `${elig.length} with a supported RAW`), h("span", {}, `${PP.page.length - elig.length} not usable (hover for the reason)`)),
    grid,
    h("div", { class: "bar" },
      h("button", { type: "button", onclick: () => { elig.forEach(p => PP.chosen.set(p.photo_uid, { kind: PP.sourceKind, uid: PP.sourceUid })); ppRender(); } }, "Select visible"),
      h("button", { type: "button", disabled: !PP.chosen.size, onclick: () => { PP.chosen.clear(); ppRender(); } }, "Clear selection"),
      h("button", { type: "button", onclick: ppSelectAll }, "Select all eligible in this " + PP.sourceKind),
      h("button", { type: "button", onclick: () => syncPpPreviews(true) }, "↻ Sync previews"),
      pager(),
      h("button", { type: "button", class: "primary", disabled: !PP.chosen.size, onclick: ppUse }, `Use ${PP.chosen.size} selected`)));
}
async function syncPpPreviews(manual = false) {
  const instId = (PP.inst && PP.inst.id) || "default";
  const run = async () => {
    try {
      const r = await api(`/photoprism/${instId}/sync-thumbs`, { method: "POST", json: { force: manual } });
      if (manual) {
        for (const a of (r.items || [])) delete thumbs[a.asset_id];
      }
      await refreshAssets();
      if (manual && PP.sourceKind && PP.sourceUid) {
        await ppOpen(PP.sourceKind, PP.sourceUid, PP.title, PP.offset, true, true);
      }
      if (manual) toast(`Synced ${r.synced || 0} preview(s) from PhotoPrism${r.updated ? ` (${r.updated} updated)` : ""}`);
    } catch (e) { if (manual) toast(e.message); }
  };
  if (manual) await withLoading("Syncing previews with PhotoPrism…", "Refreshing thumbnails and checking for changes…", run);
  else await run();
}
async function ppSelectAll() {
  await withLoading("Importing all eligible RAWs…", "Hashing and snapshotting every RAW in this collection…", async () => {
    await ppSelect({ all_eligible: true, source_kind: PP.sourceKind, source_uid: PP.sourceUid });
  });
}
async function ppUse() {
  await withLoading(`Importing ${PP.chosen.size} selected RAW(s)…`, "Verifying RAW originals and extracting thumbnails…", async () => {
    const groups = new Map();
    for (const [uid, g] of PP.chosen) { const k = g.kind + ":" + g.uid; if (!groups.has(k)) groups.set(k, { ...g, uids: [] }); groups.get(k).uids.push(uid); }
    for (const g of groups.values()) for (let i = 0; i < g.uids.length; i += 25) await ppSelect({ photo_uids: g.uids.slice(i, i + 25), source_kind: g.kind, source_uid: g.uid });
    PP.chosen.clear(); ppRender();
  });
}
async function ppSelect(body) {
  try {
    const r = await api(`/photoprism/${PP.inst.id}/select`, { method: "POST", json: body });
    r.assets.forEach(a => { S.dismissed.delete(a.asset_id); S.selected.add(a.asset_id); });
    saveDismissed();
    S.ppSource = r.source;
    await refreshAssets();
    if (r.assets.length) setCurrent(r.assets[r.assets.length - 1].asset_id);
    toast(`${r.assets.length} RAW source(s) ready${r.skipped.length ? `, ${r.skipped.length} skipped: ${r.skipped[0].reason}` : ""}`);
  } catch (e) { toast(e.message); }
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
      S.dismissed.delete(src.asset_id); saveDismissed();
      S.selected.add(src.asset_id);
      await refreshAssets();
      setCurrent(src.asset_id);
    } catch (e) { msg.textContent = e.message; msg.className = "err"; }
  }
}
function clearPreviewStage() {
  pvSeq++; clearTimeout(pvTimer); resetPvState();
  ["#pv_t", "#pv_b"].forEach(q => { const i = $(q); if (i) { i.removeAttribute("src"); i.hidden = true; i.classList.remove("stale"); } });
  const c = $("#pv_c"); if (c) c.hidden = true;
  const b = $("#busy"); if (b) b.textContent = "";
  const emp = $("#empty"); if (emp) emp.hidden = false;
  const st = $("#stage"); if (st) st.style.height = "";
  const info = $("#pvinfo"); if (info) info.textContent = "Previews are real renders at reduced size and are not export quality.";
}
async function refreshAssets() {
  const r = await api("/sources?count=500");
  S.allSourceCount = r.items.length;
  S.assets = r.items.filter(a => !S.dismissed.has(a.asset_id));
  for (const id of [...S.selected]) if (!S.assets.some(a => a.asset_id === id)) S.selected.delete(id);
  if (!S.current || !S.assets.find(a => a.asset_id === S.current)) S.current = S.assets.length ? S.assets[0].asset_id : null;
  if (!S.current) clearPreviewStage();
  else loadFrameAdjustments(S.current);
  renderAssets(); syncControls(); if (S.current) schedulePreview();
}
/* The preview always follows the frame the user last touched; the previous frame's picture is cleared, never left standing. */
function setCurrent(id) {
  if (!id) return;
  const changed = S.current !== id;
  S.current = id;
  loadFrameAdjustments(id);
  syncControls();
  if (changed) {
    resetPvState();
    ["#pv_t", "#pv_b"].forEach(q => { const i = $(q); if (i) { i.removeAttribute("src"); i.hidden = true; i.classList.remove("stale"); } });
    const c = $("#pv_c"); if (c) c.hidden = true;
    const info = $("#pvinfo"); if (info) info.textContent = "Rendering the preview of the selected frame…";
  }
  renderAssets(); schedulePreview(true);
}
function selectAll(on) {
  S.selected = new Set(on ? S.assets.filter(a => a.eligible).map(a => a.asset_id) : []);
  renderAssets(); updateDevelop();
}
function clearAssets() {
  if (S.cropMode) endCrop(false);
  S.assets.forEach(a => S.dismissed.add(a.asset_id));
  saveDismissed();
  S.assets = [];
  S.selected.clear();
  S.current = null;
  S.adjustments = {}; saveAdjustments();
  if (PP.chosen.size) { PP.chosen.clear(); if ($("#pp_photos") && $("#pp_photos").children.length) ppRender(); }
  const upl = $("#uplist"); if (upl) upl.replaceChildren();
  clearPreviewStage();
  renderAssets(); syncRotateUi();
  toast("Cleared selected photos");
}
function removeAsset(id) {
  if (S.cropMode && S.current === id) endCrop(false);
  S.dismissed.add(id);
  saveDismissed();
  S.selected.delete(id);
  delete S.adjustments[id]; saveAdjustments();
  S.assets = S.assets.filter(a => a.asset_id !== id);
  if (S.current === id) {
    S.current = S.assets.length ? S.assets[0].asset_id : null;
    if (!S.current) clearPreviewStage();
    else setCurrent(S.current);
  }
  renderAssets(); syncRotateUi();
}
async function restoreAssets() {
  S.dismissed.clear();
  saveDismissed();
  await refreshAssets();
  toast(`Restored ${S.assets.length} photo(s)`);
}
const thumbs = {};
function renderAssets() {
  const box = $("#assets"); if (!box) return;
  box.replaceChildren(...getSortedAssets().map(a => {
    const m = a.meta || {}, sel = S.selected.has(a.asset_id), rot = S.rotates[a.asset_id] ? normDeg(S.rotates[a.asset_id]) : 0;
    const tv = a.thumb_v || a.sha256 || "0";
    const entry = thumbs[a.asset_id];
    const hasImg = entry && entry.v === tv && entry.url;
    const th = h("div", { class: "th" }, hasImg ? null : "…");
    if (hasImg) th.style.backgroundImage = `url(${entry.url})`;
    else if (!entry || entry.v !== tv) loadThumb(a.asset_id, tv);
    const rmBtn = h("button", { type: "button", class: "rm", title: "Remove from workspace",
      onclick: ev => { ev.stopPropagation(); removeAsset(a.asset_id); } }, "×");
    const el = h("div", { class: "asset" + (S.current === a.asset_id ? " cur" : ""), role: "button", tabindex: "0", "aria-pressed": String(sel),
      title: "Click: show in the preview · tick: include in Develop · ×: remove from workspace" },
      th, h("span", { class: "tick", title: "Include in Develop" }, sel ? "✓" : ""), rmBtn,
      h("div", { class: "meta" }, h("b", {}, a.filename, S.crops[a.asset_id] ? " ✂" : "", rot ? ` ⟳${rot}°` : "", S.adjustments[a.asset_id] ? " 🎛" : ""), [m.model, m.width && `${m.width}×${m.height}`, m.iso && `ISO ${m.iso}`].filter(Boolean).join(" · "),
        (m.warnings || []).length ? h("span", { class: "err" }, " ⚠ " + m.warnings[0]) : null));
    const toggle = () => { sel ? S.selected.delete(a.asset_id) : S.selected.add(a.asset_id); renderAssets(); updateDevelop(); };
    el.addEventListener("click", ev => { if (ev.target.classList.contains("tick")) toggle(); else { if (S.cropMode && a.asset_id !== S.current) endCrop(false); setCurrent(a.asset_id); } });
    el.addEventListener("keydown", e => { if (e.key === " ") { e.preventDefault(); toggle(); } if (e.key === "Enter") { e.preventDefault(); setCurrent(a.asset_id); } });
    return el;
  }));
  const desel = $("#deselectbtn"), clr = $("#clearbtn"), rest = $("#restorebtn"), ppsync = $("#ppsyncbtn");
  if (desel) desel.disabled = S.selected.size === 0;
  if (clr) clr.disabled = S.assets.length === 0 && S.selected.size === 0 && PP.chosen.size === 0;
  if (ppsync) ppsync.hidden = !S.assets.some(a => a.origin === "photoprism");
  if (rest) { rest.hidden = !(S.assets.length === 0 && S.allSourceCount > 0); rest.textContent = `Restore ${S.allSourceCount} archived`; }
  $("#selcount").textContent = S.assets.length
    ? `${S.selected.size} of ${S.assets.length} selected for Develop · click a frame to preview it, tick to include it`
    : "Workspace empty · choose RAWs from Upload, PhotoPrism or M-Film rolls";
  updateDevelop();
}
async function loadThumb(id, v = "0") {
  thumbs[id] = { v, url: "" };   // mark in flight for this version
  try {
    const r = await fetch(`${API}/sources/${id}/thumbnail?v=${encodeURIComponent(v)}`, { credentials: "same-origin" });
    if (r.ok) {
      const url = URL.createObjectURL(await r.blob());
      thumbs[id] = { v, url };
      renderAssets();
    }
  } catch (e) { /* thumbnails are best effort */ }
}
setInterval(() => {
  if (!document.hidden && S.assets.some(a => a.origin === "photoprism")) syncPpPreviews(false);
}, 30000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.assets.some(a => a.origin === "photoprism")) syncPpPreviews(false);
});
async function imgUrl(pid) {
  const r = await fetch(`${API}/previews/${pid}/image`, { credentials: "same-origin" });
  if (!r.ok) throw new Error("image " + r.status);
  return URL.createObjectURL(await r.blob());
}
async function pollPreview(pid, tries = 400) {
  for (let i = 0; i < tries; i++) {
    const st = await api("/previews/" + pid);
    if (["DONE", "FAILED", "SUPERSEDED"].includes(st.status)) return st;
    await new Promise(r => setTimeout(r, i < 8 ? 150 : 400));
  }
  return { status: "FAILED", error_code: "TIMEOUT" };
}

/* ---------------- step 2: camera look ---------------- */
const LOOK_SIGNATURES = {
  neutral: {
    tag: "Базовый профиль",
    summary: "Чистая линейная цветопередача без окраса сенсора",
    detail: "Нейтральная точка отсчета: точный базовый цвет и линейный контраст для максимального контроля при дальнейшей проявке плёнки."
  },
  leica_m8_ccd: {
    tag: "Kodak CCD · 10 Мп",
    summary: "Высокий микроконтраст и винтажный «лейковский» объем",
    detail: "Легендарный сенсор Kodak KAF-8300 с тонким ИК-фильтром. Плотные холодноватые тени, сочные теплые света, выразительная пластика и живые оттенки кожи."
  },
  leica_m9_ccd: {
    tag: "Full-frame Kodak CCD · 18 Мп",
    summary: "Густой аналоговый цвет и фирменная пластика M-серии",
    detail: "Знаменитый CCD-сенсор Kodak KAF-18500. Плёночная глубина, теплые света, оливково-изумрудные полутона зелени и высокая микрорезкость без цифровой жесткости."
  },
  fujifilm_s5_pro: {
    tag: "Super CCD SR Pro · Двойные пиксели",
    summary: "Широчайший ДД в светах и мягкие портретные тона",
    detail: "Легендарная матрица Fujifilm с раздельными датчиками для светов. Мягкий гармоничный контраст, невыбивающиеся света и нежные естественные скинтоны."
  },
  nikon_d200_ccd: {
    tag: "Sony CCD · Эпоха ранних зеркалок",
    summary: "Плотный контраст и глубокий насыщенный цвет",
    detail: "Узнаваемый характер классических CCD-камер Nikon: плотные тени, глубокий синий цвет неба, кирпично-теплые оттенки и живая цветопередача без перенасыщения."
  },
  pentax_645d_ccd: {
    tag: "Medium Format CCD · 40 Мп",
    summary: "Плавные тональные градиенты и среднеформатный объем",
    detail: "Крупноформатная CCD-матрица Kodak. Высочайшая градация полутонов, мягкий благородный спад в светах и сдержанный естественный колорит с глубоким разделением планов."
  },
  ricoh_gr_iii_positive: {
    tag: "Стрит-культура · Ricoh GR",
    summary: "Контрастный характер слайдовой фотопленки",
    detail: "Фирменный режим Positive Film: выразительный микроконтраст, глубокие тени, акцент на красный и синий спектры и сочная драматичная подача кадра."
  },
  sigma_dp2_merrill_foveon: {
    tag: "Foveon X3 · Прямой захват RGB",
    summary: "Экстремальный микроконтраст и текстурная резкость",
    detail: "Трехслойная кремниевая структура без дебайеризации (Bayer). Невероятная попиксельная четкость мелких фактур, нейтральные света и осязаемый трехмерный объем."
  },
  fujifilm_xpro3_classic_negative: {
    tag: "Fujicolor Superia Look",
    summary: "Плотные тени, умеренная насыщенность и бирюзовая зелень",
    detail: "Стилизация под классическую негативную плёнку: характерный S-образный контраст в средних тонах, приглушенные цвета и смещение зелени в благородный циановый оттенок."
  }
};

let lookHoverTimer = null, activeTooltipEl = null;
function hideLookTooltip() {
  if (lookHoverTimer) { clearTimeout(lookHoverTimer); lookHoverTimer = null; }
  if (activeTooltipEl) { activeTooltipEl.remove(); activeTooltipEl = null; }
}

function showLookTooltip(targetEl, lookId) {
  hideLookTooltip();
  const sig = LOOK_SIGNATURES[lookId];
  if (!sig || !targetEl || !targetEl.isConnected) return;
  const l = (S.catalog && S.catalog.camera_looks) ? S.catalog.camera_looks.find(x => x.id === lookId) : null;
  const name = l ? l.name : lookId;

  const tt = h("div", { class: "look-tooltip", role: "tooltip" },
    h("div", { class: "tt-head" },
      h("span", { class: "tt-title" }, name),
      h("span", { class: "tt-tag" }, sig.tag)),
    h("div", { class: "tt-summary" }, sig.summary),
    h("p", { class: "tt-detail" }, sig.detail));

  document.body.appendChild(tt);
  activeTooltipEl = tt;

  const rect = targetEl.getBoundingClientRect();
  const ttRect = tt.getBoundingClientRect();

  let top = rect.top - ttRect.height - 8;
  if (top < 10) top = rect.bottom + 8;

  let left = rect.left + (rect.width - ttRect.width) / 2;
  const pad = 12;
  if (left < pad) left = pad;
  if (left + ttRect.width > window.innerWidth - pad) {
    left = window.innerWidth - pad - ttRect.width;
  }

  tt.style.top = Math.round(top) + "px";
  tt.style.left = Math.round(left) + "px";
}

window.addEventListener("scroll", hideLookTooltip, { passive: true });
window.addEventListener("pointerdown", hideLookTooltip);
window.addEventListener("keydown", hideLookTooltip);

function looksPanel() { return h("div", {}, h("div", { class: "cards", id: "looks" }),
  h("div", { class: "grid2", style: "margin-top:1rem" }, h("div", {},
    h("label", { for: "strength" }, "Look intensity ", h("span", { id: "lookv", class: "val" }, "100%")),
    h("input", { type: "range", id: "strength", min: 0, max: 400, value: 100, disabled: true, title: "Double-click resets to 100%",
      ondblclick: e => { e.target.value = 100; S.strength = 1.0; if ($("#lookv")) $("#lookv").textContent = "100%"; scheduleLiveTone(); schedulePreview(); },
      oninput: e => { S.strength = e.target.value / 100; if ($("#lookv")) $("#lookv").textContent = Math.round(S.strength * 100) + "%"; scheduleLiveTone(); schedulePreview(); } })))); }
function renderLooks() {
  hideLookTooltip();
  $("#looks").replaceChildren(...S.catalog.camera_looks.map(l => {
    const b = h("button", { class: "card", "aria-pressed": String(S.look === l.id), "aria-disabled": String(!l.supported),
      title: l.supported ? "" : "Not implemented in this engine yet", onclick: () => {
        hideLookTooltip();
        if (!l.supported) return toast(`${l.name}: not implemented in this engine yet`);
        S.look = l.id; syncControls(); schedulePreview(); } },
      h("strong", {}, l.name), h("small", {}, l.evidence_tier), h("span", { class: "tag" }, l.supported ? "available" : "not available"));

    b.addEventListener("pointerenter", e => {
      if (e.pointerType === "touch") return;
      hideLookTooltip();
      lookHoverTimer = setTimeout(() => {
        if (b.matches(":hover")) showLookTooltip(b, l.id);
      }, 5000);
    });
    b.addEventListener("pointerleave", hideLookTooltip);
    b.addEventListener("mouseleave", hideLookTooltip);

    return b;
  }));
}

/* ---------------- step 3: film ---------------- */
function filmPanel() {
  const q = h("input", { type: "text", placeholder: "Search 72 film stocks…", "aria-label": "Search films", oninput: e => { S.filmQuery = e.target.value; renderFilms(); } });
  const sl = (label, key) => h("div", {}, h("label", {}, label, " ", h("span", { id: "v_" + key }, "1.00")),
    h("input", { type: "range", id: "sl_" + key, min: 0, max: 400, value: 100, "aria-label": label, title: "Double-click resets to 1.00",
      ondblclick: e => { e.target.value = 100; S[key] = 1.0; $("#v_" + key).textContent = "1.00"; schedulePreview(); },
      oninput: e => { S[key] = e.target.value / 100; $("#v_" + key).textContent = S[key].toFixed(2); schedulePreview(); } }));
  return h("div", {}, q, h("div", { class: "filmlist", id: "films", role: "listbox" }),
    h("div", { class: "row3", style: "margin-top:1rem" }, sl("Grain", "grain"), sl("Halation (film)", "halation"), sl("Softness", "softness")));
}
function renderFilms() {
  const q = S.filmQuery.toLowerCase();
  const none = h("button", { role: "option", "aria-pressed": String(S.film === "none"), title: "No film emulation: just the developed RAW",
    onclick: () => { S.film = "none"; syncControls(); schedulePreview(); } }, "None (no film emulation)", h("span", {}, "film stage off"));
  $("#films").replaceChildren(none, ...S.catalog.films.filter(f => !q || (f.name + f.id).toLowerCase().includes(q)).map(f =>
    h("button", { role: "option", "aria-pressed": String(S.film === f.id), onclick: () => { S.film = f.id; syncControls(); schedulePreview(); } },
      f.name, h("span", {}, [f.kind, f.iso && "ISO " + f.iso].filter(Boolean).join(" · ")))));
}

/* ---------------- step 4: optics (presets vs individual effects) ---------------- */
function normKey(t) { return String(t || "").toLowerCase().replace(/[^a-z0-9]/g, ""); }
function findFilmId(alias) {
  if (!alias || !S.catalog) return null;
  const n = normKey(alias);
  const f = S.catalog.films.find(x => normKey(x.id) === n || normKey(x.name) === n);
  return f ? f.id : null;
}
function isCompositeActive(c) {
  const f = c.film && findFilmId(c.film);
  const lookOk = S.look === c.camera_look;
  const filmOk = !f || S.film === f;
  const fxOk = c.optical_preset === "golden_haze"
    ? S.fxPreset === "golden_haze"
    : (S.fxPreset === "none" && S.fx.size === 1 && S.fx.has(c.optical_preset));
  return Boolean(lookOk && filmOk && fxOk && (!S.activePreset || S.activePreset === c.id));
}
function opticsPanel() {
  const presetGroup = h("div", { class: "preset-group" },
    h("div", { class: "group-head" },
      h("span", {}, "✦ Effect bundles & presets"),
      h("small", {}, "sets a curated combination · active bundle is framed in gold")),
    h("div", { class: "cards", id: "presetcards" }));
  const divider = h("div", { class: "fx-divider", role: "separator" });
  const fxGroup = h("div", { class: "effects-group" },
    h("div", { class: "group-head" },
      h("span", {}, "Individual optical effects"),
      h("small", {}, "combinable · effects included in an active bundle are also highlighted")),
    h("div", { class: "cards", id: "fxcards" }));
  const strength = h("input", { type: "range", id: "fxstrength", min: 0, max: 400, value: 50, "aria-label": "Optical effects strength", title: "Double-click resets to 0.50",
    ondblclick: e => { e.target.value = 50; S.fxStrength = 0.5; $("#fxv").textContent = "0.50"; scheduleLiveTone(); schedulePreview(); },
    oninput: e => { S.fxStrength = e.target.value / 100; $("#fxv").textContent = S.fxStrength.toFixed(2); scheduleLiveTone(); schedulePreview(); } });
  const policy = h("select", { id: "policy", onchange: e => { S.policy = e.target.value; schedulePreview(); } },
    h("option", { value: "film" }, "film: the film stock owns halation"), h("option", { value: "optical" }, "optical: replaces the film's halation"),
    h("option", { value: "stacked" }, "stacked: film + optical (deliberate)"), h("option", { value: "disabled" }, "disabled: no halation at all"));
  return h("div", {}, h("p", { class: "dim", style: "margin-top:0" }, "Effects run on scene-linear light before the look and film, in the engine's fixed order. Starter parameters are provisional artistic approximations, not measured recreations of any filter."),
    presetGroup, divider, fxGroup, h("div", { class: "grid2", style: "margin-top:1rem" },
      h("div", {}, h("label", { for: "fxstrength" }, "Effects strength ", h("span", { id: "fxv", class: "val" }, "0.50")), strength),
      h("div", {}, h("label", { for: "policy" }, "Halation (applied exactly once)"), policy)));
}
function renderFx() {
  const pbox = $("#presetcards"), box = $("#fxcards");
  if (!box || !S.catalog) return;
  if (pbox) {
    const compCards = S.catalog.composites.map(c => {
      const on = isCompositeActive(c);
      const summary = [c.camera_look !== "neutral" ? c.camera_look.replace(/_/g, " ") : "neutral look", c.film, c.optical_preset.replace(/_/g, " ")].filter(Boolean).join(" + ");
      return h("button", { class: "card preset-card", "aria-pressed": String(on), title: "Sets camera look, film and optical effect together",
        onclick: () => {
          if (on) {
            S.activePreset = null; S.fxPreset = "none"; S.fx.clear(); S.policy = "film";
            resetAllFrameOverrides();
            loadFrameAdjustments(S.current);
            syncControls(); renderAssets(); schedulePreview(true); toast("Preset cleared: " + c.name);
            return;
          }
          S.activePreset = c.id;
          S.look = c.camera_look; S.strength = c.look_strength;
          const f = c.film && findFilmId(c.film); if (f) S.film = f;
          if (c.optical_preset === "golden_haze") {
            S.fxPreset = "golden_haze"; S.fx = new Set(["soft_sun_glow", "black_pro_mist_like"]);
          } else {
            S.fxPreset = "none"; S.fx = new Set([c.optical_preset]);
          }
          S.fxStrength = c.optical_strength; S.policy = c.halation_policy || "film";
          resetAllFrameOverrides();
          loadFrameAdjustments(S.current);
          syncControls(); renderAssets(); schedulePreview(true); toast("Applied preset: " + c.name);
        } },
        h("span", { class: "badge" }, "✦ Preset"),
        h("strong", {}, c.name),
        h("small", {}, summary));
    });
    const anyCompOn = S.catalog.composites.some(isCompositeActive);
    const optPresets = S.catalog.optical_presets.filter(p => p.id !== "none").map(p => {
      const on = S.fxPreset === p.id && (!anyCompOn || S.activePreset === "opt:" + p.id);
      return h("button", { class: "card preset-card", "aria-pressed": String(on), "aria-disabled": String(!p.supported),
        title: "Applies the optical bundle without changing Camera Look or Film",
        onclick: () => {
          if (!p.supported) return toast(`${p.name}: not available`);
          if (on) {
            S.activePreset = null; S.fxPreset = "none"; S.fx.clear();
          } else {
            S.activePreset = "opt:" + p.id; S.fxPreset = p.id;
            S.fx = new Set(p.id === "golden_haze" ? ["soft_sun_glow", "black_pro_mist_like"] : []);
          }
          syncControls(); schedulePreview();
        } },
        h("span", { class: "badge" }, "✦ Optics bundle"),
        h("strong", {}, p.name),
        h("small", {}, "Soft Sun Glow + Black Pro-Mist (keeps Look & Film)"));
    });
    pbox.replaceChildren(...compCards, ...optPresets);
  }
  box.replaceChildren(...S.catalog.optical_effects.map(o => {
    const inGoldenHaze = S.fxPreset === "golden_haze" && (o.id === "soft_sun_glow" || o.id === "black_pro_mist_like");
    const on = inGoldenHaze || S.fx.has(o.id);
    return h("button", { class: "card fx-card", "aria-pressed": String(on), "aria-disabled": String(!o.supported), onclick: () => {
      if (!o.supported) return toast(`${o.name}: not available`);
      if (S.fxPreset === "golden_haze") {
        S.fxPreset = "none";
        S.fx = new Set(["soft_sun_glow", "black_pro_mist_like"]);
      }
      S.activePreset = null;
      on ? S.fx.delete(o.id) : S.fx.add(o.id);
      if (o.id === "film_halation_extra") S.policy = S.fx.has(o.id) ? "optical" : "film";
      syncControls(); schedulePreview(); } },
      h("span", { class: "badge" }, inGoldenHaze ? "Effect · in preset" : "Individual effect"),
      h("strong", {}, o.name),
      h("small", {}, "optical effect"));
  }));
}
function syncControls() {
  renderLooks(); renderFilms(); renderFx();
  if ($("#strength")) { $("#strength").disabled = S.look === "neutral"; $("#strength").value = Math.round(S.strength * 100); if ($("#lookv")) $("#lookv").textContent = Math.round(S.strength * 100) + "%"; }
  if ($("#fxstrength")) { $("#fxstrength").value = Math.round(S.fxStrength * 100); $("#fxv").textContent = S.fxStrength.toFixed(2); }
  ["grain", "halation", "softness"].forEach(k => {
    const el = $("#sl_" + k), val = $("#v_" + k);
    if (el) el.value = Math.round((S[k] !== undefined ? S[k] : 1) * 100);
    if (val) val.textContent = (S[k] !== undefined ? S[k] : 1).toFixed(2);
  });
  if ($("#policy")) $("#policy").value = S.policy;
  S.sliders.forEach(x => { x.inp.value = x.get(); x.out.textContent = x.fmt(x.get()); });
  const none = S.film === "none";
  ["#sl_grain", "#sl_halation", "#sl_softness", "#sl_develop"].forEach(q => { const i = $(q); if (i) i.disabled = none; });
  if ($("#filterstr")) { $("#filterstr").disabled = S.tone.filter === "none"; $("#filter").value = S.tone.filter; }
  if ($("#wbsel")) { renderWb(); }
  syncRotateUi();
  renderPresets();
}

/* ---------------- step 5: operator presets (the whole Darkroom setting under a name, stored on the server) ---------------- */
const PRESET_V = 1;
let userPresets = [], activeUserPreset = null;
function snapshotState() {
  return { v: PRESET_V, look: S.look, strength: S.strength, film: S.film, grain: S.grain, halation: S.halation, softness: S.softness,
    fxPreset: S.fxPreset, fx: [...S.fx], fxStrength: S.fxStrength, policy: S.policy, activePreset: S.activePreset,
    tone: { ...S.tone }, wbSel: S.wbSel, wbCustom: { ...S.wbCustom }, seed: S.seed };
}
function canon(x) {
  if (Array.isArray(x)) return "[" + x.map(canon).join(",") + "]";
  if (x && typeof x === "object") return "{" + Object.keys(x).sort().map(k => JSON.stringify(k) + ":" + canon(x[k])).join(",") + "}";
  return JSON.stringify(x === undefined ? null : x);
}
function stateKey(st) { const { v, activePreset, ...rest } = st || {}; return canon({ ...rest, fx: [...(rest.fx || [])].sort() }); }
function applyPresetState(st, name) {
  const C = S.catalog, warn = [];
  const num = (v, d) => (typeof v === "number" && isFinite(v) ? v : d);
  const look = C.camera_looks.find(l => l.id === st.look && l.supported);
  S.look = look ? look.id : "neutral"; if (st.look && !look) warn.push(`look ${st.look}`);
  S.strength = num(st.strength, 1);
  if (st.film === "none" || C.films.some(f => f.id === st.film)) S.film = st.film; else if (st.film) warn.push(`film ${st.film}`);
  S.grain = num(st.grain, 1); S.halation = num(st.halation, 1); S.softness = num(st.softness, 1);
  const okFx = new Set(C.optical_effects.filter(o => o.supported).map(o => o.id));
  S.fx = new Set((st.fx || []).filter(id => okFx.has(id)));
  S.fxPreset = st.fxPreset && C.optical_presets.some(p => p.id === st.fxPreset) ? st.fxPreset : "none";
  S.fxStrength = num(st.fxStrength, 0.5);
  S.policy = ["film", "optical", "stacked", "disabled"].includes(st.policy) ? st.policy : "film";
  S.activePreset = st.activePreset || null;
  if (st.tone) {
    Object.assign(S.baseTone, { brightness: 0, contrast: 0, develop: 1, filter: "none", filterStrength: 1 }, st.tone);
  } else {
    Object.assign(S.baseTone, { brightness: 0, contrast: 0, develop: 1, filter: "none", filterStrength: 1 });
  }
  Object.assign(S.baseWbCustom, { k: 5500, t: 0 }, st.wbCustom || {});
  const L = S.wbl || { builtin: [], imported: [] };
  const wbOk = ["daylight", "as-shot", "custom"].includes(st.wbSel) || [...L.builtin, ...L.imported].some(p => p.id === st.wbSel);
  S.baseWbSel = wbOk ? st.wbSel : "daylight"; if (st.wbSel && !wbOk) warn.push("white-balance profile");
  resetAllFrameOverrides();
  loadFrameAdjustments(S.current);
  S.seed = num(st.seed, 0);
  ["grain", "halation", "softness"].forEach(k => { const i = $("#sl_" + k), o = $("#v_" + k); if (i) i.value = Math.round(S[k] * 100); if (o) o.textContent = S[k].toFixed(2); });
  syncControls(); renderAssets(); schedulePreview(true);
  toast(`Preset “${name}” applied${warn.length ? ` · unavailable here: ${warn.join(", ")}` : ""}`);
}
function presetSummary(st) {
  const C = S.catalog, film = st.film === "none" ? "no film" : ((C.films.find(f => f.id === st.film) || {}).name || st.film);
  const look = st.look === "neutral" ? "neutral look" : ((C.camera_looks.find(l => l.id === st.look) || {}).name || st.look);
  const fx = st.fxPreset && st.fxPreset !== "none" ? st.fxPreset.replace(/_/g, " ") : (st.fx || []).length ? `${st.fx.length} effect(s)` : "no optics";
  const t = st.tone || {}, adj = [t.brightness ? `${t.brightness > 0 ? "+" : ""}${t.brightness} EV` : "", t.contrast ? `contrast ${Math.round(t.contrast * 100)}%` : "",
    t.filter && t.filter !== "none" ? t.filter : ""].filter(Boolean);
  return [look, film, fx, ...adj].join(" · ");
}
function presetsPanel() {
  const name = h("input", { type: "text", id: "presetname", maxlength: 80, placeholder: "Preset name, e.g. Autumn Portra soft", style: "flex:1 1 14rem",
    onkeydown: e => { if (e.key === "Enter") { e.preventDefault(); savePreset(); } } });
  return h("div", {},
    h("p", { class: "dim", style: "margin-top:0" }, "Saves camera look, film stock and its sliders, optical effects, adjustments and white balance together. Crop and rotation stay per frame. Saving under an existing name updates that preset."),
    h("div", { class: "bar", style: "margin-top:0" }, name, h("button", { type: "button", class: "primary", onclick: savePreset }, "★ Save current settings")),
    h("div", { class: "cards", id: "userpresets", style: "margin-top:.9rem" }));
}
async function refreshPresets() {
  try { userPresets = (await api("/presets")).items; } catch (e) { userPresets = []; }
  renderPresets();
}
function renderPresets() {
  const box = $("#userpresets"); if (!box) return;
  const cur = stateKey(snapshotState());
  if (!userPresets.length) { box.replaceChildren(h("p", { class: "dim" }, "No saved presets yet.")); return; }
  box.replaceChildren(...userPresets.map(p => {
    const on = stateKey({ v: PRESET_V, ...p.state }) === cur;
    const del = h("button", { type: "button", class: "rm", title: "Delete preset", onclick: async ev => {
      ev.stopPropagation();
      if (!confirm(`Delete preset “${p.name}”?`)) return;
      try { await api(`/presets/${p.id}`, { method: "DELETE" }); toast(`Preset “${p.name}” deleted`); refreshPresets(); } catch (e) { toast(e.message); }
    } }, "×");
    return h("button", { type: "button", class: "card user-preset", "aria-pressed": String(on), title: "Apply this preset",
      onclick: () => { activeUserPreset = p.id; $("#presetname").value = p.name; applyPresetState(p.state, p.name); } },
      del, h("span", { class: "badge" }, "★ My preset"), h("strong", {}, p.name), h("small", {}, presetSummary(p.state)),
      h("small", { class: "dim" }, (p.updated_at || "").slice(0, 16).replace("T", " ")));
  }));
}
async function savePreset() {
  const inp = $("#presetname"), name = (inp.value || "").trim();
  if (!name) { inp.focus(); return toast("Give the preset a name"); }
  const exists = userPresets.find(p => p.name === name);
  if (exists && !confirm(`Overwrite preset “${name}” with the current settings?`)) return;
  try {
    const r = await api("/presets", { method: "POST", json: { name, state: snapshotState() } });
    activeUserPreset = r.id; toast(r.created ? `Preset “${r.name}” saved` : `Preset “${r.name}” updated`); refreshPresets();
  } catch (e) { toast(e.message); }
}

/* ---------------- step 6: real-time preview + adjustments ---------------- */
let pvSeq = 0, pvTimer = null, liveRaf = 0;

/* Precomputed sRGB and Sepia tables (1025 steps = 1/4 bit precision) for 60 FPS canvas post-processing */
const LUT_N = 1024;
const SRGB_DEC = new Float32Array(LUT_N + 1);
const SEPIA_R = new Float32Array(LUT_N + 1);
const SEPIA_G = new Float32Array(LUT_N + 1);
const SEPIA_B = new Float32Array(LUT_N + 1);
for (let i = 0; i <= LUT_N; i++) {
  const x = i / LUT_N;
  SRGB_DEC[i] = x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
  SEPIA_R[i] = Math.min(1, Math.pow(x, 0.90) * 1.00);
  SEPIA_G[i] = Math.min(1, Math.pow(x, 1.02) * 0.93);
  SEPIA_B[i] = Math.min(1, Math.pow(x, 1.30) * 0.78);
}
function srgbEncScalar(x) {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  return x <= 0.0031308 ? 12.92 * x : 1.055 * Math.pow(x, 1 / 2.4) - 0.055;
}

const pvState = {
  w: 0, h: 0,
  filmImageData: null, filmPx: null,
  neutralPx: null,
  noFxPx: null, baseFxStrength: 0,
  noLookPx: null, baseLookStrength: 1,
  baseRotate: 0, workCanvas: null,
  outImageData: null,
  grain: null, grainKey: "",
  meta: null
};
function resetPvState() {
  pvState.w = pvState.h = 0;
  pvState.filmImageData = pvState.filmPx = pvState.neutralPx = pvState.noFxPx = pvState.noLookPx = pvState.outImageData = null;
  pvState.baseRotate = 0;
  pvState.meta = null;
}
function extractPixels(img) {
  const c = document.createElement("canvas");
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0);
  return ctx.getImageData(0, 0, c.width, c.height);
}
function ensureSilverGrain(w, h, seed) {
  const key = `${w}x${h}:${seed}`;
  if (pvState.grain && pvState.grainKey === key) return pvState.grain;
  const g = new Float32Array(w * h);
  let s = ((seed | 0) ^ 0x9e3779b9) >>> 0;
  if (!s) s = 1;
  const nextU = () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) + 0.5) / 4294967296; };
  for (let i = 0; i < g.length; i += 2) {
    const u1 = nextU(), u2 = nextU();
    const r = Math.sqrt(-2 * Math.log(u1)), th = 6.283185307179586 * u2;
    g[i] = r * Math.cos(th);
    if (i + 1 < g.length) g[i + 1] = r * Math.sin(th);
  }
  pvState.grain = g; pvState.grainKey = key;
  return g;
}

function scheduleLiveTone() {
  if (liveRaf) return;
  liveRaf = requestAnimationFrame(() => { liveRaf = 0; renderLiveTone(); });
}

function putWithLiveRotation(c, ctx, imgData) {
  const deltaRot = normDeg(curRotate() - (pvState.baseRotate || 0));
  const b = $("#pv_b");
  if (Math.abs(deltaRot) < 0.01) {
    const resized = c.width !== pvState.w || c.height !== pvState.h;
    if (resized) { c.width = pvState.w; c.height = pvState.h; fitStage(c); }
    ctx.putImageData(imgData, 0, 0);
    if (b) b.style.transform = "";
    return false;
  }
  if (!pvState.workCanvas) pvState.workCanvas = document.createElement("canvas");
  const wc = pvState.workCanvas;
  if (wc.width !== pvState.w || wc.height !== pvState.h) { wc.width = pvState.w; wc.height = pvState.h; }
  wc.getContext("2d").putImageData(imgData, 0, 0);
  const q = Math.round(deltaRot / 90) * 90;
  const rem = deltaRot - q;
  const swap = Math.abs((q / 90) % 2) === 1;
  const bw = swap ? pvState.h : pvState.w, bh = swap ? pvState.w : pvState.h;
  const radRem = Math.abs(rem * Math.PI / 180);
  const cosA = Math.cos(radRem), sinA = Math.sin(radRem);
  const s = Math.abs(rem) >= 0.01 ? Math.min(bw / (bw * cosA + bh * sinA), bh / (bw * sinA + bh * cosA)) : 1;
  const cw = Math.max(16, Math.round(bw * s)), ch = Math.max(16, Math.round(bh * s));
  const resized = c.width !== cw || c.height !== ch;
  if (resized) { c.width = cw; c.height = ch; fitStage(c); }
  ctx.save();
  ctx.clearRect(0, 0, cw, ch);
  ctx.translate(cw / 2, ch / 2);
  ctx.rotate(deltaRot * Math.PI / 180);
  ctx.drawImage(wc, -pvState.w / 2, -pvState.h / 2);
  ctx.restore();
  if (b) b.style.transform = `rotate(${deltaRot}deg)`;
  return true;
}

function renderLiveTone() {
  const c = $("#pv_c");
  if (!c || !pvState.filmPx || !pvState.w || !pvState.h) return;
  const ctx = c.getContext("2d");
  const T = S.tone;
  const dev = S.film === "none" ? 1 : T.develop;
  const ev = T.brightness, con = T.contrast, flt = T.filter, fstr = T.filterStrength;
  const hasFxDelta = pvState.noFxPx && pvState.baseFxStrength > 0 && Math.abs(S.fxStrength - pvState.baseFxStrength) > 1e-3;
  const fxScale = hasFxDelta ? (S.fxStrength / pvState.baseFxStrength) : 1;
  const hasLookDelta = pvState.noLookPx && pvState.baseLookStrength > 0 && S.look !== "neutral" && Math.abs(S.strength - pvState.baseLookStrength) > 1e-3;
  const lookScale = hasLookDelta ? (S.strength / pvState.baseLookStrength) : 1;

  if (dev === 1 && ev === 0 && con === 0 && (flt === "none" || fstr <= 0) && !hasFxDelta && !hasLookDelta) {
    const rotChanged = putWithLiveRotation(c, ctx, pvState.filmImageData);
    updatePvInfo(rotChanged);
    return;
  }

  const bcLut = new Float32Array(LUT_N + 1);
  const bcByte = new Uint8ClampedArray(LUT_N + 1);
  const evMul = ev !== 0 ? Math.pow(2, ev) : 1;
  for (let i = 0; i <= LUT_N; i++) {
    let x = i / LUT_N;
    if (ev !== 0) {
      x = srgbEncScalar(SRGB_DEC[i] * evMul);
    }
    if (con !== 0) {
      const s = x * x * (3 - 2 * x);
      x = Math.min(1, Math.max(0, x + con * (s - x)));
    }
    bcLut[i] = x;
    bcByte[i] = (x * 255 + 0.5) | 0;
  }

  if (!pvState.outImageData || pvState.outImageData.width !== pvState.w || pvState.outImageData.height !== pvState.h) {
    pvState.outImageData = ctx.createImageData(pvState.w, pvState.h);
  }
  const src = pvState.filmPx, np = pvState.neutralPx, nfx = pvState.noFxPx, nlk = pvState.noLookPx;
  const out = pvState.outImageData.data;
  const len = src.length;
  const useDev = dev < 1 && np && np.length === len;
  const useFx = hasFxDelta && nfx && nfx.length === len;
  const useLook = hasLookDelta && nlk && nlk.length === len;
  const useFilter = flt !== "none" && fstr > 0;
  const grain = (useFilter && flt === "silver") ? ensureSilverGrain(pvState.w, pvState.h, S.seed) : null;
  const scaleIdx = LUT_N / 255;

  for (let p = 0; p < len; p += 4) {
    let r = src[p], g = src[p + 1], b = src[p + 2];
    if (useFx) {
      r = Math.min(255, Math.max(0, nfx[p] + (r - nfx[p]) * fxScale));
      g = Math.min(255, Math.max(0, nfx[p + 1] + (g - nfx[p + 1]) * fxScale));
      b = Math.min(255, Math.max(0, nfx[p + 2] + (b - nfx[p + 2]) * fxScale));
    }
    if (useLook) {
      r = Math.min(255, Math.max(0, nlk[p] + (r - nlk[p]) * lookScale));
      g = Math.min(255, Math.max(0, nlk[p + 1] + (g - nlk[p + 1]) * lookScale));
      b = Math.min(255, Math.max(0, nlk[p + 2] + (b - nlk[p + 2]) * lookScale));
    }
    if (useDev) {
      r = np[p] + dev * (r - np[p]);
      g = np[p + 1] + dev * (g - np[p + 1]);
      b = np[p + 2] + dev * (b - np[p + 2]);
    }
    const ri = (r * scaleIdx + 0.5) | 0;
    const gi = (g * scaleIdx + 0.5) | 0;
    const bi = (b * scaleIdx + 0.5) | 0;
    if (!useFilter) {
      out[p] = bcByte[ri];
      out[p + 1] = bcByte[gi];
      out[p + 2] = bcByte[bi];
      out[p + 3] = 255;
    } else {
      let rf = bcLut[ri], gf = bcLut[gi], bf = bcLut[bi];
      if (flt === "grayscale" || flt === "sepia") {
        const linL = 0.2126 * SRGB_DEC[(rf * LUT_N) | 0] + 0.7152 * SRGB_DEC[(gf * LUT_N) | 0] + 0.0722 * SRGB_DEC[(bf * LUT_N) | 0];
        const lumI = Math.min(LUT_N, Math.max(0, (srgbEncScalar(linL) * LUT_N + 0.5) | 0));
        if (flt === "grayscale") {
          const lv = lumI / LUT_N;
          rf += fstr * (lv - rf); gf += fstr * (lv - gf); bf += fstr * (lv - bf);
        } else {
          rf += fstr * (SEPIA_R[lumI] - rf); gf += fstr * (SEPIA_G[lumI] - gf); bf += fstr * (SEPIA_B[lumI] - bf);
        }
      } else if (flt === "silver") {
        let v = 0.38 * rf + 0.52 * gf + 0.10 * bf;
        v = (v + 0.40 * (v * v * (3 - 2 * v) - v)) * 0.965 + 0.018;
        const amp = 0.008 + 0.034 * 4.0 * v * (1.0 - v);
        v = Math.min(1, Math.max(0, v + amp * grain[p >> 2]));
        rf += fstr * (v - rf); gf += fstr * (v - gf); bf += fstr * (v - bf);
      }
      out[p] = (rf * 255 + 0.5) | 0;
      out[p + 1] = (gf * 255 + 0.5) | 0;
      out[p + 2] = (bf * 255 + 0.5) | 0;
      out[p + 3] = 255;
    }
  }
  putWithLiveRotation(c, ctx, pvState.outImageData);
  updatePvInfo(true);
}

function updatePvInfo(liveAdjusted) {
  const info = $("#pvinfo"), m = pvState.meta;
  if (!info || !m) return;
  const rot = curRotate();
  info.replaceChildren(
    h("span", {}, "recipe ", m.hash.slice(0, 12)),
    h("span", {}, `${m.width}×${m.height}px preview`),
    rot ? h("span", { style: "color:var(--safe2)" }, `rotated ${rot > 0 ? "+" : ""}${rot}°`) : null,
    h("span", {}, `${m.elapsed_s}s${m.cached ? " (cached)" : ""}`),
    liveAdjusted ? h("span", { style: "color:var(--safe2)" }, "live adjustments active") : null,
    h("span", {}, "not export quality"));
}

/* ---------------- adjustments: brightness, contrast, development strength, filters, white balance, all-off ---------------- */
function slider(id, label, min, max, step, get, set, fmt, def, title, liveOnly = false) {
  const out = h("span", { class: "val" }, fmt(get()));
  const onChange = () => { if (liveOnly) scheduleLiveTone(); else schedulePreview(); };
  const inp = h("input", { type: "range", id, min, max, step, value: get(), "aria-label": label, title: (title || "") + " Double-click resets.",
    oninput: e => { set(+e.target.value); out.textContent = fmt(get()); onChange(); },
    onchange: e => { set(+e.target.value); out.textContent = fmt(get()); onChange(); },
    ondblclick: () => { set(def); inp.value = def; out.textContent = fmt(def); onChange(); } });
  S.sliders.push({ inp, out, get, fmt });
  return h("div", {}, h("label", { for: id }, label, " ", out), inp);
}
function adjustPanel() {
  S.sliders = [];
  const sg = v => (v > 0 ? "+" : "") + v.toFixed(2);
  const filter = h("select", { id: "filter", "aria-label": "Tone filter", onchange: e => { S.tone.filter = e.target.value; markFrameAdjusted(); syncControls(); scheduleLiveTone(); } },
    h("option", { value: "none" }, "No filter"), h("option", { value: "grayscale" }, "Black & white (plain grayscale)"), h("option", { value: "silver" }, "Silver B&W film (grain, film curve)"), h("option", { value: "sepia" }, "Sepia"));
  const wbsel = h("select", { id: "wbsel", "aria-label": "White balance", onchange: e => { S.wbSel = e.target.value; S.wb = S.wbSel === "as-shot" ? "as-shot" : "daylight"; markFrameAdjusted(); renderWb(); schedulePreview(true); } });
  const file = h("input", { type: "file", id: "wbfile", multiple: true, hidden: true, accept: ".json,.csv,.xmp,.lrtemplate,.pp3", onchange: wbImport });
  return h("div", { class: "adjust" },
    h("h3", { style: "font-size:.95rem;margin:0 0 .6rem" }, "Adjustments ", h("small", { class: "dim" }, "· real-time in preview and kept in every full render")),
    h("div", { class: "row3" },
      slider("sl_bright", "Brightness (exposure, stops)", -3, 3, 0.05, () => S.tone.brightness, v => { S.tone.brightness = v; markFrameAdjusted(); }, sg, 0, "Exposure compensation in stops.", true),
      slider("sl_contrast", "Contrast", -1, 1, 0.01, () => S.tone.contrast, v => { S.tone.contrast = v; markFrameAdjusted(); }, v => Math.round(v * 100) + "%", 0, "S-curve around the mid-tones.", true),
      slider("sl_develop", "Development strength", 0, 1, 0.01, () => S.tone.develop, v => { S.tone.develop = v; markFrameAdjusted(); }, v => Math.round(v * 100) + "%", 1, "0 % = developed without film, 100 % = the full film look.", true)),
    h("div", { class: "grid2", style: "margin-top:.8rem" },
      h("div", {}, h("label", { for: "filter" }, "Filter"), filter,
        h("div", { style: "margin-top:.4rem" }, slider("filterstr", "Filter strength", 0, 1, 0.01, () => S.tone.filterStrength, v => { S.tone.filterStrength = v; markFrameAdjusted(); }, v => Math.round(v * 100) + "%", 1, "Filter blend strength.", true))),
      h("div", {}, h("label", { for: "wbsel" }, "White balance"), wbsel,
        h("div", { class: "bar", style: "margin-top:.4rem" }, h("button", { onclick: () => $("#wbfile").click(), title: "Import .json .csv .xmp .lrtemplate .pp3" }, "Import profile…"),
          h("button", { id: "wbdel", hidden: true, onclick: wbDelete }, "Delete imported"), file),
        h("div", { id: "wbcustom", hidden: true, style: "margin-top:.4rem" },
          slider("sl_kelvin", "Light colour temperature", 2000, 12000, 50, () => S.wbCustom.k, v => { S.wbCustom.k = v; markFrameAdjusted(); }, v => v + " K", 5500),
          slider("sl_tint", "Tint (− green · + magenta)", -100, 100, 1, () => S.wbCustom.t, v => { S.wbCustom.t = v; markFrameAdjusted(); }, v => (v > 0 ? "+" : "") + v, 0)),
        h("p", { class: "dim", id: "wbnote", style: "font:.68rem var(--mono);margin:.3rem 0 0" }))),
    h("div", { class: "bar" },
      h("button", { onclick: resetAdjust, title: "Reset adjustments for this frame back to preset/defaults" }, "Reset adjustments"),
      h("button", { onclick: adjustAll, title: "Apply adjustments of this frame to all selected frames" }, "Apply to all selected"),
      h("button", { onclick: everythingOff, title: "Neutral look, no optics, no film, no filter, no adjustments: the plain developed RAW" }, "Everything off")));
}
function renderWb() {
  const sel = $("#wbsel"); if (!sel) return;
  const L = S.wbl || { builtin: [], imported: [] }, groups = {};
  L.builtin.forEach(p => (groups[p.group] = groups[p.group] || []).push(p));
  sel.replaceChildren(h("option", { value: "daylight" }, "Daylight (M-Film default, decoder)"), h("option", { value: "as-shot" }, "As shot (camera)"), h("option", { value: "custom" }, "Custom Kelvin / tint…"),
    ...(L.imported.length ? [h("optgroup", { label: "Imported" }, L.imported.map(p => h("option", { value: p.id }, `${p.name}${p.kelvin ? " · " + p.kelvin + " K" : ""}`)))] : []),
    ...Object.entries(groups).map(([g, ps]) => h("optgroup", { label: g }, ps.map(p => h("option", { value: p.id }, p.name)))));
  sel.value = S.wbSel;
  $("#wbcustom").hidden = S.wbSel !== "custom"; $("#wbdel").hidden = !S.wbSel.startsWith("user:");
  const p = [...L.builtin, ...L.imported].find(x => x.id === S.wbSel);
  $("#wbnote").textContent = p ? `${p.kelvin ? p.kelvin + " K" : "RGB gains"}${p.tint ? ", tint " + p.tint : ""} · gains ${p.gains.map(g => g.toFixed(2)).join(" / ")} · ${p.source}` : "";
}
async function wbImport(ev) {
  const files = [...ev.target.files]; ev.target.value = ""; let last = null, n = 0;
  for (const f of files) {
    try { const r = await api("/wb-profiles?filename=" + encodeURIComponent(f.name), { method: "POST", body: f, headers: { "Content-Type": "application/octet-stream" } }); n += r.added.length; last = r.added[0]; }
    catch (e) { toast(`${f.name}: ${e.message}`); }
  }
  if (n) { S.wbl = await api("/wb-profiles"); S.wbSel = last.id; S.wb = "daylight"; markFrameAdjusted(); renderWb(); schedulePreview(true); toast(`${n} white-balance profile(s) imported`); }
}
async function wbDelete() {
  const id = S.wbSel; if (!id.startsWith("user:")) return;
  try { await api("/wb-profiles/" + id, { method: "DELETE" }); S.wbl = await api("/wb-profiles"); S.wbSel = "daylight"; markFrameAdjusted(); renderWb(); schedulePreview(true); toast("Profile deleted (renders already made keep their own copy)"); } catch (e) { toast(e.message); }
}
function resetAdjust() {
  if (S.current) {
    delete S.adjustments[S.current];
    saveAdjustments();
  }
  loadFrameAdjustments(S.current);
  syncControls();
  renderAssets();
  schedulePreview(true);
}
function adjustAll() {
  const curAdj = {
    tone: { ...S.tone },
    wbSel: S.wbSel,
    wbCustom: { ...S.wbCustom }
  };
  [...S.selected].forEach(id => {
    S.adjustments[id] = JSON.parse(JSON.stringify(curAdj));
  });
  if (S.current) S.adjustments[S.current] = JSON.parse(JSON.stringify(curAdj));
  saveAdjustments();
  renderAssets();
  toast(`Adjustments copied to ${S.selected.size} selected frame(s)`);
}
function everythingOff() {
  S.look = "neutral"; S.fx.clear(); S.fxPreset = "none"; S.activePreset = null; S.policy = "film"; S.film = "none";
  Object.assign(S.baseTone, { brightness: 0, contrast: 0, develop: 1, filter: "none", filterStrength: 1 });
  S.baseWbSel = "daylight"; Object.assign(S.baseWbCustom, { k: 5500, t: 0 });
  resetAllFrameOverrides();
  loadFrameAdjustments(S.current);
  syncControls(); renderAssets(); schedulePreview(true); toast("All effects off: the plain developed RAW");
}
function previewPanel() {
  const treatedCanvas = h("canvas", { id: "pv_c", hidden: true, "aria-label": "Treated preview" });
  const treated = h("img", { alt: "Treated preview", id: "pv_t", hidden: true });
  const before = h("img", { alt: "Original, neutral development", id: "pv_b", hidden: true });
  const cut = h("div", { class: "cut", id: "cut", tabindex: "0", role: "slider", "aria-label": "Before / after", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": 50 });
  const stage = h("div", { class: "stage", id: "stage" }, h("div", { class: "layer" }, treatedCanvas, treated), h("div", { class: "layer", id: "beforeLayer" }, before), cut,
    h("div", { class: "layer", id: "cropLayer", hidden: true }), h("span", { class: "busy", id: "busy" }), h("span", { class: "dim", id: "empty" }, "Upload a RAW to see a preview"));
  let pos = 50;
  const setCut = p => { pos = Math.max(0, Math.min(100, p)); cut.style.left = pos + "%"; $("#beforeLayer").style.clipPath = `inset(0 ${100 - pos}% 0 0)`; cut.setAttribute("aria-valuenow", Math.round(pos)); };
  setTimeout(() => setCut(50));
  const move = ev => { const r = stage.getBoundingClientRect(); setCut(100 * (ev.clientX - r.left) / r.width); };
  cut.addEventListener("pointerdown", e => { cut.setPointerCapture(e.pointerId); cut.addEventListener("pointermove", move); });
  cut.addEventListener("pointerup", () => cut.removeEventListener("pointermove", move));
  cut.addEventListener("keydown", e => { if (e.key === "ArrowLeft") setCut(pos - 3); if (e.key === "ArrowRight") setCut(pos + 3); });
  const rotGroup = h("span", { class: "rot-group", role: "group", "aria-label": "Rotate photograph" },
    h("button", { type: "button", id: "rot_ccw", onclick: () => stepRotate(-90), title: "Rotate 90° counter-clockwise (left)" }, "↶ −90°"),
    h("button", { type: "button", id: "rot_cw", onclick: () => stepRotate(90), title: "Rotate 90° clockwise (right)" }, "↷ +90°"),
    h("select", { id: "rotpreset", "aria-label": "Rotation angle", title: "Select rotation angle", onchange: e => setRotate(Number(e.target.value), false) },
      h("option", { value: "0" }, "0° (upright)"),
      h("option", { value: "90" }, "90° ↷ (right)"),
      h("option", { value: "180" }, "180° (flip)"),
      h("option", { value: "-90" }, "−90° ↶ (270° left)")),
    h("input", { type: "number", id: "rotdeg", min: -180, max: 180, step: 0.5, value: 0, "aria-label": "Rotation angle in degrees",
      title: "Rotation angle in degrees (-180° to +180°)",
      oninput: e => setRotate(Number(e.target.value) || 0, true),
      onchange: e => setRotate(Number(e.target.value) || 0, false) }),
    h("span", { class: "dim", style: "font:.75rem var(--mono);padding-right:.2rem" }, "°"),
    h("button", { type: "button", id: "rotbtn", "aria-pressed": "false", onclick: toggleRotatePanel, title: "Open fine angle slider and rotation options" }, "⟳ Angle…"));
  const rotPanel = h("div", { id: "rotctl", class: "rot-panel", hidden: true },
    h("span", {}, "Rotate / Straighten ", h("b", { id: "rotval", class: "val" }, "0°")),
    h("button", { type: "button", onclick: () => stepRotate(-90), title: "Rotate 90° counter-clockwise" }, "↶ −90°"),
    h("button", { type: "button", onclick: () => nudgeRotate(-1), title: "Rotate 1° counter-clockwise" }, "−1°"),
    h("input", { type: "range", id: "rotslider", min: -45, max: 45, step: 0.1, value: 0, "aria-label": "Fine straighten angle (-45° to +45°)",
      title: "Fine straighten angle (-45° to +45°). Double-click resets fine angle.",
      oninput: e => setFineRotate(Number(e.target.value), true),
      onchange: e => setFineRotate(Number(e.target.value), false),
      ondblclick: () => setFineRotate(0, false) }),
    h("button", { type: "button", onclick: () => nudgeRotate(1), title: "Rotate 1° clockwise" }, "+1°"),
    h("button", { type: "button", onclick: () => stepRotate(90), title: "Rotate 90° clockwise" }, "↷ +90°"),
    h("button", { type: "button", onclick: () => setRotate(180, false), title: "Rotate 180°" }, "180°"),
    h("button", { type: "button", onclick: () => setRotate(0, false), title: "Reset rotation to 0°" }, "Reset 0°"),
    h("button", { type: "button", onclick: rotateAll, title: "Apply this rotation angle to all selected frames" }, "Apply to all selected"));
  return h("div", {}, h("div", { class: "bar", style: "margin:0 0 .6rem" },
    h("label", { for: "pvsize", style: "margin:0" }, "Preview size"), h("select", { id: "pvsize", style: "width:auto", onchange: () => schedulePreview(true) },
      h("option", { value: 1280 }, "1280 px (default)"), h("option", { value: 720 }, "720 px"), h("option", { value: 2048 }, "2048 px")),
    h("button", { onclick: () => schedulePreview(true) }, "Refresh preview"),
    rotGroup,
    h("button", { id: "cropbtn", "aria-pressed": "false", onclick: toggleCrop, title: "Frame this photograph" }, "✂ Crop"),
    h("span", { id: "cropctl", hidden: true, class: "bar", style: "margin:0;gap:.4rem" },
      h("select", { id: "aspect", "aria-label": "Crop proportions", style: "width:auto", onchange: e => { S.aspect = e.target.value; refit(); } },
        ["free", "original", "1:1", "5:4", "4:5", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"].map(a => h("option", { value: a }, a === "free" ? "Free" : a === "original" ? "Original ratio" : a))),
      h("button", { onclick: flipCrop, title: "Swap landscape / portrait crop ratio" }, "⇄ Swap ratio"), h("button", { class: "primary", onclick: () => endCrop(true) }, "Done"),
      h("button", { onclick: () => endCrop(false) }, "Cancel"), h("button", { onclick: resetCrop }, "Reset"),
      h("button", { onclick: cropAll, title: "Give every selected frame this framing" }, "Apply to all selected")),
    h("span", { class: "dim", id: "wipelabel" }, "left of the line: original (neutral) · right: treated")),
    rotPanel,
    stage, h("div", { class: "pvinfo", id: "pvinfo" }, "Previews are real renders at reduced size and are not export quality."));
}

function rotateCropBox90(r, kCw) {
  const k = ((kCw % 4) + 4) % 4;
  if (!r || k === 0) return r;
  if (k === 1) return clampRect({ x: +(1 - r.y - r.h).toFixed(4), y: +r.x.toFixed(4), w: +r.h.toFixed(4), h: +r.w.toFixed(4) });
  if (k === 2) return clampRect({ x: +(1 - r.x - r.w).toFixed(4), y: +(1 - r.y - r.h).toFixed(4), w: +r.w.toFixed(4), h: +r.h.toFixed(4) });
  return clampRect({ x: +r.y.toFixed(4), y: +(1 - r.x - r.w).toFixed(4), w: +r.h.toFixed(4), h: +r.w.toFixed(4) });
}
function toggleRotatePanel() {
  S.rotOpen = !S.rotOpen;
  const p = $("#rotctl"), b = $("#rotbtn");
  if (p) p.hidden = !S.rotOpen;
  if (b) b.setAttribute("aria-pressed", String(S.rotOpen));
  syncRotateUi();
}
function syncRotateUi() {
  const rot = curRotate();
  const q = Math.round(rot / 90) * 90;
  const rem = +(rot - q).toFixed(2);
  const sel = $("#rotpreset"), deg = $("#rotdeg"), sl = $("#rotslider"), val = $("#rotval"), btn = $("#rotbtn");
  if (sel) {
    const std = ["0", "90", "180", "-90"];
    const sVal = String(rot);
    let customOpt = sel.querySelector("option[data-custom='1']");
    if (std.includes(sVal)) {
      if (customOpt) customOpt.remove();
      sel.value = sVal;
    } else {
      if (!customOpt) { customOpt = h("option", { "data-custom": "1" }); sel.append(customOpt); }
      customOpt.value = sVal;
      customOpt.textContent = `${rot > 0 ? "+" : ""}${rot}° (custom)`;
      sel.value = sVal;
    }
  }
  if (deg && document.activeElement !== deg) deg.value = rot;
  if (sl) sl.value = Math.max(-45, Math.min(45, rem));
  if (val) val.textContent = `${rot > 0 ? "+" : ""}${rot}°`;
  if (btn) btn.textContent = rot ? `⟳ ${rot > 0 ? "+" : ""}${rot}°` : "⟳ Angle…";
}
function setRotate(deg, liveOnly = false) {
  if (!S.current) { toast("Choose a frame first"); return; }
  const prev = curRotate();
  const next = normDeg(deg);
  const delta = normDeg(next - prev);
  if (next === 0) delete S.rotates[S.current];
  else S.rotates[S.current] = next;
  if (delta !== 0 && Math.abs(delta % 90) < 0.01) {
    const kCw = Math.round(delta / 90);
    if (S.crops[S.current]) { S.crops[S.current] = rotateCropBox90(S.crops[S.current], kCw); saveCrops(); }
    if (S.cropRect) S.cropRect = rotateCropBox90(S.cropRect, kCw);
  }
  saveRotates();
  syncRotateUi();
  renderAssets();
  scheduleLiveTone();
  if (S.cropMode) {
    if (!liveOnly) startCrop();
  } else {
    schedulePreview(!liveOnly && Math.abs(delta % 90) < 0.01);
  }
}
function stepRotate(stepDeg) {
  if (!S.current) return toast("Choose a frame first");
  setRotate(curRotate() + stepDeg, false);
}
function nudgeRotate(stepDeg) {
  if (!S.current) return toast("Choose a frame first");
  setRotate(curRotate() + stepDeg, false);
}
function setFineRotate(fineDeg, liveOnly = false) {
  if (!S.current) return toast("Choose a frame first");
  const cur = curRotate();
  const q = Math.round(cur / 90) * 90;
  setRotate(q + Number(fineDeg || 0), liveOnly);
}
function rotateAll() {
  if (!S.current) return toast("Choose a frame first");
  const r = curRotate();
  const targets = S.selected.size ? [...S.selected] : [S.current];
  targets.forEach(id => {
    if (r === 0) delete S.rotates[id];
    else S.rotates[id] = r;
  });
  saveRotates();
  renderAssets();
  toast(`Rotation ${r > 0 ? "+" : ""}${r}° set on ${targets.length} frame(s)`);
}

function schedulePreview(now) {
  const c = $("#pv_c"); if (!c) return;
  clearTimeout(pvTimer);
  pvTimer = setTimeout(runPreview, now ? 0 : 200);
}
function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = url;
  });
}
async function fetchPreviewPixels(rec, edge, stream) {
  const p = await api("/previews", { method: "POST", json: { asset_id: S.current, recipe: rec, max_edge: edge, stream } });
  const st = await pollPreview(p.preview_id);
  if (st.status !== "DONE") return null;
  const u = await imgUrl(p.preview_id);
  const img = await loadImage(u);
  return extractPixels(img).data;
}
async function runPreview() {
  if (!S.current) { $("#empty").hidden = false; return; }
  if (S.cropMode) return;                                  // the cropper shows the whole frame, not a render
  const seq = ++pvSeq, edge = Number($("#pvsize").value), busy = $("#busy");
  const snapFxStrength = S.fxStrength, snapLookStrength = S.strength, snapRotate = curRotate();
  const hasFx = S.fxPreset !== "none" || S.fx.size > 0;
  const hasLook = S.look !== "neutral";
  const needsSeparateNeutral = S.film !== "none" && (hasLook || hasFx || wbExt() !== null);
  busy.textContent = "rendering…"; $("#empty").hidden = true;
  try {
    const reqs = [
      api("/previews", { method: "POST", json: { asset_id: S.current, recipe: baseRecipe(), max_edge: edge, stream: "main" } }),
      api("/previews", { method: "POST", json: { asset_id: S.current, kind: "before", max_edge: edge, stream: "main", white_balance: S.wb,
        ...(S.crops[S.current] ? { crop: S.crops[S.current] } : {}),
        ...(snapRotate ? { rotate: snapRotate } : {}) } })
    ];
    if (needsSeparateNeutral) {
      reqs.push(api("/previews", { method: "POST", json: { asset_id: S.current, recipe: baseRecipe({ noFilm: true }), max_edge: edge, stream: "main-nofilm" } }));
    }
    const [pt, pb, pn] = await Promise.all(reqs);
    const [st, sb, sn] = await Promise.all([
      pollPreview(pt.preview_id),
      pollPreview(pb.preview_id),
      pn ? pollPreview(pn.preview_id) : Promise.resolve(null)
    ]);
    if (seq !== pvSeq) return;                         // a newer edit superseded this one: never show it as current
    if (st.status !== "DONE") { busy.textContent = ""; $("#pvinfo").textContent = `Preview failed: ${st.error_code || st.status} ${st.detail || ""}`; return; }
    const [u1, u2, u3] = await Promise.all([
      imgUrl(pt.preview_id),
      sb.status === "DONE" ? imgUrl(pb.preview_id) : null,
      sn && sn.status === "DONE" ? imgUrl(pn.preview_id) : null
    ]);
    if (seq !== pvSeq) return;
    const [imgT, imgB, imgN] = await Promise.all([
      loadImage(u1),
      u2 ? loadImage(u2) : Promise.resolve(null),
      u3 ? loadImage(u3) : Promise.resolve(null)
    ]);
    if (seq !== pvSeq) return;
    const t = $("#pv_t"), b = $("#pv_b"), c = $("#pv_c");
    const fData = extractPixels(imgT);
    const bData = imgB ? extractPixels(imgB) : null;
    const nData = imgN ? extractPixels(imgN) : bData;
    pvState.w = imgT.naturalWidth; pvState.h = imgT.naturalHeight;
    pvState.filmImageData = fData; pvState.filmPx = fData.data;
    pvState.neutralPx = nData ? nData.data : null;
    pvState.baseFxStrength = hasFx ? snapFxStrength : 0;
    pvState.baseLookStrength = hasLook ? snapLookStrength : 1;
    pvState.baseRotate = snapRotate;
    if (!hasFx) pvState.noFxPx = fData.data;
    if (!hasLook) pvState.noLookPx = fData.data;
    pvState.meta = { hash: pt.recipe_hash, width: st.width, height: st.height, elapsed_s: st.elapsed_s, cached: st.cached };

    $("#stage").style.height = "";
    t.src = u1; t.hidden = true;
    c.hidden = false;
    renderLiveTone();
    fitStage(c);
    if (u2) { b.style.transform = ""; b.src = u2; b.hidden = false; }
    busy.textContent = "";

    /* Pre-warm reference baselines for real-time slider interpolation of Effects strength & Look intensity */
    if (hasFx && snapFxStrength > 0) {
      fetchPreviewPixels(baseRecipe({ noFx: true }), edge, "bg-nofx").then(px => {
        if (seq === pvSeq && px) { pvState.noFxPx = px; scheduleLiveTone(); }
      }).catch(() => {});
    }
    if (hasLook && snapLookStrength > 0) {
      fetchPreviewPixels(baseRecipe({ noLook: true }), edge, "bg-nolook").then(px => {
        if (seq === pvSeq && px) { pvState.noLookPx = px; scheduleLiveTone(); }
      }).catch(() => {});
    }
  } catch (e) { if (seq === pvSeq) { busy.textContent = ""; $("#pvinfo").textContent = "Preview: " + e.message; } }
}

/* The stage must be as tall as the picture in it (the layers are absolutely positioned, so they cannot size it). */
function fitStage(el) {
  const st = $("#stage"); if (!st || !el) return;
  requestAnimationFrame(() => { const h = el.getBoundingClientRect().height; if (h > 40) st.style.height = Math.round(h + (S.cropMode ? 24 : 0)) + "px"; });
}
window.addEventListener("resize", () => {
  const c = $("#pv_c");
  const i = S.cropMode ? S.cropImg : (c && !c.hidden ? c : $("#pv_t"));
  if (i && (i.tagName === "CANVAS" || i.getAttribute("src"))) { $("#stage").style.height = ""; fitStage(i); }
});

/* ---------------- crop tool ----------------
   The rectangle is kept in normalized coordinates of the upright frame, the same numbers the server uses for the
   preview and the full-size render. While cropping, the stage shows the whole uncropped frame. */
const ASPECT = { "1:1": 1, "5:4": 5 / 4, "4:5": 4 / 5, "4:3": 4 / 3, "3:4": 3 / 4, "3:2": 3 / 2, "2:3": 2 / 3, "16:9": 16 / 9, "9:16": 9 / 16 };
const MINC = 0.04;
function pxRatio() {                         // crop width/height in PIXELS the lock asks for, or null for free
  if (S.aspect === "free") return null;
  const i = S.cropImg; if (!i || !i.naturalWidth) return null;
  return S.aspect === "original" ? i.naturalWidth / i.naturalHeight : ASPECT[S.aspect];
}
function normRatio() { const a = pxRatio(), i = S.cropImg; return a ? a * i.naturalHeight / i.naturalWidth : null; }   // w_n / h_n
function clampRect(r) {
  r.w = Math.min(Math.max(r.w, MINC), 1); r.h = Math.min(Math.max(r.h, MINC), 1);
  r.x = Math.min(Math.max(r.x, 0), 1 - r.w); r.y = Math.min(Math.max(r.y, 0), 1 - r.h); return r;
}
function fitRatio(r, nr, anchor = "center") {   // largest rectangle of ratio nr inside r
  let w = r.w, h = r.h;
  if (w / h > nr) w = h * nr; else h = w / nr;
  const out = anchor === "center" ? { x: r.x + (r.w - w) / 2, y: r.y + (r.h - h) / 2, w, h } : { x: r.x, y: r.y, w, h };
  return clampRect(out);
}
function refit() { const nr = normRatio(); if (nr && S.cropRect) S.cropRect = fitRatio(S.cropRect, nr); drawCrop(); }
function flipCrop() {
  const m = { "4:3": "3:4", "3:4": "4:3", "3:2": "2:3", "2:3": "3:2", "16:9": "9:16", "9:16": "16:9", "5:4": "4:5", "4:5": "5:4" };
  if (m[S.aspect]) { S.aspect = m[S.aspect]; $("#aspect").value = S.aspect; refit(); }
}
async function toggleCrop() { S.cropMode ? endCrop(false) : startCrop(); }
async function startCrop() {
  if (!S.current) return toast("Choose a frame first");
  S.cropMode = true; $("#cropbtn").setAttribute("aria-pressed", "true"); $("#cropctl").hidden = false;
  const stage = $("#stage"), lay = $("#cropLayer");
  stage.querySelectorAll(".layer:not(#cropLayer), .cut").forEach(e => { e.style.visibility = "hidden"; });
  lay.hidden = false; lay.replaceChildren(h("span", { class: "dim" }, "loading the whole frame…")); $("#busy").textContent = "";
  try {
    const edge = Math.max(Number($("#pvsize").value), 1280);
    const rot = curRotate();
    const p = await api("/previews", { method: "POST", json: { asset_id: S.current, kind: "before", max_edge: Math.min(edge, 2048), stream: "crop", white_balance: S.wb, ...(rot ? { rotate: rot } : {}) } });
    const st = await pollPreview(p.preview_id);
    if (st.status !== "DONE") throw new Error(st.error_code || st.status);
    const url = await imgUrl(p.preview_id); if (!S.cropMode) return;
    const img = h("img", { alt: "Whole frame, for cropping", draggable: "false" }); img.onload = () => { fitStage(img); S.cropRect = S.crops[S.current] ? { ...S.crops[S.current] } : { x: 0.05, y: 0.05, w: 0.9, h: 0.9 }; refit(); drawCrop(); };
    S.cropImg = img; img.src = url;
    const box = h("div", { class: "cropbox", id: "cropbox", tabindex: "0", role: "group", "aria-label": "Crop rectangle. Shift+drag: resize symmetrically from center. Arrow keys move it, Shift+arrows resize it." },
      ["nw", "n", "ne", "e", "se", "s", "sw", "w"].map(d => h("i", { class: "hd hd-" + d, "data-h": d })));
    lay.replaceChildren(h("div", { class: "cropwrap", id: "cropwrap" }, img, box));
    wireCrop(box);
  } catch (e) { toast("Crop: " + e.message); endCrop(false); }
}
function endCrop(apply) {
  if (!S.cropMode) return;
  if (apply && S.cropRect) {
    const r = S.cropRect, full = r.x < 0.001 && r.y < 0.001 && r.w > 0.998 && r.h > 0.998;
    if (full) delete S.crops[S.current]; else S.crops[S.current] = { x: +r.x.toFixed(4), y: +r.y.toFixed(4), w: +r.w.toFixed(4), h: +r.h.toFixed(4) };
    saveCrops();
  }
  S.cropMode = false; S.cropRect = null; $("#cropbtn").setAttribute("aria-pressed", "false"); $("#cropctl").hidden = true;
  const lay = $("#cropLayer"); lay.hidden = true; lay.replaceChildren();
  $("#stage").querySelectorAll(".layer:not(#cropLayer), .cut").forEach(e => { e.style.visibility = ""; });
  resetPvState();
  ["#pv_t", "#pv_b"].forEach(q => { const i = $(q); i.removeAttribute("src"); i.hidden = true; });
  const c = $("#pv_c"); if (c) c.hidden = true;
  renderAssets(); schedulePreview(true);
}
function saveCrops() { try { localStorage.setItem("mfilm.crops", JSON.stringify(S.crops)); } catch (e) { /* private mode: crops last for this page only */ } }
function resetCrop() { S.cropRect = { x: 0, y: 0, w: 1, h: 1 }; S.aspect = "free"; $("#aspect").value = "free"; drawCrop(); }
function cropAll() {
  const r = S.cropRect; if (!r) return;
  const c = { x: +r.x.toFixed(4), y: +r.y.toFixed(4), w: +r.w.toFixed(4), h: +r.h.toFixed(4) };
  [...S.selected].forEach(id => { S.crops[id] = { ...c }; }); S.crops[S.current] = { ...c }; saveCrops();
  toast(`Framing set on ${S.selected.size} selected frame(s). Same fractions of each frame, so frames of other proportions are cropped accordingly.`);
}
function drawCrop() {
  const box = $("#cropbox"), r = S.cropRect; if (!box || !r) return;
  Object.assign(box.style, { left: r.x * 100 + "%", top: r.y * 100 + "%", width: r.w * 100 + "%", height: r.h * 100 + "%" });
  const i = S.cropImg; const px = i && i.naturalWidth ? `${Math.round(r.w * i.naturalWidth)}×${Math.round(r.h * i.naturalHeight)} of the preview` : "";
  $("#pvinfo").textContent = `Crop ${(r.w * 100).toFixed(1)}% × ${(r.h * 100).toFixed(1)}% of the frame, ${px}. The full-size render keeps the matching native pixels.`;
}
function wireCrop(box) {
  let drag = null;
  const wrap = () => $("#cropwrap").getBoundingClientRect();
  box.addEventListener("pointerdown", e => {
    const hd = e.target.dataset.h || "move"; const w = wrap();
    drag = { hd, sx: e.clientX, sy: e.clientY, r: { ...S.cropRect }, w }; box.setPointerCapture(e.pointerId); e.preventDefault();
  });
  box.addEventListener("pointermove", e => {
    if (!drag) return;
    const dx = (e.clientX - drag.sx) / drag.w.width, dy = (e.clientY - drag.sy) / drag.w.height, o = drag.r, hd = drag.hd, nr = normRatio();
    let x0 = o.x, y0 = o.y, x1 = o.x + o.w, y1 = o.y + o.h;
    if (hd === "move") {
      const w = o.w, h = o.h;
      x0 = Math.min(Math.max(o.x + dx, 0), 1 - w);
      y0 = Math.min(Math.max(o.y + dy, 0), 1 - h);
      x1 = x0 + w;
      y1 = y0 + h;
    } else if (e.shiftKey) {
      // Симметричное масштабирование относительно центра рамки
      const cx = o.x + o.w / 2, cy = o.y + o.h / 2;
      let hw = o.w / 2, hh = o.h / 2;
      const hasE = hd.includes("e"), hasW = hd.includes("w");
      const hasS = hd.includes("s"), hasN = hd.includes("n");

      if (hasE) hw += dx;
      else if (hasW) hw -= dx;

      if (hasS) hh += dy;
      else if (hasN) hh -= dy;

      hw = Math.max(MINC / 2, hw);
      hh = Math.max(MINC / 2, hh);

      if (nr) {
        if (hasE || hasW) {
          if (hasS || hasN) {
            if (hw / hh > nr) hh = hw / nr;
            else hw = hh * nr;
          } else {
            hh = hw / nr;
          }
        } else if (hasS || hasN) {
          hw = hh * nr;
        }
      }

      const maxHw = Math.min(cx, 1 - cx);
      const maxHh = Math.min(cy, 1 - cy);
      let k = 1;
      if (hw > maxHw && maxHw > 0) k = Math.min(k, maxHw / hw);
      if (hh > maxHh && maxHh > 0) k = Math.min(k, maxHh / hh);
      hw = Math.max(MINC / 2, hw * k);
      hh = Math.max(MINC / 2, hh * k);

      x0 = cx - hw;
      x1 = cx + hw;
      y0 = cy - hh;
      y1 = cy + hh;
    } else {
      if (hd.includes("w")) x0 = Math.min(Math.max(o.x + dx, 0), x1 - MINC);
      if (hd.includes("e")) x1 = Math.max(Math.min(o.x + o.w + dx, 1), x0 + MINC);
      if (hd.includes("n")) y0 = Math.min(Math.max(o.y + dy, 0), y1 - MINC);
      if (hd.includes("s")) y1 = Math.max(Math.min(o.y + o.h + dy, 1), y0 + MINC);
      if (nr) {                                           // keep the chosen proportions, anchored at the opposite side
        let w = x1 - x0, h = y1 - y0;
        const horiz = hd === "e" || hd === "w", vert = hd === "n" || hd === "s";
        if (vert) w = h * nr; else if (horiz) h = w / nr; else if (w / h > nr) w = h * nr; else h = w / nr;
        const ax = hd.includes("w") ? x1 : hd.includes("e") ? x0 : (x0 + x1) / 2, ay = hd.includes("n") ? y1 : hd.includes("s") ? y0 : (y0 + y1) / 2;
        const maxW = hd.includes("w") ? ax : hd.includes("e") ? 1 - ax : 2 * Math.min(ax, 1 - ax), maxH = hd.includes("n") ? ay : hd.includes("s") ? 1 - ay : 2 * Math.min(ay, 1 - ay);
        const k = Math.min(1, maxW / w, maxH / h); w *= k; h *= k;
        x0 = hd.includes("w") ? ax - w : hd.includes("e") ? ax : ax - w / 2; y0 = hd.includes("n") ? ay - h : hd.includes("s") ? ay : ay - h / 2; x1 = x0 + w; y1 = y0 + h;
      }
    }
    S.cropRect = clampRect({ x: x0, y: y0, w: x1 - x0, h: y1 - y0 }); drawCrop();
  });
  box.addEventListener("pointerup", () => { drag = null; });
  box.addEventListener("keydown", e => {
    const st = 0.01, r = { ...S.cropRect };
    const dir = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!dir) return;
    e.preventDefault();
    if (e.shiftKey) {
      const nr = normRatio();
      const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
      let w = r.w + dir[0] * st * 2;
      let h = r.h + dir[1] * st * 2;
      w = Math.max(MINC, w);
      h = Math.max(MINC, h);
      if (nr) {
        if (dir[0] !== 0) h = w / nr;
        else if (dir[1] !== 0) w = h * nr;
      }
      const maxW = 2 * Math.min(cx, 1 - cx), maxH = 2 * Math.min(cy, 1 - cy);
      w = Math.min(w, maxW);
      h = Math.min(h, maxH);
      if (nr) {
        if (w / h > nr) w = h * nr;
        else h = w / nr;
      }
      S.cropRect = clampRect({ x: cx - w / 2, y: cy - h / 2, w, h });
    } else {
      r.x += dir[0] * st; r.y += dir[1] * st;
      S.cropRect = clampRect(r);
    }
    drawCrop();
  });
}

/* ---------------- develop + jobs ---------------- */
const OUTPUT_SIZES = [
  { val: "3000x2000", label: "3000 × 2000 (3:2)", w: 3000, h: 2000 },
  { val: "2000x1333", label: "2000 × 1333 (3:2)", w: 2000, h: 1333 },
  { val: "1600x1200", label: "1600 × 1200 (4:3)", w: 1600, h: 1200 },
  { val: "1200x800",  label: "1200 × 800 (3:2)",  w: 1200, h: 800 },
  { val: "",          label: "Original size",      w: 0,    h: 0 }
];

function getAssetEffectiveDimensions(a) {
  if (!a) return null;
  const m = a.meta || {};
  let w = m.width || 0;
  let h = m.height || 0;
  if (!w || !h) return null;
  const crop = S.crops[a.asset_id];
  if (crop && crop.w > 0 && crop.h > 0) {
    w = Math.round(w * crop.w);
    h = Math.round(h * crop.h);
  }
  const rot = S.rotates[a.asset_id] ? normDeg(S.rotates[a.asset_id]) : 0;
  if (rot === 90 || rot === 270) {
    const t = w; w = h; h = t;
  }
  return { w, h, maxEdge: Math.max(w, h), minEdge: Math.min(w, h) };
}

function checkAndFitOutputSize(requestedVal, showWarning = true) {
  if (!requestedVal) {
    S.width = 0; S.height = 0;
    const sel = $("#outsize");
    if (sel && sel.value !== "") sel.value = "";
    return "";
  }
  const [reqW, reqH] = requestedVal.split("x").map(Number);
  const reqMax = Math.max(reqW, reqH);
  const reqMin = Math.min(reqW, reqH);

  const targetAssets = S.selected.size ?
    [...S.selected].map(id => S.assets.find(a => a.asset_id === id)).filter(Boolean) :
    (S.current ? [S.assets.find(a => a.asset_id === S.current)].filter(Boolean) : []);

  let minMaxEdge = Infinity, minMinEdge = Infinity;
  for (const a of targetAssets) {
    const d = getAssetEffectiveDimensions(a);
    if (d) {
      if (d.maxEdge < minMaxEdge) minMaxEdge = d.maxEdge;
      if (d.minEdge < minMinEdge) minMinEdge = d.minEdge;
    }
  }

  if (minMaxEdge < Infinity && (reqMax > minMaxEdge || reqMin > minMinEdge)) {
    const reqIdx = OUTPUT_SIZES.findIndex(s => s.val === requestedVal);
    const searchSlice = reqIdx >= 0 ? OUTPUT_SIZES.slice(reqIdx + 1) : OUTPUT_SIZES;
    const fit = searchSlice.find(s => {
      if (!s.val) return true;
      const sMax = Math.max(s.w, s.h);
      const sMin = Math.min(s.w, s.h);
      return sMax <= minMaxEdge && sMin <= minMinEdge;
    }) || OUTPUT_SIZES[OUTPUT_SIZES.length - 1];

    const sel = $("#outsize");
    if (sel) sel.value = fit.val;
    [S.width, S.height] = fit.val ? fit.val.split("x").map(Number) : [0, 0];

    if (showWarning) {
      const origOpt = OUTPUT_SIZES.find(s => s.val === requestedVal);
      const origLabel = origOpt ? origOpt.label : `${reqW}×${reqH}`;
      const assetDesc = targetAssets.length > 1 ? "одного из выбранных кадров" : "кадра";
      toast(`⚠️ Размер ${origLabel} превышает разрешение ${assetDesc} (${minMaxEdge}×${minMinEdge}). Автоматически выбран: ${fit.label}.`);
    }
    return fit.val;
  }

  [S.width, S.height] = [reqW, reqH];
  const sel = $("#outsize");
  if (sel && sel.value !== requestedVal) sel.value = requestedVal;
  return requestedVal;
}

function developPanel() {
  const sizeSel = h("select", { id: "outsize", onchange: e => {
    const v = e.target.value;
    [S.width, S.height] = v ? v.split("x").map(Number) : [0, 0];
    schedulePreview();
  } },
    h("option", { value: "" }, "Original size"),
    h("option", { value: "3000x2000" }, "3000 × 2000 (3:2)"),
    h("option", { value: "2000x1333" }, "2000 × 1333 (3:2)"),
    h("option", { value: "1600x1200" }, "1600 × 1200 (4:3)"),
    h("option", { value: "1200x800" }, "1200 × 800 (3:2)"));
  return h("div", { style: "margin-top:1.4rem" }, h("h3", { style: "font-size:.95rem;margin:0 0 .6rem" }, "Develop (full size, from the original RAW)"),
    h("div", { class: "row3" }, h("div", {}, h("label", { for: "outsize" }, "Output size (never upscaled)"), sizeSel),
      h("div", {}, h("label", { for: "q" }, "JPEG quality"), h("input", { type: "number", id: "q", min: 1, max: 100, value: 92, onchange: e => { S.quality = Number(e.target.value); } })),
      h("div", {})),
    destPanel(),
    h("div", { class: "bar" }, h("button", { class: "primary", id: "develop", onclick: develop }, "Develop selected"), h("span", { class: "dim", id: "devinfo" })),
    h("h3", { style: "font-size:.95rem;margin:1.6rem 0 .6rem" }, "Jobs"), h("div", { class: "jobs", id: "jobs" }),
    h("h3", { style: "font-size:.95rem;margin:1.6rem 0 .6rem" }, "History of renditions"),
    h("p", { class: "dim", style: "font:.72rem var(--mono)" }, "Every recipe gives its own file; nothing is overwritten. Publish uses the destination chosen above."),
    h("div", { class: "jobs", id: "history" }));
}
function updateDevelop() { const b = $("#develop"); if (!b) return; b.disabled = S.selected.size === 0; $("#devinfo").textContent = S.selected.size ? `${S.selected.size} frame(s) → ${S.selected.size} JPEG` : "select at least one frame"; }
function destPanel() {
  const mode = h("select", { id: "dest", onchange: () => { const on = $("#dest").value !== "none"; $("#destbox").hidden = !on; if (on) loadDestAlbums(); } },
    h("option", { value: "none" }, "Save on the server only (download later)"), h("option", { value: "pp" }, "Publish to PhotoPrism"));
  return h("div", { style: "margin-top:1rem" }, h("label", { for: "dest" }, "Destination (independent of where the sources came from)"), mode,
    h("div", { id: "destbox", hidden: true, class: "grid2", style: "margin-top:.7rem" },
      h("div", {}, h("label", { for: "dfolder" }, "Output folder under originals (blank = managed default)"), h("input", { type: "text", id: "dfolder", placeholder: "M-Film/Developed/<year>/<job>" })),
      h("div", {}, h("label", { for: "dalbum" }, "Album"), h("select", { id: "dalbum" }, h("option", { value: "" }, "No album")),
        h("input", { type: "text", id: "dnew", placeholder: "…or a new album name", style: "margin-top:.4rem" }))));
}
async function loadDestAlbums(force = false) {
  const sel = $("#dalbum"); if (!sel) return;
  if (!force && sel.dataset.loaded) return;
  try {
    const curVal = sel.value;
    const r = await api("/photoprism/default/albums?count=500");
    sel.dataset.loaded = "1";
    const firstOpt = sel.firstElementChild || h("option", { value: "" }, "— create new manual album below —");
    sel.replaceChildren(firstOpt);
    r.items.filter(a => a.manual).forEach(a => sel.append(h("option", { value: a.uid }, a.title)));
    if (curVal && sel.querySelector(`option[value="${curVal}"]`)) sel.value = curVal;
  }
  catch (e) { toast("Albums unavailable: " + e.message); }
}
function outputSpec() {
  const o = { format: "jpeg", quality: S.quality, publish: false };
  if ($("#dest") && $("#dest").value === "pp") {
    o.publish = true; const f = $("#dfolder").value.trim(), a = $("#dalbum").value, n = $("#dnew").value.trim();
    if (f) o.photoprism_folder = f; if (a && !n) o.photoprism_album_uid = a; if (n) o.create_album_name = n;
  }
  return o;
}
async function develop() {
  try {
    const assets = [...S.selected].map(id => S.assets.find(a => a.asset_id === id)).filter(Boolean);
    if (!assets.length) return toast("Select at least one frame to develop");
    const origins = new Set(assets.map(a => a.origin));
    if (origins.size > 1) return toast("Develop frames from one kind of source per job (uploads, PhotoPrism or a roll)");
    const o = [...origins][0];
    const source = o === "photoprism" ? { kind: S.ppSource && S.ppSource.kind === "album" ? "photoprism_album" : "photoprism_folder", ...(S.ppSource ? { source_uid: S.ppSource.uid } : {}) }
      : o === "camera_roll" ? { kind: "mfilm_roll", ...(S.ppSource ? { source_uid: S.ppSource.uid } : {}) } : { kind: "upload" };
    const assetsPayload = assets.map(a => {
      const { tone, wbSel, wbCustom, isAdjusted } = getFrameAdjustments(a.asset_id);
      const item = { asset_id: a.asset_id };
      if (S.crops[a.asset_id]) item.crop = S.crops[a.asset_id];
      if (S.rotates[a.asset_id] && normDeg(S.rotates[a.asset_id])) item.rotate = normDeg(S.rotates[a.asset_id]);
      if (isAdjusted) {
        const tn = frameToneExt(tone);
        if (Object.keys(tn).length) item.tone = tn;
        const wp = frameWbExt(wbSel, wbCustom);
        if (wp) item.wb_profile = wp;
        if (wbSel === "as-shot") item.white_balance = "as-shot";
      }
      return item;
    });
    const j = await api("/jobs", { method: "POST", json: { schema_version: 1, source: { ...source, assets: assetsPayload },
      recipe: baseJobRecipe(), output: outputSpec() } });
    toast(`Job queued (${j.total} frame${j.total === 1 ? "" : "s"})`); refreshJobs();
  } catch (e) { toast(e.message); }
}
let jobsTimer;
async function refreshJobs(force = false) {
  clearTimeout(jobsTimer);
  let list; try { list = await api("/jobs?count=15"); } catch (e) { return; }
  const full = await Promise.all(list.items.map(j => api("/jobs/" + j.job_id)));
  const box = $("#jobs"); if (!box) return;
  const typing = !force && document.activeElement && box.contains(document.activeElement) && document.activeElement.tagName === "INPUT";
  if (!typing) box.replaceChildren(...full.map(jobCard));
  refreshHistory();
  if (full.some(j => ["QUEUED", "RUNNING", "PUBLISHING"].includes(j.state))) jobsTimer = setTimeout(refreshJobs, 2500);
  else jobsTimer = setTimeout(refreshJobs, 15000);
}
async function refreshHistory() {
  const box = $("#history"); if (!box) return;
  let r; try { r = await api("/history?count=30"); } catch (e) { return; }
  box.replaceChildren(...(r.items.length ? r.items.map(x => h("div", { class: "job" }, h("header", {}, h("b", {}, x.filename), h("span", { class: "dim" },
      `${x.film} · ${x.camera_look} · ${x.optical} · ${x.width}×${x.height} · ${(x.bytes / 1048576).toFixed(1)} MB · ${x.created_at.slice(0, 16).replace("T", " ")}`)),
    h("div", { class: "acts" },
      h("button", { class: "session-load-btn", title: "Загрузить этот кадр и его рецепт в редактор", onclick: () => loadHistoryRender(x) }, "↺ Загрузить"),
      h("a", { class: "btn", href: `${API}/renders/${x.render_id}/file` }, "Download"),
      h("button", { onclick: async () => {
        const o = outputSpec(); if (!o.publish) return toast("Choose “Publish to PhotoPrism” in the destination above first");
        try { const j = await api(`/renders/${x.render_id}/publish`, { method: "POST", json: { photoprism_folder: o.photoprism_folder, photoprism_album_uid: o.photoprism_album_uid, create_album_name: o.create_album_name } });
          toast(j.created ? "Publishing…" : "Already queued or published"); refreshJobs(); } catch (e) { toast(e.message); } } }, "Publish")))) : [h("p", { class: "dim" }, "Nothing developed yet.")]));
}
const COLOR = { PUBLISHING: "var(--safe2)", COMPLETE: "var(--ok)", FAILED: "var(--bad)", PARTIAL: "var(--safe2)", RUNNING: "var(--safe)", QUEUED: "var(--dim)", CANCELLED: "var(--dim)" };
function jobCard(j) {
  const st = h("span", { class: "st", style: `color:${COLOR[j.state] || "inherit"}` }, j.state);
  const acts = h("div", { class: "acts" });
  acts.append(h("button", { class: "session-load-btn", title: "Загрузить сессию: восстановить кадры, рецепт, кадрирование и целевой альбом в редактор", onclick: () => loadSession(j) }, "↺ Загрузить сессию"));
  if (["QUEUED", "RUNNING"].includes(j.state)) acts.append(h("button", { onclick: async () => { await api(`/jobs/${j.job_id}/cancel`, { method: "POST" }); refreshJobs(); } }, "Cancel"));
  if (j.counts.FAILED || j.counts.CANCELLED) acts.append(h("button", { onclick: async () => { await api(`/jobs/${j.job_id}/retry`, { method: "POST" }); refreshJobs(); } }, "Retry failed / cancelled"));
  if (j.counts.COMPLETE) acts.append(h("a", { class: "btn", href: `${API}/jobs/${j.job_id}/zip`, download: "" }, `Download ZIP (${j.counts.COMPLETE})`));
  const albumBox = (j.counts.COMPLETE && (!j.publish || (!j.album_uid && j.state !== "PUBLISHING" && j.state !== "RUNNING"))) ? albumCreator(j) : null;
  const pubInfo = j.publish ? h("div", { class: "pubinfo" }, "→ PhotoPrism ",
    h("b", {}, j.publish.create_album_name ? `album “${j.publish.create_album_name}”` : j.publish.album_uid ? "existing album" : "folder only"),
    h("span", { class: "dim" }, ` · ${j.publish.folder}`),
    j.album_uid ? h("span", { class: "okc" }, " · album ✓")
      : (j.state === "FAILED" || (j.counts.FAILED && !j.counts.RUNNING && !j.counts.QUEUED && !j.counts.PUBLISHING))
        ? h("span", { class: "err", title: "Publication failed" }, " · album/publish failed ✗")
        : (j.counts.PUBLISHING || j.state === "PUBLISHING") ? h("span", { class: "dim" }, " · publishing…") : null) : null;
  return h("div", { class: "job" }, h("header", {}, st, h("b", {}, j.film), h("span", { class: "dim" }, `${j.camera_look} · recipe ${j.recipe_hash.slice(0, 10)} · ${j.created_at.slice(0, 19).replace("T", " ")}`)),
    pubInfo,
    h("div", { class: "items" }, j.items.map(i => h("div", {}, h("span", {}, i.filename, i.crop ? " ✂" : "", i.rotate ? ` ⟳${i.rotate}°` : "", (i.tone || i.wb_profile || i.white_balance) ? " 🎛" : ""),
      i.published_path ? h("span", { class: i.state === "COMPLETE" ? "okc" : "dim", title: i.publish_note || i.published_path }, i.state === "COMPLETE" ? "in PhotoPrism ✓" : i.state.toLowerCase()) : null,
      i.state === "FAILED" ? h("span", { class: "err", title: i.error_detail || i.publish_note || "" }, ` ✗ ${i.error_code || "failed"}${i.error_detail ? ": " + i.error_detail : ""}`) : null,
      i.render ? h("span", {},
        h("a", { href: `${API}/renders/${i.render.render_id}/file`, style: "color:var(--ok)" }, `${i.render.width}×${i.render.height} ↓`),
        i.warning ? h("span", { class: "warn", style: "color:var(--safe2);margin-left:.4rem;font-size:.68rem", title: i.warning }, ` ⚠ ${i.warning}`) : null)
        : (i.state !== "FAILED" ? h("span", { class: "dim", title: i.error_detail || "" }, i.state) : null)))), acts, albumBox);
}

async function loadSession(j) {
  try {
    if (!j) return;
    let job = j;
    if (!job.items || !job.recipe) {
      job = await api(`/jobs/${j.job_id}`);
    }
    const items = job.items || [];
    if (!items.length) {
      return toast("В этой сессии нет кадров");
    }

    // 1. Un-dismiss any asset in this session and reload assets
    items.forEach(it => S.dismissed.delete(it.asset_id));
    saveDismissed();
    await refreshAssets();

    // 2. Select session assets
    const itemAssetIds = new Set(items.map(it => it.asset_id));
    S.selected = new Set(S.assets.filter(a => itemAssetIds.has(a.asset_id)).map(a => a.asset_id));
    if (items.length) {
      const firstAvailable = items.find(it => S.assets.some(a => a.asset_id === it.asset_id));
      if (firstAvailable) S.current = firstAvailable.asset_id;
    }

    // 3. Restore base recipe
    const r = job.recipe || {};
    if (r.film) {
      S.film = r.film.id || "portra400";
      S.grain = Number(r.film.grain_scale !== undefined ? r.film.grain_scale : 1);
      S.halation = Number(r.film.halation_scale !== undefined ? r.film.halation_scale : 1);
      S.softness = Number(r.film.softness_scale !== undefined ? r.film.softness_scale : 1);
    }
    if (r.camera_look) {
      S.look = r.camera_look.id || "neutral";
      S.strength = Number(r.camera_look.strength !== undefined ? r.camera_look.strength : 1);
    }
    if (r.optical) {
      S.fxPreset = r.optical.preset_id || "none";
      S.fxStrength = Number(r.optical.strength !== undefined ? r.optical.strength : 0);
      S.policy = r.optical.halation_policy || "film";
      S.fx = new Set((r.optical.stack || []).map(x => x.id));
    }
    if (r.render) {
      S.quality = Number(r.render.quality || 92);
      S.width = Number(r.render.width || 0);
      S.height = Number(r.render.height || 0);
    }
    S.seed = r.seed || 0;
    S.activePreset = null;

    const ext = r.extensions || {};
    const tn = ext.tone || {};
    S.baseTone = {
      brightness: Number(tn.brightness_ev || 0),
      contrast: Number(tn.contrast || 0),
      develop: Number(tn.develop_strength !== undefined ? tn.develop_strength : 1),
      filter: tn.filter || "none",
      filterStrength: Number(tn.filter_strength !== undefined ? tn.filter_strength : 1)
    };
    if (ext.wb_profile) {
      S.baseWbSel = "custom";
      S.baseWbCustom = { k: ext.wb_profile.cct || 5500, t: ext.wb_profile.tint || 0 };
    } else {
      S.baseWbSel = ext.white_balance === "as-shot" ? "as-shot" : "daylight";
    }

    // 4. Restore per-frame overrides (crop, rotate, adjustments)
    items.forEach(it => {
      if (it.crop) S.crops[it.asset_id] = { ...it.crop };
      else delete S.crops[it.asset_id];

      if (it.rotate) S.rotates[it.asset_id] = normDeg(it.rotate);
      else delete S.rotates[it.asset_id];

      if (it.tone || it.wb_profile || it.white_balance) {
        const itemTone = it.tone || {};
        S.adjustments[it.asset_id] = {
          tone: {
            brightness: Number(itemTone.brightness_ev || 0),
            contrast: Number(itemTone.contrast || 0),
            develop: Number(itemTone.develop_strength !== undefined ? itemTone.develop_strength : 1),
            filter: itemTone.filter || "none",
            filterStrength: Number(itemTone.filter_strength !== undefined ? itemTone.filter_strength : 1)
          },
          wbSel: it.wb_profile ? "custom" : (it.white_balance === "as-shot" ? "as-shot" : "daylight"),
          wbCustom: it.wb_profile ? { k: it.wb_profile.cct || 5500, t: it.wb_profile.tint || 0 } : { ...S.baseWbCustom }
        };
      } else {
        delete S.adjustments[it.asset_id];
      }
    });
    saveCrops();
    saveRotates();
    saveAdjustments();

    // 5. Restore destination & PhotoPrism album
    const pub = job.publish;
    const albumUid = job.album_uid || (pub && pub.album_uid);
    const albumTitle = (pub && pub.create_album_name) || job.album_title || "";
    if (pub || albumUid) {
      if ($("#dest")) $("#dest").value = "pp";
      if ($("#destbox")) $("#destbox").hidden = false;
      if ($("#dfolder") && pub && pub.folder) $("#dfolder").value = pub.folder;
      await loadDestAlbums(true);
      const dalbum = $("#dalbum");
      if (dalbum) {
        const hasOption = albumUid && Boolean(dalbum.querySelector(`option[value="${albumUid}"]`));
        if (hasOption) {
          dalbum.value = albumUid;
          if ($("#dnew")) $("#dnew").value = "";
        } else {
          dalbum.value = "";
          if ($("#dnew")) $("#dnew").value = albumTitle;
          if (albumUid) {
            toast(albumTitle
              ? `Альбом «${albumTitle}» не найден в PhotoPrism (удалён) и будет создан заново.`
              : "Целевой альбом не найден в PhotoPrism и будет создан заново.");
          }
        }
      }
    } else {
      if ($("#dest")) $("#dest").value = "none";
      if ($("#destbox")) $("#destbox").hidden = true;
    }

    // 6. Update UI
    if ($("#outsize")) {
      const szVal = S.width && S.height ? `${S.width}x${S.height}` : "";
      $("#outsize").value = szVal;
    }
    if ($("#q")) $("#q").value = S.quality;
    loadFrameAdjustments(S.current);
    syncControls();
    renderAssets();
    updateDevelop();
    schedulePreview(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
    toast(`Сессия загружена: ${items.length} кадров, пленка ${S.film}`);
  } catch (e) {
    toast("Ошибка загрузки сессии: " + e.message);
  }
}

async function loadHistoryRender(x) {
  try {
    S.dismissed.delete(x.asset_id);
    saveDismissed();
    await refreshAssets();
    S.selected.add(x.asset_id);
    S.current = x.asset_id;
    if (x.film) S.film = x.film;
    if (x.camera_look) S.look = x.camera_look;
    if (x.crop) { S.crops[x.asset_id] = { ...x.crop }; saveCrops(); }
    loadFrameAdjustments(S.current);
    syncControls();
    renderAssets();
    updateDevelop();
    schedulePreview(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
    toast(`Кадр ${x.filename} загружен в редактор`);
  } catch (e) {
    toast("Ошибка загрузки: " + e.message);
  }
}
const albumNames = {};
function defaultAlbumName(j) {
  const f = S.catalog && S.catalog.films.find(x => x.id === j.film);
  return `${f ? f.name : j.film} · ${j.created_at.slice(0, 10)}`;
}
function albumCreator(j) {
  if (!(j.job_id in albumNames)) albumNames[j.job_id] = defaultAlbumName(j);
  const inp = h("input", { type: "text", maxlength: 200, value: albumNames[j.job_id], "aria-label": "New PhotoPrism album name",
    placeholder: "Album name", oninput: e => { albumNames[j.job_id] = e.target.value; },
    onkeydown: e => { if (e.key === "Enter") { e.preventDefault(); btn.click(); } } });
  const btn = h("button", { type: "button", class: "album-btn", title: "Copy the finished frames into PhotoPrism and collect them in a new album",
    onclick: async () => {
      const name = (albumNames[j.job_id] || "").trim();
      if (!name) { inp.focus(); return toast("Enter an album name"); }
      btn.disabled = true;
      try {
        const r = await api(`/jobs/${j.job_id}/publish`, { method: "POST", json: { create_album_name: name } });
        toast(r.created ? `Creating album “${name}” in PhotoPrism (${r.frames} frame(s))…` : `Album “${name}” is already being created for this job`);
        refreshJobs(true);
      } catch (e) { toast(e.message); btn.disabled = false; }
    } }, `★ Create album in PhotoPrism (${j.counts.COMPLETE})`);
  return h("div", { class: "album-create" }, h("label", {}, "Developed frames → new PhotoPrism album"), h("div", { class: "bar", style: "margin-top:.3rem" }, inp, btn));
}

/* Range sliders respond to mouse wheel scroll when hovered */
window.addEventListener("wheel", e => {
  const t = e.target;
  if (!t || t.tagName !== "INPUT" || t.type !== "range" || t.disabled) return;
  e.preventDefault();
  const min = t.min !== "" ? Number(t.min) : 0;
  const max = t.max !== "" ? Number(t.max) : 100;
  let step = t.step !== "" && t.step !== "any" ? Number(t.step) : 1;
  if (!step || step <= 0) step = 1;
  const cur = Number(t.value);
  const dir = (e.deltaY < 0 || e.deltaX < 0) ? 1 : -1;
  let next = cur + dir * step;
  const stepStr = String(step);
  const stepDec = stepStr.includes(".") ? stepStr.split(".")[1].length : 0;
  next = Number(next.toFixed(stepDec));
  next = Math.max(min, Math.min(max, next));
  if (next !== cur) {
    t.value = next;
    t.dispatchEvent(new Event("input", { bubbles: true }));
    t.dispatchEvent(new Event("change", { bubbles: true }));
  }
}, { passive: false });

boot();
