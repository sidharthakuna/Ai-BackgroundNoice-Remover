package com.sidhartha.keepalive;

import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.io.IOException;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class KeepAliveServiceTest {

    @Test
    void testFormatPingUrl() {
        KeepAliveService service = new KeepAliveService();

        assertEquals("https://my-app.onrender.com/health",
                service.formatPingUrl("https://my-app.onrender.com"));
        assertEquals("https://my-app.onrender.com/health",
                service.formatPingUrl("https://my-app.onrender.com/"));
        assertEquals("https://my-app.onrender.com/health",
                service.formatPingUrl("https://my-app.onrender.com/health"));
        assertEquals("https://my-app.onrender.com/health",
                service.formatPingUrl("my-app.onrender.com"));
    }

    @Test
    void testPingSkippedWhenDisabled() {
        HttpClient mockClient = mock(HttpClient.class);
        KeepAliveService service = new KeepAliveService(mockClient);
        service.setEnabled(false);
        service.setTargetUrl("https://my-app.onrender.com");

        service.ping();

        verifyNoInteractions(mockClient);
    }

    @Test
    void testPingSkippedWhenUrlEmpty() {
        HttpClient mockClient = mock(HttpClient.class);
        KeepAliveService service = new KeepAliveService(mockClient);
        service.setEnabled(true);
        service.setTargetUrl("");

        service.ping();

        verifyNoInteractions(mockClient);
    }

    @Test
    @SuppressWarnings("unchecked")
    void testPingSuccessful() throws Exception {
        HttpClient mockClient = mock(HttpClient.class);
        HttpResponse<String> mockResponse = mock(HttpResponse.class);
        when(mockResponse.statusCode()).thenReturn(200);
        when(mockClient.send(any(HttpRequest.class), any(HttpResponse.BodyHandler.class)))
                .thenReturn(mockResponse);

        KeepAliveService service = new KeepAliveService(mockClient);
        service.setEnabled(true);
        service.setTargetUrl("https://my-app.onrender.com");

        service.ping();

        verify(mockClient, times(1)).send(any(HttpRequest.class), any(HttpResponse.BodyHandler.class));
    }

    @Test
    @SuppressWarnings("unchecked")
    void testPingHandlesExceptionGracefully() throws Exception {
        HttpClient mockClient = mock(HttpClient.class);
        when(mockClient.send(any(HttpRequest.class), any(HttpResponse.BodyHandler.class)))
                .thenThrow(new IOException("Connection timed out"));

        KeepAliveService service = new KeepAliveService(mockClient);
        service.setEnabled(true);
        service.setTargetUrl("https://my-app.onrender.com");

        assertDoesNotThrow(service::ping);
    }
}
