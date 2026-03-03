/**
 * App — Root component for Clinical Copilot Engine.
 */

import ClinicalEditor from "./components/Editor";
import HealthStatus from "./components/HealthStatus";

export default function App() {
  return (
    <div className="flex min-h-screen flex-col bg-gradient-to-b from-gray-50 to-gray-100">
      {/* Header */}
      <header className="border-b border-gray-200 bg-white shadow-sm">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-clinical-600 text-white font-bold text-sm">
              CC
            </div>
            <div>
              <h1 className="text-lg font-semibold text-gray-900">
                Clinical Copilot Engine
              </h1>
              <p className="text-xs text-gray-500">
                Real-time autocomplete for clinical note-writing
              </p>
            </div>
          </div>
          <HealthStatus />
        </div>
      </header>

      {/* Main Content */}
      <main className="flex flex-1 flex-col items-center px-6 py-10">
        <div className="mb-6 text-center">
          <p className="text-sm text-gray-500">
            Start typing a clinical note below. Suggestions appear automatically.
          </p>
          <p className="mt-1 text-xs text-gray-400">
            Press <kbd className="rounded border border-gray-300 bg-white px-1 py-0.5 font-mono text-[10px]">Tab</kbd> to accept
            {" "}&middot;{" "}
            <kbd className="rounded border border-gray-300 bg-white px-1 py-0.5 font-mono text-[10px]">Esc</kbd> to dismiss
          </p>
        </div>

        <ClinicalEditor />

        {/* Quick-try hints */}
        <div className="mt-6 flex flex-wrap items-center justify-center gap-2 text-xs text-gray-400">
          <span>Try:</span>
          {[
            '"patient has htn"',
            '"Glucose: 35"',
            '"copd with"',
            '"Na: 128"',
            '"Troponin: 0.5"',
          ].map((example) => (
            <span
              key={example}
              className="rounded-full border border-gray-200 bg-white px-2.5 py-1 font-mono text-[11px] text-gray-500"
            >
              {example}
            </span>
          ))}
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-200 bg-white py-4 text-center text-xs text-gray-400">
        Clinical Copilot Engine &middot; 4-Stage Waterfall: Abbreviation &rarr; MARISA-Trie &rarr; Lab Engine &rarr; BioMistral-7B
      </footer>
    </div>
  );
}
