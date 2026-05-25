import React from "react";

// Surface dispatch was removed when the legacy scenario-set frontend was
// deleted; product is the only surface. `activeSurface` is retained for
// callsite compatibility but ignored.
export function surfaceFromPathname() {
  return "product";
}

export function AugurShellHeader({ activeSurface: _activeSurface, rightSlot = null }) {
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 px-4 py-3 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-950/95 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-base font-semibold text-slate-950 dark:text-slate-50">Augur</h1>
          <div className="text-xs uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            Financial futures explorer
          </div>
        </div>
        {rightSlot && (
          <div className="flex min-w-[min(100%,28rem)] flex-1 flex-wrap items-center justify-end gap-3 text-xs augur-muted sm:flex-none">
            {rightSlot}
          </div>
        )}
      </div>
    </header>
  );
}
