# Grader TODOs

## N-to-M Matching with Credit Assignment

**Implemented:**
- Credit assignment with database-level validation (triggers enforce sum ≤ 1.0 per occurrence)
- Unknowns storage per grader run (`GraderSuccess.unknowns`)
- Interactive human labeling workflow (`/verify-clusters` command)

**TODO:**
- Automated cross-critique clustering of unknowns
- Completeness validation (every input issue matched OR unknown, no overlaps)
- Ground truth provenance tracking (human-labeled vs original)
- Automatic re-grading after ground truth updates

---

## Related Work

See also:
- `src/adgn/props/db/temp_user_manager.py` - Unified user manager for all agent types
- `src/adgn/props/clustering/` - Clustering infrastructure
- `src/adgn/props/db/migrations/versions/*_clustering*.py` - Clustering schema migrations
