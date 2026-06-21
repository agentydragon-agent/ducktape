"""Convert a glTF/glb scene into a binary STL mesh.

Pure Python 3 (stdlib only) -- no FreeCAD, no numpy. Import the resulting STL
into FreeCAD (File -> Import) or any mesh tool yourself.

    GLB_IN=in.glb STL_OUT=out.stl python3 glb_to_stl.py

Environment variables:
    GLB_IN    (required) decompressed glb to read
    STL_OUT   (required) STL path to write
    SCALE     (default 1000) glb-units -> mm; glTF is meters, FreeCAD is mm
    OBJ_NAME  (default "model") written into the 80-byte STL header

The input glb must NOT be Draco-compressed -- this parser reads only
uncompressed buffers. Decode Draco first with:

    pnpm dlx @gltf-transform/cli copy in.glb decompressed.glb

The glb_to_stl.sh wrapper in this skill does the decode + this step in one.

Walks the default scene's node hierarchy, applies each node's TRS/matrix
transform, triangulates POSITION+indices, and writes one binary STL.
"""

import base64
import json
import math
import os
import struct
from pathlib import Path

GLB = os.environ["GLB_IN"]
OUT_STL = os.environ["STL_OUT"]
# glTF is in meters; FreeCAD documents default to millimeters. 1000 keeps
# furniture furniture-sized instead of under a millimeter tall at the origin.
SCALE = float(os.environ.get("SCALE", "1000"))
OBJ_NAME = os.environ.get("OBJ_NAME", "model")

data = Path(GLB).read_bytes()
assert data[:4] == b"glTF", "not a glb"
ver, length = struct.unpack_from("<II", data, 4)
off = 12
chunks = {}
while off < length:
    clen, ctype = struct.unpack_from("<II", data, off)
    off += 8
    chunks[ctype] = data[off : off + clen]
    off += clen
gltf = json.loads(chunks[0x4E4F534A].decode("utf-8"))
BIN = chunks.get(0x004E4942, b"")

bufs = []
for b in gltf.get("buffers", []):
    uri = b.get("uri")
    if uri is None:
        bufs.append(BIN)
    elif uri.startswith("data:"):
        bufs.append(base64.b64decode(uri.split(",", 1)[1]))
    else:
        bufs.append((Path(GLB).parent / uri).read_bytes())

CT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_accessor(idx):
    a = gltf["accessors"][idx]
    bv = gltf["bufferViews"][a["bufferView"]]
    buf = bufs[bv["buffer"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    fmt, sz = CT[a["componentType"]]
    nc = NC[a["type"]]
    stride = bv.get("byteStride") or (sz * nc)
    out = []
    for i in range(a["count"]):
        vals = struct.unpack_from("<" + fmt * nc, buf, base + i * stride)
        out.append(vals if nc > 1 else vals[0])
    return out


def mat_mul(a, b):
    r = [0.0] * 16
    for i in range(4):
        for j in range(4):
            r[i * 4 + j] = sum(a[i * 4 + k] * b[k * 4 + j] for k in range(4))
    return r


def trs_matrix(node):
    if "matrix" in node:
        m = node["matrix"]  # column-major in glTF
        return [m[0], m[4], m[8], m[12], m[1], m[5], m[9], m[13], m[2], m[6], m[10], m[14], m[3], m[7], m[11], m[15]]
    trans = node.get("translation", [0, 0, 0])
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    sx, sy, sz = node.get("scale", [1, 1, 1])
    rm = [
        1 - 2 * (y * y + z * z),
        2 * (x * y - z * w),
        2 * (x * z + y * w),
        2 * (x * y + z * w),
        1 - 2 * (x * x + z * z),
        2 * (y * z - x * w),
        2 * (x * z - y * w),
        2 * (y * z + x * w),
        1 - 2 * (x * x + y * y),
    ]
    return [
        rm[0] * sx,
        rm[1] * sy,
        rm[2] * sz,
        trans[0],
        rm[3] * sx,
        rm[4] * sy,
        rm[5] * sz,
        trans[1],
        rm[6] * sx,
        rm[7] * sy,
        rm[8] * sz,
        trans[2],
        0,
        0,
        0,
        1,
    ]


def apply(m, p):
    x, y, z = p
    return (
        (m[0] * x + m[1] * y + m[2] * z + m[3]) * SCALE,
        (m[4] * x + m[5] * y + m[6] * z + m[7]) * SCALE,
        (m[8] * x + m[9] * y + m[10] * z + m[11]) * SCALE,
    )


facets = []


def walk(ni, parent):
    node = gltf["nodes"][ni]
    mat = mat_mul(parent, trs_matrix(node))
    if "mesh" in node:
        for prim in gltf["meshes"][node["mesh"]]["primitives"]:
            if prim.get("mode", 4) != 4:  # only plain triangles
                continue
            pos = read_accessor(prim["attributes"]["POSITION"])
            idx = read_accessor(prim["indices"]) if "indices" in prim else list(range(len(pos)))
            facets.extend(
                (apply(mat, pos[idx[t]]), apply(mat, pos[idx[t + 1]]), apply(mat, pos[idx[t + 2]]))
                for t in range(0, len(idx), 3)
            )
    for ch in node.get("children", []):
        walk(ch, mat)


IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
for ni in gltf["scenes"][gltf.get("scene", 0)]["nodes"]:
    walk(ni, IDENTITY)


def normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    n = math.sqrt(nx * nx + ny * ny + nz * nz)
    return (nx / n, ny / n, nz / n) if n else (0.0, 0.0, 0.0)


print("FACETS:", len(facets))
if facets:
    xs = [v[0] for f in facets for v in f]
    ys = [v[1] for f in facets for v in f]
    zs = [v[2] for f in facets for v in f]
    print("BBOX_XYZ:", round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3), round(max(zs) - min(zs), 3))

# Binary STL: 80-byte header, uint32 triangle count, then per triangle
# 12 little-endian floats (normal + 3 vertices) + uint16 attribute (0).
with Path(OUT_STL).open("wb") as f:
    f.write(OBJ_NAME.encode("ascii", "replace")[:80].ljust(80, b"\0"))
    f.write(struct.pack("<I", len(facets)))
    for a, b, c in facets:
        f.write(struct.pack("<3f", *normal(a, b, c)))
        f.write(struct.pack("<9f", *a, *b, *c))
        f.write(struct.pack("<H", 0))
print("WROTE_OK")
