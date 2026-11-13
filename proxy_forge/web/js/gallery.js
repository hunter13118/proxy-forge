// III. The Gallery: the deck hung on the wall. Every card has a museum label that says where its picture came from; fallbacks are amber, never silent.
import { $, S, h, api, pic, on, emit, policyOf, money, ck } from "./core.js";
import { openLoupe } from "./loupe.js";

let filter = "all";
const FILTERS = [["all", "All"], ["matched", "Matched"], ["fallback", "Fallback"], ["ai", "AI art"], ["pinned", "Pinned"]];

export const kindOf = (u) => (u.art_source || "forge") === "forge" ? "ai" : (u.printing && u.printing.fallback ? "fallback" : "matched");
const keep = (u, f) => f === "all" || (f === "pinned" ? !!u.locked : f === "matched" ? kindOf(u) === "matched" : kindOf(u) === f);

function label(u) {
  const p = u.printing;
  if (!p) return u.note ? [h("span", {}, "✦ AI art"), ` · ${u.note}`] : [h("span", {}, "✦ AI art")];
  return [pic(`/api/sets/${p.set}/icon.svg`, { alt: "", loading: "lazy" }), `${p.set.toUpperCase()} · #${p.cn} · ${p.label || p.treatment}`];
}

function cardEl(d, k, i) {
  const u = d.units[k], p = u.printing, kind = kindOf(u);
  const v = encodeURIComponent([u.art, d.template, u.status, p && p.id, policyOf(d).print, u.locked].join("|"));
  const img = pic(`/api/decks/${d.id}/cards/${ck(k)}.jpg?v=${v}`, { alt: u.name, loading: "lazy" });
  const price = u.price ? `${money(u.price.amount, u.price.currency)} · ${u.price.finish}` : "";
  return h("button", { class: "card" + (u.price ? " priced" : ""), style: `animation-delay:${Math.min(i, 24) * 25}ms`, "data-key": k, onclick: () => openLoupe(k), "aria-label": u.name },
    h("div", { class: "face" }, img, h("span", { class: "qty" }, `×${u.copies}`),
      kind === "fallback" ? h("span", { class: "ribbon-tag", title: p.why }, "Fallback") : null,
      kind === "ai" ? h("span", { class: "glyph-tag" }, u.locked ? "✦ AI · pinned" : "✦ AI") : (u.locked ? h("span", { class: "glyph-tag" }, "◆ pinned") : null)),
    h("div", { class: "cap" },
      h("div", { class: "nm" }, u.name + (u.faces > 1 ? ` (side ${u.face + 1})` : "")),
      h("div", { class: "src" + (kind === "fallback" ? " fb" : ""), title: p ? p.why : "" }, label(u)),
      kind === "fallback" ? h("div", { class: "src fb" }, p.why) : null,
      price ? h("div", { class: "px" }, price) : null));
}

export function renderGallery() {
  const d = S.deck;
  $("empty").hidden = !!(d && d.order.length);
  $("g-title").textContent = d ? d.name : "The Gallery";
  if (!d || !d.order.length) { $("grid").replaceChildren(); $("g-filter").replaceChildren(); $("g-sub").textContent = ""; $("appraisal").hidden = true; return; }
  const pol = policyOf(d);
  const counts = Object.fromEntries(FILTERS.map(([f]) => [f, d.order.filter((k) => keep(d.units[k], f)).length]));
  $("g-filter").replaceChildren(...FILTERS.map(([f, l]) => h("button", { class: "chip" + (filter === f ? " on" : ""), role: "tab", onclick: () => { filter = f; renderGallery(); } }, l, h("b", {}, counts[f]))));
  const n = d.order.reduce((s, k) => s + d.units[k].copies, 0);
  const how = { forge: "AI art", archive: "official art from " + (pol.sets.map((c) => c.toUpperCase()).join(" → ") || "…"), vault: "the priciest art variants", budget: "the cheapest art variants" }[pol.source];
  $("g-sub").textContent = `${n} cards (${d.order.length} different) · ${how}`;
  $("grid").replaceChildren(...d.order.filter((k) => keep(d.units[k], filter)).map((k, i) => cardEl(d, k, i)));
  appraisal(d, pol);
}

let lastAppraisal = "";
async function appraisal(d, pol) {
  const box = $("appraisal");
  if (!["vault", "budget"].includes(pol.source)) { box.hidden = true; return; }
  const sig = d.id + d.order.map((k) => d.units[k].printing && d.units[k].printing.id).join();
  if (sig === lastAppraisal) return;
  lastAppraisal = sig;
  try {
    const a = await api(`/api/decks/${d.id}/appraisal`);
    box.hidden = false;
    const total = h("div", { class: "total" }, money(0, a.currency));
    const max = Math.max(1, ...a.top.map((t) => t.amount * t.copies));
    box.replaceChildren(
      h("div", {}, h("div", { class: "mute" }, pol.source === "budget" ? "This deck, bought at the cheapest" : "This deck at its most expensive"), total,
        h("small", {}, `${a.priced} of ${a.cards} cards priced · Scryfall prices of ${a.as_of || "today"} (TCGplayer / Cardmarket); never live`)),
      h("div", { class: "topbars", "aria-label": "The ten priciest cards" }, a.top.map((t) => h("div", { title: `${t.name}: ${money(t.amount, a.currency)} × ${t.copies}` }, h("i", { style: `height:${Math.max(3, Math.round(100 * t.amount * t.copies / max))}%` }), h("span", {}, t.name)))));
    const t0 = performance.now();                                         // the total counts up
    const tick = (t) => { const f = Math.min(1, (t - t0) / 900); total.textContent = money(a.total * (1 - Math.pow(1 - f, 3)), a.currency); if (f < 1) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  } catch (_) { box.hidden = true; }
}

export function wireGallery() {
  on("deck", () => renderGallery());
  $("grid").addEventListener("keydown", (e) => {                       // arrow keys walk the wall
    const cards = [...$("grid").querySelectorAll(".card")], i = cards.indexOf(document.activeElement);
    if (i < 0) return;
    const cols = Math.max(1, Math.round($("grid").clientWidth / cards[0].offsetWidth));
    const to = { ArrowRight: i + 1, ArrowLeft: i - 1, ArrowDown: i + cols, ArrowUp: i - cols }[e.key];
    if (to != null && cards[to]) { e.preventDefault(); cards[to].focus(); }
  });
}
