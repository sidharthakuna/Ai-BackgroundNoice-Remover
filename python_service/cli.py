"""
cli.py — Direct CLI runner for the audio enhancement pipeline.
Provides standalone execution and fallback invocation capability for the Java backend.
"""

import sys
import argparse
from python_service.engine import model_registry
from python_service.pipeline import execute_pipeline


def main():
    parser = argparse.ArgumentParser(description="AI Noise Remover CLI Runner")
    parser.add_argument("input_path", help="Path to input audio file")
    parser.add_argument("output_path", help="Path to output audio file")
    parser.add_argument("--mode", default="balanced", choices=["subtle", "balanced", "aggressive", "podcast"], help="Preset DSP mode")
    parser.add_argument("--demucs", action="store_true", help="Enable chunked Demucs vocal isolation")
    parser.add_argument("--job-id", default="cli-job", help="Job ID for logging")

    args = parser.parse_args()

    def progress(pct: int, stage: str, msg: str):
        print(f"PROGRESS: {pct}% [{stage}] {msg}", flush=True)

    try:
        success = execute_pipeline(
            input_path=args.input_path,
            output_path=args.output_path,
            mode=args.mode,
            use_demucs=args.demucs,
            model_registry=model_registry,
            progress_callback=progress,
            cancel_check=lambda: False
        )
        if not success:
            sys.exit(1)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
