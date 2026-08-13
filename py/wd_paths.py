#!/usr/bin/env python3
"""Shared path constants for the wdttest-tables pipeline (submission variant).

Every script resolves its paths through this module rather than recomputing
``Path(__file__)`` chains of its own, so moving a folder is a one-line change
here instead of an edit in five places.

Layout (all paths relative to the repository root):

    data/                 input   the table CSVs (one per table) and
                                  captions.yaml; the CSVs are the source of
                                  record and are what the pages are rendered
                                  from - nothing in this repository writes them
    docs/                 output  the GitHub Pages site
    py/                   code    build_tables.py, make_metadata.py, main.py

This variant carries the table pipeline only. The RDF pipeline (``py/rdf/``,
``metadata/ontology/``, ``queries.yaml``) lives on the ``v0.1_rdf`` branch and
declares its own path constants there.
"""

from __future__ import annotations

from pathlib import Path

# --- roots -----------------------------------------------------------------
PY = Path(__file__).resolve().parent           # <repo>/py
ROOT = PY.parent                               # <repo>

# --- input -----------------------------------------------------------------
DATA = ROOT / "data"                           # table CSVs + captions.yaml
CSV = DATA                                     # where the source CSVs are read from
CAPTIONS = DATA / "captions.yaml"              # per-table captions, creators, licences
TEMPLATES = PY / "templates"                   # Jinja2 templates + canonical style.css

# --- generated outputs -----------------------------------------------------
DOCS = ROOT / "docs"                           # GitHub Pages site
DOWNLOADS = DOCS / "downloads"                 # per-table csv + json downloads


def ensure_dirs() -> None:
    """Create every generated directory, so no step has to guard for itself."""
    for path in (DOCS, DOWNLOADS):
        path.mkdir(parents=True, exist_ok=True)
