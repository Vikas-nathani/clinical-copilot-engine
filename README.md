# Clinical Copilot Engine

> Real-time autocomplete for clinical note-writing — medical terms, ICD-10 codes, and AI-powered sentence completion. Like Gmail's Smart Compose, but for medicine.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![React 18](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://reactjs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Waterfall Autocomplete Logic](#waterfall-autocomplete-logic)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Data Pipeline](#data-pipeline)
- [API Contract](#api-contract)
- [Getting Started](#getting-started)
- [Deployment](#deployment)
- [Configuration](#configuration)
- [Security & Compliance](#security--compliance)
- [Roadmap](#roadmap)

---

## Overview

**Clinical Copilot Engine** is a production-grade autocomplete system designed for doctors writing clinical notes. As a clinician types, the system suggests:

- **Medical terms** via UMLS REST API live lookup (primary) and instant trie-based prefix matching (fallback)
- **ICD-10 codes** mapped to recognized medical concepts
- **Abnormal lab value warnings** via rule-based pattern detection
- **Full sentence completions** via BioMistral-7B on Ollama (CPU-friendly Q4 quant) as a fallback

The system prioritizes **speed** (trie lookups < 1ms) and **accuracy** (clinically validated dictionaries + UMLS live lookup), falling back to AI generation only when deterministic methods cannot provide a suggestion.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React + Vite)                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              Lexical Editor (Rich Text + Ghost Text)          │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │  │
│  │  │ Keystroke    │→ │ Debounce     │→ │POST /api/v1/suggest│  │  │
│  │  │ Listener     │  │ (300ms)      │  │ (Async Fetch)      │  │  │
│  │  └─────────────┘  └──────────────┘  └────────┬───────────┘  │  │
│  │                                               │              │  │
│  │  ┌────────────────────────────────────────────▼───────────┐  │  │
│  │  │  Ghost Text Overlay (Tab to accept / Esc to dismiss)   │  │  │
│  │  └────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ HTTP/JSON
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     BACKEND (FastAPI - Async)                       │
│                                                                     │
│  ┌──────────────┐    ┌──────────────────────────────────────────┐  │
│  │  POST        │    │          ORCHESTRATOR SERVICE             │  │
│  │ /api/v1/     │──→ │  (Waterfall Logic - Sequential Stages)   │  │
│  │  suggest     │    │                                          │  │
│  └──────────────┘    │  Stage 1: Abbreviation Map Lookup        │  │
│                      │      │ miss                              │  │
│                      │      ▼                                   │  │
│                      │  Stage 2a: UMLS REST API (primary)       │  │
│                      │      │ miss / error                      │  │
│                      │      ▼                                   │  │
│                      │  Stage 2b: MARISA-Trie (fallback)        │  │
│                      │      │ miss                              │  │
│                      │      ▼                                   │  │
│                      │  Stage 3: Lab Pattern Engine              │  │
│                      │      │ miss                              │  │
│                      │      ▼                                   │  │
│                      │  Stage 4: BioMistral-7B (Ollama)         │  │
│                      └──────────────────────────────────────────┘  │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                      SERVICE LAYER                             │ │
│  │  ┌──────────────┐ ┌────────────┐ ┌──────────┐ ┌───────────┐  │ │
│  │  │ dictionary.py│ │lab_engine  │ │llm_client│ │orchestrator│  │ │
│  │  │              │ │.py         │ │.py       │ │.py         │  │ │
│  │  │• Abbrev Map  │ │• Regex     │ │• Ollama  │ │• Waterfall │  │ │
│  │  │• UMLS API    │ │  Patterns  │ │  Client  │ │  Control   │  │ │
│  │  │• MARISA-Trie │ │• Normal    │ │• Async   │ │• Response  │  │ │
│  │  │• ICD-10 Map  │ │  Ranges    │ │  HTTP    │ │  Assembly  │  │ │
│  │  └──────────────┘ └────────────┘ └──────────┘ └───────────┘  │ │
│  └────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
┌──────────────────┐  ┌─────────────────┐  ┌─────────────────────┐
│   Data Layer     │  │  Ollama Server  │  │   External APIs     │
│                  │  │                 │  │                     │
│ • MARISA-Trie    │  │ • BioMistral-7B │  │ • UMLS REST API     │
│   (compiled)     │  │   (Q4 quant)   │  │   (live lookup)     │
│ • ICD-10 JSON    │  │ • CPU-friendly  │  │ • RxNorm            │
│ • SNOMED JSON    │  │ • /api/chat     │  │ • NLM Services      │
│ • LOINC JSON     │  │                 │  │                     │
│ • Abbrev JSON    │  │                 │  │                     │
└──────────────────┘  └─────────────────┘  └─────────────────────┘
```

---

## Waterfall Autocomplete Logic

The orchestrator executes these stages **in strict sequential order**, returning the first successful match:

| Stage | Source | Latency | Description |
|-------|--------|---------|-------------|
| **1** | Abbreviation Map | < 0.1ms | Static dictionary lookup. Maps common clinical abbreviations to full terms (e.g., `htn` → `hypertension`, `dm2` → `diabetes mellitus type 2`). |
| **2a** | UMLS REST API | 50–200ms | Live lookup against the UMLS Metathesaurus for medical concepts, returning ICD-10 and SNOMED codes. Falls through silently to the trie if the API key is missing or the service is down. |
| **2b** | MARISA-Trie | < 1ms | Fallback prefix search against a compiled trie of ~500K+ medical terms from ICD-10, SNOMED-CT, and LOINC. Returns the best match + ICD-10/SNOMED code if available. |
| **3** | Lab Pattern Engine | < 1ms | Regex-based detection of lab value patterns (e.g., `Glucose: 35`). Flags abnormal values against a clinically validated reference range table and returns a warning annotation. |
| **4** | BioMistral-7B | 500–5000ms | AI-powered sentence completion via Ollama (CPU-friendly Q4 quant). Only invoked when all deterministic stages fail. Returns contextual completions grounded in medical knowledge. |

**Why this order?**
- Deterministic lookups first → fastest, most reliable, no hallucination risk
- AI last → expensive, slower, but handles open-ended completion

---

## Tech Stack

### Frontend
| Technology | Purpose |
|-----------|---------|
| **React 18** | UI framework |
| **Vite** | Build tool & dev server |
| **Lexical** | Rich text editor (Meta's framework) — supports ghost text plugins |
| **TailwindCSS** | Utility-first styling |
| **TypeScript** | Type safety |

### Backend
| Technology | Purpose |
|-----------|---------|
| **FastAPI** | Async Python web framework |
| **Uvicorn** | ASGI server |
| **MARISA-Trie** | Memory-efficient, blazing-fast prefix trie (C++ backed) |
| **Pydantic v2** | Request/response validation |
| **httpx** | Async HTTP client (for Ollama + UMLS API calls) |

### AI & Data
| Technology | Purpose |
|-----------|--------|
| **BioMistral-7B** | Medical LLM (fine-tuned Mistral for biomedical text) |
| **Ollama** | Lightweight local LLM server — CPU-friendly inference |
| **Q4 Quantization** | 4-bit quantization for reduced memory (~4.4 GB download) |
| **UMLS REST API** | Live medical concept lookup with ICD-10 / SNOMED codes |

### Data Standards
| Standard | Description | Source |
|----------|-------------|--------|
| **ICD-10-CM** | Diagnosis codes (~70K codes) | CMS.gov public download |
| **SNOMED-CT** | Clinical terminology (~350K concepts) | UMLS (requires license) |
| **LOINC** | Lab/observation codes (~100K) | loinc.org (free registration) |

### Infrastructure
| Technology | Purpose |
|-----------|---------|
| **Docker** | Containerization |
| **Docker Compose** | Multi-service orchestration (frontend, backend, Ollama) |
| **Nginx** | Reverse proxy (production) |

---

## Project Structure

```
clinical-copilot-engine/
├── README.md                          # This file
├── docker-compose.yml                 # Multi-service orchestration
├── .env.example                       # Environment variable template
├── .gitignore
│
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app entry point
│   │   ├── api/
│   │   │   └── autocomplete.py        # POST /api/v1/suggest + SSE stream route
│   │   ├── core/
│   │   │   ├── config.py              # Settings via Pydantic BaseSettings
│   │   │   └── middleware.py           # CORS, rate limiting, logging
│   │   ├── schemas/
│   │   │   └── models.py              # Request/Response Pydantic models
│   │   └── services/
│   │       ├── dictionary.py           # Abbreviation map + MARISA-Trie + UMLS API
│   │       ├── lab_engine.py           # Lab pattern detection + ranges
│   │       ├── llm_client.py           # Async Ollama/BioMistral client
│   │       └── orchestrator.py         # Waterfall logic controller
│   ├── scripts/
│   │   ├── Dockerfile                  # Backend container
│   │   └── download_data.py           # Download ICD-10, LOINC + UMLS extract
│   ├── tests/
│   │   ├── test_autocomplete.py       # API endpoint tests
│   │   ├── test_dictionary.py         # Trie + abbreviation tests
│   │   ├── test_lab_engine.py         # Lab pattern tests
│   │   └── test_orchestrator.py       # Waterfall integration tests
│   └── requirements.txt               # Python dependencies
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx                     # Root component
│   │   ├── main.tsx                    # Vite entry point
│   │   ├── components/
│   │   │   └── Editor.tsx              # Lexical editor + ghost text plugin
│   │   ├── hooks/
│   │   │   └── useAutocomplete.ts     # Debounced autocomplete hook
│   │   └── services/
│   │       └── api.ts                  # Fetch wrapper for /api/v1/suggest
│   ├── index.html
│   ├── package.json
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── vite.config.ts
│
└── data/
    ├── raw/                            # Downloaded source files
    │   ├── icd10cm_codes.csv          # From CMS.gov
    │   ├── loinc_table.csv            # From loinc.org
    │   └── snomed_descriptions.txt    # From UMLS (SNOMED-CT RF2)
    └── compiled/                       # Processed, ready-to-load files
        ├── medical_trie.marisa        # Compiled MARISA-Trie binary
        ├── abbreviations.json         # Clinical abbreviation map
        ├── icd10_lookup.json          # Term → ICD-10 code mapping
        ├── snomed_lookup.json         # Term → SNOMED-CT code mapping
        ├── loinc_lookup.json          # Term → LOINC code mapping
        └── lab_ranges.json            # Lab test normal ranges
```

---

## Data Pipeline

### Sources & Download Strategy

The `backend/scripts/download_data.py` script handles data acquisition:

| Dataset | Source | Access | Method |
|---------|--------|--------|--------|
| **ICD-10-CM** | [CMS.gov](https://www.cms.gov/medicare/coding-billing/icd-10-codes) | Public, no login | Direct HTTP download |
| **LOINC** | [loinc.org](https://loinc.org/downloads/) | Free registration required | Manual download or API with credentials |
| **SNOMED-CT** | [UMLS](https://www.nlm.nih.gov/research/umls/) | UMLS license required | UMLS REST API or manual SNOMED-CT RF2 extract |

### UMLS Integration

Since you have UMLS access, the download script will support:
1. **UMLS API key authentication** — set `UMLS_API_KEY` in `.env`
2. **SNOMED-CT RF2 extraction** — parse `sct2_Description_Full` files
3. **Cross-mapping** — SNOMED → ICD-10 mappings from UMLS `MRCONSO.RRF`

### Compilation Pipeline

```
Raw CSVs/TSVs  →  download_data.py  →  Normalized JSON  →  MARISA-Trie binary
                                     →  ICD-10 lookup JSON
                                     →  SNOMED lookup JSON
                                     →  LOINC lookup JSON
                                     →  Abbreviation map JSON
                                     →  Lab ranges JSON
```

---

## API Contract

### `POST /api/v1/suggest`

**Request:**
```json
{
  "text": "patient has diab",
  "cursor_position": 16,
  "specialty": "endocrinology"
}
```

**Response (trie match):**
```json
{
  "suggestion": "etes mellitus type 2",
  "source": "trie",
  "icd_code": "E11.9",
  "snomed_code": "44054006",
  "confidence": 0.95
}
```

**Response (abbreviation match):**
```json
{
  "suggestion": "hypertension",
  "source": "abbreviation",
  "icd_code": "I10",
  "snomed_code": "38341003",
  "confidence": 1.0
}
```

**Response (lab warning):**
```json
{
  "suggestion": "⚠ Critical low — normal range: 70–100 mg/dL",
  "source": "lab_engine",
  "icd_code": null,
  "snomed_code": null,
  "confidence": 1.0,
  "lab_flag": "critical_low"
}
```

**Response (LLM fallback):**
```json
{
  "suggestion": "with a history of chronic obstructive pulmonary disease",
  "source": "llm",
  "icd_code": null,
  "snomed_code": null,
  "confidence": 0.72
}
```

### `GET /health`

Returns service health and loaded resource status.

```json
{
  "status": "healthy",
  "trie_loaded": true,
  "trie_term_count": 523847,
  "abbreviation_count": 1250,
  "lab_ranges_count": 85,
  "ollama_available": true,
  "umls_available": true
}
```

### `GET /api/v1/suggest/stream`

Streams Server-Sent Events with individual LLM tokens.

**Query params:** `text` (required), `context_window` (optional, default 200)

```
data: {"token": "with"}
data: {"token": " a"}
data: {"token": " history"}
data: [DONE]
```

---

## Getting Started

### Prerequisites

- **Python 3.11+**
- **Node.js 20+** and **pnpm** (or npm)
- **Docker** and **Docker Compose**
- **UMLS API Key** (for live Layer 2 lookup + SNOMED-CT download) — optional but recommended

> **No GPU required.** Ollama runs BioMistral-7B Q4 on CPU.

### 1. Clone & Configure

```bash
git clone https://github.com/your-org/clinical-copilot-engine.git
cd clinical-copilot-engine
cp .env.example .env
# Edit .env with your UMLS_API_KEY and other settings
```

### 2. Download & Compile Data

```bash
cd backend
pip install -r requirements.txt
python scripts/download_data.py --all
```

This will:
- Download ICD-10-CM from CMS.gov
- Download LOINC (requires credentials in `.env`)
- Extract SNOMED-CT from UMLS (requires `UMLS_API_KEY`)
- Compile the MARISA-Trie and all lookup JSONs into `data/compiled/`

### 3. Run Backend (Dev Mode)

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Run Frontend (Dev Mode)

```bash
cd frontend
pnpm install
pnpm dev
```

### 5. Run with Docker Compose (Full Stack)

```bash
docker compose up --build

# One-time: pull the BioMistral model (~4.4 GB)
./scripts/pull_model.sh
```

Services:
| Service | Port | Description |
|---------|------|-------------|
| `ollama` | 11434 | Ollama LLM server (BioMistral-7B Q4) |
| `backend` | 8000 | FastAPI server |
| `frontend` | 3000 | React + Nginx static build |

---

## Deployment

### Production Architecture (Recommended)

For real-world production deployment, the recommended setup is:

```
Internet → Nginx (TLS/SSL) → Frontend (Static build)
                            → /api/* → FastAPI (Uvicorn, 4 workers)
                                         → Ollama Server (BioMistral-7B)
                                         → UMLS REST API (external)
```

**Ollama as a separate Docker container** is the recommended approach because:
- **Isolation** — LLM workloads don't compete with CPU-bound trie lookups
- **Scaling** — scale API servers and LLM servers independently
- **Reliability** — LLM container can restart without affecting fast-path lookups
- **Flexibility** — swap models (BioMistral → Meditron, etc.) by changing one env var
- **No GPU required** — Q4 quantization runs efficiently on CPU

### Docker Compose Services

```yaml
services:
  ollama:         # Ollama + BioMistral-7B Q4 (CPU)
  frontend:       # Nginx serving static React build
  backend:        # FastAPI + Uvicorn (CPU)
```

---

## Configuration

All configuration via environment variables (`.env`):

| Variable | Description | Default |
|----------|-------------|---------|
| `UMLS_API_KEY` | UMLS REST API key for live Layer 2 lookup + data download | — |
| `LOINC_USERNAME` | LOINC download credentials | — |
| `LOINC_PASSWORD` | LOINC download credentials | — |
| `OLLAMA_URL` | Ollama server endpoint | `http://ollama:11434` |
| `OLLAMA_MODEL` | Model identifier | `cniongolo/biomistral` |
| `OLLAMA_TIMEOUT_SECONDS` | Request timeout for Ollama | `30.0` |
| `CORS_ORIGINS` | Allowed frontend origins | `http://localhost:3000` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `RATE_LIMIT_PER_MINUTE` | API rate limit per client | `300` |
| `MAX_SUGGESTION_LENGTH` | Max chars in LLM suggestion | `80` |

---

## Security & Compliance

This system is designed for use in clinical environments. Key considerations:

- **No PHI storage** — the engine is stateless; no patient data is persisted
- **On-premise deployment** — all components (including the LLM) run locally, no data leaves the network
- **No authentication required** — designed for internal/trusted network use; auth can be layered on later
- **Rate limiting** — configurable per-client rate limits to prevent abuse
- **CORS** — strict origin whitelisting
- **Input sanitization** — all inputs validated via Pydantic models
- **Audit logging** — structured logs for all autocomplete requests (configurable)
- **HIPAA alignment** — UMLS API calls transmit only search terms (no PHI); Ollama runs on-premise

> **Note:** This tool provides *suggestions only*. All clinical decisions remain with the treating physician. The system does not store, transmit, or process Protected Health Information (PHI) beyond the immediate autocomplete request.

---

## Roadmap

- [x] Project structure & architecture design
- [x] Backend: FastAPI app scaffold + health endpoint
- [x] Backend: Abbreviation map service (~1,250 clinical abbreviations)
- [x] Backend: MARISA-Trie dictionary service (ICD-10 + SNOMED + LOINC)
- [x] Backend: Lab pattern engine (85+ lab tests with clinical ranges)
- [x] Backend: Ollama / BioMistral client with async streaming
- [x] Backend: UMLS REST API service (live Layer 2 lookup)
- [x] Backend: Orchestrator (waterfall logic with UMLS → Trie fallback)
- [x] Backend: Data download & compilation script (CMS + UMLS + LOINC)
- [x] Backend: Rate limiting, CORS, structured logging middleware
- [x] Backend: Test suite (unit + integration)
- [x] Frontend: Lexical editor with ghost text plugin
- [x] Frontend: Debounced autocomplete hook (300ms)
- [x] Frontend: Polished clinical UI
- [x] Docker Compose: Full stack (frontend + backend + Ollama)
- [x] Production: Nginx config, multi-worker Uvicorn
- [x] SSE streaming endpoint (`/api/v1/suggest/stream`)
- [ ] Production: TLS termination
- [ ] Documentation: API docs (auto-generated via FastAPI /docs)