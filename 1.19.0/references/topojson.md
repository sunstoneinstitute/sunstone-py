> Source: TopoJSON specification — https://github.com/topojson/topojson-specification

# TopoJSON Reference (for implementers)

Agent-oriented spec for implementing TopoJSON **decode** (topology → GeoJSON-like features) and **encode** (features → topology).

## Core concept (vs GeoJSON)

- GeoJSON embeds coordinates directly in every geometry.
- TopoJSON factors all shared line segments into one top-level **`arcs`** array. Line/polygon geometries reference arcs **by integer index** instead of embedding coordinates. Shared boundaries between adjacent shapes reference the same arc once → no coordinate duplication.
- Point/MultiPoint still embed coordinates directly (no arcs).
- TopoJSON has **no Feature object**: feature-level data (`properties`, `id`) lives on geometry objects.
- Coordinate order: x, y, z = (longitude, latitude, altitude) for geographic / (easting, northing, altitude) for projected. Same CRS expectations as GeoJSON (default WGS84).

## Top-level Topology object

| Member | Req | Value |
|---|---|---|
| `type` | MUST | `"Topology"` |
| `objects` | MUST | object: map of name → geometry object (usually GeometryCollection) |
| `arcs` | MUST | array of arcs; each arc = array of **≥2 positions** |
| `transform` | optional | quantization transform (see below) |
| `bbox` | optional | bounding box |

- `objects` is the named map; e.g. `objects.counties`, `objects.states`. Each value is a geometry object.
- `bbox`: `2*n` array `[minX, minY, ..., maxX, maxY, ...]` (n = dimensions): all min axes then all max axes. **MUST NOT** be transformed by the topology's transform (bbox values are absolute).

## Geometry objects

Types: `Point`, `MultiPoint`, `LineString`, `MultiLineString`, `Polygon`, `MultiPolygon`, `GeometryCollection`. A geometry with `type: null` (or no coordinates/arcs) represents a null geometry.

Every geometry object MAY have: `properties` (JSON object or null), `id`, `bbox`.

Coordinate vs arc reference, and exact nesting:

| Type | Member | Shape | Example |
|---|---|---|---|
| Point | `coordinates` | one position | `[x, y]` |
| MultiPoint | `coordinates` | array of positions | `[[x,y], [x,y]]` |
| LineString | `arcs` | array of arc indexes | `[0, 1, -2]` |
| MultiLineString | `arcs` | array of (array of arc indexes) | `[[0,1], [2]]` |
| Polygon | `arcs` | array of rings; ring = array of arc indexes | `[[0,1,2], [3]]` |
| MultiPolygon | `arcs` | array of polygons (one level deeper) | `[[[0,1]], [[2,3]]]` |
| GeometryCollection | `geometries` | array of geometry objects | — |

- Polygon `arcs`: first ring = exterior, rest = holes (interior).
- A LinearRing is a closed LineString with ≥4 positions; first == last after stitching.

## Arc indexing semantics

- An arc index is an integer into the top-level `arcs` array.
- **Negative index** means the arc is **reversed**. Index `~i` (i.e. `-i - 1`) refers to arc `i` reversed: `-1`→arc 0 reversed, `-2`→arc 1 reversed, `-3`→arc 2 reversed, …
- Dereference: if index `idx >= 0` use `arcs[idx]` as-is; else use `arcs[~idx]` reversed, where `~idx == -idx - 1`.

```
def deref(arcs, idx):
    if idx >= 0: return arcs[idx]
    else:        return reversed(arcs[~idx])   # ~idx = -idx - 1
```

## Arcs array + stitching (de-duplication rule)

- Each arc is an array of ≥2 positions.
- When a line/ring is built from multiple arcs, **the first position of each subsequent arc MUST equal the last position of the previous arc** (arcs overlap by one shared endpoint).
- On reconstruction, drop the duplicate: the first position of each arc **except the first** is dropped (equivalently, last of each arc except the last). Concatenate the rest.

```
def stitch(arc_indexes, arcs):
    line = []
    for k, idx in enumerate(arc_indexes):
        pts = deref(arcs, idx)
        if k > 0: pts = pts[1:]   # drop shared first point
        line.extend(pts)
    return line
```

## Transform (quantization + delta-encoding)

Present only when coordinates are quantized. If absent, **all arc positions are absolute floats and NOT delta-encoded**.

```json
"transform": { "scale": [sx, sy], "translate": [tx, ty] }
```

When `transform` is present:
- Every quantized position's first two elements MUST be **integers**.
- Within each arc, positions are **delta-encoded**: position[0] is absolute (integer); each later position stores the delta from the previous: `xₖ = xₖ₋₁ + Δxₖ`, `yₖ = yₖ₋₁ + Δyₖ`.

**Decode (quantized integer deltas → absolute float coordinate)** — per arc, accumulate deltas then apply scale/translate:

```js
function decodeArc(transform, arc) {
  let x = 0, y = 0;
  return arc.map(p => {
    x += p[0]; y += p[1];                       // delta-decode
    return [ x * transform.scale[0] + transform.translate[0],
             y * transform.scale[1] + transform.translate[1] ];
  });
}
```

**Encode (absolute float → quantized integer deltas)** — inverse, per arc:

```
prevX = prevY = 0
for each position [X, Y] in arc:           # X,Y absolute floats
    qx = round((X - translate[0]) / scale[0])   # quantized integer
    qy = round((Y - translate[1]) / scale[1])
    emit [qx - prevX, qy - prevY]               # delta
    prevX, prevY = qx, qy
```

Note: `transform` affects only positions inside `arcs` and `coordinates`; it does NOT affect `bbox`.

## Decode algorithm (Topology → features)

1. For each arc in `topology.arcs`: if `transform` present, run `decodeArc` (delta-decode + scale/translate) to get absolute positions; else use positions as-is. Cache decoded arcs.
2. For each named object in `topology.objects`, recursively convert each geometry:
   - **Point/MultiPoint**: take `coordinates`; if `transform` present, decode each position absolutely (`x*scale+translate`) — Point/MultiPoint coords are quantized but NOT delta-encoded across points; each is standalone integer scaled directly.
   - **LineString**: `stitch(geom.arcs, decodedArcs)`.
   - **MultiLineString**: stitch each sub-array → list of lines.
   - **Polygon**: stitch each ring → list of rings (ensure closed).
   - **MultiPolygon**: one level deeper.
   - **GeometryCollection**: recurse into `geometries`.
3. Carry `properties` and `id` onto the resulting GeoJSON Feature.

## Encode algorithm (features → Topology)

1. Extract all line segments (LineString/ring sequences) from input geometries.
2. Cut/merge shared sequences into **arcs**; arrange so consecutive arcs in a line/ring share endpoints (last of one == first of next). Build geometry `arcs` index arrays; use negative indexes (`~i`) where an arc is traversed in reverse.
3. (Optional) Choose a quantization grid; compute `scale`/`translate` so that `q = round((coord - translate)/scale)` maps coordinates to integers; set `transform`.
4. For each arc, quantize positions, then **delta-encode** (store first position absolute, then successive deltas).
5. Assemble `{ type: "Topology", transform?, bbox?, objects, arcs }`. Move feature `properties`/`id` onto geometry objects.

## Complete example (with transform)

```json
{
  "type": "Topology",
  "transform": {
    "scale": [0.0005000500050005, 0.00010001000100010001],
    "translate": [100, 0]
  },
  "objects": {
    "example": {
      "type": "GeometryCollection",
      "geometries": [
        { "type": "Point", "properties": {"prop0": "value0"}, "coordinates": [4000, 5000] },
        { "type": "LineString", "properties": {"prop0": "value0", "prop1": 0}, "arcs": [0] },
        { "type": "Polygon", "properties": {"prop0": "value0", "prop1": {"this": "that"}}, "arcs": [[1]] }
      ]
    }
  },
  "arcs": [
    [[4000, 0], [1999, 9999], [2000, -9999], [2000, 9999]],
    [[0, 0], [0, 9999], [2000, 0], [0, -9999], [-2000, 0]]
  ]
}
```

Arc 0 first position `[4000,0]` is absolute (integer); `[1999,9999]` etc. are deltas. Decode via `decodeArc` to recover absolute lon/lat.
