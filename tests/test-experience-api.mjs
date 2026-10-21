import { randomUUID } from "node:crypto";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire, Module } from "node:module";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const output = mkdtempSync(join(tmpdir(), "fourseas-api-test-"));
const require = createRequire(import.meta.url);
const { Pool } = require(join(root, "web/node_modules/pg"));
const pool = new Pool({ connectionString: process.env.TEST_DATABASE_URL });
globalThis.pool = pool;
const resolve = Module._resolveFilename;
Module._resolveFilename = function(specifier, ...args) {
  if (specifier.startsWith("@/")) return join(output, specifier.slice(2) + ".js");
  if (specifier === "pg") return require.resolve(join(root, "web/node_modules/pg"));
  return resolve.call(this, specifier, ...args);
};
function request(path, method = "GET", body, origin = "http://localhost:3000") {
  return new Request("http://localhost:3000" + path, { method,
    headers: { host: "localhost:3000", origin, "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
}
const context = id => ({ params: Promise.resolve({ id }) });
try {
  const config = join(output, "tsconfig.json");
  writeFileSync(config, JSON.stringify({
    compilerOptions: { target: "ES2022", module: "Node16", moduleResolution: "node16",
      esModuleInterop: true, skipLibCheck: true, strict: true,
      rootDir: join(root, "web"), outDir: output,
      paths: { "@/*": [join(root, "web/*")] } },
    files: ["app/api/experiences/route.ts", "app/api/experiences/[id]/route.ts"]
      .map(p => join(root, "web", p))
  }));
  execFileSync(join(root, "web/node_modules/.bin/tsc"), ["-p", config], { stdio: "inherit" });
  const list = require(join(output, "app/api/experiences/route.js"));
  const detail = require(join(output, "app/api/experiences/[id]/route.js"));
  assert.equal((await list.POST(request("/api/experiences", "POST", { name: "   " }))).status, 400);
  assert.equal((await list.POST(request("/api/experiences", "POST", { name: "x".repeat(61) }))).status, 400);
  assert.equal((await list.POST(request("/api/experiences", "POST", { name: "测试" }, "http://untrusted.example"))).status, 403);
  const clientA = randomUUID(), clientB = randomUUID(), clientC = randomUUID();
  await pool.query("INSERT INTO sources (id,name,kind,metric,unit) VALUES ('api:band-a','手环 A','ble_heart_rate','heart_rate','bpm'),('api:band-b','手环 B','ble_heart_rate','heart_rate','bpm')");
  const start = (name, client_id, heart_source_id) => list.POST(request("/api/experiences", "POST", { name, client_id, heart_source_id }));
  await pool.query("UPDATE sources SET last_seen=now()-interval '2 minutes',status='waiting' WHERE id='api:band-a'");
  assert.equal((await start("失联手环",clientC,"api:band-a")).status,409,"stale status cannot start an experience");
  await pool.query("UPDATE sources SET last_seen=now() WHERE id='api:band-a'");
  const started = await Promise.all([start("体验者 1",clientA,"api:band-a"),start("体验者 2",clientB,"api:band-a")]);
  assert.deepEqual(started.map(r => r.status).sort(), [201, 409], "one band cannot belong to two active participants");
  const first = await started.find(r => r.status === 201).json();
  const otherClient = first.client_id === clientA ? clientB : clientA;
  const secondResponse = await start("第二位体验者",otherClient,"api:band-b");
  assert.equal(secondResponse.status, 201, "different bands run concurrently");
  const second = await secondResponse.json();
  assert.equal((await start("重试",first.client_id,"api:band-a")).status,200);
  assert.equal((await (await start("重试",first.client_id,"api:band-a")).json()).id,first.id,"start is idempotent for this client");
  const end = (id, client_id) => detail.PATCH(request("", "PATCH", { client_id }), context(id));
  assert.equal((await end(first.id,clientC)).status,404,"another client cannot end this experience");
  const ended = await end(first.id,first.client_id);
  assert.equal(ended.status,200);
  const endedAt = (await ended.json()).ended_at;
  assert.equal((await (await end(first.id,first.client_id)).json()).ended_at,endedAt);
  assert.equal((await pool.query("SELECT ended_at FROM experiences WHERE id=$1",[second.id])).rows[0].ended_at,null,"ending A leaves B running");
  await pool.query("INSERT INTO sources (id,name,kind,metric,unit,enabled) VALUES ('api:air','环境','airgradient','co2','ppm',true)");
  await pool.query(`INSERT INTO samples (source_id,value,recorded_at,experience_id,metadata)
    SELECT 'api:air',v,clock_timestamp(),$1,'{"measurements":{"rco2":800}}'::jsonb
    FROM generate_series(1,55) v`, [first.id]);
  await pool.query(`INSERT INTO samples (source_id,value,recorded_at,experience_id)
    VALUES ('api:air',999,clock_timestamp(),$1)`, [second.id]);
  await pool.query("INSERT INTO experience_samples(experience_id,sample_id) SELECT experience_id,id FROM samples WHERE experience_id IS NOT NULL ON CONFLICT DO NOTHING");
  const firstPage = await (await detail.GET(request(""), context(first.id))).json();
  assert.equal(firstPage.samples.length, 50);
  assert.equal(firstPage.sources[0].sample_count, "55");
  assert.ok(firstPage.samples.every(s => s.value !== 999), "other participant is excluded");
  const nextPage = await (await detail.GET(request("/?before=" + firstPage.next), context(first.id))).json();
  assert.equal(nextPage.samples.length, 5);
  assert.equal(nextPage.next, null);
  assert.equal(new Set([...firstPage.samples, ...nextPage.samples].map(s => s.id)).size, 55);
  const filtered = await (await detail.GET(request("/?source=missing"), context(first.id))).json();
  assert.equal(filtered.samples.length, 0);
  assert.equal((await detail.GET(request(""), context("bad-id"))).status, 400);
  assert.equal((await detail.GET(request("/?before=9223372036854775808"), context(first.id))).status, 400);
  assert.equal((await detail.GET(request(""), context("00000000-0000-0000-0000-000000000000"))).status, 404);
  const history = await (await list.GET(request("/"))).json();
  assert.equal(history.experiences.length, 2);
  assert.equal(history.experiences.find(e => e.id === first.id).sample_count, "55");
  await end(second.id,second.client_id);
  await pool.query(`INSERT INTO experiences (name,started_at,ended_at)
    SELECT '分页体验 ' || n, '2020-01-01T00:00:00.123456Z', '2020-01-01T00:00:01Z'
    FROM generate_series(1,164) n`);
  let cursor = null, ids = [], sequences = [];
  do {
    const result = await (await list.GET(request("/" + (cursor ? "?before=" + cursor : "")))).json();
    ids.push(...result.experiences.map(e => e.id));
    sequences.push(...result.experiences.map(e => Number(e.sequence))); cursor = result.next;
  } while (cursor);
  assert.deepEqual(sequences, Array.from({length:166},(_,index)=>166-index),
    "sequence follows entry order and descends across all pages");
  const oldFirst = await (await list.GET(request("/"))).json();
  assert.equal(oldFirst.experiences.length,100,"history pages contain 100 records");
  await pool.query("INSERT INTO experiences (name,started_at,ended_at) VALUES ('new entry',clock_timestamp(),clock_timestamp())");
  const freshList = await (await list.GET(request("/"))).json();
  assert.equal(freshList.experiences[0].sequence, "167");
  assert.equal(freshList.experiences[1].id, oldFirst.experiences[0].id);
  assert.equal(freshList.experiences[1].sequence, oldFirst.experiences[0].sequence);
  const older = await (await list.GET(request("/?before="+oldFirst.next))).json();
  assert.equal(older.experiences[0].sequence, "66", "new records do not shift the previous cursor");
  assert.equal(ids.length, 166);
  assert.equal(new Set(ids).size, 166, "same-timestamp experience pagination must not skip or repeat rows");
  assert.equal((await list.GET(request("/?before=bad"))).status, 400);
  console.log("API integration passed: validation, concurrent starts, idempotent end, isolation, filtering, pagination.");
} finally {
  Module._resolveFilename = resolve;
  await pool.end();
  rmSync(output, { recursive: true, force: true });
}
