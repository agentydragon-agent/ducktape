import React from "react";
import { Button } from "@mantine/core";

import { AugurShellHeader } from "./shell.jsx";

export default function ProductProjectionAppShell() {
  return (
    <div
      data-augur-surface="product"
      className="min-h-screen bg-slate-100 text-slate-800 dark:bg-slate-950 dark:text-slate-100"
    >
      <AugurShellHeader
        activeSurface="product"
        rightSlot={<span className="whitespace-nowrap">Product projection</span>}
      />

      <main className="px-4 py-6 sm:px-6 lg:px-8">
        <section className="grid min-w-0 gap-5 xl:grid-cols-[26rem_minmax(0,1fr)]">
          <aside className="min-w-0 space-y-5">
            <div className="augur-card p-4">
              <div className="augur-eyebrow">Scenario</div>
              <h2 className="display mt-2 text-xl augur-heading">Cash runway</h2>
              <div className="mt-5 h-40 rounded-md border border-dashed border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900" />
            </div>
            <div className="augur-card p-4">
              <div className="augur-eyebrow">Controls</div>
              <div className="mt-4 grid gap-3">
                <Button variant="light" disabled>
                  Run projection
                </Button>
              </div>
            </div>
          </aside>

          <div className="min-w-0 space-y-5">
            <div className="border-b border-slate-300 pb-5 dark:border-slate-700">
              <div className="augur-eyebrow">Product projection</div>
              <h2 className="display mt-2 text-3xl text-slate-950 dark:text-slate-50">Cash runway</h2>
            </div>

            <div
              data-product-empty-state="cash-runway"
              className="augur-panel min-h-[28rem] rounded-lg border-dashed p-5"
              aria-label="Cash runway projection workspace"
            >
              <div className="h-full min-h-[24rem] rounded-md border border-dashed border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900" />
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
