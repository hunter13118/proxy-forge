// Proxy Forge: the page. Four steps (Deck, Source, Gallery, Press), the status dots, sign-in through the tunnel, and the theme.
import { $, S, h, api, auth, authFetch, remember, recall, fail, follow, emit, on } from "./core.js";
import { wireForge, loadTemplates, loadProfiles, renderTemplates, fillLoras } from "./forge.js";
import { wireDeck, loadDecks, openDeck, deckNotes } from "./deck.js";
import { wireDoors } from "./atlas.js";
import { wireGallery, renderGallery } from "./gallery.js";
import { wireLoupe } from "./loupe.js";
import { wirePress, renderPress } from "./press.js";

function go(view) {
  for (const v of document.querySelectorAll(".view")) v.hidden = v.id !== "v-" + view;
  for (const b of document.querySelectorAll(".step")) b.classList.toggle("on", b.dataset.view === view);
  remember("view", view);
  if (view === "gallery") renderGallery();
  if (view === "press") renderPress();
  scrollTo({ top: 0 });
}

async function loadStatus() {
  try {
    const s = await api("/api/status");
    S.status = s;
    const dot = (ok, label, why) => h("span", { title: why || "" }, h("i", { class: ok ? "ok" : "" }), label);
    $("status").replaceChildren(dot(s.studio, "studio", s.studio_problem), dot(s.comfy, s.picture_model || "pictures"), dot(s.printings > 0, s.printings ? `${Math.round(s.printings / 1000)}k printings` : "card index", "every printing of every card, for set-locked art"));
    fillLoras(s);
  } catch (e) { $("status").textContent = "server not answering"; }
}

const generate = async (body) => {
  if (!S.deck) return;
  try {
    if (S.deck.art_policy && S.deck.art_policy.source && S.deck.art_policy.source !== "forge") {       // back to AI art first, then draw
      const j = await api(`/api/decks/${S.deck.id}/art-policy`, { method: "PUT", json: { source: "forge" } });
      await new Promise((res) => follow(j.job, res));
    }
    follow(await api(`/api/decks/${S.deck.id}/generate`, { method: "POST", json: body }), () => go("gallery"));
  } catch (e) { fail(e); }
};

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
  auth.set(async () => (Clerk.session ? Clerk.session.getToken() : null));
  if (!Clerk.session) {
    gate.hidden = false;
    await new Promise((resolve) => { Clerk.mountSignIn($("gate-box"), { routing: "hash" }); const off = Clerk.addListener(({ session }) => { if (session) { off(); resolve(); } }); });
    gate.hidden = true;
  }
  $("who").hidden = false;
  Clerk.mountUserButton($("who"));
}

function wire() {
  for (const b of document.querySelectorAll(".step")) b.onclick = () => go(b.dataset.view);
  on("goto", go);
  on("template", renderTemplates);
  on("deck", deckNotes);
  $("cancel").onclick = () => S.job && api(`/api/jobs/${S.job.id}/cancel`, { method: "POST" });
  $("theme").onclick = () => {
    const light = (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")) === "light";
    document.documentElement.dataset.theme = light ? "dark" : "light"; remember("theme", light ? "dark" : "light");
  };
  const t = recall("theme"); if (t) document.documentElement.dataset.theme = t;
  wireForge(); wireDeck(); wireDoors(generate); wireGallery(); wireLoupe(); wirePress();
}

(async function start() {
  try {
    wire();
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
    if ($("deck-pick").value) { await openDeck($("deck-pick").value); go(recall("view") && recall("view") !== "deck" ? recall("view") : "gallery"); } else go("deck");
    setInterval(loadStatus, 30000);
  } catch (e) { $("status").textContent = "could not start: " + e.message; console.error(e); }
})();
