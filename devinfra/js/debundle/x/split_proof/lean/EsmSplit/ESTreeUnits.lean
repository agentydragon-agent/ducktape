import EsmSplit.ESTreeSource

open Lean

namespace ESTreeUnits

private def replaceField (node : Json) (key : String) (value : Json) : Except String Json := do
  return .obj ((← node.getObj?).insert key value)

private def split (statement : Json) : Except String (Array Json) := do
  let exported := (← statement.getObjValAs? String "type") == "ExportNamedDeclaration"
  let declaration ← if exported then statement.getObjVal? "declaration" else pure statement
  if declaration == .null then return #[statement]
  if (← declaration.getObjValAs? String "type") != "VariableDeclaration" then return #[statement]
  let kind ← declaration.getObjValAs? String "kind"
  let declarators ← declaration.getObjValAs? (Array Json) "declarations"
  unless declarators.size > 1 && ["var", "let", "const"].contains kind do return #[statement]
  declarators.mapM fun d => do
    let single ← replaceField declaration "declarations" (.arr #[d])
    if exported then replaceField statement "declaration" single else pure single

/-- Source ordinals are array indices. A split declaration keeps the original declarator node. -/
def nodes (program : Json) : Except String (Array Json) := do
  unless (← program.getObjValAs? String "type") == "Program" do throw "expected an ESTree Program"
  unless (← program.getObjValAs? String "sourceType") == "module" do throw "expected an ESTree module Program"
  let body ← program.getObjValAs? (Array Json) "body"
  let mut units := Array.mkEmpty body.size
  for statement in body do
    for unit in (← split statement) do units := units.push unit
  return units

/-- Validate the ranges without changing or renumbering the source units. -/
def validateRanges (units : Array Json) (source : String) : Except String Unit := do
  let offsets := ESTreeSource.ranges source
  for ast in units do
    offsets.validate ast
    let decl := if (ast.getObjVal? "type").toOption == some (.str "ExportNamedDeclaration")
      then (ast.getObjVal? "declaration").toOption.getD .null else ast
    if let .ok ds := decl.getObjValAs? (Array Json) "declarations" then
      for d in ds do offsets.validate d

/-- Validate source unit positions before using any ranges in the printer. Model-only ASTs
need no positions and use `nodes` directly. -/
def checkedNodes (program : Json) (source : String) : Except String (Array Json) := do
  let units ← nodes program
  validateRanges units source
  return units

/-- Range validation retains the exact nodes and therefore their original ordinals. -/
theorem checkedNodes_nodes {program : Json} {source : String} {units : Array Json}
    (accepted : checkedNodes program source = .ok units) : nodes program = .ok units := by
  cases hn : nodes program with
  | error reason => simp [checkedNodes, hn, bind, Except.bind] at accepted
  | ok found =>
    cases hv : validateRanges found source with
    | error reason => simp [checkedNodes, hn, hv, bind, Except.bind] at accepted
    | ok _ => simpa [checkedNodes, hn, hv, bind, Except.bind, pure, Except.pure] using accepted

end ESTreeUnits
