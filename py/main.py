#!/usr/bin/env python3
"""wdttest-tables — single entry point for the whole pipeline.

    python py/main.py                    # everything, in dependency order
    python py/main.py tables             # one phase only
    python py/main.py --list             # show phases and their steps
    python py/main.py --dry-run          # print the plan, run nothing
    python py/main.py --verbose          # show each step's own output

Phases run in the order below, because each consumes what the previous one
wrote. A first run therefore has to be a full run (or the phases in order);
afterwards any phase can be re-run on its own.

    tables    data/*.csv  ->  docs/*.html
              + per-table CSV and JSON under docs/downloads/
    metadata  metadata.yaml + data.yaml + data/captions.yaml
              ->  the generated README blocks

This is the submission variant: the table site only. The RDF pipeline (the
instance graph, the ontology modules, the SPARQL page) lives on the ``v0.1_rdf``
branch, which adds the ``rdf`` and ``docs`` phases back.

Every step is also runnable on its own, e.g. ``python py/build_tables.py``;
this orchestrator is a convenience, not the only path.
"""

from __future__ import annotations

import argparse
import importlib
import io
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))          # <repo>/py

import wd_paths  # noqa: E402

# ---------------------------------------------------------------------------
# Phase definitions:  phase -> [(step name, module, callable, argv, kwargs)]
# ---------------------------------------------------------------------------
# Modules are imported lazily, so --list and --dry-run need no heavy imports
# and a missing optional dependency only bites the phase that needs it.
# `argv` is what the step would have been given on the command line; `kwargs`
# is for steps that take Python arguments instead.

Step = tuple[str, str, str, list[str], dict]

PHASES: dict[str, list[Step]] = {
    "tables": [
        ("csv2html", "build_tables", "main", [], {}),
    ],
    "metadata": [
        ("make-metadata", "make_metadata", "main", [], {}),
    ],
}

PHASE_HELP = {
    "tables": "the data/ CSVs -> HTML pages + downloads",
    "metadata": "metadata.yaml/data.yaml -> the generated README blocks",
}


def run_step(name: str, module: str, func: str, argv: list[str],
             kwargs: dict, verbose: bool) -> tuple[bool, float, str]:
    """Import a step and call it, capturing its output unless --verbose.

    Steps parse ``sys.argv`` themselves, so it is set for the duration of the
    call and restored afterwards. Returns (ok, seconds, captured output).
    """
    started = time.perf_counter()
    saved_argv = sys.argv
    buffer = io.StringIO()
    try:
        sys.argv = [f"{module}.py", *argv]
        mod = importlib.import_module(module)
        entry = getattr(mod, func)
        if verbose:
            entry(**kwargs)
        else:
            with redirect_stdout(buffer):
                entry(**kwargs)
        return True, time.perf_counter() - started, buffer.getvalue()
    except SystemExit as exc:                    # argparse/--help inside a step
        ok = exc.code in (0, None)
        return ok, time.perf_counter() - started, buffer.getvalue()
    except Exception as exc:                     # noqa: BLE001 — report and stop
        out = buffer.getvalue() + f"\n{type(exc).__name__}: {exc}\n"
        return False, time.perf_counter() - started, out
    finally:
        sys.argv = saved_argv


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the wdttest-tables site and its README metadata.")
    parser.add_argument("phase", nargs="?", default="all",
                        choices=["all", *PHASES],
                        help="phase to run (default: all)")
    parser.add_argument("--list", action="store_true",
                        help="list the phases and their steps, then exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would run, without running it")
    parser.add_argument("--verbose", action="store_true",
                        help="show each step's own output as it runs")
    args = parser.parse_args()

    if args.list:
        print("Phases (in dependency order):\n")
        for phase, steps in PHASES.items():
            print(f"  {phase:<9} {PHASE_HELP[phase]}")
            for name, module, _, argv, _kw in steps:
                extra = " " + " ".join(argv) if argv else ""
                print(f"      - {name:<14} {module}.py{extra}")
        print("\n  python py/main.py [phase]   (default: all)")
        return 0

    selected = list(PHASES) if args.phase == "all" else [args.phase]
    plan = [(phase, step) for phase in selected for step in PHASES[phase]]

    print(f"Python : {sys.executable}")
    print(f"Repo   : {wd_paths.ROOT}")
    print(f"Phases : {', '.join(selected)}\n")

    if args.dry_run:
        for phase, (name, module, _, argv, _kw) in plan:
            extra = " " + " ".join(argv) if argv else ""
            print(f"  would run  {phase}/{name:<14} {module}.py{extra}")
        print("\nDry run — nothing was written.")
        return 0

    wd_paths.ensure_dirs()

    results: list[tuple[str, str, bool, float]] = []
    for index, (phase, (name, module, func, argv, kwargs)) in enumerate(plan, 1):
        print(f"[{index}/{len(plan)}] {phase}/{name}")
        ok, seconds, output = run_step(name, module, func, argv, kwargs, args.verbose)
        results.append((phase, name, ok, seconds))
        if not ok:
            if output and not args.verbose:
                print(output.rstrip())
            print(f"  -> FAILED  ({seconds:.1f}s)\n")
            break                                # fail fast: later phases read this one
        print(f"  -> ok      ({seconds:.1f}s)")

    print("\nSummary")
    print("-------")
    for phase, name, ok, seconds in results:
        print(f"  {'ok' if ok else 'FAILED':<8} {seconds:6.1f}s  {phase}/{name}")

    completed = len(results) == len(plan) and all(ok for _, _, ok, _ in results)
    print("\nAll phases completed successfully." if completed
          else "\nStopped on error — see the failing step above.")
    return 0 if completed else 1


if __name__ == "__main__":
    sys.exit(main())
