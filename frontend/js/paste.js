// Paste screenshots / copied images straight into an attachment area.
// Works two ways: the "Paste" button (reads the clipboard) and Ctrl+V / ⌘V anywhere on the page.

const EXT = { "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp", "application/pdf": "pdf" };

function named(blob, i = 0) {
  if (blob instanceof File && blob.name && !/^image\.\w+$/i.test(blob.name)) return blob;   // a real copied file keeps its name
  const ext = EXT[blob.type] || "png";
  const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "").replace(/^(\d{8})/, "$1-");
  return new File([blob], `pasted-${stamp}${i ? `-${i + 1}` : ""}.${ext}`, { type: blob.type || "image/png" });
}

/** Files from a paste event (Ctrl+V). Empty when the clipboard holds only text. */
export function filesFromPaste(e) {
  const items = [...(e.clipboardData?.items || [])].filter((it) => it.kind === "file");
  return items.map((it, i) => it.getAsFile()).filter(Boolean).map(named);
}

/** Read images from the clipboard (Paste button). Throws a friendly message if the browser can't. */
export async function readClipboardFiles() {
  if (!navigator.clipboard?.read) throw new Error("Your browser can't read the clipboard from a button — press Ctrl+V (⌘V on Mac) instead.");
  let items;
  try { items = await navigator.clipboard.read(); }
  catch { throw new Error("Clipboard access was blocked — press Ctrl+V (⌘V on Mac) to paste instead."); }
  const out = [];
  for (const it of items) {
    const type = it.types.find((t) => t.startsWith("image/") || t === "application/pdf");
    if (type) out.push(named(await it.getType(type), out.length));
  }
  if (!out.length) throw new Error("There's no image on the clipboard. Take a screenshot (Win + Shift + S) or copy an image first.");
  return out;
}

/** Ctrl+V on the page adds files (ignored while typing text, unless the clipboard has a picture). */
export function onPasteFiles(root, handler) {
  const fn = (e) => {
    if (!root.isConnected) { document.removeEventListener("paste", fn); return; }
    const files = filesFromPaste(e);
    if (files.length) { e.preventDefault(); handler(files); }
  };
  document.addEventListener("paste", fn);
}
