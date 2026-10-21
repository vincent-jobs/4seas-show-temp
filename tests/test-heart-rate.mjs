import assert from "node:assert/strict";
import test, { after } from "node:test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

// Use the project's existing compiler; the development container has Node 20.
const root = fileURLToPath(new URL("../", import.meta.url));
const output = mkdtempSync(join(tmpdir(), "fourseas-heart-test-"));
after(() => rmSync(output, { recursive: true, force: true }));
execFileSync(join(root, "web/node_modules/.bin/tsc"), [
  join(root, "web/lib/heart-rate.ts"), join(root, "web/lib/dashboard.ts"), join(root, "web/lib/experiences.ts"), join(root, "web/lib/eight-sleep.ts"), "--outDir", output,
  "--target", "es2020", "--module", "commonjs", "--skipLibCheck", "--ignoreConfig",
]);
const { heartRateStatus, heartRateValue, availableHeartBand } = createRequire(import.meta.url)(join(output, "heart-rate.js"));

test("removed band with a stuck contact flag has no usable heart rate", () => {
  for (const value of [0, null]) {
    assert.equal(heartRateStatus(value, { contact: true }), "无有效心率");
    assert.equal(heartRateValue(value, { contact: true }), null);
  }
});

test("missing, stale or paused data cannot confirm contact", () => {
  assert.equal(heartRateStatus(72, { contact: true }, false), "状态未知");
  assert.equal(heartRateStatus(0, { contact: true }, false), "状态未知");
  assert.equal(heartRateStatus(null, null, false), "状态未知");
});

test("unsupported contact and explicit no contact stay distinct", () => {
  assert.equal(heartRateStatus(72, { contact: null }), "接触状态未提供");
  assert.equal(heartRateStatus(72, { contact: false }), "未接触");
  assert.equal(heartRateValue(72, { contact: false }), null);
});

test("recovery shows only the device's report without claiming verified wearing", () => {
  assert.equal(heartRateValue(72, { contact: true, measurement_valid: true }), 72);
  assert.equal(heartRateStatus(72, { contact: true }), "设备报告接触");
  assert.equal(heartRateValue(72, { contact: true, measurement_valid: false }), null);
});

const { overviewSource, sampleSeries, isSourceFresh, timelineSamples } = createRequire(import.meta.url)(join(output, "dashboard.js"));
const { experienceName } = createRequire(import.meta.url)(join(output, "experiences.js"));

test("room panels keep independent source histories while switching sources", () => {
  const air = { id: "air:1", kind: "airgradient", enabled: true };
  const heart = { id: "ble:1", kind: "ble_heart_rate", enabled: true };
  assert.equal(overviewSource([heart, air], "airgradient", heart.id), air);
  assert.deepEqual(sampleSeries({ [air.id]: [{ id: "a" }] }, air, heart.id, [{ id: "h" }]), [{ id: "a" }]);
  assert.deepEqual(sampleSeries(undefined, air, heart.id, [{ id: "h" }]), []);
});
test("waiting, stale, disabled and offline readings cannot be presented as live", () => {
  const now = Date.now(), source = { enabled: true, kind: "ble_heart_rate", status: "streaming", last_sample_at: new Date(now).toISOString() };
  assert.equal(isSourceFresh(source, true, now), true);
  for (const altered of [{ ...source, status: "waiting" }, { ...source, enabled: false }]) {
    assert.equal(isSourceFresh(altered, true, now), false);
  }
  assert.equal(isSourceFresh(source, true, now + 11000), false);
  assert.equal(isSourceFresh(source, false, now), false);
});
test("timeline uses actual samples including both ends", () => {
  const samples = Array.from({ length: 120 }, (_, i) => ({ id: String(i) }));
  const points = timelineSamples(samples);
  assert.equal(points.length, 12);
  assert.equal(points[0], samples[0]);
  assert.equal(points.at(-1), samples.at(-1));
  assert.equal(new Set(points).size, 12);
  assert.deepEqual(timelineSamples([]), []);
});
test("participant names are trimmed and validated without turning blank input into a name", () => {
  assert.equal(experienceName("  体验者 1  "), "体验者 1");
  for (const value of [null, 1, "", "   ", "x".repeat(61), "bad\nname"]) assert.equal(experienceName(value), null);
});

const { availableBedMetrics, bedMetricValue, lastBedDisplay, bedDisplayTime } = createRequire(import.meta.url)(join(output, "eight-sleep.js"));

test("bed display prioritizes available current readings and keeps valid zero angles", () => {
  const payload = {
    leftBedTempC: 21, rightBedTempC: 22, currentBedTempC: 21,
    leftTorsoAngle: 0, rightTorsoAngle: 0, leftLegAngle: 0, rightLegAngle: 0,
    audioVolume: 34, currentLevel: 0, currentDeviceLevel: -47,
    heartRate: 60, hrv: 45, tempBedC: 29,
  };
  assert.deepEqual(availableBedMetrics(payload), [
    "leftBedTempC", "rightBedTempC", "leftTorsoAngle", "rightTorsoAngle", "leftLegAngle", "rightLegAngle",
  ]);
  assert.equal(bedMetricValue(payload, "leftTorsoAngle"), 0);
  assert.deepEqual(availableBedMetrics({ currentBedTempC: 21, audioVolume: 0 }), ["currentBedTempC"]);
});

test("bed display omits missing and invalid readings without treating zero as absent", () => {
  assert.deepEqual(availableBedMetrics({ heartRate: 0, hrv: null, tempBedC: "29", audioVolume: NaN }), []);
  assert.deepEqual(availableBedMetrics(undefined), []);
  assert.deepEqual(availableBedMetrics({ currentLevel: 0, heartRate: 62 }), ["currentLevel", "heartRate"]);
  assert.deepEqual(availableBedMetrics({ hub_online: false, currentLevel: 0, tempBedC: 28 }), ["tempBedC"]);
});

test("cloud polling retains a recent bed snapshot until it expires", () => {
  const now = Date.now();
  const bed = { enabled: true, kind: "eight_sleep", status: "waiting", last_sample_at: new Date(now - 15000).toISOString() };
  assert.equal(isSourceFresh(bed, true, now), true);
  assert.equal(isSourceFresh(bed, true, now + 31000), false);
  assert.equal(isSourceFresh({ ...bed, status: "offline" }, true, now), false);
  assert.equal(isSourceFresh(bed, false, now), false);
});

test("bed values survive stale/offline source status and partial new snapshots", () => {
  const before = "2026-10-21T03:00:00.000Z", after = "2026-10-21T03:00:10.000Z";
  const samples = [{ recorded_at: before, metadata: {measurements: {leftBedTempC:21,rightBedTempC:22,leftTorsoAngle:12}} }];
  const source = { status:"offline", enabled:true, last_sample_at:after,
    latest_metadata:{measurements:{leftBedTempC:23,rightBedTempC:null,leftTorsoAngle:0}} };
  const display = lastBedDisplay(source, samples);
  assert.deepEqual(display.measurements, {leftBedTempC:23,rightBedTempC:22,leftTorsoAngle:0});
  assert.equal(display.updated_at.rightBedTempC, before);
  assert.equal(bedDisplayTime(display, ["rightBedTempC"]), before);
  assert.equal(bedDisplayTime(display, ["leftBedTempC","rightBedTempC"]), after);
  const persisted = {...source, latest_metadata:{measurements:{},display}};
  assert.deepEqual(lastBedDisplay(persisted), display);
});

test("no bed reading creates no placeholder metric", () => {
  assert.deepEqual(availableBedMetrics(lastBedDisplay(undefined).measurements), []);
  assert.equal(bedDisplayTime(lastBedDisplay(undefined), []), undefined);
});

test("a band requires a recent sighting or notification and cannot already be occupied", () => {
  const now = Date.now(), source = {kind:"ble_heart_rate",last_seen:new Date(now).toISOString(),status:"waiting"};
  assert.equal(availableHeartBand(source,now),true);
  assert.equal(availableHeartBand({...source,occupied:true},now),false);
  for (const status of ["waiting","streaming","offline"]) {
    assert.equal(availableHeartBand({...source,status},now+61000),false);
  }
  assert.equal(availableHeartBand({...source,last_seen:"invalid"},now),false);
});

const { lastAirDisplay } = createRequire(import.meta.url)(join(output, "airgradient.js"));
test("air retains each valid reading while offline, with zero and original times preserved", () => {
  const before = "2026-10-21T03:00:00.000Z", after = "2026-10-21T03:01:00.000Z";
  const samples = [{ recorded_at: before, metadata: {measurements:{rco2:650,rhum:45,pm02:8}} }];
  const source = {status:"offline",enabled:true,last_sample_at:after,
    latest_metadata:{measurements:{rco2:null,rhum:"unknown",pm02:0,atmp:23,noxIndex:true}}};
  const display = lastAirDisplay(source,samples);
  assert.deepEqual(display.measurements,{rco2:650,rhum:45,pm02:0,atmp:23});
  assert.equal(display.updated_at.rco2,before);
  assert.equal(display.updated_at.pm02,after);
  assert.deepEqual(lastAirDisplay({...source,latest_metadata:{display}},[]),display);
  assert.deepEqual(lastAirDisplay(undefined).measurements,{});
});
test("historical air snapshots use their own retained display, never newer readings", () => {
  const time = "2026-10-21T03:00:00.000Z";
  const snapshot = {recorded_at:time,metadata:{measurements:{atmp:23},
    display:{measurements:{atmp:23,rhum:45},updated_at:{atmp:time,rhum:time}}}};
  assert.deepEqual(lastAirDisplay(undefined,[snapshot]).measurements,{atmp:23,rhum:45});
});
