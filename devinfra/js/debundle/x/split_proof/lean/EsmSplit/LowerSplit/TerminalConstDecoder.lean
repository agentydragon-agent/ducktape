import EsmSplit.LowerSplit.TerminalConstInput

/-! Build-time decoding facts for generated terminal-export glue. These facts do not
assert an equation for the emitter or the complete linked decoder. -/

namespace EsmSplit.LowerSplit.TerminalConstDecoder

open Lean (Json toJson)

set_option maxRecDepth 16000
set_option maxHeartbeats 4000000

private def node (kind : String) (fields : List (String × Json)) : Json :=
  Json.mkObj (("type", .str kind) :: fields)

private def ident (name : String) : Json := node "Identifier" [("name", .str name)]
private def exportSpecifier (name : String) : Json :=
  node "ExportSpecifier" [("local", ident name), ("exported", ident name)]
private def importSpecifier (name : String) : Json :=
  node "ImportSpecifier" [("local", ident name), ("imported", ident name)]
private def importDecl (name : String) : Json := node "ImportDeclaration" [
  ("source", node "Literal" [("value", .str "./provider.mjs")]),
  ("specifiers", toJson [importSpecifier name]), ("attributes", toJson ([] : List Json))]

/-- The synthetic named import decodes without parser-added scope annotations. -/
theorem import_decl : CoreJS.ModuleInput.importDecl "entry.mjs" (importDecl "x") =
    .ok ⟨"provider.mjs", [("x", "x")]⟩ := by cbv

/-- The generated export specifier names the same local binding. -/
theorem export_spec :
    CoreJS.FromESTree.exportSpec (exportSpecifier "x") = .ok ("x", "x") := by cbv

#print axioms import_decl
#print axioms export_spec

end EsmSplit.LowerSplit.TerminalConstDecoder
