// Shared plumbing: DOM helper, the API (with the Clerk token when the page is reached through the tunnel), pictures, jobs, tiny event bus.
export const $ = (id) => document.getElementById(id);
export const S = { profiles: [], templates: [], profile: null, deck: null, template: "classic", job: null, status: {}, sets: null, coverage: null, policy: null };

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
}

const bus = new EventTarget();
export const on = (name, fn) => bus.addEventListener(name, (e) => fn(e.detail));
export const emit = (name, detail) => bus.dispatchEvent(new CustomEvent(name, { detail }));

let getToken = async () => null;
let authed = false;
export const auth = { set(fn) { getToken = fn; authed = true; } };
const blobs = new Map();
export async function authFetch(path, init = {}) {
  const t = await getToken();
  return fetch(path, t ? { ...init, headers: { ...(init.headers || {}), Authorization: "Bearer " + t } } : init);
}
async function blobUrl(url) {
  if (!blobs.has(url)) blobs.set(url, authFetch(url).then(async (r) => { if (!r.ok) throw new Error(r.statusText); return URL.createObjectURL(await r.blob()); }));
  return blobs.get(url);
}
export function setSrc(img, url) {
  if (!authed) img.src = url; else blobUrl(url).then((u) => (img.src = u)).catch(() => {});
  return img;
}
export const pic = (url, attrs) => setSrc(h("img", attrs), url);
export async function saveAs(url, name) {
  const r = await authFetch(url);
  if (!r.ok) return fail(new Error((await r.text()).slice(0, 200) || r.statusText));
  const a = h("a", { href: URL.createObjectURL(await r.blob()), download: name });
  document.body.append(a); a.click(); a.remove();
}
export async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers["Content-Type"] = "application/json"; }
  if (opts.form) init.body = opts.form;
  const r = await authFetch(path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) {}
    const e = new Error(msg); e.status = r.status; throw e;
  }
  return r.json();
}
export const remember = (k, v) => { try { localStorage.setItem("pf-" + k, v); } catch (_) {} };
export const recall = (k) => { try { return localStorage.getItem("pf-" + k) || ""; } catch (_) { return ""; } };
export const debounce = (fn, ms = 600) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

// a toast instead of alert(): errors stay readable and never block the page
export function toast(msg, kind = "") {
  const t = h("div", { class: "toast " + kind, role: "status" }, String(msg));
  $("toasts").append(t);
  setTimeout(() => t.remove(), kind === "bad" ? 9000 : 4500);
}
export const fail = (e) => toast(e.message || e, "bad");

// jobs: the dock at the bottom shows progress; `after` runs when the job ends
export function follow(job, after) {
  S.job = job;
  const dock = $("dock");
  dock.hidden = false;
  let ticks = 0;
  const step = async () => {
    try {
      const j = await api(`/api/jobs/${job.id}`);
      $("bar").style.width = (j.total ? Math.round((100 * j.done) / j.total) : 6) + "%";
      $("dock-msg").textContent = j.message;
      if (S.deck && j.deck === S.deck.id && ++ticks % 3 === 0 && ["generate", "render", "art", "pin"].includes(j.kind)) { S.deck = await api(`/api/decks/${S.deck.id}`); emit("deck", S.deck); }
      if (j.state === "queued" || j.state === "running") return setTimeout(step, 900);
      $("dock-msg").textContent = j.state === "error" ? "Failed: " + j.error : j.message;
      if (j.state === "error") toast(j.error, "bad");
      if (S.deck && j.deck === S.deck.id) { S.deck = await api(`/api/decks/${S.deck.id}`); emit("deck", S.deck); emit("decks"); }
      if (after) await after(j);
      setTimeout(() => { if (S.job && S.job.id === job.id) dock.hidden = true; }, 3500);
    } catch (e) { $("dock-msg").textContent = e.message; }
  };
  step();
}

export const policyOf = (d) => ({ source: "forge", sets: [], family: true, treatment: "regular", pins: true, fallback: "nearest", vary_basics: true, print: "scan",
  ...(d && d.art_policy ? d.art_policy : {}), vault: { currency: "usd", basis: "median", foil: true, serialized: false, guard: true, scope: false, ...((d && d.art_policy && d.art_policy.vault) || {}) } });
export const money = (n, cur = "usd") => (n == null ? "" : (cur === "eur" ? "€" : "$") + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
export const ck = (k) => encodeURIComponent(k);             // card keys can contain '#' (split basic lands)
