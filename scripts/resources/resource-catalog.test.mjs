import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { request as httpRequest } from 'node:http';
import { spawnSync } from 'node:child_process';
import { validateConfig, normalizeRepository, rankResources, createSeedSnapshot, refreshCatalog, readCatalog, queryCatalog } from './resource-catalog.mjs';
import { createResourceServer } from './resource-server.mjs';

const NOW = '2026-11-14T00:00:00.000Z';
const LATER = '2026-11-15T01:00:00.000Z';
const config = { schemaVersion: 1, project: 'example/math-app', title: 'Math resources', minStars: 100, maxPerCategory: 12, categories: [{ id: 'mathematics', title: 'Mathematics', queries: ['topic:mathematics'], seeds: ['sympy/sympy'] }] };
const raw = (overrides = {}) => ({ id: 123, full_name: 'sympy/sympy', html_url: 'https://github.com/sympy/sympy', description: 'Symbolic mathematics', topics: ['mathematics', 'python'], stargazers_count: 10000, forks_count: 2000, pushed_at: '2026-11-01T00:00:00Z', license: { spdx_id: 'BSD-3-Clause' }, archived: false, fork: false, private: false, ...overrides });
const jsonResponse = (value, options = {}) => new Response(JSON.stringify(value), { status: 200, ...options });
const searchResponse = (items, options = {}) => jsonResponse({ incomplete_results: false, items }, options);
const options = (more = {}) => ({ now: NOW, requestSpacingMs: 0, token: '', ...more });
async function fixture(t) {
  const directory = await mkdtemp(join(tmpdir(), 'resource-catalog-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return { directory, snapshotPath: join(directory, 'catalog.json') };
}
const successfulFetch = async (url) => url.includes('/search/') ? searchResponse([raw()], { headers: { etag: '"query-v1"' } }) : jsonResponse(raw(), { headers: { etag: '"seed-v1"' } });

test('config validation bounds source counts, categories, and repositories', () => {
  assert.equal(validateConfig(config).maxPages, 1);
  assert.throws(() => validateConfig({ ...config, categories: [...config.categories, ...config.categories] }), /unique/);
  assert.throws(() => validateConfig({ ...config, categories: [{ id: 'math', title: 'Math', seeds: ['https://evil.test/a'] }] }), /owner\/name/);
  assert.throws(() => validateConfig({ ...config, maxPages: 200 }), /maxPages/);
  assert.throws(() => validateConfig({ ...config, maxPerCategory: 500 }), /maxPerCategory/);
});

test('normalization removes unsafe, archived, forked, private, and low-star repositories', () => {
  const normalized = normalizeRepository(raw(), { category: 'mathematics', sourceQuery: 'math', fetchedAt: NOW, minStars: 100 });
  assert.equal(normalized.license, 'BSD-3-Clause');
  assert.equal(normalized.fetchedAt, NOW);
  for (const patch of [{ archived: true }, { fork: true }, { disabled: true }, { private: true }, { html_url: 'https://github.com.evil.test/sympy/sympy' }, { html_url: 'javascript:alert(1)' }, { stargazers_count: -1 }, { stargazers_count: 4 }, { id: NaN }]) {
    assert.equal(normalizeRepository(raw(patch), { minStars: 100 }), null, JSON.stringify(patch));
  }
});

test('ranking favors topical relevance, deduplicates renamed IDs, and is deterministic', () => {
  const context = { category: 'mathematics', sourceQuery: 'math', fetchedAt: NOW };
  const relevant = normalizeRepository(raw({ stargazers_count: 1000 }), context);
  const unrelated = normalizeRepository(raw({ id: 456, full_name: 'other/styles', html_url: 'https://github.com/other/styles', description: 'CSS colors', topics: [], stargazers_count: 1000000 }), context);
  const newerName = { ...relevant, fullName: 'new/symbols', fetchedAt: '2026-11-14T01:00:00.000Z' };
  const items = rankResources([unrelated, relevant, newerName], config.categories[0], { now: NOW });
  assert.equal(items.length, 2);
  assert.equal(items[0].fullName, 'new/symbols');
  assert.deepEqual(items, rankResources([newerName, relevant, unrelated], config.categories[0], { now: NOW }));
});

test('offline seeds are useful links with unknown statistics and no fabricated dates', () => {
  const snapshot = createSeedSnapshot(config, { now: NOW });
  assert.equal(snapshot.status, 'seed');
  assert.equal(snapshot.fetchedAt, null);
  assert.equal(snapshot.items[0].stars, null);
  assert.equal(snapshot.items[0].license, null);
  assert.equal(snapshot.items[0].provenance, 'seed');
  assert.equal(snapshot.items[0].url, 'https://github.com/sympy/sympy');
});

test('refresh writes a compact public snapshot and separate reusable cache atomically', async (t) => {
  const { snapshotPath, directory } = await fixture(t);
  const snapshot = await refreshCatalog(config, options({ snapshotPath, fetchImpl: successfulFetch }));
  assert.equal(snapshot.status, 'live');
  assert.equal(snapshot.items.length, 1);
  assert.equal(snapshot.items[0].stars, 10000);
  const publicData = JSON.parse(await readFile(snapshotPath, 'utf8'));
  assert.equal(publicData.sourceCache, undefined);
  assert.equal(Object.keys(JSON.parse(await readFile(`${snapshotPath}.cache.json`, 'utf8')).sourceCache).length, 2);
  assert.deepEqual((await readdir(directory)).sort(), ['catalog.json', 'catalog.json.cache.json']);
  assert.equal((await readCatalog(config, { snapshotPath, now: NOW })).status, 'cached');
});

test('public snapshots remain usable when transport cache is unavailable', async (t) => {
  const { snapshotPath } = await fixture(t);
  await refreshCatalog(config, options({ snapshotPath, fetchImpl: successfulFetch }));
  await rm(`${snapshotPath}.cache.json`);
  const read = await readCatalog(config, { snapshotPath, now: LATER });
  assert.equal(read.items[0].stars, 10000);
  assert.equal(read.items[0].stale, true);
  assert.equal(read.status, 'partial');
  const failed = await refreshCatalog(config, options({ snapshotPath, now: LATER, fetchImpl: async () => { throw new Error('offline'); } }));
  assert.equal(failed.items[0].stars, 10000);
  assert.equal(failed.items[0].fetchedAt, NOW);
});

test('invalid but parseable transport cache falls back to the public snapshot', async (t) => {
  const { snapshotPath } = await fixture(t);
  await refreshCatalog(config, options({ snapshotPath, fetchImpl: successfulFetch }));
  await writeFile(`${snapshotPath}.cache.json`, '{}');
  const failed = await refreshCatalog(config, options({ snapshotPath, now: LATER, fetchImpl: async () => { throw new Error('offline'); } }));
  assert.equal(failed.items[0].stars, 10000);
  assert.equal(failed.items[0].fetchedAt, NOW);
});

test('JSON null public and transport files use safe fallback paths', async (t) => {
  const { snapshotPath } = await fixture(t);
  await writeFile(snapshotPath, 'null');
  assert.equal((await readCatalog(config, { snapshotPath, now: NOW })).status, 'seed');
  await refreshCatalog(config, options({ snapshotPath, fetchImpl: successfulFetch }));
  await writeFile(`${snapshotPath}.cache.json`, 'null');
  const failed = await refreshCatalog(config, options({ snapshotPath, now: LATER, fetchImpl: async () => { throw new Error('offline'); } }));
  assert.equal(failed.items[0].stars, 10000);
  assert.equal(failed.items[0].fetchedAt, NOW);
});

test('malformed 200 payloads preserve good data instead of deleting sources', async (t) => {
  const { snapshotPath } = await fixture(t);
  await refreshCatalog(config, options({ snapshotPath, fetchImpl: successfulFetch }));
  const failed = await refreshCatalog(config, options({ snapshotPath, now: LATER, fetchImpl: async (url) => url.includes('/search/') ? searchResponse([{}]) : jsonResponse({}) }));
  assert.equal(failed.items[0].stars, 10000);
  assert.equal(failed.items[0].fetchedAt, NOW);
  assert.equal(failed.errors.length, 2);
});

test('malformed repository URLs in 200 payloads preserve the last good source', async (t) => {
  const { snapshotPath } = await fixture(t);
  await refreshCatalog(config, options({ snapshotPath, fetchImpl: successfulFetch }));
  const fetchImpl = async (url) => url.includes('/search/') ? searchResponse([raw({ html_url: 'bad-url' })]) : jsonResponse(raw({ html_url: 'https://evil.test/sympy/sympy' }));
  const failed = await refreshCatalog(config, options({ snapshotPath, now: LATER, fetchImpl }));
  assert.equal(failed.items[0].stars, 10000);
  assert.equal(failed.items[0].fetchedAt, NOW);
  assert.equal(failed.errors.length, 2);
  assert.equal(failed.status, 'partial');
});

test('ETag 304 responses preserve data and advance successful verification time', async (t) => {
  const { snapshotPath } = await fixture(t);
  await refreshCatalog(config, options({ snapshotPath, fetchImpl: successfulFetch }));
  let calls = 0;
  const fetchImpl = async (_url, request) => { calls++; assert.ok(request.headers['If-None-Match']); return new Response(null, { status: 304 }); };
  const snapshot = await refreshCatalog(config, options({ snapshotPath, now: LATER, fetchImpl }));
  assert.equal(calls, 2);
  assert.equal(snapshot.status, 'live');
  assert.equal(snapshot.items[0].fetchedAt, LATER);
  assert.equal(snapshot.items[0].stars, 10000);
});

test('source failure preserves its last good data and original timestamp', async (t) => {
  const { snapshotPath } = await fixture(t);
  const queryOnly = { ...config, categories: [{ ...config.categories[0], seeds: [] }] };
  await refreshCatalog(queryOnly, options({ snapshotPath, fetchImpl: successfulFetch }));
  const snapshot = await refreshCatalog(queryOnly, options({ snapshotPath, now: LATER, fetchImpl: async () => new Response('bad', { status: 503 }) }));
  assert.equal(snapshot.status, 'partial');
  assert.equal(snapshot.items[0].fetchedAt, NOW);
  assert.equal(snapshot.items[0].stale, true);
  assert.match(snapshot.errors[0].message, /503/);
});

test('refresh CLI persists a partial catalog and returns the distinct partial-success exit code', async (t) => {
  const { snapshotPath, directory } = await fixture(t);
  const queryOnly = { ...config, categories: [{ ...config.categories[0], seeds: [] }] };
  const configPath = join(directory, 'sources.json');
  await writeFile(configPath, JSON.stringify(queryOnly));
  await refreshCatalog(queryOnly, options({ snapshotPath, fetchImpl: successfulFetch }));
  const bootstrap = "globalThis.fetch = async () => new Response('', {status: 503}); const {main} = await import(process.argv[1]); await main(process.argv.slice(2));";
  const result = spawnSync(process.execPath, ['--input-type=module', '--eval', bootstrap, new URL('./resource-server.mjs', import.meta.url).href, 'refresh', '--config', configPath, '--output', snapshotPath], { encoding: 'utf8', timeout: 5000 });
  assert.equal(result.status, 2, result.stderr);
  const snapshot = JSON.parse(await readFile(snapshotPath, 'utf8'));
  assert.equal(snapshot.status, 'partial');
  assert.equal(snapshot.items[0].stars, 10000);
  assert.equal(snapshot.items[0].fetchedAt, NOW);
  assert.equal(snapshot.errors.length, 1);
});

test('rate limits stop further requests and persist cooldown across refreshes', async (t) => {
  const { snapshotPath } = await fixture(t);
  let calls = 0;
  const fetchImpl = async () => { calls++; return new Response('', { status: 429, headers: { 'Retry-After': '120' } }); };
  const first = await refreshCatalog(config, options({ snapshotPath, fetchImpl }));
  assert.equal(calls, 1);
  assert.equal(first.errors.length, 2);
  await refreshCatalog(config, options({ snapshotPath, fetchImpl, now: '2026-11-14T00:01:00.000Z' }));
  assert.equal(calls, 1);
  await refreshCatalog(config, options({ snapshotPath, fetchImpl: successfulFetch, now: '2026-11-14T00:03:00.000Z' }));
  assert.equal((await readCatalog(config, { snapshotPath, now: '2026-11-14T00:03:00.000Z' })).status, 'cached');
});

test('Retry-After starts when the rate-limit response arrives, not when refresh began', async (t) => {
  const { snapshotPath } = await fixture(t);
  let clock = Date.parse(NOW);
  let calls = 0;
  const fetchImpl = async (url) => {
    calls++;
    if (url.includes('/search/')) return searchResponse([raw()]);
    clock += 120_000;
    return new Response('', { status: 429, headers: { 'Retry-After': '60' } });
  };
  await refreshCatalog(config, options({ snapshotPath, now: () => clock, fetchImpl }));
  const cache = JSON.parse(await readFile(`${snapshotPath}.cache.json`, 'utf8'));
  const limited = Object.values(cache.sourceCache).find((source) => source.nextRetryAt);
  assert.equal(Date.parse(limited.nextRetryAt) - clock, 60_000);
  clock += 30_000;
  await refreshCatalog(config, options({ snapshotPath, now: () => clock, fetchImpl }));
  assert.equal(calls, 2, 'A second refresh during the cooldown must not make upstream requests.');
});

test('repository timestamps record successful response observations', async (t) => {
  const { snapshotPath } = await fixture(t);
  let clock = Date.parse(NOW);
  const snapshot = await refreshCatalog(config, options({ snapshotPath, now: () => clock, fetchImpl: async (url) => { clock += 30_000; return successfulFetch(url); } }));
  assert.equal(snapshot.attemptedAt, NOW);
  assert.equal(snapshot.items[0].fetchedAt, new Date(clock).toISOString());
});

test('excluded archived seeds stay excluded, while relevant low-star seeds are permitted', async (t) => {
  const { snapshotPath } = await fixture(t);
  const seedOnly = { ...config, categories: [{ ...config.categories[0], queries: [] }] };
  const archived = await refreshCatalog(seedOnly, options({ snapshotPath, fetchImpl: async () => jsonResponse(raw({ archived: true })) }));
  assert.equal(archived.items.length, 0);
  const read = await readCatalog(seedOnly, { snapshotPath, now: NOW });
  assert.equal(read.items.length, 0);
  await rm(`${snapshotPath}.cache.json`);
  const offline = await refreshCatalog(seedOnly, options({ snapshotPath, now: LATER, fetchImpl: async () => { throw new Error('offline'); } }));
  assert.equal(offline.items.length, 0);
  const active = await refreshCatalog(seedOnly, options({ snapshotPath, fetchImpl: async () => jsonResponse(raw({ stargazers_count: 3 })) }));
  assert.equal(active.items[0].stars, 3);
});

test('a known-archived seed is removed from failed discovery sources too', async (t) => {
  const { snapshotPath } = await fixture(t);
  await refreshCatalog(config, options({ snapshotPath, fetchImpl: successfulFetch }));
  const snapshot = await refreshCatalog(config, options({ snapshotPath, now: LATER, fetchImpl: async (url) => url.includes('/search/') ? new Response('', { status: 503 }) : jsonResponse(raw({ archived: true })) }));
  assert.equal(snapshot.items.length, 0);
  assert.equal(snapshot.excludedSeeds[0].repositoryId, 123);
  await rm(`${snapshotPath}.cache.json`);
  assert.equal((await readCatalog(config, { snapshotPath, now: LATER })).items.length, 0);
  const offline = await refreshCatalog(config, options({ snapshotPath, now: LATER, fetchImpl: async () => { throw new Error('offline'); } }));
  assert.equal(offline.items.length, 0);
});

test('known exclusions match repository IDs after a seed has been renamed', async (t) => {
  const { snapshotPath } = await fixture(t);
  const renamed = raw({ full_name: 'symbolic/sympy', html_url: 'https://github.com/symbolic/sympy' });
  await refreshCatalog(config, options({ snapshotPath, fetchImpl: async (url) => url.includes('/search/') ? searchResponse([renamed]) : jsonResponse(renamed) }));
  const snapshot = await refreshCatalog(config, options({ snapshotPath, now: LATER, fetchImpl: async (url) => url.includes('/search/') ? new Response('', { status: 503 }) : jsonResponse({ ...renamed, archived: true }) }));
  assert.equal(snapshot.items.length, 0);
  assert.equal(snapshot.excludedSeeds[0].fullName, 'sympy/sympy');
  assert.equal(snapshot.excludedSeeds[0].repositoryId, 123);
});

test('incomplete search preserves previous entries instead of dropping them', async (t) => {
  const { snapshotPath } = await fixture(t);
  const queryOnly = { ...config, categories: [{ ...config.categories[0], seeds: [] }] };
  await refreshCatalog(queryOnly, options({ snapshotPath, fetchImpl: successfulFetch }));
  const snapshot = await refreshCatalog(queryOnly, options({ snapshotPath, now: LATER, fetchImpl: async () => jsonResponse({ incomplete_results: true, items: [] }) }));
  assert.equal(snapshot.items.length, 1);
  assert.equal(snapshot.items[0].fetchedAt, NOW);
  assert.equal(snapshot.items[0].stale, true);
  assert.equal(snapshot.status, 'partial');
});

test('pagination follows only allowlisted URLs and remains bounded', async () => {
  const queryOnly = { ...config, maxPages: 2, categories: [{ ...config.categories[0], seeds: [] }] };
  let calls = 0;
  const fetchImpl = async (url) => {
    calls++;
    const next = new URL(url); next.searchParams.set('page', String(calls + 1));
    return searchResponse([raw({ id: 123 + calls, full_name: `org/math${calls}`, html_url: `https://github.com/org/math${calls}` })], { headers: { link: `<${next.href}>; rel="next"` } });
  };
  const snapshot = await refreshCatalog(queryOnly, options({ fetchImpl }));
  assert.equal(calls, 2);
  assert.equal(snapshot.items.length, 2);
  calls = 0;
  const unsafe = await refreshCatalog(queryOnly, options({ fetchImpl: async () => { calls++; return searchResponse([raw()], { headers: { link: '<https://evil.test/capture>; rel="next"' } }); } }));
  assert.equal(calls, 1);
  assert.equal(unsafe.items.length, 0);
  assert.match(unsafe.errors[0].message, /unexpected/);
});

test('redirects retain credentials only on api.github.com and are bounded', async () => {
  const seedOnly = { ...config, categories: [{ ...config.categories[0], queries: [] }] };
  const seen = [];
  const snapshot = await refreshCatalog(seedOnly, options({ token: 'test-token', fetchImpl: async (url, request) => { seen.push(url); assert.equal(request.headers.Authorization, 'Bearer test-token'); return seen.length === 1 ? new Response(null, { status: 301, headers: { location: 'https://api.github.com/repositories/123' } }) : jsonResponse(raw()); } }));
  assert.equal(snapshot.status, 'live');
  assert.equal(seen.length, 2);
  let calls = 0;
  const unsafe = await refreshCatalog(seedOnly, options({ token: 'test-token', fetchImpl: async () => { calls++; return new Response(null, { status: 302, headers: { location: 'https://evil.test/capture' } }); } }));
  assert.equal(calls, 1);
  assert.equal(JSON.stringify(unsafe).includes('test-token'), false);
  assert.equal(unsafe.status, 'seed');
});

test('invalid payloads and oversized responses use offline fallback', async () => {
  for (const fetchImpl of [async () => searchResponse({}, {}), async () => jsonResponse({}, { headers: { 'content-length': '3000000' } }), async () => new Response('{broken')]) {
    const snapshot = await refreshCatalog(config, options({ fetchImpl }));
    assert.equal(snapshot.status, 'seed');
    assert.ok(snapshot.errors.length > 0);
  }
});

test('concurrent refresh calls coalesce and do not duplicate upstream work', async (t) => {
  const { snapshotPath } = await fixture(t);
  let calls = 0;
  const fetchImpl = async (url) => { calls++; await new Promise((done) => setTimeout(done, 5)); return successfulFetch(url); };
  const [first, second] = await Promise.all([refreshCatalog(config, options({ snapshotPath, fetchImpl })), refreshCatalog(config, options({ snapshotPath, fetchImpl }))]);
  assert.deepEqual(first, second);
  assert.equal(calls, 2);
});

test('query filters are bounded and do not mutate original snapshot', () => {
  const snapshot = createSeedSnapshot(config, { now: NOW });
  assert.equal(queryCatalog(snapshot, { q: 'SYMPY', limit: 10000 }).items.length, 1);
  assert.equal(queryCatalog(snapshot, { category: 'unknown' }).items.length, 0);
  assert.equal(snapshot.items.length, 1);
});

test('corrupt snapshots safely fall back to seeds', async (t) => {
  const { snapshotPath } = await fixture(t);
  await writeFile(snapshotPath, '{broken');
  assert.equal((await readCatalog(config, { snapshotPath, now: NOW })).status, 'seed');
});

test('loopback API is read-only, filters resources, enforces CORS, and keeps cache private', async (t) => {
  const { snapshotPath } = await fixture(t);
  await refreshCatalog(config, options({ snapshotPath, fetchImpl: successfulFetch }));
  const server = createResourceServer(config, { snapshotPath, now: NOW, allowedOrigins: ['http://localhost:5173'] });
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  t.after(() => new Promise((done) => server.close(done)));
  const base = `http://127.0.0.1:${server.address().port}`;
  const response = await fetch(`${base}/api/resources?q=sympy&limit=1`, { headers: { Origin: 'http://localhost:5173' } });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('access-control-allow-origin'), 'http://localhost:5173');
  const data = await response.json();
  assert.equal(data.items.length, 1);
  assert.equal(data.sourceCache, undefined);
  assert.equal((await fetch(`${base}/api/resources`, { method: 'POST' })).status, 405);
  assert.equal((await fetch(`${base}/api/resources?limit=201`)).status, 400);
  assert.equal((await fetch(`${base}/api/resources?category=unknown`)).status, 400);
  assert.equal((await fetch(`${base}/api/resources`, { headers: { Origin: 'https://evil.test' } })).status, 403);
  const rejectedHost = await new Promise((done, reject) => { const request = httpRequest(`${base}/api/resources`, { headers: { Host: 'evil.test' } }, (response) => { response.resume(); done(response.statusCode); }); request.on('error', reject); request.end(); });
  assert.equal(rejectedHost, 403);
  assert.equal((await fetch(`${base}/refresh`)).status, 404);
});
