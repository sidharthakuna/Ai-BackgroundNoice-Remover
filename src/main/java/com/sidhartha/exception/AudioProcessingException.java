package com.sidhartha.exception;

import org.springframework.http.HttpStatus;

/**
 * Thrown for any failure in the audio pipeline (bad file, unsupported
 * format, script crash, conversion failure, etc). Carries an HTTP status
 * so the GlobalExceptionHandler can return the right response code instead
 * of a blanket 500.
 */
public class AudioProcessingException extends RuntimeException {

    private final HttpStatus status;

    public AudioProcessingException(String message, HttpStatus status) {
        super(message);
        this.status = status;
    }

    public AudioProcessingException(String message, HttpStatus status, Throwable cause) {
        super(message, cause);
        this.status = status;
    }

    public HttpStatus getStatus() {
        return status;
    }
}