# JSONB Normalization Plan

## Summary

Several JSONB columns should be converted to proper normalized tables for better queryability, validation, and integrity.

## Keep as JSONB (Legitimate use cases)

These are **correctly using JSONB**:

1. **`AgentRun.type_config`** - Polymorphic discriminated union (PydanticColumn)
2. **`Event.payload`** - Polymorphic event data (PydanticColumn)
3. **`ReportedIssueOccurrence.locations`** - Tightly coupled small list (PydanticColumn)
4. **View aggregates** - `status_counts`, `winning_definitions` (computed aggregates)

## Convert to Tables

### Priority 1: Occurrence Files & Ranges

**Current State:**
- `TruePositiveOccurrenceORM.files`: `Mapped[dict]` storing `{path: [line_ranges] | null}`
- `FalsePositiveOccurrenceORM.files`: `Mapped[dict]` storing `{path: [line_ranges] | null}`

**Problems:**
- Can't query "all TPs affecting file X"
- Can't filter by line numbers in SQL
- No foreign key validation
- Per-range notes buried in nested JSONB
- Type safety only at application layer

**Proposed Schema:**

```python
class TruePositiveOccurrenceRange(Base):
    """Line range within a TP occurrence."""
    __tablename__ = "tp_occurrence_ranges"

    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(primary_key=True)
    tp_id: Mapped[str] = mapped_column(primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(primary_key=True)
    range_id: Mapped[int] = mapped_column(primary_key=True)  # 0-based index within file

    start_line: Mapped[int] = mapped_column(nullable=False)
    end_line: Mapped[int] = mapped_column(nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_slug", "tp_id", "occurrence_id"],
            ["tp_occurrences.snapshot_slug", "tp_occurrences.tp_id", "tp_occurrences.occurrence_id"],
            ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["snapshot_slug", "file_path"],
            ["snapshot_files.snapshot_slug", "snapshot_files.relative_path"],
            ondelete="CASCADE",
            name="fk_tp_range_snapshot_file"
        ),
        CheckConstraint("start_line >= 1"),
        CheckConstraint("end_line >= start_line"),
        CheckConstraint("start_line <= end_line"),  # Redundant but explicit
    )

class FalsePositiveOccurrenceRange(Base):
    """Line range within an FP occurrence."""
    __tablename__ = "fp_occurrence_ranges"

    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(primary_key=True)
    fp_id: Mapped[str] = mapped_column(primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(primary_key=True)
    range_id: Mapped[int] = mapped_column(primary_key=True)

    start_line: Mapped[int] = mapped_column(nullable=False)
    end_line: Mapped[int] = mapped_column(nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_slug", "fp_id", "occurrence_id"],
            ["fp_occurrences.snapshot_slug", "fp_occurrences.fp_id", "fp_occurrences.occurrence_id"],
            ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["snapshot_slug", "file_path"],
            ["snapshot_files.snapshot_slug", "snapshot_files.relative_path"],
            ondelete="CASCADE",
            name="fk_fp_range_snapshot_file"
        ),
        CheckConstraint("start_line >= 1"),
        CheckConstraint("end_line >= start_line"),
    )
```

**Migration Strategy:**
1. Create new tables with migration
2. Populate from existing JSONB data
3. Update application code to use new tables
4. Add database constraint to ensure JSONB and table stay in sync during transition
5. Remove JSONB column after full migration

**Benefits:**
- SQL queries: `WHERE file_path = 'foo.py' AND start_line <= 50 AND end_line >= 40`
- Proper indexing on file paths and line ranges
- Foreign key integrity:
  - To `tp_occurrences`/`fp_occurrences` (CASCADE deletes)
  - To `snapshot_files` (validates file exists in snapshot)
- Per-range notes as first-class columns
- Better support for range-based analytics
- **Referential integrity**: Database enforces that ground truth only references files that actually exist in the snapshot
- **Line number validation**: Can add CHECK constraint that `end_line <= snapshot_files.line_count`

### Priority 2: FP Relevant Files

**Current State:**
- `FalsePositiveOccurrenceORM.relevant_files`: `Mapped[list]` storing `[path, ...]`

**Problems:**
- Can't join on relevant files
- No foreign key validation
- Can't efficiently query "FPs relevant to file X"

**Proposed Schema:**

```python
class FalsePositiveRelevantFile(Base):
    """Files that make an FP occurrence relevant."""
    __tablename__ = "fp_occurrence_relevant_files"

    snapshot_slug: Mapped[SnapshotSlug] = mapped_column(primary_key=True)
    fp_id: Mapped[str] = mapped_column(primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_slug", "fp_id", "occurrence_id"],
            ["fp_occurrences.snapshot_slug", "fp_occurrences.fp_id", "fp_occurrences.occurrence_id"],
            ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["snapshot_slug", "file_path"],
            ["snapshot_files.snapshot_slug", "snapshot_files.relative_path"],
            ondelete="CASCADE",
            name="fk_fp_relevant_file_snapshot_file"
        ),
    )
```

**Benefits:**
- Join queries: `JOIN fp_occurrence_relevant_files ON file_path = reviewed_file`
- Proper foreign keys
- Easier to query scope relevance

## Implementation Notes

### Backward Compatibility

During migration:
1. Keep JSONB columns temporarily
2. Dual-write to both JSONB and new tables
3. Add validation that JSONB matches table data
4. Gradually migrate read queries to new tables
5. Remove JSONB columns after full cutover

### Data Migration

```python
# Migration pseudo-code for TP ranges
for occ in session.query(TruePositiveOccurrenceORM).all():
    files_dict = occ.files  # Current JSONB
    for file_path, ranges_json in files_dict.items():
        if ranges_json is None:
            # Null ranges = whole file anchor (no specific lines)
            continue
        for idx, range_data in enumerate(ranges_json):
            new_range = TruePositiveOccurrenceRange(
                snapshot_slug=occ.snapshot_slug,
                tp_id=occ.tp_id,
                occurrence_id=occ.occurrence_id,
                file_path=file_path,
                range_id=idx,
                start_line=range_data["start_line"],
                end_line=range_data["end_line"],
                note=range_data.get("note"),
            )
            session.add(new_range)
```

### API Impact

Minimal - API responses can be constructed from either source:
- Before migration: Read from JSONB, parse to LineRange
- After migration: Read from table, construct LineRange objects
- API schema stays the same

### Performance Considerations

**Pros:**
- Better indexes → faster file-based queries
- Selective loading (don't load all ranges if you only need counts)
- Native SQL operations on line numbers

**Cons:**
- More rows (each range = separate row vs nested in JSONB)
- More joins required
- Slightly more complex queries

**Mitigation:**
- Use eager loading where appropriate
- Create composite indexes on common query patterns
- Keep denormalized views for common aggregations

## Timeline

1. **Phase 1** (Week 1): Create new tables, migration script
2. **Phase 2** (Week 2): Dual-write implementation, validation
3. **Phase 3** (Week 3): Migrate read queries, test thoroughly
4. **Phase 4** (Week 4): Remove JSONB columns, clean up code

## Open Questions

1. Should we keep a denormalized JSONB copy for backward compatibility?
   - **Recommendation**: No, clean break is better long-term

2. How to handle whole-file anchors (ranges=null)?
   - **Option A**: No rows in ranges table = whole file
   - **Option B**: Synthetic sentinel range (0, 0)
   - **Recommendation**: Option A - null in JSONB maps to zero rows

3. What about match_filter_hash (used for grader optimization)?
   - Keep on occurrence table - it's a hash of the file set, not per-range data

4. Should we add line number validation against `snapshot_files.line_count`?
   - **Option A**: CHECK constraint joining to snapshot_files (complex, not all DBs support)
   - **Option B**: Application-level validation during YAML load
   - **Option C**: Trigger to validate on INSERT/UPDATE
   - **Recommendation**: Option B for now - validate during sync from YAML
   - **Future enhancement**: Could add trigger if we see invalid data in production

## Additional Validations

Once normalized, we can add these constraints:

```python
# Optional future constraint (via trigger)
CREATE TRIGGER validate_range_line_numbers
BEFORE INSERT OR UPDATE ON tp_occurrence_ranges
FOR EACH ROW
EXECUTE FUNCTION check_range_within_file_bounds();

-- Function would verify:
-- NEW.end_line <= (SELECT line_count FROM snapshot_files
--                   WHERE snapshot_slug = NEW.snapshot_slug
--                   AND relative_path = NEW.file_path)
```

This would catch authoring errors where ground truth references line numbers beyond EOF.
