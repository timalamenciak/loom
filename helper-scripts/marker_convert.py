#!/usr/bin/env python3
"""Convert PDFs to Markdown using Marker with optional LLM assist.

Run this on a machine with marker-pdf installed (and ideally a GPU or a fast
LLM endpoint). The output .md files are named after the source PDF and placed
in the same directory, ready to be bundled into a Loom ZIP import alongside the
PDFs and the RIS file.

Requirements (on the conversion machine):
    pip install marker-pdf rispy

Usage:
    python marker_convert.py /path/to/papers/ \\
        --llm-url https://spark-1267:11434/v1 \\
        --llm-model qwen2.5:35b

    # Layout-only (no LLM):
    python marker_convert.py /path/to/papers/ --no-llm

    # Filter to PDFs listed in a RIS file's L1 / file_attachments tags:
    python marker_convert.py /path/to/papers/ --ris refs.ris --llm-url ...

    # Re-convert even if .md already exists:
    python marker_convert.py /path/to/papers/ --force --llm-url ...

Loom workflow:
    1. Run this script on spark to produce <paper>.md alongside each <paper>.pdf.
    2. ZIP the directory (refs.ris + *.pdf + *.md).
    3. Upload the ZIP as a bundle in Loom — markdown is ingested automatically.
    4. Or copy the .md files to the server and run:
           python manage.py extract_markdown [--force]
       to pick up sidecars for documents already in the database.
"""

import argparse
import io
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# PDF discovery
# ---------------------------------------------------------------------------


def _find_pdfs_from_ris(ris_path: Path, base_dir: Path) -> list[Path]:
    """Return PDF paths referenced in the RIS file's L1 / file_attachments tags."""
    try:
        import rispy
    except ImportError:
        print(
            "rispy not installed; --ris filter ignored. pip install rispy",
            file=sys.stderr,
        )
        return []

    text = ris_path.read_text(encoding="utf-8", errors="replace")
    try:
        records = list(rispy.load(io.StringIO(text)))
    except Exception as exc:
        print(f"Could not parse RIS file: {exc}", file=sys.stderr)
        return []

    pdfs: list[Path] = []
    for rec in records:
        for key in ("file_attachments1", "file_attachments2"):
            values = rec.get(key) or []
            if isinstance(values, str):
                values = [values]
            for v in values:
                for part in str(v).split(";"):
                    name = part.strip().replace("\\", "/").rsplit("/", 1)[-1]
                    if name.lower().endswith(".pdf"):
                        candidate = base_dir / name
                        if candidate.exists():
                            pdfs.append(candidate)
    return pdfs


# ---------------------------------------------------------------------------
# Marker conversion
# ---------------------------------------------------------------------------


def _build_converter(llm_url: str | None, llm_model: str | None, api_key: str):
    """Import Marker, configure it, and return (converter, env_overrides)."""
    try:
        from marker.config.parser import ConfigParser
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
    except ImportError as exc:
        print(f"marker-pdf is not installed: {exc}", file=sys.stderr)
        print("Run: pip install marker-pdf", file=sys.stderr)
        sys.exit(1)

    config: dict = {"force_ocr": False}
    env_overrides: dict[str, str] = {}

    if llm_url:
        config["use_llm"] = True
        config["llm_service"] = "marker.services.openai.OpenAIService"
        env_overrides["OPENAI_BASE_URL"] = llm_url
        env_overrides["OPENAI_API_KEY"] = api_key
        if llm_model:
            config["openai_model"] = llm_model

    config_parser = ConfigParser(config)
    converter = PdfConverter(
        config=config_parser.generate_config_dict(),
        artifact_dict=create_model_dict(),
    )
    return converter, env_overrides


def _convert_one(pdf_path: Path, converter, env_overrides: dict[str, str]) -> str | None:
    """Run the converter on one PDF; return Markdown or None on failure."""
    old_env = {k: os.environ.get(k) for k in env_overrides}
    try:
        os.environ.update(env_overrides)
        rendered = converter(str(pdf_path))
        return rendered.markdown
    except Exception as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        return None
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing PDF files (and optionally a RIS manifest).",
    )
    parser.add_argument(
        "--llm-url",
        metavar="URL",
        help="Base URL of an OpenAI-compatible LLM endpoint, e.g. https://spark:11434/v1",
    )
    parser.add_argument(
        "--llm-model",
        metavar="MODEL",
        help="Model name to pass to the endpoint, e.g. qwen2.5:35b",
    )
    parser.add_argument(
        "--api-key",
        default="nokey",
        metavar="KEY",
        help="API key for the LLM endpoint (default: 'nokey' for local endpoints).",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Layout-only Marker pass — no LLM assist.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-convert even if a .md file already exists.",
    )
    parser.add_argument(
        "--ris",
        type=Path,
        metavar="FILE",
        help=(
            "Restrict to PDFs listed in this RIS file's L1 / file_attachments tags. "
            "Relative paths are resolved against the target directory. "
            "Defaults to all *.pdf files in the directory."
        ),
    )
    args = parser.parse_args()

    directory = args.directory.resolve()
    if not directory.is_dir():
        parser.error(f"Not a directory: {directory}")

    # Discover PDFs
    if args.ris:
        ris_path = args.ris if args.ris.is_absolute() else directory / args.ris
        if not ris_path.exists():
            parser.error(f"RIS file not found: {ris_path}")
        pdfs = _find_pdfs_from_ris(ris_path, directory)
        if not pdfs:
            print(
                f"No matching PDFs found via {ris_path.name}; "
                "falling back to all *.pdf in directory.",
                file=sys.stderr,
            )
            pdfs = sorted(directory.glob("*.pdf"))
    else:
        pdfs = sorted(directory.glob("*.pdf"))

    if not pdfs:
        print(f"No PDF files found in {directory}", file=sys.stderr)
        sys.exit(1)

    llm_url = None if args.no_llm else args.llm_url

    print(f"Found {len(pdfs)} PDF(s) in {directory}")
    if llm_url:
        model_label = args.llm_model or "(endpoint default)"
        print(f"  LLM endpoint : {llm_url}")
        print(f"  Model        : {model_label}")
    else:
        print("  LLM          : disabled (layout-only)")
    print()

    print("Loading Marker models (this may take a moment on first run)…")
    converter, env_overrides = _build_converter(llm_url, args.llm_model, args.api_key)
    print()

    ok = skip = fail = 0
    for pdf in pdfs:
        out_path = pdf.with_suffix(".md")
        if out_path.exists() and not args.force:
            print(f"  skip  {pdf.name}  (.md exists; use --force to redo)")
            skip += 1
            continue

        print(f"  → {pdf.name} … ", end="", flush=True)
        markdown = _convert_one(pdf, converter, env_overrides)
        if markdown is None:
            print("FAILED")
            fail += 1
        else:
            out_path.write_text(markdown, encoding="utf-8")
            print(f"✓  {out_path.name}  ({len(markdown):,} chars)")
            ok += 1

    print()
    print(f"Done: {ok} converted, {skip} skipped, {fail} failed.")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
