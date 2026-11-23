"use strict";
/* Knowledge Base page: add / edit / delete clinic information, import & export spreadsheets (CSV),
   and "Test a question" to see how the assistant retrieves information and builds an answer.
   Uses the helpers in /shared/ui.js (h, api, send, toast...). */

const $ = (id) => document.getElementById(id);
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const LABELS = { treatments: "Treatments", doctors: "Doctors", faqs: "FAQs", clinic: "Clinic info" };
const INTENTS = {
  greeting: "Greeting", thanks: "Thanks", clinic_timings: "Clinic timings", location: "Location", contact_info: "Contact details",
  treatment_price: "Treatment price", treatment_info: "Treatment info", doctor_info: "Doctors", appointment_booking: "Appointment",
  appointment_change: "Reschedule / cancel", payment_insurance: "Payment & insurance", general_faq: "FAQ", emergency: "Emergency",
  complaint: "Complaint", medical_advice: "Medical question", unknown: "Not understood",
};
const METHODS = { precise: "Matched by name or keyword", topic: "Matched by topic", words: "Matched by shared words" };
const KINDS = { treatment: ["Treatment", "chip-info"], doctor: ["Doctor", "chip"], faq: ["FAQ", "chip-ok"], clinic: ["Clinic info", "chip-neutral"] };
const DECISIONS = {
  auto_send: ["Safe to reply automatically", "d-ok"], needs_approval: ["Needs a receptionist's approval", "d-warn"],
  escalate: ["Forwarded to a person", "d-danger"],
};
const EXAMPLES = [
  "How much does a root canal cost and which doctor does it?",
  "Is it okay to come in without an appointment?",
  "Do you have a wheelchair ramp?",
  "How much is a hair transplant and what are your timings?",
];

/* What each form asks for. Plain-English labels; nothing here needs programming knowledge. */
const SCHEMAS = {
  treatments: {
    noun: "treatment",
    fields: [
      { key: "name", label: "Treatment name", type: "text", required: true, help: "As patients should see it, e.g. Root Canal Treatment (RCT)" },
      { key: "short_name", label: "Short name", type: "text", help: "Optional. Used in lists, e.g. Root canal (RCT)" },
      { key: "aliases", label: "Other names patients use", type: "list", required: true, help: "One per line. Include spellings and nicknames, e.g. root canal, rct, rootcanal" },
      { key: "price_min", label: "Lowest price (₹)", type: "number", required: true, half: true },
      { key: "price_max", label: "Highest price (₹)", type: "number", required: true, half: true, help: "Same as the lowest if the price is fixed." },
      { key: "price_unit", label: "The price is…", type: "text", required: true, placeholder: "per tooth  /  per session  /  for the full treatment" },
      { key: "price_notes", label: "Price notes", type: "textarea", help: "Optional, e.g. what makes the price higher or lower" },
      { key: "variants", label: "Price options", type: "variants", help: "Optional, e.g. Metal braces 30000 – 50000" },
      { key: "duration", label: "How long it takes", type: "text", required: true, placeholder: "e.g. 1 to 3 visits of 45 to 60 minutes each" },
      { key: "description", label: "Description for patients", type: "textarea", required: true },
      { key: "handled_by", label: "Doctors who do this", type: "doctors" },
    ],
  },
  doctors: {
    noun: "doctor",
    fields: [
      { key: "name", label: "Name", type: "text", required: true, help: "e.g. Dr. Anjali Deshmukh" },
      { key: "title", label: "Role", type: "text", required: true, help: "e.g. Orthodontist (Braces & Aligners Specialist)" },
      { key: "qualification", label: "Qualification", type: "text", required: true, help: "e.g. BDS, MDS (Orthodontics)" },
      { key: "specialties", label: "Specialities", type: "list", required: true, help: "One per line" },
      { key: "specialty_keywords", label: "Words patients use to find this doctor", type: "list", help: "One per line, e.g. braces doctor, orthodontist" },
      { key: "experience_years", label: "Years of experience", type: "number", required: true, half: true },
      { key: "languages", label: "Languages spoken", type: "list", required: true, half: true, help: "One per line" },
      { key: "available_days", label: "Days available", type: "days", required: true },
      { key: "available_hours", label: "Hours on those days", type: "text", required: true, placeholder: "e.g. 2:00 PM to 8:00 PM" },
    ],
  },
  faqs: {
    noun: "FAQ",
    fields: [
      { key: "question", label: "Question", type: "text", required: true, help: "e.g. Do you accept walk-ins?" },
      { key: "keywords", label: "Phrases patients might type", type: "list", required: true, help: "One per line, lower-case, e.g. walk in / without appointment. The more phrases, the more often this answer is found." },
      { key: "answer", label: "Answer", type: "textarea", required: true, help: "Exactly what the assistant may tell patients. Put every number (prices, times) in here." },
    ],
  },
  clinic: {
    noun: "clinic information",
    fields: [
      { key: "clinic_name", label: "Clinic name", type: "text", required: true },
      { key: "short_name", label: "Short name", type: "text", required: true },
      { key: "tagline", label: "Tagline", type: "text" },
      { key: "address", label: "Address", type: "textarea", required: true },
      { key: "landmark", label: "Landmark", type: "text" },
      { key: "maps_link", label: "Google Maps link", type: "text" },
      { key: "parking", label: "Parking", type: "textarea" },
      { key: "phone", label: "Phone number", type: "text", required: true, half: true },
      { key: "email", label: "Email", type: "text", half: true },
      { key: "timings", label: "Opening hours", type: "timings", required: true, help: "Write hours like 10:00 AM to 8:00 PM" },
      { key: "closed_note", label: "Holiday note", type: "text", help: "e.g. The clinic is closed on major public holidays." },
      { key: "emergency_note", label: "Emergency guidance", type: "textarea", help: "Added to replies about dental emergencies" },
      { key: "payment_methods", label: "Payment methods", type: "list", help: "One per line" },
      { key: "insurance_note", label: "Insurance note", type: "textarea" },
      { key: "languages", label: "Languages the team speaks", type: "list" },
      { key: "appointment_policy", label: "Appointment policy", type: "textarea", help: "Included in every booking reply" },
    ],
  },
};

const state = { view: "edit", dataset: "treatments", summary: null, data: {}, query: "", editing: null, pendingImport: null };
const doctorsList = () => (state.data.doctors ? state.data.doctors.records : []);

/* ======================= loading ======================= */
async function loadSummary() { state.summary = await api("/api/kb/summary"); renderTabs(); renderIssues(); renderDummyChip(); }
async function loadDataset(name) { state.data[name] = await api(`/api/kb/${name}`); }

async function refreshAll() {
  await Promise.all([loadSummary(), loadDataset(state.dataset), state.dataset !== "doctors" ? loadDataset("doctors") : null, loadGaps()]);
  renderToolbar(); renderEntries();
}

function renderDummyChip() {
  const n = state.summary ? state.summary.dummy_entries : 0;
  $("dummyChip").hidden = n === 0;
  $("dummyChip").textContent = `Dummy data · ${n} ${n === 1 ? "entry" : "entries"}`;
}

/* ======================= tabs, toolbar, issues ======================= */
function renderTabs() {
  if (!state.summary) return;
  $("dsTabs").replaceChildren(...state.summary.datasets.map((d) => h("button", {
    class: "ds", type: "button", role: "tab", "aria-selected": String(d.name === state.dataset), onclick: () => setDataset(d.name),
  }, d.label, d.name === "clinic" ? null : h("span", { class: "n" }, d.count))));
}

async function setDataset(name) {
  state.dataset = name; state.query = ""; $("search").value = "";
  renderTabs();
  if (!state.data[name]) await loadDataset(name);
  renderToolbar(); renderEntries();
}

function renderToolbar() {
  const d = state.summary && state.summary.datasets.find((x) => x.name === state.dataset);
  const isClinic = state.dataset === "clinic";
  $("fileChip").textContent = d ? `data/${d.file}${d.dummy_count ? ` · ${d.dummy_count} dummy` : ""}` : "";
  $("addBtn").hidden = isClinic;
  $("search").hidden = isClinic;
  $("exportBtn").href = `/api/kb/${state.dataset}/export.csv`;
}

function renderIssues() {
  const issues = state.summary ? state.summary.issues : [];
  $("issues").hidden = issues.length === 0;
  if (!issues.length) return;
  $("issues").replaceChildren(h("b", {}, `${issues.length} thing${issues.length === 1 ? "" : "s"} worth checking`),
    h("ul", {}, issues.slice(0, 6).map((i) => h("li", {}, i.message))), issues.length > 6 ? h("div", { class: "muted" }, `…and ${issues.length - 6} more`) : null);
}

/* ======================= entries ======================= */
function subtitle(ds, r) {
  if (ds === "treatments") return `${priceRange(r.price_min, r.price_max)} ${r.price_unit} · ${r.duration}`;
  if (ds === "doctors") return `${r.title} · ${r.experience_years} years · ${r.available_days.map((d) => d.slice(0, 3)).join(", ")} ${r.available_hours}`;
  return r.answer.length > 170 ? r.answer.slice(0, 170) + "…" : r.answer;
}

function entryCard(ds, r) {
  const title = ds === "faqs" ? r.question : r.name;
  const extra = ds === "treatments" ? `also called: ${r.aliases.slice(0, 4).join(", ")}${r.aliases.length > 4 ? "…" : ""}` : ds === "faqs" ? `${r.keywords.length} phrases` : "";
  return h("div", { class: "entry" },
    h("div", { class: "main" }, h("h3", {}, title), h("div", { class: "sub" }, subtitle(ds, r)),
      h("div", { class: "meta" }, r.dummy ? h("span", { class: "chip chip-warn" }, "Sample data") : h("span", { class: "chip chip-ok" }, "Real"),
        extra ? h("span", { class: "chip chip-neutral" }, extra) : null, h("span", { class: "chip chip-neutral mono" }, r.id))),
    h("div", { class: "acts" },
      h("button", { class: "btn btn-sm", type: "button", onclick: () => openEditor(ds, r) }, "Edit"),
      h("button", { class: "btn btn-sm btn-danger", type: "button", onclick: () => deleteEntry(ds, r) }, "Delete")));
}

function clinicCard(c) {
  const rows = [["Name", c.clinic_name], ["Address", c.address], ["Landmark", c.landmark], ["Phone", c.phone], ["Email", c.email],
    ["Hours", (c.timings || []).map((t) => `${t.days}: ${t.hours}`).join("  ·  ")], ["Holidays", c.closed_note],
    ["Payments", (c.payment_methods || []).join(", ")], ["Insurance", c.insurance_note], ["Languages", (c.languages || []).join(", ")],
    ["Appointment policy", c.appointment_policy]].filter(([, v]) => v);
  return h("div", { class: "entry" }, h("div", { class: "main" }, h("h3", {}, "Clinic details"),
    h("div", { class: "meta", style: "margin-bottom:10px" }, c.dummy ? h("span", { class: "chip chip-warn" }, "Sample data") : h("span", { class: "chip chip-ok" }, "Real")),
    ...rows.map(([k, v]) => h("div", { class: "sub" }, h("b", {}, k + ": "), v))),
    h("div", { class: "acts" }, h("button", { class: "btn btn-sm btn-primary", type: "button", onclick: () => openEditor("clinic", c) }, "Edit")));
}

function renderEntries() {
  const ds = state.dataset, loaded = state.data[ds];
  if (!loaded) return;
  if (ds === "clinic") { $("entries").replaceChildren(clinicCard(loaded.record)); return; }
  const q = state.query.trim().toLowerCase();
  const list = loaded.records.filter((r) => !q || JSON.stringify(r).toLowerCase().includes(q));
  $("entries").replaceChildren(...(list.length ? list.map((r) => entryCard(ds, r)) : [h("div", { class: "empty" },
    h("h3", {}, q ? "Nothing matches your search" : "Nothing here yet"),
    h("p", {}, q ? "Try a different word." : "Press “+ Add” to add the first entry, or import a spreadsheet."))]));
}

async function deleteEntry(ds, r) {
  const name = ds === "faqs" ? r.question : r.name;
  if (!confirm(`Delete “${name}”?\n\nThe assistant will stop using it straight away. (A backup of the file is kept in data/backups/.)`)) return;
  try {
    const res = await send("DELETE", `/api/kb/${ds}/${r.id}`);
    toast("Deleted." + (res.notes.length ? " " + res.notes.join(" ") : ""));
    state.data = {}; await refreshAll();
  } catch (err) { toast(err.message); }
}

/* ======================= add / edit form ======================= */
function removeButton(onclick) { return h("button", { type: "button", "aria-label": "Remove this row", onclick }, "✕"); }

function buildField(f, value) {
  const id = "f_" + f.key;
  const wrap = h("div", { class: "field" + (f.half ? " half" : "") });
  const label = (forId) => h(forId ? "label" : "div", forId ? { for: forId } : { class: "lab" }, f.label, f.required ? h("span", { class: "req", "aria-hidden": "true" }, "*") : null);
  const help = f.help ? h("div", { class: "help" }, f.help) : null;
  let get;

  if (f.type === "text" || f.type === "number") {
    const input = h("input", { type: "text", id, placeholder: f.placeholder || "", inputmode: f.type === "number" ? "numeric" : null });
    input.value = value ?? "";
    wrap.append(label(id), input, help); get = () => input.value;
  } else if (f.type === "textarea" || f.type === "list") {
    const area = h("textarea", { id, rows: f.type === "list" ? 4 : 3 });
    area.value = f.type === "list" ? (value || []).join("\n") : value ?? "";
    wrap.append(label(id), area, help); get = () => area.value;
  } else if (f.type === "variants" || f.type === "timings") {
    const rows = h("div", { class: "rows" });
    const isV = f.type === "variants";
    const addRow = (v = {}) => {
      const a = h("input", { type: "text", "aria-label": isV ? "Option name" : "Days", placeholder: isV ? "Option name" : "e.g. Monday to Saturday" });
      const b = h("input", { type: "text", "aria-label": isV ? "Lowest price" : "Hours", placeholder: isV ? "Lowest ₹" : "e.g. 10:00 AM to 8:00 PM", inputmode: isV ? "numeric" : null });
      const c = isV ? h("input", { type: "text", "aria-label": "Highest price", placeholder: "Highest ₹", inputmode: "numeric" }) : null;
      a.value = isV ? v.name ?? "" : v.days ?? ""; b.value = isV ? v.price_min ?? "" : v.hours ?? ""; if (c) c.value = v.price_max ?? "";
      const row = h("div", { class: "row" + (isV ? "" : " t") }, a, b, c, removeButton(() => row.remove()));
      row._get = () => (isV ? { name: a.value, price_min: b.value, price_max: c.value } : { days: a.value, hours: b.value });
      rows.append(row);
    };
    (value || []).forEach(addRow);
    if (!isV && !(value || []).length) addRow();
    wrap.append(label(), help, rows, h("div", {}, h("button", { class: "btn btn-sm", type: "button", onclick: () => addRow() }, isV ? "+ Add an option" : "+ Add a row")));
    get = () => [...rows.children].map((r) => r._get()).filter((v) => Object.values(v).some((x) => String(x).trim()));
  } else if (f.type === "days") {
    const boxes = WEEKDAYS.map((d) => { const i = h("input", { type: "checkbox", value: d }); i.checked = (value || []).includes(d); return i; });
    wrap.append(label(), h("div", { class: "checks" }, WEEKDAYS.map((d, i) => h("label", {}, boxes[i], d))));
    get = () => boxes.filter((b) => b.checked).map((b) => b.value);
  } else if (f.type === "doctors") {
    const docs = doctorsList();
    const boxes = docs.map((d) => { const i = h("input", { type: "checkbox", value: d.id }); i.checked = (value || []).includes(d.id); return i; });
    wrap.append(label(), docs.length ? h("div", { class: "checks" }, docs.map((d, i) => h("label", {}, boxes[i], d.name))) : h("div", { class: "help" }, "Add doctors first (Doctors tab)."));
    get = () => boxes.filter((b) => b.checked).map((b) => b.value);
  }
  return { node: wrap, get };
}

function openEditor(dataset, record, prefill) {
  const schema = SCHEMAS[dataset], isNew = !record && dataset !== "clinic";
  const source = record || prefill || {};
  state.editing = { dataset, id: record ? record.id : null, isNew };
  $("editorTitle").textContent = dataset === "clinic" ? "Edit clinic information" : `${isNew ? "Add" : "Edit"} ${schema.noun}`;

  const built = schema.fields.map((f) => ({ f, ...buildField(f, source[f.key]) }));
  const dummy = h("input", { type: "checkbox", id: "f_dummy" });
  dummy.checked = record ? Boolean(record.dummy) : false;
  const dummyBox = h("div", { class: "dummy-box" }, h("label", {}, dummy, h("span", {}, "This is sample (dummy) information",
    h("div", { class: "help" }, "Tick this for made-up examples. Untick it once the information is real – sample entries are flagged on every page."))));

  $("editorBody").replaceChildren(...[
    record && record.id ? h("div", { class: "idline" }, `ID: ${record.id} (this never changes)`) : null,
    ...built.map((b) => b.node), dummyBox].filter(Boolean));
  state.editing.collect = () => { const out = {}; built.forEach((b) => { out[b.f.key] = b.get(); }); out.dummy = dummy.checked; return out; };
  $("editorErrors").hidden = true;
  $("editor").showModal();
  const first = $("editorBody").querySelector("input[type=text],textarea"); if (first) first.focus();
}

$("editorForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const { dataset, id, isNew, collect } = state.editing, data = collect();
  $("editorSave").disabled = true;
  try {
    if (dataset === "clinic") await send("PUT", "/api/kb/clinic", data);
    else if (isNew) await send("POST", `/api/kb/${dataset}`, data);
    else await send("PUT", `/api/kb/${dataset}/${id}`, data);
    $("editor").close();
    toast("Saved. The assistant is using the new information now.");
    state.data = {}; await refreshAll();
  } catch (err) {
    const list = err.errors && err.errors.length ? err.errors : [err.message];
    $("editorErrors").replaceChildren(h("b", {}, "Please fix this before saving:"), h("ul", {}, list.map((m) => h("li", {}, m))));
    $("editorErrors").hidden = false; $("editorErrors").scrollIntoView({ block: "nearest" });
  } finally { $("editorSave").disabled = false; }
});
for (const id of ["editorCancel", "editorClose"]) $(id).addEventListener("click", () => $("editor").close());

/* ======================= CSV import ======================= */
$("importBtn").addEventListener("click", () => $("importFile").click());
$("importFile").addEventListener("change", async (e) => {
  const file = e.target.files[0]; e.target.value = "";
  if (!file) return;
  const text = await file.text();
  try {
    const res = await send("POST", `/api/kb/${state.dataset}/import`, { csv: text, dry_run: true });
    state.pendingImport = res.ok ? text : null;
    renderImport(res, file.name);
    $("importDlg").showModal();
  } catch (err) { toast(err.message); }
});

function renderImport(res, filename) {
  const label = LABELS[state.dataset];
  const list = (title, items) => items.length ? h("div", {}, h("b", {}, title), h("ul", {}, items.slice(0, 12).map((i) => h("li", {}, i)), items.length > 12 ? h("li", {}, `…and ${items.length - 12} more`) : null)) : null;
  const body = [h("div", { class: "imp" }, h("p", {}, `File: `, h("b", {}, filename), ` → replaces the current “${label}” list.`))];
  if (!res.ok) {
    body.push(h("div", { class: "imp" }, h("div", { class: "warnbox" }, h("b", {}, "This file can't be imported yet:"), h("ul", {}, res.errors.slice(0, 10).map((m) => h("li", {}, m))))));
    $("importConfirm").hidden = true;
  } else {
    body.push(h("div", { class: "imp" }, h("div", { class: "nums" },
      h("div", { class: "num" }, h("b", {}, res.added.length), "new"), h("div", { class: "num" }, h("b", {}, res.updated.length), "changed"),
      h("div", { class: "num" }, h("b", {}, res.removed.length), "removed")),
      list("New", res.added), list("Changed", res.updated), list("Will be DELETED (not in the file)", res.removed),
      res.warnings.length ? h("div", { class: "muted" }, res.warnings.join(" ")) : null,
      h("p", { class: "muted" }, "Nothing has been changed yet. A backup of the current file is saved before replacing it.")));
    $("importConfirm").hidden = false;
  }
  $("importBody").replaceChildren(...body);
}
$("importConfirm").addEventListener("click", async () => {
  try {
    const res = await send("POST", `/api/kb/${state.dataset}/import`, { csv: state.pendingImport, dry_run: false });
    if (!res.ok) throw new Error(res.errors[0]);
    $("importDlg").close(); toast("Imported. The assistant is using the new information now.");
    state.data = {}; await refreshAll();
  } catch (err) { toast(err.message); }
});
for (const id of ["importCancel", "importClose"]) $(id).addEventListener("click", () => $("importDlg").close());

/* ======================= questions the assistant could not answer ======================= */
async function loadGaps() {
  const { questions } = await api("/api/kb/gaps");
  const box = $("gaps");
  box.replaceChildren(h("h2", {}, "Questions it couldn't answer"),
    h("p", { class: "hint" }, "Patients asked these and the knowledge base had no (full) answer. Add the answer here so next time it can reply by itself."),
    ...(questions.length ? questions.map((g) => h("div", { class: "gap" }, h("div", { class: "q" }, `“${g.question}”`),
      h("div", {}, h("button", { class: "btn btn-sm", type: "button", onclick: () => { setDataset("faqs").then(() => openEditor("faqs", null, { question: g.question })); } }, "Add as FAQ"),
        " ", g.partial ? h("span", { class: "chip chip-warn" }, "partly answered") : null)))
      : [h("div", { class: "muted" }, "None yet – every question so far was covered. 🎉")]));
}

/* ======================= test a question ======================= */
function chip(text, cls = "chip-neutral") { return h("span", { class: "chip " + cls }, text); }
function step(no, title, ...kids) { return h("section", { class: "step" }, h("h3", {}, h("span", { class: "no" }, no), title), ...kids); }

function renderResult(t) {
  const u = t.understood;
  const understood = step(1, "What the assistant understood",
    h("div", { class: "chips" }, u.intents.map((i, n) => chip(INTENTS[i] || i, n === 0 ? "chip" : "chip-neutral")), chip(`${pct(u.confidence)} sure`),
      u.sensitive ? chip("Sensitive topic", "chip-danger") : null, u.entities.when ? chip("when: " + u.entities.when) : null));

  const retrieved = step(2, `Entries retrieved from the knowledge base (${t.retrieved.length})`,
    ...(t.retrieved.length ? t.retrieved.map((s) => {
      const [kl, kc] = KINDS[s.kind] || [s.kind, "chip-neutral"];
      return h("div", { class: "src" + (s.used ? " used" : "") },
        h("div", { class: "top" }, chip(kl, kc), h("span", { class: "title" }, s.title), chip(s.id, "chip-neutral mono"),
          s.used ? chip("Used in the answer", "chip-ok") : chip("Retrieved, not used"), s.dummy ? chip("Sample data", "chip-warn") : null,
          h("span", { class: "score" }, pct(s.score), h("span", { class: "meter" }, h("i", { style: `width:${pct(s.score)}` })))),
        h("div", { class: "muted", style: "margin-top:4px" }, `${METHODS[s.method] || s.method} · from data/${s.file}`),
        h("ul", {}, s.why.map((w) => h("li", {}, w))),
        h("details", {}, h("summary", {}, "Show the entry's text"), h("p", {}, s.text)));
    }) : [h("p", { class: "muted" }, "Nothing relevant was found in the knowledge base.")]));

  const g = t.generation;
  const generation = step(3, "How the answer was generated",
    h("div", { class: "chips" }, chip(g.mode === "claude" ? `Claude · ${g.model}` : "Template mode", g.mode === "claude" ? "chip-info" : "chip-neutral")),
    h("p", { style: "margin-top:8px" }, g.how),
    g.note ? h("p", { class: "muted" }, g.note) : null,
    h("details", { class: "more" }, h("summary", {}, "The context an AI model would receive (only these entries)"), h("pre", {}, t.context || "(empty – nothing relevant was retrieved, so the model would not be asked)")),
    h("details", { class: "more" }, h("summary", {}, "The full instructions sent to the model"), h("pre", {}, "SYSTEM\n" + t.prompt.system + "\n\nUSER\n" + t.prompt.user)));

  const refs = t.parts.filter((p) => p.sources.length);
  const answer = step(4, t.answerable ? "The answer" : "No answer – forwarded to reception",
    t.answerable ? h("div", { class: "answer" }, t.answer)
      : h("div", {}, h("p", { class: "muted", style: "margin-bottom:8px" }, "The information is not in the knowledge base, so the assistant does not guess. The patient is told:"),
        h("div", { class: "answer none" }, t.holding_reply)),
    t.answerable ? h("div", { class: "refs" }, h("b", {}, "Where each part came from "), h("span", { class: "muted" }, "(internal – the receptionist sees this, the patient does not)"),
      ...(refs.length ? refs.map((p) => h("div", { class: "ref" }, h("span", { class: "txt" }, "“" + p.text.trim().split("\n")[0].slice(0, 80) + (p.text.length > 80 ? "…" : "") + "”"),
        p.sources.map((s) => chip(s, "chip-ok mono")))) : [h("div", { class: "muted" }, "No clinic facts are quoted in this reply.")])) : null);

  const [dl, dc] = DECISIONS[t.decision] || [t.decision, "d-warn"];
  const decision = step(5, "Decision", h("div", { class: "decision " + dc }, h("b", {}, dl), h("ul", {}, t.reasons.map((r) => h("li", {}, r)))),
    h("details", { class: "more" }, h("summary", {}, `Safety checks (${t.checks.length})`),
      ...t.checks.map((c) => { const [cls, ic] = c.passed ? ["ic-ok", "✓"] : c.severity === "block" ? ["ic-bad", "✕"] : ["ic-warn", "!"];
        return h("div", { class: "chk" }, h("div", { class: "ic " + cls }, ic), h("div", {}, h("b", {}, c.label), h("div", { class: "muted" }, c.detail))); })));

  $("result").replaceChildren(understood, retrieved, generation, answer, decision);
}

async function ask(question) {
  question = question.trim(); if (!question) return;
  $("question").value = question; $("askBtn").disabled = true;
  try { renderResult(await send("POST", "/api/kb/ask", { question })); }
  catch (err) { toast(err.message); } finally { $("askBtn").disabled = false; }
}
$("askForm").addEventListener("submit", (e) => { e.preventDefault(); ask($("question").value); });
$("examples").replaceChildren("Try:", ...EXAMPLES.map((q) => h("button", { type: "button", onclick: () => ask(q) }, q)));

/* ======================= views ======================= */
function setView(view) {
  state.view = view;
  $("viewEdit").hidden = view !== "edit"; $("viewTest").hidden = view !== "test";
  $("tabEdit").setAttribute("aria-selected", String(view === "edit")); $("tabTest").setAttribute("aria-selected", String(view === "test"));
  if (view === "test") $("question").focus();
}
$("tabEdit").addEventListener("click", () => setView("edit"));
$("tabTest").addEventListener("click", () => setView("test"));
$("addBtn").addEventListener("click", () => openEditor(state.dataset, null));
$("search").addEventListener("input", (e) => { state.query = e.target.value; renderEntries(); });

(async function init() {
  try {
    const meta = await api("/api/meta");
    $("clinicName").textContent = meta.clinic_name;
    $("aiModeChip").textContent = meta.ai_mode === "claude" ? "AI: Claude" : "AI: template mode";
    await refreshAll();
  } catch (err) { toast("Can't reach the server. Is it running? (python run.py)"); }
  if (location.hash === "#test") setView("test");
})();
