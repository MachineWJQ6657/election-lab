// Read-only post-deployment check. Does not authenticate, deploy, or change DNS.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

export function inspectPublishedHtml(html, expectedSnapshot) {
  const snapshot = html.match(/data-snapshot-id="([a-f0-9]{64})"/)?.[1];
  assert.equal(snapshot, expectedSnapshot, "Published forecast snapshot differs from local snapshot");
  assert.match(html, /id="election-map"/, "Published page does not contain the election map");
  const states = [...html.matchAll(/data-state="([A-Z]{2})"/g)].map((m) => m[1]);
  assert.equal(states.length, 51, "Expected 50 states plus DC on the initial map");
  assert.equal(new Set(states).size, 51, "Map contains duplicate state keys");
  assert.match(html, /<title>2026 Senate forecast map<\/title>/, "Missing initial map title");
  const seats=html.match(/data-seat-summary="senate" data-total-seats="(\d+)" data-dem-seats="([\d.]+)" data-rep-seats="([\d.]+)"/);
  assert.ok(seats,"Missing map final seat comparison");
  assert.equal(Number(seats[1]),100,"Senate summary does not include all 100 seats");
  assert.equal(Number(seats[2])+Number(seats[3]),100,"Seat comparison does not sum to 100");
  const assets = [...new Set([...html.matchAll(/(?:src|href)="(\/_next\/static\/[^"?#]+\.(?:js|css))"/g)].map((m) => m[1]))];
  assert.ok(assets.some((a) => a.endsWith(".js")), "No JavaScript build assets found");
  assert.ok(assets.some((a) => a.endsWith(".css")), "No stylesheet build assets found");
  return { snapshot_id: snapshot, map_states: states.length, senate_projection: {dem:Number(seats[2]),rep:Number(seats[3]),total:100}, assets };
}

export async function verifyPublication(origin, expectedSnapshot, request = fetch) {
  const target = new URL(origin);
  assert.equal(target.protocol, "https:", "Publication verification requires HTTPS");
  assert.ok(!target.username && !target.password && !target.search && !target.hash, "Use a plain public origin, without credentials or query strings");
  const page = await request(new URL("/", target), { signal: AbortSignal.timeout(20000), cache: "no-store" });
  assert.equal(page.status, 200, "Published page is not HTTP 200");
  assert.equal(new URL(page.url).origin, target.origin, "Public domain redirected to another origin");
  assert.match(page.headers.get("content-type") ?? "", /text\/html/i);
  const result = inspectPublishedHtml(await page.text(), expectedSnapshot);
  // Inspect all referenced build assets, not just HTML served by a stale worker.
  for (let i = 0; i < result.assets.length; i += 4) {
    await Promise.all(result.assets.slice(i, i + 4).map(async (path) => {
      const response = await request(new URL(path, target), { signal: AbortSignal.timeout(20000), cache: "no-store" });
      assert.equal(response.status, 200, `Build asset unavailable: ${path}`);
      assert.match(response.headers.get("content-type") ?? "", path.endsWith(".css") ? /text\/css/i : /javascript/i, `Wrong build asset content type: ${path}`);
      assert.ok((await response.arrayBuffer()).byteLength > 0, `Empty build asset: ${path}`);
    }));
  }
  return { verified_at: new Date().toISOString(), origin: target.origin, http_status: 200, snapshot_id: result.snapshot_id, map_states: result.map_states, senate_projection: result.senate_projection, assets_verified: result.assets.length };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const data = JSON.parse(await readFile(new URL("../lib/forecast-data.json", import.meta.url), "utf8"));
    console.log(JSON.stringify(await verifyPublication(process.argv[2] ?? "https://forecast.idontknowanythingowo.cc", data.snapshot_id), null, 2));
  } catch (error) {
    console.error(`Publication verification failed: ${error.message}`);
    process.exitCode = 1;
  }
}
