package com.sidhartha.job;

import com.sidhartha.denoise.DenoiseProcessRunner;
import com.sidhartha.denoise.DenoiseScriptStager;
import com.sidhartha.exception.AudioProcessingException;
import com.sidhartha.media.FfmpegAudioExtractor;
import com.sidhartha.media.FfmpegFormatConverter;
import com.sidhartha.media.UploadValidator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.mock.web.MockMultipartFile;

import static org.junit.jupiter.api.Assertions.*;

class AudioJobServiceTest {

    private AudioJobService service;
    private JobStatusStore store;
    private UploadValidator validator;
    private FfmpegAudioExtractor extractor;
    private FfmpegFormatConverter converter;
    private DenoiseScriptStager stager;
    private DenoiseProcessRunner runner;

    @BeforeEach
    void setUp() {
        validator = new UploadValidator();
        store = new JobStatusStore();
        extractor = Mockito.mock(FfmpegAudioExtractor.class);
        converter = Mockito.mock(FfmpegFormatConverter.class);
        stager = Mockito.mock(DenoiseScriptStager.class);
        runner = Mockito.mock(DenoiseProcessRunner.class);

        service = new AudioJobService(validator, extractor, converter, stager, runner, store);
    }

    @Test
    void acceptAndStageJob_validAudio_createsRecord() {
        MockMultipartFile file = new MockMultipartFile(
                "file", "voice.wav", "audio/wav", "sample audio content".getBytes());

        JobRecord record = service.acceptAndStageJob(file, false, "balanced", "wav");

        assertNotNull(record);
        assertNotNull(record.getJobId());
        assertEquals("voice.wav", record.getOriginalFilename());
        assertEquals(JobStatus.QUEUED, record.getStatus());
        assertTrue(store.find(record.getJobId()).isPresent());

        // Cleanup
        service.cleanupJobRecordDir(record);
    }

    @Test
    void acceptAndStageJob_emptyFile_throwsBadRequest() {
        MockMultipartFile emptyFile = new MockMultipartFile("file", "empty.wav", "audio/wav", new byte[0]);
        assertThrows(AudioProcessingException.class, () -> service.acceptAndStageJob(emptyFile, false, "balanced", "wav"));
    }

    @Test
    void cancelJob_triggersProcessCancelAndCleansUp() {
        MockMultipartFile file = new MockMultipartFile(
                "file", "speech.mp3", "audio/mpeg", "dummy content".getBytes());

        JobRecord record = service.acceptAndStageJob(file, false, "balanced", "wav");
        String jobId = record.getJobId();

        service.cancelJob(jobId);

        Mockito.verify(runner).cancel(jobId);
        Mockito.verify(extractor).cancel(jobId);
        Mockito.verify(converter).cancel(jobId);
    }
}
