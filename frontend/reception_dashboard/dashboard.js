"use strict";
/* Receptionist dashboard.
   Every 3 seconds it asks the server for the latest numbers and message list
   (GET /api/dashboard/stats and /api/dashboard/inquiries). Clicking a message loads its
   full detail: the conversation, what the AI understood, its draft, the knowledge-base
   sources it used and the safety checks it ran. */

const POLL_MS = 3000;
const IST = "Asia/Kolkata";
const $ = (id) => document.getElementById(id);

const INTENTS = {
  greeting: "Greeting", thanks: "Thanks", clinic_timings: "Clinic timings", location: "Location", contact_info: "Contact details",
  treatment_price: "Treatment price", treatment_info: "Treatment info", doctor_info: "Doctors",
  appointment_booking: "Appointment", appointment_change: "Reschedule / cancel", payment_insurance: "Payment & insurance",
  general_faq: "FAQ", emergency: "Emergency", complaint: "Complaint", medical_advice: "Medical question",
  unknown: "Not understood", error: "System error", non_text: "Voice / photo / file",
};
const STATUS = {
  auto_replied: { label: "Auto-replied", chip: "chip-ok", bar: "bar-ok" },
  pending_approval: { label: "Needs approval", chip: "chip-warn", bar: "bar-warn" },
  escalated: { label: "Escalated", chip: "chip-danger", bar: "bar-danger" },
  approved: { label: "Approved & sent", chip: "chip-info", bar: "bar-info" },
  replied: { label: "Replied by staff", chip: "chip-info", bar: "bar-info" },
  dismissed: { label: "Dismissed", chip: "chip-neutral", bar: "bar-neutral" },
};
const DECISION = {
  auto_send: { label: "Verified – every check passed, sent automatically", cls: "d-ok" },
  needs_approval: { label: "Held for approval – nothing was sent to the patient", cls: "d-warn" },
  escalate: { label: "Held back – nothing was sent to the patient; a person must handle this", cls: "d-danger" },
};
const KIND = { treatment: ["Treatment", "chip-info"], doctor: ["Doctor", "chip"], faq: ["FAQ", "chip-ok"], clinic: ["Clinic info", "chip-neutral"] };
const TABS = [["open", "Needs action"], ["pending", "Pending"], ["escalated", "Escalated"], ["auto", "Auto-replied"], ["resolved", "Resolved"], ["all", "All"]];
const AVATARS = [["#e2f4f5", "#0a5c64"], ["#e8edff", "#2a47b8"], ["#fde9e7", "#a8352a"], ["#fff1d4", "#8a5509"], ["#ece5fb", "#6a3bb0"], ["#e1f5ec", "#14805a"]];

const state = { tab: "open", selectedId: null, loaded: null, stats: null, list: [], knownMax: null, meta: null, busy: false };

/* ---------- helpers ---------- */
function h(tag, props, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "style") node.setAttribute("style", v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText, structured = null;
    try {
      const body = await res.json();
      structured = body.detail && typeof body.detail === "object" ? body.detail : null;
      detail = typeof body.detail === "string" ? body.detail : (structured && structured.message) || JSON.stringify(body.detail);
    } catch (e) { /* ignore */ }
    const error = new Error(detail);
    error.detail = structured;
    throw error;
  }
  return res.json();
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });

let toastTimer;
function toast(message) {
  const t = $("toast");
  t.textContent = message; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 4200);
}


/* The WhatsApp mode chip: simulated (demo) vs the real Cloud API. Shows names of missing settings, never values. */
function showWhatsAppMode(meta, chip) {
  const wa = meta.whatsapp || {};
  if (meta.whatsapp_mode !== "cloud") { chip.textContent = "WhatsApp is simulated"; chip.className = "chip chip-warn"; chip.title = "No real WhatsApp connection: this is a demo."; return; }
  const ready = wa.ready_to_receive && wa.ready_to_send;
  chip.textContent = ready ? "WhatsApp: live (Cloud API)" : "WhatsApp: setup incomplete";
  chip.className = "chip " + (ready ? "chip-ok" : "chip-danger");
  chip.title = ready ? "Connected to the official Meta WhatsApp Cloud API." : "Missing in .env: " + (wa.missing || []).join(", ");
}

function ago(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: IST });
}
const fullTime = (iso) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: IST });
const clock = (iso) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: IST });
const phoneLabel = (d) => `+${d.slice(0, 2)} ${d.slice(2, 7)} ${d.slice(7)}`;
const pct = (n) => Math.round(n * 100) + "%";

function avatar(name, large) {
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
  let hash = 0; for (const c of name) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
  const [bg, fg] = AVATARS[hash % AVATARS.length];
  return h("div", { class: "av" + (large ? " lg" : ""), style: `--av-bg:${bg};--av-fg:${fg}`, "aria-hidden": "true" }, initials);
}
const intentChip = (key, primary) => h("span", { class: "chip " + (primary ? "chip" : "chip-neutral") }, INTENTS[key] || key);
const statusChip = (status) => h("span", { class: "chip " + (STATUS[status]?.chip || "chip-neutral") }, STATUS[status]?.label || status);
const isOpen = (status) => status === "pending_approval" || status === "escalated";

/* ---------- stats and tabs ---------- */
function renderStats() {
  const s = state.stats; if (!s) return;
  const per = state.meta ? state.meta.minutes_saved_per_auto_reply : 2;
  const cards = [
    { label: "Messages handled", value: s.total, sub: `${s.counts.open} need attention`, tone: "tone-brand" },
    { label: "Auto-replied", value: s.auto_replied, sub: `${s.auto_rate}% of all messages`, tone: "tone-ok", tab: "auto" },
    { label: "Pending approval", value: s.pending, sub: "waiting for a receptionist", tone: "tone-warn", tab: "pending" },
    { label: "Escalated", value: s.escalated, sub: s.urgent_open ? `${s.urgent_open} urgent` : "need a person", tone: "tone-danger", tab: "escalated" },
    { label: "Estimated time saved", value: s.minutes_saved + " min", sub: `assumes ${per} min per auto-reply`, tone: "tone-info" },
  ];
  $("stats").replaceChildren(...cards.map((c) => {
    const node = h(c.tab ? "button" : "div", { class: "stat " + c.tone, "data-tab": c.tab, type: c.tab ? "button" : null },
      h("div", { class: "label" }, c.label), h("div", { class: "value" }, c.value), h("div", { class: "sub" }, c.sub));
    if (c.tab) node.addEventListener("click", () => setTab(c.tab));
    return node;
  }));
}

function renderTabs() {
  const counts = state.stats?.counts || {};
  $("tabs").replaceChildren(...TABS.map(([key, label]) => {
    const n = counts[key] ?? 0;
    const hot = key === "escalated" && state.stats?.urgent_open > 0;
    return h("button", { class: "tab", role: "tab", type: "button", "aria-selected": String(state.tab === key), onclick: () => setTab(key) },
      label, h("span", { class: "count" + (hot ? " hot" : "") }, n));
  }));
}

function setTab(tab) { state.tab = tab; renderTabs(); refresh(); }

/* ---------- list ---------- */
function renderList() {
  const list = $("list");
  const total = state.stats?.total ?? 0;
  if (!state.list.length) {
    list.replaceChildren(total === 0 ? firstRunState() : h("div", { class: "empty-state" },
      h("div", { class: "big" }, state.tab === "open" ? "🎉" : "📭"),
      h("h3", {}, state.tab === "open" ? "All caught up" : "Nothing here"),
      h("p", {}, state.tab === "open" ? "No messages are waiting for you right now." : "No messages match this filter.")));
    return;
  }
  list.replaceChildren(...state.list.map((it) => {
    const fresh = state.knownMax !== null && it.id > state.knownMax;
    return h("button", {
      class: `item ${STATUS[it.status]?.bar || ""}${fresh ? " fresh" : ""}`, type: "button",
      "aria-current": String(it.id === state.selectedId), onclick: () => openDetail(it.id),
    },
      avatar(it.patient_name),
      h("div", { class: "item-main" },
        h("div", { class: "item-top" }, h("span", { class: "item-name" }, it.patient_name), h("span", { class: "item-time", title: fullTime(it.created_at) }, ago(it.created_at))),
        h("div", { class: "item-text" }, it.question),
        h("div", { class: "item-tags" },
          it.urgent && isOpen(it.status) ? h("span", { class: "chip chip-danger" }, "Urgent") : null,
          it.failed_checks && isOpen(it.status) ? h("span", { class: "chip chip-danger" }, "Failed verification") : null,
          statusChip(it.status), it.rag && it.rag.answerable === false ? h("span", { class: "chip chip-danger" }, "Not in knowledge base") : intentChip(it.intent, false))));
  }));
}

function firstRunState() {
  return h("div", { class: "empty-state" },
    h("div", { class: "big" }, "💬"),
    h("h3", {}, "No messages yet"),
    h("p", {}, "Send a message from the patient chat, or load a set of sample conversations to explore the dashboard."),
    h("div", { class: "btns" },
      h("button", { class: "btn btn-primary", type: "button", onclick: seedDemo }, "Load sample conversations"),
      h("a", { class: "btn", href: "/chat/", target: "_blank", rel: "noopener" }, "Open patient chat ↗")));
}

/* ---------- detail ---------- */
/* How a reply got to the patient, for the conversation history. */
function messageMeta(m) {
  const meta = m.meta || {}, bits = [];
  if (meta.verified) bits.push(`✓ Verified automatically (${meta.checks_passed} of ${meta.checks_total} checks passed)`);
  if (meta.kind === "not_in_knowledge_base_notice") bits.push("Fixed notice: the answer is not in the knowledge base");
  if (meta.approved_by) bits.push(meta.edited ? "Edited and sent by the receptionist" : "AI draft approved by the receptionist");
  if (meta.overrode_checks && meta.overrode_checks.length) bits.push("Receptionist overrode: " + meta.overrode_checks.join("; "));
  if (m.delivery && m.delivery !== "simulated") {   // real WhatsApp: sent -> delivered -> read, or failed
    bits.push(m.delivery === "failed" ? "⚠ Not delivered on WhatsApp: " + (m.delivery_error || "failed") : "WhatsApp: " + m.delivery);
  }
  return bits;
}

const VGROUPS = [["source", "1. Relevant source in the knowledge base"], ["price_doctor", "2. Prices and doctor names"],
  ["calendar", "3. Appointment availability"], ["medical", "4. Diagnosis and medicine"], ["validity", "5. Valid and complete"], ["routing", "Routing"]];
const groupStatus = (list) => list.some((c) => !c.passed && c.severity === "block") ? "bad" : list.some((c) => !c.passed && c.severity === "warn") ? "warn" : "ok";
const STATUS_ICON = { ok: ["ic-ok", "✓", "chip-ok"], warn: ["ic-warn", "!", "chip-warn"], bad: ["ic-bad", "✕", "chip-danger"] };

function checkRow(c) {
  const [cls, icon] = c.passed ? (c.severity === "info" ? ["ic-info", "✓"] : ["ic-ok", "✓"]) : c.severity === "block" ? ["ic-bad", "✕"] : ["ic-warn", "!"];
  return h("div", { class: "check" }, h("div", { class: "ic " + cls }, icon), h("div", {}, h("div", { class: "label" }, c.label), h("div", { class: "why" }, c.detail)));
}

/* The verification result, grouped under the five questions every answer must pass. */
function verification(inq) {
  if (!inq.checks.length) return h("p", { class: "muted" }, "No verification was recorded.");
  const groups = VGROUPS.map(([key, title]) => [key, title, inq.checks.filter((c) => (c.group || "validity") === key)]).filter((g) => g[2].length);
  const summary = h("div", { class: "vsum" }, groups.filter((g) => g[0] !== "routing").map(([, title, list]) => {
    const [, icon, chip] = STATUS_ICON[groupStatus(list)];
    return h("span", { class: "chip " + chip }, icon + " " + title.replace(/^\d\.\s*/, ""));
  }));
  return h("div", {}, summary, ...groups.map(([, title, list]) => {
    const st = groupStatus(list), [icls, icon] = STATUS_ICON[st];
    return h("details", { class: "vgroup", open: st !== "ok" },
      h("summary", {}, h("span", { class: "ic " + icls }, icon), title, h("span", { class: "n" }, `${list.filter((c) => c.passed).length} of ${list.length} passed`)),
      h("div", { class: "checks" }, list.map(checkRow)));
  }));
}

function activity(inq) {
  const trail = inq.audit || [];
  if (!trail.length) return h("p", { class: "muted" }, "No activity recorded.");
  return h("div", { class: "trail" }, trail.map((e) => h("div", { class: "ev" },
    h("span", { class: "when" }, clock(e.at)), h("span", { class: "by" }, e.by), h("span", { class: "what" }, e.detail || e.event))));
}

/* The internal source references: which knowledge entries this answer was built from. */
function builtFrom(inq) {
  const rag = inq.rag || {};
  if (rag.answerable === false) {
    return h("div", { class: "built none" }, h("b", {}, "Not in the knowledge base. "),
      "The assistant did not guess." + (rag.holding_reply ? " The patient was told the reception team will reply." : ""));
  }
  const ids = rag.used_sources || [];
  if (!ids.length) return h("div", { class: "built" }, "No clinic facts are quoted in this reply.");
  return h("div", { class: "built" }, h("b", {}, "Built from: "), ids.map((id) => h("span", { class: "chip chip-ok mono" }, id)),
    rag.parts && rag.parts.some((p) => p.sources.length) ? h("details", { class: "orig" }, h("summary", {}, "Which part came from where"),
      ...rag.parts.filter((p) => p.sources.length).map((p) => h("div", { class: "partref" },
        h("span", {}, "“" + p.text.trim().split("\n")[0].slice(0, 70) + (p.text.length > 70 ? "…" : "") + "”"), p.sources.map((id) => h("span", { class: "chip chip-ok mono" }, id))))) : null);
}

function renderDetail(inq) {
  const open = isOpen(inq.status);
  const decision = DECISION[inq.decision] || DECISION.escalate;

  const head = h("div", { class: "d-head" },
    h("button", { class: "btn btn-sm btn-ghost back", type: "button", onclick: closeDetail }, "← Back"),
    avatar(inq.patient_name, true),
    h("div", { class: "d-who" }, h("h2", {}, inq.patient_name), h("div", { class: "muted" }, `${phoneLabel(inq.patient_phone)} · ${fullTime(inq.created_at)}`)),
    h("div", { class: "d-chips" }, inq.urgent ? h("span", { class: "chip chip-danger" }, "Urgent") : null, statusChip(inq.status)));

  /* conversation */
  const thread = h("div", { class: "thread" }, inq.thread.map((m) => h("div", { class: "t-row " + (m.role === "patient" ? "t-in" : "t-out") + (m.id === inq.message_id ? " t-focus" : "") },
    h("div", { class: "t-bubble" },
      m.role === "patient" ? null : h("div", { class: "t-who" }, m.role === "assistant" ? "AI assistant" : "Receptionist"),
      m.text,
      m.sources && m.sources.length ? h("div", { class: "t-src" }, "Source: ", m.sources.map((s) => h("span", { class: "chip chip-ok mono", title: `${s.title} (data/${s.file})` }, s.id))) : null,
      ...messageMeta(m).map((b) => h("div", { class: "t-meta" + (b.startsWith("⚠") ? " bad" : "") }, b)),
      h("div", { class: "t-time" }, clock(m.created_at))))));

  /* AI analysis */
  const barColor = inq.confidence >= 0.8 ? "#1fa971" : inq.confidence >= 0.7 ? "var(--brand)" : "#e0a21a";
  const analysis = h("div", {},
    h("div", { class: "analysis" },
      h("div", { class: "mini" }, h("div", { class: "k" }, "Topic understood"),
        h("div", { class: "chips" }, (inq.intents.length ? inq.intents : [inq.intent]).map((i, n) => intentChip(i, n === 0)))),
      h("div", { class: "mini" }, h("div", { class: "k" }, "Confidence"), h("div", { class: "big-num" }, pct(inq.confidence)),
        h("div", { class: "meter" }, h("i", { style: `width:${pct(inq.confidence)};--fill:${barColor}` }))),
      h("div", { class: "mini" }, h("div", { class: "k" }, "Answer written by"),
        h("div", { class: "big-num", style: "font-size:17px" }, inq.rag && inq.rag.answerable === false ? "Nobody – not found" : inq.draft_mode === "claude" ? "Claude" : inq.draft_mode === "none" ? "Nobody (error)" : "Template"))),
    h("div", { class: "decision " + decision.cls },
      h("div", { class: "title" }, decision.label),
      h("ul", {}, inq.reasons.map((r) => h("li", {}, r))),
      inq.draft_note ? h("div", { class: "note" }, inq.draft_note) : null));

  /* reply */
  let reply, actions = null;
  const failedBlocks = inq.checks.filter((c) => !c.passed && c.severity === "block");
  const wasRejected = Boolean(inq.rag && inq.rag.draft_rejected);
  if (open) {
    const box = h("textarea", { class: "reply-box", rows: "8", "aria-label": "Reply to the patient",
      placeholder: "The AI did not write a draft for this message. Type your reply to the patient…" });
    box.value = inq.draft;
    const sendBtn = h("button", { class: "btn btn-primary", type: "button" });
    const updateSend = () => {
      const t = box.value.trim();
      sendBtn.disabled = !t || state.busy;
      const unchanged = t && t === inq.draft.trim();
      sendBtn.textContent = unchanged ? (failedBlocks.length ? "Send anyway…" : "Approve & send") : inq.draft.trim() ? "Send edited reply" : "Send reply";
    };
    box.addEventListener("input", updateSend);
    box.addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && !sendBtn.disabled) sendBtn.click(); });
    sendBtn.addEventListener("click", () => sendReply(inq, box.value));
    updateSend();

    const help = wasRejected ? "You rejected the AI draft, so it will not be sent. Write your own reply below."
      : !inq.draft.trim() ? "The AI did not write a draft for this message. Write your reply to the patient."
      : inq.status === "escalated" ? "The AI did not send this. Review the suggested reply, change anything you like, then send it yourself."
      : "Nothing has been sent yet. Approve the AI's draft as it is, edit it first, or reject it.";
    const failNote = inq.draft.trim() && failedBlocks.length ? h("div", { class: "failnote" },
      h("b", {}, "This draft failed verification, so it was not sent."),
      h("ul", {}, failedBlocks.map((c) => h("li", {}, h("b", {}, c.label + ": "), c.detail))),
      "It is only sent if you confirm.") : null;
    const windowNote = inq.whatsapp_window && !inq.whatsapp_window.open ? h("div", { class: "failnote" },
      h("b", {}, "More than 24 hours since the patient's last message. "),
      "WhatsApp only allows a free-form reply within 24 hours, so sending will probably be refused. An approved message template is needed, or wait for the patient to write again.") : null;
    reply = h("div", {}, windowNote, failNote, h("p", { class: "help" }, help), box, builtFrom(inq),
      wasRejected && inq.rag.rejected_draft ? h("details", { class: "orig" }, h("summary", {}, "Show the rejected AI draft"), h("pre", {}, inq.rag.rejected_draft)) : null);
    actions = h("div", { class: "d-actions" }, sendBtn,
      inq.draft.trim() ? h("button", { class: "btn btn-danger", type: "button", title: "Do not send this AI draft", onclick: () => rejectDraft(inq) }, "Reject draft") : null,
      inq.status === "pending_approval" ? h("button", { class: "btn", type: "button", title: "Mark as needing a person (doctor or manager) to handle", onclick: () => act(inq, "escalate", null, "Escalated") }, "Escalate") : null,
      h("button", { class: "btn btn-ghost", type: "button", onclick: () => { if (confirm("Close this message without sending a reply?")) act(inq, "dismiss", null, "Closed without a reply"); } }, "Close without reply"),
      h("span", { class: "spacer" }, "Ctrl/⌘ + Enter to send"));
  } else if (inq.status === "dismissed") {
    reply = h("div", { class: "sent closed" }, h("div", { class: "by" }, "Closed without a reply"), h("div", { class: "txt" }, "No message was sent to the patient."));
  } else {
    const by = inq.status === "auto_replied" ? "Sent automatically by the AI assistant"
      : inq.status === "approved" ? "AI draft approved and sent by the receptionist" : "Reply written and sent by the receptionist";
    const text = inq.status === "auto_replied" ? inq.draft : inq.final_reply;
    reply = h("div", { class: "sent" }, h("div", { class: "by" }, by + (inq.resolved_at ? " · " + fullTime(inq.resolved_at) : "")), h("div", { class: "txt" }, text),
      inq.status === "replied" && inq.draft ? h("details", { class: "orig" }, h("summary", {}, "Show the original AI draft"), h("pre", {}, inq.draft)) : null);
    reply.append(builtFrom(inq));
  }

  /* sources */
  const METHOD = { precise: "name or keyword match", topic: "topic match", words: "shared words" };
  const sources = inq.sources.length ? h("div", { class: "sources" }, inq.sources.map((s) => {
    const [kindLabel, kindClass] = KIND[s.kind] || [s.kind, "chip-neutral"];
    return h("div", { class: "source" + (s.used ? " used" : "") },
      h("div", { class: "top" }, h("span", { class: "chip " + kindClass }, kindLabel), h("span", { class: "title" }, s.title),
        s.used ? h("span", { class: "chip chip-ok" }, "Used in answer") : h("span", { class: "chip chip-neutral" }, "Not used"),
        s.dummy ? h("span", { class: "chip chip-warn" }, "Sample data") : null,
        h("span", { class: "match" }, "match " + pct(s.score), h("div", { class: "meter" }, h("i", { style: `width:${pct(s.score)}` })))),
      h("div", { class: "file" }, h("span", { class: "mono" }, s.id), ` · data/${s.file}` + (s.method ? ` · ${METHOD[s.method] || s.method}` : "")),
      s.why && s.why.length ? h("ul", { class: "why" }, s.why.map((w) => h("li", {}, w))) : null,
      h("details", {}, h("summary", {}, "Show source text"), h("p", {}, s.text)));
  })) : h("p", { class: "muted" }, "No knowledge-base entries matched this message.");

  const sec = (title, node, count) => h("section", { class: "sec" }, h("h3", {}, title, count !== undefined ? h("span", { class: "n" }, count) : null), node);
  const body = h("div", { class: "d-body" },
    sec("Conversation", thread), sec("AI analysis", analysis),
    sec(open ? "Reply" : "Reply sent", reply),
    sec("Sources retrieved", sources, inq.sources.length ? `${inq.sources.length} found` : undefined),
    sec("Verification checks", verification(inq)), sec("Activity", activity(inq)));

  $("detail").replaceChildren(head, body, ...(actions ? [actions] : []));
  const t = $("detail").querySelector(".thread"); if (t) t.scrollTop = t.scrollHeight;
}

function renderEmptyDetail() {
  $("detail").replaceChildren(h("div", { class: "empty-state" }, h("div", { class: "big" }, "👈"),
    h("h3", {}, "Select a message"), h("p", {}, "Pick a conversation on the left to see the AI's draft, why it was held, the sources it used and the verification checks.")));
}

async function openDetail(id) {
  try {
    state.selectedId = id;
    state.loaded = await api(`/api/dashboard/inquiries/${id}`);
    renderDetail(state.loaded); renderList();
    $("inbox").classList.add("show-detail");
  } catch (err) { toast("Couldn't open that message: " + err.message); }
}
function closeDetail() { $("inbox").classList.remove("show-detail"); }

async function act(inq, action, body, successMessage) {
  if (state.busy) return;
  state.busy = true;
  try {
    state.loaded = await post(`/api/dashboard/inquiries/${inq.id}/${action}`, body);
    toast(successMessage);
    renderDetail(state.loaded);
    await refresh();
  } catch (err) {
    toast(err.message);
    await openDetail(inq.id);
  } finally { state.busy = false; }
}

/* Approve or edit: send the reply. If verification flagged problems the receptionist must confirm. */
async function sendReply(inq, text, acknowledge = false) {
  if (state.busy) return;
  state.busy = true;
  try {
    state.loaded = await post(`/api/dashboard/inquiries/${inq.id}/send`, { text, acknowledge });
    toast(`Reply sent to ${inq.patient_name}`);
    renderDetail(state.loaded);
    await refresh();
  } catch (err) {
    if (err.detail && err.detail.needs_acknowledgement) {
      state.busy = false;
      const lines = err.detail.warnings.map((w) => `• ${w.label}\n    ${w.detail}`).join("\n");
      if (confirm(`This reply did not pass verification:\n\n${lines}\n\nSend it to the patient anyway?`)) return sendReply(inq, text, true);
      return;
    }
    toast(err.message);
    await openDetail(inq.id);
  } finally { state.busy = false; }
}

async function rejectDraft(inq) {
  const reason = prompt("Reject this AI draft?\nIt will NOT be sent. You can then write your own reply.\n\nReason (optional):");
  if (reason === null) return;
  await act(inq, "reject", { reason }, "Draft rejected – it was not sent");
}

/* ---------- data refresh ---------- */
function setLive(ok) { const l = $("live"); l.classList.toggle("off", !ok); l.querySelector("span").textContent = ok ? "Live" : "Offline – retrying"; }

async function refresh() {
  try {
    const [stats, list] = await Promise.all([api("/api/dashboard/stats"), api(`/api/dashboard/inquiries?status=${state.tab}`)]);
    const increased = state.knownMax !== null && stats.newest_inquiry_id > state.knownMax;
    state.stats = stats; state.list = list.inquiries;
    renderStats(); renderTabs(); renderList();
    state.knownMax = stats.newest_inquiry_id;
    if (increased) toast("New patient message received");
    document.title = (stats.counts.open ? `(${stats.counts.open}) ` : "") + "Reception Dashboard – Dental Clinic AI";

    if (state.selectedId && state.loaded && !state.busy) {  // refresh the open message if someone else changed it
      const row = list.inquiries.find((i) => i.id === state.selectedId);
      if (row && row.status !== state.loaded.status) { state.loaded = await api(`/api/dashboard/inquiries/${row.id}`); renderDetail(state.loaded); }
    }
    setLive(true);
  } catch (err) { setLive(false); }
}

/* ---------- demo tools and settings ---------- */
async function seedDemo() {
  try { const r = await post("/api/dashboard/seed-demo"); toast(`Added ${r.added} sample conversations`); await refresh(); }
  catch (err) { toast("Couldn't load samples: " + err.message); }
}

async function resetDemo() {
  if (!confirm("Delete ALL conversations and AI records? This cannot be undone.")) return;
  try {
    await post("/api/dashboard/reset");
    state.selectedId = null; state.loaded = null; renderEmptyDetail(); closeDetail();
    toast("All demo data deleted"); await refresh();
  } catch (err) { toast("Couldn't reset: " + err.message); }
}

async function init() {
  $("seedBtn").addEventListener("click", () => { $("demoMenu").open = false; seedDemo(); });
  $("resetBtn").addEventListener("click", () => { $("demoMenu").open = false; resetDemo(); });
  document.addEventListener("click", (e) => { if (!$("demoMenu").contains(e.target)) $("demoMenu").open = false; });
  $("autoToggle").addEventListener("change", async (e) => {
    try {
      const s = await post("/api/dashboard/settings", { auto_reply: e.target.checked });
      toast(s.auto_reply ? "AI auto-reply is ON – safe questions are answered instantly." : "AI auto-reply is OFF – every reply now waits for your approval.");
    } catch (err) { e.target.checked = !e.target.checked; toast("Couldn't change the setting: " + err.message); }
  });

  try {
    state.meta = await api("/api/meta");
    $("clinicName").textContent = state.meta.clinic_name;
    $("dummyChip").hidden = !state.meta.dummy_notice;
    showWhatsAppMode(state.meta, $("waChip"));
    if (state.meta.whatsapp_mode === "cloud") $("demoMenu").hidden = true;   // demo tools could touch real patient data
    $("aiModeChip").textContent = state.meta.ai_mode === "claude" ? "AI: Claude" : "AI: template mode";
    $("aiModeChip").title = state.meta.ai_mode === "claude" ? `Claude (${state.meta.model}) writes informational answers` : "Answers are built from templates – no API key needed";
    $("autoToggle").checked = (await api("/api/dashboard/settings")).auto_reply;
  } catch (err) { setLive(false); }

  renderTabs(); renderEmptyDetail();
  await refresh();
  setInterval(refresh, POLL_MS);
}
init();
