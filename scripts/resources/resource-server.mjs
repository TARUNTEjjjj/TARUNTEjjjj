#!/usr/bin/env node
/** Optional local API and explicit refresh CLI. No network requests when serving. */
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { validateConfig, readCatalog, refreshCatalog, queryCatalog, createSeedSnapshot, writeSnapshot } from './resource-catalog.mjs';

export function createResourceServer(configInput, { snapshotPath, allowedOrigins = [], now } = {}) {
  const config = validateConfig(configInput);
  const origins = new Set(allowedOrigins.map((value) => {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.origin !== value) throw new Error('Allowed origins must be exact HTTP(S) origins.');
    return value;
  }));
  const server = createServer(async (request, response) => {
    const headers = { 'Content-Type': 'application/json; charset=utf-8', 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'public, max-age=60', 'Access-Control-Expose-Headers': 'Content-Type' };
    const origin = request.headers.origin;
    const reply = (status, body) => { response.writeHead(status, headers); response.end(JSON.stringify(body)); };
    const port = server.address()?.port;
    if (![ `127.0.0.1:${port}`, `localhost:${port}`, `[::1]:${port}` ].includes(request.headers.host)) return reply(403, { error: 'Host is not allowed.' });
    // Exact allowlist; no wildcard CORS and no client-provided remote URLs.
    if (origin) {
      let sameOrigin = false;
      try { sameOrigin = new URL(origin).host === request.headers.host && new URL(origin).protocol === 'http:'; } catch { /* Invalid Origin is rejected below. */ }
      if (!origins.has(origin) && !sameOrigin) return reply(403, { error: 'Origin is not allowed.' });
      headers['Access-Control-Allow-Origin'] = origin;
      headers.Vary = 'Origin';
    }
    if (request.method !== 'GET' && request.method !== 'HEAD') return reply(405, { error: 'Only GET and HEAD are supported.' });
    let url;
    try { url = new URL(request.url, 'http://localhost'); } catch { return reply(400, { error: 'Invalid URL.' }); }
    if (url.pathname === '/health') return reply(200, { ok: true, project: config.project });
    if (!['/api/resources', '/resources/catalog.json'].includes(url.pathname)) return reply(404, { error: 'Not found.' });
    const category = url.searchParams.get('category');
    const q = url.searchParams.get('q') ?? '';
    const limit = Number(url.searchParams.get('limit') ?? 100);
    if (category && !config.categories.some((item) => item.id === category)) return reply(400, { error: 'Unknown category.' });
    if (q.length > 200 || !Number.isSafeInteger(limit) || limit < 1 || limit > 200) return reply(400, { error: 'Use q up to 200 characters and limit between 1 and 200.' });
    try {
      const snapshot = await readCatalog(config, { snapshotPath, now });
      const result = queryCatalog(snapshot, { category, q, limit });
      if (Buffer.byteLength(JSON.stringify(result)) > 1_000_000) return reply(503, { error: 'Catalog exceeds the response size limit.' });
      return reply(200, result);
    } catch { return reply(503, { error: 'Catalog is temporarily unavailable.' }); }
  });
  server.requestTimeout = 10_000;
  server.headersTimeout = 10_000;
  server.maxHeadersCount = 40;
  return server;
}

function parseArgs(args) {
  const [command = 'help', ...rest] = args;
  const options = {};
  const allowed = new Set(['config', 'output', 'snapshot', 'port', 'origins']);
  for (let index = 0; index < rest.length; index += 2) {
    const key = rest[index]?.replace(/^--/, '');
    if (!rest[index]?.startsWith('--') || !allowed.has(key) || !rest[index + 1] || rest[index + 1].startsWith('--')) throw new Error('Invalid command options. Run with help for usage.');
    options[key] = rest[index + 1];
  }
  return { command, options };
}

export async function main(args = process.argv.slice(2)) {
  const { command, options } = parseArgs(args);
  if (command === 'help' || command === '--help') {
    process.stdout.write('Usage:\n  node resource-server.mjs seed --config resources/sources.json --output resources/catalog.json\n  node resource-server.mjs refresh --config resources/sources.json --output resources/catalog.json\n  node resource-server.mjs serve --config resources/sources.json --snapshot resources/catalog.json --port 8787\nOptional serve --origins http://localhost:3000,http://localhost:5173\nGITHUB_TOKEN is optional and read only by the refresh command.\n');
    return;
  }
  if (!['seed', 'refresh', 'serve'].includes(command) || !options.config) throw new Error('Choose seed, refresh, or serve and provide --config.');
  const config = validateConfig(JSON.parse(await readFile(resolve(options.config), 'utf8')));
  const snapshotPath = resolve(options.output ?? options.snapshot ?? 'resources/catalog.json');
  if (command === 'seed') {
    const snapshot = createSeedSnapshot(config);
    await writeSnapshot(snapshotPath, snapshot);
    process.stdout.write(`Seeded ${snapshot.items.length} curated links for ${config.project}.\n`);
    return snapshot;
  }
  if (command === 'refresh') {
    const snapshot = await refreshCatalog(config, { snapshotPath });
    process.stdout.write(`${config.project}: ${snapshot.items.length} resources; status=${snapshot.status}; source errors=${snapshot.errors.length}.\n`);
    if (snapshot.errors.length) process.exitCode = 2;
    return snapshot;
  }
  const port = Number(options.port ?? 8787);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) throw new Error('Port must be between 1 and 65535.');
  const server = createResourceServer(config, { snapshotPath, allowedOrigins: options.origins ? options.origins.split(',') : [] });
  await new Promise((done, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', done); });
  process.stdout.write(`Resource API: http://127.0.0.1:${port}/api/resources\n`);
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch((error) => { process.stderr.write(`Resource catalog: ${error.message}\n`); process.exitCode = 1; });
}
