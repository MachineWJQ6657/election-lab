import assert from "node:assert/strict";
import test from "node:test";
import { inspectPublishedHtml, verifyPublication } from "../scripts/verify-publication.mjs";

const snapshot = "a".repeat(64);
const states = Array.from({length:51}, (_, i) => `data-state="${String.fromCharCode(65 + Math.floor(i / 26))}${String.fromCharCode(65 + i % 26)}"`).join(" ");
const html = `<main data-snapshot-id="${snapshot}"><section id="election-map" data-map-rating-scale="solid-likely-lean-tilt"><div data-seat-summary="senate" data-total-seats="100" data-dem-seats="52" data-rep-seats="48"><span data-seat-band="solid-d" data-seat-count="52"></span><span data-seat-band="solid-r" data-seat-count="48"></span></div><title>2026 Senate forecast map</title>${states}</section></main><script src="/_next/static/app.js"></script><link href="/_next/static/app.css" rel="stylesheet">`;
const origin = "https://forecast.example";
const response = (body, type, url, status = 200) => ({ status, url, headers: new Headers({"content-type":type}), text: async () => body, arrayBuffer: async () => new TextEncoder().encode(body).buffer });
const request = async (url) => url.pathname === "/" ? response(html,"text/html",origin) : response("content",url.pathname.endsWith("css") ? "text/css" : "text/javascript",url.href);

test("publication check rejects old snapshot, missing map and duplicate states", () => {
  assert.equal(inspectPublishedHtml(html,snapshot).map_states,51);
  assert.throws(()=>inspectPublishedHtml(html,"b".repeat(64)),/snapshot differs/);
  assert.throws(()=>inspectPublishedHtml(html.replace('id="election-map"','id="old-map"'),snapshot),/does not contain/);
  assert.throws(()=>inspectPublishedHtml(html.replace('data-state="AB"','data-state="AA"'),snapshot),/duplicate state/);
  assert.throws(()=>inspectPublishedHtml(html.replace('data-seat-summary="senate"','data-seat-summary="old"'),snapshot),/Missing map final seat/);
  assert.throws(()=>inspectPublishedHtml(html.replace('data-map-rating-scale="solid-likely-lean-tilt"',''),snapshot),/missing the named rating/);
  assert.throws(()=>inspectPublishedHtml(html.replace('data-seat-count="48"','data-seat-count="15"'),snapshot),/incomplete segmented/);
  assert.throws(()=>inspectPublishedHtml(html.replace('data-rep-seats="48"','data-rep-seats="15"'),snapshot),/does not sum/);
});
test("publication check verifies the public origin and every JS/CSS asset", async () => {
  const result = await verifyPublication(origin,snapshot,request);
  assert.equal(result.http_status,200);
  assert.equal(result.assets_verified,2);
  assert.equal(result.snapshot_id,snapshot);
  assert.deepEqual(result.senate_projection,{dem:52,rep:48,total:100});
});
test("publication check rejects wrong redirects, broken assets and HTML fallbacks", async () => {
  await assert.rejects(verifyPublication(origin,snapshot,async()=>response(html,"text/html","https://other.example")),/redirected/);
  await assert.rejects(verifyPublication(origin,snapshot,async(url)=>url.pathname==="/" ? request(url) : response("missing","text/plain",url.href,404)),/asset unavailable/);
  await assert.rejects(verifyPublication(origin,snapshot,async(url)=>url.pathname==="/" ? request(url) : response(html,"text/html",url.href)),/content type/);
});
