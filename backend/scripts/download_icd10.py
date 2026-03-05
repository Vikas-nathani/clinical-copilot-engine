"""
Download ICD-10-CM codes from CMS.gov and build lookup JSON.
Free download - no license required.
Run: python scripts/download_icd10.py
"""
import json
import urllib.request
import zipfile
import csv
import os
from pathlib import Path

OUTPUT_DIR = Path("data/compiled")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

URL = "https://www.cms.gov/files/zip/2024-code-descriptions-tabular-order-updated-02/01/2024.zip"
ZIP_PATH = Path("/tmp/icd10.zip")

print("Downloading ICD-10-CM from CMS.gov (~20MB)...")
urllib.request.urlretrieve(URL, ZIP_PATH)
print("Download complete.")

print("Extracting...")
with zipfile.ZipFile(ZIP_PATH, "r") as z:
    z.extractall("/tmp/icd10_extracted")

# Find the order file
order_file = None
for root, dirs, files in os.walk("/tmp/icd10_extracted"):
    for f in files:
        if "order" in f.lower() and f.endswith(".txt"):
            order_file = os.path.join(root, f)
            break

if not order_file:
    print("Could not find order file. Files found:")
    for root, dirs, files in os.walk("/tmp/icd10_extracted"):
        for f in files:
            print(os.path.join(root, f))
    exit(1)

print(f"Parsing {order_file}...")
icd10_lookup = {}
with open(order_file, "r", encoding="utf-8") as f:
    for line in f:
        # Fixed-width format: order(5) space code(7) space valid(1) space short(60) long
        if len(line) < 77:
            continue
        code = line[6:13].strip()
        valid = line[14].strip()
        description = line[77:].strip()
        if valid == "1" and code and description:
            icd10_lookup[description.lower()] = {
                "term": description,
                "code": code,
                "type": "ICD-10-CM"
            }

print(f"Parsed {len(icd10_lookup)} ICD-10 codes.")
out_path = OUTPUT_DIR / "icd10_lookup.json"
with open(out_path, "w") as f:
    json.dump(icd10_lookup, f)
print(f"Saved to {out_path}")
print("Done. Restart backend to load new data.")