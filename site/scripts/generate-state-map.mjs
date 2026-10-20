// Development-only conversion. No remote map requests are made by the website.
import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";

const source = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-albers-10m.json";
const codes = Object.fromEntries(`01 AL,02 AK,04 AZ,05 AR,06 CA,08 CO,09 CT,10 DE,11 DC,12 FL,13 GA,15 HI,16 ID,17 IL,18 IN,19 IA,20 KS,21 KY,22 LA,23 ME,24 MD,25 MA,26 MI,27 MN,28 MS,29 MO,30 MT,31 NE,32 NV,33 NH,34 NJ,35 NM,36 NY,37 NC,38 ND,39 OH,40 OK,41 OR,42 PA,44 RI,45 SC,46 SD,47 TN,48 TX,49 UT,50 VT,51 VA,53 WA,54 WV,55 WI,56 WY`.split(",").map((s) => s.trim().split(" ")));
const response = await fetch(source);
if (!response.ok) throw new Error(`Map download failed: ${response.status}`);
const bytes = Buffer.from(await response.arrayBuffer());
const topology = JSON.parse(bytes);
if (topology.type !== "Topology" || !topology.transform || !topology.objects.states) throw new Error("Unexpected atlas schema");
const arcs = topology.arcs.map((arc) => {
  let x = 0, y = 0;
  return arc.map(([dx, dy]) => {
    x += dx; y += dy;
    return [x * topology.transform.scale[0] + topology.transform.translate[0], y * topology.transform.scale[1] + topology.transform.translate[1]];
  });
});
const ring = (ids) => ids.flatMap((id, i) => {
  const points = id < 0 ? [...arcs[~id]].reverse() : arcs[id];
  return i ? points.slice(1) : points;
});
function centroid(points) {
  let area = 0, x = 0, y = 0;
  for (let i = 0; i < points.length; i++) {
    const a = points[i], b = points[(i + 1) % points.length];
    const cross = a[0] * b[1] - b[0] * a[1];
    area += cross; x += (a[0] + b[0]) * cross; y += (a[1] + b[1]) * cross;
  }
  return { area: Math.abs(area), point: [x / (3 * area), y / (3 * area)] };
}
const round = (v) => Math.round(v * 10) / 10;
const states = topology.objects.states.geometries.filter((g) => codes[g.id]).map((g) => {
  if (!["Polygon", "MultiPolygon"].includes(g.type)) throw new Error(`Unexpected geometry: ${g.type}`);
  const polygons = g.type === "Polygon" ? [g.arcs] : g.arcs;
  const rings = polygons.flatMap((polygon) => polygon.map(ring));
  const largest = polygons.map((polygon) => centroid(ring(polygon[0]))).sort((a, b) => b.area - a.area)[0];
  const path = rings.map((points) => points.map(([x, y], i) => `${i ? "L" : "M"}${round(x)},${round(y)}`).join("") + "Z").join("");
  if (!path || largest.point.some((v) => !Number.isFinite(v))) throw new Error(`Invalid path: ${g.id}`);
  return { code: codes[g.id], name: g.properties.name, fips: g.id, path, label: largest.point.map(round) };
}).sort((a, b) => a.code.localeCompare(b.code));
if (states.length !== 51) throw new Error(`Expected 50 states plus DC, got ${states.length}`);
await writeFile(new URL("../lib/us-state-paths.json", import.meta.url), JSON.stringify({
  source, source_sha256: createHash("sha256").update(bytes).digest("hex"),
  atlas_version: "3.0.1", boundary_vintage: "2017 state cartographic boundaries; not congressional districts",
  projection: "Albers USA; Alaska and Hawaii inset", viewBox: "0 0 1070 610", states,
}, null, 2) + "\n");
const licenseResponse = await fetch("https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/LICENSE");
if (!licenseResponse.ok) throw new Error("License download failed");
await writeFile(new URL("../public/us-atlas-LICENSE.txt", import.meta.url), await licenseResponse.text());
console.log(`Generated ${states.length} state SVG paths; no runtime map dependency.`);
