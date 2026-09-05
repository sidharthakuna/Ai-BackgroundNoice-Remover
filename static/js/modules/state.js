// ============================================================================
// state.js — the single source of truth for in-flight files and completed
// history. Other modules read/mutate through this object rather than
// holding their own copies, so there's one place that knows what's true.
// ============================================================================

/**
 * @typedef {Object} FileEntry
 * @property {string} id
 * @property {File} file
 * @property {'pending'|'processing'|'done'|'error'} status
 * @property {boolean} useDemucs
 * @property {string} format
 * @property {string} mode
 * @property {XMLHttpRequest|null} xhr
 * @property {number|null} startTime
 * @property {number|null} timerHandle
 * @property {Blob|null} resultBlob
 * @property {string|null} resultUrl
 * @property {string|null} errorMessage
 * @property {HTMLElement|null} listEl
 */

class AppState {
    constructor() {
        /** @type {Map<string, FileEntry>} */
        this.files = new Map();
        this.nextFileId = 1;
        this.activeUploads = 0;
        this.uploadQueue = [];
        /** @type {Array<{name: string, meta: string, url: string}>} */
        this.history = [];
    }

    createEntry(file, defaults) {
        const id = `f${this.nextFileId++}`;
        /** @type {FileEntry} */
        const entry = {
            id,
            file,
            status: "pending",
            useDemucs: defaults.useDemucs,
            mode: defaults.mode || "balanced",
            format: defaults.format,
            jobId: null,
            xhr: null,
            startTime: null,
            timerHandle: null,
            resultBlob: null,
            resultUrl: null,
            errorMessage: null,
            listEl: null,
        };
        this.files.set(id, entry);
        return entry;
    }


    get(id) {
        return this.files.get(id);
    }

    remove(id) {
        const entry = this.files.get(id);
        if (!entry) return;
        if (entry.xhr) entry.xhr.abort();
        if (entry.timerHandle) clearInterval(entry.timerHandle);
        if (entry.resultUrl) URL.revokeObjectURL(entry.resultUrl);
        if (entry.jobId) {
            try {
                const xhr = new XMLHttpRequest();
                xhr.open("DELETE", `/api/v1/jobs/${entry.jobId}`);
                xhr.send();
            } catch {}
        }
        entry.listEl?.remove();
        this.files.delete(id);
    }

    clearAllFiles() {
        for (const id of Array.from(this.files.keys())) {
            this.remove(id);
        }
    }

    values() {
        return Array.from(this.files.values());
    }

    get size() {
        return this.files.size;
    }

    addHistoryItem(item) {
        this.history.unshift(item);
    }

    clearHistory() {
        this.history.length = 0;
    }
}

// One shared instance for the whole app — files/history are inherently
// singular per page load, so a module-level singleton avoids threading an
// instance through every function signature.
export const appState = new AppState();