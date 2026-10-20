#!/usr/bin/env python3
"""
Command-line session runner for prompt-based video editing engine.
Accepts a JSON or YAML session file, executes instructions sequentially using the real engine,
records results to results.json, and exits with non-zero on assertion failure.
"""

import argparse
import sys
from pathlib import Path
from app.models.db import init_db
from app.services.session_service import SessionExecutionError, execute_session, load_session_file


def main():
    parser = argparse.ArgumentParser(description="Deterministic Session Runner for Video Editing Engine")
    parser.add_argument("session_file", help="Path to YAML or JSON session configuration file")
    parser.add_argument("--output", "-o", default="results.json", help="Path to output results.json (default: results.json)")
    args = parser.parse_args()

    # Initialize database
    init_db()

    session_path = Path(args.session_file)
    if not session_path.is_file():
        print(f"Error: Session file '{args.session_file}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        data = load_session_file(session_path)
        print(f"Loaded session '{session_path.name}' with {len(data.get('instructions', []))} instructions.")
        results = execute_session(data, output_results_path=args.output)
        print(f"Session executed successfully!")
        print(f"  Final Revision: {results['final_revision']}")
        print(f"  Final Duration: {results['final_duration_s']:.3f}s")
        print(f"  Final Hash: {results['final_timeline_hash']}")
        print(f"  Results saved to: {args.output}")
        sys.exit(0)
    except SessionExecutionError as e:
        print(f"Session Assertion Failure: {str(e)}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Unexpected Execution Error: {str(e)}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
