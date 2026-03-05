import json
import logging
from pathlib import Path
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

MRCONSO = Path("data/raw/2025AB/META/MRCONSO.RRF")
OUT_DIR  = Path("data/compiled")
OUT_DIR.mkdir(parents=True, exist_ok=True)

WANTED_SOURCES = {"SNOMEDCT_US", "LNC", "RXNORM", "ICD10CM"}
SOURCE_KEY_MAP  = {
    "SNOMEDCT_US": "snomed",
    "LNC":         "loinc",
    "RXNORM":      "rxnorm",
    "ICD10CM":     "icd10",
}

log.info("Reading MRCONSO.RRF - this takes 2-3 minutes...")

cui_data = defaultdict(dict)
cui_term = {}

with open(MRCONSO, encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i % 1_000_000 == 0:
            log.info(f"  {i:,} rows processed...")
        cols = line.rstrip("\n").split("|")
        if len(cols) < 15:
            continue
        cui     = cols[0]
        lat     = cols[1]
        ispref  = cols[6]
        sab     = cols[11]
        code    = cols[13]
        term    = cols[14]
        suppress= cols[16]

        if lat != "ENG" or suppress != "O":
            continue

        # Capture ANY english term for this CUI if we don't have one yet
        # Prefer ispref=Y but fall back to anything
        if cui not in cui_term:
            cui_term[cui] = term
        elif ispref == "Y":
            cui_term[cui] = term

        if sab in WANTED_SOURCES and code and code != cui:
            if sab not in cui_data[cui]:
                cui_data[cui][sab] = {"code": code, "term": term}

log.info(f"Done. {len(cui_term):,} concepts, {len(cui_data):,} with source codes.")

snomed_lookup = {}
loinc_lookup  = {}

for cui, sources in cui_data.items():
    term = cui_term.get(cui, "")
    if not term:
        continue
    key = term.lower()
    entry = {"term": term, "cui": cui}
    for sab, info in sources.items():
        field = SOURCE_KEY_MAP.get(sab)
        if field:
            entry[f"{field}_code"] = info["code"]
    if "SNOMEDCT_US" in sources:
        snomed_lookup[key] = entry
    if "LNC" in sources:
        loinc_lookup[key] = entry

log.info(f"SNOMED entries: {len(snomed_lookup):,}")
log.info(f"LOINC entries:  {len(loinc_lookup):,}")

log.info("Writing snomed_lookup.json...")
with open(OUT_DIR / "snomed_lookup.json", "w") as f:
    json.dump(snomed_lookup, f)

log.info("Writing loinc_lookup.json...")
with open(OUT_DIR / "loinc_lookup.json", "w") as f:
    json.dump(loinc_lookup, f)

log.info("Done. Restart backend to load new data.")
