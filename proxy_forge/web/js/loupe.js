// The Loupe: one card, large, with a magnifier, where its picture came from, a filmstrip of every art variant, and the AI-art editor.
import { $, S, h, api, pic, setSrc, fail, follow, emit, on, policyOf, money, ck, toast } from "./core.js";

let key = null, variants = [], sel = null, tab = "official", seq = 0;
const unit = () => S.deck && S.deck.units[key];

export function openLoupe(k) {
  key = k; sel = null;
  const u = unit();
  tab = (u.art_source || "forge") === "forge" && policyOf(S.deck).source === "forge" ? "ai" : "official";
  draw(); showTab(tab);
  if (!$("loupe").open) $("loupe").showModal();
  loadVariants();
}

function pretty(t) { return t.split("-").map((x) => x[0].toUpperCase() + x.slice(1)).join(" · ").replace("Regular · ", "Regular "); }

function draw() {
  const d = S.deck, u = unit();
  if (!u) return;
  const p = u.printing;
  const v = encodeURIComponent([u.art, d.template, u.status, p && p.id, policyOf(d).print, u.locked].join("|"));
  setSrc($("l-img"), `/api/decks/${d.id}/cards/${ck(key)}.png?v=${v}`);
  $("l-name").textContent = u.name + (u.faces > 1 ? ` (side ${u.face + 1})` : "");
  const pills = [];
  if ((u.art_source || "forge") === "forge") pills.push(h("span", { class: "pill" }, "✦ AI art"), u.note ? h("span", { class: "pill warn" }, u.note) : null);
  else {
    pills.push(h("span", { class: "pill good" }, `${p.set.toUpperCase()} · #${p.cn}`), h("span", { class: "pill" }, p.label || p.treatment));
    if (p.artist) pills.push(h("span", { class: "pill" }, "Illus. " + p.artist));
    if (p.fallback) pills.push(h("span", { class: "pill warn" }, p.why));
    if (p.pin_missing) pills.push(h("span", { class: "pill warn" }, "the (SET) number in the list was not found"));
    if (u.price) pills.push(h("span", { class: "pill gilt" }, `${money(u.price.amount, u.price.currency)} · ${u.price.finish} · ${u.price.provider} via ${u.price.via}${u.price.as_of ? " · " + u.price.as_of : ""}`));
  }
  if (u.locked) pills.push(h("span", { class: "pill" }, "◆ pinned by hand"));
  $("l-prov").replaceChildren(...pills);
  $("l-ai").querySelector("#m-prompt").value = u.prompt || "";
  $("m-seed").value = u.seed; $("m-error").textContent = u.error || "";
  $("m-subjects").replaceChildren(S.profile && S.profile.subjects.length ? h("label", {}, "Who is in this picture") : "",
    ...(S.profile ? S.profile.subjects : []).map((s) => h("label", { class: "check" }, h("input", { type: "checkbox", value: s.id, checked: (u.subjects || []).includes(s.id) }), s.name + (s.tags.length ? "" : " (not described yet)"))));
}

function showTab(t) {
  tab = t;
  for (const b of document.querySelectorAll(".tab")) b.classList.toggle("on", b.dataset.tab === t);
  $("l-official").hidden = t !== "official"; $("l-ai").hidden = t !== "ai";
}

async function loadVariants() {
  const my = ++seq;
  $("l-strip").replaceChildren(h("span", { class: "mute" }, "Looking through every printing…"));
  $("l-hang").disabled = true; $("l-pick").textContent = "";
  try {
    const r = await api(`/api/decks/${S.deck.id}/units/${ck(key)}/printings`);
    if (my !== seq) return;
    variants = r.variants.map((v) => ({ ...v, currency: r.currency }));
    renderStrip();
  } catch (e) {
    $("l-strip").replaceChildren(h("span", { class: "mute" }, e.status === 409 ? "Build the card index in the Source step (Archive door) to browse printings." : e.message));
  }
}

function renderStrip() {
  const f = $("l-filter").value.trim().toLowerCase();
  const face = unit().face || 0;
  const shown = variants.filter((v) => !f || v.treatment.includes(f) || v.printings.some((p) => p.set.includes(f)));
  if (!shown.length) return $("l-strip").replaceChildren(h("span", { class: "mute" }, "No printing matches."));
  $("l-strip").replaceChildren(...shown.map((v) => {
    const chosen = sel && v.printings.some((p) => p.id === sel);
    const best = v.printings.find((p) => p.id === v.best) || v.printings[0];
    const el = h("div", { class: "var" + (v.current ? " cur" : "") + (chosen ? " sel" : ""), tabindex: 0, role: "button", onclick: () => pick(best.id), onkeydown: (e) => { if (e.key === "Enter") pick(best.id); } },
      pic(`/api/scans/${best.id}/${face}.jpg`, { alt: "", loading: "lazy" }),
      h("div", { class: "t" }, h("b", {}, pretty(v.treatment)), h("span", { class: "mute" }, `${v.printings.length} printing${v.printings.length > 1 ? "s" : ""}`), v.amount != null ? h("div", { class: "px" }, `${money(v.amount, v.currency)} ${v.finish || ""}`) : h("div", { class: "mute" }, "no price")),
      v.printings.length > 1 || true ? h("div", { class: "sets" }, v.printings.slice(0, 8).map((p) => h("button", { class: p.id === sel ? "sel" : "", title: `${p.set.toUpperCase()} #${p.cn}, ${p.released}`, onclick: (e) => { e.stopPropagation(); pick(p.id); } }, `${p.set.toUpperCase()} ${p.cn}`)),
        v.printings.length > 8 ? h("span", { class: "mute" }, `+${v.printings.length - 8}`) : null) : null);
    return el;
  }));
}

function pick(id) {
  sel = id;
  const v = variants.find((x) => x.printings.some((p) => p.id === id)), p = v && v.printings.find((q) => q.id === id);
  $("l-hang").disabled = !!(p && p.current);
  $("l-pick").textContent = p ? (p.current ? "this card already hangs on it" : `${p.set.toUpperCase()} #${p.cn} · ${pretty(v.treatment)}`) : "";
  renderStrip();
}

async function hang() {
  if (!sel) return;
  try {
    const r = await api(`/api/decks/${S.deck.id}/units/${ck(key)}/printing`, { method: "PUT", json: { printing_id: sel } });
    toast("Hanging it…");
    follow(r.job, async () => { draw(); loadVariants(); });
  } catch (e) { fail(e); }
}

const picked = () => [...$("m-subjects").querySelectorAll("input:checked")].map((i) => i.value);
async function saveAI(fields, rewrite) {
  const d = S.deck, k = key;
  try {
    if ((unit().art_source || "forge") !== "forge") {                     // the card changes sides: from official art to AI art
      const j = await api(`/api/decks/${d.id}/units/${ck(k)}/printing`, { method: "PUT", json: { printing_id: null } });
      await new Promise((res) => follow(j.job, res));
    }
    await api(`/api/decks/${d.id}/units/${ck(k)}`, { method: "PATCH", json: fields });
    $("loupe").close();
    S.deck = await api(`/api/decks/${d.id}`); emit("deck", S.deck);
    follow(await api(`/api/decks/${d.id}/generate`, { method: "POST", json: { keys: [k], force: true, rewrite_prompts: !!rewrite } }));
  } catch (e) { fail(e); }
}

export function wireLoupe() {
  const host = $("l-host"), lens = $("lens"), img = $("l-img");
  host.addEventListener("pointermove", (e) => {
    const r = host.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, z = 2.4;
    lens.hidden = false;
    lens.style.left = x + "px"; lens.style.top = y + "px";
    lens.style.backgroundImage = `url("${img.src}")`;
    lens.style.backgroundSize = `${r.width * z}px ${r.height * z}px`;
    lens.style.backgroundPosition = `${-(x * z - 95)}px ${-(y * z - 95)}px`;
  });
  host.addEventListener("pointerleave", () => { lens.hidden = true; });
  $("l-close").onclick = () => $("loupe").close();
  $("loupe").addEventListener("click", (e) => { if (e.target === $("loupe")) $("loupe").close(); });
  for (const b of document.querySelectorAll(".tab")) b.onclick = () => showTab(b.dataset.tab);
  $("l-filter").oninput = renderStrip;
  $("l-hang").onclick = hang;
  $("m-save").onclick = () => saveAI({ prompt: $("m-prompt").value, seed: parseInt($("m-seed").value) || 0, subjects: picked() });
  $("m-reroll").onclick = () => saveAI({ prompt: $("m-prompt").value, seed: Math.floor(Math.random() * 2 ** 32), subjects: picked() });
  $("m-rewrite").onclick = () => saveAI({ seed: parseInt($("m-seed").value) || 0, subjects: picked() }, true);
  document.addEventListener("keydown", (e) => {
    if (!$("loupe").open || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    if (tab === "official" && (e.key === "[" || e.key === "]")) {
      const flat = variants.map((v) => v.printings.find((p) => p.id === v.best) || v.printings[0]);
      const i = flat.findIndex((p) => p.id === sel || (sel && variants.find((v) => v.printings.some((q) => q.id === sel)).best === p.id));
      const n = Math.max(0, Math.min(flat.length - 1, (i < 0 ? (e.key === "]" ? -1 : flat.length) : i) + (e.key === "]" ? 1 : -1)));
      if (flat[n]) pick(flat[n].id);
    }
    if (e.key.toLowerCase() === "p" && tab === "official" && !$("l-hang").disabled) hang();
  });
  on("deck", () => { if ($("loupe").open && unit()) draw(); });
}
