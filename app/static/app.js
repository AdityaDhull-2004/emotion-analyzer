// Emotion Analyzer web UI (spec §5.4, v1.5). Three tabs:
//   Try it        record (level meter, timer, Space), upload or drop a file, demo clips with
//                 their true labels and Run all demos, and this session's history;
//   How it works  the pipeline diagram with the last analysis's stage timings;
//   Results       built from GET /api/report, the aggregates in results/ (§5.3).
// Plain JavaScript with no libraries, so the page works offline.
"use strict";

const LABELS = ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"];
const EMOJI = {anger: "😠", disgust: "🤢", fear: "😨", joy: "😄", neutral: "😐", sadness: "😢", surprise: "😲"};
const ADJECTIVE = {anger: "angry", disgust: "disgusted", fear: "afraid", joy: "happy",
                   neutral: "neutral", sadness: "sad", surprise: "surprised"};
const BRANCH = {sound: "👂 Sound", text: "💬 Words", fused: "Fused"};
const STAGES = [["decode", "Decode + VAD"], ["encode", "Whisper encoder"], ["transcribe", "Transcript"],
                ["sound", "Sound head"], ["text", "Text model"], ["fusion", "Fusion"]];
const MAX_RECORD_S = 120;
const MAX_HISTORY = 30;
const TABS = ["try", "how", "results"];

const $ = (id) => document.getElementById(id);
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Builds an element. Strings become text nodes, so nothing is ever parsed as HTML.
function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  setProps(node, props);
  return append(node, children);
}

const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, props = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  setProps(node, props);
  return append(node, children);
}

function setProps(node, props) {
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.setAttribute("class", v);
    else if (k === "style") {
      for (const [p, val] of Object.entries(v)) {
        if (p.startsWith("--")) node.style.setProperty(p, val);
        else node.style[p] = val;
      }
    } else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
}

function append(node, children) {
  for (const c of children.flat(Infinity)) {
    if (c !== null && c !== undefined && c !== false) node.append(c instanceof Node ? c : String(c));
  }
  return node;
}

const icon = (label) => h("span", {class: "emo-icon", "aria-hidden": "true"}, EMOJI[label]);
const emo = (label) => h("span", {class: `emo ${label}`}, icon(label), " ", label);
const pct = (x) => `${Math.round(100 * x)}%`;
const fix = (x, d = 1) => Number(x).toFixed(d);
const secs = (ms) => `${(ms / 1000).toFixed(2)} s`;
const signed = (x, d = 1) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(d)}`;
const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length ? (s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2) : 0;
};

// localStorage can be missing or throw (private windows, blocked storage): it only remembers the theme.
const store = {
  get(key) { try { return window.localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { window.localStorage.setItem(key, value); } catch { /* not remembered */ } },
};

// --- Theme -----------------------------------------------------------------------------

function effectiveTheme() {
  const t = document.documentElement.dataset.theme;
  if (t === "light" || t === "dark") return t;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function showThemeIcon() {
  const dark = effectiveTheme() === "dark";
  $("theme").textContent = dark ? "☀️" : "🌙";
  $("theme").setAttribute("aria-label", dark ? "Switch to the light theme" : "Switch to the dark theme");
}

{
  const saved = store.get("theme");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  showThemeIcon();
  $("theme").addEventListener("click", () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.set("theme", next);
    showThemeIcon();
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", showThemeIcon);
}

// --- Tabs (ARIA tabs pattern) --------------------------------------------------------------

function showTab(name, focus = false) {
  if (!TABS.includes(name)) name = "try";
  for (const t of TABS) {
    const on = t === name;
    const tab = $(`tab-${t}`);
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    $(`panel-${t}`).hidden = !on;
  }
  if (focus) $(`tab-${name}`).focus();
  if (name === "results") animateFills($("report"));  // replay the bars each time the tab opens
  if (window.location.hash !== `#${name}`) window.history.replaceState(null, "", `#${name}`);
}

for (const t of TABS) $(`tab-${t}`).addEventListener("click", () => showTab(t));
document.querySelector(".tabs").addEventListener("keydown", (e) => {
  const i = TABS.findIndex((t) => $(`tab-${t}`).getAttribute("aria-selected") === "true");
  const next = {ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: TABS.length - 1}[e.key];
  if (next === undefined) return;
  e.preventDefault();
  showTab(TABS[(next + TABS.length) % TABS.length], true);
});
window.addEventListener("hashchange", () => showTab(window.location.hash.slice(1)));
showTab(window.location.hash.slice(1));

// --- State and controls ------------------------------------------------------------------

let busy = false;        // an analysis is running
let rec = null;          // the recording in progress
let demoRun = null;      // Run all demos in progress: {stop}
let samples = [];        // demo clips from /static/samples/index.json
const entries = [];      // this session's analyses, newest first
let shownId = null;
let nextId = 1;
let looseUrl = null;     // object URL of audio whose analysis failed (not in the history)
const canRecord = Boolean(window.isSecureContext && navigator.mediaDevices && window.MediaRecorder);

function refreshControls() {
  const blocked = busy || Boolean(rec) || Boolean(demoRun);
  $("record").disabled = !canRecord || busy || Boolean(demoRun);
  $("upload").disabled = blocked;
  document.querySelector('label[for="upload"]').classList.toggle("disabled", blocked);
  for (const s of samples) s.button.disabled = blocked;
  const runAll = $("run-all");
  runAll.disabled = !demoRun && blocked;
  runAll.textContent = demoRun ? "■ Stop" : "▶ Run all demos";
  runAll.classList.toggle("stop", Boolean(demoRun));
  for (const b of document.querySelectorAll(".history-item")) b.disabled = busy || Boolean(demoRun) || Boolean(rec);
  $("history-clear").disabled = Boolean(demoRun) || busy;
  document.body.classList.toggle("busy", busy);
}

function status(text, isError = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", isError);
}

function setPlayer(url) {
  const player = $("player");
  if (player.src !== url) player.src = url;
  player.hidden = false;
}

// Plays the clip in the page's player and resolves when it ends (or can't play).
function playClip(url) {
  const player = $("player");
  setPlayer(url);
  return new Promise((resolve) => {
    let timeout = null;
    const done = () => {
      player.removeEventListener("ended", done);
      player.removeEventListener("error", done);
      player.removeEventListener("pause", done);
      clearTimeout(timeout);
      resolve();
    };
    player.addEventListener("ended", done);
    player.addEventListener("error", done);
    timeout = setTimeout(done, 30000);
    player.currentTime = 0;
    player.play().then(() => player.addEventListener("pause", done)).catch(done);
  });
}

// --- Analysis ------------------------------------------------------------------------------

async function analyze(blob, filename, meta = {}) {
  if (busy) return null;
  busy = true;
  refreshControls();
  status(meta.statusText || "Analysing…");
  if (looseUrl) URL.revokeObjectURL(looseUrl);
  const url = URL.createObjectURL(blob);
  looseUrl = url;
  const form = new FormData();
  form.append("audio", blob, filename);
  const started = performance.now();
  try {
    const request = fetch("/api/analyze", {method: "POST", body: form}).then(async (res) => {
      const body = await res.json().catch(() => ({error: `HTTP ${res.status}`, detail: ""}));
      return {res, body, ms: performance.now() - started};
    });
    let out;
    if (meta.play) {
      status(`${meta.statusText || "Analysing"}: playing the clip…`);
      [out] = await Promise.all([request, playClip(url)]);
    } else {
      setPlayer(url);
      out = await request;
    }
    if (!out.res.ok) {
      status(`${out.body.error}${out.body.detail ? ": " + out.body.detail : ""}`, true);
      return null;
    }
    looseUrl = null;
    const r = out.body;
    const speech = Boolean(r.speech_detected && r.segments.length && r.overall);
    const entry = {id: nextId++, url, result: r, roundTripMs: out.ms, at: new Date(), source: meta.source || filename,
                   trueLabel: meta.trueLabel || null, speech,
                   right: Boolean(meta.trueLabel && speech && r.overall.label === meta.trueLabel)};
    entries.unshift(entry);
    while (entries.length > MAX_HISTORY) URL.revokeObjectURL(entries.pop().url);
    status("");
    show(entry);
    if (window.matchMedia("(max-width: 980px)").matches) {  // one column: the result is below the inputs
      $("results").scrollIntoView({behavior: reducedMotion() ? "auto" : "smooth", block: "start"});
    }
    return entry;
  } catch (err) {
    status(`Couldn't reach the server: ${err.message}`, true);
    return null;
  } finally {
    busy = false;
    refreshControls();
  }
}

function show(entry) {
  shownId = entry.id;
  render(entry);
  setPlayer(entry.url);
  updatePipeline(entry);
  renderHistory();
}

// --- Result cards ----------------------------------------------------------------------------

// Bars start empty and grow on the next frames, so the CSS transition animates them.
function animateFills(root) {
  const fills = root.querySelectorAll("[data-w]");
  for (const f of fills) f.style.width = "0";
  requestAnimationFrame(() => requestAnimationFrame(() => {
    for (const f of fills) f.style.width = f.dataset.w;
  }));
}

function probBars(listId, answer) {
  $(listId).replaceChildren(...LABELS.map((label) => {
    const p = answer ? answer.probs[label] : 0;
    return h("li", {class: `bar ${label}${answer && label === answer.label ? " top" : ""}`},
      h("span", {class: "name"}, icon(label), " ", label),
      h("span", {class: "track"}, h("span", {class: "fill", "data-w": pct(p)})),
      h("span", {class: "val"}, pct(p)));
  }));
}

// One segment shows its own branch; several show duration-weighted means.
function weighted(segments, key) {
  if (segments.length === 1) return segments[0][key];
  const probs = Object.fromEntries(LABELS.map((l) => [l, 0]));
  let total = 0;
  for (const s of segments) {
    const d = s.end_s - s.start_s;
    total += d;
    for (const l of LABELS) probs[l] += d * s[key].probs[l];
  }
  for (const l of LABELS) probs[l] /= total;
  const label = LABELS.reduce((a, b) => (probs[a] >= probs[b] ? a : b));
  return {label, confidence: probs[label], probs};
}

function branchLabel(entry, key) {
  if (!entry.speech) return null;
  return key === "fused" ? entry.result.overall.label : weighted(entry.result.segments, key).label;
}

function render(entry) {
  const r = entry.result;
  const seg = r.segments;
  const speech = entry.speech;
  $("placeholder").hidden = true;
  $("results").hidden = false;
  $("no-speech").hidden = speech;

  const label = speech ? r.overall.label : null;
  document.querySelector(".card.result").className = `card result ${label || "none"}`;
  $("fused-emoji").textContent = speech ? EMOJI[label] : "🤫";
  $("fused-label").textContent = speech ? label : "no speech";
  $("fused-meter").className = `meter-fill ${label || ""}`;
  $("fused-meter").dataset.w = speech ? pct(r.overall.confidence) : "0%";
  $("fused-conf").textContent = speech ? `Confidence ${pct(r.overall.confidence)} (calibrated)` : "";

  probBars("sound-bars", speech ? weighted(seg, "sound") : null);
  probBars("text-bars", speech ? weighted(seg, "text") : null);
  $("transcript").textContent = speech ? (seg.map((s) => s.transcript).join(" ").trim() || "(no words recognised)") : "—";

  const verdict = $("verdict");
  verdict.hidden = !entry.trueLabel;
  if (entry.trueLabel) {
    verdict.className = `verdict ${entry.right ? "right" : "wrong"}`;
    verdict.replaceChildren();
    append(verdict, [h("span", {class: "mark"}, entry.right ? "✓ Right" : "✗ Wrong"),
                     h("span", {}, "True label ", emo(entry.trueLabel)),
                     entry.right ? null : h("span", {}, "Predicted ", speech ? emo(label) : "no speech")]);
  }

  const disagree = seg.filter((s) => s.disagreement);
  const banner = $("banner");
  banner.hidden = !disagree.length;
  if (disagree.length) {
    const s = disagree[0];
    const where = seg.length > 1 ? ` (from ${s.start_s.toFixed(1)} s)` : "";
    banner.replaceChildren(h("strong", {}, `⚠️ Tone and words disagree${where}: `),
      `it sounds ${ADJECTIVE[s.sound.label]} ${EMOJI[s.sound.label]}, but the words read as ` +
      `${ADJECTIVE[s.text.label]} ${EMOJI[s.text.label]}.`);
  }

  const long = r.duration_s > 10 && seg.length > 0;
  $("timeline-card").hidden = !long;
  if (long) timeline(seg, r.duration_s);

  const t = r.timing_ms;
  $("timing").textContent = `Processed in ${secs(t.total)} on the server for ${r.duration_s.toFixed(1)} s of audio ` +
    `(${secs(entry.roundTripMs)} round trip). Stage times are on the How it works tab.`;

  animateFills($("results"));
  const pop = $("fused-emoji");
  pop.classList.remove("pop");
  void pop.offsetWidth;  // restart the animation
  pop.classList.add("pop");
}

function timeline(segments, duration) {
  $("timeline").replaceChildren(...segments.map((s) => h("span", {
    class: `block ${s.fused.label}`, title: `${s.start_s.toFixed(1)}–${s.end_s.toFixed(1)} s: ${s.fused.label}`,
    style: {left: `${(100 * s.start_s) / duration}%`, width: `${(100 * (s.end_s - s.start_s)) / duration}%`},
  }, EMOJI[s.fused.label])));
  $("segments").replaceChildren(...segments.map((s) => h("li", {},
    h("span", {class: "time"}, `${s.start_s.toFixed(1)}–${s.end_s.toFixed(1)} s`), " ",
    emo(s.fused.label), s.disagreement ? h("span", {class: "flag"}, "disagree") : null, " ",
    h("span", {class: "said"}, s.transcript ? `“${s.transcript}”` : ""))));
}

// --- History -----------------------------------------------------------------------------------

function renderHistory() {
  $("history-card").hidden = !entries.length;
  $("history").replaceChildren(...entries.map((e) => {
    const r = e.result;
    return h("li", {}, h("button", {
      type: "button", class: `history-item${e.id === shownId ? " active" : ""}`,
      "aria-current": e.id === shownId ? "true" : null, onclick: () => show(e)},
    h("span", {class: "h-time"}, e.at.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"})),
    e.speech ? emo(r.overall.label) : h("span", {class: "emo"}, "🤫 no speech"),
    e.speech ? h("span", {class: "h-conf"}, pct(r.overall.confidence)) : null,
    h("span", {class: "h-src"}, e.source),
    e.trueLabel ? h("span", {class: `h-mark ${e.right ? "right" : "wrong"}`, title: e.right ? "right" : "wrong"},
      e.right ? "✓" : "✗") : null));
  }));
  refreshControls();
}

$("history-clear").addEventListener("click", () => {
  for (const e of entries) if (e.id !== shownId) URL.revokeObjectURL(e.url);
  entries.length = 0;
  renderHistory();
});

// --- Upload and drag and drop -------------------------------------------------------------------

$("upload").addEventListener("change", (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (file) analyze(file, file.name, {source: file.name});
});

{
  let depth = 0;
  const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes("Files");
  const idle = () => !busy && !rec && !demoRun;
  window.addEventListener("dragenter", (e) => {
    if (!hasFiles(e)) return;
    depth += 1;
    document.body.classList.add("dragging");
  });
  window.addEventListener("dragleave", (e) => {
    if (!hasFiles(e)) return;
    depth = Math.max(0, depth - 1);
    if (!depth) document.body.classList.remove("dragging");
  });
  window.addEventListener("dragover", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();  // otherwise the browser opens the file
    e.dataTransfer.dropEffect = idle() ? "copy" : "none";
  });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth = 0;
    document.body.classList.remove("dragging");
    const file = e.dataTransfer.files[0];
    if (!file || !idle()) return;
    showTab("try");
    analyze(file, file.name, {source: file.name});
  });
}

// --- Recording (needs a secure context: HTTPS or localhost) --------------------------------------

function recordingType() {
  const options = [["audio/webm;codecs=opus", "webm"], ["audio/webm", "webm"],
                   ["audio/mp4", "m4a"], ["audio/ogg;codecs=opus", "ogg"]];
  for (const [type, ext] of options) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(type)) return {type, ext};
  }
  return {type: "", ext: "webm"};
}

const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}.${Math.floor((s * 10) % 10)}`;

// Live input level: RMS of the waveform in dB, mapped from −60..0 dB to 0..100%.
function startMeter(stream) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return null;
  try {
    const ctx = new Ctx();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analyser);
    return {ctx, analyser, buf: new Float32Array(analyser.fftSize), level: 0};
  } catch {
    return null;
  }
}

function tick() {
  if (!rec) return;
  const elapsed = (performance.now() - rec.t0) / 1000;
  $("rec-timer").textContent = clock(elapsed);
  if (rec.meter) {
    const m = rec.meter;
    m.analyser.getFloatTimeDomainData(m.buf);
    let sum = 0;
    for (const v of m.buf) sum += v * v;
    const db = 20 * Math.log10(Math.sqrt(sum / m.buf.length) + 1e-8);
    m.level = Math.max(Math.min(1, Math.max(0, (db + 60) / 60)), m.level * 0.9);
    $("level-fill").style.width = `${Math.round(100 * m.level)}%`;
    $("level-fill").classList.toggle("hot", db > -6);
  }
  rec.raf = requestAnimationFrame(tick);
}

async function startRecording() {
  if (!canRecord || busy || rec || demoRun) return;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio: true});
  } catch (err) {
    status(`Microphone unavailable: ${err.message}. Upload still works.`, true);
    return;
  }
  const {type, ext} = recordingType();
  const recorder = new MediaRecorder(stream, type ? {mimeType: type} : undefined);
  const chunks = [];
  rec = {recorder, stream, t0: performance.now(), meter: startMeter(stream), raf: 0, limit: 0};
  recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  recorder.onstop = () => {
    const r = rec;
    rec = null;
    cancelAnimationFrame(r.raf);
    clearTimeout(r.limit);
    r.stream.getTracks().forEach((t) => t.stop());
    if (r.meter) r.meter.ctx.close().catch(() => {});
    const seconds = (performance.now() - r.t0) / 1000;
    $("record").classList.remove("recording");
    $("record-label").textContent = "Record";
    $("rec-live").hidden = true;
    $("level-fill").style.width = "0";
    const mime = recorder.mimeType || type || "audio/webm";
    const blob = new Blob(chunks, {type: mime});
    refreshControls();
    analyze(blob, `recording.${mime.includes("mp4") ? "m4a" : ext}`, {source: `recording, ${seconds.toFixed(1)} s`});
  };
  recorder.start();
  rec.limit = setTimeout(stopRecording, MAX_RECORD_S * 1000);
  $("record").classList.add("recording");
  $("record-label").textContent = "Stop";
  $("rec-live").hidden = false;
  status("Recording… press Space or Stop when you're done.");
  refreshControls();
  rec.raf = requestAnimationFrame(tick);
}

function stopRecording() {
  if (rec && rec.recorder.state !== "inactive") rec.recorder.stop();
}

function toggleRecording() {
  if (rec) stopRecording();
  else startRecording();
}

$("record").addEventListener("click", toggleRecording);

if (!canRecord) {
  $("record").disabled = true;
  $("record-note").textContent = "Recording needs a secure connection (HTTPS or localhost). Upload still works.";
  $("record-note").hidden = false;
}

// Space starts and stops recording on the Try it tab, except while typing in a text field.
// Both key events are cancelled so a focused button or checkbox doesn't also react.
{
  const TEXT_INPUTS = /^(text|search|email|number|password|tel|url)$/;
  const typing = (t) => t && (t.isContentEditable || t.tagName === "TEXTAREA" || t.tagName === "SELECT" ||
                              (t.tagName === "INPUT" && TEXT_INPUTS.test(t.type)));
  const isSpace = (e) => (e.code === "Space" || e.key === " ") && !e.ctrlKey && !e.metaKey && !e.altKey;
  const applies = (e) => isSpace(e) && !typing(e.target) && !$("panel-try").hidden;
  window.addEventListener("keydown", (e) => {
    if (!applies(e)) return;
    e.preventDefault();
    if (!e.repeat) toggleRecording();
  }, true);
  window.addEventListener("keyup", (e) => { if (applies(e)) e.preventDefault(); }, true);
}

// --- Demo clips and Run all demos --------------------------------------------------------------

async function runSample(s, opts = {}) {
  let blob;
  try {
    const res = await fetch(`/static/samples/${encodeURIComponent(s.file)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    blob = await res.blob();
  } catch (err) {
    status(`Couldn't load the demo clip: ${err.message}`, true);
    return null;
  }
  const entry = await analyze(blob, s.file, {trueLabel: s.label, source: `demo: ${s.name}`, ...opts});
  if (entry) {
    s.button.classList.toggle("right", entry.right);
    s.button.classList.toggle("wrong", !entry.right);
    const mark = s.button.querySelector(".s-mark");
    mark.textContent = entry.right ? "✓" : "✗";
    mark.title = entry.right ? "right" : "wrong";
  }
  return entry;
}

async function runAllDemos() {
  if (demoRun) {
    demoRun.stop = true;
    $("player").pause();
    return;
  }
  if (busy || rec || !samples.length) return;
  demoRun = {stop: false};
  $("scoreboard-card").hidden = true;
  refreshControls();
  const done = [];
  for (const [i, s] of samples.entries()) {
    if (demoRun.stop) break;
    s.button.classList.add("current");
    const entry = await runSample(s, {play: $("play-demos").checked,
                                      statusText: `Demo ${i + 1} of ${samples.length}: ${s.name}`});
    s.button.classList.remove("current");
    if (entry) done.push({s, entry});
    if (!demoRun.stop && i < samples.length - 1) await sleep(1500);  // a moment to read the result
  }
  const stopped = demoRun.stop;
  demoRun = null;
  refreshControls();
  if (stopped) status(`Stopped after ${done.length} of ${samples.length} clips.`);
  scoreboard(done);
}

function scoreboard(done) {
  const card = $("scoreboard-card");
  card.hidden = !done.length;
  if (!done.length) return;
  const n = done.length;
  const right = (key) => done.filter(({s, entry}) => branchLabel(entry, key) === s.label).length;
  const cell = (entry, key, truth) => {
    const label = branchLabel(entry, key);
    return h("td", {class: label === truth ? "right" : "wrong"},
      label ? emo(label) : "—", " ", h("span", {class: "mark"}, label === truth ? "✓" : "✗"));
  };
  const fused = right("fused");
  $("scoreboard").replaceChildren(
    h("p", {class: "score-big"}, h("strong", {}, `${fused} / ${n}`), ` right (${Math.round((100 * fused) / n)}%)`),
    h("div", {class: "table-wrap"}, h("table", {class: "score-table"},
      h("thead", {}, h("tr", {}, h("th", {}, "True"), ...Object.values(BRANCH).map((b) => h("th", {}, b)),
                       h("th", {class: "num"}, "Time"))),
      h("tbody", {}, done.map(({s, entry}) => h("tr", {}, h("td", {}, emo(s.label)),
        ...Object.keys(BRANCH).map((k) => cell(entry, k, s.label)),
        h("td", {class: "num"}, secs(entry.result.timing_ms.total))))),
      h("tfoot", {}, h("tr", {}, h("th", {}, "Right"),
        ...Object.keys(BRANCH).map((k) => h("th", {}, `${right(k)} / ${n}`)),
        h("th", {class: "num"}, `median ${secs(median(done.map(({entry}) => entry.result.timing_ms.total)))}`))))),
    h("p", {class: "note"}, "Each column is one model on its own; the fused answer is what the app shows."));
  card.scrollIntoView({behavior: reducedMotion() ? "auto" : "smooth", block: "nearest"});
}

$("run-all").addEventListener("click", runAllDemos);

fetch("/static/samples/index.json")
  .then((r) => (r.ok ? r.json() : []))
  .then((list) => {
    const valid = list.filter((s) => LABELS.includes(s.label) && s.file);
    if (!valid.length) return;
    const count = {};
    samples = valid.map((s) => {
      count[s.label] = (count[s.label] || 0) + 1;
      return {...s};
    });
    const seen = {};
    for (const s of samples) {
      seen[s.label] = (seen[s.label] || 0) + 1;
      s.name = count[s.label] > 1 ? `${s.label} ${seen[s.label]}` : s.label;
      s.button = h("button", {type: "button", class: `sample ${s.label}`, title: `True label: ${s.label}`,
                              onclick: () => runSample(s)},
        h("span", {class: "s-emoji", "aria-hidden": "true"}, EMOJI[s.label]),
        h("span", {class: "s-label"}, s.name),
        h("span", {class: "s-mark"}));
    }
    $("sample-buttons").replaceChildren(...samples.map((s) => s.button));
    $("samples").hidden = false;
    refreshControls();
  })
  .catch(() => {});

// --- How it works ---------------------------------------------------------------------------------

function setText(id, text) {
  const node = $(id);
  if (node) node.textContent = text;
}

function updatePipeline(entry) {
  const r = entry.result;
  const t = r.timing_ms;
  for (const [key] of STAGES) setText(`t-${key}`, `${t[key]} ms`);
  const n = r.segments.length;
  setText("t-total", `total ${secs(t.total)} · ${r.duration_s.toFixed(1)} s of audio · ${n} segment${n === 1 ? "" : "s"}`);
  setText("d-answer", entry.speech ? `${EMOJI[r.overall.label]} ${r.overall.label} · ${pct(r.overall.confidence)}`
                                   : "🤫 no speech");
  const node = $("d-answer").closest(".node");
  node.setAttribute("class", `node answer ${entry.speech ? r.overall.label : ""}`);
  $("pipeline").classList.add("has-timings");
  $("diagram-note").textContent = `Timings from the last analysis (${entry.source}, ` +
    `${entry.at.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}). Stage times add up across segments.`;
}

function fillHow(rep) {
  const d = rep.deployed;
  if (d && d.available) {
    setText("d-temps", `T_sound ${fix(d.t_sound, 2)} · T_text ${fix(d.t_text, 2)} (fitted on MELD dev)`);
    setText("d-weight", `w_sound ${fix(d.w_sound, 2)} · w_text ${fix(1 - d.w_sound, 2)}`);
    weightChart(d);
  }
  const pc = rep.sections.per_class;
  if (pc && pc.available) {
    const s = pc.branches.sound.per_class;
    const t = pc.branches.text.per_class;
    const fmt = (l, a, b) => `${l} (F1 ${Math.round(a[l].f1)} against ${Math.round(b[l].f1)})`;
    const words = LABELS.filter((l) => t[l].f1 - s[l].f1 >= 2).map((l) => fmt(l, t, s));
    const voice = LABELS.filter((l) => s[l].f1 - t[l].f1 >= 2).map((l) => fmt(l, s, t));
    const list = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}` : xs[0]);
    if (words.length && voice.length) {
      setText("why-numbers", `On MELD test the words are better at ${list(words)}, and the voice is better at ${list(voice)}.`);
    }
    const g = pc.disagreement;
    if (g) {
      setText("why-disagree", `On MELD test the flag comes up on ${fix(g.flagged_pct)}% of clips. There the voice alone ` +
        `is right ${Math.round(g.sound_right_pct)}% of the time, the words ${Math.round(g.text_right_pct)}%, and the ` +
        `fused answer ${Math.round(g.fused_right_pct)}%, against ${Math.round(g.fused_right_other_pct)}% on the other clips.`);
    }
  }
  const rt = rep.sections.results_table;
  if (rt && rt.available && rt.gains) {
    const row = (k) => rt.rows.find((r) => r.row === k);
    const g = rt.gains["R7-R5"];
    if (row("R1") && row("R5") && row("R7") && g) {
      setText("why-gain", `On MELD test the fused system scores ${fix(row("R7").weighted_f1_mean)} weighted-F1, against ` +
        `${fix(row("R1").weighted_f1_mean)} for the voice alone and ${fix(row("R5").weighted_f1_mean)} for the words ` +
        `alone: ${signed(g.gain)} points (95% CI ${fix(g.ci_low)} to ${fix(g.ci_high)}).`);
    }
  }
}

// Weighted-F1 on the weight-fitting dev clips for every w_sound tried: the peak is the deployed weight.
function weightChart(d) {
  if (!d.grid || !d.grid.length) return;
  const W = 520, H = 220, L = 46, R = 14, T = 16, B = 44;
  const ys = d.grid.map(([, y]) => y);
  const lo = Math.floor(Math.min(...ys) / 5) * 5, hi = Math.ceil(Math.max(...ys) / 5) * 5;
  const x = (w) => L + w * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const best = d.grid.reduce((a, b) => (b[1] > a[1] ? b : a));
  const ticks = [];
  for (let v = lo; v <= hi; v += 5) {
    ticks.push(svg("line", {x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid-line"}),
               svg("text", {x: L - 8, y: y(v) + 4, class: "axis-text", "text-anchor": "end"}, v));
  }
  for (const w of [0, 0.25, 0.5, 0.75, 1]) {
    ticks.push(svg("text", {x: x(w), y: H - B + 18, class: "axis-text", "text-anchor": "middle"}, w));
  }
  $("weight-chart").replaceChildren(
    h("h3", {}, "How the weight was chosen"),
    svg("svg", {viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img",
                "aria-label": `Weighted-F1 on ${d.n_weight} dev clips for each fusion weight; best at w_sound ${best[0]}.`},
      ticks,
      svg("polyline", {points: d.grid.map(([w, v]) => `${x(w)},${y(v)}`).join(" "), class: "line after"}),
      svg("circle", {cx: x(best[0]), cy: y(best[1]), r: 6, class: "dot-best"}),
      svg("text", {x: x(best[0]), y: y(best[1]) - 12, class: "axis-text strong", "text-anchor": "middle"},
          `best: w_sound ${best[0]}, ${fix(best[1])}`),
      svg("text", {x: L, y: H - 6, class: "axis-text", "text-anchor": "start"}, "← words only"),
      svg("text", {x: W - R, y: H - 6, class: "axis-text", "text-anchor": "end"}, "voice only →"),
      svg("text", {x: (L + W - R) / 2, y: H - 6, class: "axis-text", "text-anchor": "middle"}, "w_sound")),
    h("p", {class: "note"}, `Weighted-F1 for each weight tried, on ${d.weight_fit} (${d.n_weight} clips). ` +
      "Either model alone scores lower than the best mix."));
}

// --- Results tab -------------------------------------------------------------------------------------

function card(title, data, build, extraClass = "") {
  const node = h("section", {class: `card report-card ${extraClass}`.trim()}, h("h2", {}, title));
  if (!data || !data.available) {
    node.append(h("p", {class: "note unavailable"}, `Not available yet: ${data ? data.reason : "no data"}.`));
    return node;
  }
  try {
    append(node, [build(data)]);
  } catch (err) {
    node.append(h("p", {class: "note unavailable"}, `This section couldn't be shown (${err.message}).`));
  }
  return node;
}

const table = (head, rows, cls = "") => h("div", {class: "table-wrap"}, h("table", {class: cls},
  h("thead", {}, h("tr", {}, head.map(([text, c]) => h("th", {class: c || null}, text)))),
  h("tbody", {}, rows)));

function hero(rep) {
  const S = rep.sections;
  const stats = [];
  const add = (value, label, cls = "") => stats.push(h("div", {class: `stat ${cls}`}, h("strong", {}, value), h("span", {}, label)));
  const rt = S.results_table;
  const r9 = rt.available && rt.rows.find((r) => r.row === "R9");
  if (r9) add(fix(r9.weighted_f1_mean), "weighted-F1 on MELD test (deployed system)");
  if (rt.available && rt.gains && rt.gains["R7-R5"]) add(signed(rt.gains["R7-R5"].gain), "points from fusing, over the words alone");
  if (S.latency.available) add(secs(S.latency.stages_ms.total.median), `per clip on this laptop (target ≤ ${rep.targets.latency_s} s)`);
  if (S.own_recordings.available) add(`${Math.round(S.own_recordings.scores.fused.accuracy)}%`, `right on ${S.own_recordings.n} new-voice recordings`);
  if (S.calibration.available) add(`${fix(S.calibration.ece_before)} → ${fix(S.calibration.ece_after)}`, "calibration error (ECE) after scaling");
  return h("div", {class: "hero"}, stats);
}

function resultsTable(rt, rep) {
  const deployed = rep.deployed;
  const group = (row) => ({R0: "base", R1: "sound", R2: "sound", R3: "sound", R4: "text", R5: "text", R6: "text"}[row] || "fused");
  const rows = rt.rows.map((r) => h("tr", {class: `grp-${group(r.row)}${r.row === "R9" ? " deployed" : ""}`},
    h("td", {}, h("strong", {}, r.row)),
    h("td", {}, r.condition, r.row === "R9" ? h("span", {class: "badge"}, "★ deployed") : null),
    h("td", {class: "num"}, fix(r.weighted_f1_mean), r.n_seeds > 1 ? h("small", {}, ` ± ${fix(r.weighted_f1_sd)}`) : null,
      h("span", {class: "cell-bar", style: {"--w": String(r.weighted_f1_mean)}})),
    h("td", {class: "num"}, `${fix(r.ci_low)}–${fix(r.ci_high)}`),
    h("td", {class: "num"}, fix(r.macro_f1_mean)),
    h("td", {class: "num"}, fix(r.accuracy_mean)),
    h("td", {class: "num"}, r.n_seeds)));
  const notes = [h("p", {class: "note"}, `Weighted-F1 in points on the ${rt.rows[0].n.toLocaleString()} MELD test utterances: ` +
    "the mean over seeds ± its SD, with a 95% bootstrap interval. R4 and R8 read the human subtitles instead of Whisper's " +
    "transcripts, an upper bound the live app can't reach.")];
  const g = rt.gains || {};
  if (g["R7-R5"] && g["R7-R1"]) {
    notes.push(h("p", {}, `Fusion gain on Whisper transcripts: ${signed(g["R7-R5"].gain)} points over the words alone ` +
      `(R7 − R5, 95% CI ${fix(g["R7-R5"].ci_low)} to ${fix(g["R7-R5"].ci_high)}) and ${signed(g["R7-R1"].gain)} over the ` +
      `voice alone (R7 − R1, ${fix(g["R7-R1"].ci_low)} to ${fix(g["R7-R1"].ci_high)}).`));
  }
  if (deployed && deployed.available) {
    let text = `Fusion weight w_sound ${fix(deployed.w_sound, 2)}, chosen on ${deployed.weight_fit} (${deployed.n_weight} dev clips).`;
    if (rt.reference && rt.reference.R9 !== undefined) {
      text += ` With the earlier weight ${rt.all_dev_weight_reference} (chosen on all of dev) the deployed system scored ${fix(rt.reference.R9)}.`;
    }
    notes.push(h("p", {class: "note"}, text));
  }
  return [table([["Row"], ["System"], ["Weighted-F1", "num"], ["95% CI", "num"], ["Macro-F1", "num"], ["Accuracy", "num"], ["Seeds", "num"]],
                rows, "results-table"), notes];
}

function perClass(pc) {
  const keys = ["sound", "text", "fused"];
  const legend = h("div", {class: "legend"}, keys.map((k) => h("span", {class: `key ${k}`}, h("span", {class: "swatch"}), BRANCH[k])));
  const rows = pc.labels.map((label) => h("div", {class: `pc-row ${label}`},
    h("div", {class: "pc-label"}, emo(label), h("small", {}, `${pc.branches.fused.per_class[label].support} clips`)),
    h("div", {class: "pc-bars"}, keys.map((k) => {
      const f = pc.branches[k].per_class[label].f1;
      return h("div", {class: `pc-bar ${k}`}, h("span", {class: "pc-key"}, BRANCH[k]),
        h("span", {class: "track"}, h("span", {class: "fill", "data-w": `${f}%`})), h("span", {class: "val"}, fix(f)));
    }))));
  const totals = h("p", {class: "note"}, `Weighted-F1: ${keys.map((k) => `${BRANCH[k]} ${fix(pc.branches[k].weighted_f1)}`).join(" · ")}. ` +
    "F1 in points, deployed models on MELD test.");
  return [legend, h("div", {class: "pc-chart"}, rows), totals];
}

function confusionTable(labels, cm, caption) {
  const head = h("tr", {}, h("th", {class: "corner"}, "true ↓ / said →"),
    labels.map((l) => h("th", {title: l, scope: "col"}, h("span", {class: "emo-icon"}, EMOJI[l]))));
  const body = cm.map((row, i) => {
    const total = row.reduce((a, b) => a + b, 0) || 1;
    return h("tr", {}, h("th", {scope: "row"}, emo(labels[i])), row.map((c, j) => {
      const share = c / total;
      return h("td", {class: `heat-cell${i === j ? " diag" : ""}`, title: `${labels[i]} → ${labels[j]}: ${c} (${pct(share)})`},
        h("span", {class: `heat ${labels[i]}`, style: {opacity: String(Math.min(1, share * 1.15))}}),
        h("span", {class: "heat-val"}, Math.round(100 * share)));
    }));
  });
  return h("figure", {class: "confusion"}, h("figcaption", {}, caption),
    h("div", {class: "table-wrap"}, h("table", {class: "cm"}, h("thead", {}, head), h("tbody", {}, body))));
}

function confusions(pc) {
  // The commonest wrong answer of the fused output, and that class's share of the test set.
  const cm = pc.branches.fused.confusion;
  const wrong = pc.labels.map((_, j) => cm.reduce((a, row, i) => a + (i === j ? 0 : row[j]), 0));
  const top = wrong.indexOf(Math.max(...wrong));
  const support = pc.branches.fused.per_class[pc.labels[top]].support;
  return [h("div", {class: "cm-grid"}, ["sound", "text", "fused"].map((k) =>
    confusionTable(pc.labels, pc.branches[k].confusion, `${BRANCH[k]} · accuracy ${fix(pc.branches[k].accuracy)}%`))),
  h("p", {class: "note"}, "Each row is one true emotion; the numbers are the % of its clips given each answer, so the diagonal " +
    `is the % right. The commonest wrong answer is ${pc.labels[top]} ${EMOJI[pc.labels[top]]} ` +
    `(${pct(wrong[top] / wrong.reduce((a, b) => a + b, 0))} of the fused output's mistakes), the largest class ` +
    `(${pct(support / pc.n)} of the test set).`)];
}

function werTable(w) {
  const chosen = w.decision.window_s;
  const rows = w.rows.map((r) => h("tr", {class: r.window_s === chosen ? "chosen" : null},
    h("td", {}, r.split), h("td", {}, `${r.window_s} s`, r.window_s === chosen ? h("span", {class: "badge"}, "deployed") : null),
    h("td", {class: "num"}, r.n.toLocaleString()), h("td", {class: "num"}, r.ref_words.toLocaleString()),
    h("td", {class: "num"}, h("strong", {}, `${fix(r.wer, 1)}%`))));
  const gap = w.decision.wer_gap_10s_minus_30s;
  return [table([["Split"], ["Window"], ["Clips", "num"], ["Words", "num"], ["WER", "num"]], rows),
    h("p", {}, `The ${chosen} s window was chosen by WER on dev: the 10 s window was ${fix(gap.dev, 2)} points worse on dev ` +
      `and ${fix(gap.test, 2)} on test.`),
    h("p", {class: "note"}, "faster-whisper small.en, greedy decoding. MELD's references are subtitles, not verbatim " +
      "transcripts, which inflates these figures.")];
}

function reliabilityChart(c) {
  const S = 300, P = 40;
  const x = (v) => P + v * (S - P - 10);
  const y = (v) => S - P - v * (S - P - 10);
  const line = (bins, cls) => [svg("polyline", {points: bins.map((b) => `${x(b.confidence)},${y(b.accuracy)}`).join(" "), class: `line ${cls}`}),
    bins.map((b) => svg("circle", {cx: x(b.confidence), cy: y(b.accuracy), r: 3.5, class: `pt ${cls}`}))];
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((v) => [
    svg("line", {x1: x(0), x2: x(1), y1: y(v), y2: y(v), class: "grid-line"}),
    svg("text", {x: P - 6, y: y(v) + 4, class: "axis-text", "text-anchor": "end"}, v),
    svg("text", {x: x(v), y: S - P + 16, class: "axis-text", "text-anchor": "middle"}, v)]);
  return svg("svg", {viewBox: `0 0 ${S} ${S}`, class: "chart reliability", role: "img",
                     "aria-label": `Reliability diagram: ECE ${fix(c.ece_before)} before and ${fix(c.ece_after)} after temperature scaling.`},
    ticks,
    svg("line", {x1: x(0), y1: y(0), x2: x(1), y2: y(1), class: "diag-line"}),
    line(c.reliability.before, "before"), line(c.reliability.after, "after"),
    svg("text", {x: (x(0) + x(1)) / 2, y: S - 6, class: "axis-text", "text-anchor": "middle"}, "confidence"),
    svg("text", {x: 12, y: (y(0) + y(1)) / 2, class: "axis-text", "text-anchor": "middle",
                 transform: `rotate(-90 12 ${(y(0) + y(1)) / 2})`}, "accuracy"));
}

function calibration(c) {
  const rows = c.rows.map((r) => h("tr", {}, h("td", {}, r.output), h("td", {class: "num"}, fix(r.ece_before, 2)),
    h("td", {class: "num"}, h("strong", {}, fix(r.ece_after, 2))), h("td", {class: "num"}, fix(r.accuracy))));
  return [h("div", {},
    h("div", {}, table([["Output"], ["ECE before", "num"], ["ECE after", "num"], ["Accuracy", "num"]], rows),
      h("p", {}, `Temperature scaling (T_sound ${fix(c.t_sound, 2)}, T_text ${fix(c.t_text, 2)}, fitted on dev) cuts the ` +
        `fused calibration error from ${fix(c.ece_before, 2)} to ${fix(c.ece_after, 2)} points, so the confidence shown ` +
        "on the result card is closer to how often it is right."),
      h("p", {class: "note"}, `ECE with ${c.bins} equal-width bins, in points, on MELD test.`)),
    h("figure", {class: "rel-fig"}, reliabilityChart(c),
      h("figcaption", {class: "legend"}, h("span", {class: "key before"}, h("span", {class: "swatch"}), "before scaling"),
        h("span", {class: "key after"}, h("span", {class: "swatch"}), "after scaling"),
        h("span", {class: "key diag"}, h("span", {class: "swatch"}), "perfect"))))];
}

function gauge(value, max, marks, unit, cls) {
  return h("div", {class: `gauge ${cls}`},
    h("div", {class: "gauge-track"}, h("span", {class: "fill", "data-w": `${(100 * value) / max}%`}),
      marks.map(([v, label]) => h("span", {class: "gauge-mark", style: {left: `${(100 * v) / max}%`}}, h("span", {}, label)))),
    h("div", {class: "gauge-scale"}, h("span", {}, `0 ${unit}`), h("span", {}, `${max} ${unit}`)));
}

function latency(l, rep) {
  const t = rep.targets;
  const total = l.stages_ms.total.median;
  const pass = (ok) => h("span", {class: `pass ${ok ? "yes" : "no"}`}, ok ? "✓ met" : "✗ not met");
  const stages = STAGES.map(([k, name]) => [k, name, l.stages_ms[k].median]);
  const sum = stages.reduce((a, [, , v]) => a + v, 0) || 1;
  const parts = [
    h("div", {class: "big-figure"}, h("strong", {}, secs(total)),
      h("span", {}, ` median per ${fix(l.clip_s)} s clip, p90 ${secs(l.stages_ms.total.p90)}`)),
    gauge(total / 1000, 2.5, [[t.latency_stretch_s, `stretch ${t.latency_stretch_s} s`], [t.latency_s, `AC-08 ${t.latency_s} s`]], "s", "time"),
    h("p", {}, "AC-08 (≤ ", String(t.latency_s), " s): ", pass(total / 1000 <= t.latency_s),
      ` · stretch goal (≤ ${t.latency_stretch_s} s): `, pass(total / 1000 <= t.latency_stretch_s)),
    h("h3", {}, "Where the time goes"),
    h("div", {class: "stack"}, stages.filter(([, , v]) => v > 0).map(([k, name, v]) =>
      h("span", {class: `seg stage-${k}`, style: {flexGrow: String(v)}, title: `${name}: ${Math.round(v)} ms`}))),
    h("ul", {class: "stack-legend"}, stages.map(([k, name, v]) => h("li", {}, h("span", {class: `swatch stage-${k}`}),
      `${name} ${Math.round(v)} ms (${Math.round((100 * v) / sum)}%)`))),
    h("h3", {}, "Memory"),
    h("div", {class: "big-figure"}, h("strong", {}, `${fix(l.peak_memory_gb, 2)} GB`), h("span", {}, " peak, all models loaded")),
    gauge(l.peak_memory_gb, 3, [[t.memory_gb, `AC-09 ${t.memory_gb} GB`]], "GB", "mem"),
    h("p", {}, `AC-09 (≤ ${t.memory_gb} GB): `, pass(l.peak_memory_gb <= t.memory_gb)),
    h("p", {class: "note"}, `${l.runs} runs after ${l.warmup} warm-ups on ${l.date}, laptop ${l.mains_power ? "on mains power" : "on battery"}; ` +
      `the models load once in ${fix(l.load_s)} s at start-up. Models: ${l.models.asr}, ${l.models.sound}, ` +
      `${l.models.text} (${l.models.text_precision}).`),
  ];
  const p = rep.sections.parity;
  if (p && p.available) {
    parts.push(h("p", {class: "note"}, `Laptop against Kaggle on ${p.n.toLocaleString()} dev clips: ` +
      ["sound", "text", "fused"].map((k) => `${k} ${signed(p.rows[k].gap, 2)}`).join(", ") +
      ` points (limit ±${p.max_gap}), so AC-07 ${p.pass ? "passes" : "fails"}.`));
  }
  return parts;
}

function compareBars(items, max = 100, unit = "%") {
  return h("div", {class: "cmp"}, items.map(([name, value, cls, note]) => h("div", {class: `cmp-row ${cls || ""}`},
    h("span", {class: "cmp-name"}, name),
    h("span", {class: "track"}, h("span", {class: "fill", "data-w": `${(100 * value) / max}%`})),
    h("span", {class: "val"}, `${unit === "%" ? Math.round(value) : fix(value, 2)}${unit}`, note ? h("small", {}, ` ${note}`) : null))));
}

function own(o) {
  const ci = (s) => `95% CI ${Math.round(s.acc_ci[0])}–${Math.round(s.acc_ci[1])}`;
  const items = [["👂 How it sounds", o.scores.sound.accuracy, "sound", ci(o.scores.sound)],
                 ["💬 What was said", o.scores.text.accuracy, "text", ci(o.scores.text)]];
  if (o.before) items.push([`Fused before the refit (${o.before.label.split(",")[0]})`, o.before.scores.fused.accuracy, "before", ci(o.before.scores.fused)]);
  items.push([`Fused now (w_sound ${fix(o.w_sound, 2)})`, o.scores.fused.accuracy, "fused", ci(o.scores.fused)]);
  const parts = [
    h("p", {}, `${o.n} recordings made for this project (${LABELS.map((l) => `${o.per_emotion[l]} ${EMOJI[l]}`).join(" ")}), ` +
      "by speakers the models never heard in training. Accuracy (% right):"),
    compareBars(items)];
  if (o.before) {
    parts.push(h("p", {class: "honest"}, h("strong", {}, "The fusion weight was refit after seeing the first result. "),
      `The first run got ${Math.round(o.before.scores.fused.accuracy)}% while the words alone got ` +
      `${Math.round(o.before.scores.text.accuracy)}%. The new weight was chosen on MELD dev clips from speakers outside ` +
      "the main cast, without using these recordings, but because the change came after seeing them they are no longer a blind test."));
  }
  parts.push(h("p", {class: "note"}, `Weighted-F1 ${fix(o.scores.fused.weighted_f1)} now${o.before ? `, ${fix(o.before.scores.fused.weighted_f1)} before` : ""}; ` +
    `median ${secs(o.median_ms)} per clip on this laptop. Chance is 14%.`));
  parts.push(confusionTable(LABELS, o.confusion_fused, "Fused answers on these recordings (now)"));
  return parts;
}

function chatbot(c) {
  const lat = c.median_latency_s;
  const parts = [];
  if (c.partial) {
    parts.push(h("p", {class: "partial"}, h("span", {class: "badge warn"}, "Partial"),
      ` ${c.n_answered} of ${c.n_total} clips answered so far: Gemini's free tier ran out of daily requests. ` +
      "The rest will be added when the quota resets."));
  }
  const items = [["🤖 Gemini", c.gemini.accuracy, "gemini"], ["🎭 This app", c.ours.accuracy, "fused"]];
  if (c.ours_before) items.push(["🎭 This app before the refit", c.ours_before.accuracy, "before"]);
  parts.push(h("h3", {}, `Accuracy on the same ${c.n_answered} recordings`), compareBars(items),
    h("h3", {}, "Median time per clip"),
    compareBars([["🤖 Gemini (cloud)", lat.gemini, "gemini"], ["🎭 This app (laptop)", lat.ours, "fused"]],
                Math.max(lat.gemini, lat.ours) * 1.05, " s"),
    h("p", {}, `Gemini is clearly more accurate on these recordings: ${Math.round(c.gemini.accuracy)}% against ` +
      `${Math.round(c.ours.accuracy)}% (weighted-F1 ${fix(c.gemini.weighted_f1)} against ${fix(c.ours.weighted_f1)}). ` +
      `The two gave the same answer on ${Math.round(c.agree_pct)}% of the clips.`),
    h("p", {class: "note"}, `Model ${c.model}${c.served && c.served.length ? ` (served as ${c.served.join(", ")})` : ""}, ` +
      `free API, asked on ${c.date}, given each audio file and asked for one of the seven emotions; ${c.invalid} answers ` +
      "couldn't be read. Only the project's own recordings were sent, never MELD."));
  return parts;
}

function canDo(rep) {
  const S = rep.sections;
  const items = [];
  const c = S.chatbot.available ? S.chatbot : null;
  const lat = S.latency.available ? S.latency.stages_ms.total.median / 1000 : null;
  if (c && lat) {
    items.push(["⚡", "Fast, with no network", `${fix(c.median_latency_s.ours, 1)} s per clip on a laptop CPU, against ` +
      `${fix(c.median_latency_s.gemini, 1)} s for Gemini: about ${Math.round(c.median_latency_s.gemini / c.median_latency_s.ours)}× faster.`]);
  }
  items.push(["🔒", "Private and offline", "The audio never leaves this laptop. Gemini needs every clip uploaded to Google's cloud."]);
  if (S.calibration.available) {
    items.push(["🎯", "Calibrated confidence for all seven emotions", `Calibration error ${fix(S.calibration.ece_after)} points ` +
      "on MELD test, so a 60% answer is right about 60% of the time. A chatbot gives one word, with no reliable confidence."]);
  }
  const g = S.per_class.available ? S.per_class.disagreement : null;
  if (g) {
    items.push(["🔍", "Shows tone and words separately, and flags conflicts", `The flag comes up on ${fix(g.flagged_pct)}% of ` +
      `MELD test clips; there the answer is right ${Math.round(g.fused_right_pct)}% of the time, against ` +
      `${Math.round(g.fused_right_other_pct)}% elsewhere, so it marks the answers to double-check.`]);
  }
  items.push(["💸", "Free and unlimited", "No API key, no quota. Gemini's free tier stopped after 20 requests a day per model" +
    (c && c.partial ? ", which is why the comparison is still partial." : " during the comparison.")]);
  items.push(["🔁", "Repeatable", "The same clip always gets the same answer (fixed weights, greedy decoding), and every number on this page can be re-run from the repository."]);
  return [h("ul", {class: "can-do"}, items.map(([i, title, text]) => h("li", {}, h("span", {class: "cd-icon", "aria-hidden": "true"}, i),
    h("div", {}, h("strong", {}, title), h("p", {}, text))))),
  c ? h("p", {class: "honest"}, h("strong", {}, "What the chatbot does better: "),
    `it understood these recordings far better (${Math.round(c.gemini.accuracy)}% against ${Math.round(c.ours.accuracy)}%).`) : null];
}

function limits(rep) {
  const S = rep.sections;
  const items = ["Trained on TV dialogue (Friends, through MELD); not for clinical use; English only."];
  if (S.per_class.available) {
    const f = S.per_class.branches.fused.per_class;
    items.push(`Weak on rare emotions: on MELD test, F1 ${Math.round(f.disgust.f1)} for disgust and ${Math.round(f.fear.f1)} ` +
      `for fear (${f.disgust.support} and ${f.fear.support} clips), against ${Math.round(f.neutral.f1)} for neutral.`);
  }
  if (S.own_recordings.available) {
    items.push(`The voice card is weak on new voices: ${Math.round(S.own_recordings.scores.sound.accuracy)}% right on the ` +
      `${S.own_recordings.n} recordings made for this project (chance 14%), so check both cards.`);
  }
  if (S.wer.available) {
    const w = S.wer.rows.find((r) => r.split === "test" && r.window_s === S.wer.decision.window_s);
    if (w) items.push(`Transcripts aren't perfect: Whisper's word error rate is ${fix(w.wer)}% on MELD test, and the words card inherits the mistakes.`);
  }
  if (S.own_recordings.available) {
    const o = S.own_recordings;
    const half = Math.round((o.scores.fused.acc_ci[1] - o.scores.fused.acc_ci[0]) / 2);
    items.push(`The own-recordings check is small: ${o.n} acted clips, with 95% intervals about ±${half} points` +
      (o.before ? ", and the weight was refit after seeing it." : "."));
  }
  if (S.latency.available) {
    const total = S.latency.stages_ms.total.median / 1000;
    items.push(`${fix(total, 2)} s per clip meets the 2 s target but not the ${rep.targets.latency_stretch_s} s stretch goal; ` +
      "the server analyses one clip at a time.");
  }
  if (S.chatbot.available) items.push(`A general chatbot is more accurate on clear, acted speech (${Math.round(S.chatbot.gemini.accuracy)}% against ${Math.round(S.chatbot.ours.accuracy)}%).`);
  return h("ul", {class: "limits"}, items.map((t) => h("li", {}, t)));
}

function renderReport(rep) {
  const S = rep.sections;
  const pc = S.per_class;
  $("report").replaceChildren(
    hero(rep),
    card("📋 All systems on MELD test", S.results_table, (d) => resultsTable(d, rep), "wide"),
    card("🎨 F1 for each emotion", pc, perClass, "wide"),
    card("🔢 Confusion matrices", pc, confusions, "wide"),
    card("📝 Speech recognition", S.wer, werTable),
    card("🎯 Calibration", S.calibration, calibration),
    card("⏱️ Speed and memory on this laptop", S.latency, (d) => latency(d, rep), "wide"),
    card("🎙️ New voices: recordings made for this project", S.own_recordings, own),
    card("🤖 Against a chatbot (Gemini)", S.chatbot, chatbot),
    card("✨ What it does that a chatbot can't", {available: true}, () => canDo(rep), "wide"),
    card("⚠️ Honest limitations", {available: true}, () => limits(rep), "wide"));
  animateFills($("report"));
  $("report-status").textContent = "";
}

$("report-status").textContent = "Loading the results…";
fetch("/api/report")
  .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
  .then((rep) => {
    renderReport(rep);
    fillHow(rep);
    $("version").textContent = `Version ${rep.version}. Results built from results/ when the server started.`;
  })
  .catch((err) => {
    $("report-status").textContent = `Couldn't load the results: ${err.message}.`;
    $("report-status").classList.add("error");
  });

fetch("/api/health").then((r) => r.json()).then((hl) => {
  if (!hl.models_loaded) status("The models are still loading…", true);
}).catch(() => status("Couldn't reach the server.", true));

refreshControls();
