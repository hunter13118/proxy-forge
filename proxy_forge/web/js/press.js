// IV. The Press: a to-scale first sheet (front, or the back page as it will print), counts, and the exports.
import { $, S, h, pic, saveAs, on, ck, api } from "./core.js";
import { kindOf } from "./gallery.js";
import { wireDuplex, opts, syncDuplex, download, onDuplexChange, layout } from "./duplex.js";

const BASIC = /^(snow-covered )?(plains|island|swamp|mountain|forest)$|^wastes$/i;
const isBasic = (u) => BASIC.test(u.name) || /^Basic/.test(u.type_line || "");
let side = "front";

// How many cards fit and how they sit is the server's call (/api/layout, the same function the PDF uses), so the preview never disagrees with the sheet.
const layouts = new Map();
const PAPER_MM = { letter: [215.9, 279.4], a4: [210, 297] };
async function getLayout(paper, gap) {
  const key = `${paper}:${gap}`;
  if (!layouts.has(key)) {
    try { layouts.set(key, await api(`/api/layout?paper=${paper}&gap=${gap}`)); }
    catch (_) { return { cols: 3, rows: 3, turned: false, per_page: 9, page_mm: PAPER_MM[paper], card_mm: [63, 88], room_mm: [5, 5, 5, 5] }; }       // server not answering: the plain 3 x 3
  }
  return layouts.get(key);
}
let renderSeq = 0;

// The back page as it prints. Each side of a back runs past its cut by the amount the server works out (export.py `_bleed_amounts`): the full bleed on the outside of the
// block, half the gap or less toward a neighbour across white space, nothing where cards touch. `amounts` are px of the card picture (750 wide); `angle` is the PIL rotation
// (counter-clockwise degrees) the PDF gives this back; `turned` means the card lies on its side (1050 x 750).
const reflect = (v, n) => (v < 0 ? -v - 1 : v >= n ? 2 * n - 1 - v : v);   // mirror a coordinate that falls outside the card back across its edge

function bledBack(src, amounts, angle, turned) {
  const bw = turned ? 1050 : 750, bh = turned ? 750 : 1050;
  const [l, t, r, b] = amounts;
  const W = bw + l + r, H = bh + t + b;
  const wrap = document.createElement("div");
  wrap.className = "bcell";
  wrap.style.aspectRatio = `${bw} / ${bh}`;
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  cv.style.width = `${(W / bw) * 100}%`;                           // the card keeps its cell; the bleed hangs out past it into the margin or the gap
  cv.style.left = `${(-l / bw) * 100}%`;
  cv.style.top = `${(-t / bh) * 100}%`;
  wrap.append(cv);
  const im = new Image();
  im.onload = () => {
    const base = document.createElement("canvas");
    base.width = bw; base.height = bh;
    const bc = base.getContext("2d");
    bc.translate(bw / 2, bh / 2);
    if (angle) bc.rotate((-angle * Math.PI) / 180);                  // canvas turns clockwise, PIL counter-clockwise
    bc.drawImage(im, -375, -525, 750, 1050);
    const src8 = bc.getImageData(0, 0, bw, bh).data;
    const ctx = cv.getContext("2d");
    const out = ctx.createImageData(W, H), od = out.data;
    for (let y = 0; y < H; y++) {
      const cy = reflect(y - t, bh);
      for (let x = 0; x < W; x++) {
        const cx = reflect(x - l, bw);
        const si = (cy * bw + cx) * 4, oi = (y * W + x) * 4;
        od[oi] = src8[si]; od[oi + 1] = src8[si + 1]; od[oi + 2] = src8[si + 2]; od[oi + 3] = 255;
      }
    }
    ctx.putImageData(out, 0, 0);
    ctx.setLineDash([10, 7]); ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,.6)";
    ctx.strokeRect(l + 1.5, t + 1.5, bw - 3, bh - 3);               // the cut line
  };
  im.src = src;
  return wrap;
}

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

// A front on a sheet where the cards lie on their sides: the picture is turned a quarter, counter-clockwise like the PDF.
const turnedFront = (img) => h("div", { class: "rcell" }, img);

export async function renderPress() {
  const mine = ++renderSeq;
  const paper = $("p-paper").value, L = layout();
  const lay = await getLayout(paper, L.gap);
  if (mine !== renderSeq) return;                                   // a newer render started while the layout was coming
  const d = S.deck, list = cards();
  const sheet = $("sheet"), o = opts();
  sheet.classList.toggle("letter", paper === "letter");
  // true scale: the card is 63 x 88 mm (or lying down), the gap is in mm, the sheet is the paper (percentages of the sheet's own width and height)
  const [pw, ph] = lay.page_mm, [cw, ch] = lay.card_mm, { cols, rows, turned } = lay;
  sheet.style.gridTemplateColumns = `repeat(${cols}, ${(cw / pw) * 100}%)`;
  sheet.style.columnGap = `${(L.gap / pw) * 100}%`;
  sheet.style.rowGap = `${(L.gap / ph) * 100}%`;
  const pxPerMm = 750 / 63;
  for (const b of ["p-pdf", "p-zip", "p-shop"]) $(b).disabled = !list.length;
  const hasBacks = duplexOn() && list.some(([k, u]) => backOf(k, u));
  $("sheet-side").hidden = !duplexOn();
  if (!duplexOn()) side = "front";
  $("sheet-side").textContent = side === "front" ? "Show the back page" : "Show the front page";
  sheet.classList.toggle("flipshort", side === "back" && o.flip === "short");
  const first = list.slice(0, lay.per_page);
  const blank = () => h("div", { class: "blank-slot", style: turned ? "aspect-ratio: 88 / 63" : "" });
  let cells;
  if (side === "front" || !d) cells = first.map(([k, u]) => {
    const im = pic(`/api/decks/${d.id}/cards/${ck(k)}.jpg?v=${encodeURIComponent((u.printing && u.printing.id) || u.art)}`, { alt: u.name });
    return turned ? turnedFront(im) : im;
  });
  else {
    const slots = Array(cols * rows).fill(null);                    // the back page, as it prints: each back in its mirrored slot
    const angle = o.flip === "long" ? (turned ? 270 : 0) : (turned ? 90 : 180);
    first.forEach(([k, u], n) => {
      const r = Math.floor(n / cols), c = n % cols;
      const m = o.flip === "long" ? r * cols + (cols - 1 - c) : (rows - 1 - r) * cols + c;
      const src = backOf(k, u);
      const mr = Math.floor(m / cols), mc = m % cols;               // the slot on the back page
      const edge = (outer, i) => Math.round((outer ? Math.min(L.bleed, lay.room_mm[i]) : Math.min(L.bleed, L.gap / 2)) * pxPerMm);   // outside: capped by what the printer reaches
      const amounts = [edge(mc === 0, 0), edge(mr === 0, 1), edge(mc === cols - 1, 2), edge(mr === rows - 1, 3)];
      slots[m] = src ? bledBack(src, amounts, angle, turned) : blank();
    });
    cells = slots.map((x) => x || blank());
  }
  sheet.replaceChildren(...cells);
  const fb = d ? d.order.filter((k) => kindOf(d.units[k]) === "fallback").length : 0, ai = d ? d.order.filter((k) => kindOf(d.units[k]) === "ai").length : 0;
  const [rl, rt, rr, rb] = lay.room_mm, capH = Math.min(rl, rr), capV = Math.min(rt, rb);                // outside bleed the printer can reach
  const capNote = [capH < L.bleed - 0.05 ? `${capH.toFixed(1)} mm left and right` : "", capV < L.bleed - 0.05 ? `${capV.toFixed(1)} mm top and bottom` : ""].filter(Boolean).join(", ");
  $("sheet-cap").textContent = !list.length ? "" : side === "front" ? `The first sheet, to scale (${lay.per_page} cards a sheet). Dashed lines are cuts.`
    : `The back of the first sheet, as it prints (${o.flip === "long" ? "columns" : "rows"} mirrored so each back lands behind its front). Dashed lines are cuts. The picture past them is the bleed: on the outside of the sheet, and in any gap.`
      + (capNote ? ` The printer cannot reach further out, so the outside bleed is limited to ${capNote}.` : "") + (hasBacks ? "" : " No back chosen yet: pick one in the Source step.");
  const sheets = Math.ceil(list.length / lay.per_page);
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
