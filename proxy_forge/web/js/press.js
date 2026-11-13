// IV. The Press: a to-scale first sheet (front, or the back page as it will print), counts, and the exports.
import { $, S, h, pic, saveAs, on, ck } from "./core.js";
import { kindOf } from "./gallery.js";
import { wireDuplex, opts, syncDuplex, download, onDuplexChange } from "./duplex.js";

const BASIC = /^(snow-covered )?(plains|island|swamp|mountain|forest)$|^wastes$/i;
const isBasic = (u) => BASIC.test(u.name) || /^Basic/.test(u.type_line || "");
let side = "front";

const backCfg = () => ({ mode: "none", dfc: true, ...((S.deck && S.deck.back) || {}) });
const duplexOn = () => opts().mode !== "none";

function cards() {
  const d = S.deck; if (!d) return [];
  const skip = $("skip-basics").checked, copies = $("p-copies").checked, dfc = backCfg().dfc && duplexOn(), out = [];
  for (const k of d.order) {
    const u = d.units[k];
    if (skip && isBasic(u)) continue;
    if (dfc && (u.faces || 1) > 1 && u.face === 1 && d.order.includes(k.replace(/-1$/, "-0"))) continue;       // printed as the back of its front face
    for (let i = 0; i < (copies ? u.copies : 1); i++) out.push([k, u]);
  }
  return out;
}

function backOf(k, u) {
  const d = S.deck, c = backCfg();
  if (c.dfc && (u.faces || 1) > 1 && u.face === 0 && d.units[k.replace(/-0$/, "-1")]) return `/api/decks/${d.id}/cards/${ck(k.replace(/-0$/, "-1"))}.jpg`;
  return c.mode !== "none" ? `/api/decks/${d.id}/back.jpg?v=${encodeURIComponent(c.mode + (c.funny || "") + (c.art || ""))}` : null;
}

export function renderPress() {
  const d = S.deck, list = cards();
  const sheet = $("sheet"), o = opts();
  sheet.classList.toggle("letter", $("p-paper").value === "letter");
  for (const b of ["p-pdf", "p-zip", "p-shop"]) $(b).disabled = !list.length;
  const hasBacks = duplexOn() && list.some(([k, u]) => backOf(k, u));
  $("sheet-side").hidden = !duplexOn();
  if (!duplexOn()) side = "front";
  $("sheet-side").textContent = side === "front" ? "Show the back page" : "Show the front page";
  sheet.classList.toggle("flipshort", side === "back" && o.flip === "short");
  const first = list.slice(0, 9);
  let cells;
  if (side === "front" || !d) cells = first.map(([k, u]) => pic(`/api/decks/${d.id}/cards/${ck(k)}.jpg?v=${encodeURIComponent((u.printing && u.printing.id) || u.art)}`, { alt: u.name }));
  else {
    const slots = Array(9).fill(null);                                              // the back page, as it prints: each back in its mirrored slot
    first.forEach(([k, u], n) => {
      const r = Math.floor(n / 3), c = n % 3;
      const m = o.flip === "long" ? r * 3 + (2 - c) : (2 - r) * 3 + c;
      const src = backOf(k, u);
      slots[m] = src ? pic(src, { alt: "back of " + u.name }) : h("div", { class: "blank-slot" });
    });
    cells = slots.map((x) => x || h("div", { class: "blank-slot" }));
  }
  sheet.replaceChildren(...cells);
  const fb = d ? d.order.filter((k) => kindOf(d.units[k]) === "fallback").length : 0, ai = d ? d.order.filter((k) => kindOf(d.units[k]) === "ai").length : 0;
  $("sheet-cap").textContent = !list.length ? "" : side === "front" ? "The first sheet, to scale. Dashed lines are cuts."
    : `The back of the first sheet, as it prints (${o.flip === "long" ? "columns" : "rows"} mirrored so each back lands behind its front).` + (hasBacks ? "" : " No back chosen yet: pick one in the Source step.");
  const sheets = Math.ceil(list.length / 9);
  const notes = [];
  if (fb || ai) notes.push(h("small", {}, [fb ? `${fb} still amber (not in the chosen sets)` : "", ai ? `${ai} drawn with AI` : ""].filter(Boolean).join(" · ")));
  if (duplexOn() && !hasBacks) notes.push(h("small", {}, "Two-sided is on but this deck has no back yet: choose one under Source → Card backs."));
  $("press-count").replaceChildren(list.length ? `${sheets} ${o.mode === "none" ? "sheets" : `sheets, ${sheets * 2} pages`} · ${list.length} cards` : "No cards yet", ...notes);
}

export function wirePress() {
  const q = () => `copies=${$("p-copies").checked}`;
  $("p-pdf").onclick = () => download();
  $("p-zip").onclick = () => saveAs(`/api/decks/${S.deck.id}/export.zip?${q()}`, `${S.deck.name}.zip`);
  $("p-shop").onclick = () => saveAs(`/api/decks/${S.deck.id}/export.zip?${q()}&bleed=true`, `${S.deck.name}-print-shop.zip`);
  for (const id of ["p-paper", "p-copies", "skip-basics"]) $(id).onchange = renderPress;
  $("sheet-side").onclick = () => { side = side === "front" ? "back" : "front"; renderPress(); };
  wireDuplex();
  onDuplexChange(renderPress);
  on("deck", renderPress);
}
