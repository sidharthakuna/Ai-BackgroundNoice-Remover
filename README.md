# denoise/ — audio DSP pipeline

Run via `main.py`, staged onto disk per-job by
`com.sidhartha.denoise.DenoiseScriptStager` and invoked by
`com.sidhartha.denoise.DenoiseProcessRunner` (see the Java `denoise/`
package). This file exists mainly so `io_utils.py`'s "see the package
README" reference points at something real — the content below was
already documented across each module's own docstring; this just
collects it in one place.

## Which file to open

| Symptom you're chasing | File |
|---|---|
| Rumble / low-end noise | `denoise_dfn.py` (`apply_highpass`) |
| Background hiss/hum surviving | `denoise_dfn.py` (`apply_deepfilternet`, `atten_lim_db`, modes: `balanced`/`aggressive`/`gentle`) |
| Harshness/hiss above ~7.5kHz, uncontrolled top end | `denoise_dfn.py` (`apply_lowpass`, default cutoff 7500Hz) |
| Harsh sibilance on "s"/"sh"/"t" consonants | `tone.py` (`apply_deesser`) |
| Mumbled words getting silenced | `vad_gate.py` (silence floor, VAD aggressiveness, energy threshold) |
| Volume pumping / breathing | `dynamics.py` — **read the module docstring first**, there's tested-and-reverted history there |
| Muddy / too bright / not clear | `tone.py` (`apply_eq` band gains) |
| Overall too quiet / too loud | `tone.py` (`apply_loudness_normalization`, `target_lufs`) |
| Stereo width / channel issues | `io_utils.py` (real-stereo detection, `reconstruct_output`) |
| Demucs vocal isolation | `demucs_stage.py` |
| Pipeline order / CLI args / `ERROR:` format | `main.py` |

## Pipeline order (see `main.py::run_pipeline`)

```
load_and_split_channels
  → apply_highpass
  → spectral_subtract          (mode-scaled)
  → apply_vad_gate            (returns vad_gain, reused later)
  → apply_deepfilternet       (mode-scaled: gentle/balanced/aggressive)
  → dynamics.process           (AGC → compressor → limiter)
  → [demucs_stage, if --demucs]
  → tone.process                (EQ → exciter → de-esser → LUFS, needs vad_gain)
  → reconstruct_output          (needs side_channel from the first step)
  → save_output
```


## Rules that don't live in any one file

- **No DSP logic in `io_utils.py` or `main.py`.** Both are explicit about
  this in their own docstrings — `io_utils.py` is "bytes in → arrays
  out" and back, `main.py` is orchestration only. If you're tuning a
  filter, threshold, or gain, you want one of the other modules.
- **`vad_gain` and `side_channel` are plain local variables in
  `main.py`**, not a shared state object, on purpose — see `main.py`'s
  docstring for the reasoning. If you add a new cross-stage value,
  follow the same pattern: pass it explicitly through the function
  signatures that need it rather than threading an untyped dict through
  everything.
- **Order matters** in ways that aren't always obvious from a single
  file — e.g. DFN must run after the VAD gate (see `denoise_dfn.py`),
  AGC must run after DFN's noise-floor reduction (see `dynamics.py`),
  and Demucs runs after dynamics but before LUFS normalization (see
  `demucs_stage.py`). Check the module docstring of both the stage
  you're moving and its immediate neighbors before reordering
  `main.py::run_pipeline`.
- **Tunable values are currently hardcoded defaults** in each function
  signature (`atten_lim_db=30`, `target_rms=0.12`, `target_lufs=-14.0`,
  etc.), not read from config. See the "Externalize DSP parameters"
  suggestion in the backend restructure notes if you want these
  adjustable without a redeploy.