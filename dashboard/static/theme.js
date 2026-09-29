"use strict";

const themeStorageKey = "dashboard-theme";

function applyTheme(theme, save = false) {
  const light = theme === "light";
  document.documentElement.dataset.theme = light ? "light" : "dark";
  document.querySelector('meta[name="theme-color"]').content = light ? "#ffffff" : "#0b1018";
  const toggle = document.getElementById("theme-toggle");
  if (toggle) {
    const label = light ? "Включить тёмную тему" : "Включить светлую тему";
    toggle.setAttribute("aria-label", label);
    toggle.title = label;
  }
  if (save) {
    try { localStorage.setItem(themeStorageKey, light ? "light" : "dark"); } catch (_) {}
  }
}

let savedTheme = "dark";
try {
  if (localStorage.getItem(themeStorageKey) === "light") savedTheme = "light";
} catch (_) {}
applyTheme(savedTheme);

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(document.documentElement.dataset.theme);
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light", true);
  });
});
