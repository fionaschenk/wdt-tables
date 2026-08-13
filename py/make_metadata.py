"""Generate the README metadata blocks from ``metadata.yaml`` and ``data.yaml``.

This step is the bridge between the single sources of truth and the parts of
``README.md`` that must stay in sync with them:

  1. The "Outputs" block, injected between the markers
     ``<!-- METADATA:OUTPUTS:START ... -->`` and ``<!-- METADATA:OUTPUTS:END -->``.
     For a table repository the outputs are read from ``data/captions.yaml``, so
     each table's caption, creator and licence has exactly one home.

  2. The "Data sources" block, injected between the ``METADATA:RAWDATA`` markers
     and generated from ``data.yaml``.

Everything outside the markers (the hand-written prose) is left untouched.

Run standalone (``python py/make_metadata.py``) or as the ``metadata`` phase of
``python py/main.py``. ``pyyaml`` is the only requirement.

EMIT_TTL below is off on this branch: the submission variant publishes the table
site alone and ships no Turtle. The RDF branch sets it to True, which writes the
DCAT/PROV ``metadata/metadata.ttl`` (the FDO metadata bundle that feeds the
wdttest-*-master gallery) and validates it against ``metadata/shapes.ttl``. The
emitting code below is kept identical on both branches so they stay mergeable.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wd_paths import ROOT, ensure_dirs  # noqa: E402

import yaml  # noqa: E402  (pyyaml; required)

META_YAML = ROOT / "metadata.yaml"
DATA_YAML = ROOT / "data.yaml"
OUTPUTS_YAML = ROOT / "outputs.yaml"
CAPTIONS_YAML = ROOT / "data" / "captions.yaml"
META_DIR = ROOT / "metadata"
TTL_OUT = META_DIR / "metadata.ttl"
ONTOLOGY = META_DIR / "ontology.ttl"
SHAPES = META_DIR / "shapes.ttl"
README = ROOT / "README.md"

MARK_START = ("<!-- METADATA:OUTPUTS:START - generated from metadata.yaml by "
              "py/make_metadata.py; do not edit by hand -->")
MARK_END = "<!-- METADATA:OUTPUTS:END -->"

MARK_RAW_START = ("<!-- METADATA:RAWDATA:START - generated from data.yaml by "
                  "py/make_metadata.py; do not edit by hand -->")
MARK_RAW_END = "<!-- METADATA:RAWDATA:END -->"

# Write metadata/metadata.ttl (DCAT/PROV) and run the SHACL gate over it.
# False on the submission branch: no Turtle, no rdflib, no pyshacl. See the
# module docstring.
EMIT_TTL = False

# Known licences -> canonical URIs. Anything else (incl. "TODO") is emitted as a
# flagged licence document so the gap is explicit rather than silently dropped.
LICENSE_URIS = {
    "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC BY 3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "ODbL 1.0": "https://opendatacommons.org/licenses/odbl/1-0/",
    "MIT": "https://spdx.org/licenses/MIT",
}
MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".svg": "image/svg+xml", ".csv": "text/csv", ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".geojson": "application/geo+json", ".json": "application/json",
    ".tab": "text/tab-separated-values", ".tsv": "text/tab-separated-values",
    ".ttl": "text/turtle", ".html": "text/html",
}


def _slug(text):
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def load_meta():
    with open(META_YAML, encoding="utf-8") as fh:
        meta = yaml.safe_load(fh)
    if "repo" not in meta:
        sys.exit("metadata.yaml must contain a 'repo' section.")
    meta.setdefault("outputs", [])
    meta = outputs_from_captions(meta)
    if not meta["outputs"]:
        sys.exit("no outputs: give an 'outputs' section in metadata.yaml, or a "
                 "data/captions.yaml for a table repository.")
    return meta


# Where a table repository publishes the citable copy of each table. The HTML
# page is the landing page a reader lands on; the CSV next to it is the file a
# machine (or the master gallery) fetches, so that is the output's downloadURL.
CAPTION_OUTPUT_DIR = "docs/downloads"
CAPTION_OUTPUT_EXT = ".csv"


def outputs_from_captions(meta):
    """Build one output per table from data/captions.yaml, if that file exists.

    Table repositories keep their per-table captions, creators and licences in
    data/captions.yaml, because the table pipeline renders the pages from it.
    Duplicating those 18 entries into metadata.yaml would be two sources of
    truth for the same strings, so they are read from there instead - the same
    rule that makes figure repos resolve their names from outputs.yaml.

    Table-only rendering fields (parsinginfo, chem_columns, title) are ignored
    here; they mean nothing outside the table pipeline. Outputs written explicitly in metadata.yaml are kept and win on
    an id clash, so a repository can add artefacts that are not tables.
    """
    if not CAPTIONS_YAML.exists():
        return meta
    with open(CAPTIONS_YAML, encoding="utf-8") as fh:
        captions = yaml.safe_load(fh) or {}

    def table_number(key):
        digits = "".join(c for c in key if c.isdigit())
        return int(digits) if digits else 0

    derived = []
    for key in sorted(captions, key=table_number):
        entry = captions[key] or {}
        # captions.yaml states the licence in the geo-lod human style,
        # "CC BY-SA 4.0, Fiona Schenk" - sometimes naming more holders than the
        # single data-creator. Split off the licence label for the machine-
        # readable URI and keep the full string as the rights statement, so no
        # named holder is lost.
        raw_licence = str(entry.get("license", "")).strip()
        licence_label = raw_licence.split(",")[0].strip() if raw_licence else None
        out = {
            "id": key,
            "file": f"{CAPTION_OUTPUT_DIR}/{key}{CAPTION_OUTPUT_EXT}",
            "caption": entry.get("caption", key).strip(),
        }
        if entry.get("captiondetail"):
            out["caption_detail"] = entry["captiondetail"].strip()
        if entry.get("data-creator"):
            out["data_creator"] = entry["data-creator"]
        if licence_label:
            out["license"] = licence_label
            out["rights"] = raw_licence
        derived.append(out)

    explicit = {o["id"]: o for o in meta["outputs"]}
    meta["outputs"] = [o for o in derived if o["id"] not in explicit] + meta["outputs"]
    print(f"  ..  {len(derived)} output(s) taken from {CAPTIONS_YAML.name}")
    return meta


def resolve_output_files(meta):
    """Fill each output's ``file`` from outputs.yaml when it is not given here.

    Output file names live in outputs.yaml (single source of truth). An output
    in metadata.yaml links to one by matching ``id``; this resolves the file to
    ``img/<name>.jpg`` (or ``img/additional/<name>.jpg``). An explicit ``file:``
    in metadata.yaml still wins, so repos without outputs.yaml are unaffected.
    """
    if not OUTPUTS_YAML.exists():
        return meta
    with open(OUTPUTS_YAML, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    names = {}
    for s in cfg.get("figure_sets", []):
        folder = "img" if s.get("dest") == "primary" else "img/additional"
        for fig in s.get("figures", []):
            for out in fig.get("outputs", []):
                names[out["id"]] = f"{folder}/{out['name']}.jpg"
    for out in meta["outputs"]:
        if not out.get("file"):
            resolved = names.get(out["id"])
            if resolved:
                out["file"] = resolved
            else:
                print(f"  !!  output '{out['id']}' has no file: and no matching "
                      f"id in outputs.yaml")
    return meta


# --------------------------------------------------------------------------
# 1) Turtle (DCAT / PROV / SKOS)
# --------------------------------------------------------------------------

def add_raw_data(g, base, ds, raw_data, agent, licence):
    """Emit the data.yaml raw inputs into graph ``g`` as wdt:RawData.

    Each raw input becomes an additional ``dcat:distribution`` of the repository
    dataset ``ds``, typed ``wdt:RawData`` so the master gallery can facet it
    separately from the produced outputs (``wdt:Output``). ``agent`` and
    ``licence`` are the caller's shared, deduplicating factories, so a raw input
    and an output by the same creator merge onto one agent node. Called by
    write_ttl (and reused by the master's sync/verification tooling), so the
    raw-data RDF shape lives in exactly one place.
    """
    from rdflib import Namespace, URIRef, Literal
    from rdflib.namespace import RDF, DCTERMS, PROV as _PROV_NS  # noqa: N811
    WDT = Namespace("http://w3id.org/geo-lod/wdttest/ns#")
    DCAT = Namespace("http://www.w3.org/ns/dcat#")
    PROV = Namespace("http://www.w3.org/ns/prov#")

    for e in (raw_data or []):
        rid = e.get("id") or _slug(str(e.get("title", "rawdata")))
        # The shipped, citable artefact: prefer an explicit file/csv, then the
        # raw .tab, then the derived product (some repos ship only one of these).
        path = e.get("file") or e.get("csv") or e.get("tab") or e.get("derived")
        if not path:
            print(f"  !!  raw_data '{rid}' has no file/csv/tab/derived path; skipped")
            continue
        node = URIRef(f"{base}#data-{_slug(rid)}")
        g.add((node, RDF.type, WDT.RawData))
        g.add((node, RDF.type, DCAT.Distribution))
        g.add((node, RDF.type, PROV.Entity))
        g.add((ds, DCAT.distribution, node))
        if e.get("title"):
            g.add((node, DCTERMS.title, Literal(e["title"], lang="en")))
        if e.get("creator"):
            ag = agent(e["creator"])
            g.add((node, DCTERMS.creator, ag))
            g.add((node, PROV.wasAttributedTo, ag))
        if e.get("license"):
            g.add((node, DCTERMS.license, licence(e["license"])))
            if e.get("creator"):
                g.add((node, DCTERMS.rights,
                       Literal(f"{e['license']}, {e['creator']}")))
        ext = Path(path).suffix.lower()
        if ext in MEDIA_TYPES:
            g.add((node, DCAT.mediaType, Literal(MEDIA_TYPES[ext])))
        g.add((node, DCAT.downloadURL, URIRef(f"{base}/{path}")))
        g.add((node, DCTERMS.identifier, Literal(path)))
        if e.get("age_scale"):
            g.add((node, WDT.ageScale, Literal(e["age_scale"])))
        # Upstream provenance: a DOI, else an http source URL. Free-text sources
        # (e.g. "Own data (WD1 study)") carry no node - creator/licence suffice.
        upstream = e.get("doi") or (
            e["source"] if str(e.get("source", "")).startswith("http") else None)
        if upstream:
            up = URIRef(upstream)
            if e.get("creator"):
                g.add((up, DCTERMS.creator, agent(e["creator"])))
            if e.get("license"):
                g.add((up, DCTERMS.license, licence(e["license"])))
            g.add((node, DCTERMS.source, up))
            g.add((node, PROV.wasDerivedFrom, up))


def write_ttl(meta, raw_data=None):
    try:
        from rdflib import Graph, Namespace, URIRef, BNode, Literal
        from rdflib.namespace import RDF, RDFS, DCTERMS, FOAF, XSD
    except Exception as exc:
        print(f"  ..  rdflib unavailable, metadata.ttl NOT written: "
              f"{type(exc).__name__}: {exc}")
        print("      Fix:  pip install rdflib")
        return False

    WDT = Namespace("http://w3id.org/geo-lod/wdttest/ns#")
    DCAT = Namespace("http://www.w3.org/ns/dcat#")
    PROV = Namespace("http://www.w3.org/ns/prov#")

    g = Graph()
    for pfx, ns in (("wdt", WDT), ("dcat", DCAT), ("dct", DCTERMS),
                    ("prov", PROV), ("foaf", FOAF), ("rdfs", RDFS)):
        g.bind(pfx, ns)

    repo = meta["repo"]
    base = repo["base_iri"].rstrip("/")
    ds = URIRef(base)

    # Deduplicate agents and licences into shared nodes.
    agents, licences = {}, {}

    def agent(name):
        if name not in agents:
            node = URIRef(f"{base}#agent-{_slug(name)}")
            # geo-lod models named creators as prov:Agent + foaf:Person.
            g.add((node, RDF.type, PROV.Agent))
            g.add((node, RDF.type, FOAF.Person))
            g.add((node, FOAF.name, Literal(name)))
            if name.upper() == "TODO":
                g.add((node, RDFS.comment, Literal("TODO: fill in creator")))
            agents[name] = node
        return agents[name]

    def licence(label):
        if label in LICENSE_URIS:
            return URIRef(LICENSE_URIS[label])
        if label not in licences:
            # A licence with no canonical URI stays a blank node - it is a local
            # description, not a resource anyone can dereference - but it gets a
            # STABLE label rather than a random one, so rebuilding this file
            # produces byte-identical output. With random ids the file showed a
            # diff on every run, which trains everyone to stop reading the diff.
            # The repository name is part of the label because wdttest-master
            # merges every repo's graph: two repos both carrying an unresolved
            # "TODO" licence must not collapse into one node.
            node = BNode(_slug(f"{meta['repo']['name']}-license-{label}"))
            g.add((node, RDF.type, DCTERMS.LicenseDocument))
            g.add((node, RDFS.label, Literal(label)))
            if label.upper() == "TODO":
                g.add((node, RDFS.comment, Literal("TODO: fill in licence")))
            licences[label] = node
        return licences[label]

    # Dataset (the repository).
    g.add((ds, RDF.type, DCAT.Dataset))
    g.add((ds, RDF.type, PROV.Entity))
    g.add((ds, DCTERMS.title, Literal(repo["title"], lang="en")))
    if repo.get("summary"):
        g.add((ds, DCTERMS.description, Literal(repo["summary"].strip(), lang="en")))
    g.add((ds, WDT.category, WDT[repo.get("category", "figure")]))
    if repo.get("landing_page"):
        g.add((ds, DCAT.landingPage, URIRef(repo["landing_page"])))
    if repo.get("doi"):
        g.add((ds, DCTERMS.identifier, URIRef(repo["doi"])))
    if repo.get("publisher"):
        g.add((ds, DCTERMS.publisher, Literal(repo["publisher"])))
    if repo.get("created"):
        g.add((ds, DCTERMS.created, Literal(str(repo["created"]), datatype=XSD.date)))

    src_nodes = {}

    def source(entry):
        key = entry["name"]
        if key not in src_nodes:
            iri = entry.get("iri")
            if iri:
                # Reference an existing resource (a geolod: dataset, a DOI, a
                # Wikidata query, ...). Do not re-type or re-title it, but DO
                # attach the attribution we explicitly know (creator/licence) so
                # it travels with the metadata rather than living only in prose.
                node = URIRef(iri)
                if entry.get("creator"):
                    g.add((node, DCTERMS.creator, agent(entry["creator"])))
                if entry.get("license"):
                    g.add((node, DCTERMS.license, licence(entry["license"])))
            else:
                node = URIRef(f"{base}#source-{_slug(key)}")
                g.add((node, RDF.type, DCAT.Dataset))
                g.add((node, RDF.type, PROV.Entity))
                g.add((node, DCTERMS.title, Literal(key)))
                if entry.get("creator"):
                    g.add((node, DCTERMS.creator, agent(entry["creator"])))
                if entry.get("license"):
                    g.add((node, DCTERMS.license, licence(entry["license"])))
                if str(entry.get("license", "")).upper() == "TODO" or \
                        str(entry.get("creator", "")).upper() == "TODO":
                    g.add((node, RDFS.comment,
                           Literal("TODO: link to the KG resource via 'iri:' "
                                   "in metadata.yaml, or fill creator/licence")))
            src_nodes[key] = node
        return src_nodes[key]

    # Outputs (distributions).
    for out in meta["outputs"]:
        dist = URIRef(f"{base}#output-{out['id']}")
        g.add((dist, RDF.type, WDT.Output))
        g.add((dist, RDF.type, PROV.Entity))
        g.add((ds, DCAT.distribution, dist))
        g.add((dist, DCTERMS.title, Literal(out["caption"], lang="en")))
        g.add((dist, WDT.caption, Literal(out["caption"], lang="en")))
        if out.get("caption_detail"):
            g.add((dist, WDT.captionDetail, Literal(out["caption_detail"], lang="en")))
        if out.get("data_creator"):
            ag = agent(out["data_creator"])
            g.add((dist, DCTERMS.creator, ag))
            g.add((dist, PROV.wasAttributedTo, ag))
        if out.get("license"):
            g.add((dist, DCTERMS.license, licence(out["license"])))
            # Human-readable rights statement in the geo-lod "licence, creator"
            # style (cf. captions.yaml), kept alongside the machine licence URI.
            # An explicit `rights` wins, because a table may name more holders
            # than its single data-creator.
            if out.get("rights"):
                g.add((dist, DCTERMS.rights, Literal(out["rights"])))
            elif out.get("data_creator"):
                g.add((dist, DCTERMS.rights,
                       Literal(f"{out['license']}, {out['data_creator']}")))
        ext = Path(out["file"]).suffix.lower()
        if ext in MEDIA_TYPES:
            g.add((dist, DCAT.mediaType, Literal(MEDIA_TYPES[ext])))
        g.add((dist, DCAT.downloadURL, URIRef(f"{base}/{out['file']}")))
        g.add((dist, DCTERMS.identifier, Literal(out["file"])))
        for entry in out.get("sources", []):
            src = source(entry)
            g.add((dist, DCTERMS.source, src))
            g.add((dist, PROV.wasDerivedFrom, src))

    # Raw input datasets (data.yaml), if any.
    add_raw_data(g, base, ds, raw_data, agent, licence)

    header = (
        "# metadata.ttl - FDO metadata for this repository (DCAT / PROV / SKOS).\n"
        "# GENERATED from metadata.yaml by py/make_metadata.py - do not edit by hand.\n"
        "# Shared vocabulary: metadata/ontology.ttl (prefix wdt:).\n\n"
    )
    ttl = g.serialize(format="turtle")
    ensure_dirs()
    META_DIR.mkdir(exist_ok=True)
    TTL_OUT.write_text(header + ttl, encoding="utf-8")
    print(f"  OK  {TTL_OUT}  ({len(g)} triples)")
    return True


def _strict():
    import os
    return os.environ.get("WDTTEST_STRICT", "") not in ("", "0", "false", "False")


def validate_shacl():
    """Validate metadata.ttl against metadata/shapes.ttl (structural gate).

    Soft-optional: if pyshacl is missing, say so loudly and skip. With --strict
    (WDTTEST_STRICT), a non-conforming graph aborts the run.
    """
    if not SHAPES.exists():
        return
    try:
        from pyshacl import validate
    except Exception as exc:
        print(f"  ..  pyshacl unavailable, SHACL check skipped: "
              f"{type(exc).__name__}: {exc}")
        print("      Fix:  pip install pyshacl")
        return
    from rdflib import Graph
    data = Graph().parse(TTL_OUT, format="turtle")
    if ONTOLOGY.exists():
        data.parse(ONTOLOGY, format="turtle")
    conforms, _, text = validate(
        data, shacl_graph=str(SHAPES), inference="rdfs", advanced=True)
    if conforms:
        print(f"  OK  SHACL: metadata.ttl conforms to {SHAPES.name}")
    else:
        print(f"  !!  SHACL: metadata.ttl does NOT conform to {SHAPES.name}:")
        for line in text.strip().splitlines():
            print(f"      {line}")
        if _strict():
            raise SystemExit("  !!  --strict: aborting on SHACL violations.")


# --------------------------------------------------------------------------
# 2) README "Outputs" block
# --------------------------------------------------------------------------

# How the generated README table shows an output's path. `file` itself stays the
# full repo-relative path everywhere it matters (the on-disk check, the
# dcat:downloadURL and the dct:identifier in the TTL); only the display in the
# README is shortened. "link" = bare file name linked to its path, "name" = bare
# file name, "path" = the full repo-relative path.
README_FILE_DISPLAY = "link"


def _display_file(path):
    if README_FILE_DISPLAY == "path":
        return f"`{path}`"
    name = Path(path).name
    if README_FILE_DISPLAY == "name":
        return f"`{name}`"
    return f"[`{name}`]({path})"


def build_readme_block(meta):
    lines = [MARK_START, ""]
    lines.append("| Output | Caption | Data creator | Licence |")
    lines.append("| --- | --- | --- | --- |")
    for out in meta["outputs"]:
        cap = out["caption"]
        if out.get("caption_detail"):
            cap = f"{cap} {out['caption_detail']}"
        cap = cap.replace("|", "\\|")
        creator = out.get("data_creator", "")
        lic = out.get("license", "")
        lines.append(f"| {_display_file(out['file'])} | {cap} | {creator} | {lic} |")

    # Unique upstream sources, in first-seen order.
    seen, srcs = set(), []
    for out in meta["outputs"]:
        for s in out.get("sources", []):
            if s["name"] not in seen:
                seen.add(s["name"])
                srcs.append(s)
    if srcs:
        lines += ["", "**Upstream data sources** (independent licences):", ""]
        for s in srcs:
            lines.append(f"- {s['name']} - creator: {s.get('creator', 'TODO')}; "
                         f"licence: {s.get('license', 'TODO')}")
    lines += ["", MARK_END]
    return "\n".join(lines)


def inject_readme(meta):
    block = build_readme_block(meta)
    text = README.read_text(encoding="utf-8")
    if MARK_START in text and MARK_END in text:
        pre = text[:text.index(MARK_START)]
        post = text[text.index(MARK_END) + len(MARK_END):]
        new = pre + block + post
    else:
        section = f"## Outputs\n\n{block}\n\n"
        anchor = "## Data"
        if anchor in text:
            i = text.index(anchor)
            new = text[:i] + section + text[i:]
        else:
            new = text.rstrip() + "\n\n" + section
    if new != text:
        README.write_text(new, encoding="utf-8")
        print(f"  OK  {README}  (Outputs block updated)")
    else:
        print(f"  --  {README}  (Outputs block already up to date)")


# --------------------------------------------------------------------------
# 2b) README "Data sources" block (from data.yaml, optional)
# --------------------------------------------------------------------------

def load_rawdata():
    """Return the ``raw_data`` manifest from data.yaml, or None if absent.

    data.yaml is optional: repos without archived raw inputs simply do not have
    it and the raw-data block is skipped.
    """
    if not DATA_YAML.exists():
        return None
    with open(DATA_YAML, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("raw_data")


def _doi_md(entry):
    """Render a raw-data entry's DOI as a markdown link, or "" if it has none."""
    doi = str(entry.get("doi", "")).strip()
    return f"[{doi.rsplit('/', 1)[-1]}]({doi})" if doi else ""


# Optional columns of the data-sources table: (heading, cell function). Each is
# rendered only when at least one entry actually fills it, so a repository whose
# inputs carry no DOI and no age scale - a table repository, typically - gets a
# four-column table instead of two permanently empty columns. Nothing is dropped
# silently: add a `doi:` or `age_scale:` to any data.yaml entry and its column
# reappears on the next run.
RAWDATA_OPTIONAL_COLUMNS = [
    ("DOI", _doi_md),
    ("Age scale", lambda e: str(e.get("age_scale", "")).strip()),
]


def build_rawdata_block(raw_data):
    optional = [(head, cell) for head, cell in RAWDATA_OPTIONAL_COLUMNS
                if any(cell(e) for e in raw_data)]
    headings = ["Data", "Source"] + [h for h, _ in optional] + ["Creator", "Licence"]

    lines = [MARK_RAW_START, ""]
    lines.append("| " + " | ".join(headings) + " |")
    lines.append("| " + " | ".join(["---"] * len(headings)) + " |")
    for e in raw_data:
        row = [
            str(e.get("id", "")),
            str(e.get("title", e.get("source", ""))).replace("|", "\\|"),
            *[cell(e) for _, cell in optional],
            str(e.get("creator", "TODO")).replace("|", "\\|"),
            str(e.get("license", "TODO")),
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", MARK_RAW_END]
    return "\n".join(lines)


def inject_rawdata(raw_data):
    """Inject the data-sources table between the RAWDATA markers in README.

    The block is opt-in: it is written only if the markers are present, so a
    repo can choose where (or whether) the generated table appears.
    """
    block = build_rawdata_block(raw_data)
    text = README.read_text(encoding="utf-8")
    if MARK_RAW_START not in text or MARK_RAW_END not in text:
        print("  ..  data.yaml present but no RAWDATA markers in README; "
              "raw-data block skipped")
        return
    pre = text[:text.index(MARK_RAW_START)]
    post = text[text.index(MARK_RAW_END) + len(MARK_RAW_END):]
    new = pre + block + post
    if new != text:
        README.write_text(new, encoding="utf-8")
        print(f"  OK  {README}  (Data-sources block updated)")
    else:
        print(f"  --  {README}  (Data-sources block already up to date)")


def check_files(meta):
    missing = [out["file"] for out in meta["outputs"]
               if not (ROOT / out["file"]).exists()]
    if missing:
        print("  ..  listed outputs not found on disk (run the figure phases "
              "first):")
        for m in missing:
            print(f"       - {m}")


def main():
    print("=" * 60)
    print("Generate the repository metadata blocks in README.md")
    print("=" * 60)
    meta = load_meta()
    resolve_output_files(meta)
    check_files(meta)
    inject_readme(meta)
    raw = load_rawdata()
    if raw:
        inject_rawdata(raw)
    if EMIT_TTL and write_ttl(meta, raw):
        validate_shacl()
    print("=" * 60 + "\nDone.\n" + "=" * 60)


if __name__ == "__main__":
    import argparse
    import os
    ap = argparse.ArgumentParser(
        description="Generate the README metadata blocks from metadata.yaml.")
    ap.add_argument("--strict", action="store_true",
                    help="abort on SHACL violations instead of only reporting them")
    args = ap.parse_args()
    if args.strict:
        os.environ["WDTTEST_STRICT"] = "1"
    main()