"use strict";
/* Chromurgy Web Darkroom UI. All text goes through textContent: file names and metadata are untrusted. */
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
  width: 0, height: 0, filmQuery: "", fxPreset: "none", fx: new Set(), fxStrength: 0.5, policy: "film", vpolicy: "film",
  activePreset: null, comboPreset: null, combos: [], comboSceneFilter: "", comboQuery: "", fxParams: {},
  baseTone: { brightness: 0, contrast: 0, develop: 1, filter: "none", filterStrength: 1 },
  baseWbSel: "daylight", baseWbCustom: { k: 5500, t: 0 },
  tone: { brightness: 0, contrast: 0, develop: 1, filter: "none", filterStrength: 1 }, wbSel: "daylight", wbCustom: { k: 5500, t: 0 }, wbl: null, sliders: [],
  adjustments: JSON.parse(localStorage.getItem("mfilm.adjustments") || "{}"),
  crops: JSON.parse(localStorage.getItem("mfilm.crops") || "{}"),
  rotates: JSON.parse(localStorage.getItem("mfilm.rotates") || "{}"), rotOpen: false,
  colorGrade: JSON.parse(localStorage.getItem("mfilm.color_grade") || '{"mode":"none"}'),
  colorGradeFilter: "",
  colorGradeQuery: "",
  frameGradeOverrides: JSON.parse(localStorage.getItem("mfilm.frame_grades") || "{}"),
  studioMode: localStorage.getItem("mfilm.studio_mode") || "classic",
  aiMode: localStorage.getItem("mfilm.ai_mode") || "pure",
  aiAutoEnhance: true,
  aiAutoEnhanceStrength: 1.0,
  aiAutoEnhanceStyle: "standard",
  aiStyleRef: false,
  aiStyleRefStrength: 0.8,
  aiStyleRefId: "warm_sunset",
  aiStyleRefName: "Warm Sunset",
  aiStyleRefThumb: "",
  aiStyleRefPreserveSkin: true,
  aiEngineEnabled: false,
  aiEngineType: "rawnind",
  aiChromaStrength: 0.6,
  aiLumaStrength: 0.3,
  aiDetailPreserve: 0.8,
  aiUpscaleScale: 2,
  aiUpscaleModel: "RealESRGAN_x2plus",
  autoAnalysis: {},
  aspect: "free", cropMode: false, cropRect: null, cropImg: null };
const STEPS = ["Material", "Camera look", "Film stock", "Optical effects", "Color grades", "My presets"];

function saveColorGrade() {
  try { localStorage.setItem("mfilm.color_grade", JSON.stringify(S.colorGrade)); } catch (e) {}
}
function saveFrameGrades() {
  try { localStorage.setItem("mfilm.frame_grades", JSON.stringify(S.frameGradeOverrides)); } catch (e) {}
}
function getEffectiveFrameGrade(id) {
  if (id && S.frameGradeOverrides && S.frameGradeOverrides[id]) {
    return { scope: "individual", ...S.frameGradeOverrides[id] };
  }
  return { scope: "inherited", ...(S.colorGrade || { mode: "none" }) };
}

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

const analysisPending = new Set();
async function ensureSourceAnalysis(asset) {
  if (!asset || !asset.asset_id || analysisPending.has(asset.asset_id)) return;
  const meta = asset.meta || {};
  if (meta.auto_exposure_ev !== undefined && meta.auto_wb && meta.auto_wb.kelvin) {
    if (!S.autoAnalysis[asset.asset_id]) {
      S.autoAnalysis[asset.asset_id] = {
        baseline_ev: meta.baseline_ev || 0.0,
        auto_exposure_ev: meta.auto_exposure_ev,
        auto_wb: meta.auto_wb,
        camera_wb: meta.camera_wb
      };
    }
    return;
  }
  analysisPending.add(asset.asset_id);
  try {
    const an = await api(`/sources/${asset.asset_id}/analysis`);
    if (an) {
      if (!asset.meta) asset.meta = {};
      asset.meta.baseline_ev = an.baseline_ev;
      asset.meta.auto_exposure_ev = an.auto_exposure_ev;
      asset.meta.camera_wb = an.camera_wb;
      asset.meta.auto_wb = an.auto_wb;
      S.autoAnalysis[asset.asset_id] = an;

      const curAdj = S.adjustments[asset.asset_id];
      let changed = false;
      if (curAdj && curAdj.autoExposure && Math.abs(curAdj.tone.brightness) < 1e-4) {
        curAdj.tone.brightness = an.auto_exposure_ev;
        changed = true;
      }
      if (curAdj && curAdj.autoWb && an.auto_wb && an.auto_wb.kelvin) {
        curAdj.wbSel = "custom";
        curAdj.wbCustom = { k: an.auto_wb.kelvin, t: an.auto_wb.tint };
        changed = true;
      }
      if (changed) saveAdjustments();

      if (S.current === asset.asset_id) {
        loadFrameAdjustments(S.current);
        syncControls();
        scheduleLiveTone();
      }
    }
  } catch (e) {
    console.warn("Analysis failed for asset", asset.asset_id, e);
  } finally {
    analysisPending.delete(asset.asset_id);
  }
}

function getFrameAutoExposureVal(id) {
  const asset = S.assets.find(a => a.asset_id === id);
  const meta = asset && asset.meta ? asset.meta : {};
  if (meta.auto_exposure_ev !== undefined) return meta.auto_exposure_ev;
  if (S.autoAnalysis[id] && S.autoAnalysis[id].auto_exposure_ev !== undefined) return S.autoAnalysis[id].auto_exposure_ev;
  return 0.0;
}

function getFrameAutoWbData(id) {
  const asset = S.assets.find(a => a.asset_id === id);
  const meta = asset && asset.meta ? asset.meta : {};
  if (meta.auto_wb && meta.auto_wb.kelvin) return meta.auto_wb;
  if (S.autoAnalysis[id] && S.autoAnalysis[id].auto_wb) return S.autoAnalysis[id].auto_wb;
  return { kelvin: 5500, tint: 0, gains: [1.0, 1.0, 1.0] };
}

function isFrameAutoExposure(id) {
  if (!id) return true;
  const adj = S.adjustments[id];
  if (adj && adj.autoExposure !== undefined) return Boolean(adj.autoExposure);
  return true;
}

function setFrameAutoExposure(id, val) {
  if (!id) return;
  if (!S.adjustments[id]) {
    S.adjustments[id] = {
      tone: { ...S.baseTone, brightness: getFrameAutoExposureVal(id) },
      wbSel: S.wbSel,
      wbCustom: { ...S.wbCustom },
      autoWb: isFrameAutoWb(id)
    };
  }
  S.adjustments[id].autoExposure = Boolean(val);
}

function isFrameAutoWb(id) {
  if (!id) return true;
  const adj = S.adjustments[id];
  if (adj && adj.autoWb !== undefined) return Boolean(adj.autoWb);
  return true;
}

function setFrameAutoWb(id, val) {
  if (!id) return;
  if (!S.adjustments[id]) {
    const awb = getFrameAutoWbData(id);
    S.adjustments[id] = {
      tone: { ...S.baseTone, brightness: getFrameAutoExposureVal(id) },
      autoExposure: isFrameAutoExposure(id),
      wbSel: awb && awb.kelvin ? "custom" : S.baseWbSel,
      wbCustom: awb && awb.kelvin ? { k: awb.kelvin, t: awb.tint } : { ...S.baseWbCustom }
    };
  }
  S.adjustments[id].autoWb = Boolean(val);
}

function initAssetAutoAdjustments(a) {
  const meta = a.meta || {};
  const autoEv = (meta.auto_exposure_ev !== undefined) ? meta.auto_exposure_ev : 0.0;
  const hasAutoWb = Boolean(meta.auto_wb && meta.auto_wb.kelvin);
  const autoK = hasAutoWb ? meta.auto_wb.kelvin : 5500;
  const autoT = hasAutoWb ? meta.auto_wb.tint : 0;
  S.adjustments[a.asset_id] = {
    tone: { ...S.baseTone, brightness: autoEv },
    wbSel: hasAutoWb ? "custom" : S.baseWbSel,
    wbCustom: { ...S.baseWbCustom, k: autoK, t: autoT },
    autoExposure: true,
    autoWb: hasAutoWb,
    rawBaselineEv: meta.baseline_ev || 0.0
  };
}

function loadFrameAdjustments(id) {
  if (!id) return;
  const asset = S.assets.find(a => a.asset_id === id);
  if (asset) ensureSourceAnalysis(asset);

  const adj = S.adjustments[id];
  if (adj && adj.tone) {
    Object.assign(S.tone, S.baseTone, adj.tone);
  } else {
    const autoEv = getFrameAutoExposureVal(id);
    Object.assign(S.tone, S.baseTone, { brightness: autoEv });
  }

  if (adj && adj.wbSel !== undefined) {
    S.wbSel = adj.wbSel;
  } else {
    const autoWb = getFrameAutoWbData(id);
    if (autoWb && autoWb.kelvin && isFrameAutoWb(id)) {
      S.wbSel = "custom";
    } else {
      S.wbSel = S.baseWbSel;
    }
  }
  S.wb = S.wbSel === "as-shot" ? "as-shot" : "daylight";

  if (adj && adj.wbCustom) {
    Object.assign(S.wbCustom, S.baseWbCustom, adj.wbCustom);
  } else {
    const autoWb = getFrameAutoWbData(id);
    if (autoWb && autoWb.kelvin && isFrameAutoWb(id)) {
      Object.assign(S.wbCustom, S.baseWbCustom, { k: autoWb.kelvin, t: autoWb.tint });
    } else {
      Object.assign(S.wbCustom, S.baseWbCustom);
    }
  }

  const chkExp = $("#chk_auto_exposure");
  if (chkExp) chkExp.checked = isFrameAutoExposure(id);
  const chkWb = $("#chk_auto_wb");
  if (chkWb) chkWb.checked = isFrameAutoWb(id);

  const rawBadge = $("#badge_raw_ev");
  if (rawBadge && asset && asset.meta) {
    const meta = asset.meta;
    const parts = [];
    if (meta.baseline_ev !== undefined && Math.abs(meta.baseline_ev) > 1e-4) {
      parts.push(`RAW: ${(meta.baseline_ev > 0 ? "+" : "") + meta.baseline_ev.toFixed(2)} EV`);
    }
    if (meta.iso) parts.push(`ISO ${meta.iso}`);
    rawBadge.textContent = parts.length ? `(${parts.join(" · ")})` : "";
  }
  updateFrameNavUi();
}

function markFrameAdjusted() {
  if (!S.current) return;
  const autoExp = isFrameAutoExposure(S.current);
  const autoWb = isFrameAutoWb(S.current);
  const toneDiff = Math.abs(S.tone.brightness - S.baseTone.brightness) > 1e-4 ||
                   Math.abs(S.tone.contrast - S.baseTone.contrast) > 1e-4 ||
                   Math.abs(S.tone.develop - S.baseTone.develop) > 1e-4 ||
                   S.tone.filter !== S.baseTone.filter ||
                   Math.abs(S.tone.filterStrength - S.baseTone.filterStrength) > 1e-4;
  const wbDiff = S.wbSel !== S.baseWbSel ||
                 (S.wbSel === "custom" && (Math.abs(S.wbCustom.k - S.baseWbCustom.k) > 1 || Math.abs(S.wbCustom.t - S.baseWbCustom.t) > 1));
  if (toneDiff || wbDiff || autoExp || autoWb) {
    S.adjustments[S.current] = {
      tone: { ...S.tone },
      wbSel: S.wbSel,
      wbCustom: { ...S.wbCustom },
      autoExposure: autoExp,
      autoWb: autoWb
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
  const vpol = S.vpolicy || (S.fx.has("optical_vignetting") ? "optical" : "film");
  if (S.fxPreset === "golden_haze" && (!S.fxParams || !Object.keys(S.fxParams).length)) {
    return { preset_id: "golden_haze", strength: S.fxStrength, halation_policy: S.policy, vignette_policy: vpol, stack: [] };
  }
  if (S.fxPreset === "vintage_glass" && (!S.fxParams || !Object.keys(S.fxParams).length)) {
    return { preset_id: "vintage_glass", strength: S.fxStrength, halation_policy: S.policy, vignette_policy: vpol, stack: [] };
  }
  const on = [...S.fx];
  if (!on.length && S.fxPreset === "none") {
    return { preset_id: "none", strength: 0, halation_policy: S.policy === "disabled" ? "disabled" : "film", stack: [] };
  }
  const pid = S.fxPreset && S.fxPreset !== "none" ? S.fxPreset : (on.length ? on[0] : "none");
  const stack = on.map(id => ({
    id,
    enabled: true,
    parameters: (S.fxParams && S.fxParams[id]) ? { ...S.fxParams[id] } : {}
  }));
  return { preset_id: pid, strength: S.fxStrength, halation_policy: S.policy, vignette_policy: vpol, stack };
}
function recipe(withCrop = true) {
  const r = { schema_version: 2,
    camera_look: { id: S.look, version: "1.0.0", strength: S.look === "neutral" ? 1 : S.strength },
    film: { id: S.film, grain_scale: S.grain, halation_scale: S.halation, softness_scale: S.softness },
    optical: opticalBlock(),
    render: { output_format: "jpeg", output_color_space: "srgb", quality: S.quality },
    seed: S.seed, extensions: { white_balance: S.wbSel === "as-shot" ? "as-shot" : "daylight" } };
  if (S.comboPreset) r.preset_id = S.comboPreset;
  const effGrade = getEffectiveFrameGrade(S.current);
  if (effGrade && effGrade.mode === "preset") {
    r.creative_color_grade = {
      mode: "preset",
      preset_id: effGrade.preset_id,
      preset_version: effGrade.preset_version || "1.0.0",
      strength: effGrade.strength !== undefined ? effGrade.strength : 1.0,
      overrides: effGrade.overrides || {},
    };
  } else if (effGrade && effGrade.mode === "none") {
    r.creative_color_grade = { mode: "none" };
  }
  const tn = toneExt(); if (Object.keys(tn).length) r.extensions.tone = tn;
  const wp = wbExt(); if (wp) r.extensions.wb_profile = wp;
  const ai = aiExt(); if (ai) r.extensions.ai = ai;
  if (S.width && S.height) { r.render.width = S.width; r.render.height = S.height; }
  if (withCrop && S.crops[S.current]) r.extensions.crop = S.crops[S.current];     // this frame's own framing
  if (withCrop && S.rotates[S.current]) r.extensions.rotate = normDeg(S.rotates[S.current]);
  return r;
}
function aiExt() {
  if (S.studioMode !== "neural") return null;
  const cfg = {
    mode: S.aiMode || "pure",
    auto_enhance: {
      enabled: !!S.aiAutoEnhance,
      strength: S.aiAutoEnhanceStrength !== undefined ? S.aiAutoEnhanceStrength : 1.0,
      style: S.aiAutoEnhanceStyle || "standard",
      model: "image_adaptive_3dlut"
    },
    style_reference: {
      enabled: !!S.aiStyleRef,
      strength: S.aiStyleRefStrength !== undefined ? S.aiStyleRefStrength : 1.0,
      reference_id: S.aiStyleRefId || null,
      preserve_skin: S.aiStyleRefPreserveSkin !== false,
      model: "sa_lut"
    },
    neural_engine: {
      enabled: !!S.aiEngineEnabled,
      engine: S.aiEngineType || "rawnind",
      chroma_strength: S.aiChromaStrength !== undefined ? S.aiChromaStrength : 0.6,
      luma_strength: S.aiLumaStrength !== undefined ? S.aiLumaStrength : 0.3,
      detail_preservation: S.aiDetailPreserve !== undefined ? S.aiDetailPreserve : 0.8,
      upscale_scale: S.aiUpscaleScale || 2,
      upscale_model: S.aiUpscaleModel || "RealESRGAN_x2plus"
    }
  };
  const hasAny = cfg.auto_enhance.enabled || cfg.style_reference.enabled || cfg.neural_engine.enabled;
  return hasAny ? cfg : null;
}
function baseJobRecipe() {
  const r = { schema_version: 2,
    camera_look: { id: S.look, version: "1.0.0", strength: S.look === "neutral" ? 1 : S.strength },
    film: { id: S.film, grain_scale: S.grain, halation_scale: S.halation, softness_scale: S.softness },
    optical: opticalBlock(),
    render: { output_format: "jpeg", output_color_space: "srgb", quality: S.quality },
    seed: S.seed, extensions: { white_balance: S.baseWbSel === "as-shot" ? "as-shot" : "daylight" } };
  if (S.comboPreset) r.preset_id = S.comboPreset;
  if (S.colorGrade && S.colorGrade.mode === "preset") {
    r.creative_color_grade = {
      mode: "preset",
      preset_id: S.colorGrade.preset_id,
      preset_version: S.colorGrade.preset_version || "1.0.0",
      strength: S.colorGrade.strength !== undefined ? S.colorGrade.strength : 1.0,
      overrides: S.colorGrade.overrides || {},
    };
  } else {
    r.creative_color_grade = { mode: "none" };
  }
  if (S.frameGradeOverrides && Object.keys(S.frameGradeOverrides).length) {
    r.frame_color_grade_overrides = { ...S.frameGradeOverrides };
  }
  const tn = frameToneExt(S.baseTone); if (Object.keys(tn).length) r.extensions.tone = tn;
  const wp = frameWbExt(S.baseWbSel, S.baseWbCustom); if (wp) r.extensions.wb_profile = wp;
  const ai = aiExt(); if (ai) r.extensions.ai = ai;
  if (S.width && S.height) { r.render.width = S.width; r.render.height = S.height; }
  return r;
}
function baseRecipe(opts = {}) {
  const r = recipe(true);
  if (r.extensions) delete r.extensions.tone;     // post-tone (brightness, contrast, develop, filter) is applied live on canvas
  if (S.studioMode === "neural" && S.aiMode === "pure") {
    r.film = { id: "none", grain_scale: 1, halation_scale: 1, softness_scale: 1 };
    r.camera_look = { id: "neutral", version: "1.0.0", strength: 1 };
    r.optical = { preset_id: "none", strength: 0, halation_policy: "disabled", stack: [] };
  } else {
    if (opts.noFilm) r.film = { id: "none", grain_scale: 1, halation_scale: 1, softness_scale: 1 };
    if (opts.noFx) r.optical = { preset_id: "none", strength: 0, halation_policy: S.policy === "disabled" ? "disabled" : "film", stack: [] };
    if (opts.noLook) r.camera_look = { id: "neutral", version: "1.0.0", strength: 1 };
  }
  return r;
}

/* ---------------- setup & onboarding ---------------- */
function setupForm(status, isModal = false, onClose = null) {
  const cfg = (status && status.config) || {};
  const authOk = Boolean(status && status.auth_configured);

  const inpPw = h("input", { type: "password", id: "setup_pw", placeholder: authOk ? "Leave blank to keep current password" : "At least 10 characters", autocomplete: "new-password" });
  const inpDataDir = h("input", { type: "text", id: "setup_data_dir", value: cfg.data_dir || "", placeholder: "/mnt/theVault/mfilm or ~/.local/share/mfilm" });
  const inpOrigDir = h("input", { type: "text", id: "setup_orig_dir", value: cfg.photoprism_originals_dir || "", placeholder: "/mnt/theVault/RAW_LIB/photos" });
  const inpPpUrl = h("input", { type: "text", id: "setup_pp_url", value: cfg.photoprism_url || "", placeholder: "http://localhost:2342" });
  const inpPpTok = h("input", { type: "password", id: "setup_pp_tok", placeholder: cfg.photoprism_token_set ? `Configured (${cfg.photoprism_token_preview || '***'}), leave blank to keep` : "PhotoPrism app password / token", autocomplete: "off" });
  const inpWebFolder = h("input", { type: "text", id: "setup_web_folder", value: cfg.photoprism_web_folder || "Chromurgy/Developed", placeholder: "Chromurgy/Developed" });
  const inpIdxTmpl = h("input", { type: "text", id: "setup_idx_tmpl", value: cfg.photoprism_index_template || "docker exec photoprism photoprism index {path}", placeholder: "docker exec photoprism photoprism index {path}" });
  const inpJobs = h("input", { type: "number", min: "1", max: "16", id: "setup_jobs", value: String(cfg.worker_jobs || 4) });

  const testStatus = h("div", { class: "test-res", id: "setup_test_res" });
  const testBtn = h("button", { type: "button", class: "btn ghost", onclick: async () => {
    testStatus.className = "test-res pending";
    testStatus.textContent = "Testing PhotoPrism connection…";
    try {
      const res = await api("/setup/test-photoprism", {
        method: "POST",
        json: {
          url: inpPpUrl.value.trim(),
          token: inpPpTok.value.trim() || undefined,
          originals_dir: inpOrigDir.value.trim() || undefined
        }
      });
      if (res.ok) {
        testStatus.className = "test-res ok";
        const v = res.version ? ` (v${res.version})` : "";
        testStatus.textContent = `✓ Connected to PhotoPrism${v} · Originals accessible`;
      } else {
        testStatus.className = "test-res err";
        testStatus.textContent = `✗ ${res.error || "Connection failed"}`;
      }
    } catch (e) {
      testStatus.className = "test-res err";
      testStatus.textContent = `✗ ${e.message}`;
    }
  } }, "⚡ Test Connection");

  const saveBtn = h("button", { type: "submit", class: "primary" }, isModal ? "Save Settings" : "Save & Open Darkroom");

  const form = h("form", { onsubmit: async ev => {
    ev.preventDefault();
    const pwVal = inpPw.value.trim();
    if (!authOk && (!pwVal || pwVal.length < 10)) {
      toast("Operator password must be at least 10 characters");
      inpPw.focus();
      return;
    }
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving…";
    try {
      const payload = {
        password: pwVal || undefined,
        data_dir: inpDataDir.value.trim() || undefined,
        photoprism_url: inpPpUrl.value.trim() || undefined,
        photoprism_token: inpPpTok.value.trim() || undefined,
        photoprism_originals_dir: inpOrigDir.value.trim() || undefined,
        photoprism_web_folder: inpWebFolder.value.trim() || undefined,
        photoprism_index_template: inpIdxTmpl.value.trim() || undefined,
        worker_jobs: parseInt(inpJobs.value, 10) || 1
      };
      const res = await api("/setup/save", { method: "POST", json: payload });
      toast(res.message || "Settings saved");
      if (isModal) {
        if (onClose) onClose();
      } else {
        boot();
      }
    } catch (e) {
      toast("Setup error: " + e.message);
      saveBtn.disabled = false;
      saveBtn.textContent = isModal ? "Save Settings" : "Save & Open Darkroom";
    }
  } },
    h("div", { class: "setup-sec" },
      h("h3", {}, "🔑 Operator Security"),
      h("div", { class: "setup-field" },
        h("label", { for: "setup_pw" }, authOk ? "Update Operator Password" : "Set Operator Password"),
        inpPw,
        h("div", { class: "hint" }, authOk ? "Leave blank to keep your current password." : "Required for accessing the darkroom (minimum 10 characters).")
      )
    ),
    h("div", { class: "setup-sec" },
      h("h3", {}, "📁 Storage & Digital Negatives"),
      h("div", { class: "setup-field" },
        h("label", { for: "setup_orig_dir" }, "PhotoPrism Originals / RAW Negatives Path"),
        inpOrigDir,
        h("div", { class: "hint" }, "Local or mount path to the directory where your RAW negatives are stored on this server.")
      ),
      h("div", { class: "setup-field" },
        h("label", { for: "setup_data_dir" }, "Chromurgy Data Storage Path"),
        inpDataDir,
        h("div", { class: "hint" }, "Directory for Chromurgy internal database, render cache, and sessions.")
      )
    ),
    h("div", { class: "setup-sec" },
      h("h3", {}, "🌐 PhotoPrism Cloud Integration"),
      h("div", { class: "setup-grid" },
        h("div", { class: "setup-field" },
          h("label", { for: "setup_pp_url" }, "PhotoPrism API URL"),
          inpPpUrl,
          h("div", { class: "hint" }, "HTTP endpoint of your PhotoPrism instance (e.g. http://localhost:2342).")
        ),
        h("div", { class: "setup-field" },
          h("label", { for: "setup_pp_tok" }, "App Password / API Token"),
          inpPpTok,
          h("div", { class: "hint" }, "Generated in PhotoPrism: Settings → Users → App Passwords.")
        )
      ),
      h("div", { class: "test-bar" }, testBtn, testStatus),
      h("div", { class: "setup-grid", style: "margin-top:1rem" },
        h("div", { class: "setup-field" },
          h("label", { for: "setup_web_folder" }, "Default Output Subfolder"),
          inpWebFolder,
          h("div", { class: "hint" }, "Subdirectory under PhotoPrism originals for developed film renditions.")
        ),
        h("div", { class: "setup-field" },
          h("label", { for: "setup_idx_tmpl" }, "Index Command Template"),
          inpIdxTmpl,
          h("div", { class: "hint" }, "Executed on server after publish to update PhotoPrism index ({path} is replaced with relative folder).")
        )
      )
    ),
    h("div", { class: "setup-sec" },
      h("h3", {}, "⚡ Performance & Workers"),
      h("div", { class: "setup-field" },
        h("label", { for: "setup_jobs" }, "Worker Concurrency (Parallel Frames)"),
        inpJobs,
        h("div", { class: "hint" }, "Number of frames rendered simultaneously (each full-resolution frame takes ~0.9 GB RAM).")
      )
    ),
    h("div", { class: "bar", style: "justify-content:flex-end;margin-top:1.5rem" },
      isModal ? h("button", { type: "button", class: "ghost", onclick: onClose }, "Cancel") : null,
      saveBtn
    )
  );
  return form;
}

function showOnboarding(status) {
  $("#logout").hidden = true;
  if ($("#btn_settings")) $("#btn_settings").hidden = true;
  $("#steps").replaceChildren();

  const container = h("div", { class: "onboarding-wrap" },
    h("div", { class: "onboarding-card" },
      h("div", { class: "onboarding-hero" },
        h("span", { class: "lamp", style: "width:1.2rem;height:1.2rem;margin:0 auto .5rem;display:block" }),
        h("h2", {}, "Welcome to Chromurgy"),
        h("p", {}, "Digital Darkroom for RAW Development & Film Simulation"),
        h("p", { class: "onboarding-intro" },
          "Let's configure your darkroom environment. Specify the location of your digital RAW negatives and connect your PhotoPrism instance to enable instant browsing and publishing.")
      ),
      setupForm(status, false, null)
    )
  );

  $("#app").replaceChildren(container);
}

async function showSettingsModal() {
  const overlay = $("#modal_overlay");
  if (!overlay) return;

  let st = null;
  try {
    st = await api("/setup/status");
  } catch (e) {
    toast("Failed to load settings: " + e.message);
    return;
  }

  const close = () => {
    overlay.hidden = true;
    overlay.replaceChildren();
  };

  const dialog = h("div", { class: "modal-dialog" },
    h("div", { class: "modal-head" },
      h("h2", {}, "⚙ Darkroom & PhotoPrism Settings"),
      h("button", { type: "button", class: "ghost", onclick: close, "aria-label": "Close" }, "✕")
    ),
    h("div", { class: "modal-body" },
      setupForm(st, true, close)
    )
  );

  overlay.replaceChildren(dialog);
  overlay.hidden = false;
  overlay.onclick = e => { if (e.target === overlay) close(); };
}

/* ---------------- login ---------------- */
async function showLogin() {
  $("#logout").hidden = true;
  if ($("#btn_settings")) $("#btn_settings").hidden = true;
  $("#steps").replaceChildren();

  let setupSt = null;
  try {
    setupSt = await api("/setup/status");
  } catch (e) {}

  if (setupSt && setupSt.onboarding_needed) {
    showOnboarding(setupSt);
    return;
  }

  const pw = h("input", { type: "password", id: "pw", autocomplete: "current-password", required: true });
  const form = h("form", { class: "step login", onsubmit: async ev => {
    ev.preventDefault();
    try {
      await api("/login", { method: "POST", json: { password: pw.value } });
      boot();
    } catch (e) {
      if (e.code === "LOGIN_NOT_CONFIGURED") {
        if (setupSt) showOnboarding(setupSt);
        else toast(e.message);
      } else {
        toast(e.message);
      }
    }
  } },
    h("h2", {}, "Safelight on"),
    h("label", { for: "pw" }, "Operator password"), pw,
    h("div", { class: "bar" },
      h("button", { class: "primary" }, "Enter the darkroom"),
      h("button", { type: "button", class: "ghost", style: "font-size:.78rem;margin-left:auto",
                   onclick: () => showOnboarding(setupSt || { config: {} }) }, "⚙ Setup")));
  $("#app").replaceChildren(form);
  pw.focus();
}

/* ---------------- layout ---------------- */
let currentRightTab = "adjust_dev";
function switchRightTab(tabId) {
  currentRightTab = tabId;
  const tabBtnAdj = $("#tab_btn_adjust"), tabBtnJobs = $("#tab_btn_jobs");
  const paneAdj = $("#tab_pane_adjust"), paneJobs = $("#tab_pane_jobs");
  if (tabBtnAdj) tabBtnAdj.setAttribute("aria-selected", String(tabId === "adjust_dev"));
  if (tabBtnJobs) tabBtnJobs.setAttribute("aria-selected", String(tabId === "jobs"));
  if (paneAdj) paneAdj.hidden = tabId !== "adjust_dev";
  if (paneJobs) paneJobs.hidden = tabId !== "jobs";
}

function getCollapsedSteps() {
  try {
    const raw = localStorage.getItem("mfilm.collapsed_steps");
    return raw ? JSON.parse(raw) : [];
  } catch (e) { return []; }
}
function setStepCollapsedState(n, isCollapsed) {
  try {
    const list = new Set(getCollapsedSteps());
    if (isCollapsed) list.add(n); else list.delete(n);
    localStorage.setItem("mfilm.collapsed_steps", JSON.stringify([...list]));
  } catch (e) {}
}

function toggleStep(n, sec, arrow, bodyEl) {
  const isCollapsed = sec.classList.toggle("collapsed");
  bodyEl.hidden = isCollapsed;
  const h2 = sec.querySelector("h2");
  if (h2) h2.setAttribute("aria-expanded", String(!isCollapsed));
  if (arrow) arrow.textContent = isCollapsed ? "◂" : "▾";
  setStepCollapsedState(n, isCollapsed);
}

function expandStep(n) {
  const sec = $("#s" + n);
  if (!sec) return;
  if (sec.classList.contains("collapsed")) {
    const h2 = sec.querySelector("h2");
    if (h2) h2.click();
  }
}

function step(n, title, hint, ...body) {
  const isCollapsible = n >= 1 && n <= 6;
  if (!isCollapsible) {
    return h("section", { class: "step", id: "s" + n },
      h("h2", {}, h("span", { class: "n" }, n), title, hint ? h("span", { class: "hint" }, hint) : null),
      body
    );
  }
  const bodyEl = h("div", { class: "step-body" }, body);
  const isCollapsed = getCollapsedSteps().includes(n);
  if (isCollapsed) bodyEl.hidden = true;

  const arrow = h("span", { class: "step-arrow", "aria-hidden": "true" }, isCollapsed ? "◂" : "▾");
  const h2 = h("h2", {
    role: "button",
    tabindex: "0",
    "aria-expanded": String(!isCollapsed),
    title: "Click to collapse or expand section"
  }, h("span", { class: "n" }, n), title, hint ? h("span", { class: "hint" }, hint) : null, arrow);

  const sec = h("section", { class: "step collapsible" + (isCollapsed ? " collapsed" : ""), id: "s" + n }, h2, bodyEl);

  h2.addEventListener("click", () => toggleStep(n, sec, arrow, bodyEl));
  h2.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggleStep(n, sec, arrow, bodyEl);
    }
  });

  return sec;
}
function updateTopNavSteps() {
  const stepsNav = $("#steps");
  if (!stepsNav) return;
  if (S.studioMode === "neural") {
    const nSteps = ["Material", "Neural Studio"];
    stepsNav.replaceChildren(...nSteps.map((t, i) => h("a", { href: "#s" + (i + 1), onclick: () => expandStep(i + 1) }, h("b", {}, i + 1), t)));
  } else {
    stepsNav.replaceChildren(...STEPS.map((t, i) => h("a", { href: "#s" + (i + 1), onclick: () => expandStep(i + 1) }, h("b", {}, i + 1), t)));
  }
}

function switchStudioMode(mode) {
  S.studioMode = mode;
  localStorage.setItem("mfilm.studio_mode", mode);
  const btnClassic = $("#btn_mode_classic");
  const btnNeural = $("#btn_mode_neural");
  const classicCont = $("#classic_steps_container");
  const neuralCont = $("#neural_steps_container");
  if (btnClassic) btnClassic.className = "mode-tab" + (mode === "classic" ? " active" : "");
  if (btnNeural) btnNeural.className = "mode-tab" + (mode === "neural" ? " active" : "");
  if (classicCont) classicCont.hidden = (mode === "neural");
  if (neuralCont) neuralCont.hidden = (mode !== "neural");
  updateTopNavSteps();
  schedulePreview(true);
}

async function boot() {
  try { S.catalog = await api("/catalog"); } catch (e) { if (e.status !== 401) toast(e.message); return; }
  try { S.wbl = await api("/wb-profiles"); } catch (e) { S.wbl = { builtin: [], imported: [] }; }
  try { const c = await api("/combos"); S.combos = c.items || []; } catch (e) { S.combos = []; }
  if (!S.film) S.film = S.catalog.films.find(f => f.id === "portra400") ? "portra400" : S.catalog.films[0].id;
  $("#logout").hidden = false;
  const btnSettings = $("#btn_settings");
  if (btnSettings) {
    btnSettings.hidden = false;
    btnSettings.onclick = () => showSettingsModal();
  }
  updateTopNavSteps();
  const modeBar = h("div", { class: "studio-mode-bar", role: "tablist" },
    h("button", {
      id: "btn_mode_classic",
      class: "mode-tab" + (S.studioMode === "classic" ? " active" : ""),
      onclick: () => switchStudioMode("classic")
    }, "🎞 Classic Darkroom"),
    h("button", {
      id: "btn_mode_neural",
      class: "mode-tab" + (S.studioMode === "neural" ? " active" : ""),
      onclick: () => switchStudioMode("neural")
    }, "🧠 Neural Studio")
  );

  const classicSteps = h("div", { id: "classic_steps_container", hidden: S.studioMode === "neural" },
    step(2, "Camera look", "independent of the camera that shot the frame", looksPanel()),
    step(3, "Film stock", `${S.catalog.films.length} profiles from the shared film engine`, filmPanel()),
    step(4, "Optical effects", "presets, bundles and individual operators", opticsPanel()),
    step(5, "Creative Color Grades", "VSCO, Instagram Classics, and finishing grades", gradesPanel()),
    step(6, "My presets", "the whole setting — look, film, optics, adjustments — saved under a name", presetsPanel())
  );

  const neuralSteps = h("div", { id: "neural_steps_container", hidden: S.studioMode !== "neural" },
    step(2, "Neural Studio Processing", "Auto-Enhance, Reference Style Transfer, and Deep Sensor Engines", neuralStudioPanel())
  );

  const left = h("div", { class: "pane-left", id: "leftPane" },
    modeBar,
    step(1, "Source material", "RAW only · originals are never modified", materialPanel()),
    classicSteps,
    neuralSteps
  );
  const tabBtnAdj = h("button", { id: "tab_btn_adjust", role: "tab", "aria-selected": "true", onclick: () => switchRightTab("adjust_dev") }, "✦ Adjust & Develop");
  const tabBtnJobs = h("button", { id: "tab_btn_jobs", role: "tab", "aria-selected": "false", onclick: () => switchRightTab("jobs") }, "⚙ Jobs & History");
  const rightTabs = h("div", { class: "right-tabs", role: "tablist" }, tabBtnAdj, tabBtnJobs);
  const paneAdjust = h("div", { class: "right-tab-pane", id: "tab_pane_adjust" },
    h("div", { class: "adjust-develop-grid" }, adjustPanel(), developPanel())
  );
  const paneJobs = h("div", { class: "right-tab-pane", id: "tab_pane_jobs", hidden: true },
    jobsPanel()
  );
  const right = h("div", { class: "pane-right", id: "rightPane" },
    step(7, "Preview, develop", "",
      h("div", { class: "pv-pin" }, previewPanel()),
      rightTabs,
      paneAdjust,
      paneJobs));
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
  const tabs = h("div", { class: "tabs", role: "tablist" }, mk("Upload RAW", upPane, true), mk("PhotoPrism", ppPane), mk("Camera rolls", rollPane));
  return h("div", {}, tabs, upPane, ppPane, rollPane,
    h("div", { class: "bar", style: "flex-wrap:wrap;gap:.4rem;align-items:center" },
      h("button", { onclick: () => selectAll(true) }, "Select all"),
      h("button", { id: "deselectbtn", onclick: () => selectAll(false), title: "Uncheck all frames without removing them from the tray" }, "Deselect"),
      h("button", { id: "clearbtn", onclick: clearAssets, title: "Clear loaded photos from the workspace tray and reset the preview" }, "Clear"),
      h("button", { id: "ppsyncbtn", hidden: true, onclick: () => syncPpPreviews(true), title: "Synchronize thumbnails with PhotoPrism" }, "↻ Sync previews"),
      h("button", { id: "restorebtn", hidden: true, onclick: restoreAssets, title: "Restore previously loaded photos from archive" }, "Restore archived"),
      h("label", { style: "display:inline-flex;align-items:center;gap:.3rem;font-size:.78rem;margin-left:auto" },
        "Tray sort: ",
        h("select", { id: "traysort", style: "padding:.2rem .4rem;font-size:.78rem", onchange: e => { S.traySort = e.target.value; saveTraySort(); renderAssets(); } },
          h("option", { value: "default", selected: S.traySort === "default" }, "Original order"),
          h("option", { value: "date_asc", selected: S.traySort === "date_asc" }, "Date (oldest first)"),
          h("option", { value: "date_desc", selected: S.traySort === "date_desc" }, "Date (newest first)"),
          h("option", { value: "name_asc", selected: S.traySort === "name_asc" }, "Name (A → Z)"),
          h("option", { value: "name_desc", selected: S.traySort === "name_desc" }, "Name (Z → A)"))),
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
        "Sort by: ",
        h("select", { id: "roll_sort", style: "padding:.2rem .4rem;font-size:.78rem", onchange: () => renderRolls() },
          h("option", { value: "date_desc" }, "Date (newest first)"),
          h("option", { value: "date_asc" }, "Date (oldest first)"),
          h("option", { value: "name_asc" }, "Film profile (A–Z)")))),
    h("div", { class: "cards", id: "rolllist" }));
}
async function rollsInit() {
  await withLoading("Loading camera rolls…", "Reading archived camera rolls from the server…", async () => {
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
const PP = {
  inst: null,
  mode: "albums",
  albumOrder: (function() { try { return localStorage.getItem("mfilm.pp_album_sort") || "name"; } catch (_) { return "name"; } })(),
  folderOrder: (function() { try { return localStorage.getItem("mfilm.pp_folder_sort") || "name_asc"; } catch (_) { return "name_asc"; } })(),
  photoOrder: (function() { try { return localStorage.getItem("mfilm.pp_photo_sort") || "newest"; } catch (_) { return "newest"; } })(),
  src: null,
  page: [],
  offset: 0,
  next: null,
  prevOffsets: [],
  stack: [],
  q: "",
  chosen: new Map(),
  sourceKind: null,
  sourceUid: null
};

function getFolderDate(f) {
  if (f.year && f.year > 1970) {
    const m = (f.month || 1) - 1;
    const d = f.day || 1;
    return new Date(f.year, m, d).getTime();
  }
  if (f.mtime) return f.mtime * 1000;
  if (f.modified_at) {
    const t = Date.parse(f.modified_at);
    if (!isNaN(t)) return t;
  }
  const mIso = (f.title || "").match(/^(\d{4})[-._](\d{2})[-._](\d{2})/);
  if (mIso) return new Date(+mIso[1], +mIso[2] - 1, +mIso[3]).getTime();
  const mRu = (f.title || "").match(/^(\d{2})[-._](\d{2})[-._](\d{4})/);
  if (mRu) return new Date(+mRu[3], +mRu[2] - 1, +mRu[1]).getTime();
  const mYear = (f.title || "").match(/^(\d{4})/);
  if (mYear) return new Date(+mYear[1], 0, 1).getTime();
  return 0;
}

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
    "Sort by: ",
    h("select", {
      id: "pp_album_sort",
      style: "padding:.2rem .4rem;font-size:.78rem",
      onchange: e => {
        PP.albumOrder = e.target.value;
        try { localStorage.setItem("mfilm.pp_album_sort", PP.albumOrder); } catch (_) {}
        ppList();
      }
    },
      h("option", { value: "name", selected: PP.albumOrder === "name" }, "Name (A–Z)"),
      h("option", { value: "newest", selected: PP.albumOrder === "newest" }, "Date (newest first)"),
      h("option", { value: "oldest", selected: PP.albumOrder === "oldest" }, "Date (oldest first)"),
      h("option", { value: "count", selected: PP.albumOrder === "count" }, "Photo count"))),
  h("label", { id: "pp_folder_sort_wrap", style: "display:inline-flex;align-items:center;gap:.3rem;font-size:.78rem", hidden: true },
    "Sort by: ",
    h("select", {
      id: "pp_folder_sort",
      style: "padding:.2rem .4rem;font-size:.78rem",
      onchange: e => {
        PP.folderOrder = e.target.value;
        try { localStorage.setItem("mfilm.pp_folder_sort", PP.folderOrder); } catch (_) {}
        ppList(true);
      }
    },
      h("option", { value: "name_asc", selected: PP.folderOrder === "name_asc" }, "Name (A → Z)"),
      h("option", { value: "name_desc", selected: PP.folderOrder === "name_desc" }, "Name (Z → A)"),
      h("option", { value: "date_desc", selected: PP.folderOrder === "date_desc" }, "Date (newest first)"),
      h("option", { value: "date_asc", selected: PP.folderOrder === "date_asc" }, "Date (oldest first)"),
      h("option", { value: "count_desc", selected: PP.folderOrder === "count_desc" }, "File count"))),
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
  PP.mode = m; PP.stack = []; PP.src = null; PP.q = "";
  $("#pp_photos").replaceChildren();
  if ($("#pp_q")) {
    $("#pp_q").value = "";
    $("#pp_q").placeholder = m === "albums" ? "Search albums…" : "Search folders…";
  }
  if ($("#pp_album_sort_wrap")) $("#pp_album_sort_wrap").hidden = m !== "albums";
  if ($("#pp_folder_sort_wrap")) $("#pp_folder_sort_wrap").hidden = m !== "folders";
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
        if (!r.items.length) box.append(h("p", { class: "dim" }, PP.q ? "No albums match search" : "No albums"));
      } else {
        const parent = PP.stack.join("/");
        $("#pp_crumb").textContent = "Folder under originals: /" + parent;
        const r = await api(`/photoprism/${PP.inst.id}/folders?parent_id=${encodeURIComponent(parent)}`);
        let folders = r.items || [];
        if (PP.q && PP.q.trim()) {
          const q = PP.q.trim().toLowerCase();
          folders = folders.filter(f => (f.title || "").toLowerCase().includes(q) || (f.path || "").toLowerCase().includes(q));
        }
        const ord = PP.folderOrder || "name_asc";
        folders.sort((a, b) => {
          if (ord === "name_desc") {
            return (b.title || "").localeCompare(a.title || "", undefined, { numeric: true, sensitivity: "base" });
          }
          if (ord === "date_desc" || ord === "date_asc") {
            const ta = getFolderDate(a);
            const tb = getFolderDate(b);
            if (ta !== tb) return ord === "date_desc" ? (tb - ta) : (ta - tb);
            return (a.title || "").localeCompare(b.title || "", undefined, { numeric: true, sensitivity: "base" });
          }
          if (ord === "count_desc") {
            const ca = a.file_count || 0;
            const cb = b.file_count || 0;
            if (ca !== cb) return cb - ca;
            return (a.title || "").localeCompare(b.title || "", undefined, { numeric: true, sensitivity: "base" });
          }
          return (a.title || "").localeCompare(b.title || "", undefined, { numeric: true, sensitivity: "base" });
        });
        if (PP.stack.length) box.append(h("button", { type: "button", class: "card", onclick: () => { PP.stack.pop(); ppList(); } }, h("strong", {}, "↑ up")));
        box.append(...folders.map(f => {
          const sub = f.file_count ? `${f.path} · ${f.file_count} files` : f.path;
          return h("button", { type: "button", class: "card", onclick: async () => { PP.stack = f.path.split("/"); await ppList(true); await ppOpen("folder", f.path, f.path, 0); } },
            h("strong", {}, f.title),
            h("small", {}, sub));
        }));
        if (!folders.length) box.append(h("p", { class: "dim" }, PP.q ? "No folders match search" : "No subfolders"));
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
          "Sort by: ",
          h("select", {
            id: "pp_photo_sort",
            style: "padding:.2rem .4rem;font-size:.78rem",
            onchange: e => {
              PP.photoOrder = e.target.value;
              ppOpen(PP.sourceKind, PP.sourceUid, PP.title, 0, false, false);
            }
          },
            h("option", { value: "newest", selected: PP.photoOrder === "newest" }, "Capture date (newest first)"),
            h("option", { value: "oldest", selected: PP.photoOrder === "oldest" }, "Capture date (oldest first)"),
            h("option", { value: "name", selected: PP.photoOrder === "name" }, "File name (A → Z)"),
            h("option", { value: "added", selected: PP.photoOrder === "added" }, "Date added")))),
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
  for (const a of S.assets) {
    if (!S.adjustments[a.asset_id]) {
      initAssetAutoAdjustments(a);
    }
    ensureSourceAnalysis(a);
  }
  for (const id of [...S.selected]) if (!S.assets.some(a => a.asset_id === id)) S.selected.delete(id);
  if (!S.current || !S.assets.find(a => a.asset_id === S.current)) S.current = S.assets.length ? S.assets[0].asset_id : null;
  if (!S.current) clearPreviewStage();
  else loadFrameAdjustments(S.current);
  renderAssets(); syncControls(); if (S.current) schedulePreview();
}
function getFrameNavInfo() {
  if (!S.assets || !S.assets.length || !S.current) {
    return { idx: -1, total: S.assets ? S.assets.length : 0, hasPrev: false, hasNext: false, currentName: "" };
  }
  const idx = S.assets.findIndex(a => a.asset_id === S.current);
  const curAsset = idx >= 0 ? S.assets[idx] : null;
  return {
    idx,
    total: S.assets.length,
    hasPrev: idx > 0,
    hasNext: idx >= 0 && idx < S.assets.length - 1,
    currentName: curAsset ? curAsset.filename : ""
  };
}

function prevFrame() {
  if (S.cropMode) return;
  if (!S.assets || !S.assets.length) return;
  const idx = S.assets.findIndex(a => a.asset_id === S.current);
  if (idx > 0) {
    setCurrent(S.assets[idx - 1].asset_id);
  } else if (idx === -1 && S.assets.length > 0) {
    setCurrent(S.assets[0].asset_id);
  }
}

function nextFrame() {
  if (S.cropMode) return;
  if (!S.assets || !S.assets.length) return;
  const idx = S.assets.findIndex(a => a.asset_id === S.current);
  if (idx >= 0 && idx < S.assets.length - 1) {
    setCurrent(S.assets[idx + 1].asset_id);
  } else if (idx === -1 && S.assets.length > 0) {
    setCurrent(S.assets[0].asset_id);
  }
}

function updateFrameNavUi() {
  const info = getFrameNavInfo();
  const prevBtns = [$("#pv_prev"), $("#stage_prev")];
  const nextBtns = [$("#pv_next"), $("#stage_next")];
  const counter = $("#pv_frame_counter");

  const isCropping = Boolean(S.cropMode);
  prevBtns.forEach(btn => {
    if (btn) {
      btn.disabled = isCropping || !info.hasPrev;
      btn.title = info.hasPrev ? `Previous frame (${info.idx} of ${info.total}) · Left Arrow` : "No previous frame";
    }
  });

  nextBtns.forEach(btn => {
    if (btn) {
      btn.disabled = isCropping || !info.hasNext;
      btn.title = info.hasNext ? `Next frame (${info.idx + 2} of ${info.total}) · Right Arrow` : "No next frame";
    }
  });

  if (counter) {
    if (info.total > 0 && info.idx >= 0) {
      counter.textContent = `${info.idx + 1} / ${info.total}`;
      counter.hidden = false;
    } else if (info.total > 0) {
      counter.textContent = `- / ${info.total}`;
      counter.hidden = false;
    } else {
      counter.textContent = "";
      counter.hidden = true;
    }
  }
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
  updateFrameNavUi();
  renderAssets();
  const curCard = document.querySelector(`.asset[data-id="${id}"]`) || document.querySelector(`.asset.cur`);
  if (curCard && curCard.scrollIntoView) {
    curCard.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }
  schedulePreview(true);
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
    const el = h("div", { class: "asset" + (S.current === a.asset_id ? " cur" : ""), "data-id": a.asset_id, role: "button", tabindex: "0", "aria-pressed": String(sel),
      title: "Click: show in the preview · tick: include in Develop · ×: remove from workspace" },
      th, h("span", { class: "tick", title: "Include in Develop" }, sel ? "✓" : ""), rmBtn,
      h("div", { class: "meta" }, h("b", {}, a.filename, S.crops[a.asset_id] ? " ✂" : "", rot ? ` ⟳${rot}°` : "", S.adjustments[a.asset_id] ? " 🎛" : "", (S.frameGradeOverrides && S.frameGradeOverrides[a.asset_id]) ? " ✦" : ""), [m.model, m.width && `${m.width}×${m.height}`, m.iso && `ISO ${m.iso}`].filter(Boolean).join(" · "),
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
    : "Workspace empty · choose RAWs from Upload, PhotoPrism or Camera rolls";
  updateDevelop();
  updateFrameNavUi();
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

/* ---------------- curated combinations and presets ---------------- */
function comboMatchesScene(c, chip) {
  if (!chip) return true;
  const cat = String(c.category || "").toLowerCase();
  const scenes = (c.scenes || []).map(s => String(s || "").toLowerCase());
  const tags = (c.suggested_tags || []).map(t => String(t || "").toLowerCase());
  const allText = [cat, c.intent || "", c.best_for || "", c.name || "", ...scenes, ...tags].join(" ").toLowerCase();

  if (chip === "street") {
    return scenes.includes("street") || cat === "street";
  }
  if (chip === "portrait") {
    return scenes.includes("portrait") || cat === "portrait" || scenes.includes("skin") || scenes.includes("windowlight");
  }
  if (chip === "golden_hour" || chip === "golden-hour") {
    return ["golden-hour", "golden_hour", "sunlight", "sun", "backlight", "summer"].some(k => allText.includes(k));
  }
  if (chip === "night") {
    return scenes.includes("night") || cat === "night" || scenes.includes("evening");
  }
  if (chip === "neon") {
    return scenes.includes("neon") || allText.includes("neon");
  }
  if (chip === "cinematic") {
    return scenes.includes("cinematic") || ["cinematic", "nostalgia", "documentary", "miniature", "anamorphic"].some(k => allText.includes(k));
  }
  if (chip === "landscape") {
    return scenes.includes("landscape") || cat === "landscape" || ["mountain", "forest", "nature"].some(k => scenes.includes(k));
  }
  if (chip === "fashion") {
    return ["portrait", "skin", "windowlight", "floral", "fashion", "editorial"].some(k => allText.includes(k));
  }
  return scenes.includes(chip.toLowerCase()) || cat.includes(chip.toLowerCase());
}

function combosChipsSync() {
  const box = $("#combochips"); if (!box) return;
  for (const b of box.children) {
    const sId = b.dataset.scene || "";
    const isAll = (sId === "") && !S.comboSceneFilter;
    const match = sId === S.comboSceneFilter;
    b.setAttribute("aria-pressed", String(isAll || match));
  }
}

function selectCombo(c) {
  if (S.comboPreset === c.id) {
    S.comboPreset = null;
    S.activePreset = null;
    S.fx.clear();
    S.fxParams = {};
    S.fxPreset = "none";
    S.policy = "film";
    S.vpolicy = "film";
    resetAllFrameOverrides();
    loadFrameAdjustments(S.current);
    syncControls();
    renderAssets();
    schedulePreview(true);
    toast("Preset cleared: " + c.name);
    return;
  }

  // 1. Unconditionally clear old state and optical effects stack
  S.comboPreset = c.id;
  S.activePreset = null;
  S.fx.clear();
  S.fxParams = {};
  S.fxPreset = "none";
  S.policy = "film";
  S.vpolicy = "film";

  // 2. Camera Look
  if (c.camera_look) S.look = c.camera_look;
  S.strength = c.look_strength !== undefined ? c.look_strength : 1.0;

  // 3. Film Stock
  const filmTarget = c.film_resolved || c.film;
  if (filmTarget) {
    const f = findFilmId(filmTarget);
    if (f) S.film = f;
  }
  S.grain = c.grain_scale !== undefined ? c.grain_scale : 1.0;
  S.halation = c.halation_scale !== undefined ? c.halation_scale : 1.0;
  S.softness = c.softness_scale !== undefined ? c.softness_scale : 1.0;

  // 4. Optical Effects
  S.fxStrength = c.optical_strength !== undefined ? c.optical_strength : 1.0;
  if (c.halation_policy) S.policy = c.halation_policy;
  if (c.vignette_policy) S.vpolicy = c.vignette_policy;

  if (Array.isArray(c.optical_stack) && c.optical_stack.length) {
    for (const op of c.optical_stack) {
      if (op && op.id && op.enabled !== false) {
        S.fx.add(op.id);
        if (op.parameters) S.fxParams[op.id] = { ...op.parameters };
      }
    }
  } else if (Array.isArray(c.optical)) {
    for (const opId of c.optical) {
      if (opId) S.fx.add(opId);
    }
  }

  // Auto-set vignette policy to optical if optical_vignetting is present and policy is film
  if (S.fx.has("optical_vignetting") && S.vpolicy === "film") {
    S.vpolicy = "optical";
  }
  // Auto-set halation policy to optical if film_halation_extra is present and policy is film
  if (S.fx.has("film_halation_extra") && S.policy === "film") {
    S.policy = "optical";
  }

  S.fxPreset = S.fx.size === 1 ? [...S.fx][0] : "none";

  // 5. Reset overrides and sync UI
  resetAllFrameOverrides();
  loadFrameAdjustments(S.current);
  syncControls();
  renderAssets();

  // 6. Force immediate preview re-render
  schedulePreview(true);
  toast(`Applied preset: ${c.name}`);
}

/* ---------------- step 2: camera look ---------------- */
const LOOK_SIGNATURES = {
  neutral: {
    tag: "Base Profile",
    summary: "Pure linear color rendition without sensor bias",
    detail: "Neutral reference point: accurate base color and linear contrast for maximum control during film emulation."
  },
  leica_m8_ccd: {
    tag: "Kodak CCD · 10 MP",
    summary: "High micro-contrast and vintage Leica rendering",
    detail: "Legendary Kodak KAF-8300 CCD sensor with thin IR cut filter. Dense cool shadows, rich warm highlights, expressive plastic rendition, and lively skin tones."
  },
  leica_m9_ccd: {
    tag: "Full-Frame Kodak CCD · 18 MP",
    summary: "Dense analog color and signature M-series character",
    detail: "Iconic Kodak KAF-18500 CCD sensor. Filmic depth, warm highlights, olive-emerald foliage transitions, and crisp micro-contrast without digital harshness."
  },
  fujifilm_s5_pro: {
    tag: "Super CCD SR Pro · Dual Pixels",
    summary: "Exceptional highlight dynamic range and soft portrait tonality",
    detail: "Legendary Fujifilm Super CCD sensor with dedicated highlight receptors. Gentle organic roll-off, unclipped bright areas, and smooth natural skin tones."
  },
  nikon_d200_ccd: {
    tag: "Sony CCD · Early DSLR Era",
    summary: "Punchy contrast and deep saturated color",
    detail: "Classic Nikon CCD character: rich dense shadows, deep sky blues, warm earthy tones, and vibrant natural color reproduction."
  },
  pentax_645d_ccd: {
    tag: "Medium Format CCD · 40 MP",
    summary: "Silky tonal gradations and medium-format depth",
    detail: "Large-format Kodak CCD sensor. Superior tonal gradations, graceful highlight roll-off, restrained natural palette, and pronounced subject separation."
  },
  ricoh_gr_iii_positive: {
    tag: "Street Culture · Ricoh GR",
    summary: "High-contrast color reversal slide film aesthetic",
    detail: "Signature Positive Film profile: punchy micro-contrast, deep blacks, accentuated reds and blues, and vibrant dramatic street look."
  },
  sigma_dp2_merrill_foveon: {
    tag: "Foveon X3 · Direct Full-RGB Capture",
    summary: "Extreme textural micro-contrast and pixel sharpness",
    detail: "Three-layer silicon sensor without Bayer debayering: extraordinary per-pixel fine detail, clean neutral highlights, and tactile 3D pop."
  },
  fujifilm_xpro3_classic_negative: {
    tag: "Fujicolor Superia Look",
    summary: "Dense shadows, muted saturation, and cyan greens",
    detail: "Stylized after nostalgic consumer color negative film: distinctive hard S-curve in midtones, subdued colors, and green shifted toward noble cyan."
  },
  hasselblad_500cm: {
    tag: "Medium Format 6×6 · Carl Zeiss",
    summary: "Planar 80mm depth, silky highlight roll-off and studio tonality",
    detail: "Legendary medium-format system used in studio, fashion, and lunar missions. Carl Zeiss Planar T* rendition with smooth tonal gradation, gentle highlight compression, refined microcontrast, and natural warm skin rendering."
  },
  leica_m6_rangefinder: {
    tag: "35mm Rangefinder · Leitz Glass",
    summary: "Summicron microcontrast, authoritative blacks, and street snap",
    detail: "The definitive photojournalism and street photography icon. High optical microcontrast from Leitz Summicron optics, crisp edge separation, deep shadows, and subtle amber warmth in highlight transitions."
  },
  contax_t2_sonnar: {
    tag: "90s Luxury Compact · Carl Zeiss",
    summary: "Punchy contrast, vivid saturation, and cool shadow bite",
    detail: "Cult 1990s titanium point-and-shoot equipped with Carl Zeiss Sonnar 38mm f/2.8 T*. High punchy contrast, vibrant saturated hues, deep cool shadows, and signature snapshot flash aesthetic."
  },
  mamiya_7_ii: {
    tag: "Medium Format 6×7 · Sekor Lenses",
    summary: "Ultra-sharp flat-field neutrality and high dynamic headroom",
    detail: "Celebrated for the sharpest, most distortion-free lenses in medium format photography. Balanced, neutral color rendering, velvety midtone graduation, and immaculate architectural clarity."
  },
  olympus_om1_zuiko: {
    tag: "Compact SLR · OM Zuiko Glass",
    summary: "Vintage Japanese glass warmth, lifted shadows, and golden glow",
    detail: "Pioneering mechanical compact SLR with OM Zuiko optics. Gentle lifted shadow toe, organic warm golden highlights, soft tactile microcontrast, and glowing skin tones."
  },
  rolleiflex_28f_tlr: {
    tag: "Twin Lens Reflex 6×6 · Zeiss / Xenotar",
    summary: "Classic TLR portraiture, soft highlight compression, and creamy depth",
    detail: "Iconic square-format twin-lens reflex camera favored by mid-century portrait masters. Smooth highlight shoulder roll-off, restrained classic color palette, and gentle amber-toned midtones."
  },
  polaroid_sx70_instant: {
    tag: "Folding Glass SLR · Integral Film",
    summary: "Compressed dynamic range, cyan-green shadows, and creamy highlights",
    detail: "The pinnacle of instant chemical photography. Signature compressed tonal latitude, tinted cyan-green shadow response, warm ivory highlights, and soft organic emulsion rendering."
  },
  lomo_lca: {
    tag: "Street Cult · Minitar-1 Glass",
    summary: "Saturated color pop, crushed gritty blacks, and raw vignette energy",
    detail: "The Soviet 35mm compact that sparked the Lomography movement. High-contrast punch, deep gritty blacks, vibrant saturated colors, and characteristic warm-shifted snapshot grit."
  },
  pentax_67: {
    tag: "Medium Format 6×7 · SMC Takumar",
    summary: "Dreamy medium format portraiture with rich tonal transitions",
    detail: "Iconic field medium format SLR known for the legendary 105mm f/2.4 lens. Velvety shallow focus roll-off, rich dimensional microcontrast, and flattering warm skin tonality."
  },
  fujifilm_x100vi: {
    tag: "X-Trans 5 HR · 40.2 MP",
    summary: "Reala Ace tonality, ultra-high resolution, and wide highlight latitude",
    detail: "Modern Fujifilm flagship compact with 40.2 MP X-Trans 5 HR sensor and redesigned Fujinon 23mm f/2 II lens. Neutral-warm fidelity, rich midtone clarity, wide dynamic range highlight preservation, and crisp micro-detail."
  },
  zenit_e_ttl: {
    tag: "Soviet SLR · Helios 44 Glass",
    summary: "Helios 58mm f/2 swirly character, amber flare warmth, and lifted earthy shadows",
    detail: "The iconic mass-production Soviet 35mm SLR paired with the Biotar-derived Helios-44 (58mm f/2). Moderate vintage single-coating contrast, rich golden-amber flare glow, lifted shadow floor, and organic analog texture."
  },
  pentax_k1000: {
    tag: "Mechanical 35mm SLR · SMC Pentax",
    summary: "Super Multi-Coated clarity, deep clean blacks, and natural color balance",
    detail: "The quintessential mechanical 35mm SLR beloved by generations of photographers. Super Multi-Coated (SMC) Takumar/Pentax 50mm glass gives exceptional flare control, deep clean shadows, and crisp natural color fidelity."
  },
  zorki_4: {
    tag: "Soviet Rangefinder · Jupiter-8 Glass",
    summary: "Zeiss Sonnar optical formula, creamy highlight bloom, and luminous portraits",
    detail: "Classic Soviet Leica-thread rangefinder equipped with the Jupiter-8 (50mm f/2), an evolution of the Carl Zeiss Sonnar. Delivers luminous portrait roll-off, soft highlight bloom, rich midtone separation, and warm vintage amber tones."
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

const FILM_LOOK_IDS = new Set([
  "hasselblad_500cm", "leica_m6_rangefinder", "contax_t2_sonnar", "mamiya_7_ii",
  "olympus_om1_zuiko", "pentax_k1000", "pentax_67", "rolleiflex_28f_tlr",
  "zenit_e_ttl", "zorki_4", "polaroid_sx70_instant", "lomo_lca"
]);

function setLookFilter(cat) {
  S.lookCategory = cat;
  const tabs = document.querySelectorAll(".look-tab");
  tabs.forEach(t => t.setAttribute("aria-pressed", String(t.dataset.cat === cat)));
  renderLooks();
}

function makeLookCard(l) {
  const isFilm = (l.category === "film") || FILM_LOOK_IDS.has(l.id);
  const catLabel = isFilm ? "Film" : "Digital";
  const catClass = isFilm ? "cat-badge cat-film" : "cat-badge cat-digital";
  const b = h("button", { class: "card", "aria-pressed": String(S.look === l.id), "aria-disabled": String(!l.supported),
    title: l.supported ? "" : "Not implemented in this engine yet", onclick: () => {
      hideLookTooltip();
      if (!l.supported) return toast(`${l.name}: not implemented in this engine yet`);
      S.look = l.id; syncControls(); schedulePreview(); } },
    h("span", { class: catClass }, catLabel),
    h("strong", {}, l.name), h("small", {}, l.evidence_tier), h("span", { class: "tag" }, l.supported ? "available" : "not available"));

  b.addEventListener("pointerenter", e => {
    if (e.pointerType === "touch") return;
    hideLookTooltip();
    lookHoverTimer = setTimeout(() => {
      if (b.matches(":hover")) showLookTooltip(b, l.id);
    }, 1000);
  });
  b.addEventListener("pointerleave", hideLookTooltip);
  b.addEventListener("mouseleave", hideLookTooltip);

  return b;
}

function looksPanel() {
  S.lookCategory = S.lookCategory || "all";
  const tabs = h("div", { class: "look-filter-tabs", role: "tablist" },
    h("button", { class: "look-tab", "data-cat": "all", "aria-pressed": String(S.lookCategory === "all"),
      onclick: () => setLookFilter("all") }, "All Cameras"),
    h("button", { class: "look-tab", "data-cat": "film", "aria-pressed": String(S.lookCategory === "film"),
      onclick: () => setLookFilter("film") }, "🎞️ Film Cameras"),
    h("button", { class: "look-tab", "data-cat": "digital", "aria-pressed": String(S.lookCategory === "digital"),
      onclick: () => setLookFilter("digital") }, "📷 Digital Cameras")
  );

  return h("div", {},
    tabs,
    h("div", { id: "looks" }),
    h("div", { class: "grid2", style: "margin-top:1rem" }, h("div", {},
      h("label", { for: "strength" }, "Look intensity ", h("span", { id: "lookv", class: "val" }, "100%")),
      h("input", { type: "range", id: "strength", min: 0, max: 400, value: 100, disabled: true, title: "Double-click resets to 100%",
        ondblclick: e => { e.target.value = 100; S.strength = 1.0; if ($("#lookv")) $("#lookv").textContent = "100%"; scheduleLiveTone(); schedulePreview(); },
        oninput: e => { S.strength = e.target.value / 100; if ($("#lookv")) $("#lookv").textContent = Math.round(S.strength * 100) + "%"; scheduleLiveTone(); schedulePreview(); } }))));
}

function renderLooks() {
  hideLookTooltip();
  const container = $("#looks");
  if (!container || !S.catalog || !S.catalog.camera_looks) return;
  const allLooks = S.catalog.camera_looks;
  const cat = S.lookCategory || "all";

  const filmLooks = allLooks.filter(l => l.category === "film" || FILM_LOOK_IDS.has(l.id));
  const digitalLooks = allLooks.filter(l => !(l.category === "film" || FILM_LOOK_IDS.has(l.id)));

  if (cat === "film") {
    container.replaceChildren(
      h("div", { class: "cards" }, ...filmLooks.map(makeLookCard))
    );
  } else if (cat === "digital") {
    container.replaceChildren(
      h("div", { class: "cards" }, ...digitalLooks.map(makeLookCard))
    );
  } else {
    container.replaceChildren(
      h("div", { class: "look-category" },
        h("div", { class: "look-category-head" },
          h("span", {}, "🎞️ Film Cameras · Analog Classics"),
          h("small", {}, `${filmLooks.length} profiles`)
        ),
        h("div", { class: "cards" }, ...filmLooks.map(makeLookCard))
      ),
      h("div", { class: "look-category" },
        h("div", { class: "look-category-head" },
          h("span", {}, "📷 Digital Cameras · CCD & Modern Sensors"),
          h("small", {}, `${digitalLooks.length} profiles`)
        ),
        h("div", { class: "cards" }, ...digitalLooks.map(makeLookCard))
      )
    );
  }
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
  const scenes = [
    { id: "", label: "All scenes" },
    { id: "street", label: "Street" },
    { id: "portrait", label: "Portrait" },
    { id: "golden_hour", label: "Golden hour" },
    { id: "night", label: "Night" },
    { id: "neon", label: "Neon" },
    { id: "cinematic", label: "Cinematic" },
    { id: "landscape", label: "Landscape" },
    { id: "fashion", label: "Fashion" }
  ];
  const chips = h("div", { class: "chips", id: "combochips", style: "margin-bottom:.6rem;flex-wrap:wrap;gap:.35rem" },
    ...scenes.map(s => h("button", {
      type: "button",
      class: "combo-chip",
      "data-scene": s.id,
      "aria-pressed": String((s.id === "" && !S.comboSceneFilter) || (S.comboSceneFilter === s.id)),
      onclick: () => { S.comboSceneFilter = s.id; combosChipsSync(); renderFx(); }
    }, s.label))
  );
  const search = h("input", {
    type: "search",
    id: "combosearch",
    placeholder: "Search presets and bundles (name, camera, film, effect)...",
    style: "margin-bottom:.6rem;width:100%",
    oninput: e => { S.comboQuery = e.target.value.toLowerCase().trim(); renderFx(); }
  });

  const presetGroup = h("div", { class: "preset-group" },
    h("div", { class: "group-head" },
      h("span", {}, "✦ Presets & bundles"),
      h("small", {}, "sets look, film and optics together · active selection is framed in gold")),
    search,
    chips,
    h("div", { class: "cards", id: "presetcards" }));

  const divider = h("div", { class: "fx-divider", role: "separator" });
  const fxGroup = h("div", { class: "effects-group" },
    h("div", { class: "group-head" },
      h("span", {}, "Individual optical effects"),
      h("small", {}, "combinable · grouped by stage · active effects highlighted")),
    h("div", { class: "fx-group-container", id: "fxgroups" }));

  const strength = h("input", { type: "range", id: "fxstrength", min: 0, max: 400, value: 50, "aria-label": "Optical effects strength", title: "Double-click resets to 0.50",
    ondblclick: e => { e.target.value = 50; S.fxStrength = 0.5; $("#fxv").textContent = "0.50"; scheduleLiveTone(); schedulePreview(); },
    oninput: e => { S.fxStrength = e.target.value / 100; $("#fxv").textContent = S.fxStrength.toFixed(2); scheduleLiveTone(); schedulePreview(); } });
  const policy = h("select", { id: "policy", onchange: e => { S.policy = e.target.value; renderFxWarnings(); schedulePreview(); } },
    h("option", { value: "film" }, "film: the film stock owns halation"), h("option", { value: "optical" }, "optical: replaces the film's halation"),
    h("option", { value: "stacked" }, "stacked: film + optical (deliberate)"), h("option", { value: "disabled" }, "disabled: no halation at all"));
  const vpolicy = h("select", { id: "vpolicy", onchange: e => { S.vpolicy = e.target.value; renderFxWarnings(); schedulePreview(); } },
    h("option", { value: "film" }, "film: film stock owns vignetting"),
    h("option", { value: "optical" }, "optical: replaces film vignette with optical vignetting"),
    h("option", { value: "stacked" }, "stacked: combine film and optical falloff"),
    h("option", { value: "disabled" }, "disabled: no vignetting"));
  const warnings = h("div", { id: "fx_warnings", style: "margin-top:.7rem" });

  return h("div", {},
    h("p", { class: "dim", style: "margin-top:0" }, "Effects run on scene-linear light before the look and film, in the engine's fixed order. Presets and bundles configure look, film and optics together; individual controls remain fully editable."),
    presetGroup, divider, fxGroup, h("div", { class: "grid2", style: "margin-top:1rem" },
      h("div", {}, h("label", { for: "fxstrength" }, "Effects strength ", h("span", { id: "fxv", class: "val" }, "0.50")), strength),
      h("div", {}, h("label", { for: "policy" }, "Halation policy"), policy),
      h("div", { style: "grid-column: 1 / -1; margin-top:.4rem" }, h("label", { for: "vpolicy" }, "Vignetting policy"), vpolicy)),
    warnings);
}

const FX_STAGE_GROUPS = [
  { id: "diffusion", name: "Diffusion & Glow", ids: ["soft_sun_glow", "black_pro_mist_like", "warm_diffusion"] },
  { id: "flares", name: "Flares & Streaks", ids: ["lens_flare_ghosting", "starburst_cross_screen", "anamorphic_streak", "horizontal_streak_blue"] },
  { id: "artifacts", name: "Light & Film Artifacts", ids: ["analog_light_leaks", "light_leak_warm", "film_halation_extra"] },
  { id: "lens", name: "Lens Character", ids: ["optical_vignetting", "vintage_glass_barrel_distortion", "vintage_glass_chromatic_aberration", "vintage_glass_edge_softness"] },
  { id: "focus", name: "Creative Focus", ids: ["lensbaby_sweet_spot", "tilt_shift_miniature"] }
];

function renderFxWarnings() {
  const box = $("#fx_warnings"); if (!box) return;
  const warns = [];
  if (S.policy === "optical" && !S.fx.has("film_halation_extra")) {
    warns.push("Halation policy 'optical' is active, but film_halation_extra is not in the optical stack.");
  }
  if (S.vpolicy === "optical" && !S.fx.has("optical_vignetting")) {
    warns.push("Vignette policy 'optical' is active, but optical_vignetting is not in the optical stack (falls back to film vignetting).");
  }
  if (S.fx.size > 5) {
    warns.push(`Heavy optical stack: ${S.fx.size} active effects. Previews and development may take longer.`);
  }
  if (!warns.length) {
    box.replaceChildren();
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.replaceChildren(
    h("div", { style: "font-size:.76rem;color:var(--safe2);background:rgba(255,138,61,.1);border:1px solid rgba(255,138,61,.3);padding:.4rem .6rem;border-radius:2px;display:flex;flex-direction:column;gap:.2rem" },
      ...warns.map(w => h("div", {}, "⚠ " + w))
    )
  );
}

function renderFx() {
  const pbox = $("#presetcards"), gbox = $("#fxgroups");
  if (!S.catalog) return;
  combosChipsSync();
  if (pbox) {
    const q = (S.comboQuery || "").trim().toLowerCase();
    const sf = S.comboSceneFilter || "";

    // 1. Curated combinations (all 21 presets)
    const comboCards = (S.combos || []).filter(c => {
      if (sf && !comboMatchesScene(c, sf)) return false;
      if (q) {
        const hay = [
          c.id, c.name, c.category, c.camera_look, c.film, c.film_resolved,
          c.intent, c.best_for, ...(c.scenes || []), ...(c.suggested_tags || []),
          ...(Array.isArray(c.optical) ? c.optical : [])
        ].join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    }).map(c => {
      const on = S.comboPreset === c.id;
      const lookName = (c.camera_look || "").replace(/_/g, " ");
      const filmName = (c.film_resolved || c.film || "no film").replace(/[-_]/g, " ");
      const fxNames = (Array.isArray(c.optical) && c.optical.length)
        ? c.optical.map(o => o.replace(/_/g, " ")).join(", ")
        : "no fx";
      const summary = `${lookName} + ${filmName} + ${fxNames}`;
      const badgeText = "#" + (c.category || (c.scenes && c.scenes[0]) || "PRESET").toUpperCase();

      return h("button", {
        type: "button",
        class: "card preset-card",
        "aria-pressed": String(on),
        title: `${c.name}: ${c.intent || c.best_for || summary}`,
        onclick: () => selectCombo(c)
      },
        h("span", { class: "badge" }, badgeText),
        h("strong", {}, c.name),
        h("small", {}, summary)
      );
    });

    // 2. Optical bundles (golden_haze, vintage_glass)
    const optPresets = S.catalog.optical_presets.filter(p => p.id !== "none").filter(p => {
      if (sf) return false;
      if (q) {
        const hay = [p.id, p.name].join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    }).map(p => {
      const on = S.fxPreset === p.id && S.activePreset === "opt:" + p.id;
      const isVG = p.id === "vintage_glass";
      const desc = isVG
        ? "Barrel Distortion + Chromatic Aberration + Edge Softness"
        : "Soft Sun Glow + Black Pro-Mist (keeps Look & Film)";
      return h("button", {
        type: "button",
        class: "card preset-card",
        "aria-pressed": String(on),
        "aria-disabled": String(!p.supported),
        title: "Applies the optical bundle without changing Camera Look or Film",
        onclick: () => {
          if (!p.supported) return toast(`${p.name}: not available`);
          if (on) {
            S.activePreset = null; S.fxPreset = "none"; S.fx.clear();
          } else {
            S.activePreset = "opt:" + p.id; S.fxPreset = p.id;
            if (p.id === "golden_haze") {
              S.fx = new Set(["soft_sun_glow", "black_pro_mist_like"]);
            } else if (p.id === "vintage_glass") {
              S.fx = new Set(["vintage_glass_barrel_distortion", "vintage_glass_chromatic_aberration", "vintage_glass_edge_softness"]);
            } else {
              S.fx = new Set();
            }
          }
          syncControls(); schedulePreview();
        }
      },
        h("span", { class: "badge" }, "#BUNDLE"),
        h("strong", {}, p.name),
        h("small", {}, desc)
      );
    });

    // 3. Legacy composites (if any)
    const legacyComposites = (S.catalog.composites || []).filter(c => {
      if (sf) return false;
      if (q) {
        const hay = [c.id, c.name, c.camera_look, c.film, c.optical_preset].join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    }).map(c => {
      const on = isCompositeActive(c);
      const summary = [c.camera_look !== "neutral" ? c.camera_look.replace(/_/g, " ") : "neutral look", c.film, c.optical_preset.replace(/_/g, " ")].filter(Boolean).join(" + ");
      return h("button", {
        type: "button",
        class: "card preset-card",
        "aria-pressed": String(on),
        title: "Sets camera look, film and optical effect together",
        onclick: () => {
          if (on) {
            S.activePreset = null; S.fxPreset = "none"; S.fx.clear(); S.policy = "film"; S.comboPreset = null;
            resetAllFrameOverrides();
            loadFrameAdjustments(S.current);
            syncControls(); renderAssets(); schedulePreview(true); toast("Preset cleared: " + c.name);
            return;
          }
          S.activePreset = c.id;
          S.comboPreset = null;
          S.look = c.camera_look; S.strength = c.look_strength;
          const f = c.film && findFilmId(c.film); if (f) S.film = f;
          if (c.optical_preset === "golden_haze") {
            S.fxPreset = "golden_haze"; S.fx = new Set(["soft_sun_glow", "black_pro_mist_like"]);
          } else if (c.optical_preset === "vintage_glass") {
            S.fxPreset = "vintage_glass"; S.fx = new Set(["vintage_glass_barrel_distortion", "vintage_glass_chromatic_aberration", "vintage_glass_edge_softness"]);
          } else {
            S.fxPreset = "none"; S.fx = new Set([c.optical_preset]);
          }
          S.fxStrength = c.optical_strength; S.policy = c.halation_policy || "film";
          resetAllFrameOverrides();
          loadFrameAdjustments(S.current);
          syncControls(); renderAssets(); schedulePreview(true); toast("Applied preset: " + c.name);
        }
      },
        h("span", { class: "badge" }, "#COMPOSITE"),
        h("strong", {}, c.name),
        h("small", {}, summary)
      );
    });

    const allCards = [...comboCards, ...optPresets, ...legacyComposites];
    if (allCards.length === 0) {
      pbox.replaceChildren(h("div", { class: "dim", style: "grid-column:1/-1;padding:.6rem;text-align:center;font-size:.78rem" }, "No presets found matching filter."));
    } else {
      pbox.replaceChildren(...allCards);
    }
  }

  if (gbox) {
    const allFx = new Map(S.catalog.optical_effects.map(o => [o.id, o]));
    const groupElements = FX_STAGE_GROUPS.map(grp => {
      const groupItems = grp.ids.map(id => allFx.get(id)).filter(Boolean);
      if (!groupItems.length) return null;
      const cards = groupItems.map(o => {
        const inPreset = (S.fxPreset === "golden_haze" && (o.id === "soft_sun_glow" || o.id === "black_pro_mist_like"))
          || (S.fxPreset === "vintage_glass" && (o.id === "vintage_glass_barrel_distortion" || o.id === "vintage_glass_chromatic_aberration" || o.id === "vintage_glass_edge_softness"));
        const on = inPreset || S.fx.has(o.id);
        return h("button", { class: "card fx-card", "aria-pressed": String(on), "aria-disabled": String(!o.supported), onclick: () => {
          if (!o.supported) return toast(`${o.name}: not available`);
          if (S.fxPreset === "golden_haze") {
            S.fxPreset = "none";
            S.fx = new Set(["soft_sun_glow", "black_pro_mist_like"]);
          } else if (S.fxPreset === "vintage_glass") {
            S.fxPreset = "none";
            S.fx = new Set(["vintage_glass_barrel_distortion", "vintage_glass_chromatic_aberration", "vintage_glass_edge_softness"]);
          }
          S.activePreset = null;
          S.comboPreset = null;
          if (on) {
            S.fx.delete(o.id);
            if (S.fxParams) delete S.fxParams[o.id];
          } else {
            S.fx.add(o.id);
          }
          if (o.id === "film_halation_extra") S.policy = S.fx.has(o.id) ? "optical" : "film";
          if (o.id === "optical_vignetting") S.vpolicy = S.fx.has(o.id) ? "optical" : "film";
          syncControls(); schedulePreview(); } },
          h("span", { class: "badge" }, inPreset ? "In bundle" : "Effect"),
          h("strong", {}, o.name),
          h("small", {}, o.category ? o.category.replace(/_/g, " ") : "optical effect"));
      });
      return h("div", { class: "fx-stage-group" },
        h("div", { class: "fx-group-title" },
          h("span", {}, grp.name),
          h("small", { class: "dim" }, `${groupItems.length} ops`)),
        h("div", { class: "cards" }, ...cards));
    }).filter(Boolean);
    gbox.replaceChildren(...groupElements);
  }
  renderFxWarnings();
}
function syncControls() {
  renderLooks(); renderFilms(); renderFx(); renderGrades(); renderFrameGrade();
  if ($("#strength")) { $("#strength").disabled = S.look === "neutral"; $("#strength").value = Math.round(S.strength * 100); if ($("#lookv")) $("#lookv").textContent = Math.round(S.strength * 100) + "%"; }
  if ($("#fxstrength")) { $("#fxstrength").value = Math.round(S.fxStrength * 100); $("#fxv").textContent = S.fxStrength.toFixed(2); }
  if ($("#gradestrength")) {
    const isNone = !S.colorGrade || S.colorGrade.mode === "none";
    const st = (S.colorGrade && S.colorGrade.strength !== undefined) ? S.colorGrade.strength : 1.0;
    $("#gradestrength").disabled = isNone;
    $("#gradestrength").value = Math.round(st * 100);
    if ($("#gradev")) $("#gradev").textContent = Math.round(st * 100) + "%";
  }
  ["grain", "halation", "softness"].forEach(k => {
    const el = $("#sl_" + k), val = $("#v_" + k);
    if (el) el.value = Math.round((S[k] !== undefined ? S[k] : 1) * 100);
    if (val) val.textContent = (S[k] !== undefined ? S[k] : 1).toFixed(2);
  });
  if ($("#policy")) $("#policy").value = S.policy;
  if ($("#vpolicy")) $("#vpolicy").value = S.vpolicy || "film";
  S.sliders.forEach(x => { x.inp.value = x.get(); x.out.textContent = x.fmt(x.get()); });
  const none = S.film === "none";
  ["#sl_grain", "#sl_halation", "#sl_softness", "#sl_develop"].forEach(q => { const i = $(q); if (i) i.disabled = none; });
  if ($("#filterstr")) { $("#filterstr").disabled = S.tone.filter === "none"; $("#filter").value = S.tone.filter; }
  if ($("#wbsel")) { renderWb(); }
  syncRotateUi();
  renderPresets();

  const sg = v => (v > 0 ? "+" : "") + v.toFixed(2) + " EV";
  if ($("#sl_bright")) $("#sl_bright").value = S.tone.brightness;
  if ($("#v_bright")) $("#v_bright").textContent = sg(S.tone.brightness);
  if ($("#chk_auto_exposure")) $("#chk_auto_exposure").checked = isFrameAutoExposure(S.current);
  if ($("#chk_auto_wb")) $("#chk_auto_wb").checked = isFrameAutoWb(S.current);

  const curAsset = S.assets.find(a => a.asset_id === S.current);
  const rawBadge = $("#badge_raw_ev");
  if (rawBadge && curAsset && curAsset.meta) {
    const meta = curAsset.meta;
    const parts = [];
    if (meta.baseline_ev !== undefined && Math.abs(meta.baseline_ev) > 1e-4) {
      parts.push(`RAW: ${(meta.baseline_ev > 0 ? "+" : "") + meta.baseline_ev.toFixed(2)} EV`);
    }
    if (meta.iso) parts.push(`ISO ${meta.iso}`);
    rawBadge.textContent = parts.length ? `(${parts.join(" · ")})` : "";
  }
  updateFrameNavUi();
}

/* ---------------- step 5: operator presets (the whole Darkroom setting under a name, stored on the server) ---------------- */
const PRESET_V = 1;
let userPresets = [], activeUserPreset = null;
function snapshotState() {
  return { v: PRESET_V, look: S.look, strength: S.strength, film: S.film, grain: S.grain, halation: S.halation, softness: S.softness,
    fxPreset: S.fxPreset, fx: [...S.fx], fxStrength: S.fxStrength, policy: S.policy, vpolicy: S.vpolicy, comboPreset: S.comboPreset, fxParams: { ...S.fxParams }, activePreset: S.activePreset,
    colorGrade: S.colorGrade ? { ...S.colorGrade } : { mode: "none" },
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
  S.vpolicy = ["film", "optical", "stacked", "disabled"].includes(st.vpolicy) ? st.vpolicy : "film";
  S.comboPreset = st.comboPreset || null;
  S.fxParams = (st.fxParams && typeof st.fxParams === "object") ? { ...st.fxParams } : {};
  S.activePreset = st.activePreset || null;
  S.colorGrade = (st.colorGrade && typeof st.colorGrade === "object") ? { ...st.colorGrade } : { mode: "none" };
  saveColorGrade();
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
/* ---------------- step 5: creative color grades ---------------- */
function gradesPanel() {
  const tagList = [
    { id: "", label: "All grades" },
    { id: "VSCO", label: "VSCO" },
    { id: "Instagram Classics", label: "Instagram Classics" },
    { id: "Matte", label: "Matte" },
    { id: "Vintage", label: "Vintage" },
    { id: "Portrait", label: "Portrait" },
    { id: "Editorial", label: "Editorial" },
    { id: "Pastel", label: "Pastel" },
    { id: "Cinematic", label: "Cinematic" },
    { id: "Moody", label: "Moody" },
    { id: "Warm", label: "Warm" },
    { id: "Cool", label: "Cool" },
    { id: "Earthy", label: "Earthy" },
    { id: "Faded", label: "Faded" },
    { id: "Monochrome", label: "Monochrome" }
  ];

  const chips = h("div", { class: "chips", id: "gradechips", style: "margin-bottom:.6rem;flex-wrap:wrap;gap:.35rem" },
    ...tagList.map(t => h("button", {
      type: "button",
      class: "combo-chip",
      "data-tag": t.id,
      "aria-pressed": String((t.id === "" && !S.colorGradeFilter) || (S.colorGradeFilter === t.id)),
      onclick: () => { S.colorGradeFilter = t.id; gradeChipsSync(); renderGrades(); }
    }, t.label))
  );

  const search = h("input", {
    type: "search",
    id: "gradesearch",
    placeholder: "Search color grades (name, style, category)...",
    style: "margin-bottom:.6rem;width:100%",
    oninput: e => { S.colorGradeQuery = e.target.value.toLowerCase().trim(); renderGrades(); }
  });

  const cardsContainer = h("div", { class: "cards", id: "gradecards" });
  const overridesBar = h("div", { id: "grade_overrides_bar", style: "margin-top:.5rem;font-size:.78rem", class: "dim" });

  const curStrength = (S.colorGrade && S.colorGrade.strength !== undefined) ? S.colorGrade.strength : 1.0;
  const isNone = !S.colorGrade || S.colorGrade.mode === "none";
  const strengthInp = h("input", {
    type: "range",
    id: "gradestrength",
    min: 0,
    max: 400,
    value: Math.round(curStrength * 100),
    disabled: isNone,
    "aria-label": "Grade intensity",
    title: "Double-click resets to 100%",
    ondblclick: e => {
      e.target.value = 100;
      if (S.colorGrade && S.colorGrade.mode === "preset") {
        S.colorGrade.strength = 1.0;
        saveColorGrade();
      }
      if ($("#gradev")) $("#gradev").textContent = "100%";
      schedulePreview(true);
    },
    oninput: e => {
      const val = e.target.value / 100;
      if (S.colorGrade && S.colorGrade.mode === "preset") {
        S.colorGrade.strength = val;
        saveColorGrade();
      }
      if ($("#gradev")) $("#gradev").textContent = Math.round(val * 100) + "%";
      schedulePreview(true);
    }
  });

  const controls = h("div", { class: "grid2", style: "margin-top:1rem" },
    h("div", {},
      h("label", { for: "gradestrength" }, "Grade intensity ", h("span", { id: "gradev", class: "val" }, Math.round(curStrength * 100) + "%")),
      strengthInp
    )
  );

  return h("div", {}, chips, search, overridesBar, cardsContainer, controls);
}

function gradeChipsSync() {
  const container = $("#gradechips");
  if (!container) return;
  for (const b of container.querySelectorAll("button[data-tag]")) {
    const t = b.getAttribute("data-tag");
    b.setAttribute("aria-pressed", String((t === "" && !S.colorGradeFilter) || (S.colorGradeFilter === t)));
  }
}

function renderGrades() {
  const box = $("#gradecards");
  if (!box || !S.catalog || !S.catalog.color_grades) return;

  const overridesCount = S.frameGradeOverrides ? Object.keys(S.frameGradeOverrides).length : 0;
  const obar = $("#grade_overrides_bar");
  if (obar) {
    if (overridesCount > 0) {
      obar.replaceChildren(
        h("span", {}, `Batch default applies to inheriting frames. ${overridesCount} frame(s) have individual overrides. `),
        h("button", { class: "ghost compact", style: "font-size:.72rem;padding:.15rem .4rem", onclick: resetAllFrameGradeOverrides }, "Reset all frame overrides")
      );
    } else {
      obar.replaceChildren();
    }
  }

  const query = (S.colorGradeQuery || "").toLowerCase();
  const filterTag = (S.colorGradeFilter || "").toLowerCase();

  const presets = S.catalog.color_grades.filter(p => {
    if (filterTag && !p.tags.some(t => t.toLowerCase() === filterTag)) return false;
    if (query) {
      const match = p.name.toLowerCase().includes(query) ||
                    (p.description || "").toLowerCase().includes(query) ||
                    (p.category || "").toLowerCase().includes(query) ||
                    p.tags.some(t => t.toLowerCase().includes(query));
      if (!match) return false;
    }
    return true;
  });

  const isGlobalNone = !S.colorGrade || S.colorGrade.mode === "none";
  const noneCard = h("button", {
    type: "button",
    class: "card" + (isGlobalNone ? " on" : ""),
    "aria-pressed": String(isGlobalNone),
    onclick: () => {
      S.colorGrade = { mode: "none" };
      saveColorGrade();
      syncControls();
      renderGrades();
      renderFrameGrade();
      schedulePreview(true);
    }
  },
    h("strong", {}, "None"),
    h("small", { class: "dim" }, "No creative color grade (natural camera look / film stock)")
  );

  const presetCards = presets.map(p => {
    const isSelected = S.colorGrade && S.colorGrade.mode === "preset" && S.colorGrade.preset_id === p.id;
    const tagSpans = (p.tags || []).map(t => h("span", { class: "tag", style: "margin-right:.25rem" }, t));
    const provClassification = p.provenance ? p.provenance.classification : "";

    return h("button", {
      type: "button",
      class: "card" + (isSelected ? " on" : ""),
      "aria-pressed": String(isSelected),
      onclick: () => {
        if (isSelected) {
          S.colorGrade = { mode: "none" };
          toast(`Color grade cleared: ${p.name}`);
        } else {
          const oldStrength = (S.colorGrade && S.colorGrade.strength !== undefined) ? S.colorGrade.strength : 1.0;
          S.colorGrade = {
            mode: "preset",
            preset_id: p.id,
            preset_version: p.version || "1.0.0",
            strength: oldStrength,
            overrides: {}
          };
          toast(`Applied grade: ${p.name}`);
        }
        saveColorGrade();
        syncControls();
        renderGrades();
        renderFrameGrade();
        schedulePreview(true);
      }
    },
      h("strong", {}, p.name),
      h("small", {}, p.description),
      h("div", { style: "margin-top:.35rem" }, ...tagSpans),
      provClassification ? h("small", { class: "dim", style: "display:block;margin-top:.2rem;font-size:.68rem" }, provClassification) : null
    );
  });

  box.replaceChildren(noneCard, ...presetCards);
}

function resetAllFrameGradeOverrides() {
  if (confirm("Reset all individual frame color grade overrides to inherit global?")) {
    S.frameGradeOverrides = {};
    saveFrameGrades();
    renderAssets();
    renderGrades();
    renderFrameGrade();
    schedulePreview(true);
    toast("All frame grade overrides reset to global");
  }
}

function renderFrameGrade() {
  const sel = $("#framesel_grade");
  if (!sel || !S.catalog || !S.catalog.color_grades) return;
  const curId = S.current;
  const globalMode = S.colorGrade ? S.colorGrade.mode : "none";
  const globalPid = (globalMode === "preset" && S.colorGrade) ? S.colorGrade.preset_id : null;
  const globalPreset = globalPid ? S.catalog.color_grades.find(x => x.id === globalPid) : null;
  const globalName = globalPreset ? globalPreset.name : (globalMode === "none" ? "None" : globalPid);

  const fo = curId && S.frameGradeOverrides ? S.frameGradeOverrides[curId] : null;
  const isIndividual = !!fo;

  // 1. Inherit option
  const inheritLabel = `Use Global: ${globalName} — Inherited`;
  const inheritOpt = h("option", { value: "__inherit__" }, inheritLabel);
  // 2. None (this frame)
  const noneOpt = h("option", { value: "__none__" }, "None (this frame)");
  // 3. Preset groups
  const presetOpts = S.catalog.color_grades.map(p => h("option", { value: p.id }, p.name));

  sel.replaceChildren(
    inheritOpt,
    noneOpt,
    h("optgroup", { label: "All Color Grades" }, ...presetOpts)
  );

  if (!isIndividual) {
    sel.value = "__inherit__";
  } else if (fo.mode === "none") {
    sel.value = "__none__";
  } else if (fo.mode === "preset") {
    sel.value = fo.preset_id;
  }

  // Update UI tags
  const indTag = $("#tag_individual_grade");
  if (indTag) indTag.hidden = !isIndividual;
  const resetBtn = $("#btn_reset_grade");
  if (resetBtn) resetBtn.hidden = !isIndividual;

  // Effective style tags
  const eff = getEffectiveFrameGrade(curId);
  const tagsBox = $("#grade_style_tags");
  if (tagsBox) {
    if (eff && eff.mode === "preset") {
      const p = S.catalog.color_grades.find(x => x.id === eff.preset_id);
      if (p && p.tags && p.tags.length) {
        tagsBox.textContent = `Style tags: ${p.tags.join(" · ")}`;
      } else {
        tagsBox.textContent = "";
      }
    } else {
      tagsBox.textContent = "No color grade applied to this frame";
    }
  }

  // Update frame grade intensity slider
  const sBox = $("#frame_grade_slider_box");
  const sInp = $("#sl_frame_gradestrength");
  const sVal = $("#v_frame_gradestr");
  if (sBox && sInp && sVal) {
    if (!eff || eff.mode === "none") {
      sBox.hidden = true;
    } else {
      sBox.hidden = false;
      const st = eff.strength !== undefined ? eff.strength : 1.0;
      sInp.value = Math.round(st * 100);
      sVal.textContent = Math.round(st * 100) + "%";
    }
  }
}

function onFrameGradeStrengthChange(val) {
  if (!S.current) return;
  if (!S.frameGradeOverrides) S.frameGradeOverrides = {};
  const curFo = S.frameGradeOverrides[S.current];
  if (curFo && curFo.mode === "preset") {
    curFo.strength = val;
  } else if (!curFo && S.colorGrade && S.colorGrade.mode === "preset") {
    S.frameGradeOverrides[S.current] = {
      mode: "preset",
      preset_id: S.colorGrade.preset_id,
      preset_version: S.colorGrade.preset_version || "1.0.0",
      strength: val,
      overrides: {}
    };
  }
  saveFrameGrades();
  renderAssets();
  renderFrameGrade();
  schedulePreview(true);
}

function onFrameGradeChange(val) {
  if (!S.current) return;
  if (val === "__inherit__") {
    resetFrameGrade();
    return;
  }
  if (!S.frameGradeOverrides) S.frameGradeOverrides = {};
  if (val === "__none__") {
    S.frameGradeOverrides[S.current] = { mode: "none" };
  } else {
    const existingSt = (S.frameGradeOverrides[S.current] && S.frameGradeOverrides[S.current].strength !== undefined)
      ? S.frameGradeOverrides[S.current].strength
      : ((S.colorGrade && S.colorGrade.strength !== undefined) ? S.colorGrade.strength : 1.0);
    S.frameGradeOverrides[S.current] = {
      mode: "preset",
      preset_id: val,
      preset_version: "1.0.0",
      strength: existingSt,
      overrides: {}
    };
  }
  saveFrameGrades();
  renderAssets();
  renderFrameGrade();
  schedulePreview(true);
}

function resetFrameGrade() {
  if (!S.current || !S.frameGradeOverrides) return;
  delete S.frameGradeOverrides[S.current];
  saveFrameGrades();
  renderAssets();
  renderFrameGrade();
  schedulePreview(true);
}

const AI_SAMPLE_PRESETS = [
  { id: "warm_sunset", name: "Warm Sunset", color: "#e07a5f", desc: "Golden hour warmth with lifted shadows" },
  { id: "moody_film", name: "Moody Film", color: "#3d5a80", desc: "Deep cinematic blues and muted greens" },
  { id: "tokyo_neon", name: "Tokyo Neon", color: "#b5179e", desc: "Vibrant magenta and teal contrast" },
  { id: "nordic_teal", name: "Nordic Teal", color: "#2a9d8f", desc: "Clean, desaturated cool tones" },
  { id: "vintage_sepia", name: "Vintage Sepia", color: "#d4a373", desc: "Warm monochrome nostalgic tone" },
];

function neuralStudioPanel() {
  const pureBtn = h("button", {
    type: "button",
    class: "compat-pill" + (S.aiMode === "pure" ? " active" : ""),
    onclick: () => setAiMode("pure")
  }, "⚡ Pure AI Mode");
  const hybridBtn = h("button", {
    type: "button",
    class: "compat-pill" + (S.aiMode === "hybrid" ? " active" : ""),
    onclick: () => setAiMode("hybrid")
  }, "🔀 Hybrid (AI + Film & Optics)");

  const compatHelp = h("p", { class: "dim", style: "font-size:.76rem;margin:.4rem 0 0;line-height:1.4" },
    S.aiMode === "pure"
      ? "Pure AI Mode: Output is processed directly through neural models without classical film curves or optical diffusion."
      : "Hybrid Mode: Neural models clean sensor noise and balance tones first, then selected Film Stocks and Optical Effects apply on top."
  );

  const compatBox = h("div", { class: "neural-compat-box" },
    h("div", { class: "neural-compat-row" },
      h("span", { style: "font-size:.82rem;font-weight:600" }, "Pipeline Workflow:"),
      h("div", { class: "compat-pills" }, pureBtn, hybridBtn)
    ),
    compatHelp
  );

  function setAiMode(m) {
    S.aiMode = m;
    localStorage.setItem("mfilm.ai_mode", m);
    pureBtn.className = "compat-pill" + (m === "pure" ? " active" : "");
    hybridBtn.className = "compat-pill" + (m === "hybrid" ? " active" : "");
    compatHelp.textContent = (m === "pure")
      ? "Pure AI Mode: Output is processed directly through neural models without classical film curves or optical diffusion."
      : "Hybrid Mode: Neural models clean sensor noise and balance tones first, then selected Film Stocks and Optical Effects apply on top.";
    schedulePreview(true);
  }

  // --- Section 1: Auto Enhancement (Lightweight Model) ---
  const aeToggle = h("input", {
    type: "checkbox",
    id: "ai_ae_enabled",
    checked: S.aiAutoEnhance,
    onchange: e => {
      S.aiAutoEnhance = e.target.checked;
      aeCard.className = "ai-section-card" + (S.aiAutoEnhance ? " active" : "");
      schedulePreview(true);
    }
  });
  const aeStyleSelect = h("select", {
    id: "ai_ae_style",
    style: "font-family:var(--mono);font-size:.78rem;padding:.2rem .4rem",
    onchange: e => {
      S.aiAutoEnhanceStyle = e.target.value;
      schedulePreview(true);
    }
  },
    h("option", { value: "standard", selected: S.aiAutoEnhanceStyle === "standard" }, "Standard / Natural Balance"),
    h("option", { value: "vivid", selected: S.aiAutoEnhanceStyle === "vivid" }, "Vivid & Dynamic Range"),
    h("option", { value: "portrait", selected: S.aiAutoEnhanceStyle === "portrait" }, "Soft Portrait (Skin-Aware)"),
    h("option", { value: "cinematic", selected: S.aiAutoEnhanceStyle === "cinematic" }, "Cinematic Warmth")
  );
  const aeStrVal = h("span", { class: "ai-val-box" }, Math.round(S.aiAutoEnhanceStrength * 100) + "%");
  const aeStrSlider = h("input", {
    type: "range",
    min: "0",
    max: "100",
    value: Math.round(S.aiAutoEnhanceStrength * 100),
    oninput: e => {
      S.aiAutoEnhanceStrength = parseFloat(e.target.value) / 100.0;
      aeStrVal.textContent = e.target.value + "%";
      schedulePreview(true);
    }
  });

  const aeCard = h("div", { class: "ai-section-card" + (S.aiAutoEnhance ? " active" : "") },
    h("div", { class: "ai-section-head" },
      h("label", { class: "ai-section-title", style: "cursor:pointer" },
        aeToggle,
        h("span", {}, "1. Auto Enhancement"),
        h("span", { class: "ai-badge" }, "3D LUT · ~500 KB · 3 ms")
      )
    ),
    h("div", { class: "ai-control-group" },
      h("div", { style: "display:flex;align-items:center;justify-content:space-between" },
        h("label", { style: "font: .78rem var(--mono);color:var(--dim)" }, "Tonal Profile:"),
        aeStyleSelect
      ),
      h("div", { class: "ai-slider-row" },
        h("label", {}, "Intensity:"),
        aeStrSlider,
        aeStrVal
      )
    )
  );

  // --- Section 2: Style by Reference (Sample Matching) ---
  const srToggle = h("input", {
    type: "checkbox",
    id: "ai_sr_enabled",
    checked: S.aiStyleRef,
    onchange: e => {
      S.aiStyleRef = e.target.checked;
      srCard.className = "ai-section-card" + (S.aiStyleRef ? " active" : "");
      schedulePreview(true);
    }
  });
  const srStrVal = h("span", { class: "ai-val-box" }, Math.round(S.aiStyleRefStrength * 100) + "%");
  const srStrSlider = h("input", {
    type: "range",
    min: "0",
    max: "100",
    value: Math.round(S.aiStyleRefStrength * 100),
    oninput: e => {
      S.aiStyleRefStrength = parseFloat(e.target.value) / 100.0;
      srStrVal.textContent = e.target.value + "%";
      schedulePreview(true);
    }
  });
  const srSkinCheck = h("input", {
    type: "checkbox",
    checked: S.aiStyleRefPreserveSkin,
    onchange: e => {
      S.aiStyleRefPreserveSkin = e.target.checked;
      schedulePreview(true);
    }
  });

  const refGallery = h("div", { class: "ref-gallery" },
    ...AI_SAMPLE_PRESETS.map(p => {
      const isSel = S.aiStyleRefId === p.id;
      const card = h("div", {
        class: "ref-thumb-card" + (isSel ? " selected" : ""),
        onclick: () => {
          S.aiStyleRefId = p.id;
          S.aiStyleRefName = p.name;
          refGallery.querySelectorAll(".ref-thumb-card").forEach(c => c.classList.remove("selected"));
          card.classList.add("selected");
          schedulePreview(true);
        }
      },
        h("div", { class: "ref-placeholder", style: `background: linear-gradient(135deg, ${p.color} 0%, #150f0d 100%)` }, "✦"),
        h("div", { class: "ref-thumb-label" }, p.name)
      );
      return card;
    })
  );

  const srCard = h("div", { class: "ai-section-card" + (S.aiStyleRef ? " active" : "") },
    h("div", { class: "ai-section-head" },
      h("label", { class: "ai-section-title", style: "cursor:pointer" },
        srToggle,
        h("span", {}, "2. Style by Reference"),
        h("span", { class: "ai-badge" }, "SA-LUT · 15 ms")
      )
    ),
    h("div", { class: "ai-control-group" },
      h("div", { style: "font: .78rem var(--mono);color:var(--dim)" }, "Choose style sample palette:"),
      refGallery,
      h("div", { class: "ai-slider-row" },
        h("label", {}, "Transfer Strength:"),
        srStrSlider,
        srStrVal
      ),
      h("label", { style: "display:inline-flex;align-items:center;gap:.5rem;font:.78rem var(--mono);cursor:pointer" },
        srSkinCheck,
        "Preserve natural portrait skin tones"
      )
    )
  );

  // --- Section 3: Large Neural Engine (Advanced / Heavy Models) ---
  const neToggle = h("input", {
    type: "checkbox",
    id: "ai_ne_enabled",
    checked: S.aiEngineEnabled,
    onchange: e => {
      S.aiEngineEnabled = e.target.checked;
      neCard.className = "ai-section-card" + (S.aiEngineEnabled ? " active" : "");
      schedulePreview(true);
    }
  });

  const neEngineSelect = h("select", {
    id: "ai_ne_engine",
    style: "font-family:var(--mono);font-size:.78rem;padding:.2rem .4rem",
    onchange: e => {
      S.aiEngineType = e.target.value;
      schedulePreview(true);
    }
  },
    h("option", { value: "rawnind", selected: S.aiEngineType === "rawnind" }, "RawNIND / NAFNet Sensor Denoise"),
    h("option", { value: "neural_isp", selected: S.aiEngineType === "neural_isp" }, "Modular Neural ISP (RAW Reconstruction)"),
    h("option", { value: "realesrgan", selected: S.aiEngineType === "realesrgan" }, "Real-ESRGAN Super-Resolution")
  );

  const chromaVal = h("span", { class: "ai-val-box" }, Math.round(S.aiChromaStrength * 100) + "%");
  const chromaSlider = h("input", {
    type: "range",
    min: "0",
    max: "100",
    value: Math.round(S.aiChromaStrength * 100),
    oninput: e => {
      S.aiChromaStrength = parseFloat(e.target.value) / 100.0;
      chromaVal.textContent = e.target.value + "%";
      schedulePreview(true);
    }
  });

  const lumaVal = h("span", { class: "ai-val-box" }, Math.round(S.aiLumaStrength * 100) + "%");
  const lumaSlider = h("input", {
    type: "range",
    min: "0",
    max: "100",
    value: Math.round(S.aiLumaStrength * 100),
    oninput: e => {
      S.aiLumaStrength = parseFloat(e.target.value) / 100.0;
      lumaVal.textContent = e.target.value + "%";
      schedulePreview(true);
    }
  });

  const detailVal = h("span", { class: "ai-val-box" }, Math.round(S.aiDetailPreserve * 100) + "%");
  const detailSlider = h("input", {
    type: "range",
    min: "0",
    max: "100",
    value: Math.round(S.aiDetailPreserve * 100),
    oninput: e => {
      S.aiDetailPreserve = parseFloat(e.target.value) / 100.0;
      detailVal.textContent = e.target.value + "%";
      schedulePreview(true);
    }
  });

  const neCard = h("div", { class: "ai-section-card" + (S.aiEngineEnabled ? " active" : "") },
    h("div", { class: "ai-section-head" },
      h("label", { class: "ai-section-title", style: "cursor:pointer" },
        neToggle,
        h("span", {}, "3. Large Neural Engine"),
        h("span", { class: "ai-badge" }, "Tesla V100 · 16 GB")
      )
    ),
    h("div", { class: "ai-control-group" },
      h("div", { style: "display:flex;align-items:center;justify-content:space-between" },
        h("label", { style: "font: .78rem var(--mono);color:var(--dim)" }, "Target Engine:"),
        neEngineSelect
      ),
      h("div", { class: "ai-slider-row" },
        h("label", {}, "Chroma Denoise:"),
        chromaSlider,
        chromaVal
      ),
      h("div", { class: "ai-slider-row" },
        h("label", {}, "Luma Denoise:"),
        lumaSlider,
        lumaVal
      ),
      h("div", { class: "ai-slider-row" },
        h("label", {}, "Detail Retention:"),
        detailSlider,
        detailVal
      )
    )
  );

  return h("div", {},
    compatBox,
    aeCard,
    srCard,
    neCard
  );
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
function exposureControl() {
  const sg = v => (v > 0 ? "+" : "") + v.toFixed(2) + " EV";
  const valSpan = h("span", { id: "v_bright", class: "val" }, sg(S.tone.brightness));
  const rawBadge = h("small", { id: "badge_raw_ev", class: "dim", style: "font-size:.72rem;margin-left:.35rem" });
  const chk = h("input", {
    type: "checkbox",
    id: "chk_auto_exposure",
    checked: isFrameAutoExposure(S.current),
    onchange: e => onToggleAutoExposure(e.target.checked)
  });
  const chkLabel = h("label", {
    style: "font-size:.78rem;cursor:pointer;display:inline-flex;align-items:center;gap:.25rem;margin:0;font-weight:normal"
  }, chk, "Auto");

  const header = h("div", {
    style: "display:flex;align-items:center;justify-content:space-between;margin-bottom:.2rem"
  },
    h("label", { for: "sl_bright", style: "margin:0" }, "Exposure compensation ", valSpan, rawBadge),
    chkLabel
  );

  const inp = h("input", {
    type: "range",
    id: "sl_bright",
    min: -3,
    max: 3,
    step: 0.05,
    value: S.tone.brightness,
    "aria-label": "Exposure compensation in stops",
    title: "Double-click resets to 0. Moving slider switches Auto off.",
    oninput: e => {
      setFrameAutoExposure(S.current, false);
      const c = $("#chk_auto_exposure"); if (c) c.checked = false;
      S.tone.brightness = +e.target.value;
      valSpan.textContent = sg(S.tone.brightness);
      markFrameAdjusted();
      scheduleLiveTone();
    },
    ondblclick: () => {
      setFrameAutoExposure(S.current, false);
      const c = $("#chk_auto_exposure"); if (c) c.checked = false;
      S.tone.brightness = 0;
      inp.value = 0;
      valSpan.textContent = sg(0);
      markFrameAdjusted();
      scheduleLiveTone();
    }
  });

  return h("div", {}, header, inp);
}

function onToggleAutoExposure(checked) {
  setFrameAutoExposure(S.current, checked);
  if (checked) {
    const autoEv = getFrameAutoExposureVal(S.current);
    S.tone.brightness = autoEv;
    const inp = $("#sl_bright"); if (inp) inp.value = autoEv;
    const v = $("#v_bright"); if (v) v.textContent = (autoEv > 0 ? "+" : "") + autoEv.toFixed(2) + " EV";
    markFrameAdjusted();
    scheduleLiveTone();
    toast(`Auto exposure applied: ${(autoEv > 0 ? "+" : "") + autoEv.toFixed(2)} EV`);
  } else {
    markFrameAdjusted();
  }
}

function onToggleAutoWb(checked) {
  setFrameAutoWb(S.current, checked);
  if (checked) {
    const awb = getFrameAutoWbData(S.current);
    if (awb && awb.kelvin) {
      S.wbSel = "custom";
      S.wbCustom.k = awb.kelvin;
      S.wbCustom.t = awb.tint;
      markFrameAdjusted();
      renderWb();
      schedulePreview(true);
      toast(`Auto white balance applied: ${awb.kelvin} K, tint ${awb.tint > 0 ? "+" : ""}${awb.tint}`);
    } else {
      S.wbSel = "as-shot";
      markFrameAdjusted();
      renderWb();
      schedulePreview(true);
      toast("Auto white balance: camera as-shot");
    }
  } else {
    markFrameAdjusted();
  }
}

function applyWbToAll() {
  const curWbSel = S.wbSel;
  const curWbCustom = { ...S.wbCustom };
  const curAutoWb = isFrameAutoWb(S.current);
  S.baseWbSel = curWbSel;
  S.baseWbCustom = { ...curWbCustom };
  for (const a of S.assets) {
    if (!S.adjustments[a.asset_id]) {
      S.adjustments[a.asset_id] = {
        tone: { ...S.baseTone, brightness: getFrameAutoExposureVal(a.asset_id) },
        autoExposure: isFrameAutoExposure(a.asset_id)
      };
    }
    S.adjustments[a.asset_id].wbSel = curWbSel;
    S.adjustments[a.asset_id].wbCustom = { ...curWbCustom };
    S.adjustments[a.asset_id].autoWb = curAutoWb;
  }
  saveAdjustments();
  renderAssets();
  renderWb();
  schedulePreview(true);
  toast(`White balance applied to all ${S.assets.length} frames on table`);
}

function adjustPanel() {
  S.sliders = [];
  const filter = h("select", { id: "filter", "aria-label": "Tone filter", onchange: e => { S.tone.filter = e.target.value; markFrameAdjusted(); syncControls(); scheduleLiveTone(); } },
    h("option", { value: "none" }, "No filter"), h("option", { value: "grayscale" }, "Black & white (plain grayscale)"), h("option", { value: "silver" }, "Silver B&W film (grain, film curve)"), h("option", { value: "sepia" }, "Sepia"));
  const wbsel = h("select", { id: "wbsel", "aria-label": "White balance", onchange: e => {
    S.wbSel = e.target.value;
    S.wb = S.wbSel === "as-shot" ? "as-shot" : "daylight";
    setFrameAutoWb(S.current, false);
    const c = $("#chk_auto_wb"); if (c) c.checked = false;
    markFrameAdjusted();
    renderWb();
    schedulePreview(true);
  } });
  const file = h("input", { type: "file", id: "wbfile", multiple: true, hidden: true, accept: ".json,.csv,.xmp,.lrtemplate,.pp3", onchange: wbImport });

  const gradeSel = h("select", { id: "framesel_grade", "aria-label": "Creative Color Grade", onchange: e => onFrameGradeChange(e.target.value) });
  const gradeResetBtn = h("button", { id: "btn_reset_grade", class: "ghost compact", hidden: true, style: "font-size:.72rem;padding:.2rem .4rem;margin-left:.4rem", onclick: () => resetFrameGrade() }, "Reset to Global");
  const gradeIndTag = h("span", { id: "tag_individual_grade", class: "tag", hidden: true, style: "background:var(--safe,#d86e3b);color:#fff;font-weight:600;padding:.12rem .35rem;border-radius:2px;font-size:.7rem;margin-left:.4rem" }, "Individual");
  const gradeStyleTags = h("div", { id: "grade_style_tags", class: "dim", style: "font-size:.74rem;margin-top:.2rem" });

  return h("div", { class: "adjust-box" },
    h("h3", { class: "sub-head" }, "Adjustments ", h("small", { class: "dim" }, "· real-time in preview & full render")),
    h("div", { class: "adjust-stack" },
      exposureControl(),
      slider("sl_contrast", "Contrast", -1, 1, 0.01, () => S.tone.contrast, v => { S.tone.contrast = v; markFrameAdjusted(); }, v => Math.round(v * 100) + "%", 0, "S-curve around the mid-tones.", true),
      slider("sl_develop", "Development strength", 0, 1, 0.01, () => S.tone.develop, v => { S.tone.develop = v; markFrameAdjusted(); }, v => Math.round(v * 100) + "%", 1, "0 % = developed without film, 100 % = the full film look.", true),
      h("div", { class: "grid2-compact", style: "margin-top:.2rem" },
        h("div", {}, h("label", { for: "filter" }, "Filter"), filter,
          h("div", { style: "margin-top:.3rem" }, slider("filterstr", "Strength", 0, 1, 0.01, () => S.tone.filterStrength, v => { S.tone.filterStrength = v; markFrameAdjusted(); }, v => Math.round(v * 100) + "%", 1, "Filter blend strength.", true))),
        h("div", {},
          h("div", { style: "display:flex;align-items:center;justify-content:space-between;margin-bottom:.2rem" },
            h("label", { for: "wbsel", style: "margin:0" }, "White balance"),
            h("label", { style: "font-size:.78rem;cursor:pointer;display:inline-flex;align-items:center;gap:.25rem;margin:0;font-weight:normal" },
              h("input", {
                type: "checkbox",
                id: "chk_auto_wb",
                checked: isFrameAutoWb(S.current),
                onchange: e => onToggleAutoWb(e.target.checked)
              }),
              "Auto"
            )
          ),
          wbsel,
          h("div", { class: "bar compact", style: "margin-top:.3rem;gap:.3rem;flex-wrap:wrap" },
            h("button", { onclick: () => $("#wbfile").click(), title: "Import .json .csv .xmp .lrtemplate .pp3" }, "Import profile…"),
            h("button", { id: "btn_wb_all", type: "button", onclick: applyWbToAll, title: "Apply current frame's white balance to all frames on table" }, "Apply WB to all"),
            h("button", { id: "wbdel", hidden: true, onclick: wbDelete }, "Delete"),
            file
          )
        )
      ),
      h("div", { id: "wbcustom", hidden: true, style: "margin-top:.2rem" },
        slider("sl_kelvin", "Light colour temperature", 2000, 12000, 50, () => S.wbCustom.k, v => { S.wbCustom.k = v; setFrameAutoWb(S.current, false); const c = $("#chk_auto_wb"); if (c) c.checked = false; markFrameAdjusted(); }, v => v + " K", 5500),
        slider("sl_tint", "Tint (− green · + magenta)", -100, 100, 1, () => S.wbCustom.t, v => { S.wbCustom.t = v; setFrameAutoWb(S.current, false); const c = $("#chk_auto_wb"); if (c) c.checked = false; markFrameAdjusted(); }, v => (v > 0 ? "+" : "") + v, 0)),
      h("p", { class: "dim", id: "wbnote", style: "font:.68rem var(--mono);margin:.1rem 0 0" }),
      h("div", { style: "margin-top:.4rem;padding-top:.4rem;border-top:1px solid var(--line)" },
        h("div", { style: "display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.3rem" },
          h("label", { for: "framesel_grade", style: "font-weight:600;display:flex;align-items:center" }, "Creative Color Grade", gradeIndTag),
          gradeResetBtn
        ),
        h("div", { style: "margin-top:.25rem" }, gradeSel),
        h("div", { id: "frame_grade_slider_box", style: "margin-top:.35rem", hidden: true },
          h("label", { for: "sl_frame_gradestrength" }, "Grade intensity ", h("span", { id: "v_frame_gradestr", class: "val" }, "100%")),
          h("input", {
            type: "range",
            id: "sl_frame_gradestrength",
            min: 0,
            max: 400,
            value: 100,
            "aria-label": "Frame grade intensity",
            title: "Double-click resets to 100%",
            ondblclick: () => onFrameGradeStrengthChange(1.0),
            oninput: e => onFrameGradeStrengthChange(e.target.value / 100)
          })
        ),
        gradeStyleTags
      ),
      h("div", { class: "bar compact", style: "margin-top:.4rem;padding-top:.4rem;border-top:1px solid var(--line)" },
        h("button", { onclick: resetAdjust, title: "Reset adjustments for this frame back to preset/defaults" }, "Reset adjustments"),
        h("button", { onclick: adjustAll, title: "Apply adjustments of this frame to all selected frames" }, "Apply to all selected"),
        h("button", { onclick: everythingOff, title: "Neutral look, no optics, no film, no filter, no adjustments: the plain developed RAW" }, "Everything off"))
    ));
}
function renderWb() {
  const sel = $("#wbsel"); if (!sel) return;
  const L = S.wbl || { builtin: [], imported: [] }, groups = {};
  L.builtin.forEach(p => (groups[p.group] = groups[p.group] || []).push(p));
  sel.replaceChildren(h("option", { value: "daylight" }, "Daylight (standard, decoder)"), h("option", { value: "as-shot" }, "As shot (camera)"), h("option", { value: "custom" }, "Custom Kelvin / tint…"),
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
    wbCustom: { ...S.wbCustom },
    autoExposure: isFrameAutoExposure(S.current),
    autoWb: isFrameAutoWb(S.current)
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
  S.colorGrade = { mode: "none" }; saveColorGrade();
  S.frameGradeOverrides = {}; saveFrameGrades();
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

  const btnStagePrev = h("button", {
    type: "button",
    id: "stage_prev",
    class: "stage-nav stage-prev",
    title: "Previous frame (Left Arrow)",
    "aria-label": "Previous frame",
    onclick: (e) => { e.stopPropagation(); prevFrame(); }
  }, "◀");

  const btnStageNext = h("button", {
    type: "button",
    id: "stage_next",
    class: "stage-nav stage-next",
    title: "Next frame (Right Arrow)",
    "aria-label": "Next frame",
    onclick: (e) => { e.stopPropagation(); nextFrame(); }
  }, "▶");

  const stage = h("div", { class: "stage", id: "stage" },
    h("div", { class: "layer" }, treatedCanvas, treated),
    h("div", { class: "layer", id: "beforeLayer" }, before),
    cut,
    btnStagePrev,
    btnStageNext,
    h("div", { class: "layer", id: "cropLayer", hidden: true }),
    h("span", { class: "busy", id: "busy" }),
    h("span", { class: "dim", id: "empty" }, "Upload a RAW to see a preview")
  );
  let pos = 50;
  const setCut = p => { pos = Math.max(0, Math.min(100, p)); cut.style.left = pos + "%"; $("#beforeLayer").style.clipPath = `inset(0 ${100 - pos}% 0 0)`; cut.setAttribute("aria-valuenow", Math.round(pos)); };
  setTimeout(() => setCut(50));
  const move = ev => { const r = stage.getBoundingClientRect(); setCut(100 * (ev.clientX - r.left) / r.width); };
  cut.addEventListener("pointerdown", e => { cut.setPointerCapture(e.pointerId); cut.addEventListener("pointermove", move); });
  cut.addEventListener("pointerup", () => cut.removeEventListener("pointermove", move));
  cut.addEventListener("keydown", e => { if (e.key === "ArrowLeft") setCut(pos - 3); if (e.key === "ArrowRight") setCut(pos + 3); });

  const navGroup = h("span", { class: "pv-nav-group", role: "group", "aria-label": "Frame navigation", style: "display:inline-flex;align-items:center;gap:.3rem" },
    h("button", { type: "button", id: "pv_prev", class: "compact", onclick: prevFrame, title: "Previous frame (Left Arrow)" }, "◀ Previous"),
    h("span", { id: "pv_frame_counter", class: "dim", style: "font:.76rem var(--mono);padding:0 .2rem;white-space:nowrap" }, ""),
    h("button", { type: "button", id: "pv_next", class: "compact", onclick: nextFrame, title: "Next frame (Right Arrow)" }, "Next ▶")
  );

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
  return h("div", {}, h("div", { class: "bar", style: "margin:0 0 .6rem;gap:.4rem;flex-wrap:wrap;align-items:center" },
    navGroup,
    h("label", { for: "pvsize", style: "margin:0 .1rem 0 .3rem" }, "Size"), h("select", { id: "pvsize", style: "width:auto", onchange: () => schedulePreview(true) },
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
      api("/previews", { method: "POST", json: { asset_id: S.current, kind: "before", max_edge: edge, stream: "before", white_balance: S.wb,
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
    if (st.status === "SUPERSEDED") return;
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
      // Symmetric scaling relative to crop center
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
      const assetDesc = targetAssets.length > 1 ? "one of the selected frames" : "the frame";
      toast(`⚠️ Size ${origLabel} exceeds resolution of ${assetDesc} (${minMaxEdge}×${minMinEdge}). Automatically adjusted to: ${fit.label}.`);
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
  return h("div", { class: "develop-box" },
    h("h3", { class: "sub-head" }, "Develop ", h("small", { class: "dim" }, "· full size from original RAW")),
    h("div", { class: "develop-stack" },
      h("div", { class: "grid2-compact" },
        h("div", {}, h("label", { for: "outsize" }, "Output size"), sizeSel),
        h("div", {}, h("label", { for: "q" }, "JPEG quality"), h("input", { type: "number", id: "q", min: 1, max: 100, value: 92, onchange: e => { S.quality = Number(e.target.value); } }))),
      destPanel(),
      h("div", { class: "bar", style: "margin-top:.6rem" },
        h("button", { class: "primary", id: "develop", style: "flex:1 1 auto;padding:.6rem 1.2rem;font-size:.88rem", onclick: develop }, "Develop selected"),
        h("span", { class: "dim", id: "devinfo", style: "font-size:.78rem" }))
    ));
}

let jobsHistoryCollapsed = false;
function toggleJobsCollapse() {
  jobsHistoryCollapsed = !jobsHistoryCollapsed;
  const el = $("#jobs_history_wrapper");
  const btn = $("#btn_toggle_jobs_history");
  if (el) el.hidden = jobsHistoryCollapsed;
  if (btn) btn.textContent = jobsHistoryCollapsed ? "▸ Expand history" : "▾ Collapse history";
}

function jobsPanel() {
  return h("div", { class: "jobs-panel" },
    h("div", { class: "active-job-container" },
      h("div", { class: "jobs-section-title" },
        h("span", {}, "Active processing"),
        h("span", { class: "dim", id: "active_job_status_label" }, "")),
      h("div", { id: "active_job_card" },
        h("p", { class: "dim", style: "font:.78rem var(--mono);margin:.4rem 0" }, "No active jobs running."))
    ),
    h("div", { style: "display:flex;align-items:center;justify-content:space-between;border-top:1px solid var(--line);padding-top:.6rem;margin-top:.4rem" },
      h("span", { style: "font:600 .78rem var(--mono);color:var(--ink);letter-spacing:.04em;text-transform:uppercase" }, "Job & Rendition History"),
      h("button", { id: "btn_toggle_jobs_history", style: "font-size:.74rem;padding:.25rem .55rem", onclick: toggleJobsCollapse },
        jobsHistoryCollapsed ? "▸ Expand history" : "▾ Collapse history")
    ),
    h("div", { id: "jobs_history_wrapper", hidden: jobsHistoryCollapsed },
      h("div", { class: "jobs-section-title", style: "margin-top:.6rem" }, h("span", {}, "Recent jobs")),
      h("div", { class: "jobs", id: "jobs" }),
      h("div", { class: "jobs-section-title", style: "margin-top:1rem" },
        h("span", {}, "History of renditions"),
        h("span", { class: "dim", style: "font-size:.7rem" }, "re-download or publish")),
      h("p", { class: "dim", style: "font:.72rem var(--mono);margin:0 0 .5rem" }, "Every recipe gives its own file; nothing is overwritten. Publish uses the destination chosen in Develop."),
      h("div", { class: "jobs", id: "history" })
    )
  );
}
function updateDevelop() { const b = $("#develop"); if (!b) return; b.disabled = S.selected.size === 0; $("#devinfo").textContent = S.selected.size ? `${S.selected.size} frame(s) → ${S.selected.size} JPEG` : "select at least one frame"; }
function destPanel() {
  const mode = h("select", { id: "dest", onchange: () => { const on = $("#dest").value !== "none"; $("#destbox").hidden = !on; if (on) loadDestAlbums(); } },
    h("option", { value: "none" }, "Save on the server only (download later)"), h("option", { value: "pp" }, "Publish to PhotoPrism"));
  return h("div", { style: "margin-top:.7rem" }, h("label", { for: "dest" }, "Destination (independent of sources)"), mode,
    h("div", { id: "destbox", hidden: true, class: "grid2-compact", style: "margin-top:.55rem" },
      h("div", {}, h("label", { for: "dfolder" }, "Output folder under originals (blank = managed default)"), h("input", { type: "text", id: "dfolder", placeholder: "Chromurgy/Developed/<year>/<job>" })),
      h("div", {}, h("label", { for: "dalbum" }, "Album"), h("select", { id: "dalbum" }, h("option", { value: "" }, "No album")),
        h("input", { type: "text", id: "dnew", placeholder: "…or a new album name", style: "margin-top:.35rem" }))));
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
      if (S.frameGradeOverrides && S.frameGradeOverrides[a.asset_id]) {
        item.creative_color_grade = S.frameGradeOverrides[a.asset_id];
      }
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
    toast(`Job queued (${j.total} frame${j.total === 1 ? "" : "s"})`);
    switchRightTab("jobs");
    refreshJobs(true);
  } catch (e) { toast(e.message); }
}
let jobsTimer;
async function refreshJobs(force = false) {
  clearTimeout(jobsTimer);
  let list; try { list = await api("/jobs?count=15"); } catch (e) { return; }
  const full = await Promise.all(list.items.map(j => api("/jobs/" + j.job_id)));

  const activeJobs = full.filter(j => ["QUEUED", "RUNNING", "PUBLISHING"].includes(j.state));
  const activeCard = $("#active_job_card");
  const tabBtnJobs = $("#tab_btn_jobs");
  if (tabBtnJobs) {
    tabBtnJobs.textContent = activeJobs.length ? `⚙ Jobs (${activeJobs.length} active)` : "⚙ Jobs & History";
  }
  if (activeCard) {
    if (activeJobs.length > 0) {
      activeCard.replaceChildren(...activeJobs.map(jobCard));
    } else {
      activeCard.replaceChildren(h("p", { class: "dim", style: "font:.78rem var(--mono);margin:.4rem 0" }, "No active jobs running."));
    }
  }

  const box = $("#jobs"); if (!box) return;
  const typing = !force && document.activeElement && box.contains(document.activeElement) && document.activeElement.tagName === "INPUT";
  if (!typing) box.replaceChildren(...full.map(jobCard));
  refreshHistory();
  if (activeJobs.length > 0) jobsTimer = setTimeout(refreshJobs, 2500);
  else jobsTimer = setTimeout(refreshJobs, 15000);
}
async function refreshHistory() {
  const box = $("#history"); if (!box) return;
  let r; try { r = await api("/history?count=30"); } catch (e) { return; }
  box.replaceChildren(...(r.items.length ? r.items.map(x => h("div", { class: "job" }, h("header", {}, h("b", {}, x.filename), h("span", { class: "dim" },
      `${x.film} · ${x.camera_look} · ${x.optical} · ${x.width}×${x.height} · ${(x.bytes / 1048576).toFixed(1)} MB · ${x.created_at.slice(0, 16).replace("T", " ")}`)),
    h("div", { class: "acts" },
      h("button", { class: "session-load-btn", title: "Load this frame and recipe into editor", onclick: () => loadHistoryRender(x) }, "↺ Load"),
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
  acts.append(h("button", { class: "session-load-btn", title: "Load session: restore frames, recipe, crop and target album into editor", onclick: () => loadSession(j) }, "↺ Load session"));
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
      return toast("No frames in this session");
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
              ? `Album "${albumTitle}" not found in PhotoPrism (deleted) and will be recreated.`
              : "Target album not found in PhotoPrism and will be recreated.");
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
    toast(`Session loaded: ${items.length} frames, film ${S.film}`);
  } catch (e) {
    toast("Failed to load session: " + e.message);
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
    toast(`Frame ${x.filename} loaded into editor`);
  } catch (e) {
    toast("Failed to load frame: " + e.message);
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

/* Keyboard navigation for quick frame switching (Left Arrow = Previous, Right Arrow = Next) */
window.addEventListener("keydown", e => {
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  const tag = (document.activeElement && document.activeElement.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return;
  if (document.activeElement && document.activeElement.id === "cut") return;
  if (e.key === "ArrowLeft") {
    e.preventDefault();
    prevFrame();
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    nextFrame();
  }
});

/* ---------------- Service Worker & PWA Registration ---------------- */
function setupPwa() {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/darkroom/sw.js", { scope: "/darkroom/" })
        .catch(() => {});
    });
  }
}

setupPwa();
boot();
