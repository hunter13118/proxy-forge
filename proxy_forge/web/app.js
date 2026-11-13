"use strict";
const $ = (id) => document.getElementById(id);
const S = { profiles: [], templates: [], profile: null, deck: null, template: "classic", job: null, status: {} };

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
}
let getToken = async () => null;          // replaced by Clerk's when the page is reached through the tunnel and has to sign in
let authed = false;                        // true once pictures and downloads must be fetched with the token
const blobs = new Map();
async function authFetch(path, init = {}) {
  const t = await getToken();
  return fetch(path, t ? { ...init, headers: { ...(init.headers || {}), Authorization: "Bearer " + t } } : init);
}
async function blobUrl(url) {
  if (!blobs.has(url)) blobs.set(url, authFetch(url).then(async (r) => { if (!r.ok) throw new Error(r.statusText); return URL.createObjectURL(await r.blob()); }));
  return blobs.get(url);
}
function setSrc(img, url) {
  if (!authed) img.src = url; else blobUrl(url).then((u) => (img.src = u)).catch(() => {});
  return img;
}
const pic = (url, attrs) => setSrc(h("img", attrs), url);
async function saveAs(url, name) {
  const r = await authFetch(url);
  if (!r.ok) return fail(new Error((await r.text()).slice(0, 200) || r.statusText));
  const a = h("a", { href: URL.createObjectURL(await r.blob()), download: name });
  document.body.append(a); a.click(); a.remove();
}
async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers["Content-Type"] = "application/json"; }
  if (opts.form) init.body = opts.form;
  const r = await authFetch(path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}
const remember = (k, v) => { try { localStorage.setItem("pf-" + k, v); } catch (_) {} };
const recall = (k) => { try { return localStorage.getItem("pf-" + k) || ""; } catch (_) { return ""; } };
const debounce = (fn, ms = 600) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const fail = (e) => alert(e.message || e);

// ------------------------------------------------------------------------------------------------------------------------------------------------------- status
async function loadStatus() {
  try {
    const s = await api("/api/status");
    S.status = s;
    const dot = (ok, label, why) => h("span", { title: why || "" }, h("i", { class: ok ? "ok" : "" }), label);
    $("status").replaceChildren(
      dot(s.studio, "studio", s.studio_problem), dot(s.comfy, s.picture_model || "pictures"), dot(s.trainer, "LoRA training", s.trainer_problem),
      h("span", {}, `${s.scryfall_cards.toLocaleString()} Scryfall names`));
    const sel = $("lora");
    const keep = S.profile ? S.profile.lora : "";
    sel.replaceChildren(h("option", { value: "" }, "none"), ...s.loras.map((l) => h("option", { value: l }, l)));
    sel.value = keep || "";
  } catch (e) { $("status").textContent = "server not answering"; }
}

// ----------------------------------------------------------------------------------------------------------------------------------------------------- templates
async function loadTemplates() {
  S.templates = await api("/api/templates");
  S.template = recall("template") || S.templates[0].id;
  renderTemplates();
}
function renderTemplates() {
  $("templates").replaceChildren(...S.templates.map((t) =>
    h("div", { class: "tile" + (t.id === S.template ? " on" : ""), title: t.blurb, onclick: () => pickTemplate(t.id) },
      pic(`/api/templates/${t.id}/preview.jpg`, { alt: t.name }), t.name)));
}
async function pickTemplate(id) {
  S.template = id; remember("template", id); renderTemplates();
  if (S.deck) {
    try { const r = await api(`/api/decks/${S.deck.id}`, { method: "PATCH", json: { template: id } }); S.deck.template = id; follow(r.job); } catch (e) { fail(e); }
  }
}

// ------------------------------------------------------------------------------------------------------------------------------------------------------ profiles
async function loadProfiles() {
  S.profiles = await api("/api/profiles");
  if (!S.profiles.length) S.profiles = [await api("/api/profiles", { method: "POST", json: { name: "My style" } })];
  const want = (S.deck && S.deck.profile) || recall("profile");
  S.profile = S.profiles.find((p) => p.id === want) || S.profiles[0];
  $("profile").replaceChildren(...S.profiles.map((p) => h("option", { value: p.id }, p.name)));
  $("profile").value = S.profile.id;
  renderProfile();
}
function renderProfile() {
  const p = S.profile;
  $("direction").value = p.direction || "";
  $("lora").value = p.lora || "";
  $("lora-strength").value = p.lora_strength ?? 0.8;
  $("cartoon-on").checked = p.cartoon_pass !== false;
  $("cartoon-strength").value = p.cartoon_strength ?? 0.4;
  $("cartoon-tags").value = p.cartoon_tags || "";
  showCartoon();
  $("subjects").replaceChildren(...p.subjects.map(subjectEl));
}
const saveProfile = debounce(async () => {
  try {
    S.profile = await api(`/api/profiles/${S.profile.id}`, { method: "PATCH", json: {
      direction: $("direction").value, lora: $("lora").value, lora_strength: parseFloat($("lora-strength").value) || 0.8,
      cartoon_pass: $("cartoon-on").checked, cartoon_strength: parseFloat($("cartoon-strength").value) || 0.4, cartoon_tags: $("cartoon-tags").value } });
  } catch (e) { fail(e); }
});
function showCartoon() {
  $("cartoon-val").textContent = $("cartoon-strength").value;
  $("cartoon-opts").style.display = $("cartoon-on").checked ? "" : "none";
}
async function refreshProfile() { S.profile = await api(`/api/profiles/${S.profile.id}`); renderProfile(); }

function subjectEl(s) {
  const pid = S.profile.id;
  const patch = (fields) => api(`/api/profiles/${pid}/subjects/${s.id}`, { method: "PATCH", json: fields }).catch(fail);
  const file = h("input", { type: "file", accept: "image/*", multiple: true, hidden: true, onchange: async () => {
    const form = new FormData();
    for (const f of file.files) form.append("files", f);
    try { await api(`/api/profiles/${pid}/subjects/${s.id}/photos`, { method: "POST", form }); await refreshProfile(); } catch (e) { fail(e); }
  } });
  const tags = h("input", { value: (s.tags || []).join(", "), placeholder: "appearance tags", onchange: (e) => patch({ tags: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) }) });
  const sentence = h("textarea", { rows: 2, placeholder: "one sentence: how they look", onchange: (e) => patch({ sentence: e.target.value }) }, s.sentence || "");
  const describe = h("button", { class: "ghost", disabled: !s.photos.length, onclick: async (e) => {
    e.target.disabled = true;
    try { follow(await api(`/api/profiles/${pid}/subjects/${s.id}/describe`, { method: "POST" }), refreshProfile); } catch (err) { fail(err); e.target.disabled = false; }
  } }, "Describe from photos");
  return h("div", { class: "subject" },
    h("div", { class: "row", style: "margin-top:0" },
      h("input", { value: s.name, onchange: (e) => patch({ name: e.target.value }) }),
      h("button", { class: "ghost danger", title: "Remove", onclick: async () => { if (confirm(`Remove ${s.name} and their photos?`)) { await api(`/api/profiles/${pid}/subjects/${s.id}`, { method: "DELETE" }); refreshProfile(); } } }, "×")),
    h("div", { class: "photos" }, s.photos.map((n) => h("div", {}, pic(`/api/profiles/${pid}/subjects/${s.id}/photos/${n}`, { alt: "" }),
      h("button", { title: "Remove photo", onclick: async () => { await api(`/api/profiles/${pid}/subjects/${s.id}/photos/${n}`, { method: "DELETE" }); refreshProfile(); } }, "×"))),
      h("button", { class: "ghost", onclick: () => file.click() }, "+ photos"), file),
    photoMeter(s.photos.length),
    describe,
    h("div", { class: "desc" }, s.described ? "Described. Edit if it is off:" : "Tags and sentence go into every prompt this person is in."),
    tags, sentence, loraEl(s, pid));
}

function photoMeter(n) {
  const level = n < 6 ? ["low", `${n} of 6 photos: add ${6 - n} more to unlock LoRA training`] : n < 15 ? ["ok", `${n} photos: enough to train. 15 or more gives a better likeness`]
    : n <= 40 ? ["good", `${n} photos: a good set for a LoRA`] : ["good", `${n} photos: plenty, more won't help much`];
  return h("div", { class: "meter " + level[0] },
    h("div", { class: "meter-bar" }, h("i", { style: `width:${Math.min(100, Math.round((100 * n) / 20))}%` }), h("b", { style: "left:30%" }), h("b", { style: "left:75%" })),
    h("div", { class: "meter-msg" }, level[1]),
    h("details", { class: "tips" }, h("summary", {}, "Tips for good training photos"),
      h("ul", {},
        h("li", {}, "Only that one person in each photo."),
        h("li", {}, "Vary angles, lighting, expressions, clothes and backgrounds. Near-duplicates teach it nothing new."),
        h("li", {}, "Mostly clear face shots, plus a few upper-body and full-body ones."),
        h("li", {}, "No sunglasses, heavy filters or masks on most of them."),
        h("li", {}, "Sharp and well lit beats high resolution."))));
}

const minutesFor = (steps) => Math.round((steps * 1.5) / 60 + 6);       // about 1.5 s a step on the 5090, plus captioning, preparing and loading

function stepsSlider() {
  const saved = parseInt(recall("lora-steps")) || 1000;
  const value = h("b", {});
  const eta = h("span", {});
  const input = h("input", { type: "range", min: 300, max: 2000, step: 100, value: saved });
  const update = () => { value.textContent = input.value + " steps"; eta.textContent = ` · about ${minutesFor(+input.value)} min`; remember("lora-steps", input.value); };
  input.oninput = update; update();
  const box = h("div", { class: "steps" },
    h("label", {}, "Training length: ", value, eta),
    input,
    h("div", { class: "desc" }, "More steps usually means a closer likeness, up to a point, but it takes proportionally longer: the GPU is busy for the whole run and other jobs wait. Fewer steps is quicker but can look generic; far too many can memorise your photos. 1000 is a good start, and you can compare the saved checkpoints afterwards."));
  return { box, value: () => parseInt(input.value) };
}

function loraEl(s, pid) {
  const base = `/api/profiles/${pid}/subjects/${s.id}`;
  const lo = s.lora;
  const slider = stepsSlider();
  const train = (label) => h("button", { class: lo ? "ghost" : "", disabled: s.photos.length < 6 || S.status.trainer === false,
    title: S.status.trainer === false ? S.status.trainer_problem : s.photos.length < 6 ? "add at least 6 photos (15 to 30 different ones is best)" : "",
    onclick: async (e) => {
      const steps = slider.value();
      if (!confirm(`Train a LoRA from ${s.photos.length} photos for ${steps} steps? It takes about ${minutesFor(steps)} minutes and uses the GPU, so other jobs wait.`)) return;
      e.target.disabled = true;
      try { follow(await api(`${base}/train`, { method: "POST", json: { steps } }), refreshProfile); } catch (err) { fail(err); e.target.disabled = false; }
    } }, label);
  if (!lo) {
    return h("div", { class: "lora" }, h("div", { class: "desc" }, "A LoRA teaches the picture model this person's actual face: far better likeness than the written description alone."), slider.box, train("Train LoRA from photos"));
  }
  const pick = (file) => api(`${base}/lora`, { method: "PATCH", json: { file } }).then(refreshProfile).catch(fail);
  const ckpts = h("select", { onchange: (e) => pick(e.target.value) }, lo.checkpoints.map((f, i) => h("option", { value: f, selected: f === lo.file }, f.endsWith("-final.safetensors") ? "final" : "checkpoint " + (i + 1))));
  const strength = h("input", { type: "number", min: 0, max: 1.5, step: 0.1, value: lo.strength, onchange: (e) => api(`${base}/lora`, { method: "PATCH", json: { strength: parseFloat(e.target.value) } }).catch(fail) });
  const tests = h("div", { class: "tests" }, lo.checkpoints.map((f, i) => {
    const stem = f.replace(/\.safetensors$/, "");
    const im = pic(`${base}/lora/previews/${stem}.jpg?v=${Math.floor(lo.trained_at)}`, { alt: "" });
    im.onerror = () => { im.style.display = "none"; };
    return h("figure", { class: f === lo.file ? "on" : "", onclick: () => pick(f) }, im, h("figcaption", {}, f.endsWith("-final.safetensors") ? "final" : "#" + (i + 1)));
  }));
  return h("div", { class: "lora" },
    h("div", { class: "desc" }, `LoRA trained on ${lo.images} photos (${lo.epochs} epochs). Used automatically for cards this person is in.`),
    h("div", { class: "row" }, h("div", { class: "grow" }, h("label", {}, "Checkpoint"), ckpts), h("div", { class: "narrow" }, h("label", {}, "Strength"), strength)),
    h("label", {}, "Reference photos, for comparing the tests below"),
    h("div", { class: "refs" }, s.photos.slice(0, 4).map((n) => pic(`/api/profiles/${pid}/subjects/${s.id}/photos/${n}`, { alt: "" }))),
    tests,
    slider.box,
    h("div", { class: "row wrap" },
      h("button", { class: "ghost", onclick: async (e) => { e.target.disabled = true; try { follow(await api(`${base}/lora/preview`, { method: "POST" }), refreshProfile); } catch (err) { fail(err); e.target.disabled = false; } } }, "Compare checkpoints"),
      train("Retrain"),
      h("button", { class: "ghost danger", onclick: async () => { if (confirm("Remove this person's LoRA?")) { await api(`${base}/lora`, { method: "DELETE" }); refreshProfile(); } } }, "Remove")));
}

// ---------------------------------------------------------------------------------------------------------------------------------------------------------- decks
async function loadDecks(select) {
  const decks = await api("/api/decks");
  const sel = $("deck-pick");
  sel.replaceChildren(h("option", { value: "" }, "— new deck —"), ...decks.map((d) => h("option", { value: d.id }, `${d.name} (${d.drawn}/${d.cards})`)));
  sel.value = select || (S.deck ? S.deck.id : "");
}
async function openDeck(id) {
  if (!id) { S.deck = null; renderDeck(); return; }
  S.deck = await api(`/api/decks/${id}`);
  remember("deck", id);
  if (S.deck.template) { S.template = S.deck.template; renderTemplates(); }
  if (S.deck.profile && S.deck.profile !== S.profile.id) { $("profile").value = S.deck.profile; S.profile = S.profiles.find((p) => p.id === S.deck.profile) || S.profile; renderProfile(); }
  $("deck-name").value = S.deck.name;
  renderDeck();
}
function renderDeck() {
  const d = S.deck;
  $("empty").hidden = !!(d && d.order.length);
  $("grid").replaceChildren();
  for (const id of ["gen", "regen"]) $(id).disabled = !(d && d.order.length);
  const links = { "pdf-letter": "export.pdf?paper=letter", "pdf-a4": "export.pdf?paper=a4", zip: "export.zip" };
  for (const [id, q] of Object.entries(links)) {
    const a = $(id);
    a.dataset.url = d ? `/api/decks/${d.id}/${q}${id.startsWith("pdf-") && $("skip-basics").checked ? "&skip_basics=true" : ""}` : "";
    a.dataset.name = d ? `${d.name}-${id.replace("pdf-", "")}.${id === "zip" ? "zip" : "pdf"}` : "";
    a.style.opacity = d ? 1 : 0.45; a.style.pointerEvents = d ? "auto" : "none";
  }
  if (!d) { $("deck-notes").textContent = ""; return; }
  const shape = (S.templates.find((t) => t.id === d.template) || {}).shape;
  const stale = d.order.filter((k) => d.units[k].art && d.units[k].art_shape !== shape).length;
  const drawn = d.order.filter((k) => d.units[k].art).length;
  $("deck-notes").replaceChildren(
    `${d.order.length} cards, ${drawn} drawn. `,
    d.missing.length ? h("b", {}, `Not found: ${d.missing.join(", ")}. `) : "",
    stale ? `${stale} were drawn for a different template shape; Generate redraws them to fit.` : "");
  $("grid").replaceChildren(...d.order.map((k) => cardEl(d, k)));
}
function cardEl(d, k) {
  const u = d.units[k];
  return h("div", { class: "card", onclick: () => openCard(k) },
    pic(`/api/decks/${d.id}/cards/${k}.jpg?v=${encodeURIComponent(u.art + d.template + u.status)}`, { alt: u.name }),
    h("span", { class: "qty" }, `×${u.copies}`),
    h("div", { class: "meta" }, h("span", {}, u.name), h("span", { class: "st " + u.status }, u.status === "new" ? "" : u.status)));
}
async function importDeck() {
  const text = $("deck-text").value.trim();
  if (!text) return alert("Paste a deck list first.");
  $("deck-import").disabled = true;
  try {
    const r = await api("/api/decks", { method: "POST", json: { name: $("deck-name").value || "My deck", text, profile: S.profile.id, template: S.template, include_sideboard: $("deck-sb").checked } });
    S.deck = { id: r.deck, order: [], units: {}, missing: [], template: S.template };
    follow(r.job, async () => { await loadDecks(r.deck); await openDeck(r.deck); $("deck-import").disabled = false; });
  } catch (e) { fail(e); $("deck-import").disabled = false; }
}

// ------------------------------------------------------------------------------------------------------------------------------------------------------------ jobs
function follow(job, after) {
  S.job = job;
  $("progress").hidden = false;
  let ticks = 0;
  const step = async () => {
    try {
      const j = await api(`/api/jobs/${job.id}`);
      $("bar").style.width = (j.total ? Math.round((100 * j.done) / j.total) : 5) + "%";
      $("progress-msg").textContent = j.message;
      if (S.deck && j.deck === S.deck.id && ++ticks % 3 === 0 && (j.kind === "generate" || j.kind === "render")) { S.deck = await api(`/api/decks/${S.deck.id}`); renderDeck(); }
      if (j.state === "queued" || j.state === "running") return setTimeout(step, 1000);
      $("progress-msg").textContent = j.state === "error" ? "Failed: " + j.error : j.message;
      if (j.state === "error") alert(j.error);
      if (S.deck && j.deck === S.deck.id) { S.deck = await api(`/api/decks/${S.deck.id}`); renderDeck(); loadDecks(); }
      if (after) await after(j);
      setTimeout(() => { if (S.job && S.job.id === job.id) $("progress").hidden = true; }, 4000);
    } catch (e) { $("progress-msg").textContent = e.message; }
  };
  step();
}
const generate = (body) => S.deck && api(`/api/decks/${S.deck.id}/generate`, { method: "POST", json: body }).then((j) => follow(j)).catch(fail);

// ------------------------------------------------------------------------------------------------------------------------------------------------------- card modal
let current = null;
function openCard(k) {
  const u = S.deck.units[k];
  current = k;
  setSrc($("m-img"), `/api/decks/${S.deck.id}/cards/${k}.png?v=${encodeURIComponent(u.art + S.deck.template + u.status)}`);
  $("m-name").textContent = u.name + (u.faces > 1 ? ` (side ${u.face + 1})` : "");
  $("m-prompt").value = u.prompt || "";
  $("m-seed").value = u.seed;
  $("m-error").textContent = u.error || "";
  $("m-subjects").replaceChildren(S.profile.subjects.length ? h("label", {}, "Who is in this picture") : "",
    ...S.profile.subjects.map((s) => h("label", { class: "check" }, h("input", { type: "checkbox", value: s.id, checked: (u.subjects || []).includes(s.id) }), s.name + (s.tags.length ? "" : " (not described yet)"))));
  $("modal").showModal();
}
const picked = () => [...$("m-subjects").querySelectorAll("input:checked")].map((i) => i.value);
async function saveCard(fields, gen) {
  const url = `/api/decks/${S.deck.id}/units/${current}`;
  try {
    await api(url, { method: "PATCH", json: fields });
    $("modal").close();
    S.deck = await api(`/api/decks/${S.deck.id}`);
    await generate({ keys: [current], force: true, rewrite_prompts: !!gen.rewrite });
  } catch (e) { fail(e); }
}

// --------------------------------------------------------------------------------------------------------------------------------------------------------------- wiring
$("profile").onchange = async () => {
  S.profile = S.profiles.find((p) => p.id === $("profile").value); remember("profile", S.profile.id); renderProfile();
  if (S.deck) await api(`/api/decks/${S.deck.id}`, { method: "PATCH", json: { profile: S.profile.id } }).catch(fail);
};
$("profile-new").onclick = async () => {
  const name = prompt("Name for the new style"); if (!name) return;
  const p = await api("/api/profiles", { method: "POST", json: { name } });
  S.profiles.push(p); S.profile = p; $("profile").append(h("option", { value: p.id }, p.name)); $("profile").value = p.id; renderProfile();
};
$("direction").oninput = saveProfile;
$("lora").onchange = saveProfile;
$("lora-strength").onchange = saveProfile;
$("cartoon-on").onchange = () => { showCartoon(); saveProfile(); };
$("cartoon-strength").oninput = () => { showCartoon(); saveProfile(); };
$("cartoon-tags").oninput = saveProfile;
$("subject-new").onclick = async () => { const name = prompt("Their name (only used as a label)"); if (name) { await api(`/api/profiles/${S.profile.id}/subjects`, { method: "POST", json: { name } }); refreshProfile(); } };
$("skip-basics").onchange = () => renderDeck();
for (const id of ["pdf-letter", "pdf-a4", "zip"]) $(id).onclick = (e) => { e.preventDefault(); const a = $(id); if (a.dataset.url) saveAs(a.dataset.url, a.dataset.name); };
$("deck-pick").onchange = () => openDeck($("deck-pick").value);
$("deck-delete").onclick = async () => {
  if (S.deck && confirm(`Delete the deck "${S.deck.name}" and its cards?`)) { await api(`/api/decks/${S.deck.id}`, { method: "DELETE" }); S.deck = null; await loadDecks(); renderDeck(); }
};
$("deck-import").onclick = importDeck;
$("gen").onclick = () => generate({});
$("regen").onclick = () => { if (confirm("Write every prompt again and redraw every card?")) generate({ rewrite_prompts: true, force: true }); };
$("cancel").onclick = () => S.job && api(`/api/jobs/${S.job.id}/cancel`, { method: "POST" });
$("m-close").onclick = () => $("modal").close();
$("m-save").onclick = () => saveCard({ prompt: $("m-prompt").value, seed: parseInt($("m-seed").value) || 0, subjects: picked() }, {});
$("m-reroll").onclick = () => saveCard({ prompt: $("m-prompt").value, seed: Math.floor(Math.random() * 2 ** 32), subjects: picked() }, {});
$("m-rewrite").onclick = () => saveCard({ seed: parseInt($("m-seed").value) || 0, subjects: picked() }, { rewrite: true });

async function signIn() {
  const config = await (await fetch("/app-config.json")).json();
  const gate = $("gate");
  if (!config.clerk) { gate.hidden = false; gate.querySelector("p").textContent = "This page is not set up for sign-in yet."; return new Promise(() => {}); }
  await new Promise((resolve, reject) => {
    const sc = document.createElement("script");
    sc.async = true; sc.crossOrigin = "anonymous";
    sc.setAttribute("data-clerk-publishable-key", config.clerk.publishableKey);
    sc.src = `${config.clerk.frontendApi.replace(/\/$/, "")}/npm/@clerk/clerk-js@5/dist/clerk.browser.js`;
    sc.onload = async () => { try { await window.Clerk.load(); resolve(); } catch (e) { reject(e); } };
    sc.onerror = () => reject(new Error("Could not load the sign-in. Check your connection and reload."));
    document.head.append(sc);
  }).catch((e) => { gate.hidden = false; gate.querySelector("p").textContent = e.message; return new Promise(() => {}); });
  const Clerk = window.Clerk;
  getToken = async () => (Clerk.session ? Clerk.session.getToken() : null);
  if (!Clerk.session) {
    gate.hidden = false;
    await new Promise((resolve) => { Clerk.mountSignIn($("gate-box"), { routing: "hash" }); const off = Clerk.addListener(({ session }) => { if (session) { off(); resolve(); } }); });
    gate.hidden = true;
  }
  authed = true;
  $("who").hidden = false;
  Clerk.mountUserButton($("who"));
}

(async function start() {
  try {
    const probe = await fetch("/api/status");                           // on the home PC this just works; through the tunnel it says who may come in
    if (probe.status === 401 || probe.status === 403) {
      await signIn();
      const again = await authFetch("/api/status");
      if (again.status === 403) { const b = await again.json().catch(() => ({})); $("gate").hidden = false; $("gate-box").replaceChildren(); $("gate").querySelector("p").textContent = b.error === "not_allowed" ? "You are signed in, but you are not on this page's list of people." : "Not allowed: " + (b.error || again.statusText); return; }
    }
    await loadStatus();
    await loadTemplates();
    await loadProfiles();
    const last = recall("deck");
    await loadDecks(last);
    if ($("deck-pick").value) await openDeck($("deck-pick").value); else renderDeck();
    setInterval(loadStatus, 30000);
  } catch (e) { $("status").textContent = "could not start: " + e.message; }
})();
