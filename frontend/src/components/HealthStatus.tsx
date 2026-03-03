/**
 * HealthStatus — Displays backend health info in a compact card.
 */

import { useEffect, useState } from "react";
import { fetchHealth, type HealthResponse } from "../services/api";

export default function HealthStatus() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      const result = await fetchHealth();
      if (!cancelled) {
        setHealth(result);
        setError(result === null);
      }
    }

    check();
    const interval = setInterval(check, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
        <span className="h-2 w-2 rounded-full bg-red-500" />
        Backend unreachable
      </div>
    );
  }

  if (!health) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-400">
        <span className="h-2 w-2 animate-pulse rounded-full bg-gray-400" />
        Connecting...
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-200 bg-white px-4 py-2 text-xs text-gray-600 shadow-sm">
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-emerald-500" />
        <span className="font-medium text-emerald-700">Healthy</span>
      </span>
      <span className="text-gray-300">|</span>
      <span>
        <span className="font-medium">{health.abbreviation_count.toLocaleString()}</span> abbreviations
      </span>
      <span>
        <span className="font-medium">{health.trie_term_count.toLocaleString()}</span> trie terms
      </span>
      <span>
        <span className="font-medium">{health.lab_ranges_count}</span> lab ranges
      </span>
      <span className="flex items-center gap-1">
        Ollama:
        <span
          className={`h-2 w-2 rounded-full ${
            health.ollama_available ? "bg-emerald-500" : "bg-gray-300"
          }`}
        />
        {health.ollama_available ? "Online" : "Offline"}
      </span>
      <span className="flex items-center gap-1">
        UMLS:
        <span
          className={`h-2 w-2 rounded-full ${
            health.umls_available ? "bg-emerald-500" : "bg-gray-300"
          }`}
        />
        {health.umls_available ? "Active" : "Inactive"}
      </span>
      <span className="text-gray-300">|</span>
      <span className="text-gray-400">v{health.version}</span>
    </div>
  );
}
