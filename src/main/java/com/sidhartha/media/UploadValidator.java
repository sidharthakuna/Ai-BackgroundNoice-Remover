package com.sidhartha.media;

import com.sidhartha.exception.AudioProcessingException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.util.Locale;
import java.util.Set;

/**
 * Validates uploaded filenames, enhancement modes, and requested output formats.
 * Includes security sanitization for incoming file names.
 */
@Component
public class UploadValidator {

    /** Extensions the Python/librosa pipeline can decode directly. */
    public static final Set<String> SUPPORTED_INPUT_EXTENSIONS =
            Set.of("mp3", "wav", "m4a", "flac", "ogg", "aac", "wma", "opus", "aiff", "aif");

    /**
     * Video containers we accept by extracting the audio track first (via ffmpeg).
     */
    public static final Set<String> SUPPORTED_VIDEO_EXTENSIONS =
            Set.of("mp4", "mov", "mkv", "webm", "avi", "m4v");

    /** Formats we know how to re-encode the WAV output into via ffmpeg. */
    public static final Set<String> SUPPORTED_OUTPUT_FORMATS =
            Set.of("wav", "mp3", "flac", "ogg", "m4a", "aac");

    /** Enhancement modes for noise cancellation strength. */
    public static final Set<String> SUPPORTED_MODES =
            Set.of("balanced", "aggressive", "gentle");

    public String extractAndValidateExtension(String originalName) {
        if (originalName == null || originalName.isBlank()) {
            throw new AudioProcessingException(
                    "The uploaded file has no name/extension, so its format can't be determined.",
                    HttpStatus.BAD_REQUEST);
        }
        String cleanName = sanitizeFilename(originalName);
        int dot = cleanName.lastIndexOf('.');
        if (dot < 0 || dot == cleanName.length() - 1) {
            throw new AudioProcessingException(
                    "The uploaded file has no file extension (e.g. .mp3, .wav). Please upload a named audio file.",
                    HttpStatus.BAD_REQUEST);
        }
        String ext = cleanName.substring(dot + 1).toLowerCase(Locale.ROOT);
        if (!SUPPORTED_INPUT_EXTENSIONS.contains(ext) && !SUPPORTED_VIDEO_EXTENSIONS.contains(ext)) {
            throw new AudioProcessingException(
                    "Unsupported file type '." + ext + "'. Supported audio: "
                            + String.join(", ", SUPPORTED_INPUT_EXTENSIONS)
                            + ". Supported video (audio track will be extracted): "
                            + String.join(", ", SUPPORTED_VIDEO_EXTENSIONS),
                    HttpStatus.BAD_REQUEST);
        }
        return ext;
    }

    public String sanitizeFilename(String filename) {
        if (filename == null || filename.isBlank()) {
            return "audio_file.wav";
        }
        // Extract base name without directory components
        String name = filename.replace('\\', '/');
        if (name.contains("/")) {
            name = name.substring(name.lastIndexOf('/') + 1);
        }
        // Strip control characters and path traversal
        name = name.replaceAll("[\\p{Cntrl}\u0000\\r\\n]", "").trim();
        name = name.replaceAll("^(\\.\\.[\\\\/])+", "");
        if (name.isBlank() || name.equals(".") || name.equals("..")) {
            return "audio_file.wav";
        }
        return name;
    }

    public String normalizeOutputFormat(String requested) {
        if (requested == null || requested.isBlank()) {
            return "wav";
        }
        String fmt = requested.trim().toLowerCase(Locale.ROOT);
        if (!SUPPORTED_OUTPUT_FORMATS.contains(fmt)) {
            throw new AudioProcessingException(
                    "Unsupported output format '" + fmt + "'. Supported: "
                            + String.join(", ", SUPPORTED_OUTPUT_FORMATS),
                    HttpStatus.BAD_REQUEST);
        }
        return fmt;
    }

    public String normalizeMode(String requested) {
        if (requested == null || requested.isBlank()) {
            return "balanced";
        }
        String m = requested.trim().toLowerCase(Locale.ROOT);
        if (!SUPPORTED_MODES.contains(m)) {
            throw new AudioProcessingException(
                    "Unsupported enhancement mode '" + m + "'. Supported: "
                            + String.join(", ", SUPPORTED_MODES),
                    HttpStatus.BAD_REQUEST);
        }
        return m;
    }

    public boolean isVideoExtension(String ext) {
        return SUPPORTED_VIDEO_EXTENSIONS.contains(ext);
    }
}