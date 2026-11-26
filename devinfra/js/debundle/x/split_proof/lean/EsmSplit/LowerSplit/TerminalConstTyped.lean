import EsmSplit.LowerSplit.TerminalConstDecoder

/-! A total decoder for the fixed terminal-const raw output shape. This is a
proof-facing construction: the production emitter, source admission, and the
printer/reparse path still require correspondence proofs. -/

namespace EsmSplit.LowerSplit.TerminalConstTyped

open Lean (Json toJson)
open CoreJS CoreJS.TerminalConstConstruction

set_option maxRecDepth 16000
set_option maxHeartbeats 4000000

private def node (kind : String) (fields : List (String × Json)) : Json :=
  Json.mkObj (("type", .str kind) :: fields)

private def ident : Json := node "Identifier" [("name", .str "x")]
private def exportSpec : Json := node "ExportSpecifier" [("local", ident), ("exported", ident)]
private def importSpec : Json := node "ImportSpecifier" [("local", ident), ("imported", ident)]
private def importNode : Json := node "ImportDeclaration" [
  ("source", node "Literal" [("value", .str "./provider.mjs")]),
  ("specifiers", toJson [importSpec]), ("attributes", .arr #[])]
private def glueExport : Json := node "ExportNamedDeclaration" [
  ("declaration", .null), ("source", .null), ("specifiers", toJson [exportSpec]), ("attributes", .arr #[])]

/-- Original nodes and the optional source hashbang are carried verbatim. -/
def encode (declaration exportNode : Json) (hashbang : Option String) : Json :=
  let hashbang := hashbang.toList.map fun text => ("hashbang", Json.str text)
  Json.mkObj [
    ("entry.mjs", node "Program" ([("sourceType", .str "module"),
      ("body", toJson [importNode, exportNode])] ++ hashbang)),
    ("provider.mjs", node "Program" [("sourceType", .str "module"),
      ("body", toJson [declaration, glueExport])])]

private def body (j : Json) : Except String (List Json) := do
  unless (← j.getObjValAs? String "type") == "Program" do throw "expected Program"
  unless (← j.getObjValAs? String "sourceType") == "module" do throw "expected module"
  j.getObjValAs? (List Json) "body"

private def bodies (files : Json) : Except String (List Json × List Json) := do
  let entry ← files.getObjVal? "entry.mjs" >>= body
  let provider ← files.getObjVal? "provider.mjs" >>= body
  return (entry, provider)

/-- Decode only an explicit local export list, including the existing attribute check. -/
def localExports (j : Json) : Except String (List (Name × Name)) := do
  unless (← j.getObjValAs? String "type") == "ExportNamedDeclaration" do throw "expected export"
  ModuleInput.noAttributes j
  match ← j.getObjVal? "source" with
  | .null => pure ()
  | _ => throw "expected local export"
  match ← j.getObjVal? "declaration" with
  | .null => pure ()
  | _ => throw "expected export list"
  (← j.getObjValAs? (List Json) "specifiers").mapM FromESTree.exportSpec

/-- Decode the raw staged programs; no JavaScript printing or reparsing is asserted. -/
def decode (files : Json) : Except String Program := do
  let (entryNodes, providerNodes) ← bodies files
  let [imp, originalExport] := entryNodes | throw "expected entry glue and export"
  let [decl, generatedExport] := providerNodes | throw "expected declaration and export glue"
  let request ← ModuleInput.importDecl "entry.mjs" imp
  let entryExports ← localExports originalExport
  let (_, statement) ← FromESTree.declaration [] decl
  let providerExports ← localExports generatedExport
  return ⟨"entry.mjs", [⟨"entry.mjs", [request], [], entryExports⟩,
    ⟨"provider.mjs", [], [(0, statement)], providerExports⟩]⟩

private theorem encode_bodies (declaration exportNode : Json) (hashbang : Option String) :
    bodies (encode declaration exportNode hashbang) =
      .ok ([importNode, exportNode], [declaration, glueExport]) := by
  cases hashbang <;> cbv

private theorem import_node : ModuleInput.importDecl "entry.mjs" importNode =
    .ok ⟨"provider.mjs", [("x", "x")]⟩ := by cbv

private theorem glue_exports : localExports glueExport = .ok [("x", "x")] := by cbv

/-- Source-only decoding facts determine the output model. Neither the output
model nor its semantics is checked as a candidate at runtime. -/
theorem decode_encode (declaration exportNode : Json) (hashbang : Option String) (value : Float)
    (declarationDecoded : FromESTree.declaration [] declaration =
      .ok ("x", .decl .const "x" (.num value)))
    (exportsDecoded : localExports exportNode = .ok [("x", "x")]) :
    decode (encode declaration exportNode hashbang) = .ok (construct value) := by
  simp [decode, encode_bodies, import_node, glue_exports, declarationDecoded, exportsDecoded,
    bind, Except.bind, pure, Except.pure, TerminalConstConstruction.construct,
    TerminalConstConstruction.entry, TerminalConstConstruction.provider,
    TerminalConstConstruction.declaration]

/-- The additional checks consume only the original source nodes. The linked
source decoder and parser remain separate premises of the full construction. -/
structure Source (declaration exportNode : Json) where
  value : Float
  declarationDecoded : FromESTree.declaration [] declaration =
    .ok ("x", .decl .const "x" (.num value))
  exportsDecoded : localExports exportNode = .ok [("x", "x")]

def admitSource (declaration exportNode : Json) : Except String (Source declaration exportNode) := do
  match declarationDecoded : FromESTree.declaration [] declaration with
  | .ok ("x", .decl .const "x" (.num value)) =>
    match exportsDecoded : localExports exportNode with
    | .ok [("x", "x")] => return ⟨value, declarationDecoded, exportsDecoded⟩
    | _ => throw "expected the local export of x"
  | _ => throw "expected a numeric const x"

theorem admitted_decode (declaration exportNode : Json) (hashbang : Option String)
    (source : Source declaration exportNode) :
    decode (encode declaration exportNode hashbang) = .ok (construct source.value) :=
  decode_encode declaration exportNode hashbang source.value source.declarationDecoded source.exportsDecoded

#print axioms decode_encode
#print axioms admitted_decode

end EsmSplit.LowerSplit.TerminalConstTyped
