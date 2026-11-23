"use strict";
/* Small helpers shared by pages. `h("div", {class: "x"}, "text", childNode)` builds DOM nodes safely
   (text is never treated as HTML, so patient or staff text can't inject markup). */

function h(tag, props, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "style") node.setAttribute("style", v);
    else if (k === "value") node.value = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

class ApiError extends Error {
  constructor(message, errors) { super(message); this.errors = errors || []; }
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let message = res.statusText, errors = [];
    try {
      const body = await res.json();
      if (body.detail && body.detail.errors) { errors = body.detail.errors; message = errors[0]; }
      else message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (e) { /* not JSON */ }
    throw new ApiError(message, errors);
  }
  return res.json();
}
const send = (method, path, body) => api(path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

let toastTimer;
function toast(message, id = "toast") {
  const t = document.getElementById(id);
  t.textContent = message; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 4500);
}

function formatInr(n) {
  const s = String(Math.round(n));
  if (s.length <= 3) return "₹" + s;
  let head = s.slice(0, -3), tail = s.slice(-3), groups = [];
  while (head.length > 2) { groups.unshift(head.slice(-2)); head = head.slice(0, -2); }
  if (head) groups.unshift(head);
  return "₹" + groups.concat(tail).join(",");
}
const priceRange = (a, b) => (a === b ? formatInr(a) : `${formatInr(a)} – ${formatInr(b)}`);
const pct = (n) => Math.round(n * 100) + "%";
