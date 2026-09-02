// ============================================================================
// processing.js — the upload/enhance pipeline: queues entries, respects
// MAX_CONCURRENT_UPLOADS, drives XHR, and reports progress back via the
// timer + VU-meter "settling" class. Talks to the DOM only through the
// entry.listEl handed to it — no direct element lookups by id.
//
// Talks to the backend's async job API in three steps, matching
// AudioController / JobController on the server:
//   1. POST /api/v1/audio/enhance        -> 202 + { jobId, statusUrl }.
//      This is just the upload being accepted, NOT the processed audio —
//      the real denoising keeps running on a background thread after this
//      response comes back (see AudioJobService.runJob, which is @Async).
//   2. GET  /api/v1/jobs/{jobId}/status  -> polled every POLL_INTERVAL_MS
//      until resultReady is true or status is "FAILED".
//   3. GET  /api/v1/jobs/{jobId}/result  -> the actual processed audio
//      bytes, fetched once resultReady is true.
// A DELETE to /api/v1/jobs/{jobId} follows on success, best-effort, to free
// the job's temp directory right away instead of waiting on the server's
// hourly eviction (see JobStatusStore) — see releaseJob() below.
//
// PREVIOUS BUG, for anyone wondering why this file changed shape: an
// earlier version sent the upload with xhr.responseType = "blob" and
// treated step 1's response as the final audio directly. That matched an
// older, synchronous version of this endpoint, but the backend has since
// moved to the async job flow above. A 202 status still falls inside the
// 200-299 "success" range, so that old code path never errored — it just
// handed the tiny { jobId, statusUrl } JSON body to
// <audio class="audio-after">.src as if it were a WAV file. Browsers can't
// decode JSON as audio, so playback silently showed 0:00 / 0:00: a
// "successful", clean-looking upload with a blank/broken result. Fixed by
// actually running steps 2 and 3 above instead of stopping after step 1.
// ============================================================================

import { API_BASE, API_ENDPOINT, MAX_CONCURRENT_UPLOADS } from "./constants.js";
import { formatElapsed, withExtension } from "./format.js";
import { updateStatusBadge } from "./fileList.js";
import { drawWaveformFromBlob, getComputedColor } from "./waveform.js";

const POLL_INTERVAL_MS = 1500;

/**
 * @param {import('./state.js').AppState} appState
 * @param {{onEntryDone: (entry: any, outName: string) => void, onQueueChange: () => void}} callbacks
 */
export function createProcessingQueue(appState, callbacks) {
    function queueProcessing(entry) {
        appState.uploadQueue.push(entry.id);
        pumpQueue();
    }

    function pumpQueue() {
        while (appState.activeUploads < MAX_CONCURRENT_UPLOADS && appState.uploadQueue.length > 0) {
            const id = appState.uploadQueue.shift();
            const entry = appState.get(id);
            if (!entry) continue;
            appState.activeUploads++;
            processFile(entry).finally(() => {
                appState.activeUploads--;
                pumpQueue();
                callbacks.onQueueChange();
            });
        }
    }

    // ── Shared retry policy for all three steps below (submit/pollOnce/fetchResult) ──
    // 500-504: transient cloud proxy / origin glitches (Render, and similar platforms,
    // can bounce a request with one of these while an instance is restarting, mid-deploy,
    // or waking from the free tier's idle sleep).
    // 429: the platform's own edge/proxy telling us to back off — most commonly seen here
    // in the same "instance isn't fully up yet" window as the codes above, rather than an
    // application-level rate limit (this app's own backend never returns 429; see
    // GlobalExceptionHandler). Since it shares a root cause with 502/503/504 in practice,
    // it gets the same short, bounded retry instead of failing the whole job outright.
    function isRetryableStatus(status) {
        return status === 429 || (status >= 500 && status <= 504);
    }

    function processFile(entry) {
        return new Promise((resolve) => {
            entry.status = "processing";
            entry.errorMessage = null;
            updateStatusBadge(entry);
            callbacks.onQueueChange();

            const progressWrap = entry.listEl.querySelector(".file-item-progress");
            const progressTimer = entry.listEl.querySelector(".progress-timer");
            const progressLabel = entry.listEl.querySelector(".progress-label");
            const errorEl = entry.listEl.querySelector(".file-item-error");
            const resultEl = entry.listEl.querySelector(".file-item-result");

            errorEl.hidden = true;
            resultEl.hidden = true;
            progressWrap.hidden = false;
            progressWrap.classList.remove("is-settling");

            entry.startTime = Date.now();
            let uploadComplete = false;
            entry.timerHandle = setInterval(() => {
                const elapsed = Math.floor((Date.now() - entry.startTime) / 1000);
                progressTimer.textContent = formatElapsed(elapsed);
                if (uploadComplete && elapsed > 3) {
                    progressWrap.classList.add("is-settling");
                }
            }, 1000);

            function finish() {
                clearInterval(entry.timerHandle);
                resolve();
            }

            // ── Step 1: upload ────────────────────────────────────────
            async function submit(maxRetries = 3) {
                const formData = new FormData();
                formData.append("file", entry.file);
                formData.append("demucs", String(entry.useDemucs));
                formData.append("mode", entry.mode || "balanced");
                formData.append("format", entry.format);

                for (let attempt = 1; attempt <= maxRetries; attempt++) {
                    try {
                        const xhr = await sendRequest(entry, "POST", API_ENDPOINT, {
                            responseType: "json",
                            body: formData,
                            onUploadProgress: (e) => {
                                if (e.lengthComputable && e.loaded >= e.total) {
                                    uploadComplete = true;
                                }
                            },
                        });
                        if (isRetryableStatus(xhr.status) && attempt < maxRetries) {
                            await abortableDelay(entry, 2500);
                            continue;
                        }
                        if (xhr.status < 200 || xhr.status >= 300) {
                            throw appError(await parseErrorResponse(xhr));
                        }
                        const body = xhr.response;
                        if (!body || !body.jobId) {
                            throw appError("The server accepted the upload but didn't return a job id.");
                        }
                        return body.jobId;
                    } catch (e) {
                        if (attempt >= maxRetries || (e && e.name === "AbortError") || (e && e.isAppError)) {
                            throw e;
                        }
                        await abortableDelay(entry, 2500);
                    }
                }
            }

            // ── Step 2: poll status (with retry for transient 429/502/503/504 cloud proxy glitches) ────
            async function pollOnce(jobId, maxRetries = 8) {
                for (let attempt = 1; attempt <= maxRetries; attempt++) {
                    try {
                        const xhr = await sendRequest(entry, "GET", `/api/v1/jobs/${jobId}/status`, {
                            responseType: "json",
                        });
                        if (isRetryableStatus(xhr.status) && attempt < maxRetries) {
                            await abortableDelay(entry, 2000);
                            continue;
                        }
                        if (xhr.status < 200 || xhr.status >= 300) {
                            throw appError(await parseErrorResponse(xhr));
                        }
                        const body = xhr.response;
                        if (!body) {
                            if (attempt < maxRetries) {
                                await abortableDelay(entry, 1500);
                                continue;
                            }
                            throw appError("Received an unreadable status response from the server.");
                        }
                        if (body.status === "FAILED") {
                            throw appError(body.errorMessage || "Audio processing failed.");
                        }
                        return body;
                    } catch (e) {
                        if (attempt >= maxRetries || (e && e.name === "AbortError") || (e && e.isAppError)) {
                            throw e;
                        }
                        await abortableDelay(entry, 2000);
                    }
                }
            }

            // ── Step 3: download the real result ──────────────────────
            async function fetchResult(jobId, maxRetries = 4) {
                for (let attempt = 1; attempt <= maxRetries; attempt++) {
                    try {
                        const xhr = await sendRequest(entry, "GET", `/api/v1/jobs/${jobId}/result`, {
                            responseType: "blob",
                        });
                        if (isRetryableStatus(xhr.status) && attempt < maxRetries) {
                            await abortableDelay(entry, 2000);
                            continue;
                        }
                        if (xhr.status < 200 || xhr.status >= 300) {
                            throw appError(await parseErrorResponse(xhr));
                        }
                        return xhr.response;
                    } catch (e) {
                        if (attempt >= maxRetries || (e && e.name === "AbortError") || (e && e.isAppError)) {
                            throw e;
                        }
                        await abortableDelay(entry, 2000);
                    }
                }
            }

            (async () => {
                try {
                    const jobId = await submit();
                    entry.jobId = jobId;

                    let status = await pollOnce(jobId);
                    setProgressLabel(progressLabel, status.message);
                    while (!status.resultReady) {
                        await abortableDelay(entry, POLL_INTERVAL_MS);
                        status = await pollOnce(jobId);
                        setProgressLabel(progressLabel, status.message);
                    }

                    const blob = await fetchResult(jobId);
                    await handleSuccess(entry, blob);
                    finish();
                } catch (err) {
                    if (err && err.name === "AbortError") {
                        // Deliberate cancel
                        finish();
                        return;
                    }
                    handleFailure(
                        entry,
                        err && err.isAppError
                            ? err.message
                            : "Couldn't reach the server. Check your connection and try again."
                    );
                    finish();
                }
            })();
        });
    }

    /**
     * Wraps a single XMLHttpRequest in a Promise, and keeps entry.xhr
     * pointed at whichever request is currently in flight so state.js's
     * remove() (entry.xhr.abort()) can still cancel mid-processing.
     */
    function sendRequest(entry, method, url, { responseType = "", body = null, onUploadProgress = null } = {}) {
        return new Promise((resolve, reject) => {
            const fullUrl = url.startsWith("http://") || url.startsWith("https://")
                ? url
                : `${API_BASE}${url.startsWith("/") ? "" : "/"}${url}`;
            const xhr = new XMLHttpRequest();
            entry.xhr = xhr;
            xhr.open(method, fullUrl);
            xhr.responseType = responseType;
            if (onUploadProgress) {
                xhr.upload.addEventListener("progress", onUploadProgress);
            }
            xhr.addEventListener("load", () => resolve(xhr));
            xhr.addEventListener("error", () => reject(new Error("Network error")));
            xhr.addEventListener("abort", () => reject(makeAbortError()));
            xhr.send(body);
        });
    }

    function abortableDelay(entry, ms) {
        return new Promise((resolve, reject) => {
            const timer = setTimeout(resolve, ms);
            entry.xhr = {
                abort() {
                    clearTimeout(timer);
                    reject(makeAbortError());
                },
            };
        });
    }

    function makeAbortError() {
        const err = new Error("Request aborted");
        err.name = "AbortError";
        return err;
    }

    function appError(message) {
        const err = new Error(message);
        err.isAppError = true;
        return err;
    }

    async function parseErrorResponse(xhr) {
        let json = null;
        if (xhr.responseType === "blob") {
            if (xhr.response) {
                try {
                    json = JSON.parse(await xhr.response.text());
                } catch {
                    json = null;
                }
            }
        } else {
            json = xhr.response || null;
        }
        if (json && json.message) return json.message;

        const genericByStatus = {
            400: "The file or request was invalid.",
            404: "The job could not be found. It may have expired.",
            408: "Processing took too long and timed out.",
            409: "The job isn't finished yet.",
            410: "The result is no longer available. It may have expired.",
            413: "The file is too large (over 100MB).",
            422: "The file couldn't be processed — it may be corrupt or in an unsupported format.",
            429: "The server is still starting up. Please wait a few seconds and try again.",
            500: "Internal server error. Please try a shorter audio clip.",
            502: "The server is temporarily unavailable or restarting. Please retry in a few moments.",
            503: "The server is currently busy. Please retry in a few moments.",
            504: "The request timed out. Please try again.",
        };
        return genericByStatus[xhr.status] || `Something went wrong (HTTP ${xhr.status}).`;
    }

    function releaseJob(jobId) {
        try {
            const fullUrl = `${API_BASE}/api/v1/jobs/${jobId}`;
            const xhr = new XMLHttpRequest();
            xhr.open("DELETE", fullUrl);
            xhr.send();
        } catch {
        }
    }

    function setProgressLabel(progressLabelEl, message) {
        if (!progressLabelEl) return;
        const textNode = progressLabelEl.firstChild;
        if (textNode && textNode.nodeType === Node.TEXT_NODE) {
            textNode.textContent = `${message || "Processing…"} `;
        }
    }

    async function handleSuccess(entry, blob) {
        entry.status = "done";
        entry.resultBlob = blob;
        entry.resultUrl = URL.createObjectURL(blob);
        updateStatusBadge(entry);

        const progressWrap = entry.listEl.querySelector(".file-item-progress");
        const resultEl = entry.listEl.querySelector(".file-item-result");
        progressWrap.hidden = true;
        resultEl.hidden = false;

        const downloadLink = resultEl.querySelector(".download-link");
        const outName = withExtension(entry.file.name, entry.format);
        downloadLink.href = entry.resultUrl;
        downloadLink.download = outName;

        const audioBefore = resultEl.querySelector(".audio-before");
        const audioAfter = resultEl.querySelector(".audio-after");
        audioBefore.src = URL.createObjectURL(entry.file);
        audioAfter.src = entry.resultUrl;

        const canvasBefore = resultEl.querySelector(".waveform-before");
        const canvasAfter = resultEl.querySelector(".waveform-after");
        drawWaveformFromBlob(entry.file, canvasBefore, "--signal-raw");
        drawWaveformFromBlob(entry.resultBlob, canvasAfter, "--signal-clean");

        setupABComparison(resultEl, audioBefore, audioAfter);

        callbacks.onEntryDone(entry, outName);
    }

    /**
     * Wires synchronized A/B toggle between original and enhanced audio tracks.
     * When toggled mid-playback, seamlessly switches tracks while preserving
     * timestamp and play/pause state.
     */
    function setupABComparison(resultEl, audioBefore, audioAfter) {
        const btnBefore = resultEl.querySelector(".ab-btn-before");
        const btnAfter = resultEl.querySelector(".ab-btn-after");
        const blockBefore = resultEl.querySelector(".waveform-block-before");
        const blockAfter = resultEl.querySelector(".waveform-block-after");

        if (!btnBefore || !btnAfter) return;

        let activeTrack = "after"; // default focus on clean output

        function setActiveTrack(track) {
            if (activeTrack === track) return;
            const fromAudio = activeTrack === "before" ? audioBefore : audioAfter;
            const toAudio = track === "before" ? audioBefore : audioAfter;

            const isPlaying = !fromAudio.paused;
            const curTime = fromAudio.currentTime;

            fromAudio.pause();
            toAudio.currentTime = curTime;

            if (isPlaying) {
                toAudio.play().catch(() => {});
            }

            activeTrack = track;
            updateABVisuals();
        }

        function updateABVisuals() {
            btnBefore.classList.toggle("is-active", activeTrack === "before");
            btnAfter.classList.toggle("is-active", activeTrack === "after");
            blockBefore.classList.toggle("is-active", activeTrack === "before");
            blockAfter.classList.toggle("is-active", activeTrack === "after");
        }

        btnBefore.addEventListener("click", () => setActiveTrack("before"));
        btnAfter.addEventListener("click", () => setActiveTrack("after"));

        audioBefore.addEventListener("play", () => {
            if (activeTrack !== "before") {
                audioAfter.pause();
                activeTrack = "before";
                updateABVisuals();
            }
        });

        audioAfter.addEventListener("play", () => {
            if (activeTrack !== "after") {
                audioBefore.pause();
                activeTrack = "after";
                updateABVisuals();
            }
        });
    }

    function handleFailure(entry, message) {
        entry.status = "error";
        entry.errorMessage = message;
        updateStatusBadge(entry);

        const progressWrap = entry.listEl.querySelector(".file-item-progress");
        const errorEl = entry.listEl.querySelector(".file-item-error");
        progressWrap.hidden = true;
        errorEl.hidden = false;
        errorEl.textContent = message;
        callbacks.onQueueChange();
    }

    return { queueProcessing };
}
