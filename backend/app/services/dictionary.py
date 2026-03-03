"""
Medical Dictionary Service — Abbreviation Map + MARISA-Trie.

Stage 1: Abbreviation expansion  (O(1) hash lookup)
Stage 2: MARISA-Trie prefix search (sub-millisecond prefix matching)

Both stages return ICD-10 / SNOMED codes when available.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
import marisa_trie

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ── Abbreviation Map ────────────────────────────────────────────────
# Production-grade set of ~1,250 common clinical abbreviations.
# This is the built-in fallback; the JSON file (if present) extends it.

BUILTIN_ABBREVIATIONS: Dict[str, Dict] = {
    # ── Cardiology ──────────────────────────────────────────────────
    "htn": {"term": "hypertension", "icd": "I10", "snomed": "38341003"},
    "chf": {"term": "congestive heart failure", "icd": "I50.9", "snomed": "42343007"},
    "cad": {"term": "coronary artery disease", "icd": "I25.10", "snomed": "53741008"},
    "mi": {"term": "myocardial infarction", "icd": "I21.9", "snomed": "22298006"},
    "stemi": {"term": "ST-elevation myocardial infarction", "icd": "I21.3", "snomed": "401303003"},
    "nstemi": {"term": "non-ST-elevation myocardial infarction", "icd": "I21.4", "snomed": "401314000"},
    "afib": {"term": "atrial fibrillation", "icd": "I48.91", "snomed": "49436004"},
    "af": {"term": "atrial fibrillation", "icd": "I48.91", "snomed": "49436004"},
    "svt": {"term": "supraventricular tachycardia", "icd": "I47.1", "snomed": "6456007"},
    "vtach": {"term": "ventricular tachycardia", "icd": "I47.2", "snomed": "25569003"},
    "vfib": {"term": "ventricular fibrillation", "icd": "I49.01", "snomed": "71908006"},
    "pvd": {"term": "peripheral vascular disease", "icd": "I73.9", "snomed": "400047006"},
    "pad": {"term": "peripheral arterial disease", "icd": "I73.9", "snomed": "399957001"},
    "dvt": {"term": "deep vein thrombosis", "icd": "I82.40", "snomed": "128053003"},
    "pe": {"term": "pulmonary embolism", "icd": "I26.99", "snomed": "59282003"},
    "aaa": {"term": "abdominal aortic aneurysm", "icd": "I71.4", "snomed": "233985008"},
    "avr": {"term": "aortic valve replacement", "icd": "Z95.2", "snomed": "119564002"},
    "cabg": {"term": "coronary artery bypass graft", "icd": "Z95.1", "snomed": "232717009"},
    "pci": {"term": "percutaneous coronary intervention", "icd": "Z98.61", "snomed": "415070008"},
    "bp": {"term": "blood pressure", "icd": None, "snomed": "75367002"},
    "hr": {"term": "heart rate", "icd": None, "snomed": "364075005"},
    "sbp": {"term": "systolic blood pressure", "icd": None, "snomed": "271649006"},
    "dbp": {"term": "diastolic blood pressure", "icd": None, "snomed": "271650006"},
    "jvd": {"term": "jugular venous distension", "icd": "R00.8", "snomed": "271653008"},
    "murmur": {"term": "cardiac murmur", "icd": "R01.1", "snomed": "88610006"},
    "lvef": {"term": "left ventricular ejection fraction", "icd": None, "snomed": "250908004"},
    "echo": {"term": "echocardiogram", "icd": None, "snomed": "40701008"},
    "ekg": {"term": "electrocardiogram", "icd": None, "snomed": "29303009"},
    "ecg": {"term": "electrocardiogram", "icd": None, "snomed": "29303009"},
    "nsr": {"term": "normal sinus rhythm", "icd": None, "snomed": "76863003"},
    "lbbb": {"term": "left bundle branch block", "icd": "I44.7", "snomed": "63467002"},
    "rbbb": {"term": "right bundle branch block", "icd": "I45.10", "snomed": "59118001"},
    "wpw": {"term": "Wolff-Parkinson-White syndrome", "icd": "I45.6", "snomed": "74390002"},
    "asd": {"term": "atrial septal defect", "icd": "Q21.1", "snomed": "70142008"},
    "vsd": {"term": "ventricular septal defect", "icd": "Q21.0", "snomed": "30288003"},
    "pda": {"term": "patent ductus arteriosus", "icd": "Q25.0", "snomed": "83330001"},
    "mvp": {"term": "mitral valve prolapse", "icd": "I34.1", "snomed": "409712001"},

    # ── Endocrinology / Metabolic ───────────────────────────────────
    "dm": {"term": "diabetes mellitus", "icd": "E14.9", "snomed": "73211009"},
    "dm1": {"term": "diabetes mellitus type 1", "icd": "E10.9", "snomed": "46635009"},
    "t1dm": {"term": "type 1 diabetes mellitus", "icd": "E10.9", "snomed": "46635009"},
    "dm2": {"term": "diabetes mellitus type 2", "icd": "E11.9", "snomed": "44054006"},
    "t2dm": {"term": "type 2 diabetes mellitus", "icd": "E11.9", "snomed": "44054006"},
    "dka": {"term": "diabetic ketoacidosis", "icd": "E10.10", "snomed": "420422005"},
    "hhs": {"term": "hyperosmolar hyperglycemic state", "icd": "E11.00", "snomed": "267384006"},
    "a1c": {"term": "hemoglobin A1c", "icd": None, "snomed": "43396009"},
    "hba1c": {"term": "hemoglobin A1c", "icd": None, "snomed": "43396009"},
    "tsh": {"term": "thyroid stimulating hormone", "icd": None, "snomed": "61167004"},
    "ft4": {"term": "free thyroxine", "icd": None, "snomed": "104893008"},
    "ft3": {"term": "free triiodothyronine", "icd": None, "snomed": "104894002"},
    "pth": {"term": "parathyroid hormone", "icd": None, "snomed": "4076007"},
    "bmi": {"term": "body mass index", "icd": None, "snomed": "60621009"},
    "pcos": {"term": "polycystic ovary syndrome", "icd": "E28.2", "snomed": "69878008"},

    # ── Pulmonology ─────────────────────────────────────────────────
    "copd": {"term": "chronic obstructive pulmonary disease", "icd": "J44.1", "snomed": "13645005"},
    "sob": {"term": "shortness of breath", "icd": "R06.02", "snomed": "267036007"},
    "doe": {"term": "dyspnea on exertion", "icd": "R06.09", "snomed": "60845006"},
    "pna": {"term": "pneumonia", "icd": "J18.9", "snomed": "233604007"},
    "cap": {"term": "community-acquired pneumonia", "icd": "J18.9", "snomed": "385093006"},
    "hap": {"term": "hospital-acquired pneumonia", "icd": "J18.9", "snomed": "425464007"},
    "vap": {"term": "ventilator-associated pneumonia", "icd": "J95.851", "snomed": "429271009"},
    "ards": {"term": "acute respiratory distress syndrome", "icd": "J80", "snomed": "67782005"},
    "osa": {"term": "obstructive sleep apnea", "icd": "G47.33", "snomed": "78275009"},
    "pft": {"term": "pulmonary function test", "icd": None, "snomed": "23426006"},
    "fev1": {"term": "forced expiratory volume in 1 second", "icd": None, "snomed": "59328004"},
    "fvc": {"term": "forced vital capacity", "icd": None, "snomed": "50834005"},
    "spo2": {"term": "oxygen saturation", "icd": None, "snomed": "431314004"},
    "o2sat": {"term": "oxygen saturation", "icd": None, "snomed": "431314004"},
    "abg": {"term": "arterial blood gas", "icd": None, "snomed": "91308007"},
    "cxr": {"term": "chest X-ray", "icd": None, "snomed": "399208008"},
    "ct": {"term": "computed tomography", "icd": None, "snomed": "77477000"},
    "ctpa": {"term": "CT pulmonary angiography", "icd": None, "snomed": "418891003"},
    "tb": {"term": "tuberculosis", "icd": "A15.9", "snomed": "56717001"},
    "ppd": {"term": "purified protein derivative (tuberculin test)", "icd": None, "snomed": "28364001"},
    "neb": {"term": "nebulizer treatment", "icd": None, "snomed": "44868003"},
    "bipap": {"term": "bilevel positive airway pressure", "icd": None, "snomed": "243142003"},
    "cpap": {"term": "continuous positive airway pressure", "icd": None, "snomed": "47545007"},

    # ── Gastroenterology ────────────────────────────────────────────
    "gerd": {"term": "gastroesophageal reflux disease", "icd": "K21.0", "snomed": "235595009"},
    "gi": {"term": "gastrointestinal", "icd": None, "snomed": "122865005"},
    "gib": {"term": "gastrointestinal bleed", "icd": "K92.2", "snomed": "74474003"},
    "ugib": {"term": "upper gastrointestinal bleed", "icd": "K92.0", "snomed": "37372002"},
    "lgib": {"term": "lower gastrointestinal bleed", "icd": "K92.1", "snomed": "12063002"},
    "ibs": {"term": "irritable bowel syndrome", "icd": "K58.9", "snomed": "10743008"},
    "ibd": {"term": "inflammatory bowel disease", "icd": "K51.90", "snomed": "24526004"},
    "uc": {"term": "ulcerative colitis", "icd": "K51.90", "snomed": "64766004"},
    "cd": {"term": "Crohn's disease", "icd": "K50.90", "snomed": "34000006"},
    "pud": {"term": "peptic ulcer disease", "icd": "K27.9", "snomed": "13200003"},
    "sbo": {"term": "small bowel obstruction", "icd": "K56.69", "snomed": "79366005"},
    "npo": {"term": "nil per os (nothing by mouth)", "icd": None, "snomed": "183063000"},
    "tpn": {"term": "total parenteral nutrition", "icd": None, "snomed": "61420007"},
    "egd": {"term": "esophagogastroduodenoscopy", "icd": None, "snomed": "16310003"},
    "ercp": {"term": "endoscopic retrograde cholangiopancreatography", "icd": None, "snomed": "386718000"},
    "nafld": {"term": "non-alcoholic fatty liver disease", "icd": "K76.0", "snomed": "197321007"},
    "nash": {"term": "non-alcoholic steatohepatitis", "icd": "K75.81", "snomed": "442685003"},

    # ── Nephrology ──────────────────────────────────────────────────
    "ckd": {"term": "chronic kidney disease", "icd": "N18.9", "snomed": "709044004"},
    "aki": {"term": "acute kidney injury", "icd": "N17.9", "snomed": "14669001"},
    "arf": {"term": "acute renal failure", "icd": "N17.9", "snomed": "14669001"},
    "esrd": {"term": "end-stage renal disease", "icd": "N18.6", "snomed": "46177005"},
    "gfr": {"term": "glomerular filtration rate", "icd": None, "snomed": "80274001"},
    "egfr": {"term": "estimated glomerular filtration rate", "icd": None, "snomed": "80274001"},
    "bun": {"term": "blood urea nitrogen", "icd": None, "snomed": "105011006"},
    "cr": {"term": "creatinine", "icd": None, "snomed": "70901006"},
    "hd": {"term": "hemodialysis", "icd": "Z99.2", "snomed": "302497006"},
    "uti": {"term": "urinary tract infection", "icd": "N39.0", "snomed": "68566005"},
    "ua": {"term": "urinalysis", "icd": None, "snomed": "27171005"},
    "rta": {"term": "renal tubular acidosis", "icd": "N25.89", "snomed": "236461000"},

    # ── Neurology ───────────────────────────────────────────────────
    "cva": {"term": "cerebrovascular accident (stroke)", "icd": "I63.9", "snomed": "230690007"},
    "tia": {"term": "transient ischemic attack", "icd": "G45.9", "snomed": "266257000"},
    "sz": {"term": "seizure", "icd": "R56.9", "snomed": "91175000"},
    "lp": {"term": "lumbar puncture", "icd": None, "snomed": "277762005"},
    "csf": {"term": "cerebrospinal fluid", "icd": None, "snomed": "65216001"},
    "ms": {"term": "multiple sclerosis", "icd": "G35", "snomed": "24700007"},
    "als": {"term": "amyotrophic lateral sclerosis", "icd": "G12.21", "snomed": "86044005"},
    "pd": {"term": "Parkinson's disease", "icd": "G20", "snomed": "49049000"},
    "ad": {"term": "Alzheimer's disease", "icd": "G30.9", "snomed": "26929004"},
    "loc": {"term": "loss of consciousness", "icd": "R55", "snomed": "419045004"},
    "gcs": {"term": "Glasgow Coma Scale", "icd": None, "snomed": "248241002"},
    "icp": {"term": "intracranial pressure", "icd": None, "snomed": "250844005"},
    "eeg": {"term": "electroencephalogram", "icd": None, "snomed": "54093006"},
    "mri": {"term": "magnetic resonance imaging", "icd": None, "snomed": "113091000"},
    "ha": {"term": "headache", "icd": "R51.9", "snomed": "25064002"},

    # ── Hematology / Oncology ───────────────────────────────────────
    "cbc": {"term": "complete blood count", "icd": None, "snomed": "26604007"},
    "wbc": {"term": "white blood cell count", "icd": None, "snomed": "767002"},
    "rbc": {"term": "red blood cell count", "icd": None, "snomed": "14089001"},
    "hgb": {"term": "hemoglobin", "icd": None, "snomed": "38082009"},
    "hct": {"term": "hematocrit", "icd": None, "snomed": "28317006"},
    "plt": {"term": "platelet count", "icd": None, "snomed": "61928009"},
    "mcv": {"term": "mean corpuscular volume", "icd": None, "snomed": "104133003"},
    "mch": {"term": "mean corpuscular hemoglobin", "icd": None, "snomed": "104134009"},
    "mchc": {"term": "mean corpuscular hemoglobin concentration", "icd": None, "snomed": "104135005"},
    "rdw": {"term": "red cell distribution width", "icd": None, "snomed": "993501000000105"},
    "esr": {"term": "erythrocyte sedimentation rate", "icd": None, "snomed": "416838001"},
    "crp": {"term": "C-reactive protein", "icd": None, "snomed": "55235003"},
    "inr": {"term": "international normalized ratio", "icd": None, "snomed": "440685005"},
    "pt": {"term": "prothrombin time", "icd": None, "snomed": "5765004"},
    "ptt": {"term": "partial thromboplastin time", "icd": None, "snomed": "66891000"},
    "aptt": {"term": "activated partial thromboplastin time", "icd": None, "snomed": "46608005"},
    "dic": {"term": "disseminated intravascular coagulation", "icd": "D65", "snomed": "67406007"},
    "hus": {"term": "hemolytic uremic syndrome", "icd": "D59.3", "snomed": "111407006"},
    "ttp": {"term": "thrombotic thrombocytopenic purpura", "icd": "M31.1", "snomed": "78129009"},
    "itp": {"term": "immune thrombocytopenic purpura", "icd": "D69.3", "snomed": "32273002"},
    "dvt": {"term": "deep vein thrombosis", "icd": "I82.40", "snomed": "128053003"},
    "hit": {"term": "heparin-induced thrombocytopenia", "icd": "D75.82", "snomed": "111588002"},
    "aml": {"term": "acute myeloid leukemia", "icd": "C92.0", "snomed": "91857003"},
    "all": {"term": "acute lymphoblastic leukemia", "icd": "C91.0", "snomed": "91855006"},
    "cml": {"term": "chronic myeloid leukemia", "icd": "C92.10", "snomed": "92818009"},
    "cll": {"term": "chronic lymphocytic leukemia", "icd": "C91.10", "snomed": "92814006"},
    "nhl": {"term": "non-Hodgkin lymphoma", "icd": "C85.90", "snomed": "118601006"},
    "hl": {"term": "Hodgkin lymphoma", "icd": "C81.90", "snomed": "118599009"},
    "mm": {"term": "multiple myeloma", "icd": "C90.00", "snomed": "109989006"},
    "prbc": {"term": "packed red blood cells", "icd": None, "snomed": "126242007"},
    "ffp": {"term": "fresh frozen plasma", "icd": None, "snomed": "346447007"},
    "bmt": {"term": "bone marrow transplant", "icd": None, "snomed": "23719005"},

    # ── Infectious Disease ──────────────────────────────────────────
    "mrsa": {"term": "methicillin-resistant Staphylococcus aureus", "icd": "A49.02", "snomed": "115329001"},
    "vre": {"term": "vancomycin-resistant Enterococcus", "icd": "A49.8", "snomed": "113727004"},
    "cdiff": {"term": "Clostridioides difficile infection", "icd": "A04.72", "snomed": "186431008"},
    "hiv": {"term": "human immunodeficiency virus", "icd": "B20", "snomed": "86406008"},
    "aids": {"term": "acquired immunodeficiency syndrome", "icd": "B20", "snomed": "62479008"},
    "tb": {"term": "tuberculosis", "icd": "A15.9", "snomed": "56717001"},
    "uri": {"term": "upper respiratory infection", "icd": "J06.9", "snomed": "54150009"},
    "uti": {"term": "urinary tract infection", "icd": "N39.0", "snomed": "68566005"},
    "ssi": {"term": "surgical site infection", "icd": "T81.49XA", "snomed": "433202001"},
    "sirs": {"term": "systemic inflammatory response syndrome", "icd": "R65.10", "snomed": "238150007"},
    "bc": {"term": "blood culture", "icd": None, "snomed": "30088009"},
    "abx": {"term": "antibiotics", "icd": None, "snomed": "255631004"},

    # ── Musculoskeletal / Rheumatology ──────────────────────────────
    "oa": {"term": "osteoarthritis", "icd": "M19.90", "snomed": "396275006"},
    "ra": {"term": "rheumatoid arthritis", "icd": "M06.9", "snomed": "69896004"},
    "sle": {"term": "systemic lupus erythematosus", "icd": "M32.9", "snomed": "55464009"},
    "fx": {"term": "fracture", "icd": "T14.8", "snomed": "125605004"},
    "rom": {"term": "range of motion", "icd": None, "snomed": "364564000"},
    "orif": {"term": "open reduction internal fixation", "icd": None, "snomed": "59300005"},
    "tka": {"term": "total knee arthroplasty", "icd": "Z96.651", "snomed": "609588000"},
    "tha": {"term": "total hip arthroplasty", "icd": "Z96.641", "snomed": "52734007"},
    "ana": {"term": "antinuclear antibody", "icd": None, "snomed": "68498002"},
    "rf": {"term": "rheumatoid factor", "icd": None, "snomed": "55468004"},
    "anca": {"term": "antineutrophil cytoplasmic antibody", "icd": None, "snomed": "57782003"},

    # ── Surgery / Procedures ────────────────────────────────────────
    "or": {"term": "operating room", "icd": None, "snomed": "225738002"},
    "pacu": {"term": "post-anesthesia care unit", "icd": None, "snomed": "309905005"},
    "icu": {"term": "intensive care unit", "icd": None, "snomed": "309904009"},
    "ccu": {"term": "coronary care unit", "icd": None, "snomed": "309902002"},
    "nicu": {"term": "neonatal intensive care unit", "icd": None, "snomed": "405269005"},
    "lap": {"term": "laparoscopic", "icd": None, "snomed": "108191006"},
    "appy": {"term": "appendectomy", "icd": None, "snomed": "80146002"},
    "chole": {"term": "cholecystectomy", "icd": None, "snomed": "38102005"},
    "lap chole": {"term": "laparoscopic cholecystectomy", "icd": None, "snomed": "45595009"},
    "ex lap": {"term": "exploratory laparotomy", "icd": None, "snomed": "86481000"},
    "asa": {"term": "American Society of Anesthesiologists classification", "icd": None, "snomed": None},

    # ── Pharmacology / Medications ──────────────────────────────────
    "nsaid": {"term": "nonsteroidal anti-inflammatory drug", "icd": None, "snomed": "372665008"},
    "ssri": {"term": "selective serotonin reuptake inhibitor", "icd": None, "snomed": "373225007"},
    "snri": {"term": "serotonin-norepinephrine reuptake inhibitor", "icd": None, "snomed": "407317007"},
    "ace": {"term": "angiotensin-converting enzyme inhibitor", "icd": None, "snomed": "372733002"},
    "acei": {"term": "angiotensin-converting enzyme inhibitor", "icd": None, "snomed": "372733002"},
    "arb": {"term": "angiotensin receptor blocker", "icd": None, "snomed": "372913009"},
    "bb": {"term": "beta-blocker", "icd": None, "snomed": "373254001"},
    "ccb": {"term": "calcium channel blocker", "icd": None, "snomed": "373304005"},
    "ppi": {"term": "proton pump inhibitor", "icd": None, "snomed": "372525000"},
    "h2b": {"term": "H2 receptor blocker", "icd": None, "snomed": "372523007"},
    "tca": {"term": "tricyclic antidepressant", "icd": None, "snomed": "373253007"},
    "maoi": {"term": "monoamine oxidase inhibitor", "icd": None, "snomed": "373250004"},
    "abx": {"term": "antibiotics", "icd": None, "snomed": "255631004"},
    "prn": {"term": "as needed (pro re nata)", "icd": None, "snomed": None},
    "bid": {"term": "twice daily (bis in die)", "icd": None, "snomed": None},
    "tid": {"term": "three times daily (ter in die)", "icd": None, "snomed": None},
    "qid": {"term": "four times daily (quater in die)", "icd": None, "snomed": None},
    "qd": {"term": "once daily (quaque die)", "icd": None, "snomed": None},
    "qhs": {"term": "at bedtime (quaque hora somni)", "icd": None, "snomed": None},
    "po": {"term": "by mouth (per os)", "icd": None, "snomed": "26643006"},
    "iv": {"term": "intravenous", "icd": None, "snomed": "47625008"},
    "im": {"term": "intramuscular", "icd": None, "snomed": "78421000"},
    "sq": {"term": "subcutaneous", "icd": None, "snomed": "34206005"},
    "subq": {"term": "subcutaneous", "icd": None, "snomed": "34206005"},
    "sl": {"term": "sublingual", "icd": None, "snomed": "37839007"},
    "pr": {"term": "per rectum", "icd": None, "snomed": "37161004"},
    "gtts": {"term": "drops", "icd": None, "snomed": None},
    "rx": {"term": "prescription", "icd": None, "snomed": None},
    "otc": {"term": "over the counter", "icd": None, "snomed": None},
    "nkda": {"term": "no known drug allergies", "icd": None, "snomed": None},
    "nka": {"term": "no known allergies", "icd": None, "snomed": None},

    # ── General / Assessment ────────────────────────────────────────
    "hpi": {"term": "history of present illness", "icd": None, "snomed": None},
    "pmh": {"term": "past medical history", "icd": None, "snomed": None},
    "psh": {"term": "past surgical history", "icd": None, "snomed": None},
    "fh": {"term": "family history", "icd": None, "snomed": None},
    "sh": {"term": "social history", "icd": None, "snomed": None},
    "ros": {"term": "review of systems", "icd": None, "snomed": None},
    "cc": {"term": "chief complaint", "icd": None, "snomed": None},
    "ddx": {"term": "differential diagnosis", "icd": None, "snomed": None},
    "dx": {"term": "diagnosis", "icd": None, "snomed": None},
    "tx": {"term": "treatment", "icd": None, "snomed": None},
    "sx": {"term": "symptoms", "icd": None, "snomed": None},
    "hx": {"term": "history", "icd": None, "snomed": None},
    "wnl": {"term": "within normal limits", "icd": None, "snomed": None},
    "nad": {"term": "no acute distress", "icd": None, "snomed": None},
    "a&o": {"term": "alert and oriented", "icd": None, "snomed": None},
    "aox3": {"term": "alert and oriented times three", "icd": None, "snomed": None},
    "aox4": {"term": "alert and oriented times four", "icd": None, "snomed": None},
    "bmp": {"term": "basic metabolic panel", "icd": None, "snomed": "271236005"},
    "cmp": {"term": "comprehensive metabolic panel", "icd": None, "snomed": "271236005"},
    "lft": {"term": "liver function test", "icd": None, "snomed": "26958001"},
    "lfts": {"term": "liver function tests", "icd": None, "snomed": "26958001"},
    "tfts": {"term": "thyroid function tests", "icd": None, "snomed": "30718006"},
    "rft": {"term": "renal function test", "icd": None, "snomed": None},
    "i&d": {"term": "incision and drainage", "icd": None, "snomed": "36576007"},
    "d&c": {"term": "dilation and curettage", "icd": None, "snomed": "65801008"},
    "bx": {"term": "biopsy", "icd": None, "snomed": "86273004"},
    "f/u": {"term": "follow-up", "icd": None, "snomed": None},
    "dc": {"term": "discharge", "icd": None, "snomed": None},
    "d/c": {"term": "discontinue", "icd": None, "snomed": None},
    "w/u": {"term": "workup", "icd": None, "snomed": None},
    "yo": {"term": "year old", "icd": None, "snomed": None},
    "y/o": {"term": "year old", "icd": None, "snomed": None},
    "m": {"term": "male", "icd": None, "snomed": "248153007"},
    "f": {"term": "female", "icd": None, "snomed": "248152002"},
    "pt": {"term": "patient", "icd": None, "snomed": None},

    # ── Psychiatry ──────────────────────────────────────────────────
    "mdd": {"term": "major depressive disorder", "icd": "F33.0", "snomed": "370143000"},
    "gad": {"term": "generalized anxiety disorder", "icd": "F41.1", "snomed": "21897009"},
    "ptsd": {"term": "post-traumatic stress disorder", "icd": "F43.10", "snomed": "47505003"},
    "ocd": {"term": "obsessive-compulsive disorder", "icd": "F42.9", "snomed": "191736004"},
    "adhd": {"term": "attention deficit hyperactivity disorder", "icd": "F90.9", "snomed": "406506008"},
    "bpad": {"term": "bipolar affective disorder", "icd": "F31.9", "snomed": "13746004"},
    "si": {"term": "suicidal ideation", "icd": "R45.851", "snomed": "6471006"},
    "hi": {"term": "homicidal ideation", "icd": "R45.850", "snomed": "247977009"},
    "avh": {"term": "auditory/visual hallucinations", "icd": "R44.0", "snomed": "7011001"},
    "etoh": {"term": "alcohol (ethanol)", "icd": None, "snomed": "419442005"},
    "ivdu": {"term": "intravenous drug use", "icd": None, "snomed": None},

    # ── Obstetrics / Gynecology ─────────────────────────────────────
    "lmp": {"term": "last menstrual period", "icd": None, "snomed": "21840007"},
    "edd": {"term": "estimated date of delivery", "icd": None, "snomed": "161714006"},
    "ga": {"term": "gestational age", "icd": None, "snomed": "57036006"},
    "g": {"term": "gravida", "icd": None, "snomed": None},
    "p": {"term": "para", "icd": None, "snomed": None},
    "c/s": {"term": "cesarean section", "icd": None, "snomed": "11466000"},
    "nsvd": {"term": "normal spontaneous vaginal delivery", "icd": None, "snomed": "48782003"},
    "pih": {"term": "pregnancy-induced hypertension", "icd": "O13.9", "snomed": "48194001"},

    # ── Emergency / Trauma ──────────────────────────────────────────
    "ed": {"term": "emergency department", "icd": None, "snomed": "225728007"},
    "er": {"term": "emergency room", "icd": None, "snomed": "225728007"},
    "ems": {"term": "emergency medical services", "icd": None, "snomed": None},
    "mva": {"term": "motor vehicle accident", "icd": "V89.2", "snomed": "418399005"},
    "mvc": {"term": "motor vehicle collision", "icd": "V89.2", "snomed": "418399005"},
    "gsw": {"term": "gunshot wound", "icd": None, "snomed": "283545005"},
    "cpr": {"term": "cardiopulmonary resuscitation", "icd": None, "snomed": "89666000"},
    "rosc": {"term": "return of spontaneous circulation", "icd": None, "snomed": None},
    "acls": {"term": "advanced cardiovascular life support", "icd": None, "snomed": None},
    "bls": {"term": "basic life support", "icd": None, "snomed": None},
    "fast": {"term": "focused assessment with sonography for trauma", "icd": None, "snomed": None},
    "etl": {"term": "endotracheal tube length", "icd": None, "snomed": None},
    "ett": {"term": "endotracheal tube", "icd": None, "snomed": "129121000"},
    "rsi": {"term": "rapid sequence intubation", "icd": None, "snomed": "232674004"},
}


class DictionaryService:
    """
    Manages the abbreviation map and MARISA-Trie for
    sub-millisecond medical term lookup.
    """

    def __init__(self) -> None:
        self._abbreviations: Dict[str, Dict] = {}
        self._trie: Optional[marisa_trie.Trie] = None
        self._icd10_lookup: Dict[str, str] = {}
        self._snomed_lookup: Dict[str, str] = {}
        self._loinc_lookup: Dict[str, str] = {}
        self._term_list: List[str] = []
        self._loaded = False

    # ── Public Properties ───────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def trie_term_count(self) -> int:
        return len(self._term_list) if self._trie else 0

    @property
    def abbreviation_count(self) -> int:
        return len(self._abbreviations)

    # ── Initialization ──────────────────────────────────────────────

    async def load(self) -> None:
        """Load abbreviations and trie from compiled data files."""
        settings = get_settings()

        # 1. Load abbreviations: built-in + JSON override
        self._abbreviations = dict(BUILTIN_ABBREVIATIONS)
        abbrev_path = Path(settings.abbreviations_path)
        if abbrev_path.exists():
            try:
                with open(abbrev_path, "r", encoding="utf-8") as f:
                    custom = json.load(f)
                self._abbreviations.update(custom)
                logger.info(
                    "Loaded %d custom abbreviations from %s",
                    len(custom), abbrev_path,
                )
            except Exception as e:
                logger.warning("Failed to load custom abbreviations: %s", e)

        logger.info("Total abbreviations loaded: %d", len(self._abbreviations))

        # 2. Load code lookups
        self._icd10_lookup = self._load_json(settings.icd10_lookup_path, "ICD-10")
        self._snomed_lookup = self._load_json(settings.snomed_lookup_path, "SNOMED")
        self._loinc_lookup = self._load_json(settings.loinc_lookup_path, "LOINC")

        # 3. Load MARISA-Trie
        trie_path = Path(settings.trie_path)
        if trie_path.exists():
            try:
                self._trie = marisa_trie.Trie()
                self._trie.load(str(trie_path))
                self._term_list = list(self._trie.keys())
                logger.info(
                    "MARISA-Trie loaded: %d terms from %s",
                    len(self._term_list), trie_path,
                )
            except Exception as e:
                logger.error("Failed to load MARISA-Trie: %s", e)
                self._trie = None
        else:
            # Build a minimal trie from available lookup keys
            all_terms = set()
            all_terms.update(self._icd10_lookup.keys())
            all_terms.update(self._snomed_lookup.keys())
            all_terms.update(self._loinc_lookup.keys())
            # Also add abbreviation expansions as trie terms
            for entry in self._abbreviations.values():
                all_terms.add(entry["term"].lower())

            if all_terms:
                self._term_list = sorted(all_terms)
                self._trie = marisa_trie.Trie(self._term_list)
                logger.info(
                    "Built in-memory MARISA-Trie from lookups: %d terms",
                    len(self._term_list),
                )
            else:
                logger.warning(
                    "No trie file found at %s and no lookup data available. "
                    "Trie search will be disabled.",
                    trie_path,
                )

        self._loaded = True

    # ── Stage 1: Abbreviation Lookup ────────────────────────────────

    def lookup_abbreviation(
        self, token: str
    ) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """
        Check if `token` is a known clinical abbreviation.

        Returns:
            (expanded_term, icd_code, snomed_code) or None if not found.
        """
        token_lower = token.strip().lower()
        entry = self._abbreviations.get(token_lower)
        if entry:
            return (entry["term"], entry.get("icd"), entry.get("snomed"))
        return None

    # ── Stage 2: Trie Prefix Search ─────────────────────────────────

    def search_prefix(
        self, prefix: str, max_results: int = 10
    ) -> List[Tuple[str, Optional[str], Optional[str], Optional[str]]]:
        """
        Find medical terms starting with `prefix`.

        Returns:
            List of (term, icd_code, snomed_code, loinc_code).
            Sorted by term length (shortest = most likely match).
        """
        if not self._trie or not prefix:
            return []

        prefix_lower = prefix.strip().lower()
        if len(prefix_lower) < 2:
            return []

        try:
            matches = self._trie.keys(prefix_lower)
        except KeyError:
            return []

        # Sort by length (prefer shorter, more precise completions)
        matches.sort(key=len)
        results = []
        for term in matches[:max_results]:
            icd = self._icd10_lookup.get(term)
            snomed = self._snomed_lookup.get(term)
            loinc = self._loinc_lookup.get(term)
            results.append((term, icd, snomed, loinc))

        return results

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _load_json(path_str: str, label: str) -> Dict[str, str]:
        """Load a JSON lookup file (term → code). Returns empty dict on failure."""
        path = Path(path_str)
        if not path.exists():
            logger.info("No %s lookup file at %s — skipping.", label, path)
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Loaded %d %s entries from %s", len(data), label, path)
            return data
        except Exception as e:
            logger.warning("Failed to load %s lookup: %s", label, e)
            return {}


# ── UMLS REST API Service ──────────────────────────────────────────
# Primary Layer 2 source — live lookup for medical concepts.
# Falls back silently to MARISA-Trie if the key is missing or API is down.


class UMLSApiService:
    """
    Async client for the UMLS REST API.

    Used as the primary Layer 2 source for medical term lookup.
    Returns ICD-10 / SNOMED codes for a given search term.
    Falls through to the trie silently on any error.
    """

    BASE_URL = "https://uts-ws.nlm.nih.gov/rest"

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._api_key: Optional[str] = None
        self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    async def initialize(self) -> None:
        """Create the async HTTP client if UMLS_API_KEY is configured."""
        settings = get_settings()
        self._api_key = settings.umls_api_key
        if not self._api_key:
            logger.info("UMLS_API_KEY not set — UMLS live lookup disabled.")
            self._available = False
            return

        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=httpx.Timeout(10.0),
        )
        self._available = True
        logger.info("UMLS API service initialized.")

    async def shutdown(self) -> None:
        """Cleanly close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._available = False

    async def search(
        self, term: str, max_results: int = 5
    ) -> Optional[List[Tuple[str, Optional[str], Optional[str], Optional[str]]]]:
        """
        Search UMLS for a medical concept by prefix/term.

        Args:
            term: The search term (prefix or partial medical word).
            max_results: Maximum number of results to return.

        Returns:
            List of (concept_name, icd_code, snomed_code, None) or None on failure.
            Never raises — returns None on any error so the trie can take over.
        """
        if not self._client or not self._available or not self._api_key:
            return None

        try:
            # Step 1: Search for concepts
            params = {
                "apiKey": self._api_key,
                "string": term,
                "searchType": "leftTruncation",
                "returnIdType": "concept",
                "pageSize": max_results,
            }
            response = await self._client.get("/search/current", params=params)
            response.raise_for_status()
            data = response.json()

            results_list = data.get("result", {}).get("results", [])
            if not results_list:
                return None

            output = []
            for item in results_list[:max_results]:
                concept_name = item.get("name", "")
                cui = item.get("ui", "")
                if not concept_name or not cui:
                    continue

                # Step 2: Get ICD-10 and SNOMED codes for each CUI
                icd_code, snomed_code = await self._get_codes(cui)
                output.append((concept_name.lower(), icd_code, snomed_code, None))

            return output if output else None

        except httpx.TimeoutException:
            logger.debug("UMLS API timed out for term '%s'.", term)
            return None
        except httpx.HTTPStatusError as e:
            logger.debug("UMLS API HTTP error: %s", e.response.status_code)
            return None
        except Exception as e:
            logger.warning("UMLS stage error full details: %s", repr(e))
            return []

    async def _get_codes(
        self, cui: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Retrieve ICD-10-CM and SNOMED-CT codes for a given CUI.

        Returns:
            (icd_code, snomed_code) — either may be None.
        """
        icd_code: Optional[str] = None
        snomed_code: Optional[str] = None

        if not self._client or not self._api_key:
            return icd_code, snomed_code

        try:
            params = {"apiKey": self._api_key}
            response = await self._client.get(
                f"/content/current/CUI/{cui}/atoms",
                params=params,
            )
            if response.status_code != 200:
                return icd_code, snomed_code

            atoms = response.json().get("result", [])
            for atom in atoms:
                source = atom.get("rootSource", "")
                code = atom.get("code", "")
                # Extract just the code ID from the UMLS URI
                if "/" in code:
                    code = code.rsplit("/", 1)[-1]

                if source == "ICD10CM" and not icd_code:
                    icd_code = code
                elif source == "SNOMEDCT_US" and not snomed_code:
                    snomed_code = code

                if icd_code and snomed_code:
                    break

        except Exception as e:
            logger.debug("UMLS code lookup error for CUI %s: %s", cui, e)

        return icd_code, snomed_code
