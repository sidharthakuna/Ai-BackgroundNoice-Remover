"""
main.py — pipeline orchestrator. Run this file directly:

    python3 main.py <input_path> <output_path> [--demucs]

EDIT THIS FILE IF you need to change:
  - The ORDER stages run in
  - Command-line argument handling
  - The top-level error message format (the "ERROR:" prefix that
    NoiseRemovalService.java parses)

DO NOT put DSP logic here. If you're tuning a filter, threshold, or gain
value, you want one of the other modules -- see the table below.

  Symptom you're chasing          -> File to open
  ---------------------------------------------------------------------
  Rumble/low-end noise            -> denoise_dfn.py (apply_highpass)
  Background hiss/hum surviving   -> denoise_dfn.py (apply_deepfilternet,
                                      atten_lim_db)
  Mumbled words getting silenced  -> vad_gate.py (silence floor, VAD
                                      aggressiveness, energy threshold)
  Volume pumping/breathing        -> dynamics.py (read the module
                                      docstring FIRST -- there's
                                      documented history here)
  Muddy / too bright / not clear  -> tone.py (apply_eq band gains)
  Overall too quiet / too loud    -> tone.py (apply_loudness_normalization,
                                      target_lufs)
  Stereo width / channel issues   -> io_utils.py (real-stereo detection,
                                      reconstruct_output)
  Demucs vocal isolation           -> demucs_stage.py

WHY vad_gain AND side_channel LIVE HERE, NOT IN A SHARED STATE OBJECT:
Both are computed by one stage and consumed by a much later one --
vad_gain by vad_gate.py, used again in tone.py's exciter; side_channel by
io_utils.py's channel split, used again in io_utils.py's reconstruction
at the very end. Rather than threading an untyped shared dict through
every function (which makes it hard to tell what any given stage
actually needs just by reading its signature), this file holds both as
plain local variables and passes them explicitly to whichever function
needs them. If a stage's signature doesn't take vad_gain or
side_channel, it doesn't use them -- that's now visible from the
function definition alone, not from tracing a shared object.
"""

import sys

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
    side_channel = split["side_channel"]          # used again at the very end
    is_stereo = split["is_stereo"]
    source_is_real_stereo = split["source_is_real_stereo"]

    # Stage 1 + 1.5 (highpass, spectral subtraction)
    print("PROGRESS: Pre-filtering & spectral noise subtraction", flush=True)
    settings = denoise_dfn.MODE_SETTINGS.get(mode, denoise_dfn.MODE_SETTINGS["balanced"])
    audio_data = denoise_dfn.apply_highpass(audio_data)
    audio_data = denoise_dfn.spectral_subtract(
        audio_data,
        over_subtract=settings["over_subtract"],
        floor=settings["floor"]
    )

    print("PROGRESS: Voice activity detection & gating", flush=True)
    audio_data, vad_gain = vad_gate.apply_vad_gate(audio_data)

    print("PROGRESS: DeepFilterNet neural noise suppression", flush=True)
    audio_data = denoise_dfn.apply_deepfilternet(
        audio_data,
        atten_lim_db=settings["atten_lim_db"],
        post_filter=settings.get("post_filter", False)
    )

    print("PROGRESS: Dynamic range leveling & limiting", flush=True)
    audio_data = dynamics.process(audio_data)

    if use_demucs:
        print("PROGRESS: Isolating vocal stems (Demucs)", flush=True)
        audio_data = demucs_stage.apply_demucs_separation(audio_data)

    print("PROGRESS: EQ, dynamic de-essing & loudness normalization", flush=True)
    audio_data = tone.process(audio_data, vad_gain)

    print("PROGRESS: Reconstructing output", flush=True)
    final_output = io_utils.reconstruct_output(
        audio_data, side_channel, is_stereo, source_is_real_stereo
    )
    io_utils.save_output(output_path, final_output, is_stereo)

    import gc
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