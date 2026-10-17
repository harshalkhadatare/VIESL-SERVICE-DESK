// Applies the saved theme before first paint to avoid a flash. External file so CSP can forbid inline scripts.
(function () {
  try {
    var t = localStorage.getItem("sd-theme");
    if (!t) t = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", t);
  } catch (e) { /* storage unavailable: keep light */ }
})();
