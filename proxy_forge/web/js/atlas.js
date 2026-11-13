// II. Three doors: Forge (AI art), Archive (the Atlas of sets), Vault (priciest). The Atlas shows every set with a coverage ring: how many of the deck's cards it holds.
import { $, S, h, api, pic, fail, follow, emit, on, policyOf, remember, recall, toast } from "./core.js";

const TYPES = [["", "All"], ["expansion", "Expansions"], ["core", "Core"], ["masters", "Masters"], ["commander", "Commander"], ["draft_innovation", "Horizons"], ["promo", "Promos"], ["box", "Secret Lair"]];
let chain = [];
let q = "", type = "", year = 0, shown = 60;
let door = recall("door") || "forge";

export function showDoor(name) {
  door = name; remember("door", name);
  for (const b of document.querySelectorAll(".door")) b.classList.toggle("on", b.dataset.door === name);
  for (const n of ["forge", "archive", "vault"]) $("door-" + n).hidden = n !== name;
  if (name === "archive") loadAtlas();
  syncButtons();
}

function syncButtons() {
  const d = S.deck, has = !!(d && d.order && d.order.length);
  $("gen").disabled = !has; $("regen").disabled = !has;
  $("archive-go").disabled = !has || !(chain.length || $("o-pins").checked);
  $("vault-go").disabled = !has;
}

function readPolicyIntoControls() {
  const p = policyOf(S.deck);
  if (S.deck && S.deck.art_policy) chain = [...(p.sets || [])];
  $("o-treatment").value = p.treatment; $("o-fallback").value = p.fallback; $("o-print").value = p.print;
  $("o-family").checked = p.family; $("o-pins").checked = p.pins; $("o-vary").checked = p.vary_basics;
  $("v-kind").value = p.source === "budget" ? "budget" : "vault"; $("v-currency").value = p.vault.currency;
  $("v-foil").checked = p.vault.foil; $("v-serialized").checked = !!p.vault.serialized; $("v-scope").checked = !!p.vault.scope;
  const open = S.deck && S.deck.art_policy ? ({ forge: "forge", archive: "archive", vault: "vault", budget: "vault" })[p.source] : null;
  if (open && !S.doorTouched) showDoor(open);
}

const policyFromControls = (source) => ({
  source, sets: chain, family: $("o-family").checked, treatment: $("o-treatment").value, pins: $("o-pins").checked, fallback: $("o-fallback").value,
  vary_basics: $("o-vary").checked, print: $("o-print").value,
  vault: { currency: $("v-currency").value, basis: "median", foil: $("v-foil").checked, serialized: $("v-serialized").checked, guard: true, scope: $("v-scope").checked },
});

async function apply(source, label) {
  if (!S.deck) return;
  try {
    const r = await api(`/api/decks/${S.deck.id}/art-policy`, { method: "PUT", json: policyFromControls(source) });
    toast(label);
    follow(r.job, async () => { emit("goto", "gallery"); });
  } catch (e) { fail(e); }
}

// ------------------------------------------------------------------------------------------------------------------------------------------------------ the Atlas
async function ensureSets() {
  if (S.sets) return true;
  try { S.sets = await api("/api/sets"); return true; }
  catch (e) {
    if (e.status !== 409) { fail(e); return false; }
    $("atlas").replaceChildren(h("div", { class: "empty", style: "grid-column:1/-1" },
      h("p", {}, "The card index (every printing of every card, about 80 MB to download) is not built yet. It takes about half a minute, once."),
      h("button", { class: "primary", onclick: async () => { try { follow(await api("/api/index", { method: "POST" }), loadAtlas); } catch (err) { fail(err); } } }, "Build the card index")));
    return false;
  }
}

export async function loadAtlas() {
  if (!S.deck || !S.deck.order.length) { $("atlas").replaceChildren(h("div", { class: "empty", style: "grid-column:1/-1" }, "Import a deck first: the Atlas shows which sets hold your cards.")); return; }
  if (!(await ensureSets())) return;
  try { S.coverage = await api(`/api/decks/${S.deck.id}/coverage`); } catch (e) { return fail(e); }
  $("atlas-note").textContent = `Every set, with how many of your ${S.coverage.total} different cards it holds. Tap sets to build a chain: the first set that has a card wins.`;
  renderTypes(); renderRibbon(); renderAtlas(); renderChain();
}

function renderTypes() {
  $("atlas-types").replaceChildren(...TYPES.map(([v, l]) => h("button", { class: "chip" + (type === v ? " on" : ""), onclick: () => { type = v; shown = 60; renderTypes(); renderAtlas(); } }, l)));
}

function visibleSets() {
  const cov = S.coverage.sets;
  const ql = q.trim().toLowerCase();
  return cov.filter((s) => (!type || s.set_type === type) && (!year || (s.released_at || "").startsWith(String(year))) && (!ql || s.name.toLowerCase().includes(ql) || s.code.includes(ql)));
}

function renderRibbon() {
  const years = {};
  for (const s of S.coverage.sets) { const y = +(s.released_at || "0").slice(0, 4); if (y) years[y] = (years[y] || 0) + s.have; }
  const ys = Object.keys(years).map(Number).sort((a, b) => a - b);
  if (!ys.length) return $("ribbon").replaceChildren();
  const max = Math.max(...Object.values(years));
  const all = []; for (let y = ys[0]; y <= ys[ys.length - 1]; y++) all.push(y);
  $("ribbon").replaceChildren(...all.map((y) => h("button", { class: year === y ? "on" : "", title: `${y}: ${years[y] || 0} card printings`, onclick: () => { year = year === y ? 0 : y; shown = 60; renderRibbon(); renderAtlas(); } },
    h("i", { style: `height:${Math.max(2, Math.round(100 * (years[y] || 0) / max))}%` }), h("span", {}, y % 5 === 0 ? String(y).slice(2) : ""))));
}

function setEl(s) {
  const total = S.coverage.total, pct = Math.round(100 * s.have / Math.max(1, total)), ord = chain.indexOf(s.code);
  const icon = pic(`/api/sets/${s.code}/icon.svg`, { alt: "", loading: "lazy" });
  icon.onerror = () => { icon.style.display = "none"; };
  return h("button", { class: "set" + (ord >= 0 ? " on" : ""), title: `${s.name} (${s.code.toUpperCase()}), ${s.released_at}: ${s.have} of ${total}`, onclick: () => toggle(s.code) },
    ord >= 0 ? h("span", { class: "ord" }, ord + 1) : null,
    h("div", { class: "ring" + (s.have === total ? " all" : ""), style: `--p:${pct}` }, h("div", {}, icon)),
    h("div", { class: "nm" }, s.name),
    h("div", { class: "cv" }, `${s.have} of ${total}`),
    h("div", { class: "cd" }, `${s.code} · ${(s.released_at || "").slice(0, 4)}`));
}

function renderAtlas() {
  const list = visibleSets();
  $("atlas").replaceChildren(...(list.length ? list.slice(0, shown).map(setEl) : [h("div", { class: "empty", style: "grid-column:1/-1" }, "No set matches.")]));
  $("atlas-more").hidden = list.length <= shown;
  $("atlas-more").textContent = `Show more sets (${list.length - shown} left)`;
}

function toggle(code) {
  chain = chain.includes(code) ? chain.filter((c) => c !== code) : [...chain, code];
  renderAtlas(); renderChain(); syncButtons();
}

function renderChain() {
  const info = Object.fromEntries((S.coverage ? S.coverage.sets : []).map((s) => [s.code, s]));
  let dragging = null;
  const chips = chain.map((c, i) => {
    const el = h("div", { class: "link-chip", draggable: "true", title: "Drag to reorder" },
      h("small", {}, i + 1), h("span", {}, `${c.toUpperCase()}${info[c] ? " · " + info[c].have + "/" + S.coverage.total : ""}`),
      h("button", { "aria-label": "Remove " + c, onclick: () => toggle(c) }, "×"));
    el.addEventListener("dragstart", () => { dragging = c; });
    el.addEventListener("dragover", (e) => { e.preventDefault(); el.classList.add("over"); });
    el.addEventListener("dragleave", () => el.classList.remove("over"));
    el.addEventListener("drop", (e) => {
      e.preventDefault(); el.classList.remove("over");
      if (dragging && dragging !== c) { chain = chain.filter((x) => x !== dragging); chain.splice(chain.indexOf(c), 0, dragging); renderAtlas(); renderChain(); }
    });
    return el;
  });
  $("chain").replaceChildren(h("span", { class: "mute" }, "Chain:"), ...(chips.length ? chips.flatMap((c, i) => [i ? h("span", { class: "link" }, "→") : null, c]) : [h("span", { class: "empty-chain" }, "Tap sets above. The first set that has a card is used; cards in none of them follow “Not in the chain”.")]));
}

// ------------------------------------------------------------------------------------------------------------------------------------------------------------- wiring
export function wireDoors(generate) {
  for (const b of document.querySelectorAll(".door")) b.onclick = () => { S.doorTouched = true; showDoor(b.dataset.door); };
  $("o-pins").onchange = syncButtons;
  $("atlas-q").oninput = (e) => { q = e.target.value; shown = 60; if (S.coverage) renderAtlas(); };
  $("atlas-more").onclick = () => { shown += 90; renderAtlas(); };
  $("archive-go").onclick = () => apply("archive", `Hanging from ${chain.map((c) => c.toUpperCase()).join(" → ")}…`);
  $("vault-go").onclick = () => apply($("v-kind").value, $("v-kind").value === "budget" ? "Looking for the cheapest printings…" : "Appraising the deck…");
  $("gen").onclick = () => generate({});
  $("regen").onclick = () => { if (confirm("Write every prompt again and redraw every card?")) generate({ rewrite_prompts: true, force: true }); };
  let last = null;
  const fresh = () => { S.coverage = null; readPolicyIntoControls(); syncButtons(); if (door === "archive") loadAtlas(); };
  on("deck", (d) => { syncButtons(); if ((d && d.id) !== last) { last = d && d.id; S.doorTouched = false; fresh(); } });     // a progress tick must not reset what is being edited
  on("decks", fresh);
  showDoor(door);
}
