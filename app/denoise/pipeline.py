"""
pipeline.py — Master 48kHz studio audio DSP pipeline coordinator.
"""

import gc
import numpy as np
import torch
from typing import Callable

from app.config import SAMPLE_RATE, MODE_CONFIGS, CHUNK_THRESHOLD_SECONDS
from app.denoise.audio_io import load_audio, save_audio, encode_mid_side, decode_mid_side
from app.denoise.dsp import (
    apply_highpass,
    apply_spectral_gating,
    apply_vad_gating,
    apply_dynamics,
    apply_tone_mastering
)
from app.denoise.demucs_engine import apply_demucs_chunked
from app.denoise.chunker import process_audio_chunked_or_direct
from app.denoise.memory_guard import memory_guard


def execute_pipeline(
    input_path: str,
    output_path: str,
    mode: str,
    use_demucs: bool,
    model_registry,
    progress_callback: Callable[[int, str, str], None],
    cancel_check: Callable[[], bool]
) -> bool:
    """Executes the full studio DSP pipeline from start to finish."""
    cfg = MODE_CONFIGS.get(mode.lower(), MODE_CONFIGS["balanced"])

    # Step 1: Load audio
    progress_callback(10, "LOADING", "Loading 48kHz audio into memory")
    audio, sr, is_stereo = load_audio(input_path)

    if cancel_check():
        return False

    # Step 2: Demucs vocal isolation (if requested)
    if use_demucs:
        progress_callback(20, "ISOLATING_VOCALS", "Isolating vocal stems via Demucs (chunked)")
        demucs_model = model_registry.get_demucs_model()
        audio = apply_demucs_chunked(audio, demucs_model)
        memory_guard.cleanup()

    if cancel_check():
        return False

    # Step 3: Stereo Mid/Side separation
    if is_stereo:
        progress_callback(35, "ENCODING_STEREO", "Encoding stereo into Mid/Side spatial domains")
        mid, side = encode_mid_side(audio)
        channels_to_process = [("mid", mid), ("side", side)]
    else:
        channels_to_process = [("mono", audio)]

    processed_channels = []
    for ch_name, ch_audio in channels_to_process:
        if cancel_check():
            return False

        # Stage A: High-pass rumble filter (< 75Hz)
        progress_callback(45, "PRE_FILTERING", f"Applying 70Hz rumble filter ({ch_name} channel)")
        ch_hp = apply_highpass(ch_audio, cutoff_hz=cfg["rumble_cutoff"])

        # Stage B: Wiener spectral gating
        progress_callback(55, "SPECTRAL_GATING", f"Wiener multi-band spectral gating ({ch_name} channel)")
        ch_gated = process_audio_chunked_or_direct(
            ch_hp,
            lambda blk: apply_spectral_gating(blk, over_subtract=cfg["spectral_oversub"], floor=cfg["spectral_floor"]),
            threshold_seconds=CHUNK_THRESHOLD_SECONDS
        )
        del ch_hp

        # Stage C: DeepFilterNet3 neural inference
        progress_callback(70, "NEURAL_SUPPRESSION", f"DeepFilterNet3 neural enhancement ({ch_name} channel)")
        df_model, df_state = model_registry.get_deepfilternet_model(post_filter=cfg["dfn_postfilter"])

        def run_dfn_block(blk: np.ndarray) -> np.ndarray:
            audio_tensor = torch.from_numpy(blk[np.newaxis, :]).float()
            with torch.inference_mode():
                from df.enhance import enhance
                df_out = enhance(df_model, df_state, audio_tensor, atten_lim_db=cfg["dfn_atten_lim"])
                out_np = df_out.squeeze().cpu().numpy().astype(np.float32)
            del audio_tensor, df_out
            return out_np

        ch_denoised = process_audio_chunked_or_direct(
            ch_gated,
            run_dfn_block,
            threshold_seconds=CHUNK_THRESHOLD_SECONDS
        )
        del ch_gated
        memory_guard.cleanup()

        # Match length
        n = len(ch_audio)
        if len(ch_denoised) < n:
            ch_denoised = np.pad(ch_denoised, (0, n - len(ch_denoised)))
        elif len(ch_denoised) > n:
            ch_denoised = ch_denoised[:n]

        # Stage D: Dual-Band VAD Gating
        progress_callback(82, "VAD_GATING", f"Dual-band voice activity gating ({ch_name} channel)")
        ch_vad = apply_vad_gating(ch_denoised, aggressiveness=cfg["vad_strength"])
        del ch_denoised

        # Stage E: Dynamics (AGC Leveler + Compressor + Limiter)
        progress_callback(88, "DYNAMICS", f"AGC speech leveling and compression ({ch_name} channel)")
        ch_dyn = apply_dynamics(ch_vad, comp_ratio=cfg["compressor_ratio"])
        del ch_vad

        # Stage F: Mastering EQ, De-Essing & EBU R128 Loudness
        progress_callback(93, "MASTERING", f"Voice EQ, de-essing and EBU R128 loudness ({ch_name} channel)")
        ch_final = apply_tone_mastering(ch_dyn, target_lufs=cfg["target_lufs"])
        del ch_dyn
        memory_guard.cleanup()

        processed_channels.append(ch_final)

    if cancel_check():
        return False

    # Step 4: Reconstruct Stereo / Mono
    progress_callback(97, "RECONSTRUCTING", "Reconstructing output audio container")
    if is_stereo:
        final_audio = decode_mid_side(processed_channels[0], processed_channels[1])
    else:
        final_audio = processed_channels[0]

    # Step 5: Save output WAV
    progress_callback(99, "SAVING", "Writing master audio file to disk")
    save_audio(output_path, final_audio, sr=SAMPLE_RATE)
    del final_audio, processed_channels
    memory_guard.cleanup()

    progress_callback(100, "DONE", "Audio enhancement completed successfully")
    return True
