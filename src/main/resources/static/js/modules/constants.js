// ============================================================================
// constants.js — shared configuration. Single source of truth so limits
// (file size, extension list, concurrency) don't drift between modules.
// ============================================================================

export const API_BASE = (typeof window !== "undefined" && (window.location.protocol === "file:" || !window.location.host))
    ? "http://localhost:8080"
    : "";

export const API_ENDPOINT = `${API_BASE}/api/v1/audio/enhance`;
export const MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024; // 100MB — matches server multipart limit
export const SUPPORTED_EXTENSIONS = ["mp3", "wav", "m4a", "flac", "ogg", "aac", "wma", "opus"];
// Video containers: the server extracts the audio track via ffmpeg before
// denoise.py ever sees the file (see NoiseRemovalService.extractAudioFromVideo).
// Kept as a separate list rather than merged into SUPPORTED_EXTENSIONS so
// validation.js can give a distinct, accurate message per file type instead
// of implying every one of these is decoded directly.
export const SUPPORTED_VIDEO_EXTENSIONS = ["mp4", "mov", "mkv", "webm"];
export const ENHANCEMENT_MODES = ["balanced", "aggressive", "gentle"];
export const DEFAULT_MODE = "balanced";
export const MAX_CONCURRENT_UPLOADS = 2;
export const THEME_STORAGE_KEY = "noise-remover-theme";