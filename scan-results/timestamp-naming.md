# Timestamp Naming Scan Results

## Summary

This scan tracks non-standard timestamp field naming in the ducktape codebase.

**Completed**:
- ✅ rspcache module - all `_ts` fields renamed to `_at` (created_at, revoked_at, updated_at)
- ✅ agent/server module - `event_ts` renamed to `event_at`
- ✅ llm/html server - `last_updated` renamed to `updated_at`

**Remaining**: openai_utils/probe module (medium priority, not in scope for this cleanup)

---

## Remaining Findings

### 1. openai_utils/probe Module (MEDIUM PRIORITY - Not Applied)

#### /home/user/ducktape/adgn/src/adgn/openai_utils/probe/main.py

**ProbeRecord Model (Lines 134-135)**
- `start_ts: datetime | None = None` - Should be `started_at`
- `end_ts: datetime | None = None` - Should be `ended_at` or `completed_at`

**Rationale**: These represent timing measurements for probe operations. While `start_ts`/`end_ts` are shorter, `started_at`/completed_at` would be more consistent with industry standards.

**Multiple usages throughout (Lines 173, 259-260, 442, 448, 454, 456, 526-527, 561-562)**
- Extensive use of `start_ts` and `end_ts` in calculations, method signatures, and data passing
- All these references would need updating if the field names are changed

**Impact**: Moderate - would require updates across probe module but isolated to that component.

---

#### /home/user/ducktape/adgn/src/adgn/openai_utils/probe/store.py

**Lines 65, 134-135**
- References to `res.start_ts` and `res.end_ts`

**Rationale**: Continued use of non-standard timestamp naming from the main module.

---

## Special Cases (Acceptable - No Action Needed)

### External API Fields

#### /home/user/ducktape/tana/src/tana/domain/nodes.py

**Line 51**
- `modified_ts: list[int] | None = Field(alias="modifiedTs", default=None)`

**Rationale**: **Acceptable** - This field is aliased from an external Tana API that uses `modifiedTs`. Maintaining `_ts` internally for consistency with the external naming is appropriate per scan guidelines: "OK to use `_ts` when External API requires it".

---

### Local Variables

#### /home/user/ducktape/k8s/helm/ember/files/rspcache_key_rotator.py

**Line 77**
- `created_ts = datetime.now(UTC).isoformat()` - Variable name uses `_ts`

**Rationale**: This is a **local variable** (not a model field), used temporarily for an annotation value. While it could be renamed to `created_at` for consistency, it's less critical than database/API model fields. Low priority.

---

### Test Data

#### /home/user/ducktape/gatelet/gatelet/server/tests/activitywatch_sample.py

**Lines 15, 25, 35**
- `"last_updated": "2025-05-22T09:53:48.805000+00:00"` - Test fixture data

**Rationale**: Sample data matching an external ActivityWatch API format. Acceptable to match external API naming in test fixtures.

---

## Recommendations

### Remaining Work (Optional)

1. **openai_utils/probe module** (MEDIUM PRIORITY):
   - Rename `start_ts`/`end_ts` to `started_at`/`completed_at` (or `ended_at`)
   - Update all calculation and method signature references
   - Isolated change within probe component

### No Action Needed

- **tana module**: Keep `modified_ts` as it mirrors external API naming
- **Test fixtures**: Keep as-is to match external API formats
- **k8s rotator script**: Local variable, very low priority

---

## Completed Changes

The following modules have been successfully updated to use standard `_at` naming conventions:

### rspcache Module
- ✅ `ClientAPIKey`: `created_ts` → `created_at`, `revoked_ts` → `revoked_at`
- ✅ `ResponseFrame`: `created_ts` → `created_at`
- ✅ `Response`: `created_ts` → `created_at`, `last_update_ts` → `updated_at`
- ✅ `ResponseSnapshot`: `created_ts` → `created_at`, `updated_ts` → `updated_at`
- ✅ `APIKeyRecord`: `created_ts` → `created_at`, `revoked_ts` → `revoked_at`
- ✅ Index: `idx_responses_created_ts` → `idx_responses_created_at`
- ✅ All queries, updates, and references updated across responses_db.py, admin_app.py, cli.py

### agent/server Module
- ✅ `Envelope`: `event_ts` → `event_at`
- ✅ All usages updated in protocol.py, ws.py, runtime.py

### llm/html Server
- ✅ `STATS_CACHE`: `"last_updated"` → `"updated_at"` (dict key)
- ✅ All references updated in server.py

**Benefits Achieved**:
- Matches industry conventions (Rails, Django, GitHub API, Stripe, etc.)
- Improved code readability ("created at" vs "created timestamp")
- Reduced cognitive load for developers familiar with standard patterns
- Better IDE autocomplete support
- Simplified onboarding for new developers
