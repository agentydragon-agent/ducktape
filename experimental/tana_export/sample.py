import json
import pathlib
from pathlib import Path
from textwrap import indent

path = pathlib.Path("/home/agentydragon/downloads/tana-export-2025-05-12.json")

with open(path) as file:
    data = json.load(file)


def show(x, i=0):
    print(indent(json.dumps(x, indent=2), "  " * i))


def by_id(id):
    return next(d for d in docs if d["id"] == id)


docs = data["docs"]
print("Supertags:")
print("System main supertag:")
show(by_id("SYS_T01"), 1)
print("#issue supertag:")
show(next(d for d in docs if d["props"].get("name") == "issue"), 1)
print("  Reference rendering of node 'xTcTNuPqb8':")
print("    Tana Paste:")
print(indent(Path("references/xTcTNuPqb8.tanapaste").read_text(), "      "))


print()
print()
print("Done on <datetime tag> tuple:")
t = "YOy0EnzmlULs"
show(by_id(t))

print()
print()
for c in set(by_id(t)["children"]) - {"4qgC_YWmtZBu", "YOy0EnzmlULs"}:
    show(by_id(c))

print()
print()
print("Tuple node:")
for child in ["OU6JjVPuPWqF"]:
    show(by_id(child))
    for c in by_id(child)["children"]:
        show(by_id(c))
print(
    "note this tuple node has *MULTIPLE* values -- corresponds to multiple assigned Hotlists, see the corresponding Tnaa Paste/Markdown",
)

print()
print()
show(by_id("UCeHxMVoBf"))
show(by_id("Of9-D47GEA"))

print()
print()
print(
    "The 'supertags for node' supertag - want to have values associated with this key for a tagged node exposed for easy access:",
)
show(by_id("SYS_A13"), 1)
show(by_id("SYS_TA05_02"))
show(by_id("SYS_TA05_03"))
show(by_id("SYS_T04"))

# 'Eecrise', has a bunchas checkboxes
print(
    "Checkboxes rendergin - please appropriately expose for convenience of spoecial rendering:",
)
show(by_id("9dCT4NlSzKqw"))
show(by_id("aAYRhJM5eKJI"))
show(by_id("br8KnsKD2KLW"))
show(by_id("aImXbMWXT9MS"))
show(by_id("SYS_A55"))
show(by_id("SYS_V03"))
show(by_id("SYS_V04"))
show(by_id("SYS_0"))
print("9dCT4NlSzKqw would render like this with all checkboxes unchecked:")
print(indent(Path("references/empty-checkboxes.tanapaste").read_text(), "  "))
print("- [ ] for unchecked, - [x] for checked.")
print("And Markdown:")
print(indent(Path("references/empty-checkboxes.markdown").read_text(), "  "))

print()
print(
    "Tana JSON dump is a JSON file with .docs[] array which contains these objects. Try to read them all. If any can't be parsed, print out its ID and the node itself.",
)
print()
print(
    "nodes with owner like uA_iLd0SUk_TRASH => is in trash, mark with some marker bool.",
)

# TODO: checkbox
# TODO: URL link

# SYS_V118 = external calendar
# SYS_A202 = "Node source"
# is SYS_A202=SYS_V118, it's an event from external calendar => would be
# good to drop if not used for other things


print()
print()
print()
print()
print(indent(Path("references/day.tanapaste").read_text(), "  "))
print(indent(Path("references/day.md").read_text(), "  "))
show(by_id("h5zrlU6cl8PM"))
show(by_id("pRR9C80rEI-8"))
