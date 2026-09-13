// No framework. A sidebar, some tables and seven source tabs do not justify a build
// step and 40kB of runtime.

const $ = (s) => document.querySelector(s);
const el = (tag, props = {}, kids = []) => {
  const n = Object.assign(document.createElement(tag), props);
  for (const k of [].concat(kids)) if (k != null) n.append(k);
  return n;
};
const api = async (path, opts = {}) => {
  // A body always means JSON here. Setting the header in one place rather than at
  // every call site: FastAPI rejects a JSON body without it, and forgetting it is
  // a 422 that looks like a validation bug in the endpoint.
  if (opts.body) opts.headers = { "Content-Type": "application/json", ...opts.headers };
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};
const num = (n) => (n == null ? "—" : n.toFixed(3));
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// Empty states say what to do next. An empty table with no explanation is the most
// common way a tool loses a non-technical user.
const emptyRow = (cols, heading, hint) =>
  el("tr", {}, [el("td", { colSpan: cols, className: "empty" }, [
    el("strong", { textContent: heading }),
    el("span", { textContent: hint }),
  ])]);

let SOURCES = [];
let FUNDS = [];
const LOADERS = {};
const fundName = (id) => (FUNDS.find((f) => f.id === id) || {}).name || id;

// --- navigation --------------------------------------------------------------

function show(tab, sourceKey) {
  document.querySelectorAll("#rail nav button").forEach((b) => {
    const active = b.dataset.tab === tab &&
      (!sourceKey || b.dataset.source === sourceKey);
    b.setAttribute("aria-current", active ? "page" : "false");
  });
  document.querySelectorAll("main > section").forEach((s) => (s.hidden = s.id !== tab));
  if (tab === "source") loadSource(sourceKey);
  else LOADERS[tab]?.();
}

// Delegated, so a data-tab button anywhere in the page navigates — the first-run
// prompt on the dashboard is one, and binding only the rail left it inert.
document.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (b) show(b.dataset.tab, b.dataset.source);
});

// --- sidebar source list -----------------------------------------------------

async function buildSourceNav() {
  const { sources } = await api("/api/sources");
  SOURCES = sources;

  $("#source-nav").replaceChildren(...sources.map((s) => {
    const btn = el("button", { dataset: { tab: "source", source: s.key } }, [
      el("span", { textContent: s.label }),
      s.ready
        ? el("span", { className: "dot", textContent: s.candidates || "" })
        : el("span", { className: "dot warn", textContent: "setup", title: s.setup || "" }),
    ]);
    // No onclick: the delegated handler above reads both data attributes, and
    // binding here as well fired show() twice and loaded the source twice.
    return btn;
  }));

  const total = sources.reduce((a, s) => a + s.candidates, 0);
  $("#brand-sub").textContent = `${total.toLocaleString()} found so far`;

  const pick = $("#job-source");
  if (pick && !pick.options.length) {
    sources.forEach((s) =>
      pick.append(el("option", { value: s.key, textContent: s.label })));
  }
}

// --- dashboard ---------------------------------------------------------------

LOADERS.dashboard = async () => {
  const d = await api("/api/overview");
  const total = d.sources.reduce((a, s) => a + s.total, 0);
  const scored = d.sources.reduce((a, s) => a + (s.scored || 0), 0);

  // Nothing downstream can work without a thesis, so a fresh install is told
  // that first rather than being shown five zeroes and left to guess.
  const fresh = !d.funds;
  $("#first-run").hidden = !fresh;
  $("#first-run-note").textContent = d.first_run || "";

  $("#c-review").textContent = d.reviewed.n ? "" : "";
  $("#metrics").replaceChildren(...[
    ["Candidates found", total, "across every source"],
    ["Scored", scored, "matched against your funds"],
    ["Places watched", d.nodes.total || 0, "subreddits, newsletters, orgs"],
    ["You have reviewed", d.reviewed.n, "teaches the system your bar"],
    ["Marked promising", d.reviewed.good || 0, ""],
  ].map(([label, value, hint]) =>
    el("div", { className: "card metric" }, [
      el("span", { textContent: label }),
      el("b", { textContent: (value ?? 0).toLocaleString() }),
      hint ? el("em", { textContent: hint }) : null,
    ])));

  renderJob(d.job);
  loadDeployment().catch(() => {});
};

async function loadDeployment() {
  const q = new URLSearchParams({
    slots: $("#dep-slots").value,
    months: $("#dep-months").value,
    deals_per_month: $("#dep-rate").value,
  });
  const d = await api(`/api/deployment?${q}`);
  $("#dep-out").replaceChildren(...[
    ["Your bar today", num(d.threshold_now), "take anything scoring above this"],
    ["Halfway through", num(d.threshold_midway), "it falls as time runs out"],
    ["Final month", num(d.threshold_final), "take what you can get"],
    ["Deals expected", d.arrivals_expected, "before the window closes"],
  ].map(([label, value, hint]) =>
    el("div", { className: "card metric" }, [
      el("span", { textContent: label }),
      el("b", { textContent: value }),
      el("em", { textContent: hint }),
    ])));
}
$("#dep-go").onclick = loadDeployment;

function renderJob(job) {
  if (!job) return;
  const lines = job.lines.filter((l) => !/^usage: |^\s*\[-h\]|^collect\.py: error/.test(l));
  $("#job-log").textContent = lines.join("\n") || "starting…";
  $("#job-log").scrollTop = $("#job-log").scrollHeight;
  $("#job-status").textContent = job.running
    ? `Running for ${job.elapsed}s`
    : `Finished in ${job.elapsed}s`;
  $("#job-start").disabled = job.running;
  if (job.running) setTimeout(async () => renderJob(await api("/api/jobs/current")), 1500);
}

// score, pipeline and entities work on everything already collected. Showing a
// "where" picker for them implies a choice that does not exist, and sending an
// empty one produced an argparse usage dump.
const JOB_NEEDS_SOURCE = new Set(["collect"]);

function syncJobForm() {
  const needs = JOB_NEEDS_SOURCE.has($("#job-kind").value);
  $("#job-source").style.display = needs ? "" : "none";
  $("#job-n").style.display = $("#job-kind").value === "score" ? "none" : "";
}
$("#job-kind").onchange = syncJobForm;

$("#job-start").onclick = async () => {
  $("#job-start").disabled = true;
  try {
    renderJob(await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        kind: $("#job-kind").value, source: $("#job-source").value,
        n: Number($("#job-n").value),
      }),
    }));
  } catch (e) {
    $("#job-status").textContent = e.message;
    $("#job-start").disabled = false;
  }
};
syncJobForm();

// --- one tab per source ------------------------------------------------------

async function loadSource(key) {
  const d = await api(`/api/sources/${key}`);
  const meta = SOURCES.find((s) => s.key === key) || {};

  $("#src-title").textContent = d.label;
  $("#src-what").textContent = d.what;

  const status = [];
  if (!meta.ready) {
    status.push(el("div", { className: "banner" }, [
      el("strong", { textContent: "Not connected yet" }),
      el("p", { textContent: d.setup || "This source needs to be set up first." }),
    ]));
  }
  if (meta.local_only) {
    status.push(el("div", { className: "banner" }, [
      el("strong", { textContent: "Runs on this computer only" }),
      el("p", { textContent: meta.local_reason }),
    ]));
  }
  $("#src-status").replaceChildren(...status);

  $("#src-metrics").replaceChildren(...[
    ["Found here", meta.candidates || 0, ""],
    ["Scored", meta.scored || 0, "matched against your funds"],
    ["Reviewed by AI", meta.triaged || 0, ""],
    ["Watching", meta.watching || 0, "places it checks"],
  ].map(([label, value, hint]) =>
    el("div", { className: "card metric" }, [
      el("span", { textContent: label }),
      el("b", { textContent: value.toLocaleString() }),
      hint ? el("em", { textContent: hint }) : null,
    ])));

  $("#src-recent").replaceChildren(...(d.recent.length
    ? d.recent.map((r) => el("tr", {}, [
        el("td", { className: "num", textContent: num(r.score ?? r.similarity) }),
        el("td", {}, [el("a", { href: r.url, target: "_blank", rel: "noopener",
                                textContent: r.title || r.url })]),
        el("td", { textContent: r.author || "—" }),
      ]))
    : [emptyRow(3, "Nothing found here yet",
        meta.ready ? `Use "Look for new candidates" on the dashboard and pick ${d.label}.`
                   : "Connect this source first, using the note above.")]));

  const titles = {
    reddit: "Subreddits it watches", substack: "Newsletters it follows",
    github: "Organisations it follows", hackernews: "Searches it runs",
    whatsapp: "Chats you have imported", inbound: "Folders it reads",
    linkedin: "Profiles it has saved",
  };
  $("#src-watching-title").textContent = titles[key] || "What it is watching";
  $("#src-watching").replaceChildren(...(d.watching.length
    ? d.watching.map((w) => el("tr", {}, [
        el("td", { textContent: w.name || w.node }),
        el("td", { className: "num", textContent: w.seen }),
        el("td", { className: "num", textContent: w.hits }),
        el("td", {}, [el("span", { className: "pill",
          textContent: w.kind === "discovered" ? "found by itself" : w.kind })]),
      ]))
    : [emptyRow(4, "Not watching anything yet",
        "It will fill in once this source has run once.")]));
}

// --- review ------------------------------------------------------------------

LOADERS.review = async () => {
  const sel = $("#review-thesis");
  if (sel.options.length <= 1) {
    const { theses } = await api("/api/theses");
    FUNDS = theses;
    theses.forEach((t) => sel.append(el("option", { value: t.id, textContent: t.name })));
  }
  loadCandidates();
};

async function loadCandidates() {
  const q = new URLSearchParams({ limit: "40" });
  if ($("#review-thesis").value) q.set("thesis", $("#review-thesis").value);
  const { candidates } = await api(`/api/candidates?${q}`);

  const chosen = $("#review-thesis").value;
  $("#review-count").textContent = chosen
    ? `${candidates.length} waiting for ${fundName(chosen)}`
    : `${candidates.length} waiting across all funds`;
  if (!candidates.length) {
    $("#candidates").replaceChildren(el("div", { className: "empty" }, [
      el("strong", { textContent: "Nothing to review" }),
      el("span", { textContent: "Find some candidates first, then score them." }),
    ]));
    return;
  }

  $("#candidates").replaceChildren(...candidates.map((c) => {
    const card = el("article", { className: "cand" }, [
      el("h3", {}, [el("a", { href: c.url, target: "_blank", rel: "noopener",
                             textContent: c.title || c.url })]),
      el("div", { className: "meta" }, [
        el("span", { className: "pill", textContent: c.source }),
        el("span", { className: "num", textContent: num(c.score ?? c.similarity) }),
        // Which fund this matched. Without it, filtering by a fund that already
        // dominates the list looks like the filter did nothing.
        c.thesis ? el("span", { className: "pill",
                                textContent: fundName(c.thesis) }) : null,
        c.stage && c.stage !== "unknown"
          ? el("span", { className: "pill", textContent: c.stage }) : null,
        c.author ? el("span", { textContent: `by ${c.author}` }) : null,
      ]),
      el("p", { textContent: (c.text || "").slice(0, 320) }),
      c.reasoning ? el("p", { className: "why", textContent: c.reasoning }) : null,
    ]);

    const mark = async (good) => {
      await api(`/api/candidates/${c.id}/review`, {
        method: "POST",
        body: JSON.stringify({ good }),
      });
      card.remove();
      const left = document.querySelectorAll("#candidates .cand").length;
      const f = $("#review-thesis").value;
      $("#review-count").textContent = f
        ? `${left} waiting for ${fundName(f)}` : `${left} waiting across all funds`;
    };

    card.append(el("div", { className: "actions" }, [
      el("button", { className: "act good", textContent: "Worth a look",
                     onclick: () => mark(true) }),
      el("button", { className: "act bad", textContent: "Not for us",
                     onclick: () => mark(false) }),
    ]));
    return card;
  }));
}
$("#review-refresh").onclick = loadCandidates;
$("#review-thesis").onchange = loadCandidates;

// --- founders ----------------------------------------------------------------

LOADERS.entities = loadEntities;
$("#entities-refresh").onclick = loadEntities;
$("#entities-build").onclick = async () => {
  const btn = $("#entities-build");
  btn.disabled = true;
  $("#entities-status").textContent = "Working through everything found…";
  try {
    const s = await api("/api/entities/build", { method: "POST" });
    $("#entities-status").textContent =
      `${s.mentions} mentions from ${s.candidates} candidates, ${s.scored} scored.`;
    loadEntities();
  } catch (e) {
    $("#entities-status").textContent = e.message;
  } finally { btn.disabled = false; }
};

async function loadEntities() {
  const { entities } = await api("/api/entities?limit=60");
  $("#entities-body").replaceChildren(...(entities.length
    ? entities.map((e) => {
        const row = el("tr", {}, [
          el("td", { className: "num", textContent: num(e.score) }),
          el("td", { textContent: e.name }),
          el("td", {}, [el("span", { className: "pill", textContent: e.kind })]),
          el("td", { className: "num", textContent: e.mentions }),
          el("td", {}, e.sources.map((s) =>
            el("span", { className: "pill", textContent: s }))),
          el("td", {}, [e.needs_review
            ? el("span", { className: "pill local", textContent: "check this",
                title: "Matched on name alone — confirm these are the same" })
            : null]),
        ]);
        row.style.cursor = "pointer";
        row.onclick = () => openDossier(e.id);
        return row;
      })
    : [emptyRow(6, "No profiles yet",
        'Press "Rebuild from what was found" once some candidates have been scored.')]));
}

async function openDossier(id) {
  const d = await api(`/api/entities/${id}`);
  const e = d.entity;

  const head = el("div", { className: "panel" }, [
    el("h2", { textContent: e.name }),
    el("div", { className: "meta" }, [
      el("span", { className: "pill", textContent: e.kind }),
      el("span", { className: "num", textContent: num(e.score) }),
      ...(e.domain ? [el("a", { href: `https://${e.domain}`, target: "_blank",
                               rel: "noopener", textContent: e.domain })] : []),
      ...e.sources.map((s) => el("span", { className: "pill", textContent: s })),
    ]),
  ]);
  if (d.scoring?.corroboration > 1) {
    head.append(el("p", { className: "note",
      textContent: `Found independently in ${d.scoring.sources} different places, which raises the score.` }));
  }

  const why = el("div", { className: "panel" }, [el("h2", { textContent: "Why this score" })]);
  d.breakdown.forEach((b) => why.append(
    el("div", { style: "display:flex;gap:8px;align-items:center;margin:3px 0" }, [
      el("span", { className: "num", style: "width:140px;font-size:12px", textContent: b.key }),
      el("span", { className: "num", style: "width:44px;font-size:12px", textContent: b.value.toFixed(2) }),
      el("span", { style: `height:8px;border-radius:2px;width:${Math.abs(b.contribution) * 240}px;background:${b.negative ? "var(--bad)" : "var(--primary)"}` }),
    ])));

  const support = el("div", { className: "panel" }, [
    el("h2", { textContent: "What it is based on" })]);
  support.append(...(d.support.length
    ? d.support.map((s) => el("p", { className: "why", style: "margin:6px 0" }, [
        el("span", { className: "num", style: "font-size:11px",
                     textContent: `${s.signal} ${s.score.toFixed(2)} ` }),
        el("span", { textContent: `“${s.quote}” ` }),
        el("a", { href: s.url, target: "_blank", rel: "noopener", textContent: s.source }),
      ]))
    : [el("p", { className: "note",
        textContent: "No verified quotes. Anything the AI could not point to in the original text is dropped rather than shown." })]));

  const paths = el("div", { className: "panel" }, [el("h2", { textContent: "People near them" })]);
  paths.append(d.warm_paths.length
    ? el("ul", { style: "margin:0;padding-left:18px" },
        d.warm_paths.map((p) => el("li", { textContent: p.describe })))
    : el("p", { className: "note", textContent: "Nobody in your sources is near this one." }));

  const ev = el("div", { className: "panel" }, [
    el("h2", { textContent: `Where it was found (${d.evidence.length})` })]);
  d.evidence.forEach((x) => ev.append(el("p", { style: "margin:6px 0;font-size:13px" }, [
    el("span", { className: "pill", textContent: x.source }),
    el("span", { textContent: " " }),
    el("a", { href: x.url, target: "_blank", rel: "noopener", textContent: x.title || x.url }),
  ])));

  $("#dossier").replaceChildren(head, why, support, paths, ev);
  $("#dossier").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// --- reports -----------------------------------------------------------------

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

  $("#report-head").replaceChildren(
    el("th", { className: "num", textContent: "Score" }),
    el("th", { textContent: "Source" }),
    ...r.columns.map((c) => el("th", { textContent: c.label })));

  $("#report-note").textContent = r.rows.length
    ? `${r.rows.length} candidates, in ${r.thesis}'s own format.`
    : "Nothing here yet. Run a full review pass with research turned on.";

  $("#report-body").replaceChildren(...(r.rows.length
    ? r.rows.map((row) => el("tr", {}, [
        el("td", { className: "num", textContent: num(row.score) }),
        el("td", {}, [el("a", { href: row.url, target: "_blank", rel: "noopener",
                                textContent: row.source })]),
        ...r.columns.map((c) => el("td", { textContent: row.fields[c.key] || "—" })),
      ]))
    : [emptyRow(2 + r.columns.length, "No reports yet",
        "Candidates need to be researched before they appear here.")]));
}

// --- sheet -------------------------------------------------------------------

LOADERS.sheet = async () => {
  const sel = $("#sheet-fund");
  if (!sel.options.length) {
    const { theses } = await api("/api/theses");
    FUNDS = theses;
    theses.forEach((t) => sel.append(el("option", { value: t.id, textContent: t.name })));
  }
  loadSheet();
};
$("#sheet-refresh").onclick = loadSheet;

$("#sheet-push").onclick = async () => {
  const btn = $("#sheet-push");
  btn.disabled = true;
  try {
    const r = await api("/api/sheet/push", {
      method: "POST",
      body: JSON.stringify({ thesis: $("#sheet-fund").value }),
    });
    $("#sheet-note").textContent = r.detail;
    if (r.appended) loadSheet();
  } catch (e) {
    $("#sheet-note").textContent = e.message;
  } finally { btn.disabled = false; }
};

async function loadSheet() {
  const d = await api("/api/sheet");
  $("#sheet-note").textContent = d.configured
    ? "Edit any cell and it saves straight back to Google. Nothing you write here is ever overwritten."
    : d.detail;

  const open = $("#sheet-open");
  open.style.display = d.url ? "inline-block" : "none";
  if (d.url) open.href = d.url;

  if (!d.configured) {
    $("#sheet-head").replaceChildren();
    $("#sheet-body").replaceChildren(emptyRow(1, "Not connected",
      "Connect a Google account on the Setup tab to write findings to a spreadsheet."));
    return;
  }

  $("#sheet-head").replaceChildren(...d.headers.map((h) => el("th", { textContent: h })));
  $("#sheet-body").replaceChildren(...d.rows.map((row, i) =>
    el("tr", {}, d.headers.map((_, col) => {
      const td = el("td", { textContent: row[col] ?? "", contentEditable: "true",
                            spellcheck: false });
      let before = td.textContent;
      td.onblur = async () => {
        if (td.textContent === before) return;
        const value = td.textContent;
        try {
          await api("/api/sheet/cell", {
            method: "POST",
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

// --- setup -------------------------------------------------------------------

LOADERS.setup = async () => {
  loadHardware();
  const { items, stored_in } = await api("/api/setup");
  $("#setup-where").textContent =
    `Saved to ${stored_in}, readable only by you. Keys are never shown again once saved.`;

  $("#setup-list").replaceChildren(...items.map((i) => {
    // One row per credential: what it unlocks, where to get it, somewhere to
    // paste it, and a button that spends one call proving it actually works. A
    // key that is present but wrong is worse than a missing one, because the
    // product reports itself configured and fails somewhere less visible.
    const status = el("span", { className: `pill ${i.present ? "on" : "off"}`,
                                textContent: i.present ? "connected" : "not set" });
    const note = el("span", { className: "sub" });
    const row = el("div", { className: "setup-item" }, [
      el("div", {}, [
        el("div", { textContent: i.name, style: "font-weight:500" }),
        el("div", { className: "note", style: "margin:2px 0", textContent: i.unlocks }),
        el("div", { className: "note", style: "margin:0" }, [
          el("code", { textContent: i.env }),
          el("span", { textContent: i.where ? `  —  ${i.where}` : "" }),
        ]),
      ]),
      status,
    ]);

    if (!i.settable) return row;

    const fields = [i.env, ...(i.extra_env ? [i.extra_env] : [])].map((name) =>
      el("input", { type: "password", autocomplete: "off", dataset: { env: name },
                    placeholder: i.present ? "•••• saved — type to replace" : name,
                    "aria-label": name }));

    const save = el("button", { className: "act", textContent: "Save" });
    const test = el("button", { className: "act", textContent: "Test" });

    save.onclick = async () => {
      save.disabled = true;
      note.textContent = "Saving…";
      try {
        for (const f of fields) {
          if (!f.value.trim()) continue;
          await api("/api/setup/key", {
            method: "POST",
            body: JSON.stringify({ name: f.dataset.env, value: f.value.trim() }),
          });
          f.value = "";                     // never leave a key sitting in the DOM
        }
        note.textContent = "Saved.";
        LOADERS.setup();
      } catch (e) {
        note.textContent = e.message || "Could not save that.";
      } finally {
        save.disabled = false;
      }
    };

    test.onclick = async () => {
      test.disabled = true;
      note.textContent = "Testing, this spends one call…";
      try {
        const r = await api("/api/setup/test", {
          method: "POST",
          body: JSON.stringify({ name: i.env, value: "" }),
        });
        note.textContent = r.ok ? `Works — ${r.detail}` : `Failed — ${r.detail}`;
      } catch (e) {
        note.textContent = e.message || "Could not test that.";
      } finally {
        test.disabled = false;
      }
    };

    row.append(el("div", { className: "controls key-entry" },
                  [...fields, save, test, note]));
    return row;
  }));
};

async function loadHardware() {
  try {
    const h = await api("/api/hardware");
    $("#hw-summary").textContent =
      `${h.summary}. About ${h.usable_gb} GB is free for AI right now. ${h.recommendation.reason}`;
  } catch (e) {
    $("#hw-summary").textContent = "Could not check this computer.";
  }
}

$("#hw-auto").onclick = async () => {
  const btn = $("#hw-auto");
  btn.disabled = true;
  $("#hw-status").textContent = "Working. This can take a few minutes.";
  $("#hw-log").hidden = false;
  $("#hw-log").textContent = "";
  try {
    const r = await api("/api/setup/auto", { method: "POST" });
    $("#hw-log").textContent = r.steps
      .map((s) => `${s.ok ? "✓" : "•"} ${s.detail}`).join("\n\n");
    $("#hw-status").textContent = r.ok ? "Done." : "Finished with notes below.";
    loadHardware();
  } catch (e) {
    $("#hw-status").textContent = e.message;
  } finally { btn.disabled = false; }
};

$("#th-create").onclick = async () => {
  const btn = $("#th-create");
  btn.disabled = true;
  try {
    const r = await api("/api/theses", {
      method: "POST",
      body: JSON.stringify({ name: $("#th-name").value, prose: $("#th-prose").value }),
    });
    $("#th-status").textContent = `Saved. Restart the app to start using it.`;
    $("#th-name").value = $("#th-prose").value = "";
  } catch (e) {
    $("#th-status").textContent = e.message;
  } finally { btn.disabled = false; }
};

// --- start -------------------------------------------------------------------

buildSourceNav().then(() => LOADERS.dashboard());
