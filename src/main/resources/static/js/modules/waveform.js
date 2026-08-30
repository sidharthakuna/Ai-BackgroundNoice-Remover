// ============================================================================
// waveform.js — decodes audio via the Web Audio API and draws a min/max
// peak trace per pixel column onto a canvas. No external libraries needed.
// ============================================================================

let sharedAudioCtx = null;

async function getAudioContext() {
    if (!sharedAudioCtx) {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        sharedAudioCtx = new AudioCtx();
    }
    // Browsers create AudioContext in a "suspended" state unless it's
    // constructed synchronously inside a user-gesture handler (a raw click
    // or keydown, before any await). Our first call happens inside an
    // async XHR "load" callback, which is NOT a gesture context as far as
    // autoplay policies are concerned — so without this resume(), Chrome in
    // particular can leave the context suspended indefinitely. decodeAudioData
    // on a suspended context doesn't reliably throw; behavior varies by
    // browser/version, from a long stall to a silently-empty AudioBuffer.
    // resume() is a no-op (resolves immediately) if the context is already
    // running, so this is safe to await on every call, not just the first.
    if (sharedAudioCtx.state === "suspended") {
        try {
            await sharedAudioCtx.resume();
        } catch (err) {
            // Some browsers refuse resume() outside a gesture entirely rather
            // than queuing it — that's fine, decodeAudioData below will then
            // fail through the normal catch path in drawWaveformFromBlob and
            // fall back to the flatline, same as any other decode failure.
            console.warn("AudioContext resume failed:", err);
        }
    }
    return sharedAudioCtx;
}

const waveformRegistry = new Map();

/**
 * @param {Blob} blob
 * @param {HTMLCanvasElement} canvas
 * @param {string} colorVar CSS variable name (e.g. '--signal-raw') or hex color
 */
export async function drawWaveformFromBlob(blob, canvas, colorVar = "--signal-raw") {
    try {
        const arrayBuffer = await blob.arrayBuffer();
        const ctx = await getAudioContext();
        // decodeAudioData detaches/consumes the buffer, so pass a copy-safe slice
        const audioBuffer = await ctx.decodeAudioData(arrayBuffer.slice(0));
        waveformRegistry.set(canvas, { audioBuffer, colorVar });
        const color = colorVar.startsWith("--") ? getComputedColor(colorVar) : colorVar;
        renderPeaks(audioBuffer, canvas, color);
    } catch (err) {
        console.warn("Waveform decode skipped:", err);
        const color = colorVar.startsWith("--") ? getComputedColor(colorVar) : colorVar;
        renderFlatline(canvas, color);
    }
}

export function redrawAllWaveforms() {
    for (const [canvas, data] of waveformRegistry.entries()) {
        if (!document.body.contains(canvas)) {
            waveformRegistry.delete(canvas);
            continue;
        }
        const color = data.colorVar.startsWith("--") ? getComputedColor(data.colorVar) : data.colorVar;
        if (data.audioBuffer) {
            renderPeaks(data.audioBuffer, canvas, color);
        } else {
            renderFlatline(canvas, color);
        }
    }
}

// Automatically redraw on resize
let resizeTimer = null;
window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(redrawAllWaveforms, 150);
});

function renderPeaks(audioBuffer, canvas, color) {
    const dpr = window.devicePixelRatio || 1;
    const cssWidth = canvas.clientWidth || 600;
    const cssHeight = canvas.clientHeight || 56;
    canvas.width = Math.round(cssWidth * dpr);
    canvas.height = Math.round(cssHeight * dpr);

    const ctx2d = canvas.getContext("2d");
    ctx2d.scale(dpr, dpr);
    ctx2d.clearRect(0, 0, cssWidth, cssHeight);

    const channelData = audioBuffer.getChannelData(0);
    const mid = cssHeight / 2;
    const barWidth = 2.5;
    const barGap = 1.5;
    const totalBarWidth = barWidth + barGap;
    const barCount = Math.floor(cssWidth / totalBarWidth);
    const samplesPerBar = Math.max(1, Math.floor(channelData.length / barCount));

    // Vertical gradient with glowing core
    const gradient = ctx2d.createLinearGradient(0, 0, 0, cssHeight);
    gradient.addColorStop(0, color);
    gradient.addColorStop(0.35, color);
    gradient.addColorStop(0.5, "rgba(255, 255, 255, 0.9)");
    gradient.addColorStop(0.65, color);
    gradient.addColorStop(1, color);

    // Subtle central zero-crossing line
    ctx2d.strokeStyle = "rgba(255, 255, 255, 0.08)";
    ctx2d.lineWidth = 1;
    ctx2d.beginPath();
    ctx2d.moveTo(0, mid);
    ctx2d.lineTo(cssWidth, mid);
    ctx2d.stroke();

    ctx2d.fillStyle = gradient;

    for (let b = 0; b < barCount; b++) {
        const start = b * samplesPerBar;
        let sumSquares = 0;
        let peak = 0;

        for (let i = 0; i < samplesPerBar; i++) {
            const sample = channelData[start + i];
            if (sample === undefined) break;
            const abs = Math.abs(sample);
            if (abs > peak) peak = abs;
            sumSquares += sample * sample;
        }

        const rms = Math.sqrt(sumSquares / samplesPerBar);
        // Blend RMS and peak for punchy yet smooth dynamics
        const amplitude = Math.min(1.0, 0.7 * peak + 0.3 * (rms * 2.2));
        const barHeight = Math.max(3, amplitude * (mid * 0.92) * 2);

        const x = b * totalBarWidth;
        const y = mid - barHeight / 2;
        const radius = Math.min(barWidth / 2, barHeight / 2);

        ctx2d.beginPath();
        if (ctx2d.roundRect) {
            ctx2d.roundRect(x, y, barWidth, barHeight, radius);
        } else {
            ctx2d.rect(x, y, barWidth, barHeight);
        }
        ctx2d.fill();
    }
}

function renderFlatline(canvas, color) {
    const cssWidth = canvas.clientWidth || 600;
    const cssHeight = canvas.clientHeight || 56;
    const ctx2d = canvas.getContext("2d");
    ctx2d.clearRect(0, 0, cssWidth, cssHeight);
    ctx2d.strokeStyle = color;
    ctx2d.lineWidth = 1.5;
    ctx2d.globalAlpha = 0.35;
    ctx2d.beginPath();
    ctx2d.moveTo(0, cssHeight / 2);
    ctx2d.lineTo(cssWidth, cssHeight / 2);
    ctx2d.stroke();
    ctx2d.globalAlpha = 1;
}


export function getComputedColor(varName) {
    return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || "#ff6b35";
}