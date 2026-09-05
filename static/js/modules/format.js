// ============================================================================
// format.js — pure display-formatting helpers. No DOM, no state.
// ============================================================================

export function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatElapsed(seconds) {
    if (seconds < 60) return `${seconds}s`;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}m ${s}s`;
}

export function withExtension(originalName, format) {
    const dot = originalName.lastIndexOf(".");
    const base = dot > 0 ? originalName.slice(0, dot) : originalName;
    return `${base}-enhanced.${format}`;
}

export function getExtension(filename) {
    const dot = filename.lastIndexOf(".");
    if (dot < 0 || dot === filename.length - 1) return "";
    return filename.slice(dot + 1).toLowerCase();
}