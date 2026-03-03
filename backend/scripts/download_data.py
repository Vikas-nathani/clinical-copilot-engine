"""
Data Download & Compilation Script.

Downloads medical terminology data from public sources and compiles
them into optimized formats for the Clinical Copilot Engine.

Sources:
  - ICD-10-CM: CMS.gov (public, no login)
  - LOINC: loinc.org (requires free registration)
  - SNOMED-CT: UMLS (requires license + API key)

Usage:
  python scripts/download_data.py --all
  python scripts/download_data.py --icd10
  python scripts/download_data.py --loinc
  python scripts/download_data.py --snomed
  python scripts/download_data.py --compile-only
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests

# Add project root to path for config imports
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.config import COMPILED_DATA_DIR, RAW_DATA_DIR, get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ── Constants ───────────────────────────────────────────────────────

ICD10_URL = (
    "https://www.cms.gov/files/zip/2025-code-descriptions-tabular-order.zip"
)
ICD10_FALLBACK_URL = (
    "https://www.cms.gov/files/zip/2024-code-descriptions-tabular-order-updated-01-11-2024.zip"
)
UMLS_AUTH_URL = "https://utslogin.nlm.nih.gov/cas/v1/api-key"
UMLS_DOWNLOAD_URL = "https://uts-ws.nlm.nih.gov/rest/download"


# ── ICD-10-CM Download ─────────────────────────────────────────────


def download_icd10() -> Optional[Path]:
    """Download ICD-10-CM code descriptions from CMS.gov."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RAW_DATA_DIR / "icd10cm_codes.csv"

    if output_path.exists():
        logger.info("ICD-10 file already exists at %s — skipping download.", output_path)
        return output_path

    for url in [ICD10_URL, ICD10_FALLBACK_URL]:
        try:
            logger.info("Downloading ICD-10-CM from %s ...", url)
            resp = requests.get(url, timeout=120, stream=True)
            resp.raise_for_status()

            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                # Find the descriptions file inside the ZIP
                txt_files = [
                    n for n in zf.namelist()
                    if n.lower().endswith(".txt") and "desc" in n.lower()
                ]
                if not txt_files:
                    txt_files = [n for n in zf.namelist() if n.lower().endswith(".txt")]

                if not txt_files:
                    logger.warning("No .txt file found in ICD-10 ZIP from %s", url)
                    continue

                target_file = txt_files[0]
                logger.info("Extracting %s from ZIP...", target_file)

                with zf.open(target_file) as src:
                    raw_text = src.read().decode("utf-8", errors="replace")

                # Parse fixed-width format: code (7 chars) + space + description
                rows = []
                for line in raw_text.strip().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    # ICD-10 codes are typically 3-7 chars at the start
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        code, description = parts
                        if len(code) >= 3 and code[0].isalpha():
                            rows.append((code.strip(), description.strip()))

                # Write as CSV
                with open(output_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["code", "description"])
                    writer.writerows(rows)

                logger.info("ICD-10-CM: %d codes saved to %s", len(rows), output_path)
                return output_path

        except requests.RequestException as e:
            logger.warning("Failed to download from %s: %s", url, e)
            continue

    logger.error("Failed to download ICD-10-CM from all sources.")
    return None


# ── LOINC Download ──────────────────────────────────────────────────


def download_loinc() -> Optional[Path]:
    """
    Download LOINC table. Requires LOINC_USERNAME and LOINC_PASSWORD in .env.
    Falls back to creating a minimal LOINC subset if credentials are not available.
    """
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RAW_DATA_DIR / "loinc_table.csv"

    if output_path.exists():
        logger.info("LOINC file already exists at %s — skipping.", output_path)
        return output_path

    settings = get_settings()
    if not settings.loinc_username or not settings.loinc_password:
        logger.warning(
            "LOINC credentials not configured (LOINC_USERNAME / LOINC_PASSWORD). "
            "Creating minimal LOINC subset from built-in lab ranges instead."
        )
        return _create_minimal_loinc(output_path)

    # LOINC requires authenticated download — manual for now
    logger.info(
        "LOINC download requires manual download from https://loinc.org/downloads/\n"
        "  1. Log in with your LOINC credentials\n"
        "  2. Download the 'LOINC Table File' (CSV)\n"
        "  3. Place it at: %s\n"
        "Then re-run this script with --compile-only",
        output_path,
    )
    return _create_minimal_loinc(output_path)


def _create_minimal_loinc(output_path: Path) -> Path:
    """Create a minimal LOINC file from the built-in lab engine ranges."""
    from app.services.lab_engine import BUILTIN_LAB_RANGES

    rows = []
    seen_codes: Set[str] = set()
    for key, rng in BUILTIN_LAB_RANGES.items():
        if rng.loinc_code and rng.loinc_code not in seen_codes:
            rows.append((rng.loinc_code, rng.name, rng.unit))
            seen_codes.add(rng.loinc_code)

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["loinc_num", "component", "example_units"])
        writer.writerows(rows)

    logger.info("Minimal LOINC subset: %d codes saved to %s", len(rows), output_path)
    return output_path


# ── SNOMED-CT via UMLS ──────────────────────────────────────────────


def download_snomed() -> Optional[Path]:
    """
    Download SNOMED-CT descriptions via UMLS REST API.
    Requires UMLS_API_KEY in .env.
    """
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RAW_DATA_DIR / "snomed_descriptions.txt"

    if output_path.exists():
        logger.info("SNOMED file already exists at %s — skipping.", output_path)
        return output_path

    settings = get_settings()
    if not settings.umls_api_key:
        logger.warning(
            "UMLS_API_KEY not configured. SNOMED-CT download skipped.\n"
            "  Set UMLS_API_KEY in .env to enable SNOMED-CT integration.\n"
            "  Get your key at: https://uts.nlm.nih.gov/uts/profile"
        )
        return None

    logger.info(
        "SNOMED-CT full download requires the UMLS Metathesaurus files.\n"
        "For full SNOMED-CT integration:\n"
        "  1. Go to https://www.nlm.nih.gov/research/umls/licensedcontent/umlsknowledgesources.html\n"
        "  2. Download the UMLS Metathesaurus (MRCONSO.RRF)\n"
        "  3. Extract SNOMED-CT entries and place at: %s\n"
        "  Then re-run with --compile-only\n\n"
        "For now, creating a minimal SNOMED subset from built-in abbreviations.",
        output_path,
    )
    return _create_minimal_snomed(output_path)


def _create_minimal_snomed(output_path: Path) -> Path:
    """Create a minimal SNOMED file from the built-in abbreviations."""
    from app.services.dictionary import BUILTIN_ABBREVIATIONS

    rows = []
    seen: Set[str] = set()
    for key, entry in BUILTIN_ABBREVIATIONS.items():
        snomed = entry.get("snomed")
        if snomed and snomed not in seen:
            rows.append(f"{snomed}\t{entry['term']}")
            seen.add(snomed)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("snomed_id\tdescription\n")
        f.write("\n".join(rows))

    logger.info("Minimal SNOMED subset: %d concepts saved to %s", len(rows), output_path)
    return output_path


# ── Compilation ─────────────────────────────────────────────────────


def compile_data() -> None:
    """
    Compile raw data files into optimized formats:
      - MARISA-Trie binary
      - ICD-10 / SNOMED / LOINC lookup JSONs
      - Abbreviation map JSON
      - Lab ranges JSON
    """
    import marisa_trie

    COMPILED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    all_terms: Set[str] = set()
    icd10_lookup: Dict[str, str] = {}
    snomed_lookup: Dict[str, str] = {}
    loinc_lookup: Dict[str, str] = {}

    # ── Parse ICD-10 ────────────────────────────────────────────────
    icd10_path = RAW_DATA_DIR / "icd10cm_codes.csv"
    if icd10_path.exists():
        logger.info("Parsing ICD-10-CM from %s ...", icd10_path)
        with open(icd10_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("code", "").strip()
                desc = row.get("description", "").strip()
                if code and desc:
                    term = desc.lower()
                    all_terms.add(term)
                    icd10_lookup[term] = code
        logger.info("ICD-10: %d terms indexed.", len(icd10_lookup))
    else:
        logger.warning("No ICD-10 file found at %s", icd10_path)

    # ── Parse LOINC ─────────────────────────────────────────────────
    loinc_path = RAW_DATA_DIR / "loinc_table.csv"
    if loinc_path.exists():
        logger.info("Parsing LOINC from %s ...", loinc_path)
        with open(loinc_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("loinc_num", row.get("LOINC_NUM", "")).strip()
                component = row.get("component", row.get("COMPONENT", "")).strip()
                if code and component:
                    term = component.lower()
                    all_terms.add(term)
                    loinc_lookup[term] = code
        logger.info("LOINC: %d terms indexed.", len(loinc_lookup))
    else:
        logger.warning("No LOINC file found at %s", loinc_path)

    # ── Parse SNOMED-CT ─────────────────────────────────────────────
    snomed_path = RAW_DATA_DIR / "snomed_descriptions.txt"
    if snomed_path.exists():
        logger.info("Parsing SNOMED-CT from %s ...", snomed_path)
        with open(snomed_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i == 0:
                    continue  # skip header
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    snomed_id, description = parts[0], parts[1]
                    term = description.lower()
                    all_terms.add(term)
                    snomed_lookup[term] = snomed_id
        logger.info("SNOMED: %d terms indexed.", len(snomed_lookup))
    else:
        logger.warning("No SNOMED file found at %s", snomed_path)

    # ── Add abbreviation expansions to the trie ─────────────────────
    from app.services.dictionary import BUILTIN_ABBREVIATIONS
    for entry in BUILTIN_ABBREVIATIONS.values():
        term = entry["term"].lower()
        all_terms.add(term)
        if entry.get("icd") and term not in icd10_lookup:
            icd10_lookup[term] = entry["icd"]
        if entry.get("snomed") and term not in snomed_lookup:
            snomed_lookup[term] = entry["snomed"]

    # ── Build MARISA-Trie ───────────────────────────────────────────
    if all_terms:
        sorted_terms = sorted(all_terms)
        trie = marisa_trie.Trie(sorted_terms)
        trie_path = COMPILED_DATA_DIR / "medical_trie.marisa"
        trie.save(str(trie_path))
        logger.info("MARISA-Trie compiled: %d terms → %s", len(sorted_terms), trie_path)
    else:
        logger.warning("No terms to compile into trie.")

    # ── Write lookup JSONs ──────────────────────────────────────────
    _write_json(icd10_lookup, COMPILED_DATA_DIR / "icd10_lookup.json", "ICD-10")
    _write_json(snomed_lookup, COMPILED_DATA_DIR / "snomed_lookup.json", "SNOMED")
    _write_json(loinc_lookup, COMPILED_DATA_DIR / "loinc_lookup.json", "LOINC")

    # ── Write abbreviations JSON ────────────────────────────────────
    _write_json(
        BUILTIN_ABBREVIATIONS,
        COMPILED_DATA_DIR / "abbreviations.json",
        "Abbreviations",
    )

    # ── Write lab ranges JSON ───────────────────────────────────────
    from app.services.lab_engine import BUILTIN_LAB_RANGES
    lab_dict = {}
    for key, rng in BUILTIN_LAB_RANGES.items():
        lab_dict[key] = {
            "name": rng.name,
            "unit": rng.unit,
            "normal_low": rng.normal_low,
            "normal_high": rng.normal_high,
            "critical_low": rng.critical_low,
            "critical_high": rng.critical_high,
            "loinc_code": rng.loinc_code,
        }
    _write_json(lab_dict, COMPILED_DATA_DIR / "lab_ranges.json", "Lab Ranges")

    logger.info("Compilation complete. All files in %s", COMPILED_DATA_DIR)


def _write_json(data: dict, path: Path, label: str) -> None:
    """Write a dict to a JSON file with pretty printing."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("%s: %d entries → %s", label, len(data), path)


# ── CLI Entry Point ─────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Download and compile medical terminology data."
    )
    parser.add_argument("--all", action="store_true", help="Download all + compile")
    parser.add_argument("--icd10", action="store_true", help="Download ICD-10-CM only")
    parser.add_argument("--loinc", action="store_true", help="Download LOINC only")
    parser.add_argument("--snomed", action="store_true", help="Download SNOMED-CT only")
    parser.add_argument(
        "--compile-only", action="store_true",
        help="Skip downloads, just compile existing raw files",
    )
    args = parser.parse_args()

    # Default to --all if no flags
    if not any([args.all, args.icd10, args.loinc, args.snomed, args.compile_only]):
        args.all = True

    if args.all or args.icd10:
        download_icd10()

    if args.all or args.loinc:
        download_loinc()

    if args.all or args.snomed:
        download_snomed()

    # Always compile after downloads
    compile_data()

    logger.info("Done! Data is ready for the Clinical Copilot Engine.")


if __name__ == "__main__":
    main()
