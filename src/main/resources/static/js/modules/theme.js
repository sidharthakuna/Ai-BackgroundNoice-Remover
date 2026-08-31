// ============================================================================
// theme.js — dark/light theme init, toggle, and persistence.
// ============================================================================

import { THEME_STORAGE_KEY } from "./constants.js";
import { redrawAllWaveforms } from "./waveform.js";

/**
 * Wires up a theme toggle button and applies the saved/preferred theme on load.
 * @param {HTMLElement} toggleEl
 */
export function initTheme(toggleEl) {
    if (!toggleEl) return;
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)").matches;
    const initialTheme = document.documentElement.getAttribute("data-theme") === "light"
        ? "light"
        : (saved || (prefersLight ? "light" : "dark"));
    applyTheme(initialTheme, toggleEl, false);

    toggleEl.addEventListener("click", () => {
        const isLight = document.documentElement.getAttribute("data-theme") === "light";
        applyTheme(isLight ? "dark" : "light", toggleEl, true);
    });
}

function applyTheme(theme, toggleEl, shouldRedraw = false) {
    if (theme === "light") {
        document.documentElement.setAttribute("data-theme", "light");
        if (toggleEl) {
            toggleEl.setAttribute("aria-pressed", "true");
            toggleEl.setAttribute("aria-label", "Switch to dark theme");
        }
    } else {
        document.documentElement.removeAttribute("data-theme");
        if (toggleEl) {
            toggleEl.setAttribute("aria-pressed", "false");
            toggleEl.setAttribute("aria-label", "Switch to light theme");
        }
    }
    localStorage.setItem(THEME_STORAGE_KEY, theme);
    if (shouldRedraw) {
        // Allow DOM styles to update before redrawing
        requestAnimationFrame(() => redrawAllWaveforms());
    }
}