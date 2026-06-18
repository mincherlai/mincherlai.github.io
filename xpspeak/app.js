/* XPSPeak web app — Pyodide-backed XPS peak fitting that runs in the browser
   (Mac, iPad Safari, anything). The numpy/scipy engine is the same code as the
   desktop .app; this file is just the UI and the calls into the Python bridge. */

let pyodide = null;
let bridge = null;

// --- document state (array of region dicts, same shape as Region.to_dict) ---
const state = {
  regions: [],
  current: 0,
  glMode: "sum",
};

const $ = (id) => document.getElementById(id);
const ENGINE_FILES = ["__init__.py", "functions.py", "background.py",
  "model.py", "fitting.py", "io_import.py", "io_native.py"];

// ------------------------------------------------------------ bootstrap
async function boot() {
  try {
    pyodide = await loadPyodide();
    $("splash-msg").innerHTML = "과학 라이브러리(scipy)를 불러오는 중…";
    await pyodide.loadPackage(["numpy", "scipy"]);

    // Write the engine package into the Pyodide filesystem.
    pyodide.FS.mkdir("xpspeak");
    for (const f of ENGINE_FILES) {
      const txt = await (await fetch("xpspeak/" + f)).text();
      pyodide.FS.writeFile("xpspeak/" + f, txt);
    }
    const bridgeSrc = await (await fetch("bridge.py")).text();
    pyodide.FS.writeFile("bridge.py", bridgeSrc);
    await pyodide.runPythonAsync("import sys; sys.path.insert(0,'.')");
    bridge = pyodide.pyimport("bridge");

    wireUI();
    fadeSplash();
  } catch (e) {
    $("splash-msg").innerHTML = "로딩 실패: " + e + "<br>네트워크를 확인하고 새로고침 해주세요.";
    console.error(e);
  }
}

function fadeSplash() {
  const s = $("splash");
  s.style.opacity = "0";
  setTimeout(() => (s.style.display = "none"), 400);
}

// ------------------------------------------------------------ helpers
function curRegion() { return state.regions[state.current] || null; }

function defaultConstraints() {
  const c = {};
  for (const p of ["position", "area", "fwhm", "gl", "ts", "tl"])
    c[p] = { ref: null, mode: "add", value: 0, lower: null, upper: null, fixed: false };
  return c;
}

function blankRegionDefaults(r) {
  // Ensure imported regions have the background/peaks fields the UI expects.
  r.bg_type = r.bg_type || "Linear";
  r.bg_navg = r.bg_navg || 1;
  r.bg_slope = r.bg_slope || 0;
  r.bg_b1 = r.bg_b1 || 100;
  r.bg_c = r.bg_c || 1643;
  r.region_shift = r.region_shift || 0;
  r.peaks = r.peaks || [];
  return r;
}

// ------------------------------------------------------------ compute + draw
function recompute() {
  const r = curRegion();
  if (!r) { drawEmpty(); return; }
  const out = JSON.parse(bridge.compute(JSON.stringify(r), state.glMode));
  draw(r, out);
  $("chi2").textContent = "χ² = " + out.chi2.toExponential(4);
  // Update read-only actual-FWHM cells.
  out.actual_fwhm.forEach((v, i) => {
    const cell = document.querySelector(`#peakTable tbody tr[data-i="${i}"] .afwhm`);
    if (cell) cell.textContent = v.toFixed(4);
  });
}

function drawEmpty() {
  Plotly.react("plot", [], {
    annotations: [{ text: "Import 또는 Demo로 스펙트럼을 불러오세요",
      showarrow: false, font: { size: 16, color: "#9aa6b6" }, x: 0.5, y: 0.5,
      xref: "paper", yref: "paper" }],
    margin: { t: 20, r: 14, b: 44, l: 60 }, xaxis: { autorange: "reversed" },
  }, { displayModeBar: false });
  $("chi2").textContent = "χ² = —";
}

function draw(r, out) {
  const traces = [];
  traces.push({ x: out.be, y: out.raw, mode: "markers", type: "scatter",
    name: "data", marker: { size: 4, color: "#1f77b4" } });
  if (out.has_bg)
    traces.push({ x: out.be, y: out.bg, mode: "lines", name: "background",
      line: { dash: "dash", color: "#888", width: 1 } });
  out.peaks.forEach((py, i) =>
    traces.push({ x: out.be, y: py, mode: "lines", name: "peak " + i,
      line: { color: "#2ca02c", width: 1 }, showlegend: false }));
  if (out.envelope)
    traces.push({ x: out.be, y: out.envelope, mode: "lines", name: "envelope",
      line: { color: "#d62728", width: 2 } });

  Plotly.react("plot", traces, {
    margin: { t: 20, r: 14, b: 44, l: 62 },
    xaxis: { title: "Binding Energy (eV)", autorange: "reversed", zeroline: false },
    yaxis: { title: "Intensity (counts)", zeroline: false },
    legend: { orientation: "h", y: 1.04, x: 1, xanchor: "right" },
    title: { text: r.name, font: { size: 13 } },
    dragmode: "pan",
  }, { responsive: true, displaylogo: false, scrollZoom: true,
       modeBarButtonsToRemove: ["select2d", "lasso2d"] });
}

// ------------------------------------------------------------ region nav
function refreshRegionSel() {
  const sel = $("regionSel");
  sel.innerHTML = "";
  state.regions.forEach((r, i) => {
    const o = document.createElement("option");
    o.value = i; o.textContent = `${i + 1}: ${r.name}`;
    sel.appendChild(o);
  });
  sel.value = state.current;
  syncRegionControls();
}

function syncRegionControls() {
  const r = curRegion();
  if (!r) return;
  $("bgType").value = r.bg_type;
  $("bgAvg").value = String(r.bg_navg);
  $("bgSlope").value = r.bg_slope;
  $("bgB1").value = r.bg_b1;
  $("regShift").value = r.region_shift;
  renderTable();
}

// ------------------------------------------------------------ peak table
function renderTable() {
  const r = curRegion();
  const tb = document.querySelector("#peakTable tbody");
  tb.innerHTML = "";
  if (!r) return;
  r.peaks.forEach((pk, i) => {
    const tr = document.createElement("tr");
    tr.dataset.i = i;
    ensureConstraints(pk);
    tr.innerHTML = `
      <td class="ro">${i}</td>
      <td><input class="name" value="${pk.name || ""}" data-f="name"></td>
      <td>${typeSelect(pk.peak_type)}</td>
      <td><input data-f="sos" value="${num(pk.sos)}"></td>
      ${pcell("position", pk)}
      ${pcell("area", pk)}
      ${pcell("fwhm", pk)}
      ${pcell("gl", pk)}
      <td><input data-f="ts" value="${num(pk.ts)}"></td>
      <td><input data-f="tl" value="${num(pk.tl)}"></td>
      <td><input type="checkbox" data-f="fix" ${pk.fix ? "checked" : ""} title="피크 전체 고정"></td>
      <td class="ro afwhm">—</td>
      <td><button class="delbtn" title="삭제">✕</button></td>`;
    tb.appendChild(tr);

    tr.querySelectorAll("input[data-f]").forEach((inp) => {
      const ev = inp.type === "checkbox" ? "change" : "input";
      inp.addEventListener(ev, () => onCellEdit(i, inp));
    });
    // Per-parameter fix (lock) checkboxes.
    tr.querySelectorAll("input[data-fix]").forEach((chk) => {
      chk.addEventListener("change", () => {
        ensureConstraints(pk);
        pk.constraints[chk.dataset.fix].fixed = chk.checked;
        chk.closest(".pcell").classList.toggle("locked", chk.checked);
      });
    });
    tr.querySelector("select").addEventListener("change", (e) => {
      r.peaks[i].peak_type = e.target.value;
      if (["p", "d", "f"].includes(e.target.value) && !r.peaks[i].sos)
        r.peaks[i].sos = 0.7;
      renderTable(); recompute();
    });
    tr.querySelector(".delbtn").addEventListener("click", () => {
      r.peaks.splice(i, 1); renderTable(); recompute();
    });
  });
}

function typeSelect(v) {
  return `<select>${["s", "p", "d", "f"].map(t =>
    `<option ${t === v ? "selected" : ""}>${t}</option>`).join("")}</select>`;
}
function num(v) { return (v === undefined || v === null) ? 0 : v; }

// A value cell with an inline per-parameter "fix" (lock) checkbox.
function pcell(f, pk) {
  const fixed = pk.constraints && pk.constraints[f] && pk.constraints[f].fixed;
  return `<td><div class="pcell${fixed ? " locked" : ""}">
    <input data-f="${f}" value="${num(pk[f])}">
    <label class="lock" title="이 파라미터 고정">
      <input type="checkbox" data-fix="${f}" ${fixed ? "checked" : ""}>🔒</label>
  </div></td>`;
}

// Guarantee a peak carries a full constraints object (older saves may lack it).
function ensureConstraints(pk) {
  if (!pk.constraints) pk.constraints = defaultConstraints();
  for (const p of ["position", "area", "fwhm", "gl", "ts", "tl"])
    if (!pk.constraints[p])
      pk.constraints[p] = { ref: null, mode: "add", value: 0, lower: null, upper: null, fixed: false };
}

function onCellEdit(i, inp) {
  const r = curRegion(); const pk = r.peaks[i]; const f = inp.dataset.f;
  if (f === "name") pk.name = inp.value;
  else if (f === "fix") pk.fix = inp.checked;
  else { const v = parseFloat(inp.value); if (!isNaN(v)) pk[f] = v; }
  recompute();
}

function addPeak() {
  const r = curRegion();
  if (!r) { alert("먼저 스펙트럼을 불러오세요."); return; }
  if (r.peaks.length >= 10) { alert("리전당 최대 10개입니다."); return; }
  const be = r.be, mid = be[Math.floor(be.length / 2)] || 0;
  const peakH = Math.max(...r.intensity) - Math.min(...r.intensity);
  r.peaks.push({
    name: "Peak" + r.peaks.length, peak_type: "s",
    position: mid, area: Math.max(peakH, 1) * 1.5, fwhm: 1.0, gl: 30,
    ts: 0, tl: 1, sos: 0, fix: false, constraints: defaultConstraints(),
  });
  renderTable(); recompute();
}

// ------------------------------------------------------------ optimize
function runFit(scope) {
  const r = curRegion();
  if (!r) return;
  const res = JSON.parse(bridge.fit(JSON.stringify(r), state.glMode, JSON.stringify(scope)));
  state.regions[state.current] = blankRegionDefaults(res.region);
  syncRegionControls(); recompute();
  const x = res.result;
  $("chi2").title = `${x.chi2_before} → ${x.chi2_after}`;
}

// ------------------------------------------------------------ file ops
function importFile(fmt, filename, text) {
  try {
    const regions = JSON.parse(bridge.import_text(fmt, text, filename));
    regions.forEach((r) => state.regions.push(blankRegionDefaults(r)));
    state.current = state.regions.length - regions.length;
    refreshRegionSel(); recompute();
  } catch (e) { alert("불러오기 실패: " + e); }
}

function saveNative() {
  const doc = { format: "xpspeak-mac", version: 1, gl_mode: state.glMode, regions: state.regions };
  download("spectrum.xpsj", JSON.stringify(doc, null, 2), "application/json");
}

function openNative(text) {
  try {
    const doc = JSON.parse(text);
    state.regions = (doc.regions || []).map(blankRegionDefaults);
    state.glMode = doc.gl_mode || "sum";
    $("glMode").value = state.glMode;
    state.current = 0; refreshRegionSel(); recompute();
  } catch (e) { alert("열기 실패: " + e); }
}

function exportData() {
  const r = curRegion(); if (!r) return;
  download(r.name.replace(/\s+/g, "_") + ".DAT", bridge.export_dat(JSON.stringify(r), state.glMode), "text/plain");
  download(r.name.replace(/\s+/g, "_") + ".PAR", bridge.export_par(JSON.stringify(r), state.glMode), "text/plain");
}

function download(name, text, type) {
  const blob = new Blob([text], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ------------------------------------------------------------ UI wiring
function wireUI() {
  $("regionSel").addEventListener("change", (e) => {
    state.current = parseInt(e.target.value); syncRegionControls(); recompute();
  });
  $("prevBtn").addEventListener("click", () => stepRegion(-1));
  $("nextBtn").addEventListener("click", () => stepRegion(1));
  $("glMode").addEventListener("change", (e) => { state.glMode = e.target.value; recompute(); });

  const bgApply = () => {
    const r = curRegion(); if (!r) return;
    r.bg_type = $("bgType").value;
    r.bg_navg = parseInt($("bgAvg").value);
    r.bg_slope = parseFloat($("bgSlope").value) || 0;
    r.bg_b1 = parseFloat($("bgB1").value) || 100;
    recompute();
  };
  ["bgType", "bgAvg", "bgSlope", "bgB1"].forEach((id) =>
    $(id).addEventListener("input", bgApply));
  $("regShift").addEventListener("input", () => {
    const r = curRegion(); if (r) { r.region_shift = parseFloat($("regShift").value) || 0; recompute(); }
  });
  $("optB1Btn").addEventListener("click", () => {
    const r = curRegion(); if (!r) return;
    state.regions[state.current] = blankRegionDefaults(JSON.parse(bridge.optimize_b1(JSON.stringify(r), state.glMode)));
    syncRegionControls(); recompute();
  });

  $("addPeakBtn").addEventListener("click", addPeak);
  $("optPeakBtn").addEventListener("click", () => {
    const tr = document.querySelector("#peakTable tbody tr");
    const sel = document.querySelector("#peakTable tbody tr.sel") || tr;
    if (!sel) { alert("피크를 추가/선택하세요."); return; }
    runFit(["peak", parseInt(sel.dataset.i)]);
  });
  $("optRegionBtn").addEventListener("click", () => runFit(["region"]));
  $("optAllBtn").addEventListener("click", () => {
    state.regions.forEach((r, i) => {
      const res = JSON.parse(bridge.fit(JSON.stringify(r), state.glMode, JSON.stringify(["region"])));
      state.regions[i] = blankRegionDefaults(res.region);
    });
    syncRegionControls(); recompute();
  });

  // row selection (for Optimize Peak)
  document.querySelector("#peakTable").addEventListener("click", (e) => {
    const tr = e.target.closest("tbody tr"); if (!tr) return;
    document.querySelectorAll("#peakTable tbody tr").forEach(t => t.classList.remove("sel"));
    tr.classList.add("sel");
  });

  // import / open
  $("importBtn").addEventListener("click", () => $("importModal").classList.add("open"));
  $("importCancel").addEventListener("click", () => $("importModal").classList.remove("open"));
  $("importPick").addEventListener("click", () => {
    pendingFmt = $("importFmt").value; pendingMode = "import";
    $("importModal").classList.remove("open"); $("fileInput").click();
  });
  $("loadBtn").addEventListener("click", () => { pendingMode = "open"; $("fileInput").click(); });
  $("fileInput").addEventListener("change", (e) => {
    const file = e.target.files[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (pendingMode === "open") openNative(reader.result);
      else importFile(pendingFmt, file.name, reader.result);
    };
    reader.readAsText(file); e.target.value = "";
  });
  $("saveBtn").addEventListener("click", saveNative);
  $("exportBtn").addEventListener("click", exportData);
  $("demoBtn").addEventListener("click", loadDemo);

  drawEmpty();
}

let pendingFmt = "ascii", pendingMode = "import";

function stepRegion(d) {
  if (!state.regions.length) return;
  state.current = (state.current + d + state.regions.length) % state.regions.length;
  $("regionSel").value = state.current; syncRegionControls(); recompute();
}

async function loadDemo() {
  const text = await (await fetch("samples/As3d_demo.prn")).text();
  importFile("ascii", "As3d_demo.prn", text);
  // Pre-set a Shirley background and an As 3d doublet so the demo shows a fit.
  const r = curRegion();
  r.bg_type = "Shirley";
  r.peaks = [{ name: "As 3d", peak_type: "d", position: 41.3, area: 8000, fwhm: 0.9,
    gl: 30, ts: 0, tl: 1, sos: 0.7, fix: false, constraints: defaultConstraints() }];
  syncRegionControls();
  runFit(["region"]);
}

// register service worker for offline / installable PWA
if ("serviceWorker" in navigator)
  navigator.serviceWorker.register("sw.js").catch(() => {});

boot();
