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
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)").matches;
    const theme = saved || (prefersLight ? "light" : "dark");
    applyTheme(theme, toggleEl, false);

    toggleEl.addEventListener("click", () => {
        const isLight = document.documentElement.getAttribute("data-theme") === "light";
        applyTheme(isLight ? "dark" : "light", toggleEl, true);
    });
}

function applyTheme(theme, toggleEl, shouldRedraw = false) {
    if (theme === "light") {
        document.documentElement.setAttribute("data-theme", "light");
        toggleEl.setAttribute("aria-pressed", "true");
        toggleEl.setAttribute("aria-label", "Switch to dark theme");
    } else {
        document.documentElement.removeAttribute("data-theme");
        toggleEl.setAttribute("aria-pressed", "false");
        toggleEl.setAttribute("aria-label", "Switch to light theme");
    }
    localStorage.setItem(THEME_STORAGE_KEY, theme);
    if (shouldRedraw) {
        // Allow DOM styles to update before redrawing
        requestAnimationFrame(() => redrawAllWaveforms());
    }
}