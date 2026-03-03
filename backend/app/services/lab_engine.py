"""
Lab Pattern Engine — Stage 3 of the Waterfall.

Detects lab value patterns in clinical text (e.g., "Glucose: 35")
and flags abnormal results against clinically validated reference ranges.

Reference ranges are sourced from standard clinical laboratory references
and represent adult values unless otherwise noted.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────────────────


class Severity(str, Enum):
    NORMAL = "normal"
    LOW = "low"
    HIGH = "high"
    CRITICAL_LOW = "critical_low"
    CRITICAL_HIGH = "critical_high"


# ── Data Classes ────────────────────────────────────────────────────


@dataclass(frozen=True)
class LabRange:
    """Reference range for a single lab test."""
    name: str
    unit: str
    normal_low: float
    normal_high: float
    critical_low: Optional[float] = None
    critical_high: Optional[float] = None
    loinc_code: Optional[str] = None


@dataclass
class LabResult:
    """Parsed lab value with clinical interpretation."""
    test_name: str
    value: float
    unit: str
    severity: Severity
    normal_range: str
    message: str
    loinc_code: Optional[str] = None


# ── Built-in Lab Reference Ranges (85+ tests) ──────────────────────
# Ranges represent typical adult reference values.
# Critical values indicate life-threatening levels requiring immediate action.

BUILTIN_LAB_RANGES: Dict[str, LabRange] = {
    # ── Basic Metabolic Panel (BMP) ─────────────────────────────────
    "glucose": LabRange("Glucose", "mg/dL", 70, 100, 40, 500, "2345-7"),
    "fasting glucose": LabRange("Fasting Glucose", "mg/dL", 70, 100, 40, 500, "1558-6"),
    "random glucose": LabRange("Random Glucose", "mg/dL", 70, 140, 40, 500, "2345-7"),
    "sodium": LabRange("Sodium", "mEq/L", 136, 145, 120, 160, "2951-2"),
    "na": LabRange("Sodium", "mEq/L", 136, 145, 120, 160, "2951-2"),
    "potassium": LabRange("Potassium", "mEq/L", 3.5, 5.0, 2.5, 6.5, "2823-3"),
    "k": LabRange("Potassium", "mEq/L", 3.5, 5.0, 2.5, 6.5, "2823-3"),
    "chloride": LabRange("Chloride", "mEq/L", 98, 106, 80, 120, "2075-0"),
    "cl": LabRange("Chloride", "mEq/L", 98, 106, 80, 120, "2075-0"),
    "bicarbonate": LabRange("Bicarbonate", "mEq/L", 22, 29, 10, 40, "1963-8"),
    "co2": LabRange("CO2 (Bicarbonate)", "mEq/L", 22, 29, 10, 40, "1963-8"),
    "hco3": LabRange("Bicarbonate", "mEq/L", 22, 29, 10, 40, "1963-8"),
    "bun": LabRange("BUN", "mg/dL", 7, 20, 2, 100, "3094-0"),
    "blood urea nitrogen": LabRange("BUN", "mg/dL", 7, 20, 2, 100, "3094-0"),
    "creatinine": LabRange("Creatinine", "mg/dL", 0.7, 1.3, 0.4, 10.0, "2160-0"),
    "cr": LabRange("Creatinine", "mg/dL", 0.7, 1.3, 0.4, 10.0, "2160-0"),
    "calcium": LabRange("Calcium", "mg/dL", 8.5, 10.5, 6.0, 13.0, "17861-6"),
    "ca": LabRange("Calcium", "mg/dL", 8.5, 10.5, 6.0, 13.0, "17861-6"),
    "ionized calcium": LabRange("Ionized Calcium", "mg/dL", 4.5, 5.3, 3.0, 7.0, "1994-3"),

    # ── Comprehensive Metabolic Panel additions ─────────────────────
    "albumin": LabRange("Albumin", "g/dL", 3.5, 5.5, 1.5, None, "1751-7"),
    "total protein": LabRange("Total Protein", "g/dL", 6.0, 8.3, None, None, "2885-2"),
    "bilirubin": LabRange("Total Bilirubin", "mg/dL", 0.1, 1.2, None, 15.0, "1975-2"),
    "total bilirubin": LabRange("Total Bilirubin", "mg/dL", 0.1, 1.2, None, 15.0, "1975-2"),
    "direct bilirubin": LabRange("Direct Bilirubin", "mg/dL", 0.0, 0.3, None, None, "1968-7"),
    "indirect bilirubin": LabRange("Indirect Bilirubin", "mg/dL", 0.1, 1.0, None, None, "1971-1"),
    "ast": LabRange("AST", "U/L", 10, 40, None, 1000, "1920-8"),
    "sgot": LabRange("AST (SGOT)", "U/L", 10, 40, None, 1000, "1920-8"),
    "alt": LabRange("ALT", "U/L", 7, 56, None, 1000, "1742-6"),
    "sgpt": LabRange("ALT (SGPT)", "U/L", 7, 56, None, 1000, "1742-6"),
    "alp": LabRange("Alkaline Phosphatase", "U/L", 44, 147, None, None, "6768-6"),
    "alkaline phosphatase": LabRange("Alkaline Phosphatase", "U/L", 44, 147, None, None, "6768-6"),
    "ggt": LabRange("GGT", "U/L", 9, 48, None, None, "2324-2"),

    # ── Complete Blood Count (CBC) ──────────────────────────────────
    "wbc": LabRange("WBC", "K/uL", 4.5, 11.0, 2.0, 30.0, "6690-2"),
    "white blood cell": LabRange("WBC", "K/uL", 4.5, 11.0, 2.0, 30.0, "6690-2"),
    "rbc": LabRange("RBC", "M/uL", 4.2, 5.9, 2.0, 8.0, "789-8"),
    "red blood cell": LabRange("RBC", "M/uL", 4.2, 5.9, 2.0, 8.0, "789-8"),
    "hemoglobin": LabRange("Hemoglobin", "g/dL", 12.0, 17.5, 7.0, 20.0, "718-7"),
    "hgb": LabRange("Hemoglobin", "g/dL", 12.0, 17.5, 7.0, 20.0, "718-7"),
    "hb": LabRange("Hemoglobin", "g/dL", 12.0, 17.5, 7.0, 20.0, "718-7"),
    "hematocrit": LabRange("Hematocrit", "%", 36.0, 51.0, 20.0, 60.0, "4544-3"),
    "hct": LabRange("Hematocrit", "%", 36.0, 51.0, 20.0, 60.0, "4544-3"),
    "platelet": LabRange("Platelets", "K/uL", 150, 400, 50, 1000, "777-3"),
    "platelets": LabRange("Platelets", "K/uL", 150, 400, 50, 1000, "777-3"),
    "plt": LabRange("Platelets", "K/uL", 150, 400, 50, 1000, "777-3"),
    "mcv": LabRange("MCV", "fL", 80, 100, None, None, "787-2"),
    "mch": LabRange("MCH", "pg", 27, 33, None, None, "785-6"),
    "mchc": LabRange("MCHC", "g/dL", 32, 36, None, None, "786-4"),
    "rdw": LabRange("RDW", "%", 11.5, 14.5, None, None, "788-0"),
    "mpv": LabRange("MPV", "fL", 7.5, 11.5, None, None, "32623-1"),
    "reticulocyte": LabRange("Reticulocyte Count", "%", 0.5, 2.5, None, None, "17849-1"),

    # ── Differential ────────────────────────────────────────────────
    "neutrophils": LabRange("Neutrophils", "%", 40, 70, None, None, "770-8"),
    "lymphocytes": LabRange("Lymphocytes", "%", 20, 40, None, None, "736-9"),
    "monocytes": LabRange("Monocytes", "%", 2, 8, None, None, "5905-5"),
    "eosinophils": LabRange("Eosinophils", "%", 1, 4, None, None, "713-8"),
    "basophils": LabRange("Basophils", "%", 0, 1, None, None, "706-2"),
    "bands": LabRange("Band Neutrophils", "%", 0, 5, None, None, "764-1"),
    "anc": LabRange("Absolute Neutrophil Count", "K/uL", 1.5, 8.0, 0.5, None, "751-8"),

    # ── Coagulation ─────────────────────────────────────────────────
    "pt": LabRange("Prothrombin Time", "seconds", 11.0, 13.5, None, 30.0, "5902-2"),
    "prothrombin time": LabRange("Prothrombin Time", "seconds", 11.0, 13.5, None, 30.0, "5902-2"),
    "inr": LabRange("INR", "", 0.8, 1.1, None, 5.0, "6301-6"),
    "ptt": LabRange("PTT", "seconds", 25, 35, None, 100, "3173-2"),
    "aptt": LabRange("aPTT", "seconds", 25, 35, None, 100, "3173-2"),
    "fibrinogen": LabRange("Fibrinogen", "mg/dL", 200, 400, 100, None, "3255-7"),
    "d-dimer": LabRange("D-Dimer", "ng/mL", 0, 500, None, None, "48065-7"),

    # ── Cardiac Markers ─────────────────────────────────────────────
    "troponin": LabRange("Troponin I", "ng/mL", 0, 0.04, None, 2.0, "10839-9"),
    "troponin i": LabRange("Troponin I", "ng/mL", 0, 0.04, None, 2.0, "10839-9"),
    "troponin t": LabRange("Troponin T", "ng/mL", 0, 0.01, None, 2.0, "6598-7"),
    "bnp": LabRange("BNP", "pg/mL", 0, 100, None, 5000, "30934-4"),
    "nt-probnp": LabRange("NT-proBNP", "pg/mL", 0, 125, None, None, "33762-6"),
    "ck": LabRange("Creatine Kinase", "U/L", 22, 198, None, None, "2157-6"),
    "ck-mb": LabRange("CK-MB", "ng/mL", 0, 5, None, None, "13969-1"),
    "ldh": LabRange("LDH", "U/L", 140, 280, None, None, "2532-0"),

    # ── Thyroid ─────────────────────────────────────────────────────
    "tsh": LabRange("TSH", "mIU/L", 0.27, 4.2, 0.01, 50, "3016-3"),
    "free t4": LabRange("Free T4", "ng/dL", 0.9, 1.7, 0.3, 5.0, "3024-7"),
    "ft4": LabRange("Free T4", "ng/dL", 0.9, 1.7, 0.3, 5.0, "3024-7"),
    "free t3": LabRange("Free T3", "pg/mL", 2.0, 4.4, None, None, "3051-0"),
    "ft3": LabRange("Free T3", "pg/mL", 2.0, 4.4, None, None, "3051-0"),
    "total t4": LabRange("Total T4", "ug/dL", 5.0, 12.0, None, None, "3026-2"),
    "total t3": LabRange("Total T3", "ng/dL", 80, 200, None, None, "3053-6"),

    # ── Lipid Panel ─────────────────────────────────────────────────
    "total cholesterol": LabRange("Total Cholesterol", "mg/dL", 0, 200, None, 400, "2093-3"),
    "cholesterol": LabRange("Total Cholesterol", "mg/dL", 0, 200, None, 400, "2093-3"),
    "ldl": LabRange("LDL Cholesterol", "mg/dL", 0, 100, None, 300, "2089-1"),
    "hdl": LabRange("HDL Cholesterol", "mg/dL", 40, 60, 20, None, "2085-9"),
    "triglycerides": LabRange("Triglycerides", "mg/dL", 0, 150, None, 1000, "2571-8"),
    "tg": LabRange("Triglycerides", "mg/dL", 0, 150, None, 1000, "2571-8"),
    "vldl": LabRange("VLDL", "mg/dL", 5, 40, None, None, "2091-7"),

    # ── Iron Studies ────────────────────────────────────────────────
    "iron": LabRange("Serum Iron", "ug/dL", 60, 170, None, None, "2498-4"),
    "ferritin": LabRange("Ferritin", "ng/mL", 12, 300, None, 1000, "2276-4"),
    "tibc": LabRange("TIBC", "ug/dL", 250, 400, None, None, "2500-7"),
    "transferrin saturation": LabRange("Transferrin Saturation", "%", 20, 50, None, None, "2502-3"),

    # ── Inflammatory Markers ────────────────────────────────────────
    "crp": LabRange("C-Reactive Protein", "mg/L", 0, 3.0, None, None, "1988-5"),
    "c-reactive protein": LabRange("C-Reactive Protein", "mg/L", 0, 3.0, None, None, "1988-5"),
    "esr": LabRange("ESR", "mm/hr", 0, 20, None, None, "4537-7"),
    "sed rate": LabRange("ESR", "mm/hr", 0, 20, None, None, "4537-7"),
    "procalcitonin": LabRange("Procalcitonin", "ng/mL", 0, 0.1, None, 10, "75241-0"),

    # ── Arterial Blood Gas (ABG) ────────────────────────────────────
    "ph": LabRange("pH", "", 7.35, 7.45, 7.0, 7.7, "2744-1"),
    "pco2": LabRange("pCO2", "mmHg", 35, 45, 20, 70, "2019-8"),
    "po2": LabRange("pO2", "mmHg", 80, 100, 40, None, "2703-7"),
    "pao2": LabRange("PaO2", "mmHg", 80, 100, 40, None, "2703-7"),
    "sao2": LabRange("SaO2", "%", 95, 100, 80, None, "2708-6"),
    "base excess": LabRange("Base Excess", "mEq/L", -2, 2, -10, 10, "11555-0"),

    # ── Diabetes Monitoring ─────────────────────────────────────────
    "hba1c": LabRange("HbA1c", "%", 4.0, 5.6, None, 14.0, "4548-4"),
    "a1c": LabRange("HbA1c", "%", 4.0, 5.6, None, 14.0, "4548-4"),
    "hemoglobin a1c": LabRange("HbA1c", "%", 4.0, 5.6, None, 14.0, "4548-4"),
    "fructosamine": LabRange("Fructosamine", "umol/L", 200, 285, None, None, "1784-8"),

    # ── Renal / Electrolytes (additional) ───────────────────────────
    "magnesium": LabRange("Magnesium", "mg/dL", 1.7, 2.2, 1.0, 4.0, "19123-9"),
    "mg": LabRange("Magnesium", "mg/dL", 1.7, 2.2, 1.0, 4.0, "19123-9"),
    "phosphorus": LabRange("Phosphorus", "mg/dL", 2.5, 4.5, 1.0, 8.0, "2777-1"),
    "phosphate": LabRange("Phosphorus", "mg/dL", 2.5, 4.5, 1.0, 8.0, "2777-1"),
    "uric acid": LabRange("Uric Acid", "mg/dL", 3.0, 7.0, None, 12.0, "3084-1"),
    "osmolality": LabRange("Serum Osmolality", "mOsm/kg", 275, 295, 240, 330, "2692-2"),
    "anion gap": LabRange("Anion Gap", "mEq/L", 8, 12, None, 20, "33037-3"),
    "lactate": LabRange("Lactate", "mmol/L", 0.5, 2.0, None, 4.0, "2524-7"),
    "lactic acid": LabRange("Lactate", "mmol/L", 0.5, 2.0, None, 4.0, "2524-7"),
    "ammonia": LabRange("Ammonia", "umol/L", 15, 45, None, 200, "1841-6"),

    # ── Pancreatic ──────────────────────────────────────────────────
    "lipase": LabRange("Lipase", "U/L", 0, 160, None, 600, "3040-3"),
    "amylase": LabRange("Amylase", "U/L", 28, 100, None, 500, "1798-8"),

    # ── Urinalysis ──────────────────────────────────────────────────
    "urine ph": LabRange("Urine pH", "", 4.5, 8.0, None, None, "2756-5"),
    "urine specific gravity": LabRange("Urine Specific Gravity", "", 1.005, 1.030, None, None, "2965-2"),
    "urine protein": LabRange("Urine Protein", "mg/dL", 0, 14, None, None, "2888-6"),
    "urine glucose": LabRange("Urine Glucose", "mg/dL", 0, 15, None, None, "2350-7"),

    # ── Hormones ────────────────────────────────────────────────────
    "cortisol": LabRange("Cortisol (AM)", "ug/dL", 6.2, 19.4, None, None, "2143-6"),
    "pth": LabRange("PTH", "pg/mL", 15, 65, None, None, "2731-8"),
    "parathyroid hormone": LabRange("PTH", "pg/mL", 15, 65, None, None, "2731-8"),
    "testosterone": LabRange("Testosterone", "ng/dL", 270, 1070, None, None, "2986-8"),
    "estradiol": LabRange("Estradiol", "pg/mL", 15, 350, None, None, "2243-4"),
    "prolactin": LabRange("Prolactin", "ng/mL", 2, 18, None, None, "2842-3"),
    "fsh": LabRange("FSH", "mIU/mL", 1.5, 12.4, None, None, "15067-2"),
    "lh": LabRange("LH", "mIU/mL", 1.7, 8.6, None, None, "10501-5"),

    # ── Vitamins ────────────────────────────────────────────────────
    "vitamin d": LabRange("Vitamin D (25-OH)", "ng/mL", 30, 100, None, 150, "1989-3"),
    "25-oh vitamin d": LabRange("Vitamin D (25-OH)", "ng/mL", 30, 100, None, 150, "1989-3"),
    "vitamin b12": LabRange("Vitamin B12", "pg/mL", 200, 900, None, None, "2132-9"),
    "b12": LabRange("Vitamin B12", "pg/mL", 200, 900, None, None, "2132-9"),
    "folate": LabRange("Folate", "ng/mL", 2.7, 17.0, None, None, "2284-8"),
    "folic acid": LabRange("Folate", "ng/mL", 2.7, 17.0, None, None, "2284-8"),

    # ── Tumor Markers ───────────────────────────────────────────────
    "psa": LabRange("PSA", "ng/mL", 0, 4.0, None, None, "2857-1"),
    "cea": LabRange("CEA", "ng/mL", 0, 3.0, None, None, "2039-6"),
    "ca-125": LabRange("CA-125", "U/mL", 0, 35, None, None, "10334-1"),
    "ca 19-9": LabRange("CA 19-9", "U/mL", 0, 37, None, None, "24108-3"),
    "afp": LabRange("AFP", "ng/mL", 0, 10, None, None, "1834-1"),
}


# ── Regex Pattern for Lab Values ────────────────────────────────────
# Matches patterns like: "Glucose: 35", "Na 128", "K+ 6.8", "Hgb: 7.2 g/dL"
LAB_PATTERN = re.compile(
    r"(?P<test>[A-Za-z][A-Za-z0-9\s\-\+/()]*?)"   # test name
    r"\s*[:=]\s*"                                     # separator (: or =)
    r"(?P<value>\d+\.?\d*)"                           # numeric value
    r"(?:\s*(?P<unit>[A-Za-z/%]+(?:/[A-Za-z]+)?))?",  # optional unit
    re.IGNORECASE,
)


class LabEngine:
    """
    Detects lab value patterns in clinical text and flags abnormalities.
    """

    def __init__(self) -> None:
        self._ranges: Dict[str, LabRange] = {}
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def lab_ranges_count(self) -> int:
        return len(self._ranges)

    async def load(self) -> None:
        """Load lab ranges from built-in defaults + optional JSON override."""
        settings = get_settings()

        self._ranges = dict(BUILTIN_LAB_RANGES)

        # Override / extend from compiled JSON if available
        ranges_path = Path(settings.lab_ranges_path)
        if ranges_path.exists():
            try:
                with open(ranges_path, "r", encoding="utf-8") as f:
                    custom = json.load(f)
                for key, entry in custom.items():
                    self._ranges[key.lower()] = LabRange(**entry)
                logger.info(
                    "Loaded %d custom lab ranges from %s", len(custom), ranges_path
                )
            except Exception as e:
                logger.warning("Failed to load custom lab ranges: %s", e)

        logger.info("Total lab ranges loaded: %d", len(self._ranges))
        self._loaded = True

    def detect_lab_pattern(self, text: str) -> Optional[LabResult]:
        """
        Scan the tail of the text for a lab value pattern.

        Only looks at the last ~80 characters to stay relevant to
        what the user just typed. Returns the first abnormal match,
        or None if no lab pattern is detected or the value is normal.
        """
        # Focus on recent text (where the user is actively typing)
        tail = text[-80:] if len(text) > 80 else text

        for match in LAB_PATTERN.finditer(tail):
            test_name_raw = match.group("test").strip()
            test_key = test_name_raw.lower().strip()
            value_str = match.group("value")

            try:
                value = float(value_str)
            except ValueError:
                continue

            # Try exact match, then partial match
            lab_range = self._find_range(test_key)
            if not lab_range:
                continue

            severity = self._classify(value, lab_range)

            # Only return a result if abnormal
            if severity == Severity.NORMAL:
                continue

            normal_str = f"{lab_range.normal_low}–{lab_range.normal_high} {lab_range.unit}"
            message = self._build_message(lab_range.name, value, severity, normal_str)

            return LabResult(
                test_name=lab_range.name,
                value=value,
                unit=lab_range.unit,
                severity=severity,
                normal_range=normal_str,
                message=message,
                loinc_code=lab_range.loinc_code,
            )

        return None

    # ── Private Helpers ─────────────────────────────────────────────

    def _find_range(self, test_key: str) -> Optional[LabRange]:
        """Find the best matching lab range for a test name."""
        # Exact match
        if test_key in self._ranges:
            return self._ranges[test_key]
        # Try without trailing +/- (e.g., "k+" → "k")
        cleaned = test_key.rstrip("+-")
        if cleaned in self._ranges:
            return self._ranges[cleaned]
        # Partial match: check if test_key is a suffix/prefix of any range key
        for key, rng in self._ranges.items():
            if key.startswith(test_key) or test_key.startswith(key):
                return rng
        return None

    @staticmethod
    def _classify(value: float, lab_range: LabRange) -> Severity:
        """Classify a lab value against its reference range."""
        if lab_range.critical_low is not None and value < lab_range.critical_low:
            return Severity.CRITICAL_LOW
        if lab_range.critical_high is not None and value > lab_range.critical_high:
            return Severity.CRITICAL_HIGH
        if value < lab_range.normal_low:
            return Severity.LOW
        if value > lab_range.normal_high:
            return Severity.HIGH
        return Severity.NORMAL

    @staticmethod
    def _build_message(
        name: str, value: float, severity: Severity, normal_range: str
    ) -> str:
        """Build a human-readable warning message."""
        labels = {
            Severity.LOW: "Low",
            Severity.HIGH: "High",
            Severity.CRITICAL_LOW: "CRITICAL LOW",
            Severity.CRITICAL_HIGH: "CRITICAL HIGH",
        }
        prefix = labels.get(severity, "Abnormal")
        icon = "\u26a0\ufe0f" if "CRITICAL" in prefix else "\u2139\ufe0f"
        return f"{icon} {prefix} — normal range: {normal_range}"
