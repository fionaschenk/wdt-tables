#!/usr/bin/env python3
"""Build supplementary-material tables for GitHub Pages.

One stage, csv2html:

    render each  data/<stem>.csv  ->  docs/<stem>.html
    plus a docs/index.html overview and, per table, downloadable CSV / JSON
    under docs/downloads/.

The CSVs in data/ are the source of record: one file per table, a rectangular
table with the header in row 1 and one value per cell, already carrying the
number formatting it should be published with. Nothing rewrites them, so a
correction is made in the CSV itself and shows up on the next build.

The HTML pages embed the table data at build time (no runtime fetch), so they
work both locally (double-click) and on GitHub Pages. Interactivity (search /
sort / paginate) is provided by DataTables, loaded from a CDN.

Run from anywhere; all paths are resolved relative to the repository root
(the parent of this script's  py/  folder).

    python py/build_tables.py
    python py/build_tables.py --verbose
    python py/build_tables.py --dry-run
    python py/build_tables.py --no-clean

British English is used throughout the table labels.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration  (edit here; no hardcoded assumptions further down)
# ---------------------------------------------------------------------------

# All paths come from the shared module, so a folder move is a one-line change
# there rather than an edit in every script (see py/wd_paths.py).
import wd_paths

REPO_ROOT = wd_paths.ROOT
CSV_DIR = wd_paths.CSV                 # input  : *.csv   (one table per file)
DOCS_DIR = wd_paths.DOCS               # output : *.html  (served by Pages)
DOWNLOADS_DIR = wd_paths.DOWNLOADS     # output : per-table .csv and .json for download
TEMPLATES_DIR = wd_paths.TEMPLATES
STYLE_SRC = TEMPLATES_DIR / "style.css"        # canonical style ("Stil"-Datei)
CAPTIONS_FILE = wd_paths.CAPTIONS              # metadata per table (see below)

CSV_DELIMITER = ","                    # delimiter of the source CSVs
CSV_ENCODING = "utf-8"                 # encoding of the source CSVs (no BOM)

SITE_TITLE = "Supplementary Tables"    # shown on the index page
SITE_INTRO = (                         # optional intro paragraph on the index
    "Supplementary data tables."
)
TABLE_LABEL = "Table"                  # short label word; "Table 1", "Table 2", ...
                                       # (set to "Tabelle" for German labels)
DOCS_KEEP = {                          # entries in docs/ preserved when clearing it
    "CNAME",                           # GitHub Pages custom domain
    ".nojekyll",                       # stop Pages from running Jekyll over the site
}

# Links shown in the index page's header. Empty here: this variant publishes the
# tables only. The RDF branch fills it with the query page, the ontology
# documentation and the graph bundle.
NAV_LINKS: list[dict[str, str]] = []

# DataTables / jQuery CDN (pinned versions). Vendoring locally is possible
# by downloading these into docs/ and changing the paths in the templates.
DATATABLES_VERSION = "2.1.8"
JQUERY_VERSION = "3.7.1"


# ---------------------------------------------------------------------------
# csv -> html
# ---------------------------------------------------------------------------

def read_csv(csv_path: Path) -> tuple[list[str], list[list[str]]]:
    with csv_path.open("r", newline="", encoding=CSV_ENCODING) as fh:
        reader = csv.reader(fh, delimiter=CSV_DELIMITER)
        all_rows = [row for row in reader]
    if not all_rows:
        return [], []
    return all_rows[0], all_rows[1:]


def load_captions(announce: bool = True) -> dict[str, dict]:
    """Load data/captions.yaml, indexed so a CSV stem always resolves.

    Each entry may carry: caption, captiondetail, parsinginfo, title, license,
    data-creator and an optional ``chem_columns`` list. Entries are indexed by
    their YAML key and by their ``title`` field.
    """
    if not CAPTIONS_FILE.exists():
        if announce:
            print(f"[captions] WARNING: {CAPTIONS_FILE} not found -> no captions loaded")
        return {}
    import yaml
    with CAPTIONS_FILE.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if announce:
        print(f"[captions] read {CAPTIONS_FILE} ({len(data)} top-level entries)")

    index: dict[str, dict] = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            if announce:
                print(f"[captions] WARNING: top-level '{key}' is a bare value, not a "
                      "table block -> likely a mis-indented field (check the indentation "
                      "of license/data-creator under the table key)")
            value = {"caption": str(value)}
        chem_cols = value.get("chem_columns")
        entry = {
            "caption": str(value.get("caption", "")),
            "captiondetail": str(value.get("captiondetail", "")),
            "parsinginfo": str(value.get("parsinginfo", "")),
            "title": str(value.get("title", "")),
            "license": str(value.get("license", "")),
            "data_creator": str(value.get("data-creator", value.get("data_creator", ""))),
            "chem_columns": chem_cols if isinstance(chem_cols, list) else None,
            "_raw_keys": sorted(str(k) for k in value.keys()),
        }
        index[str(key)] = entry
        title = entry["title"]
        if title and title not in index:      # fallback lookup by title field
            index[title] = entry
    return index


def resolve_meta(captions: dict[str, dict], stem: str) -> dict:
    """Find a table's metadata by exact stem, then by its 'Table N' number.

    This tolerates a file named 'Table1_Lithology_of_WD1' resolving to a
    captions key/title of just 'Table1' (and vice versa).
    """
    if stem in captions:
        return captions[stem]
    m = re.match(r"^\s*Table\s*0*(\d+)", stem, flags=re.IGNORECASE)
    if m:
        key = f"Table{int(m.group(1))}"
        if key in captions:
            return captions[key]
    return {}


def short_label(stem: str, meta: dict[str, str]) -> str:
    """Human label for a table: 'Table 1' derived from a 'Table1_...' stem."""
    m = re.match(r"^\s*Table\s*0*(\d+)", stem, flags=re.IGNORECASE)
    if m:
        return f"{TABLE_LABEL} {int(m.group(1))}"
    return meta.get("title") or stem


def sort_key(stem: str) -> tuple:
    """Order tables numerically (Table 1, 2, ... 10) rather than lexically."""
    m = re.match(r"^\s*Table\s*0*(\d+)", stem, flags=re.IGNORECASE)
    return (0, int(m.group(1))) if m else (1, stem.lower())


def write_json(header: list[str], body: list[list[str]], json_path: Path) -> None:
    """Write the table as a JSON array of row objects (values kept verbatim)."""
    records = [dict(zip(header, row)) for row in body]
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)


def cc_license(license_str: str) -> tuple[str, str]:
    """From a licence string, return (short_code, deed_url) if it is a CC licence.

    'CC BY-SA 4.0, Fiona Schenk' -> ('CC BY-SA 4.0',
                                     'https://creativecommons.org/licenses/by-sa/4.0/')
    Returns ('', '') when no Creative Commons code is recognised.
    """
    m = re.search(r"CC[\s-]+([A-Za-z][A-Za-z-]*)\s+(\d\.\d)", license_str or "")
    if not m:
        return "", ""
    code, version = m.group(1).upper(), m.group(2)
    url = f"https://creativecommons.org/licenses/{code.lower()}/{version}/"
    return f"CC {code} {version}", url


def license_html(license_str: str, short: str, url: str):
    """Return the licence string with only its CC code hyperlinked (safe markup)."""
    from markupsafe import Markup, escape
    if not license_str:
        return Markup("")
    if url and short and short in license_str:
        before, after = license_str.split(short, 1)
        return Markup('{}<a href="{}" target="_blank" rel="noopener">{}</a>{}').format(
            before, url, short, after)
    return escape(license_str)


def license_short_html(short: str, url: str, fallback: str):
    """Compact licence for the index: linked CC code, else the plain string."""
    from markupsafe import Markup, escape
    if url and short:
        return Markup('<a href="{}" target="_blank" rel="noopener">{}</a>').format(url, short)
    return escape(fallback or "")


# Real element symbols, so sample codes like 'G1', 'UT6', 'WD1' are never
# mistaken for formulae (G, R, D, T ... are not elements).
_ELEMENTS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si",
    "P", "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni",
    "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb",
    "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe",
    "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho",
    "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np",
    "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg",
    "Bh", "Hs", "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
}
_ELEM_GROUP = re.compile(r"([A-Z][a-z]?)(\d*)")


def _chem_token(token: str) -> str:
    """One token as safe HTML: leading digits -> <sup> (isotope mass number),
    counts after a *real* element symbol -> <sub>. Anything that isn't a valid
    formula/isotope (incl. sample codes like 'G1', 'UT6') is returned escaped.
    """
    from markupsafe import escape
    plain = str(escape(token))
    if not token or not any(c.isdigit() for c in token):
        return plain                       # nothing to sub/superscript
    lead, rest = re.match(r"^(\d*)(.*)$", token).groups()

    groups: list[tuple[str, str]] = []
    pos = 0
    for gm in _ELEM_GROUP.finditer(rest):
        if gm.start() != pos or gm.group(1) not in _ELEMENTS:
            return plain                   # gap or non-element -> not a formula
        groups.append((gm.group(1), gm.group(2)))
        pos = gm.end()
    if pos != len(rest) or not groups:
        return plain

    parts = [f"<sup>{lead}</sup>"] if lead else []
    for sym, count in groups:
        parts.append(sym)
        if count:
            parts.append(f"<sub>{count}</sub>")
    return "".join(parts)


def chemify(text: str):
    """HTML display of chemical formulae and isotopes (safe markup).

    Formulae get subscripted counts (SiO2 -> SiO<sub>2</sub>), isotopes get a
    superscripted mass number (89Y -> <sup>89</sup>Y). '/'-separated parts are
    handled individually so isotope ratios (87Sr/86Sr) render correctly.
    Ordinary labels and sample codes are left untouched.
    """
    from markupsafe import Markup
    return Markup("/".join(_chem_token(p) for p in (text or "").split("/")))


def chem_column_indices(chem_columns, header: list[str]) -> set[int]:
    """Resolve a captions ``chem_columns`` list to 0-based column indices.

    Entries may be 1-based integers (``[1]`` = first column) or exact header
    names (``["Isotope"]``). Unknown entries are ignored.
    """
    idx: set[int] = set()
    for c in chem_columns or []:
        if isinstance(c, bool):
            continue
        if isinstance(c, int):
            if 1 <= c <= len(header):
                idx.add(c - 1)
        else:
            name = str(c)
            for i, h in enumerate(header):
                if h == name:
                    idx.add(i)
    return idx


def get_jinja_env():
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),  # escapes cell content
        trim_blocks=True,
        lstrip_blocks=True,
    )


def copy_style(dry_run: bool) -> None:
    dest = DOCS_DIR / "style.css"
    if dry_run:
        print(f"[csv2html] (dry-run) copy style.css -> {dest.relative_to(REPO_ROOT)}")
        return
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(STYLE_SRC, dest)


def clean_dir(directory: Path, keep: set[str], dry_run: bool, label: str) -> None:
    """Empty a generated directory before a rebuild so removed/renamed inputs
    leave no orphan outputs. Names in ``keep`` are preserved (e.g. a Pages CNAME).
    """
    if not directory.exists():
        return
    removed = 0
    for item in sorted(directory.iterdir()):
        if item.name in keep:
            continue
        removed += 1
        if dry_run:
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    suffix = " (dry-run)" if dry_run else ""
    print(f"[{label}] cleaned {directory.name}/ ({removed} item(s) removed{suffix})")


# ---------------------------------------------------------------------------
# Per-table semantic RDF (Turtle) — reuses the ontology pipeline in  py/rdf/
# ---------------------------------------------------------------------------

RDF_DIR = wd_paths.PY / "rdf"        # the semantic pipeline (build_rdf.py), if present


def semantic_ttl(stem: str, csv_path: Path, meta: dict, out_dir: Path,
                 verbose: bool = False) -> bool:
    """Write ``downloads/<stem>.ttl`` using py/rdf/build_rdf.py's per-table modelling.

    Returns True if a Turtle graph was written. On this branch ``py/rdf/`` does
    not exist, so the function returns False immediately and no page offers a
    Turtle download; the hook is kept so the two branches share one file.
    """
    if not RDF_DIR.is_dir():
        return False
    m = re.match(r"^\s*Table\s*0*(\d+)", stem, flags=re.IGNORECASE)
    if not m:
        return False
    n = int(m.group(1))
    try:
        if str(RDF_DIR) not in sys.path:
            sys.path.insert(0, str(RDF_DIR))
        from build_rdf import graph_for_table, TABLES  # type: ignore
        if n not in TABLES:
            return False
        g = graph_for_table(n, csv_path, meta)
        out_dir.mkdir(parents=True, exist_ok=True)
        g.serialize(str(out_dir / f"{stem}.ttl"), format="turtle")
        if verbose:
            print(f"[csv2html] {stem}: semantic TTL ({len(g)} triples)")
        return True
    except Exception as exc:                       # keep the table build robust
        print(f"[csv2html] note: no semantic TTL for '{stem}' ({exc})")
        return False


def stage_csv2html(verbose: bool, dry_run: bool, clean: bool = True) -> list[dict]:
    csv_files = sorted(CSV_DIR.glob("*.csv"), key=lambda p: sort_key(p.stem))
    if not csv_files:
        print(f"[csv2html] no .csv files found in {CSV_DIR}")
        return []

    if clean:
        clean_dir(DOCS_DIR, DOCS_KEEP, dry_run=dry_run, label="csv2html")

    captions = load_captions()
    env = get_jinja_env()
    table_tpl = env.get_template("table.html.j2")
    index_tpl = env.get_template("index.html.j2")

    entries: list[dict] = []
    for csv_path in csv_files:
        stem = csv_path.stem
        header, body = read_csv(csv_path)
        meta = resolve_meta(captions, stem)
        if not meta:
            print(f"[csv2html] WARNING: no captions.yaml entry for '{stem}' "
                  "-> using derived label, empty caption")
        label = short_label(stem, meta)
        licence = meta.get("license", "")
        data_creator = meta.get("data_creator", "")
        licence_short, licence_url = cc_license(licence)
        licence_html = license_html(licence, licence_short, licence_url)
        if not licence or not data_creator:
            missing = [n for n, v in (("license", licence),
                                      ("data-creator", data_creator)) if not v]
            found = ", ".join(meta.get("_raw_keys", [])) or "no entry matched"
            print(f"[csv2html] WARNING: '{stem}' has no {', '.join(missing)} "
                  f"in captions.yaml (fields found for this entry: {found})")
        out_path = DOCS_DIR / f"{stem}.html"
        has_ttl = False

        if dry_run:
            print(f"[csv2html] (dry-run) {csv_path.name} -> "
                  f"{out_path.relative_to(REPO_ROOT)} ({len(body)} rows) "
                  f"+ downloads/{stem}.csv,.json")
        else:
            # downloadable source files (served alongside the pages)
            DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(csv_path, DOWNLOADS_DIR / f"{stem}.csv")
            write_json(header, body, DOWNLOADS_DIR / f"{stem}.json")
            has_ttl = semantic_ttl(stem, csv_path, meta, DOWNLOADS_DIR, verbose)

            # chemical/isotope notation in configured data columns (display only)
            chem_idx = chem_column_indices(meta.get("chem_columns"), header)
            display_rows = body
            if chem_idx:
                display_rows = [
                    [chemify(v) if i in chem_idx else v for i, v in enumerate(row)]
                    for row in body
                ]

            html = table_tpl.render(
                label=label,
                caption=meta.get("caption", ""),
                captiondetail=meta.get("captiondetail", ""),
                parsinginfo=meta.get("parsinginfo", ""),
                header=[chemify(h) for h in header], rows=display_rows, stem=stem,
                has_ttl=has_ttl,
                license_html=licence_html,
                data_creator=data_creator,
                datatables_version=DATATABLES_VERSION, jquery_version=JQUERY_VERSION,
            )
            DOCS_DIR.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html, encoding="utf-8")
            if verbose:
                print(f"[csv2html] {csv_path.name} -> "
                      f"{out_path.relative_to(REPO_ROOT)} ({len(body)} rows) "
                      f"+ CSV/JSON downloads")

        entries.append({
            "stem": stem, "label": label,
            "caption": meta.get("caption", ""),
            "href": f"{stem}.html", "n_rows": len(body), "n_cols": len(header),
            "license_html": licence_html,
            "license_short_html": license_short_html(licence_short, licence_url, licence),
            "data_creator": data_creator,
            "has_ttl": has_ttl,
        })

    if dry_run:
        print(f"[csv2html] (dry-run) -> "
              f"{(DOCS_DIR / 'index.html').relative_to(REPO_ROOT)} ({len(entries)} tables)")
    else:
        index_html = index_tpl.render(
            site_title=SITE_TITLE, intro=SITE_INTRO, entries=entries,
            nav_links=NAV_LINKS,
        )
        (DOCS_DIR / "index.html").write_text(index_html, encoding="utf-8")
        copy_style(dry_run=False)
        (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")  # serve verbatim
        if verbose:
            print(f"[csv2html] -> docs/index.html ({len(entries)} tables)")

    print(f"[csv2html] {len(entries)} page(s) + index generated.")
    return entries


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true",
                        help="print one line per file")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would happen without writing files")
    parser.add_argument("--no-clean", action="store_true",
                        help="do not empty docs/ before rebuilding it")
    args = parser.parse_args(argv)

    print(f"Repository root: {REPO_ROOT}")
    stage_csv2html(verbose=args.verbose, dry_run=args.dry_run,
                   clean=not args.no_clean)
    return 0


if __name__ == "__main__":
    sys.exit(main())