# Timestamp Naming Scan Results

## Summary

All non-standard timestamp field naming has been standardized to use `_at` suffix throughout the ducktape codebase.

**Completed**:
- ✅ rspcache module - all `_ts` fields renamed to `_at` (created_at, revoked_at, updated_at)
- ✅ agent/server module - `event_ts` renamed to `event_at`
- ✅ llm/html server - `last_updated` renamed to `updated_at`
- ✅ openai_utils/probe module - `start_ts`/`end_ts` renamed to `started_at`/`ended_at`

**Status**: All timestamp field naming issues resolved.

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

**Rationale**: This is a **local variable** (not a model field), used temporarily for an annotation value. While it could be renamed to `created_at` for consistency, it's less critical than database/API model fields. Very low priority.

---

### Test Data

#### /home/user/ducktape/gatelet/gatelet/server/tests/activitywatch_sample.py

**Lines 15, 25, 35**
- `"last_updated": "2025-05-22T09:53:48.805000+00:00"` - Test fixture data

**Rationale**: Sample data matching an external ActivityWatch API format. Acceptable to match external API naming in test fixtures.

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

### openai_utils/probe Module
- ✅ `ProbeRecord`: `start_ts` → `started_at`, `end_ts` → `ended_at`
- ✅ All usages updated in main.py, store.py
- ✅ Updated calculations, method signatures, and data passing throughout

**Benefits Achieved**:
- Matches industry conventions (Rails, Django, GitHub API, Stripe, etc.)
- Improved code readability ("created at" vs "created timestamp")
- Reduced cognitive load for developers familiar with standard patterns
- Better IDE autocomplete support
- Simplified onboarding for new developers
- Consistent naming across entire codebase
