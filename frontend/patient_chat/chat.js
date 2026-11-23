"use strict";
/* Patient chat: a simulated WhatsApp conversation.
   - Sending a message calls POST /api/webhook/whatsapp (the "webhook").
   - New replies (including ones a receptionist sends later) are fetched by polling
     GET /api/chat/<phone>/messages every few seconds. */

const PATIENTS = [
  { name: "Aarav Sharma", phone: "919000000001" },
  { name: "Ishita Deshpande", phone: "919000000002" },
  { name: "Rohan Kapoor", phone: "919000000003" },
  { name: "Sneha Pawar", phone: "919000000004" },
  { name: "Vikas Naik", phone: "919000000005" },
];

const PROMPTS = [
  "What are your timings on Sunday?",
  "root canal ka kharcha kitna hoga?",
  "Which doctor does braces, and what is the cost?",
  "Is teeth whitening safe?",
  "Do you accept insurance or UPI?",
  "I want to book an appointment for Saturday evening",
  "Severe pain and swelling, I can't sleep",
  "I was overcharged and want a refund",
];

const QUICK = [
  ["Clinic timings", "What are your clinic timings?"],
  ["Root canal cost", "How much does a root canal cost?"],
  ["Our doctors", "Which doctors do you have?"],
  ["Location", "Where are you located?"],
  ["Book appointment", "I'd like to book an appointment"],
];

const POLL_MS = 2500;
const $ = (id) => document.getElementById(id);
const messagesEl = $("messages"), inputEl = $("input"), sendBtn = $("sendBtn"), noticeEl = $("notice"), toastEl = $("toast");

let patient = loadPatient();
let lastId = 0;
let lastDay = null;
let inFlight = false;
const rendered = new Set();

/* ---------- helpers ---------- */
function store(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* storage may be blocked */ } }
function recall(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
function loadPatient() { return PATIENTS.find((p) => p.phone === recall("dca_patient")) || PATIENTS[0]; }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { const body = await res.json(); detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail); } catch (e) { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

let toastTimer;
function toast(message) {
  toastEl.textContent = message;
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.hidden = true; }, 4000);
}

const IST = "Asia/Kolkata";
const dayKey = (iso) => new Date(iso).toLocaleDateString("en-CA", { timeZone: IST });
function dayLabel(key) {
  const today = dayKey(new Date().toISOString());
  const yesterday = dayKey(new Date(Date.now() - 864e5).toISOString());
  if (key === today) return "Today";
  if (key === yesterday) return "Yesterday";
  return new Date(key + "T12:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
const timeLabel = (iso) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: IST });

/* Turn plain text into DOM nodes, making links clickable (never uses innerHTML). */
function textNodes(text) {
  const frag = document.createDocumentFragment();
  text.split(/(https?:\/\/[^\s]+)/g).forEach((part, i) => {
    if (i % 2 === 1) {
      const a = el("a", "", part);
      a.href = part; a.target = "_blank"; a.rel = "noopener noreferrer";
      frag.append(a);
    } else if (part) frag.append(part);
  });
  return frag;
}

function scrollDown() { messagesEl.scrollTop = messagesEl.scrollHeight; }

/* ---------- rendering ---------- */

/* The WhatsApp mode chip: simulated (demo) vs the real Cloud API. Shows names of missing settings, never values. */
function showWhatsAppMode(meta, chip) {
  const wa = meta.whatsapp || {};
  if (meta.whatsapp_mode !== "cloud") { chip.textContent = "WhatsApp is simulated"; chip.className = "chip chip-warn"; chip.title = "No real WhatsApp connection: this is a demo."; return; }
  const ready = wa.ready_to_receive && wa.ready_to_send;
  chip.textContent = ready ? "WhatsApp: live (Cloud API)" : "WhatsApp: setup incomplete";
  chip.className = "chip " + (ready ? "chip-ok" : "chip-danger");
  chip.title = ready ? "Connected to the official Meta WhatsApp Cloud API." : "Missing in .env: " + (wa.missing || []).join(", ");
}

let cloudMode = false;      // true when the real WhatsApp Cloud API is on: this simulated chat must stay off
let showDummyNote = true;  // switched off if the clinic data no longer carries a "_notice"
function simNote() {
  if (cloudMode) return el("div", "sim-note", "WhatsApp Cloud mode is ON. Patients now write to the real WhatsApp number, so this simulated chat is switched off. Set WHATSAPP_MODE=simulated in .env to demo with it.");
  return el("div", "sim-note", "Simulated chat – not connected to real WhatsApp." + (showDummyNote ? " Clinic details are dummy sample data." : ""));
}

function renderMessage(msg) {
  document.querySelector(".empty")?.remove();
  const key = dayKey(msg.created_at);
  if (key !== lastDay) { lastDay = key; messagesEl.append(el("div", "day", dayLabel(key))); }

  const mine = msg.role === "patient";
  const row = el("div", "row " + (mine ? "out" : "in"));
  const bubble = el("div", "bubble");
  if (!mine) bubble.append(el("div", "who " + (msg.role === "assistant" ? "ai" : "staff"), msg.role === "assistant" ? "AI assistant" : "Reception team"));
  const text = el("div", "text");
  text.append(textNodes(msg.text));
  const meta = el("div", "meta");
  meta.append(el("span", "", timeLabel(msg.created_at)));
  if (mine) meta.append(el("span", "ticks", "✓"));
  bubble.append(text, meta);
  row.append(bubble);
  messagesEl.append(row);
  scrollDown();
  return row;
}

function showTyping() {
  const row = el("div", "row in typing-row");
  const bubble = el("div", "bubble");
  const dots = el("div", "typing");
  dots.append(el("i"), el("i"), el("i"));
  bubble.append(dots);
  row.append(bubble);
  messagesEl.append(row);
  scrollDown();
}
const hideTyping = () => document.querySelector(".typing-row")?.remove();

let noticeKey = "";
function setNotice(notice) {
  const key = notice ? `${notice.state}:${notice.urgent}` : "";
  if (!notice) noticeEl.hidden = true;
  else {
    noticeEl.hidden = false;
    noticeEl.className = "notice " + (notice.urgent ? "urgent" : "wait");
    if (notice.urgent) noticeEl.textContent = "Marked urgent – our reception team has been alerted. If this is a medical emergency, please call the clinic or go to the nearest hospital.";
    else if (notice.state === "escalated") noticeEl.textContent = "A member of our team will reply to you personally.";
    else noticeEl.textContent = "Your message has been passed to our reception team. They'll reply shortly.";
  }
  if (key !== noticeKey) { noticeKey = key; scrollDown(); }  // the notice shrinks the chat area, so keep the newest message in view
}

/* ---------- conversation ---------- */
async function loadConversation() {
  messagesEl.replaceChildren(simNote());
  lastId = 0; lastDay = null; rendered.clear(); setNotice(null);
  try {
    const data = await api(`/api/chat/${patient.phone}/messages?after_id=0`);
    messagesEl.classList.add("static");  // don't animate the history, only new messages
    data.messages.forEach((m) => { rendered.add(m.id); lastId = Math.max(lastId, m.id); renderMessage(m); });
    setTimeout(() => messagesEl.classList.remove("static"), 50);
    setNotice(data.notice);
    if (!data.messages.length) {
      const empty = el("div", "empty");
      empty.append(el("b", "", "Say hello 👋"), "Type a question below, or tap one of the quick questions.");
      messagesEl.append(empty);
    }
  } catch (err) {
    toast("Can't reach the server. Is it running? (python run.py)");
  }
}

async function poll() {
  if (inFlight || document.hidden) return;
  try {
    const data = await api(`/api/chat/${patient.phone}/messages?after_id=${lastId}`);
    data.messages.forEach((m) => {
      if (rendered.has(m.id)) return;
      rendered.add(m.id); lastId = Math.max(lastId, m.id); renderMessage(m);
    });
    setNotice(data.notice);
  } catch (err) { /* server may be restarting; try again next time */ }
}

async function sendMessage(raw) {
  const text = raw.trim();
  if (!text || inFlight || cloudMode) return;
  inFlight = true;
  inputEl.value = ""; autosize();

  const row = renderMessage({ role: "patient", text, created_at: new Date().toISOString() });
  row.classList.add("sending");
  try {
    const res = await api("/api/webhook/whatsapp", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: patient.phone, name: patient.name, text }),
    });
    row.classList.remove("sending");
    row.querySelector(".ticks").textContent = "✓✓";
    rendered.add(res.patient_message.id); lastId = Math.max(lastId, res.patient_message.id);
    if (res.reply) {
      rendered.add(res.reply.id); lastId = Math.max(lastId, res.reply.id);
      showTyping();
      await sleep(650 + Math.min(900, res.reply.text.length * 3));  // a short "typing…" pause feels natural
      hideTyping();
      renderMessage(res.reply);
    }
    setNotice(res.notice);
  } catch (err) {
    row.classList.remove("sending"); row.classList.add("failed");
    row.querySelector(".ticks").textContent = "!";
    inputEl.value = text; autosize();
    toast("Couldn't send: " + err.message);
  } finally {
    inFlight = false; autosize(); inputEl.focus();
  }
}

/* ---------- setup ---------- */
function autosize() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 110) + "px";
  sendBtn.disabled = inFlight || !inputEl.value.trim();
}

function buildControls() {
  const select = $("patientSelect");
  PATIENTS.forEach((p) => select.append(new Option(`${p.name}  ·  +${p.phone.slice(0, 2)} ${p.phone.slice(2, 7)} ${p.phone.slice(7)}`, p.phone)));
  select.value = patient.phone;
  select.addEventListener("change", () => {
    patient = PATIENTS.find((p) => p.phone === select.value);
    store("dca_patient", patient.phone);
    loadConversation();
  });

  PROMPTS.forEach((text) => {
    const b = el("button", "", text); b.type = "button";
    b.addEventListener("click", () => sendMessage(text));
    $("prompts").append(b);
  });
  QUICK.forEach(([label, text]) => {
    const b = el("button", "", label); b.type = "button";
    b.addEventListener("click", () => sendMessage(text));
    $("quick").append(b);
  });

  const side = $("side"), narrow = matchMedia("(max-width: 900px)");
  const syncSide = () => { side.open = !narrow.matches; };
  narrow.addEventListener("change", syncSide); syncSide();
}

$("composer").addEventListener("submit", (e) => { e.preventDefault(); sendMessage(inputEl.value); });
inputEl.addEventListener("input", autosize);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMessage(inputEl.value); }
});
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });

(async function init() {
  buildControls();
  try {
    const meta = await api("/api/meta");
    $("clinicName").textContent = meta.clinic_name;
    showDummyNote = Boolean(meta.dummy_notice);
    showWhatsAppMode(meta, $("waChip"));
    cloudMode = meta.whatsapp_mode === "cloud";
    if (cloudMode) {
      inputEl.disabled = true; inputEl.placeholder = "Simulated chat is off (WhatsApp Cloud mode)";
      document.querySelectorAll("#prompts button, #quick button, #patientSelect").forEach((n) => { n.disabled = true; });
    }
    $("dummyChip").hidden = !showDummyNote;
    $("aiModeChip").textContent = meta.ai_mode === "claude" ? "AI: Claude" : "AI: template mode";
    $("aiModeChip").title = meta.ai_mode === "claude" ? `Claude (${meta.model}) writes informational answers` : "Answers are built from templates – no API key needed";
  } catch (e) { /* the conversation loader shows the error */ }
  await loadConversation();
  autosize();
  setInterval(poll, POLL_MS);
})();
