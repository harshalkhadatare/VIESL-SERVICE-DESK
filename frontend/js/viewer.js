// In-app file viewer: images and PDFs open inside the portal (files are only reachable while signed in).
// Toolbar: zoom, fit, rotate, previous/next, open in a new tab, print, copy link, download, delete (IT only).
import { api } from "./api.js";
import { $, $$, html, mount, icon, fileSize, fmtDate, toast, errorToast, confirmDialog, nameIdText } from "./ui.js";

const blobs = new Map();   // "IT-26-000001:15" → Promise<Blob>, so thumbnails and the viewer share one download

export const isImage = (a) => /^image\//.test(a.content_type) && !/hei[cf]/i.test(a.content_type);
export const isPdf = (a) => a.content_type === "application/pdf";

// PDF.js (bundled in /static/vendor/pdfjs) draws PDFs page by page, so they show on phones too
const PDFJS = "/static/vendor/pdfjs/";
let pdfLib = null;
function pdfjs() {
  if (!pdfLib) {
    pdfLib = import(PDFJS + "pdf.min.mjs").then((m) => { m.GlobalWorkerOptions.workerSrc = PDFJS + "pdf.worker.min.mjs"; return m; });
    pdfLib.catch(() => { pdfLib = null; });
  }
  return pdfLib;
}

export function fileBlob(number, a) {
  const key = `${number}:${a.id}`;
  if (!blobs.has(key)) {
    const p = api.blob(`/tickets/${number}/attachments/${a.id}`, { mode: "view" });
    p.catch(() => blobs.delete(key));
    blobs.set(key, p);
  }
  return blobs.get(key);
}

/** Small previews for image tiles (only reasonably small images, to keep the page fast). */
export function loadThumbs(root, number, files) {
  for (const a of files) {
    const box = root.querySelector(`[data-thumb="${a.id}"]`);
    if (!box || !isImage(a) || a.size_bytes > 4 * 1024 * 1024) continue;
    fileBlob(number, a).then((b) => {
      if (!box.isConnected) return;
      const img = new Image();
      img.alt = "";
      img.onload = () => URL.revokeObjectURL(img.src);
      img.src = URL.createObjectURL(b);
      box.replaceChildren(img);
      box.classList.add("has-img");
    }).catch(() => {});
  }
}

export async function downloadFile(number, a) {
  try {
    const b = await api.blob(`/tickets/${number}/attachments/${a.id}`, { mode: "download" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(b);
    link.download = a.original_name;
    document.body.appendChild(link);
    link.click();
    setTimeout(() => { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
  } catch (e) { errorToast(e); }
}

export function openViewer({ number, files, index = 0, canDelete = false, onDeleted }) {
  let i = index, url = null, zoom = 1, rot = 0, nat = null, cur = null, pdf = null, renderSeq = 0;
  const wrap = document.createElement("div");
  wrap.className = "viewer";
  wrap.setAttribute("role", "dialog");
  wrap.setAttribute("aria-modal", "true");
  mount(wrap, html`
    <div class="vw-bar">
      <div class="vw-title"><span class="vw-ic" id="vw-ic"></span>
        <div class="vw-names"><b id="vw-name"></b><span id="vw-meta"></span></div></div>
      <div class="vw-tools">
        <span class="vw-group" id="vw-zoom">
          <button class="vw-btn" data-a="out" title="Zoom out (−)">${icon("zoomOut")}</button>
          <button class="vw-btn vw-pct" data-a="fit" title="Fit to screen (0)" id="vw-pct">100%</button>
          <button class="vw-btn" data-a="in" title="Zoom in (+)">${icon("zoomIn")}</button>
          <button class="vw-btn" data-a="rot" title="Rotate (R)">${icon("rotate")}</button></span>
        <span class="vw-group">
          <button class="vw-btn" data-a="tab" title="Open in a new tab">${icon("external")}<span>Open</span></button>
          <button class="vw-btn" data-a="print" title="Print">${icon("printer")}<span>Print</span></button>
          <button class="vw-btn" data-a="link" title="Copy a link to this ticket's files (sign-in required)">${icon("link")}<span>Copy link</span></button>
          <button class="vw-btn primary" data-a="dl" title="Download">${icon("download")}<span>Download</span></button>
          ${canDelete ? html`<button class="vw-btn danger" data-a="del" title="Delete this file (IT only)">${icon("trash")}</button>` : ""}</span>
        <button class="vw-btn" data-a="close" title="Close (Esc)" aria-label="Close">${icon("x")}</button>
      </div>
    </div>
    <div class="vw-main">
      <button class="vw-nav prev" data-a="prev" aria-label="Previous file">${icon("chevLeft")}</button>
      <div class="vw-stage" id="vw-stage"></div>
      <button class="vw-nav next" data-a="next" aria-label="Next file">${icon("chevRight")}</button>
    </div>
    <div class="vw-strip" id="vw-strip"></div>`);
  document.body.appendChild(wrap);
  document.body.classList.add("vw-open");
  const stage = $("#vw-stage", wrap);

  const zoomable = () => isImage(cur) || isPdf(cur);
  let zoomTimer;
  const zoomSoon = () => { clearTimeout(zoomTimer); zoomTimer = setTimeout(applyZoom, pdf ? 120 : 0); };

  function close() {
    if (url) URL.revokeObjectURL(url);
    pdf?.destroy?.();
    wrap.remove();
    document.body.classList.remove("vw-open");
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", zoomSoon);
  }

  function strip() {
    const s = $("#vw-strip", wrap);
    s.hidden = files.length < 2;
    mount(s, html`${files.map((a, k) => html`<button class="vw-thumb ${k === i ? "on" : ""}" data-k="${k}" title="${a.original_name}">
      <span class="vw-thumb-box" data-thumb="${a.id}">${icon(isPdf(a) ? "file" : "image")}</span>
      <span class="vw-thumb-name">${a.original_name}</span></button>`)}`);
    loadThumbs(s, number, files);
    $$(".vw-thumb", s).forEach((b) => b.addEventListener("click", () => show(Number(b.dataset.k))));
    s.querySelector(".on")?.scrollIntoView({ block: "nearest", inline: "center" });
  }

  function applyZoom() {
    $("#vw-pct", wrap).textContent = `${Math.round(zoom * 100)}%`;
    if (pdf) return renderPdf();
    const img = $("img", stage);
    if (!img || !nat) return;
    const turned = rot % 180 !== 0;
    const w = turned ? nat.h : nat.w, h = turned ? nat.w : nat.h;
    const fit = Math.min((stage.clientWidth - 32) / w, (stage.clientHeight - 32) / h, 1);
    const s = fit * zoom;
    // the box takes the rotated size so scrolling works; the image inside is rotated around its centre
    const box = img.parentElement;
    box.style.width = `${w * s}px`;
    box.style.height = `${h * s}px`;
    img.style.width = `${nat.w * s}px`;
    img.style.height = `${nat.h * s}px`;
    img.style.transform = `translate(-50%, -50%) rotate(${rot}deg)`;
    stage.classList.toggle("zoomed", zoom > 1);
  }

  async function show(k) {
    i = (k + files.length) % files.length;
    cur = files[i];
    zoom = 1; rot = 0; nat = null;
    if (pdf) { pdf.destroy?.(); pdf = null; }
    if (url) { URL.revokeObjectURL(url); url = null; }
    $("#vw-name", wrap).textContent = cur.original_name;
    $("#vw-meta", wrap).textContent = [fileSize(cur.size_bytes), nameIdText(cur.uploader), fmtDate(cur.created_at),
      cur.is_internal ? "Internal (IT only)" : "", files.length > 1 ? `${i + 1} of ${files.length}` : ""].filter(Boolean).join("  ·  ");
    mount($("#vw-ic", wrap), html`${icon(isPdf(cur) ? "file" : "image")}`);
    $("#vw-zoom", wrap).hidden = !(isImage(cur) || isPdf(cur));
    $$(".vw-nav", wrap).forEach((b) => { b.hidden = files.length < 2; });
    $("[data-a=print]", wrap).hidden = !(isImage(cur) || isPdf(cur));
    mount(stage, html`<div class="vw-loading"><span class="spinner"></span>Opening ${cur.original_name}…</div>`);
    strip();
    const want = cur;
    let blob;
    try { blob = await fileBlob(number, cur); } catch (e) {
      if (want !== cur) return;
      mount(stage, html`<div class="vw-msg">${icon("alert")}<b>Couldn't open this file.</b><span>${e.message || "Please try again."}</span></div>`);
      return;
    }
    if (want !== cur) return;   // the user moved on while it was loading
    url = URL.createObjectURL(blob);
    if (isImage(cur)) {
      mount(stage, html`<div class="vw-imgbox"><img alt="${cur.original_name}" draggable="false"></div>`);
      const img = $("img", stage);
      img.onload = () => { nat = { w: img.naturalWidth, h: img.naturalHeight }; applyZoom(); };
      img.src = url;
      img.addEventListener("dblclick", () => { zoom = zoom > 1 ? 1 : 2; applyZoom(); });
    } else if (isPdf(cur)) {
      try {
        const lib = await pdfjs();
        const doc = await lib.getDocument({ data: new Uint8Array(await blob.arrayBuffer()), isEvalSupported: false,
          standardFontDataUrl: PDFJS + "standard_fonts/", cMapUrl: PDFJS + "cmaps/", cMapPacked: true }).promise;
        if (want !== cur) { doc.destroy(); return; }
        pdf = doc;
        $("#vw-meta", wrap).textContent += `  ·  ${doc.numPages} page${doc.numPages === 1 ? "" : "s"}`;
        mount(stage, html`<div class="vw-pages"></div>`);
        renderPdf();
      } catch (e) {
        if (want !== cur) return;
        mount(stage, html`<div class="vw-msg">${icon("file")}<b>This PDF can't be shown here</b>
          <span>It may be damaged or password-protected. Download it or open it in a new tab.</span>
          <button class="btn primary" data-a="dl">${icon("download")} Download</button></div>`);
      }
    } else {
      mount(stage, html`<div class="vw-msg">${icon("file")}<b>No preview for this file type</b>
        <span>${cur.original_name} can't be shown in the browser (for example iPhone HEIC photos). Download it to open it.</span>
        <button class="btn primary" data-a="dl">${icon("download")} Download</button></div>`);
    }
  }

  // Draw every page (sharp on high-resolution screens); placeholders keep the layout steady while drawing
  async function renderPdf() {
    const seq = ++renderSeq, doc = pdf, box = $(".vw-pages", stage);
    if (!doc || !box) return;
    const first = await doc.getPage(1);
    const base = first.getViewport({ scale: 1, rotation: rot });
    const fitW = Math.max(200, Math.min(stage.clientWidth - 40, 1100));
    const scale = (fitW / base.width) * zoom;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    box.replaceChildren();
    const canvases = [];
    for (let n = 1; n <= doc.numPages; n++) {
      const c = document.createElement("canvas");
      c.className = "vw-page";
      c.style.width = `${base.width * scale}px`;
      c.style.height = `${base.height * scale}px`;
      box.appendChild(c);
      canvases.push(c);
    }
    stage.classList.toggle("zoomed", zoom > 1);
    for (let n = 1; n <= doc.numPages; n++) {
      if (seq !== renderSeq || pdf !== doc) return;   // zoom/rotate/next file started a new drawing
      const page = n === 1 ? first : await doc.getPage(n);
      const vp = page.getViewport({ scale: scale * dpr, rotation: rot });
      const c = canvases[n - 1];
      c.width = vp.width; c.height = vp.height;
      c.style.width = `${vp.width / dpr}px`; c.style.height = `${vp.height / dpr}px`;
      await page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise.catch(() => {});
    }
  }

  async function printIt() {
    if (!url) return;
    let pages;
    if (isPdf(cur) && pdf) {
      toast("Preparing pages for printing…");
      pages = [];
      for (let n = 1; n <= pdf.numPages; n++) {
        const page = await pdf.getPage(n);
        const vp = page.getViewport({ scale: 2, rotation: rot });
        const c = document.createElement("canvas");
        c.width = vp.width; c.height = vp.height;
        await page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise;
        pages.push(c.toDataURL("image/jpeg", 0.92));
      }
    } else pages = [url];
    const fr = document.createElement("iframe");
    fr.className = "vw-print-frame";
    fr.srcdoc = `<!doctype html><title>${cur.original_name.replace(/</g, "&lt;")}</title>
      <style>@page{margin:10mm}html,body{margin:0}img{display:block;margin:0 auto;max-width:100%;max-height:100vh;page-break-after:always;break-after:page}
      img:last-child{page-break-after:auto;break-after:auto}${isImage(cur) && rot ? `img{transform:rotate(${rot}deg)}` : ""}</style>
      ${pages.map((s) => `<img src="${s}">`).join("")}`;
    fr.onload = () => {
      setTimeout(() => {
        try { fr.contentWindow.focus(); fr.contentWindow.print(); }
        catch { window.open(url, "_blank"); }
        setTimeout(() => fr.remove(), 60000);
      }, 300);
    };
    document.body.appendChild(fr);
  }

  async function act(a) {
    if (a === "close") return close();
    if (a === "prev") return show(i - 1);
    if (a === "next") return show(i + 1);
    if (a === "in") { zoom = Math.min(6, +(zoom * 1.25).toFixed(3)); $("#vw-pct", wrap).textContent = `${Math.round(zoom * 100)}%`; return zoomSoon(); }
    if (a === "out") { zoom = Math.max(0.25, +(zoom / 1.25).toFixed(3)); $("#vw-pct", wrap).textContent = `${Math.round(zoom * 100)}%`; return zoomSoon(); }
    if (a === "fit") { zoom = 1; return zoomSoon(); }
    if (a === "rot") { rot = (rot + 90) % 360; return zoomSoon(); }
    if (a === "dl") return downloadFile(number, cur);
    if (a === "print") return printIt();
    if (a === "tab") {
      if (!url) return;
      const w = window.open(url, "_blank");
      if (!w) toast("Your browser blocked the new tab — allow pop-ups for this site.", "err");
      return;
    }
    if (a === "link") {
      const link = `${location.origin}${location.pathname}#/tickets/${number}/files`;
      try { await navigator.clipboard.writeText(link); toast("Link copied. It opens this ticket's files after signing in."); }
      catch { toast(link); }
      return;
    }
    if (a === "del") {
      const ok = await confirmDialog({ title: "Delete this file?", danger: true, confirmText: "Delete file",
        message: `“${cur.original_name}” will be removed from ${number} for everyone. This cannot be undone.` });
      if (!ok) return;
      try {
        await api.del(`/tickets/${number}/attachments/${cur.id}`);
        blobs.delete(`${number}:${cur.id}`);
        files = files.filter((x) => x !== cur);
        toast("File deleted.");
        onDeleted?.();
        if (!files.length) return close();
        show(Math.min(i, files.length - 1));
      } catch (e) { errorToast(e); }
    }
  }

  wrap.addEventListener("click", (e) => {
    const b = e.target.closest("[data-a]");
    if (b) act(b.dataset.a);
    else if (e.target === stage || e.target.classList?.contains("vw-main")) close();
  });
  stage.addEventListener("wheel", (e) => {
    if (!zoomable() || !(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    act(e.deltaY < 0 ? "in" : "out");
  }, { passive: false });
  const onKey = (e) => {
    if (document.querySelector(".modal-backdrop")) return;   // a confirm dialog is open on top
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft" && files.length > 1) show(i - 1);
    else if (e.key === "ArrowRight" && files.length > 1) show(i + 1);
    else if (zoomable() && (e.key === "+" || e.key === "=")) act("in");
    else if (zoomable() && e.key === "-") act("out");
    else if (zoomable() && e.key === "0") act("fit");
    else if (zoomable() && (e.key === "r" || e.key === "R")) act("rot");
  };
  document.addEventListener("keydown", onKey);
  window.addEventListener("resize", zoomSoon);
  show(i);
  return { close };
}
