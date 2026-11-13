// Forge: the AI-art door. Style, templates and the people (photos -> description -> LoRA). Moved as it was from the single-file page; only the imports are new.
import { $, S, h, api, pic, remember, recall, debounce, fail, follow, emit } from "./core.js";

// ----------------------------------------------------------------------------------------------------------------------------------------------------- templates
export async function loadTemplates() {
  S.templates = await api("/api/templates");
  S.template = recall("template") || S.templates[0].id;
  renderTemplates();
}
export function renderTemplates() {
  $("templates").replaceChildren(...S.templates.map((t) =>
    h("div", { class: "tile" + (t.id === S.template ? " on" : ""), title: t.blurb, onclick: () => pickTemplate(t.id) },
      pic(`/api/templates/${t.id}/preview.jpg`, { alt: t.name }), t.name)));
}
async function pickTemplate(id) {
  S.template = id; remember("template", id); renderTemplates();
  if (S.deck) {
    try { const r = await api(`/api/decks/${S.deck.id}`, { method: "PATCH", json: { template: id } }); S.deck.template = id; emit("deck", S.deck); follow(r.job); } catch (e) { fail(e); }
  }
}

// ------------------------------------------------------------------------------------------------------------------------------------------------------ profiles
export async function loadProfiles() {
  S.profiles = await api("/api/profiles");
  if (!S.profiles.length) S.profiles = [await api("/api/profiles", { method: "POST", json: { name: "My style" } })];
  const want = (S.deck && S.deck.profile) || recall("profile");
  S.profile = S.profiles.find((p) => p.id === want) || S.profiles[0];
  $("profile").replaceChildren(...S.profiles.map((p) => h("option", { value: p.id }, p.name)));
  $("profile").value = S.profile.id;
  renderProfile();
}
export function renderProfile() {
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


export function wireForge() {
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
}

export function fillLoras(s) {
  const sel = $("lora");
  const keep = S.profile ? S.profile.lora : "";
  sel.replaceChildren(h("option", { value: "" }, "none"), ...s.loras.map((l) => h("option", { value: l }, l)));
  sel.value = keep || "";
}
