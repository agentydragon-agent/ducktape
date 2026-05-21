import React from "react";

const SURFACES = [
  { id: "scenario_set", label: "Scenario set", href: "/distribution" },
  { id: "product", label: "Product", href: "/product" },
];

export function surfaceFromPathname(pathname) {
  const [firstSegment] = String(pathname ?? "")
    .split("/")
    .filter(Boolean);
  return firstSegment === "product" ? "product" : "scenario_set";
}

export function AugurShellHeader({ activeSurface, rightSlot = null }) {
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 px-4 py-3 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-950/95 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-base font-semibold text-slate-950 dark:text-slate-50">Augur</h1>
          <div className="text-xs uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            Financial futures explorer
          </div>
        </div>
        <div className="flex min-w-[min(100%,28rem)] flex-1 flex-wrap items-center justify-end gap-3 text-xs augur-muted sm:flex-none">
          <nav
            aria-label="Augur workspace"
            className="flex rounded-md border border-slate-200 bg-slate-50 p-1 dark:border-slate-800 dark:bg-slate-900"
          >
            {SURFACES.map((surface) => {
              const active = activeSurface === surface.id;
              return (
                <a
                  key={surface.id}
                  href={surface.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded px-3 py-1.5 text-sm font-semibold transition ${
                    active
                      ? "bg-blue-600 text-white shadow-sm dark:bg-blue-500 dark:text-white"
                      : "text-slate-600 hover:bg-white hover:text-blue-700 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-blue-300"
                  }`}
                >
                  {surface.label}
                </a>
              );
            })}
          </nav>
          {rightSlot}
        </div>
      </div>
    </header>
  );
}
