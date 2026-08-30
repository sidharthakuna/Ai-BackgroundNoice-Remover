package com.sidhartha.media;

import com.sidhartha.exception.AudioProcessingException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

import static org.junit.jupiter.api.Assertions.*;

class UploadValidatorTest {

    private UploadValidator validator;

    @BeforeEach
    void setUp() {
        validator = new UploadValidator();
    }

    @Test
    void extractAndValidateExtension_validAudio_returnsExtension() {
        assertEquals("mp3", validator.extractAndValidateExtension("track.mp3"));
        assertEquals("wav", validator.extractAndValidateExtension("sample.WAV"));
        assertEquals("flac", validator.extractAndValidateExtension("audio.file.flac"));
        assertEquals("ogg", validator.extractAndValidateExtension("voice.ogg"));
        assertEquals("m4a", validator.extractAndValidateExtension("record.m4a"));
        assertEquals("opus", validator.extractAndValidateExtension("note.opus"));
    }

    @Test
    void extractAndValidateExtension_validVideo_returnsExtension() {
        assertEquals("mp4", validator.extractAndValidateExtension("clip.mp4"));
        assertEquals("mov", validator.extractAndValidateExtension("video.MOV"));
        assertEquals("webm", validator.extractAndValidateExtension("capture.webm"));
        assertEquals("mkv", validator.extractAndValidateExtension("movie.mkv"));
    }

    @Test
    void extractAndValidateExtension_invalidOrEmpty_throwsException() {
        AudioProcessingException ex1 = assertThrows(AudioProcessingException.class,
                () -> validator.extractAndValidateExtension(""));
        assertEquals(HttpStatus.BAD_REQUEST, ex1.getStatus());

        AudioProcessingException ex2 = assertThrows(AudioProcessingException.class,
                () -> validator.extractAndValidateExtension("filename_without_extension"));
        assertEquals(HttpStatus.BAD_REQUEST, ex2.getStatus());

        AudioProcessingException ex3 = assertThrows(AudioProcessingException.class,
                () -> validator.extractAndValidateExtension("document.pdf"));
        assertEquals(HttpStatus.BAD_REQUEST, ex3.getStatus());
        assertTrue(ex3.getMessage().contains("Unsupported file type '.pdf'"));
    }

    @Test
    void normalizeOutputFormat_valid_returnsFormat() {
        assertEquals("wav", validator.normalizeOutputFormat(null));
        assertEquals("wav", validator.normalizeOutputFormat(""));
        assertEquals("wav", validator.normalizeOutputFormat("  "));
        assertEquals("mp3", validator.normalizeOutputFormat("mp3"));
        assertEquals("flac", validator.normalizeOutputFormat(" FLAC "));
        assertEquals("ogg", validator.normalizeOutputFormat("ogg"));
    }

    @Test
    void normalizeOutputFormat_invalid_throwsException() {
        assertThrows(AudioProcessingException.class,
                () -> validator.normalizeOutputFormat("wma"));
        assertThrows(AudioProcessingException.class,
                () -> validator.normalizeOutputFormat("exe"));
    }

    @Test
    void normalizeMode_valid_returnsMode() {
        assertEquals("balanced", validator.normalizeMode(null));
        assertEquals("balanced", validator.normalizeMode(""));
        assertEquals("aggressive", validator.normalizeMode("AGGRESSIVE"));
        assertEquals("gentle", validator.normalizeMode(" gentle "));
    }

    @Test
    void normalizeMode_invalid_throwsException() {
        assertThrows(AudioProcessingException.class,
                () -> validator.normalizeMode("extreme"));
    }

    @Test
    void extractAndValidateExtension_additionalFormats_returnsExtension() {
        assertEquals("aiff", validator.extractAndValidateExtension("track.AIFF"));
        assertEquals("aif", validator.extractAndValidateExtension("sample.aif"));
        assertEquals("aac", validator.extractAndValidateExtension("audio.aac"));
    }

    @Test
    void sanitizeFilename_cleansPathsAndControlCharacters() {
        assertEquals("track.mp3", validator.sanitizeFilename("../../etc/passwd/track.mp3"));
        assertEquals("sample.wav", validator.sanitizeFilename("..\\..\\Windows\\System32\\sample.wav"));
        assertEquals("audio.flac", validator.sanitizeFilename("audio\u0000\r\n.flac"));
        assertEquals("audio_file.wav", validator.sanitizeFilename(""));
        assertEquals("audio_file.wav", validator.sanitizeFilename(".."));
    }

    @Test
    void isVideoExtension_checksProperly() {
        assertTrue(validator.isVideoExtension("mp4"));
        assertTrue(validator.isVideoExtension("mov"));
        assertTrue(validator.isVideoExtension("webm"));
        assertTrue(validator.isVideoExtension("mkv"));
        assertTrue(validator.isVideoExtension("avi"));
        assertFalse(validator.isVideoExtension("wav"));
        assertFalse(validator.isVideoExtension("mp3"));
    }
}
