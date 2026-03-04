/**
 * useAutocomplete — Debounced autocomplete hook.
 *
 * Sends requests to POST /autocomplete after a configurable debounce delay.
 * Automatically cancels in-flight requests when the user keeps typing.
 */

import { useCallback, useRef, useState } from "react";
import {
  fetchAutocomplete,
  type AutocompleteResponse,
} from "../services/api";

const DEFAULT_DEBOUNCE_MS = 300;
const MIN_PREFIX_LENGTH = 2;

interface UseAutocompleteOptions {
  debounceMs?: number;
  minPrefixLength?: number;
}

interface UseAutocompleteReturn {
  suggestion: AutocompleteResponse | null;
  loading: boolean;
  requestSuggestion: (text: string, cursorPosition: number) => void;
  clearSuggestion: () => void;
  acceptSuggestion: () => string | null;
}

export function useAutocomplete(
  options: UseAutocompleteOptions = {}
): UseAutocompleteReturn {
  const {
    debounceMs = DEFAULT_DEBOUNCE_MS,
    minPrefixLength = MIN_PREFIX_LENGTH,
  } = options;

  const [suggestion, setSuggestion] = useState<AutocompleteResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const clearSuggestion = useCallback(() => {
    setSuggestion(null);
  }, []);

  const requestSuggestion = useCallback(
    (text: string, cursorPosition: number) => {
      // Clear previous timer
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }

      // Cancel in-flight request
      if (abortRef.current) {
        abortRef.current.abort();
      }

      // Don't request for very short input
      const textUpToCursor = text.slice(0, cursorPosition);
      const lastWord = textUpToCursor.split(/[\s,;]+/).pop() ?? "";
      if (lastWord.length < minPrefixLength && !textUpToCursor.includes(":")) {
        setSuggestion(null);
        return;
      }

      // Debounce
      timerRef.current = setTimeout(async () => {
        const controller = new AbortController();
        abortRef.current = controller;
        setLoading(true);
        


        console.log('cursor:', cursorPosition, 'textLen:', text.length);
        const result = await fetchAutocomplete(
          { text, cursor_position: cursorPosition },
          controller.signal
        );


        // Only update if this request wasn't aborted
        if (!controller.signal.aborted) {
          setSuggestion(result);
          setLoading(false);
        }
      }, debounceMs);
    },
    [debounceMs, minPrefixLength]
  );

  const acceptSuggestion = useCallback((): string | null => {
    if (!suggestion?.suggestion) return null;
    const accepted = suggestion.suggestion;
    setSuggestion(null);
    return accepted;
  }, [suggestion]);

  return {
    suggestion,
    loading,
    requestSuggestion,
    clearSuggestion,
    acceptSuggestion,
  };
}
