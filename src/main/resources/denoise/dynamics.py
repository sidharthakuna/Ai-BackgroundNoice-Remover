"""
dynamics.py — the three gain-staging stages: AGC, compressor, limiter
(original Stages 4, 7, 8).

WHY THESE THREE ARE IN ONE FILE, NOT THREE:
These stages measurably interact in ways that aren't obvious from reading
any one of them alone. The short version, documented at length inline:
  - AGC alone left ~10.4dB of loudness swing ("pumping") on real
    conversational speech.
  - The FIRST attempt to fix pumping widened AGC's window (150ms->350ms)
    and made the compressor a rare peak-catcher (threshold -22dB->-8dB).
    This was TESTED and made pumping WORSE (7.0dB -> 13.5dB), because it
    turned off the compressor, which turned out to be the stage actually
    doing the smoothing work, not the AGC.
  - The actual fix was tuning the compressor's threshold/ratio, leaving
    AGC's window alone.
If these three functions were split into agc.py / compressor.py /
limiter.py, a future editor tuning one in isolation would have no way to
know this history exists, and could easily repeat the exact mistake
above. Keep them together unless you're also willing to re-run the
head-to-head measurement this file's comments describe.

EDIT THIS FILE IF you need to change:
  - AGC target level, attack/release timing, or max boost (currently
    target_rms=0.12, 80ms/400ms attack/release, max_boost_db=36)
  - Compressor threshold/ratio (currently -26dB / 3.5:1)
  - Limiter ceiling or knee (currently ceiling=0.95, knee at 80% of
    ceiling)

If you're chasing a "pumping" or "breathing" complaint, read the
apply_agc() docstring below FIRST before touching anything -- there's a
real risk of re-doing the already-tested-and-reverted first attempt.
"""

import numpy as np
from scipy.ndimage import uniform_filter1d

SAMPLE_RATE = 16000


def apply_agc(audio, target_rms=0.12, attack_ms=80, release_ms=400,
               max_boost_db=36, min_gain=0.20, sr=SAMPLE_RATE):
    """
    Stage 4: Automatic Gain Control. Boosts quiet/mumbled speech toward
    target_rms using a 150ms RMS window (tracks overall speaking level
    rather than reacting to every syllable) and an 80ms attack / 400ms
    release envelope.

    max_boost_db=36 (64x) exists specifically so a true mumble/whisper at
    -40dBFS can reach the -18dBFS target rather than staying buried --
    the original max_boost_db=24 (16x) wasn't enough.

    DO NOT narrow the RMS window below 150ms to "react faster" without
    re-testing the compressor in the same file, and read the module
    docstring above first. A 75ms window with faster attack/release was
    tried, measured to pump MORE (12 of 49 half-second test windows
    showed >6dB internal swing vs 3 of 49 at 150ms), and reverted. This
    parameter set is not the first thing that was tried -- it's what
    survived after two other configurations were tested and rejected.
    """
    max_boost = 10.0 ** (max_boost_db / 20.0)

    window = max(1, int(sr * 0.150))
    rms = np.sqrt(uniform_filter1d(audio.astype(np.float32) ** 2, size=window) + 1e-12)
    raw_gain = np.clip(target_rms / rms, min_gain, max_boost)

    # 1kHz control-rate envelope smoothing (1ms precision, 16x faster than per-sample loop)
    step = 16
    down_gain = raw_gain[::step]
    eff_sr = sr / step
    att_a = np.exp(-1.0 / (eff_sr * attack_ms / 1000.0))
    rel_a = np.exp(-1.0 / (eff_sr * release_ms / 1000.0))

    down_smooth = np.empty_like(down_gain)
    down_smooth[0] = down_gain[0]
    for i in range(1, len(down_gain)):
        a = att_a if down_gain[i] < down_smooth[i - 1] else rel_a
        down_smooth[i] = a * down_smooth[i - 1] + (1.0 - a) * down_gain[i]

    smooth = np.interp(np.arange(len(raw_gain)), np.arange(0, len(raw_gain), step), down_smooth)
    return (audio * smooth.astype(np.float32)).astype(np.float32)



def apply_compressor(audio, threshold_db=-26, ratio=3.5, sr=SAMPLE_RATE):
    """
    Stage 7: RMS compressor. This is the stage doing the actual pumping
    control for the whole chain (see module docstring) -- threshold sits
    below AGC's own target so it fires on most loud syllables, not just
    rare transients, which is what makes it effective as a smoother
    rather than a peak-safety-net.

    threshold_db=-26 / ratio=3.5 (moved from -22/2.5) measurably dropped
    max adjacent-window swing from 7.0dB to 5.4dB on test conversational
    speech, at negligible cost to mumble boosting (-25.4dBFS old vs
    -25.8dBFS new on an isolated mumbled test word -- within measurement
    noise).
    """
    threshold_lin = 10.0 ** (threshold_db / 20.0)
    window = max(1, int(sr * 0.020))
    rms = np.sqrt(uniform_filter1d(audio.astype(np.float32) ** 2, size=window) + 1e-12)
    gain = np.ones_like(rms)
    above = rms > threshold_lin
    gain[above] = (threshold_lin + (rms[above] - threshold_lin) / ratio) / rms[above]
    gain = uniform_filter1d(gain, size=max(1, int(sr * 0.050))).astype(np.float32)
    return audio * gain


def apply_limiter(audio, ceiling=0.95):
    """
    Stage 8: soft-knee limiter. Final hard ceiling before Demucs/LUFS
    stages. Knee starts at 80% of ceiling; above that, a tanh curve
    softens the approach to ceiling instead of hard-clipping.
    """
    knee = 0.80 * ceiling
    sign = np.sign(audio)
    mag = np.abs(audio)
    above = mag > knee
    mag[above] = knee + (ceiling - knee) * np.tanh(
        (mag[above] - knee) / (ceiling - knee)
    )
    return (sign * np.minimum(mag, ceiling)).astype(np.float32)


def process(audio_data):
    """Runs AGC -> compressor -> limiter in order. This is the only
    function main.py needs to call from this module."""
    audio_data = apply_agc(
        audio_data, target_rms=0.12, attack_ms=80, release_ms=400,
        max_boost_db=36, min_gain=0.20, sr=SAMPLE_RATE
    )
    audio_data = apply_compressor(audio_data, threshold_db=-26, ratio=3.5, sr=SAMPLE_RATE)
    audio_data = apply_limiter(audio_data, ceiling=0.95)
    return audio_data