/**
 * Clinical Note Editor — Lexical editor with ghost text autocomplete.
 *
 * Features:
 * - Rich text editing via Lexical
 * - Ghost text overlay (Tab to accept, Esc to dismiss)
 * - Real-time autocomplete via the backend waterfall pipeline
 * - Source badge + ICD code display
 */

import { useEffect, useRef } from "react";
import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { PlainTextPlugin } from "@lexical/react/LexicalPlainTextPlugin";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  $getRoot,
  $getSelection,
  $isRangeSelection,
  KEY_TAB_COMMAND,
  KEY_ESCAPE_COMMAND,
  COMMAND_PRIORITY_HIGH,
} from "lexical";
import { useAutocomplete } from "../hooks/useAutocomplete";
import type { AutocompleteResponse } from "../services/api";

// ── Lexical Config ─────────────────────────────────────────────────

const editorConfig = {
  namespace: "ClinicalCopilot",
  onError: (error: Error) => console.error("Lexical error:", error),
  nodes: [],
};

// ── Source Badge Colors ────────────────────────────────────────────

const SOURCE_STYLES: Record<string, { bg: string; label: string }> = {
  abbreviation: { bg: "bg-emerald-100 text-emerald-800", label: "Abbreviation" },
  trie: { bg: "bg-blue-100 text-blue-800", label: "Medical Term" },
  lab_engine: { bg: "bg-amber-100 text-amber-800", label: "Lab Warning" },
  llm: { bg: "bg-purple-100 text-purple-800", label: "AI Suggestion" },
};

// ── Ghost Text + Autocomplete Plugin ───────────────────────────────

function AutocompletePlugin({
  suggestion,
  onRequestSuggestion,
  onClearSuggestion,
  onAcceptSuggestion,
}: {
  suggestion: AutocompleteResponse | null;
  onRequestSuggestion: (text: string, cursorPos: number) => void;
  onClearSuggestion: () => void;
  onAcceptSuggestion: () => string | null;
}) {
  const [editor] = useLexicalComposerContext();

  // Tab to accept suggestion
  useEffect(() => {
    return editor.registerCommand(
      KEY_TAB_COMMAND,
      (event: KeyboardEvent) => {
        if (!suggestion?.suggestion) return false;

        event.preventDefault();
        const accepted = onAcceptSuggestion();
        if (!accepted) return false;

        editor.update(() => {
          const selection = $getSelection();
          if ($isRangeSelection(selection)) {
            selection.insertText(accepted);
          }
        });

        return true;
      },
      COMMAND_PRIORITY_HIGH
    );
  }, [editor, suggestion, onAcceptSuggestion]);

  // Escape to dismiss suggestion
  useEffect(() => {
    return editor.registerCommand(
      KEY_ESCAPE_COMMAND,
      () => {
        if (!suggestion) return false;
        onClearSuggestion();
        return true;
      },
      COMMAND_PRIORITY_HIGH
    );
  }, [editor, suggestion, onClearSuggestion]);

  // On text change → request autocomplete
  useEffect(() => {
    return editor.registerUpdateListener(({ editorState }) => {
      editorState.read(() => {
        const root = $getRoot();
        const text = root.getTextContent();
        const selection = $getSelection();

        if ($isRangeSelection(selection)) {
          const anchor = selection.anchor;
          // Calculate cursor position as offset within full text
          let cursorPos = 0;
          const children = root.getAllTextNodes();
          for (const node of children) {
            if (node.getKey() === anchor.key) {
              cursorPos += anchor.offset;
              break;
            }
            cursorPos += node.getTextContentSize();
          }

          if (text.trim().length > 0) {
            onRequestSuggestion(text, cursorPos);
          } else {
            onClearSuggestion();
          }
        }
      });
    });
  }, [editor, onRequestSuggestion, onClearSuggestion]);

  return null;
}

// ── Ghost Text Overlay ─────────────────────────────────────────────

function GhostTextOverlay({
  suggestion,
  editorRef,
}: {
  suggestion: AutocompleteResponse | null;
  editorRef: React.RefObject<HTMLDivElement | null>;
}) {
  if (!suggestion?.suggestion || !editorRef.current) return null;

  const isLabWarning = suggestion.source === "lab_engine";

  return (
    <div className="pointer-events-none absolute bottom-full left-0 mb-2 w-full">
      <div
        className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 shadow-lg border ${
          isLabWarning
            ? "bg-amber-50 border-amber-200"
            : "bg-white border-gray-200"
        }`}
      >
        {/* Ghost text */}
        <span
          className={`font-mono text-sm ${
            isLabWarning ? "text-amber-700 font-medium" : "text-gray-400"
          }`}
        >
          {suggestion.suggestion}
        </span>

        {/* Source badge */}
        {suggestion.source && (
          <span
            className={`ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
              SOURCE_STYLES[suggestion.source]?.bg ?? "bg-gray-100 text-gray-600"
            }`}
          >
            {SOURCE_STYLES[suggestion.source]?.label ?? suggestion.source}
          </span>
        )}

        {/* ICD code */}
        {suggestion.icd_code && (
          <span className="ml-1 inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-mono text-gray-500">
            ICD: {suggestion.icd_code}
          </span>
        )}

        {/* Accept hint */}
        {!isLabWarning && (
          <span className="ml-2 text-xs text-gray-300">
            Tab ↹
          </span>
        )}
      </div>
    </div>
  );
}

// ── Status Bar ─────────────────────────────────────────────────────

function StatusBar({
  suggestion,
  loading,
}: {
  suggestion: AutocompleteResponse | null;
  loading: boolean;
}) {
  return (
    <div className="flex items-center justify-between border-t border-gray-200 bg-gray-50 px-4 py-2 text-xs text-gray-500">
      <div className="flex items-center gap-3">
        {loading && (
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
            Thinking...
          </span>
        )}
        {suggestion?.source && !loading && (
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Suggestion ready
            {suggestion.confidence != null && (
              <span className="text-gray-400">
                ({Math.round(suggestion.confidence * 100)}%)
              </span>
            )}
          </span>
        )}
        {!suggestion && !loading && (
          <span className="text-gray-400">Start typing a clinical note...</span>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span>
          <kbd className="rounded border border-gray-300 bg-white px-1.5 py-0.5 font-mono text-[10px]">
            Tab
          </kbd>{" "}
          accept
        </span>
        <span>
          <kbd className="rounded border border-gray-300 bg-white px-1.5 py-0.5 font-mono text-[10px]">
            Esc
          </kbd>{" "}
          dismiss
        </span>
      </div>
    </div>
  );
}

// ── Main Editor Component ──────────────────────────────────────────

export default function ClinicalEditor() {
  const editorRef = useRef<HTMLDivElement | null>(null);
  const {
    suggestion,
    loading,
    requestSuggestion,
    clearSuggestion,
    acceptSuggestion,
  } = useAutocomplete({ debounceMs: 150 });

  return (
    <div className="mx-auto w-full max-w-4xl">
      <LexicalComposer initialConfig={editorConfig}>
        <div className="relative overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-gray-200 bg-gray-50 px-4 py-3">
            <div className="flex items-center gap-2">
              <div className="h-3 w-3 rounded-full bg-emerald-400" />
              <h2 className="text-sm font-semibold text-gray-700">
                Clinical Note Editor
              </h2>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="h-2.5 w-2.5 rounded-full bg-red-400" />
              <div className="h-2.5 w-2.5 rounded-full bg-yellow-400" />
              <div className="h-2.5 w-2.5 rounded-full bg-green-400" />
            </div>
          </div>

          {/* Editor area with ghost text */}
          <div className="relative" ref={editorRef}>
            {/* Ghost text overlay */}
            <div className="relative">
              <GhostTextOverlay
                suggestion={suggestion}
                editorRef={editorRef}
              />
            </div>

            <PlainTextPlugin
              contentEditable={
                <ContentEditable className="min-h-[400px] px-6 py-4 font-mono text-sm leading-relaxed text-gray-800 outline-none" />
              }
              placeholder={
                <div className="pointer-events-none absolute left-6 top-4 font-mono text-sm text-gray-300">
                  Begin typing your clinical note here...
                  {"\n\n"}
                  Try: "patient has htn" or "Glucose: 35" or "patient has diab"
                </div>
              }
              ErrorBoundary={LexicalErrorBoundary}
            />

            <HistoryPlugin />
            <OnChangePlugin onChange={() => {}} />
            <AutocompletePlugin
              suggestion={suggestion}
              onRequestSuggestion={requestSuggestion}
              onClearSuggestion={clearSuggestion}
              onAcceptSuggestion={acceptSuggestion}
            />
          </div>

          {/* Status bar */}
          <StatusBar suggestion={suggestion} loading={loading} />
        </div>
      </LexicalComposer>
    </div>
  );
}
