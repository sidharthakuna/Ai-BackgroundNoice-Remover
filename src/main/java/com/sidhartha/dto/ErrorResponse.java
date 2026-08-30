package com.sidhartha.dto;

import java.time.Instant;

/**
 * Uniform JSON error body returned to the frontend so it can show a real
 * message instead of "Upload Failed (500)".
 */
public record ErrorResponse(
        String error,
        String message,
        int status,
        Instant timestamp
) {
    public static ErrorResponse of(String error, String message, int status) {
        return new ErrorResponse(error, message, status, Instant.now());
    }
}