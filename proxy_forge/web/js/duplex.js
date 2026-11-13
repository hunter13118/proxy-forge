// Two-sided printing: the choices, the printer help, and the downloads. The geometry (a back exactly behind its front) is the server's; this page only asks for it and explains it.
import { $, S, h, saveAs, recall, remember, on, toast, ck } from "./core.js";

const PRESETS = { "auto-long": { mode: "auto", flip: "long" }, "manual-long": { mode: "manual", flip: "long" } };

export const opts = () => ({ mode: $("d-mode").value, flip: $("d-flip").value, rev: $("d-rev").checked, split: $("d-split").checked, dx: parseFloat($("d-dx").value) || 0, dy: parseFloat($("d-dy").value) || 0 });

export function query() {
  const o = opts();
  return o.mode === "none" ? "" : `&duplex=${o.mode}&flip=${o.flip}&reverse_backs=${o.rev}&back_dx=${o.dx}&back_dy=${o.dy}`;
}

function note() {
  const o = opts();
  const lines = {
    none: "",
    auto: `The PDF alternates front, back, front, back. In your print dialog turn on 2-sided printing and choose “flip on the ${o.flip} edge” to match this page. Print one sheet first.`,
    manual: `The PDF has every front first, then every back. Print the fronts, turn the stack over (${o.flip === "long" ? "like a book page: left edge to right" : "like a notepad: top edge to bottom"}), put it back in, and print the backs. Print one sheet first.`,
  };
  $("d-note").textContent = lines[o.mode];
}

export function syncDuplex() {
  const o = opts();
  $("d-more").hidden = o.mode === "none";
  $("d-rev-wrap").hidden = $("d-split-wrap").hidden = o.mode !== "manual";
  $("p-pdf").textContent = o.mode === "none" ? "Print sheets (PDF)" : o.mode === "manual" && o.split ? "Save fronts + backs (2 PDFs)" : "Print sheets, two-sided (PDF)";
  note();
  remember("duplex", JSON.stringify(o));
}

function helpHtml() {
  const o = opts(), edge = o.flip === "long" ? "long" : "short";
  const turn = o.flip === "long" ? "Turn the stack over like turning a page of a book: the left edge goes to the right, and the same end of the sheet still goes into the printer first." : "Turn the stack over like flipping a notepad up: the top edge goes to the bottom.";
  const common = h("div", {},
    h("h3", {}, "Before anything"),
    h("ul", {}, h("li", {}, "Print at ", h("b", {}, "100% / Actual size"), ". Never “Fit to page” or “Shrink oversized pages”: a card must measure 63 × 88 mm."),
      h("li", {}, "Pick the paper size you chose here (A4 or Letter) in the print dialog, and switch off any borderless mode."),
      h("li", {}, "Print the ", h("b", {}, "alignment test sheet"), " first (button here). Print both sides, hold the sheet to a window: the red crosses must sit on top of each other and the numbers must read the same way up. Then print the deck.")));
  const auto = h("div", {},
    h("h3", {}, "Auto-duplex (the printer pulls the sheet back in), for example the Epson ET-2980"),
    h("ol", {},
      h("li", {}, "Choose ", h("b", {}, "Auto-duplex"), " here and the same flip edge in the print dialog: ", h("b", {}, `“flip on the ${edge} edge”`), " (some dialogs call it long-edge / short-edge binding). The two must agree, or the backs come out upside-down."),
      h("li", {}, "Load plain paper in the normal tray, the way you do for any two-sided print."),
      h("li", {}, "Print pages 1–2 only first (one sheet). Compare it with the test sheet."),
      h("li", {}, "If the backs are upside-down against the fronts, the flip edge in the dialog and here disagree: set both to the other edge."),
      h("li", {}, "If the back sits a little off, use “shift backs” here (1 mm is about 12 pixels at 300 dpi) rather than changing the printer."),
      h("li", {}, "Thick card stock may not duplex reliably: use the manual way below for that.")));
  const manual = h("div", {},
    h("h3", {}, "All fronts, then all backs (a rear-feed printer, or any printer without duplex)"),
    h("ol", {},
      h("li", {}, "Print the fronts (the first pages of the PDF, or the “fronts” PDF)."),
      h("li", {}, "Do not shuffle the stack. ", turn),
      h("li", {}, "Put it back in so that the blank side is the one that gets printed. Which way up that is depends on your printer (many rear feeds print on the side that faces you or up; check the manual or run one test sheet). Mark the first sheet lightly in pencil to see what happened."),
      h("li", {}, "Print the backs (the later pages, or the “backs” PDF)."),
      h("li", {}, "If the backs come out in the reverse order to the fronts (your printer stacks its output the other way), tick “backs come out in the opposite order” and save the PDF again."),
      h("li", {}, "If a test back lands upside-down, change “Flip the sheet on its” here to the other edge: you do not need to re-feed differently.")));
  const save = h("div", {},
    h("h3", {}, "Saving the PDF for your setup"),
    h("ul", {},
      h("li", {}, h("b", {}, "Auto-duplex: "), "one PDF. Open it in a PDF viewer (not a web page) and print with 2-sided on."),
      h("li", {}, h("b", {}, "Manual: "), "tick “two separate PDFs” and keep ", h("code", {}, "fronts"), " and ", h("code", {}, "backs"), " as two files, so each print is a single plain job."),
      h("li", {}, "Do not tick “Print as image” and keep scale at 100%. If you use “Microsoft Print to PDF” or similar, choose the same paper size."),
      h("li", {}, "Once a setup lines up, note the shift values: they are saved in this browser."),
      h("li", {}, "Backs are drawn exactly behind the fronts on the sheet, in the mirrored place: if you cut them apart and they do not match, it is the printer's feed, not the file: use the test sheet and the shift.")));
  return [common, o.mode === "manual" ? manual : auto, o.mode === "manual" ? auto : manual, save];
}

export function wireDuplex() {
  try { const o = JSON.parse(recall("duplex") || "{}"); if (o.mode) { $("d-mode").value = o.mode; $("d-flip").value = o.flip || "long"; $("d-rev").checked = !!o.rev; $("d-split").checked = !!o.split; $("d-dx").value = o.dx || 0; $("d-dy").value = o.dy || 0; } } catch (_) {}
  for (const id of ["d-mode", "d-flip", "d-rev", "d-split", "d-dx", "d-dy"]) $(id).onchange = () => { syncDuplex(); emitChange(); };
  $("d-preset").onchange = () => { const p = PRESETS[$("d-preset").value]; if (p) { $("d-mode").value = p.mode; $("d-flip").value = p.flip; syncDuplex(); emitChange(); } };
  $("d-help").onclick = () => { $("help-body").replaceChildren(h("h2", {}, "Printing two-sided"), ...helpHtml()); $("help").showModal(); };
  $("help-close").onclick = () => $("help").close();
  $("d-test").onclick = () => saveAs(`/api/duplex-test.pdf?paper=${$("p-paper").value}&flip=${$("d-flip").value}&back_dx=${opts().dx}&back_dy=${opts().dy}`, `duplex-test-${$("p-paper").value}-${$("d-flip").value}.pdf`);
  syncDuplex();
}
let emitChange = () => {};
export const onDuplexChange = (fn) => { emitChange = fn; };

export function download() {
  const o = opts(), base = `/api/decks/${S.deck.id}/export.pdf?paper=${$("p-paper").value}&copies=${$("p-copies").checked}&skip_basics=${$("skip-basics").checked}${query()}`;
  const name = `${S.deck.name}-${$("p-paper").value}`;
  if (o.mode === "manual" && o.split) { saveAs(base + "&part=fronts", `${name}-fronts.pdf`); setTimeout(() => saveAs(base + "&part=backs", `${name}-backs.pdf`), 600); toast("Saving the fronts and the backs as two PDFs."); }
  else saveAs(base, `${name}${o.mode === "none" ? "" : "-" + o.mode}.pdf`);
}
