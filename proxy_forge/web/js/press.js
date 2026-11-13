// IV. The Press: a to-scale first sheet, counts, and the exports.
import { $, S, h, pic, saveAs, on, ck } from "./core.js";
import { kindOf } from "./gallery.js";

const BASIC = /^(snow-covered )?(plains|island|swamp|mountain|forest)$|^wastes$/i;
const isBasic = (u) => BASIC.test(u.name) || /^Basic/.test(u.type_line || "");

function cards() {
  const d = S.deck; if (!d) return [];
  const skip = $("skip-basics").checked, copies = $("p-copies").checked, out = [];
  for (const k of d.order) { const u = d.units[k]; if (skip && isBasic(u)) continue; for (let i = 0; i < (copies ? u.copies : 1); i++) out.push([k, u]); }
  return out;
}

export function renderPress() {
  const d = S.deck, list = cards();
  const sheet = $("sheet");
  sheet.classList.toggle("letter", $("p-paper").value === "letter");
  for (const b of ["p-pdf", "p-zip", "p-shop"]) $(b).disabled = !list.length;
  sheet.replaceChildren(...list.slice(0, 9).map(([k, u]) => pic(`/api/decks/${d.id}/cards/${ck(k)}.jpg?v=${encodeURIComponent((u.printing && u.printing.id) || u.art)}`, { alt: u.name })));
  const fb = d ? d.order.filter((k) => kindOf(d.units[k]) === "fallback").length : 0, ai = d ? d.order.filter((k) => kindOf(d.units[k]) === "ai").length : 0;
  $("sheet-cap").textContent = list.length ? "The first sheet, to scale. Dashed lines are cuts." : "";
  $("press-count").replaceChildren(list.length ? `${Math.ceil(list.length / 9)} sheets · ${list.length} cards` : "No cards yet",
    fb || ai ? h("small", {}, [fb ? `${fb} still amber (not in the chosen sets)` : "", ai ? `${ai} drawn with AI` : ""].filter(Boolean).join(" · ")) : null);
}

export function wirePress() {
  const q = () => `copies=${$("p-copies").checked}`;
  $("p-pdf").onclick = () => saveAs(`/api/decks/${S.deck.id}/export.pdf?paper=${$("p-paper").value}&${q()}&skip_basics=${$("skip-basics").checked}`, `${S.deck.name}-${$("p-paper").value}.pdf`);
  $("p-zip").onclick = () => saveAs(`/api/decks/${S.deck.id}/export.zip?${q()}`, `${S.deck.name}.zip`);
  $("p-shop").onclick = () => saveAs(`/api/decks/${S.deck.id}/export.zip?${q()}&bleed=true`, `${S.deck.name}-print-shop.zip`);
  for (const id of ["p-paper", "p-copies", "skip-basics"]) $(id).onchange = renderPress;
  on("deck", renderPress);
}
