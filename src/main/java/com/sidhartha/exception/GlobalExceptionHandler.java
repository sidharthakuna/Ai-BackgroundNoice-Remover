package com.sidhartha.exception;

import com.sidhartha.dto.ErrorResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.task.TaskRejectedException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(AudioProcessingException.class)
    public ResponseEntity<ErrorResponse> handleAudioProcessing(AudioProcessingException e) {
        if (e.getStatus().is5xxServerError()) {
            log.error("Audio processing failure", e);
        } else {
            log.info("Audio processing rejected: {}", e.getMessage());
        }
        return ResponseEntity.status(e.getStatus())
                .body(ErrorResponse.of("audio_processing_failed", e.getMessage(), e.getStatus().value()));
    }

    @ExceptionHandler(TaskRejectedException.class)
    public ResponseEntity<ErrorResponse> handleTaskRejected(TaskRejectedException e) {
        log.warn("Server task queue full, rejected async job: {}", e.getMessage());
        return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS)
                .header("Retry-After", "5")
                .body(ErrorResponse.of("server_busy",
                        "The server is currently processing maximum concurrent audio jobs. Please try again in a moment.",
                        HttpStatus.TOO_MANY_REQUESTS.value()));
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<ErrorResponse> handleTooLarge(MaxUploadSizeExceededException e) {
        return ResponseEntity.status(HttpStatus.PAYLOAD_TOO_LARGE)
                .body(ErrorResponse.of("file_too_large",
                        "The uploaded file is too large. Maximum allowed size is 100MB.",
                        HttpStatus.PAYLOAD_TOO_LARGE.value()));
    }

    @ExceptionHandler({MissingServletRequestPartException.class, MissingServletRequestParameterException.class, IllegalArgumentException.class})
    public ResponseEntity<ErrorResponse> handleMissingParam(Exception e) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(ErrorResponse.of("bad_request", e.getMessage(), HttpStatus.BAD_REQUEST.value()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleUnexpected(Exception e) {
        log.error("Unhandled exception", e);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ErrorResponse.of("internal_error",
                        "Something went wrong while processing your request.",
                        HttpStatus.INTERNAL_SERVER_ERROR.value()));
    }
}