import EsmSplit.CoreJS.IndexedReorder
import EsmSplit.CoreJS.LinkedInput

/-! Authenticate executable inline exports against the actual planner bundle
and authored entry. The original export ordinal remains an executable unit. -/

namespace CoreJS.IndexedInlinePlan

open LinkedInput (IndexedSource InlineOnlySource InlineExportUnit)

private def publishPairs (names : List (Name × Name)) : List (Name × Option Name) :=
  names.map fun (publicName, localName) => (publicName, some localName)

private theorem localExports_publishPairs (names : List (Name × Name)) :
    EsmSplit.localExports (publishPairs names) = names := by
  induction names with
  | nil => rfl
  | cons pair rest ih =>
    obtain ⟨publicName, localName⟩ := pair
    simp only [publishPairs, List.map_cons, EsmSplit.localExports, List.filterMap_cons, Option.map_some]
    exact congrArg ((publicName, localName) :: ·) ih

/-- Each inline item belongs to the executable source body. Its actual
footprint publishes exactly those ordered names at the same ordinal. -/
def RowAtEntry (source : Module) (B : EsmSplit.Bundle) (S : EsmSplit.Spec)
    (entry : EsmSplit.Module) (row : InlineExportUnit) : Prop :=
  row.ordinal ∈ source.body.map Prod.fst ∧
    row.ordinal < B.length ∧
    row.ordinal ∈ entry.stmts ∧
    S.claimants B row.ordinal = [S.entry] ∧
    (B.stmt row.ordinal).exports = publishPairs row.names ∧
    ∀ pair ∈ row.names, pair.2 ∈ (B.stmt row.ordinal).defs

instance (source : Module) (B : EsmSplit.Bundle) (S : EsmSplit.Spec)
    (entry : EsmSplit.Module) (row : InlineExportUnit) :
    Decidable (RowAtEntry source B S entry row) := by
  unfold RowAtEntry
  infer_instance

structure Checked (decoded : IndexedSource) (B : EsmSplit.Bundle) (S : EsmSplit.Spec) (P : EsmSplit.Plan) where
  source : InlineOnlySource decoded
  planEq : P = EsmSplit.mkPlan B S
  entry : EsmSplit.Module
  planEntry : P.find P.entry = some entry
  unique : (decoded.inlineExports.map (·.ordinal)).Nodup
  rows : ∀ row ∈ decoded.inlineExports, RowAtEntry source.module B S entry row
  noGlue : entry.exports = []
  publication : entry.published B = publishPairs decoded.inlineExportNames

/-- Use the already-derived authored plan. Check every original inline ordinal
and the entry's ordered publishing footprints before constructing output. -/
def check {decoded : IndexedSource} (source : InlineOnlySource decoded)
    (B : EsmSplit.Bundle) (S : EsmSplit.Spec) (P : EsmSplit.Plan) (planEq : P = EsmSplit.mkPlan B S) :
    Except String (Checked decoded B S P) := do
  match found : P.find P.entry with
  | none => throw "authored plan has no entry"
  | some entry =>
    let .isTrue unique := (inferInstance : Decidable ((decoded.inlineExports.map (·.ordinal)).Nodup)) |
      throw "inline export ordinals are duplicated"
    let .isTrue rows := (inferInstance : Decidable (∀ row ∈ decoded.inlineExports,
      RowAtEntry source.module B S entry row)) |
      throw "inline export ordinal, declaration, or authored entry ownership differs"
    let .isTrue noGlue := (inferInstance : Decidable (entry.exports = [])) |
      throw "entry needs unsupported glue exports"
    let .isTrue publication := (inferInstance : Decidable
        (entry.published B = publishPairs decoded.inlineExportNames)) |
      throw "planned entry publication differs from the original inline export order"
    return ⟨source, planEq, entry, found, unique, rows, noGlue, publication⟩

/-- The common checked footprints connect each inline row to the actual
CoreJS declaration at its original executable ordinal. -/
theorem Checked.originalDeclaration {decoded B S P} (checked : Checked decoded B S P)
    (footprints : IndexedExportCells.Footprints checked.source.module.body B)
    {row : InlineExportUnit} (member : row ∈ decoded.inlineExports) :
    ∃ stmt, checked.source.module.body.lookup row.ordinal = some stmt ∧
      ∀ pair ∈ row.names, pair.2 ∈ stmt.bindings.map Prod.fst := by
  obtain ⟨inBody, _, _, _, _, defined⟩ := checked.rows row member
  obtain ⟨⟨id, stmt⟩, present, same⟩ := List.mem_map.1 inBody
  change id = row.ordinal at same
  subst id
  have found : checked.source.module.body.lookup row.ordinal = some stmt :=
    IndexedExportCells.body_lookup footprints present
  exact ⟨stmt, found, fun pair inNames =>
    ((footprints.statement row.ordinal stmt found).2 pair.2).1 (defined pair inNames)⟩

/-- The live-cell proof receives names from the checked original rows, each
backed by its own local declaration in the entry. -/
theorem Checked.owned {decoded B S P} (checked : Checked decoded B S P) :
    IndexedReorder.InlineExportsOwned checked.source.module B checked.entry := by
  intro pair member
  rw [checked.source.table, IndexedSource.inlineExportNames] at member
  obtain ⟨row, inRows, inNames⟩ := List.mem_flatMap.1 member
  change pair ∈ row.names at inNames
  obtain ⟨_, within, inEntry, _, published, declared⟩ := checked.rows row inRows
  refine ⟨row.ordinal, inEntry, within, declared pair inNames, ?_⟩
  rw [published]
  exact List.mem_map.2 ⟨pair, inNames, by cases pair <;> rfl⟩

/-- The constructed module's public spelling follows from the planned
publishing footprints. The linker separately resolves these names to cells. -/
theorem Checked.table {decoded B S P} (checked : Checked decoded B S P) :
    (moduleOfIndexed checked.source.module.body B P checked.entry).exports = checked.source.module.exports := by
  change checked.entry.exports ++ EsmSplit.localExports (checked.entry.published B) = _
  rw [checked.noGlue, List.nil_append, checked.publication, localExports_publishPairs, checked.source.table]

#print axioms check
#print axioms Checked.originalDeclaration
#print axioms Checked.owned
#print axioms Checked.table

end CoreJS.IndexedInlinePlan
