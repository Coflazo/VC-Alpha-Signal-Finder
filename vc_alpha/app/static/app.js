// No framework. The page has five tabs and a handful of tables; a build step and
// 40kB of runtime to render them would be cost without benefit.

const $ = (s) => document.querySelector(s);
const el = (tag, props = {}, kids = []) => {
  const n = Object.assign(document.createElement(tag), props);
  for (const k of [].concat(kids)) n.append(k);
  return n;
};
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};
const pct = (n) => (n == null ? "—" : n.toFixed(3));
const esc = (s) => (s ?? "").toString();

// --- tabs -------------------------------------------------------------------

const LOADERS = {};
document.querySelectorAll("nav button").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll("nav button").forEach((b) =>
      b.setAttribute("aria-selected", String(b === btn)));
    document.querySelectorAll("main section").forEach((s) =>
      (s.hidden = s.id !== btn.dataset.tab));
    LOADERS[btn.dataset.tab]?.();
  };
});

// --- dashboard --------------------------------------------------------------

LOADERS.dashboard = async () => {
  const d = await api("/api/overview");
  const total = d.sources.reduce((a, s) => a + s.total, 0);
  const scored = d.sources.reduce((a, s) => a + (s.scored || 0), 0);

  $("#headline").textContent =
    `${total} candidates · ${d.nodes.active || 0} active nodes · ${d.reviewed.n} reviewed`;

  $("#metrics").replaceChildren(...[
    ["Candidates", total],
    ["Scored", scored],
    ["Frontier nodes", d.nodes.total || 0],
    ["Reviewed", d.reviewed.n],
    ["Marked good", d.reviewed.good],
  ].map(([label, value]) =>
    el("div", { className: "card metric" }, [
      el("span", { textContent: label }),
      el("b", { textContent: value ?? 0 }),
    ])));

  $("#sources").replaceChildren(...d.sources.map((s) =>
    el("tr", {}, [
      el("td", { textContent: s.source }),
      el("td", { className: "num", textContent: s.total }),
      el("td", { className: "num", textContent: s.scored || 0 }),
      el("td", { className: "num", textContent: s.triaged || 0 }),
      el("td", {}, [
        s.local_only
          ? el("span", { className: "pill local", textContent: "this machine only", title: s.note })
          : el("span", { className: "pill", textContent: "CI or local" }),
      ]),
    ])));

  renderJob(d.job);
};

function renderJob(job) {
  if (!job) return;
  $("#job-log").textContent = job.lines.join("\n") || "starting…";
  $("#job-log").scrollTop = $("#job-log").scrollHeight;
  $("#job-status").textContent = job.running
    ? `${job.name} running · ${job.elapsed}s`
    : `${job.name} finished in ${job.elapsed}s`;
  $("#job-start").disabled = job.running;
  if (job.running) setTimeout(pollJob, 1500);
}

const pollJob = async () => renderJob(await api("/api/jobs/current"));

$("#job-start").onclick = async () => {
  $("#job-start").disabled = true;
  try {
    renderJob(await api("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: $("#job-kind").value,
        source: $("#job-source").value,
        n: Number($("#job-n").value),
      }),
    }));
  } catch (e) {
    $("#job-status").textContent = e.message;
    $("#job-start").disabled = false;
  }
};

// --- review -----------------------------------------------------------------

LOADERS.review = async () => {
  const sel = $("#review-thesis");
  if (sel.options.length <= 1) {
    const { theses } = await api("/api/theses");
    theses.forEach((t) => sel.append(el("option", { value: t.id, textContent: t.name })));
  }
  loadCandidates();
};

async function loadCandidates() {
  const q = new URLSearchParams({ limit: "40" });
  if ($("#review-thesis").value) q.set("thesis", $("#review-thesis").value);
  const { candidates } = await api(`/api/candidates?${q}`);

  $("#review-count").textContent = `${candidates.length} waiting`;
  if (!candidates.length) {
    $("#candidates").replaceChildren(
      el("p", { className: "empty", textContent: "Nothing to review. Collect and score first." }));
    return;
  }

  $("#candidates").replaceChildren(...candidates.map((c) => {
    const meta = [
      el("span", { className: "pill", textContent: c.source }),
      el("span", { className: "num", textContent: pct(c.score ?? c.similarity) }),
    ];
    if (c.thesis) meta.push(el("span", { textContent: c.thesis }));
    if (c.stage) meta.push(el("span", { className: "pill", textContent: c.stage }));
    if (c.author) meta.push(el("span", { textContent: `by ${c.author}` }));

    const card = el("article", { className: "cand" }, [
      el("h3", {}, [el("a", { href: c.url, target: "_blank", rel: "noopener",
                             textContent: c.title || c.url })]),
      el("div", { className: "meta" }, meta),
      el("p", { textContent: esc(c.text).slice(0, 320) }),
    ]);
    if (c.reasoning) card.append(el("p", { className: "why", textContent: c.reasoning }));

    const mark = async (good) => {
      await api(`/api/candidates/${c.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ good }),
      });
      card.remove();
      $("#review-count").textContent =
        `${document.querySelectorAll("#candidates .cand").length} waiting`;
    };

    card.append(el("div", { className: "actions" }, [
      el("button", { className: "act good", textContent: "Good lead", onclick: () => mark(true) }),
      el("button", { className: "act bad", textContent: "Not relevant", onclick: () => mark(false) }),
    ]));
    return card;
  }));
}

$("#review-refresh").onclick = loadCandidates;
$("#review-thesis").onchange = loadCandidates;

// --- reports ----------------------------------------------------------------

LOADERS.reports = async () => {
  const sel = $("#report-thesis");
  if (!sel.options.length) {
    const { theses } = await api("/api/theses");
    theses.forEach((t) => sel.append(el("option", { value: t.id, textContent: t.name })));
    sel.onchange = loadReport;
  }
  loadReport();
};

async function loadReport() {
  const id = $("#report-thesis").value;
  if (!id) return;
  const r = await api(`/api/reports/${id}`);

  // Each fund gets its own columns, because they asked different questions.
  $("#report-head").replaceChildren(
    el("th", { className: "num", textContent: "Score" }),
    el("th", { textContent: "Source" }),
    ...r.columns.map((c) => el("th", { textContent: c.label })));

  $("#report-note").textContent = r.rows.length
    ? `${r.rows.length} candidates, in ${r.thesis}'s own report format.`
    : "Nothing yet. Run the pipeline with --research to fill these in.";

  $("#report-body").replaceChildren(...r.rows.map((row) =>
    el("tr", {}, [
      el("td", { className: "num", textContent: pct(row.score) }),
      el("td", {}, [el("a", { href: row.url, target: "_blank", rel: "noopener",
                              textContent: row.source })]),
      ...r.columns.map((c) => el("td", { textContent: row.fields[c.key] || "—" })),
    ])));
}

// --- sheet ------------------------------------------------------------------

LOADERS.sheet = loadSheet;
$("#sheet-refresh").onclick = loadSheet;

async function loadSheet() {
  const d = await api("/api/sheet");
  $("#sheet-note").textContent = d.configured
    ? "Edit any cell below and it writes straight back to Google. The pipeline only ever appends, so your edits are safe."
    : d.detail;

  const open = $("#sheet-open");
  open.style.display = d.url ? "inline-block" : "none";
  if (d.url) open.href = d.url;

  if (!d.configured) {
    $("#sheet-head").replaceChildren();
    $("#sheet-body").replaceChildren();
    return;
  }

  $("#sheet-head").replaceChildren(...d.headers.map((h) => el("th", { textContent: h })));
  $("#sheet-body").replaceChildren(...d.rows.map((row, i) =>
    el("tr", {}, d.headers.map((_, col) => {
      const td = el("td", {
        textContent: row[col] ?? "",
        contentEditable: "true",
        spellcheck: false,
      });
      let before = td.textContent;
      td.onblur = async () => {
        if (td.textContent === before) return;
        const value = td.textContent;
        try {
          // +2: rows are 0-indexed here and the sheet has a header row.
          await api("/api/sheet/cell", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ row: i + 2, column: col + 1, value }),
          });
          before = value;
        } catch (e) {
          td.textContent = before;
          $("#sheet-note").textContent = `Could not save: ${e.message}`;
        }
      };
      return td;
    }))));
}

// --- setup ------------------------------------------------------------------

LOADERS.setup = async () => {
  const { items } = await api("/api/setup");
  $("#setup-list").replaceChildren(...items.map((i) =>
    el("div", { className: "setup-item" }, [
      el("div", {}, [
        el("div", { textContent: i.name, style: "font-weight:500" }),
        el("code", { textContent: i.env }),
        el("div", { className: "note", style: "margin:4px 0 0", textContent: i.unlocks }),
        i.where?.startsWith("http")
          ? el("a", { href: i.where, target: "_blank", rel: "noopener", textContent: i.where })
          : el("div", { className: "note", style: "margin:2px 0 0", textContent: i.where || "" }),
      ]),
      el("span", {
        className: `pill ${i.present ? "on" : "off"}`,
        textContent: i.present ? "configured" : "not set",
      }),
    ])));
};

LOADERS.dashboard();
