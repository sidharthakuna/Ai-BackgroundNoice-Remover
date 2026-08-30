// ============================================================================
// history.js — renders the session history list. History is in-memory only
// (blob URLs die on reload), which the empty-state copy is upfront about.
// ============================================================================

import { formatBytes } from "./format.js";

/**
 * @param {import('./state.js').FileEntry} entry
 * @param {string} outName
 * @returns {{name: string, meta: string, url: string}}
 */
export function buildHistoryItem(entry, outName) {
    return {
        name: outName,
        meta: `${entry.format.toUpperCase()} · ${formatBytes(entry.resultBlob.size)}${entry.useDemucs ? " · Vocals isolated" : ""} · ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
        url: entry.resultUrl,
    };
}

/**
 * @param {{name: string, meta: string, url: string}} item
 * @param {HTMLTemplateElement} template
 * @param {HTMLElement} listContainer
 */
export function renderHistoryItem(item, template, listContainer) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector(".history-item-name").textContent = item.name;
    node.querySelector(".history-item-meta").textContent = item.meta;
    const link = node.querySelector(".download-link");
    link.href = item.url;
    link.download = item.name;
    listContainer.prepend(node);
    return node;
}