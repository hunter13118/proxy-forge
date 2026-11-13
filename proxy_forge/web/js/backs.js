// Card backs (in the Source step): none, the official Magic back, funny ones, your own picture, or one the AI draws.
import { $, S, h, api, pic, fail, follow, emit, on, toast } from "./core.js";

let list = [];
const cfgOf = (d) => ({ mode: "none", funny: "swirl", dfc: true, prompt: "", seed: 1, art: "", ...((d && d.back) || {}) });

function tile(label, content, on_, click) {
  return h("div", { class: "tile" + (on_ ? " on" : ""), role: "button", tabindex: 0, onclick: click, onkeydown: (e) => { if (e.key === "Enter") click(); } }, content, label);
}

async function put(fields, msg) {
  if (!S.deck) return toast("Open a deck first.", "bad");
  try { const r = await api(`/api/decks/${S.deck.id}/back`, { method: "PUT", json: fields }); if (msg) toast(msg); follow(r.job, refresh); } catch (e) { fail(e); }
}

function render() {
  const c = cfgOf(S.deck), d = S.deck;
  const none = tile("No back", h("div", { class: "none-tile" }, "—"), c.mode === "none", () => put({ mode: "none" }));
  const tiles = list.map((b) => tile(b.name, pic(`/api/backs/${b.id}.jpg`, { alt: b.name, title: b.blurb }), b.id === "mtg" ? c.mode === "mtg" : c.mode === "funny" && c.funny === b.id,
    () => (b.id === "mtg" ? put({ mode: "mtg" }, "Using Magic's own back.") : put({ mode: "funny", funny: b.id }, `Using “${b.name}”.`))));
  const mine = tile("My own picture", c.mode === "custom" ? pic(`/api/decks/${d.id}/back.jpg?v=${Date.now()}`, { alt: "" }) : h("div", { class: "none-tile" }, "+"), c.mode === "custom", () => $("back-file").click());
  const ai = tile("Drawn by the AI", c.mode === "ai" ? pic(`/api/decks/${d.id}/back.jpg?v=${Date.now()}`, { alt: "" }) : h("div", { class: "none-tile" }, "✦"), c.mode === "ai", () => { $("back-ai").hidden = false; $("back-prompt").focus(); });
  $("back-tiles").replaceChildren(none, ...tiles, mine, ai);
  $("back-dfc").checked = c.dfc;
  $("back-prompt").value = $("back-prompt").value || c.prompt || "";
  $("back-seed").value = c.seed;
  $("back-ai").hidden = $("back-ai").hidden && c.mode !== "ai";
}

async function refresh() {
  if (!S.deck) return;
  S.deck = await api(`/api/decks/${S.deck.id}`);
  emit("deck", S.deck);
  render();
}

export function wireBacks() {
  api("/api/backs").then((l) => { list = l; if (S.deck) render(); }).catch(() => {});
  on("deck", (d) => { if (d && list.length) render(); });
  $("back-dfc").onchange = () => S.deck && api(`/api/decks/${S.deck.id}/back`, { method: "PUT", json: { dfc: $("back-dfc").checked } }).then((r) => follow(r.job, refresh)).catch(fail);
  $("back-file").onchange = async () => {
    const f = $("back-file").files[0];
    if (!f || !S.deck) return;
    const form = new FormData(); form.append("file", f);
    try { const r = await api(`/api/decks/${S.deck.id}/back/custom`, { method: "POST", form }); toast("Using your picture."); follow(r.job, refresh); } catch (e) { fail(e); }
    $("back-file").value = "";
  };
  $("back-draw").onclick = async () => {
    if (!S.deck) return toast("Open a deck first.", "bad");
    try {
      const r = await api(`/api/decks/${S.deck.id}/back/draw`, { method: "POST", json: { prompt: $("back-prompt").value, seed: parseInt($("back-seed").value) || 1 } });
      follow(r.job, refresh);
    } catch (e) { fail(e); }
  };
}
