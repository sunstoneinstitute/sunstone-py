# GeoJSON Reference (RFC 7946)

Source: RFC 7946, IETF — https://datatracker.ietf.org/doc/html/rfc7946
Agent-oriented spec for implementing/validating GeoJSON read/write.

## Core rules

- Every GeoJSON object MUST have a `"type"` member.
- `"type"` values are **case-sensitive** and exact (e.g. `Point`, not `point`).
- Valid `"type"` values: `Point`, `MultiPoint`, `LineString`, `MultiLineString`, `Polygon`, `MultiPolygon`, `GeometryCollection`, `Feature`, `FeatureCollection`.
- Three top-level kinds: **Geometry** (7 types), **Feature**, **FeatureCollection**.

## CRS / coordinate system

- CRS is **fixed to WGS 84**, equivalent to `urn:ogc:def:crs:OGC::CRS84`. No CRS member exists.
- Units: **decimal degrees**. Order is **longitude, latitude, [altitude]** = **(x, y, z)**.
- COMMON BUG: lon comes first, not lat.
- The legacy GeoJSON-2008 `"crs"` member is **removed** by RFC 7946. Do not emit it; assume WGS84 on read.

## Position

- A position is an array of numbers.
- MUST have **two or more** elements: `[lon, lat]` or `[lon, lat, altitude]`.
- 3rd element (optional) = height in meters above/below WGS84 ellipsoid.
- Implementations SHOULD NOT use more than 3 elements (extras are undefined).
- Latitude MUST be in [-90, 90]; values outside MUST NOT be used to imply non-spherical-cap extent.

## Geometry types — `"coordinates"` nesting

Required members per geometry: `"type"` + `"coordinates"` (except GeometryCollection, which uses `"geometries"`).

| Type | coordinates structure | constraints |
|------|----------------------|-------------|
| Point | position | single `[lon,lat]` |
| MultiPoint | array of positions | |
| LineString | array of positions | **>= 2** positions |
| MultiLineString | array of LineString coords | each line >= 2 positions |
| Polygon | array of linear rings | ring[0] = exterior, rest = holes |
| MultiPolygon | array of Polygon coords | |
| GeometryCollection | (uses `"geometries"`: array of Geometry objects) | array may be empty |

Nesting depth of `coordinates`: Point=1, MultiPoint/LineString=2, MultiLineString/Polygon=3, MultiPolygon=4.

```json
{"type":"Point","coordinates":[100.0,0.0]}
{"type":"MultiPoint","coordinates":[[100.0,0.0],[101.0,1.0]]}
{"type":"LineString","coordinates":[[100.0,0.0],[101.0,1.0]]}
{"type":"MultiLineString","coordinates":[[[100.0,0.0],[101.0,1.0]],[[102.0,2.0],[103.0,3.0]]]}
{"type":"Polygon","coordinates":[[[100.0,0.0],[101.0,0.0],[101.0,1.0],[100.0,1.0],[100.0,0.0]]]}
{"type":"MultiPolygon","coordinates":[[[[100.0,0.0],[101.0,0.0],[101.0,1.0],[100.0,0.0]]]]}
{"type":"GeometryCollection","geometries":[{"type":"Point","coordinates":[100.0,0.0]}]}
```

## Linear rings (Polygon / MultiPolygon)

- A linear ring is a **closed** LineString with **four or more** positions.
- First and last positions MUST be identical values (representation SHOULD also be identical).
- Right-hand rule: ring MUST follow it w.r.t. the area it bounds — **exterior ring counterclockwise, holes clockwise**.
- Backward compat: parsers SHOULD NOT reject Polygons that violate the right-hand rule.

## Feature

Required members:
- `"type": "Feature"`
- `"geometry"`: a Geometry object **or JSON `null`** (null = unlocated feature).
- `"properties"`: a JSON object **or JSON `null`**.

Optional:
- `"id"`: a JSON **string or number**.

```json
{"type":"Feature","id":"x1","geometry":{"type":"Point","coordinates":[100.0,0.0]},"properties":{"name":"A"}}
```

## FeatureCollection

Required members:
- `"type": "FeatureCollection"`
- `"features"`: a JSON array of Feature objects (MAY be empty).

```json
{"type":"FeatureCollection","features":[]}
```

## bbox

- Any GeoJSON object MAY have a `"bbox"` member.
- Value is an array of length **2*n** (n = number of dimensions, usually 2 → length 4, or 3 → length 6).
- Order: **all axes of the southwesterly-most point first, then all axes of the northeasterly-most point**, same axis order as positions (lon, lat, [alt]).
- 2D example: `[west, south, east, north]`.
- Antimeridian-crossing bbox: the northeast longitude is **less than** the southwest longitude, e.g. Fiji `[177.0,-20.0,-178.0,-16.0]`.
- Pole caps: North `[-180.0, minlat, 180.0, 90.0]`; South `[-180.0, -90.0, 180.0, maxlat]`.

## Foreign members

- Any GeoJSON object MAY carry additional ("foreign") members beyond those in the spec.
- GeoJSON semantics do NOT apply to foreign members or their descendants; no normative processing model; support varies — interoperability caveat.
- Feature / FeatureCollection / Geometry MUST NOT contain the defining members of another type. In particular a FeatureCollection MUST NOT carry `"geometry"`, `"properties"`, or `"coordinates"` with their GeoJSON meaning.

## Antimeridian & poles

- Any geometry crossing the antimeridian (180° lon) SHOULD be cut in two so neither part crosses it (line → MultiLineString; polygon → MultiPolygon).
- Regions touching a pole: represent as a spherical cap; do not abuse latitude values to imply otherwise (see bbox pole forms above).

## Precision

- Implementations SHOULD weigh the cost of excess precision; ~6 decimal places ≈ 10 cm, enough for most uses. Excess precision inflates size.

## Validation checklist (MUST rules)

- [ ] `"type"` present, exact-case, one of the 9 valid values.
- [ ] Geometry has `"coordinates"` (or `"geometries"` for GeometryCollection).
- [ ] Position arrays have >= 2 numbers; coordinate order is lon, lat, [alt].
- [ ] LineString >= 2 positions.
- [ ] Each Polygon ring: closed (first == last), >= 4 positions.
- [ ] Latitude within [-90, 90].
- [ ] bbox length == 2*n; SW axes before NE axes.
- [ ] Feature has `"type":"Feature"`, `"geometry"` (object or null), `"properties"` (object or null); `"id"` if present is string/number.
- [ ] FeatureCollection has `"type":"FeatureCollection"` and a `"features"` array of Features.
- [ ] FeatureCollection does NOT carry GeoJSON `"geometry"`/`"properties"`/`"coordinates"`.
- [ ] No `"crs"` member emitted (RFC 7946 forbids it).
