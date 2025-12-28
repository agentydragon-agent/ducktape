# Props Backend TODO

## High Priority

- [ ] **Show incomplete runs properly**
  - Don't count incomplete runs in stats aggregates
  - Add "X runs in progress" indicator when applicable

## Medium Priority

- [ ] **Improve status display**
  - Replace S/C letters with full words or icons
  - Has tooltips already, just need visible labels

## Lower Priority

- [ ] **Stats display improvements**
  - Move total available count to subheader: "Valid Partial (N=171)" instead of "5/171" per row
  - Full 95% CI display: "45.2% [38.1% - 52.3%]" or "45.2% ±7.1%"

- [ ] **Migrate `props stats` to frontend**
  - Tables: by-example, by-occurrence views
  - Include props stats subcommands: `example`, `occurrence`

- [ ] **Live rollout display**
  - Grid of validation jobs with progress bars
  - Timeline of runs (critic->grader pairs)

## Future

- [ ] **Ground truth update workflow**
  - BUG: Staleness check marks everything as stale (compares wrong fields)
  - Fix: Compare only TP/FP IDs, rationales, locations - not `critic_scopes_expected_to_recall`
  - Then: `/api/stats/stale-runs` endpoint, dashboard indicator, regrade button

- [ ] **Definitions browser page**
  - Filter by agent type
  - View definition details (tarball contents)
  - Click through to runs
