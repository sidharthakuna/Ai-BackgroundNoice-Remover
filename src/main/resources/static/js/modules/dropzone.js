// ============================================================================
// dropzone.js — drag/drop + click-to-browse wiring for the upload surface.
// Pure event plumbing; hands the resulting FileList off via a callback.
// ============================================================================

/**
 * @param {HTMLElement} dropZoneEl
 * @param {HTMLInputElement} fileInputEl
 * @param {(files: File[]) => void} onFilesAdded
 */
export function initDropZone(dropZoneEl, fileInputEl, onFilesAdded) {
    dropZoneEl.addEventListener("click", () => fileInputEl.click());

    dropZoneEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            fileInputEl.click();
        }
    });

    ["dragenter", "dragover"].forEach((evt) => {
        dropZoneEl.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZoneEl.classList.add("drag-active");
        });
    });

    ["dragleave", "drop"].forEach((evt) => {
        dropZoneEl.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (evt === "dragleave" && e.target !== dropZoneEl) return;
            dropZoneEl.classList.remove("drag-active");
        });
    });

    dropZoneEl.addEventListener("drop", (e) => {
        const dropped = e.dataTransfer?.files;
        if (dropped && dropped.length) {
            onFilesAdded(Array.from(dropped));
        }
    });

    fileInputEl.addEventListener("change", () => {
        if (fileInputEl.files.length) {
            onFilesAdded(Array.from(fileInputEl.files));
        }
        fileInputEl.value = ""; // allow re-selecting the same file later
    });
}

/**
 * Live in-browser microphone recorder using HTML5 MediaRecorder.
 */
export function initMicRecorder({ recordBtn, panel, stopBtn, cancelBtn, timerEl, onRecorded }) {
    if (!recordBtn || !panel) return;

    let mediaRecorder = null;
    let audioStream = null;
    let recordedChunks = [];
    let timerInterval = null;
    let secondsElapsed = 0;

    function formatTimer(sec) {
        const m = String(Math.floor(sec / 60)).padStart(2, "0");
        const s = String(sec % 60).padStart(2, "0");
        return `${m}:${s}`;
    }

    async function startRecording() {
        if (!navigator.mediaDevices?.getUserMedia) {
            alert("Microphone access is not supported in this browser.");
            return;
        }

        try {
            audioStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: false,
                    noiseSuppression: false, // keep noise untouched so our AI denoiser cleans it!
                    autoGainControl: false,
                },
            });

            recordedChunks = [];
            let options = {};
            if (MediaRecorder.isTypeSupported("audio/webm")) {
                options = { mimeType: "audio/webm" };
            } else if (MediaRecorder.isTypeSupported("audio/mp4")) {
                options = { mimeType: "audio/mp4" };
            }

            mediaRecorder = new MediaRecorder(audioStream, options);

            mediaRecorder.ondataavailable = (e) => {
                if (e.data && e.data.size > 0) {
                    recordedChunks.push(e.data);
                }
            };

            mediaRecorder.onstop = () => {
                if (recordedChunks.length === 0) return;
                const mime = mediaRecorder.mimeType || "audio/webm";
                const ext = mime.includes("mp4") ? "mp4" : (mime.includes("ogg") ? "ogg" : "webm");
                const blob = new Blob(recordedChunks, { type: mime });
                const filename = `mic-record-${new Date().toISOString().slice(11, 19).replace(/:/g, "-")}.${ext}`;
                const file = new File([blob], filename, { type: mime });
                onRecorded([file]);
            };

            mediaRecorder.start(250);
            secondsElapsed = 0;
            timerEl.textContent = "00:00";
            panel.hidden = false;
            recordBtn.disabled = true;

            timerInterval = setInterval(() => {
                secondsElapsed++;
                timerEl.textContent = formatTimer(secondsElapsed);
            }, 1000);

        } catch (err) {
            console.error("Mic access failed:", err);
            alert("Could not access microphone. Please ensure microphone permissions are granted.");
            cleanup();
        }
    }

    function stopRecording() {
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
        }
        cleanup();
    }

    function cancelRecording() {
        recordedChunks = [];
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            mediaRecorder.stop();
        }
        cleanup();
    }

    function cleanup() {
        clearInterval(timerInterval);
        if (audioStream) {
            audioStream.getTracks().forEach((track) => track.stop());
            audioStream = null;
        }
        panel.hidden = true;
        recordBtn.disabled = false;
    }

    recordBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        startRecording();
    });
    stopBtn.addEventListener("click", stopRecording);
    cancelBtn.addEventListener("click", cancelRecording);
}