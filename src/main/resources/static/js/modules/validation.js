// ============================================================================
// validation.js — pre-flight checks on files the user selects/drops.
// ============================================================================

import { MAX_FILE_SIZE_BYTES, SUPPORTED_EXTENSIONS, SUPPORTED_VIDEO_EXTENSIONS } from "./constants.js";
import { formatBytes, getExtension } from "./format.js";

/**
 * @param {File} file
 * @returns {string|null} an error message, or null if the file is valid
 */
export function validateFile(file) {
    const ext = getExtension(file.name);
    if (!ext) {
        return `"${file.name}" has no file extension — can't tell what format it is.`;
    }
    // Video containers are accepted too — the server pulls the audio track
    // out via ffmpeg before processing, so from a validation standpoint
    // they're a distinct-but-allowed category, not "unsupported."
    const isAudio = SUPPORTED_EXTENSIONS.includes(ext);
    const isVideo = SUPPORTED_VIDEO_EXTENSIONS.includes(ext);
    if (!isAudio && !isVideo) {
        return `"${file.name}" is a .${ext} file, which isn't supported. Supported audio: ${SUPPORTED_EXTENSIONS.join(", ")}. Supported video (audio track only): ${SUPPORTED_VIDEO_EXTENSIONS.join(", ")}.`;
    }
    if (file.size === 0) {
        return `"${file.name}" is empty.`;
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
        return `"${file.name}" is ${formatBytes(file.size)}, which is over the 100MB limit.`;
    }
    return null;
}