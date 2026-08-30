// ============================================================================
// fileList.js — renders FileEntry objects into the DOM and keeps their
// per-item chrome (badge, meta line, per-file options) in sync with state.
// ============================================================================

import { formatBytes } from "./format.js";

const STATUS_LABELS = { pending: "Ready", processing: "Processing", done: "Done", error: "Failed" };

/**
 * @param {import('./state.js').FileEntry} entry
 * @param {HTMLTemplateElement} template
 * @param {HTMLElement} listContainer
 * @param {{onRemove: (id: string) => void, onOptionsChange: (id: string) => void}} handlers
 */
export function renderFileItem(entry, template, listContainer, handlers) {
    const node = template.content.firstElementChild.cloneNode(true);
    entry.listEl = node;

    node.querySelector(".file-item-name").textContent = entry.file.name;
    updateFileMeta(entry);

    // Per-file overrides: a batch can mix "vocal isolation on for this one
    // interview clip, off for the rest" without re-touching the global
    // toggle for every add. Defaults to the global option's value at
    // add-time, then travels with the entry from there.
    const demucsCheckbox = node.querySelector(".file-item-demucs");
    const formatSelect = node.querySelector(".file-item-format");
    const modeSelect = node.querySelector(".file-item-mode");
    if (demucsCheckbox) demucsCheckbox.checked = entry.useDemucs;
    if (formatSelect) formatSelect.value = entry.format;
    if (modeSelect) modeSelect.value = entry.mode || "balanced";

    if (demucsCheckbox) {
        demucsCheckbox.addEventListener("change", () => {
            entry.useDemucs = demucsCheckbox.checked;
            updateFileMeta(entry);
            handlers.onOptionsChange(entry.id);
        });
    }
    if (formatSelect) {
        formatSelect.addEventListener("change", () => {
            entry.format = formatSelect.value;
            updateFileMeta(entry);
            handlers.onOptionsChange(entry.id);
        });
    }
    if (modeSelect) {
        modeSelect.addEventListener("change", () => {
            entry.mode = modeSelect.value;
            updateFileMeta(entry);
            handlers.onOptionsChange(entry.id);
        });
    }

    node.querySelector(".file-item-remove").addEventListener("click", () => handlers.onRemove(entry.id));

    listContainer.appendChild(node);
    updateStatusBadge(entry);
    return node;
}

export function updateFileMeta(entry) {
    if (!entry.listEl) return;
    const modeLabel = entry.mode ? ` · ${entry.mode.charAt(0).toUpperCase() + entry.mode.slice(1)}` : "";
    entry.listEl.querySelector(".file-item-meta").textContent =
        `${formatBytes(entry.file.size)} · ${entry.format.toUpperCase()}${modeLabel}${entry.useDemucs ? " · Vocal isolation" : ""}`;
}

export function updateStatusBadge(entry) {
    const badge = entry.listEl.querySelector(".status-badge");
    badge.className = `status-badge status-badge-${entry.status}`;
    badge.textContent = STATUS_LABELS[entry.status] || entry.status;
    entry.listEl.dataset.status = entry.status;

    // Lock per-file options once a file leaves "pending" — editing format
    // mid-upload (or after) would silently disagree with what was sent.
    const isEditable = entry.status === "pending" || entry.status === "error";
    const demucsCheckbox = entry.listEl.querySelector(".file-item-demucs");
    const formatSelect = entry.listEl.querySelector(".file-item-format");
    const modeSelect = entry.listEl.querySelector(".file-item-mode");
    if (demucsCheckbox) demucsCheckbox.disabled = !isEditable;
    if (formatSelect) formatSelect.disabled = !isEditable;
    if (modeSelect) modeSelect.disabled = !isEditable;
}

export function updateEmptyStates({ fileListEmptyEl, historyEmptyEl, clearHistoryBtnEl, filesSize, historyLength }) {
    fileListEmptyEl.hidden = filesSize > 0;
    historyEmptyEl.hidden = historyLength > 0;
    clearHistoryBtnEl.hidden = historyLength === 0;
}