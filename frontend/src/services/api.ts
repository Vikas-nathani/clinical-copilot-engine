/**
 * API Service — Fetch wrapper for the Clinical Copilot Engine backend.
 *
 * In dev mode, Vite proxies /autocomplete and /health to localhost:8000.
 * In production, VITE_API_BASE_URL points to the backend service.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export interface AutocompleteRequest {
  text: string;
  cursor_position: number;
  context_window?: number;
  specialty?: string;
}

export interface AutocompleteResponse {
  suggestion: string | null;
  source: "abbreviation" | "trie" | "umls" | "lab_engine" | "llm" | null;
  icd_code: string | null;
  snomed_code: string | null;
  loinc_code: string | null;
  confidence: number;
  lab_flag: string | null;
  specialty: string | null;
  message?: string;
}

export interface HealthResponse {
  status: string;
  trie_loaded: boolean;
  trie_term_count: number;
  abbreviation_count: number;
  lab_ranges_count: number;
  ollama_available: boolean;
  umls_available: boolean;
  version: string;
}

/**
 * Request an autocomplete suggestion from the backend.
 * Returns null on network error or empty response.
 */
export async function fetchAutocomplete(
  request: AutocompleteRequest,
  signal?: AbortSignal
): Promise<AutocompleteResponse | null> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/suggest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    });

    if (!response.ok) return null;

    const data: AutocompleteResponse = await response.json();
    return data.suggestion ? data : null;
  } catch {
    return null;
  }
}

/**
 * Fetch backend health status.
 */
export async function fetchHealth(): Promise<HealthResponse | null> {
  try {
    const response = await fetch(`${API_BASE}/health`);
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}
