// ============================================================================
// main.js — composition root. Grabs DOM refs, wires modules together,
// owns nothing but the glue. Each module above is independently testable;
// this file is the only place that knows how they fit into this one page.
// ============================================================================

import { appState } from "./modules/state.js";
import { initTheme } from "./modules/theme.js";
import { validateFile } from "./modules/validation.js";
import { initDropZone, initMicRecorder } from "./modules/dropzone.js";
import { renderFileItem, updateEmptyStates } from "./modules/fileList.js";
import { createProcessingQueue } from "./modules/processing.js";
import { buildHistoryItem, renderHistoryItem } from "./modules/history.js";

// ── DOM refs ────────────────────────────────────────────────────────

const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const recordMicBtn = document.getElementById("recordMicBtn");
const recordingPanel = document.getElementById("recordingPanel");
const stopRecordBtn = document.getElementById("stopRecordBtn");
const cancelRecordBtn = document.getElementById("cancelRecordBtn");
const recordingTimer = document.getElementById("recordingTimer");

const fileList = document.getElementById("fileList");
const fileListEmpty = document.getElementById("fileListEmpty");
const processAllBtn = document.getElementById("processAllBtn");
const clearAllBtn = document.getElementById("clearAllBtn");
const demucsToggle = document.getElementById("demucsToggle");
const modeSelect = document.getElementById("modeSelect");
const formatSelect = document.getElementById("formatSelect");
const themeToggle = document.getElementById("themeToggle");

const historyList = document.getElementById("historyList");
const historyEmpty = document.getElementById("historyEmpty");
const historyCount = document.getElementById("historyCount");
const clearHistoryBtn = document.getElementById("clearHistoryBtn");

const fileItemTemplate = document.getElementById("fileItemTemplate");
const historyItemTemplate = document.getElementById("historyItemTemplate");

// ── Theme ───────────────────────────────────────────────────────────

initTheme(themeToggle);

// ── Empty-state + action-button sync ───────────────────────────────

function refreshChrome() {
    updateEmptyStates({
        fileListEmptyEl: fileListEmpty,
        historyEmptyEl: historyEmpty,
        clearHistoryBtnEl: clearHistoryBtn,
        filesSize: appState.size,
        historyLength: appState.history.length,
    });

    const hasFiles = appState.size > 0;
    const hasPending = appState.values().some((e) => e.status === "pending" || e.status === "error");
    const anyProcessing = appState.values().some((e) => e.status === "processing");

    clearAllBtn.disabled = !hasFiles || anyProcessing;
    processAllBtn.disabled = !hasPending || anyProcessing;
    processAllBtn.querySelector(".btn-label").textContent = anyProcessing ? "Processing…" : "Enhance Audio";
}

// ── Adding / removing files ────────────────────────────────────────

function addFiles(files) {
    const errors = [];

    for (const file of files) {
        const validationError = validateFile(file);
        if (validationError) {
            errors.push(validationError);
            continue;
        }

        const entry = appState.createEntry(file, {
            useDemucs: demucsToggle.checked,
            mode: modeSelect ? modeSelect.value : "balanced",
            format: formatSelect.value,
        });

        renderFileItem(entry, fileItemTemplate, fileList, {
            onRemove: removeFile,
            onOptionsChange: () => {}, // per-file meta already updates itself
        });
    }

    if (errors.length) {
        // Surface validation problems cleanly with a toast banner without blocking UI
        errors.forEach((err) => showToast(err, "error"));
    }

    refreshChrome();
}

function showToast(message, type = "info") {
    let container = document.querySelector(".toast-container");
    if (!container) {
        container = document.createElement("div");
        container.className = "toast-container";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3.5 21.5 20h-19L12 3.5Z"/>
            <path d="M12 9.5v4.25M12 16.9v.1"/>
        </svg>
        <div class="toast-content">${message}</div>
    `;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = "toast-out 0.2s ease forwards";
        setTimeout(() => toast.remove(), 200);
    }, 4500);
}

function removeFile(id) {
    appState.remove(id);
    refreshChrome();
}

clearAllBtn.addEventListener("click", () => {
    appState.clearAllFiles();
    refreshChrome();
});

// ── Drop zone & Mic Recorder ────────────────────────────────────────

initDropZone(dropZone, fileInput, addFiles);

initMicRecorder({
    recordBtn: recordMicBtn,
    panel: recordingPanel,
    stopBtn: stopRecordBtn,
    cancelBtn: cancelRecordBtn,
    timerEl: recordingTimer,
    onRecorded: addFiles,
});


// ── Processing ──────────────────────────────────────────────────────

const processingQueue = createProcessingQueue(appState, {
    onQueueChange: refreshChrome,
    onEntryDone: (entry, outName) => {
        const item = buildHistoryItem(entry, outName);
        appState.addHistoryItem(item);
        renderHistoryItem(item, historyItemTemplate, historyList);
        historyCount.textContent = `(${appState.history.length})`;
        refreshChrome();
    },
});

processAllBtn.addEventListener("click", () => {
    const pending = appState.values().filter((e) => e.status === "pending" || e.status === "error");
    pending.forEach((entry) => processingQueue.queueProcessing(entry));
});

// ── History ─────────────────────────────────────────────────────────

clearHistoryBtn.addEventListener("click", () => {
    appState.clearHistory();
    historyList.innerHTML = "";
    historyCount.textContent = "(0)";
    refreshChrome();
});

// ── Initial paint ──────────────────────────────────────────────────

refreshChrome();