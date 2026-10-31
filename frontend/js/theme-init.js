// Applies the saved colour theme before the page paints (no flash). Kept tiny and non-module on purpose.
(function () {
  var a = "ocean", m = "light";
  try { a = localStorage.getItem("sd-accent") || a; m = localStorage.getItem("sd-mode") || m; } catch (e) { /* storage blocked */ }
  if (m === "system") m = window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  var d = document.documentElement;
  d.setAttribute("data-accent", a);
  d.setAttribute("data-mode", m);
})();
