# Timestamp Naming Scan Results

## Summary

This scan found **multiple instances** of non-standard timestamp field naming throughout the ducktape codebase. The primary issues are:

1. **Use of `_ts` suffix instead of `_at`** - Found extensively in the rspcache module and scattered across other modules
2. **Verbose naming (`last_update_ts` vs `updated_at`)** - Found in rspcache Response model
3. **Cache dictionary using `last_updated`** - Found in llm/html server

The rspcache module is the primary area requiring refactoring, with consistent use of non-standard `_ts` suffixes across its database models (ClientAPIKey, ResponseFrame, Response, ResponseSnapshot).

---

## Detailed Findings

### 1. rspcache Module (Primary Area)

#### /home/user/ducktape/adgn/src/adgn/rspcache/responses_db.py

**ClientAPIKey Model (Lines 69-70)**
- `created_ts: Mapped[datetime]` - Should be `created_at`
- `revoked_ts: Mapped[datetime | None]` - Should be `revoked_at`

**Rationale**: These are database timestamp columns representing when an API key was created and optionally revoked. The `_ts` suffix is non-standard compared to industry conventions (Rails, Django, GitHub API, etc.).

**ResponseFrame Model (Line 90)**
- `created_ts: Mapped[datetime]` - Should be `created_at`

**Rationale**: Records when a response frame was created. Should follow standard `_at` convention.

**Response Model (Lines 111-112)**
- `created_ts: Mapped[datetime]` - Should be `created_at`
- `last_update_ts: Mapped[datetime]` - Should be `updated_at`

**Rationale**: Double violation - both uses `_ts` suffix AND uses verbose `last_update_ts` instead of the more concise, standard `updated_at`.

**ResponseSnapshot Model (Lines 132-134)**
- `created_ts: Mapped[datetime]` - Should be `created_at`
- `updated_ts: Mapped[datetime]` - Should be `updated_at`

**Rationale**: Mix of `_ts` naming. Should be `created_at` and `updated_at` for consistency.

**APIKeyRecord Dataclass (Lines 151-152)**
- `created_ts: datetime` - Should be `created_at`
- `revoked_ts: datetime | None` - Should be `revoked_at`

**Rationale**: Mirrors the ClientAPIKey model issues. This dataclass is used for API responses and should follow standard naming.

**Index Definition (Line 99)**
- `Index("idx_responses_created_ts", "created_ts")` - Index name would need updating when field is renamed

**Database Update Operations (Lines 242, 306, 337, 371, 396)**
- `.values(revoked_ts=datetime.now(UTC))` - Should use `revoked_at`
- `.values(status="in_progress", response_id=response_id, last_update_ts=datetime.now(UTC))` - Should use `updated_at`
- Multiple other update operations using these non-standard field names

**Query Operations (Lines 231, 241, 261, 416)**
- `.order_by(ClientAPIKey.created_ts.desc())` - Should use `created_at`
- `.where(ClientAPIKey.revoked_ts.is_(None))` - Should use `revoked_at`
- `.order_by(Response.created_ts.desc())` - Should use `created_at`

**Model Conversion (Lines 611-612)**
- `created_ts=obj.created_ts,` - Should use `created_at`
- `revoked_ts=obj.revoked_ts,` - Should use `revoked_at`

---

#### /home/user/ducktape/adgn/src/adgn/rspcache/admin_app.py

**Line 117**
- `revoked_ts: datetime | None = None` - Should be `revoked_at`

**Rationale**: API model field should follow standard naming conventions.

**Lines 162-163, 177, 188-189**
- Multiple usages mapping `created_ts`/`last_update_ts`/`revoked_ts` to `created_at`/`updated_at` in API responses
- Shows the inconsistency: database uses `_ts`, but API exposes `_at`

**Rationale**: The code is already doing the right thing in the API layer by exposing `created_at`/`updated_at`, but the database layer still uses non-standard names, creating unnecessary translation.

---

#### /home/user/ducktape/adgn/src/adgn/rspcache/cli.py

**Line 136**
- `status = "revoked" if item.revoked_ts else "active"` - Uses non-standard field name

**Rationale**: CLI code referencing the database model's non-standard field.

---

### 2. openai_utils/probe Module

#### /home/user/ducktape/adgn/src/adgn/openai_utils/probe/main.py

**ProbeRecord Model (Lines 134-135)**
- `start_ts: datetime | None = None` - Should be `started_at`
- `end_ts: datetime | None = None` - Should be `ended_at` or `completed_at`

**Rationale**: These represent timing measurements for probe operations. While `start_ts`/`end_ts` are shorter, `started_at`/`completed_at` would be more consistent with industry standards.

**Multiple usages throughout (Lines 173, 259-260, 442, 448, 454, 456, 526-527, 561-562)**
- Extensive use of `start_ts` and `end_ts` in calculations, method signatures, and data passing

**Rationale**: All these references would need updating if the field names are changed to follow standards.

---

#### /home/user/ducktape/adgn/src/adgn/openai_utils/probe/store.py

**Lines 65, 134-135**
- References to `res.start_ts` and `res.end_ts`

**Rationale**: Continued use of non-standard timestamp naming from the main module.

---

### 3. agent/server Module

#### /home/user/ducktape/adgn/src/adgn/agent/server/protocol.py

**Line 29**
- `event_ts: datetime` - Should be `event_at` or `occurred_at`

**Rationale**: Represents when an event occurred. Should follow `_at` convention.

---

#### /home/user/ducktape/adgn/src/adgn/agent/server/ws.py

**Line 175**
- `event_ts=datetime.now(UTC)` - Uses non-standard field

**Rationale**: Creating Envelope objects with non-standard timestamp field.

---

#### /home/user/ducktape/adgn/src/adgn/agent/server/runtime.py

**Line 148**
- `event_ts=datetime.now(UTC)` - Uses non-standard field

**Rationale**: Same pattern as ws.py.

---

### 4. llm/html Module

#### /home/user/ducktape/llm/html/llm_html/server.py

**Line 40**
- `STATS_CACHE = {"data": None, "last_updated": None, "ttl": timedelta(minutes=5)}` - Uses verbose `last_updated`

**Rationale**: While this is a dictionary key (not a typed field), it uses the verbose `last_updated` instead of the more concise `updated_at`. The scan specifically calls out `last_update` as a pattern to avoid.

**Lines 207-208, 237**
- References to `STATS_CACHE["last_updated"]` in conditional and assignment

**Rationale**: All references to this cache key would benefit from using `updated_at` instead.

---

### 5. Special Cases (Acceptable)

#### /home/user/ducktape/tana/src/tana/domain/nodes.py

**Line 51**
- `modified_ts: list[int] | None = Field(alias="modifiedTs", default=None)` - Uses `_ts` suffix

**Rationale**: This is **acceptable** per the scan guidelines' "Special Cases" section: "OK to use `_ts` when External API requires it". This field is aliased from an external Tana API that uses `modifiedTs`, so maintaining `_ts` internally for consistency with the external naming is appropriate.

---

#### /home/user/ducktape/k8s/helm/ember/files/rspcache_key_rotator.py

**Line 77**
- `created_ts = datetime.now(UTC).isoformat()` - Variable name uses `_ts`

**Rationale**: This is a **local variable** (not a model field), used temporarily for an annotation value. While it could be renamed to `created_at` for consistency, it's less critical than database/API model fields. The variable is used to create a `created_at` annotation key on line 82 and a `rspcache/key-rotated-at` annotation on line 95, showing mixed naming even within the same file.

---

### 6. Test Data (Informational)

#### /home/user/ducktape/gatelet/gatelet/server/tests/activitywatch_sample.py

**Lines 15, 25, 35**
- `"last_updated": "2025-05-22T09:53:48.805000+00:00"` - Test fixture data

**Rationale**: This appears to be sample data matching an external ActivityWatch API format. Generally acceptable to match external API naming in test fixtures.

---

## Impact Analysis

### Database Migration Required
The rspcache module changes would require:
1. **Database migrations** to rename columns:
   - `created_ts` → `created_at` (4 tables)
   - `last_update_ts` → `updated_at` (1 table)
   - `updated_ts` → `updated_at` (1 table)
   - `revoked_ts` → `revoked_at` (2 tables)

2. **Index renames**: `idx_responses_created_ts` → `idx_responses_created_at`

3. **Code updates**: All queries, updates, and model references throughout the codebase

### API Compatibility
The admin_app.py already exposes `created_at`/`updated_at` in its API responses, so external API consumers shouldn't be affected by the internal database changes. However, the CLI and any direct database queries would need updates.

### Consistency Benefits
Standardizing on `_at` would:
- Match industry conventions (Rails, Django, GitHub API, Stripe, etc.)
- Improve code readability ("created at" vs "created timestamp")
- Reduce cognitive load for developers familiar with standard patterns
- Enable better IDE autocomplete support
- Simplify onboarding for new developers

---

## Recommendations

### High Priority
1. **rspcache module**: Refactor all `_ts` fields to `_at` convention
   - This is the most extensive use and would provide the biggest consistency improvement
   - Create database migrations to rename columns
   - Update all references in queries, updates, and model conversions

### Medium Priority
2. **agent/server module**: Rename `event_ts` to `event_at` or `occurred_at`
   - More straightforward change with fewer dependencies
   - Improves consistency across the agent codebase

3. **openai_utils/probe module**: Rename `start_ts`/`end_ts` to `started_at`/`completed_at`
   - Consider `ended_at` vs `completed_at` based on semantics
   - Update all calculation and method signature references

### Low Priority
4. **llm/html server**: Rename `last_updated` dict key to `updated_at`
   - Simple dictionary key change
   - Low impact but improves consistency

### No Action Needed
- **tana module**: Keep `modified_ts` as it mirrors external API naming
- **Test fixtures**: Keep as-is to match external API formats
- **k8s rotator script**: Consider renaming for consistency but low priority
