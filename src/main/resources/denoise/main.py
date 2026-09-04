"""
main.py — Master orchestrator for the 48kHz audio enhancement DSP pipeline.
"""

import sys
import gc

import io_utils
import vad_gate
import denoise_dfn
import dynamics
import tone
import demucs_stage


def run_pipeline(input_path, output_path, use_demucs=False, mode="balanced"):
    io_utils.validate_input_path(input_path)

    print("PROGRESS: Analyzing input & channel splitting", flush=True)
    split = io_utils.load_and_split_channels(input_path)
    audio_data = split["audio_data"]
    side_channel = split["side_channel"]
    is_stereo = split["is_stereo"]
    source_is_real_stereo = split["source_is_real_stereo"]

    # Stage 1 + 1.5: Pre-filtering & Wiener spectral noise subtraction
    print("PROGRESS: Pre-filtering & spectral noise subtraction", flush=True)
    settings = denoise_dfn.MODE_SETTINGS.get(mode, denoise_dfn.MODE_SETTINGS["balanced"])
    audio_data = denoise_dfn.apply_highpass(audio_data, cutoff_hz=70.0)
    audio_data = denoise_dfn.spectral_subtract(
        audio_data,
        over_subtract=settings["over_subtract"],
        floor=settings["floor"]
    )
    gc.collect()

    # Stage 2: Dual-band VAD & speech gating
    print("PROGRESS: Voice activity detection & gating", flush=True)
    audio_data, vad_gain = vad_gate.apply_vad_gate(audio_data)
    gc.collect()

    # Stage 3: DeepFilterNet neural noise suppression at 48kHz
    print("PROGRESS: DeepFilterNet neural noise suppression", flush=True)
    audio_data = denoise_dfn.apply_deepfilternet(
        audio_data,
        atten_lim_db=settings["atten_lim_db"],
        post_filter=settings.get("post_filter", False)
    )
    gc.collect()

    # Stage 4: Dynamic range leveling & limiting
    print("PROGRESS: Dynamic range leveling & limiting", flush=True)
    audio_data = dynamics.process(audio_data)
    gc.collect()

    # Optional Stage 5: Demucs vocal isolation
    if use_demucs:
        print("PROGRESS: Isolating vocal stems (Demucs)", flush=True)
        audio_data = demucs_stage.apply_demucs_separation(audio_data)
        gc.collect()

    # Stage 6: 5-band EQ, dynamic de-essing & LUFS normalization
    print("PROGRESS: EQ, dynamic de-essing & loudness normalization", flush=True)
    audio_data = tone.process(audio_data, vad_gain)
    del vad_gain
    gc.collect()

    # Stage 7: Mid/Side reconstruction & true-peak ceiling
    print("PROGRESS: Reconstructing output", flush=True)
    final_output = io_utils.reconstruct_output(
        audio_data, side_channel, is_stereo, source_is_real_stereo
    )
    del audio_data, side_channel
    io_utils.save_output(output_path, final_output, is_stereo)
    del final_output
    gc.collect()


def main():
    if len(sys.argv) < 3:
        print("ERROR: usage: main.py <input_path> <output_path> [--demucs] [--mode <mode>]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    use_demucs = "--demucs" in sys.argv

    mode = "balanced"
    for i, arg in enumerate(sys.argv):
        if arg == "--mode" and i + 1 < len(sys.argv):
            mode = sys.argv[i + 1]
        elif arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]

    try:
        run_pipeline(input_path, output_path, use_demucs=use_demucs, mode=mode)
    except Exception as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()