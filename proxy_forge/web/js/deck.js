// I. The Threshold: paste or drop a deck list, a live ledger, the list of decks.
import { $, S, h, api, remember, recall, fail, follow, emit, toast } from "./core.js";

const SECTION = { commander: "Commander", deck: "Main", main: "Main", mainboard: "Main", maindeck: "Main", sideboard: "Sideboard", side: "Sideboard", companion: "Sideboard", maybeboard: "Maybe", considering: "Maybe", tokens: "Tokens" };

export function ledger(text) {
  const counts = {}; let sec = "Main"; let lines = 0;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("//") || line.startsWith("#")) continue;
    const head = line.replace(/:$/, "").toLowerCase();
    if (SECTION[head] && !/^\d/.test(line)) { sec = SECTION[head]; continue; }
    const sb = /^SB:/i.test(line);
    const m = line.replace(/^SB:\s*/i, "").match(/^(\d+)\s*x?\s+/);
    const q = m ? parseInt(m[1]) : 1;
    const s = sb ? "Sideboard" : sec;
    counts[s] = (counts[s] || 0) + q; lines++;
  }
  return { counts, lines };
}

function showLedger() {
  const { counts, lines } = ledger($("deck-text").value);
  const rows = Object.entries(counts).map(([k, v]) => h("div", {}, h("span", {}, k), h("b", {}, v)));
  $("ledger").replaceChildren(...(rows.length ? [...rows, h("div", {}, h("span", {}, "Distinct lines"), h("b", {}, lines))] : [h("span", { class: "mute" }, "Nothing yet.")]));
}

export async function loadDecks(select) {
  const decks = await api("/api/decks");
  const sel = $("deck-pick");
  sel.replaceChildren(h("option", { value: "" }, "— new deck —"), ...decks.map((d) => h("option", { value: d.id }, `${d.name} (${d.cards} cards)`)));
  sel.value = select || (S.deck ? S.deck.id : "");
}

export async function openDeck(id) {
  if (!id) { S.deck = null; emit("deck", null); return; }
  S.deck = await api(`/api/decks/${id}`);
  remember("deck", id);
  if (S.deck.template) { S.template = S.deck.template; emit("template"); }
  $("deck-name").value = S.deck.name;
  $("deck-text").value = S.deck.text || rebuiltList(S.deck);
  $("deck-sb").checked = !!S.deck.include_sideboard;
  showLedger();
  emit("deck", S.deck);
}

// Decks made before the list was kept: rebuilt from what was imported (quantities and names; the set and number of each line are not kept in those).
function rebuiltList(d) {
  const by = {};
  for (const e of d.entries || []) (by[e.section] = by[e.section] || []).push(`${e.qty} ${e.name}`);
  const head = { commander: "Commander", main: "Deck", sideboard: "Sideboard" };
  const single = Object.keys(by).length === 1 && by.main;
  return Object.entries(by).map(([sec, lines]) => (single ? "" : (head[sec] || sec) + "\n") + lines.join("\n")).join("\n\n");
}

export function deckNotes() {
  const d = S.deck;
  if (!d) { $("deck-notes").textContent = ""; return; }
  $("deck-notes").replaceChildren(`${d.order.length} cards hung. `, d.missing && d.missing.length ? h("b", {}, `Not found: ${d.missing.join(", ")}. `) : "");
}

async function viaImporter(form) {
  const r = await api("/api/import", { method: "POST", form });
  $("deck-text").value = r.text; showLedger();
  toast(`Read ${r.source}.` + (r.warnings.length ? " " + r.warnings.join(" ") : ""));
}

async function importDeck() {
  if (/^https?:\/\/\S+$/.test($("deck-text").value.trim())) {                    // a link: Archidekt
    const f = new FormData(); f.append("url", $("deck-text").value.trim());
    try { await viaImporter(f); } catch (e) { return fail(e); }
  }
  const text = $("deck-text").value.trim();
  if (!text) return toast("Paste a deck list first.", "bad");
  $("deck-import").disabled = true;
  try {
    const r = await api("/api/decks", { method: "POST", json: { name: $("deck-name").value || "My deck", text, profile: S.profile ? S.profile.id : "", template: S.template, include_sideboard: $("deck-sb").checked } });
    S.deck = { id: r.deck, order: [], units: {}, missing: [], template: S.template };
    follow(r.job, async () => { await loadDecks(r.deck); await openDeck(r.deck); $("deck-import").disabled = false; emit("goto", "source"); });
  } catch (e) { fail(e); $("deck-import").disabled = false; }
}

export function wireDeck() {
  $("deck-text").addEventListener("input", showLedger);
  $("deck-import").onclick = importDeck;
  $("deck-pick").onchange = () => openDeck($("deck-pick").value);
  $("deck-delete").onclick = async () => {
    if (S.deck && confirm(`Delete the deck "${S.deck.name}" and its cards?`)) { await api(`/api/decks/${S.deck.id}`, { method: "DELETE" }); S.deck = null; await loadDecks(); emit("deck", null); }
  };
  const well = $("well");
  for (const ev of ["dragenter", "dragover"]) document.addEventListener(ev, (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { e.preventDefault(); well.classList.add("drag"); emit("goto", "deck"); } });
  for (const ev of ["dragleave", "drop"]) document.addEventListener(ev, (e) => { if (ev === "drop" || e.target === document.documentElement) well.classList.remove("drag"); });
  document.addEventListener("drop", async (e) => {
    const f = e.dataTransfer?.files?.[0];
    if (!f) return;
    e.preventDefault();
    if (/\.(dek|csv)$/i.test(f.name)) { const fd = new FormData(); fd.append("file", f); try { await viaImporter(fd); } catch (err) { fail(err); } }
    else $("deck-text").value = await f.text();
    if (!$("deck-name").value || $("deck-name").value === "My deck") $("deck-name").value = f.name.replace(/\.[^.]+$/, "");
    showLedger();
  });
  showLedger();
}
