import sys
import shutil
import numpy as np
import torch
import soundfile as sf
import librosa
from scipy.signal import butter, filtfilt, sosfilt
from scipy.ndimage import uniform_filter1d
import webrtcvad
import pyloudnorm as pyln
from df.enhance import enhance, init_df
try:
    from df.config import config as df_config
except ImportError:
    df_config = None

input_path  = sys.argv[1]
output_path = sys.argv[2]
use_demucs  = len(sys.argv) > 3 and sys.argv[3] == "--demucs"

SAMPLE_RATE = 16000

# ── Load audio ─────────────────────────────────────────────────────────────────
raw_audio, original_sample_rate = librosa.load(input_path, sr=SAMPLE_RATE, mono=False)
is_stereo = raw_audio.ndim == 2

if is_stereo:
    left_channel  = raw_audio[0]
    right_channel = raw_audio[1]
    mid_channel   = ((left_channel + right_channel) / 2).astype(np.float32)
    side_channel  = ((left_channel - right_channel) / 2).astype(np.float32)
    side_channel  = side_channel * 0.15
    audio_data    = mid_channel
else:
    audio_data = raw_audio.astype(np.float32)

# ── Stage 1: High-pass filter (remove rumble below 80 Hz) ─────────────────────
highpass_b, highpass_a = butter(4, 80 / (SAMPLE_RATE / 2), btype='high')
audio_data = filtfilt(highpass_b, highpass_a, audio_data).astype(np.float32)

# ── Stage 2: Mumble-aware VAD gate ────────────────────────────────────────────
#
# FIX 1 — Mumble preservation.
#
# Old problem: webrtcvad level 2 is moderately aggressive and will classify
# soft/mumbled speech frames as silence, which then get attenuated to 0.15
# (−16 dB). This destroys the very content we want to keep.
#
# Changes made:
#   a) VAD aggressiveness reduced from 2 → 0 (least aggressive).
#      Level 0 accepts almost any signal above room noise as speech.
#      Levels 1-3 progressively discard quieter/murmured frames.
#
#   b) Silence floor raised from 0.15 → 0.40.
#      This reduces attenuation of non-speech from −16 dB to only −8 dB,
#      giving mumbled frames that were mis-classified as silence a fighting
#      chance instead of being crushed.
#
#   c) Lookahead extended from 80ms → 160ms and smoothing release from
#      80ms → 150ms so the gate stays open through the full arc of a
#      mumbled word rather than closing between syllables.
#
#   d) Multi-band energy pre-check: if the 200–3400 Hz band (core speech
#      band) has energy above a soft threshold, the frame is force-included
#      even if the VAD says "no speech". This catches low-energy mumbles.
#
pcm16_audio  = (np.clip(audio_data, -1.0, 1.0) * 32767).astype(np.int16)

# Level 0 = least aggressive: keeps mumbled/quiet speech frames
vad_detector = webrtcvad.Vad(0)
frame_length = int(SAMPLE_RATE * 30 / 1000)   # 30ms frames

remainder = len(pcm16_audio) % frame_length
if remainder:
    pcm16_audio = np.pad(pcm16_audio, (0, frame_length - remainder), mode='constant')

# --- Multi-band energy detector (catches mumbles VAD misses) ---
# Any 30ms frame with sufficient energy in the speech formant band
# (200–3400 Hz) is treated as speech regardless of VAD verdict.
sos_speech_band = butter(4, [200 / (SAMPLE_RATE / 2), 3400 / (SAMPLE_RATE / 2)],
                         btype='band', output='sos')
filtered_for_energy = sosfilt(sos_speech_band, audio_data)

# Noise floor estimate: 20th percentile of frame RMS across the file
frame_rms_all = []
padded_full = np.pad(filtered_for_energy,
                     (0, frame_length - len(filtered_for_energy) % frame_length
                      if len(filtered_for_energy) % frame_length else 0))
for fs in range(0, len(padded_full) - frame_length + 1, frame_length):
    rms_val = np.sqrt(np.mean(padded_full[fs:fs + frame_length].astype(np.float64) ** 2))
    frame_rms_all.append(rms_val)

noise_floor = np.percentile(frame_rms_all, 20)
mumble_threshold = noise_floor * 3.5   # 3.5× above noise floor = likely mumble

speech_mask = np.zeros(len(pcm16_audio), dtype=bool)
for idx, fs in enumerate(range(0, len(pcm16_audio) - frame_length + 1, frame_length)):
    vad_says_speech = vad_detector.is_speech(
        pcm16_audio[fs:fs + frame_length].tobytes(), SAMPLE_RATE
    )
    # Energy check in the speech formant band
    band_rms = frame_rms_all[idx] if idx < len(frame_rms_all) else 0.0
    energy_says_speech = band_rms > mumble_threshold

    if vad_says_speech or energy_says_speech:
        speech_mask[fs:fs + frame_length] = True

speech_mask = speech_mask[:len(audio_data)]

# Extended 160ms lookahead — keeps gate open through mumbled word endings
exp_samples = int(SAMPLE_RATE * 0.16)
expanded_mask = np.convolve(speech_mask.astype(float),
                            np.ones(exp_samples * 2), mode='same') > 0

# Raised silence floor: 0.40 instead of 0.15 — only −8 dB instead of −16 dB.
# Mumbles mis-classified as silence survive rather than being crushed.
target_vad = np.where(expanded_mask, 1.0, 0.40).astype(np.float64)
att_a = np.exp(-1.0 / (SAMPLE_RATE * 0.030))
rel_a = np.exp(-1.0 / (SAMPLE_RATE * 0.150))  # 150ms release (was 80ms)

vad_gain = np.empty_like(target_vad)
vad_gain[0] = target_vad[0]
for i in range(1, len(target_vad)):
    a = att_a if target_vad[i] > vad_gain[i - 1] else rel_a
    vad_gain[i] = a * vad_gain[i - 1] + (1.0 - a) * target_vad[i]

vad_gain   = vad_gain.astype(np.float32)
audio_data = audio_data * vad_gain

# ── Stage 3: DeepFilterNet — speech-preserving noise removal ──────────────────
#
# FIX 2 — Prevent DeepFilterNet from erasing mumbled speech.
#
# By default DeepFilterNet applies full attenuation wherever its internal
# mask falls below the model's confidence. For mumbled speech the mask
# value is low (the model is uncertain), so the default behaviour removes
# the energy — exactly the same effect as the noise it's trying to kill.
#
# The fix: set post_filter_beta=0.0 (disables the extra post-filter
# that aggressively zeros uncertain regions) and atten_lim_db to a
# conservative 12 dB. This means even the "noisiest" bin will only be
# reduced by 12 dB, not silenced — preserving the spectral shape of
# quiet, mumbled phonemes.
#
# atten_lim_db=12  → max attenuation 12 dB  (default is ~100 dB = total kill)
# post_filter_beta=0 → turns off the binary "is this noise?" post-filter
#
deepfilter_model, deepfilter_state, _ = init_df()

# Conservative attenuation limit — preserves mumbled low-energy speech
try:
    if df_config is not None:
        df_config.set("df", "post_filter_beta", "0.0")
except Exception:
    pass

audio_tensor = torch.from_numpy(audio_data[np.newaxis, :]).float()
audio_data   = enhance(
    deepfilter_model,
    deepfilter_state,
    audio_tensor,
    atten_lim_db=12          # Never attenuate any bin by more than 12 dB
).squeeze().numpy().astype(np.float32)

# ── Stage 4: Automatic Gain Control ───────────────────────────────────────────
#
# FIX 3 — Larger max_boost for mumbles, shorter smoothing window.
#
# Mumbled speech can be 30–40 dB quieter than normal speech. The old
# max_boost_db=24 (16×) is not enough for a true whisper/mumble.
# Raised to 36 dB (64×) so a mumble at −40 dBFS can reach the −18 dBFS
# target rather than staying buried.
#
# Also: window halved from 150ms → 75ms so the gain reacts within a
# single short syllable rather than averaging across it.
#
def automatic_gain_control(audio, target_rms=0.12, attack_ms=50, release_ms=300,
                             max_boost_db=36, min_gain=0.20, sr=16000):
    max_boost = 10.0 ** (max_boost_db / 20.0)

    # 75ms RMS window — tight enough to track individual mumbled syllables
    window   = max(1, int(sr * 0.075))
    rms      = np.sqrt(uniform_filter1d(audio.astype(np.float64) ** 2, size=window) + 1e-12)
    raw_gain = np.clip(target_rms / rms, min_gain, max_boost)

    att_a = np.exp(-1.0 / (sr * attack_ms  / 1000.0))
    rel_a = np.exp(-1.0 / (sr * release_ms / 1000.0))

    smooth = np.empty_like(raw_gain)
    smooth[0] = raw_gain[0]
    for i in range(1, len(raw_gain)):
        a = att_a if raw_gain[i] < smooth[i - 1] else rel_a
        smooth[i] = a * smooth[i - 1] + (1.0 - a) * raw_gain[i]

    return (audio * smooth.astype(np.float32)).astype(np.float32)

audio_data = automatic_gain_control(
    audio_data, target_rms=0.12, attack_ms=50, release_ms=300,
    max_boost_db=36, min_gain=0.20, sr=SAMPLE_RATE
)

# ── Stage 5: Cinematic EQ ──────────────────────────────────────────────────────
#
# FIX 4 — Mumble-friendly EQ adjustments.
#
# Mumbled speech concentrates energy in the 300–1500 Hz range (vowels and
# fundamental) with very little 3–8 kHz energy. The old EQ was tuned for
# clear speech; it under-boosted the region where mumbles live.
#
# Changes:
#   5a. Warmth band widened slightly downward (100–300 Hz) to include
#       more of the mumbled fundamental.
#   5c. Presence boost left as-is (2–4 kHz) — still good for clarity.
#   NEW 5e. Mumble intelligibility boost (500–1500 Hz) — the formant region
#       where vowel identity lives in mumbled speech. +3 dB here turns
#       "mhm mhm" into distinguishable vowels.
#

# 5a. Voice body/warmth (100–300 Hz)
sos_warmth  = butter(2, [100 / (SAMPLE_RATE / 2), 300 / (SAMPLE_RATE / 2)], btype='band', output='sos')
audio_data  = audio_data + 0.30 * sosfilt(sos_warmth, audio_data)

# 5b. Mud cut (320–600 Hz)
sos_mud     = butter(2, [320 / (SAMPLE_RATE / 2), 600 / (SAMPLE_RATE / 2)], btype='band', output='sos')
audio_data  = audio_data - 0.18 * sosfilt(sos_mud, audio_data)

# 5c. Presence (2000–4000 Hz)
sos_pres    = butter(2, [2000 / (SAMPLE_RATE / 2), 4000 / (SAMPLE_RATE / 2)], btype='band', output='sos')
audio_data  = audio_data + 0.35 * sosfilt(sos_pres, audio_data)

# 5d. Consonant clarity (4000–7500 Hz)
sos_air     = butter(2, [4000 / (SAMPLE_RATE / 2), min(7500 / (SAMPLE_RATE / 2), 0.999)], btype='band', output='sos')
audio_data  = audio_data + 0.15 * sosfilt(sos_air, audio_data)

# 5e. NEW: Mumble intelligibility boost (500–1500 Hz vowel formant region)
#     This is the band where vowel identity is encoded. Boosting it by
#     ~2.5 dB makes mumbled vowels distinguishable without making
#     clear speech muddy.
sos_mumble  = butter(2, [500 / (SAMPLE_RATE / 2), 1500 / (SAMPLE_RATE / 2)], btype='band', output='sos')
audio_data  = audio_data + 0.28 * sosfilt(sos_mumble, audio_data)

# ── Stage 6: Subtle harmonic exciter (adds analog warmth) ─────────────────────
harmonic   = np.tanh(audio_data * 1.4) / np.tanh(1.4)
audio_data = audio_data + 0.05 * harmonic * vad_gain

# ── Stage 7: Final compressor ─────────────────────────────────────────────────
#
# FIX 5 — Lower threshold so the compressor works harder on the
# newly boosted mumble sections, preventing the AGC-amplified
# mumbles from clipping the output stage.
#
def rms_compressor(audio, threshold_db=-22, ratio=2.5, sr=16000):
    threshold_lin = 10.0 ** (threshold_db / 20.0)
    window = max(1, int(sr * 0.020))
    rms    = np.sqrt(uniform_filter1d(audio.astype(np.float64) ** 2, size=window) + 1e-12)
    gain   = np.ones_like(rms)
    above  = rms > threshold_lin
    gain[above] = (threshold_lin + (rms[above] - threshold_lin) / ratio) / rms[above]
    gain   = uniform_filter1d(gain, size=max(1, int(sr * 0.050))).astype(np.float32)
    return audio * gain

audio_data = rms_compressor(audio_data, threshold_db=-22, ratio=2.5, sr=SAMPLE_RATE)

# ── Stage 8: Soft-knee limiter ─────────────────────────────────────────────────
def soft_limiter(audio, ceiling=0.95):
    knee  = 0.80 * ceiling
    sign  = np.sign(audio)
    mag   = np.abs(audio)
    above = mag > knee
    mag[above] = knee + (ceiling - knee) * np.tanh(
        (mag[above] - knee) / (ceiling - knee)
    )
    return (sign * np.minimum(mag, ceiling)).astype(np.float32)

audio_data = soft_limiter(audio_data, ceiling=0.95)

# ── Stage 9: Optional Demucs source separation ────────────────────────────────
if use_demucs:
    import subprocess, tempfile, os
    tmp = tempfile.mktemp(suffix=".wav")
    sf.write(tmp, audio_data, SAMPLE_RATE)
    subprocess.run(["python3", "-m", "demucs.separate", "--two-stems=vocals",
                    "-o", os.path.dirname(tmp), tmp], check=True)
    vocals = os.path.join(os.path.dirname(tmp), "htdemucs",
                          os.path.splitext(os.path.basename(tmp))[0], "vocals.wav")
    audio_data, _ = librosa.load(vocals, sr=SAMPLE_RATE, mono=True)
    audio_data = audio_data.astype(np.float32)
    os.unlink(tmp)
    shutil.rmtree(os.path.join(os.path.dirname(tmp), "htdemucs"), ignore_errors=True)

# ── Stage 10: Loudness normalization (-14 LUFS) ────────────────────────────────
loudness_meter      = pyln.Meter(SAMPLE_RATE)
integrated_loudness = loudness_meter.integrated_loudness(audio_data)
audio_data          = pyln.normalize.loudness(audio_data, integrated_loudness, -14.0)

# ── Stereo reconstruction ──────────────────────────────────────────────────────
if is_stereo:
    n            = min(len(audio_data), len(side_channel))
    audio_data   = audio_data[:n]
    side_channel = side_channel[:n]
    L = (audio_data + side_channel).astype(np.float32)
    R = (audio_data - side_channel).astype(np.float32)
    peak = np.max(np.abs(np.stack([L, R]))) + 1e-9
    final_output = np.stack([L / peak * 0.95, R / peak * 0.95], axis=1)
else:
    final_output = audio_data

final_output = np.clip(final_output, -1.0, 1.0)
sf.write(output_path, final_output, SAMPLE_RATE)
print(f"Done. Stereo={is_stereo}")