/** Dependency-free GitHub resource catalog. Node.js 20+. */
import { readFile, writeFile, mkdir, rename, unlink } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';

const API_ORIGIN = 'https://api.github.com';
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const DAY = 86_400_000;
const inFlight = new Map();
const REPO_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\/[A-Za-z0-9_.-]{1,100}$/;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const boundedText = (value, max) => typeof value === 'string' ? value.slice(0, max).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, '') : '';
const isoDate = (value) => typeof value === 'string' && Number.isFinite(Date.parse(value)) ? new Date(value).toISOString() : null;
const positiveInteger = (value) => Number.isSafeInteger(value) && value >= 0 ? value : null;
const instant = (now) => new Date(typeof now === 'function' ? now() : (now ?? Date.now())).toISOString();

function repositoryUrl(repository) {
  if (!repository || typeof repository.full_name !== 'string' || !REPO_NAME.test(repository.full_name) || typeof repository.html_url !== 'string') return null;
  try {
    const candidate = new URL(repository.html_url);
    if (candidate.origin !== 'https://github.com' || candidate.username || candidate.password || candidate.search || candidate.hash || candidate.pathname.toLowerCase() !== `/${repository.full_name}`.toLowerCase()) return null;
    return candidate.href;
  } catch { return null; }
}

export function validateConfig(input) {
  if (!input || input.schemaVersion !== 1) throw new Error('Config schemaVersion must be 1.');
  if (typeof input.project !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.\/-]{0,160}$/.test(input.project)) throw new Error('Config requires a valid project identifier.');
  if (typeof input.title !== 'string' || !input.title.trim() || input.title.length > 160) throw new Error('Config requires a title of at most 160 characters.');
  if (!Array.isArray(input.categories) || !input.categories.length || input.categories.length > 20) throw new Error('Config requires 1–20 categories.');
  const ids = new Set();
  const categories = input.categories.map((category) => {
    if (!category || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(category.id) || ids.has(category.id)) throw new Error('Category ids must be unique lowercase slugs.');
    ids.add(category.id);
    if (typeof category.title !== 'string' || !category.title.trim() || category.title.length > 120) throw new Error('Each category needs a title of at most 120 characters.');
    const queries = category.queries ?? [];
    const seeds = category.seeds ?? [];
    if (!Array.isArray(queries) || queries.length > 6 || queries.some((q) => typeof q !== 'string' || !q.trim() || q.length > 256)) throw new Error('Each category supports up to six bounded GitHub queries.');
    if (!Array.isArray(seeds) || seeds.length > 12 || seeds.some((repo) => typeof repo !== 'string' || !REPO_NAME.test(repo))) throw new Error('Seed repositories must use owner/name format (at most 12 per category).');
    if (!queries.length && !seeds.length) throw new Error('Each category needs a query or seed repository.');
    return { id: category.id, title: category.title.trim(), queries: [...new Set(queries.map((q) => q.trim()))], seeds: [...new Set(seeds)] };
  });
  const minStars = input.minStars ?? 100;
  const maxPerCategory = input.maxPerCategory ?? 12;
  const maxPages = input.maxPages ?? 1;
  const ttlHours = input.ttlHours ?? 24;
  if (!Number.isSafeInteger(minStars) || minStars < 0 || minStars > 1_000_000) throw new Error('minStars must be an integer between 0 and 1000000.');
  if (!Number.isSafeInteger(maxPerCategory) || maxPerCategory < 1 || maxPerCategory > 50) throw new Error('maxPerCategory must be between 1 and 50.');
  if (!Number.isSafeInteger(maxPages) || maxPages < 1 || maxPages > 2) throw new Error('maxPages must be 1 or 2.');
  if (!Number.isFinite(ttlHours) || ttlHours < 1 || ttlHours > 168) throw new Error('ttlHours must be between 1 and 168.');
  return { schemaVersion: 1, project: input.project, title: input.title.trim(), categories, minStars, maxPerCategory, maxPages, ttlHours };
}

export function normalizeRepository(repository, { category, sourceQuery, fetchedAt, minStars = 0 } = {}) {
  if (!repository || !REPO_NAME.test(repository.full_name ?? '') || !Number.isSafeInteger(repository.id) || repository.id < 1) return null;
  if (repository.archived || repository.disabled || repository.fork || repository.private) return null;
  const stars = positiveInteger(repository.stargazers_count);
  if (stars === null || stars < minStars) return null;
  const url = repositoryUrl(repository);
  if (!url) return null;
  return {
    id: repository.id,
    fullName: repository.full_name,
    url,
    description: boundedText(repository.description, 500),
    topics: Array.isArray(repository.topics) ? [...new Set(repository.topics.filter((topic) => typeof topic === 'string' && /^[a-z0-9-]{1,50}$/.test(topic)))].slice(0, 30) : [],
    stars,
    forks: positiveInteger(repository.forks_count),
    pushedAt: isoDate(repository.pushed_at),
    license: repository.license?.spdx_id && repository.license.spdx_id !== 'NOASSERTION' ? boundedText(repository.license.spdx_id, 80) : null,
    category,
    sourceQuery,
    fetchedAt: isoDate(fetchedAt),
    provenance: 'github',
    stale: false,
  };
}

export function rankResources(items, category, { now = Date.now(), limit = 12 } = {}) {
  const time = Date.parse(instant(now));
  const tokens = [...new Set(`${category.id} ${category.title}`.toLowerCase().split(/[^a-z0-9]+/).filter((token) => token.length > 2))];
  const unique = new Map();
  for (const item of items) {
    const key = String(item.id).startsWith('seed:') ? item.fullName.toLowerCase() : String(item.id);
    const prior = unique.get(key);
    if (!prior || (prior.stale && !item.stale) || ((Date.parse(item.fetchedAt) || 0) > (Date.parse(prior.fetchedAt) || 0))) unique.set(key, item);
  }
  const verifiedNames = new Set([...unique.values()].filter((item) => item.provenance === 'github').map((item) => item.fullName.toLowerCase()));
  return [...unique.values()].filter((item) => item.provenance !== 'seed' || !verifiedNames.has(item.fullName.toLowerCase())).map((item) => {
    const searchable = `${item.fullName} ${item.description} ${item.topics.join(' ')}`.toLowerCase();
    const relevance = tokens.length ? tokens.filter((token) => searchable.includes(token)).length / tokens.length : 0;
    const popularity = Math.min(Math.log10(1 + (item.stars ?? 0)) / 6, 1);
    const age = item.pushedAt ? Math.max(0, time - Date.parse(item.pushedAt)) / DAY : Infinity;
    const recency = Number.isFinite(age) ? 1 / (1 + age / 365) : 0;
    const score = Math.round((60 * relevance + 30 * popularity + 10 * recency) * 100) / 100;
    const reason = item.provenance === 'seed' ? `Curated starting point for ${category.title}; GitHub metadata not yet fetched.` : `${category.title} resource; ${item.stars} GitHub stars${item.stale ? '; cached metadata' : ''}.`;
    return { ...item, score, reason };
  }).sort((a, b) => b.score - a.score || (b.stars ?? -1) - (a.stars ?? -1) || a.fullName.toLowerCase().localeCompare(b.fullName.toLowerCase(), 'en')).slice(0, limit);
}

function seedItems(config, sourceCache = {}) {
  return config.categories.flatMap((category) => category.seeds.filter((fullName) => {
    const source = sourceCache[cacheKey(category.id, 'seed', fullName)];
    // A successfully inspected but excluded seed must not reappear as unverified.
    return !source || (!source.excluded && source.stale && !source.items.length);
  }).map((fullName) => ({
    id: `seed:${fullName.toLowerCase()}`, fullName, url: `https://github.com/${fullName}`, description: '', topics: [], stars: null, forks: null, pushedAt: null, license: null,
    category: category.id, sourceQuery: `repo:${fullName}`, fetchedAt: null, provenance: 'seed', stale: false,
  })));
}

function assemble(config, sourceCache, { now, errors = [], attemptedAt = null, forceStatus } = {}) {
  const time = Date.parse(instant(now));
  const cached = Object.values(sourceCache).flatMap((source) => source.items.map((item) => ({ ...item, stale: source.stale || time - Date.parse(item.fetchedAt) > config.ttlHours * 3_600_000 })));
  const all = [...cached, ...seedItems(config, sourceCache)];
  const items = config.categories.flatMap((category) => rankResources(all.filter((item) => item.category === category.id), category, { now, limit: config.maxPerCategory }));
  const times = cached.map((item) => item.fetchedAt).filter(Boolean).sort();
  const anyVerified = cached.length > 0;
  const status = forceStatus ?? (!anyVerified ? 'seed' : errors.length || cached.some((item) => item.stale) ? 'partial' : 'live');
  const excludedSeeds = Object.values(sourceCache).filter((source) => source.kind === 'seed' && source.excluded).map((source) => ({ category: source.category, fullName: source.query.slice(5) }));
  return { schemaVersion: 1, project: config.project, title: config.title, fetchedAt: times.at(-1) ?? null, attemptedAt, status, errors, excludedSeeds, categories: config.categories.map(({ id, title }) => ({ id, title, count: items.filter((item) => item.category === id).length })), items };
}

export function createSeedSnapshot(input, { now } = {}) {
  return assemble(validateConfig(input), {}, { now, forceStatus: 'seed' });
}

function cacheKey(category, kind, query) { return JSON.stringify([category, kind, query]); }

function sourcesFor(config) {
  return config.categories.flatMap((category) => [
    ...category.queries.map((query) => {
      const url = new URL('/search/repositories', API_ORIGIN);
      url.search = new URLSearchParams({ q: `${query} stars:>=${config.minStars} archived:false fork:false is:public`, sort: 'stars', order: 'desc', per_page: '100' }).toString();
      return { key: cacheKey(category.id, 'query', query), category: category.id, kind: 'query', query, url: url.href };
    }),
    ...category.seeds.map((repo) => ({ key: cacheKey(category.id, 'seed', repo), category: category.id, kind: 'seed', query: `repo:${repo}`, url: `${API_ORIGIN}/repos/${repo}` })),
  ]);
}

function isSafeApiUrl(value, kind, allowRedirect = false) {
  try {
    const url = new URL(value);
    return url.origin === API_ORIGIN && !url.username && !url.password && !url.hash && (kind === 'query' ? url.pathname === '/search/repositories' : /^\/repos\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(url.pathname) || (allowRedirect && /^\/repositories\/[0-9]+$/.test(url.pathname)));
  } catch { return false; }
}

async function loadStore(path, config) {
  if (!path) return null;
  try {
    const text = await readFile(`${path}.cache.json`, 'utf8');
    if (Buffer.byteLength(text) > MAX_FILE_BYTES) return storeFromPublic(path, config);
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== 'object' || parsed.schemaVersion !== 1 || parsed.project !== config.project || !parsed.sourceCache || typeof parsed.sourceCache !== 'object') return storeFromPublic(path, config);
    // Accept only known source keys, bounded arrays, and normalized metadata.
    const fallback = await storeFromPublic(path, config);
    const sourceCache = { ...fallback?.sourceCache };
    for (const source of sourcesFor(config)) {
      const entry = parsed.sourceCache[source.key];
      if (!entry || !Array.isArray(entry.items) || entry.items.length > 300) continue;
      const items = entry.items.map((item) => restoreItem(item, config, source)).filter(Boolean);
      if (entry.items.length && !items.length) continue;
      const pages = Array.isArray(entry.pages) ? entry.pages.filter((page) => page && isSafeApiUrl(page.url, source.kind) && Array.isArray(page.items) && page.items.length <= 100).slice(0, 2).map((page) => ({ url: page.url, etag: typeof page.etag === 'string' ? page.etag.slice(0, 500) : null, items: page.items.map((item) => restoreItem(item, config, source)).filter(Boolean), next: isSafeApiUrl(page.next, source.kind) ? page.next : null, incomplete: !!page.incomplete })) : [];
      sourceCache[source.key] = { ...source, items, pages, fetchedAt: isoDate(entry.fetchedAt), stale: !!entry.stale, excluded: source.kind === 'seed' && !!entry.excluded, nextRetryAt: isoDate(entry.nextRetryAt) };
    }
    return { sourceCache, attemptedAt: isoDate(parsed.attemptedAt), errors: Array.isArray(parsed.errors) ? parsed.errors.slice(0, 160).map((error) => ({ source: boundedText(error?.source, 300), message: boundedText(error?.message, 200) })) : [] };
  } catch (error) {
    if (error.code === 'ENOENT' || error instanceof SyntaxError) {
      return storeFromPublic(path, config);
    }
    throw error;
  }
}

async function storeFromPublic(path, config) {
  const publicSnapshot = await loadPublicSnapshot(path, config);
  if (!publicSnapshot) return null;
  const sourceCache = {};
  for (const source of sourcesFor(config)) {
    const items = publicSnapshot.items.filter((item) => item.provenance === 'github' && item.category === source.category && item.sourceQuery === source.query);
    const excluded = source.kind === 'seed' && publicSnapshot.excludedSeeds.some((entry) => entry.category === source.category && `repo:${entry.fullName}` === source.query);
    if (items.length || excluded) sourceCache[source.key] = { ...source, items, pages: [], fetchedAt: items.map((item) => item.fetchedAt).sort().at(-1) ?? null, stale: items.some((item) => item.stale), excluded, nextRetryAt: null };
  }
  return { sourceCache, attemptedAt: publicSnapshot.attemptedAt, errors: publicSnapshot.errors };
}

function restoreItem(item, config, source = null) {
  if (!item || item.provenance !== 'github') return null;
  const category = source?.category ?? item.category;
  if (!config.categories.some((value) => value.id === category)) return null;
  const normalized = normalizeRepository({ id: item.id, full_name: item.fullName, html_url: item.url, description: item.description, topics: item.topics, stargazers_count: item.stars, forks_count: item.forks, pushed_at: item.pushedAt, license: { spdx_id: item.license } }, {
    category, sourceQuery: source?.query ?? boundedText(item.sourceQuery, 300), fetchedAt: item.fetchedAt, minStars: source?.kind === 'query' ? config.minStars : 0,
  });
  return normalized?.fetchedAt ? { ...normalized, stale: !!item.stale } : null;
}

async function loadPublicSnapshot(path, config) {
  if (!path) return null;
  try {
    const text = await readFile(path, 'utf8');
    if (Buffer.byteLength(text) > MAX_FILE_BYTES) return null;
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== 'object' || parsed.schemaVersion !== 1 || parsed.project !== config.project || !Array.isArray(parsed.items) || parsed.items.length > 1000) return null;
    const validSeeds = seedItems(config);
    const sources = sourcesFor(config);
    const items = parsed.items.map((item) => {
      if (item?.provenance === 'seed') return validSeeds.find((seed) => seed.fullName === item.fullName && seed.category === item.category);
      const source = sources.find((entry) => entry.category === item?.category && entry.query === item?.sourceQuery);
      return source ? restoreItem(item, config, source) : null;
    }).filter(Boolean);
    const excludedSeeds = Array.isArray(parsed.excludedSeeds) ? parsed.excludedSeeds.filter((entry) => validSeeds.some((seed) => seed.fullName === entry?.fullName && seed.category === entry?.category)).map(({ category, fullName }) => ({ category, fullName })) : [];
    const errors = Array.isArray(parsed.errors) ? parsed.errors.slice(0, 160).map((error) => ({ source: boundedText(error?.source, 300), message: boundedText(error?.message, 200) })) : [];
    return { items, errors, excludedSeeds, attemptedAt: isoDate(parsed.attemptedAt), status: parsed.status };
  } catch (error) { if (error.code === 'ENOENT' || error instanceof SyntaxError) return null; throw error; }
}

export async function readCatalog(input, { snapshotPath, now } = {}) {
  const config = validateConfig(input);
  const saved = await loadPublicSnapshot(snapshotPath, config);
  if (!saved) return createSeedSnapshot(config, { now });
  const time = Date.parse(instant(now));
  const candidates = saved.items.map((item) => ({ ...item, stale: item.stale || (item.fetchedAt !== null && time - Date.parse(item.fetchedAt) > config.ttlHours * 3_600_000) }));
  const items = config.categories.flatMap((category) => rankResources(candidates.filter((item) => item.category === category.id), category, { now, limit: config.maxPerCategory }));
  const anyVerified = items.some((item) => item.provenance === 'github');
  const status = !anyVerified ? 'seed' : saved.errors.length || items.some((item) => item.stale) ? 'partial' : 'cached';
  return { schemaVersion: 1, project: config.project, title: config.title, fetchedAt: items.map((item) => item.fetchedAt).filter(Boolean).sort().at(-1) ?? null, attemptedAt: saved.attemptedAt, status, errors: saved.errors, excludedSeeds: saved.excludedSeeds, categories: config.categories.map(({ id, title }) => ({ id, title, count: items.filter((item) => item.category === id).length })), items };
}

export function queryCatalog(snapshot, { category, q = '', limit = 100 } = {}) {
  const maximum = Number.isSafeInteger(limit) ? Math.max(1, Math.min(limit, 200)) : 100;
  const query = typeof q === 'string' ? q.trim().toLowerCase().slice(0, 200) : '';
  const filtered = snapshot.items.filter((item) => (!category || item.category === category) && (!query || `${item.fullName} ${item.description} ${item.topics.join(' ')}`.toLowerCase().includes(query)));
  return { ...snapshot, total: filtered.length, items: filtered.slice(0, maximum) };
}

export async function writeSnapshot(snapshotPath, snapshot) {
  if (!snapshotPath) return;
  const file = resolve(snapshotPath);
  await mkdir(dirname(file), { recursive: true });
  const temporary = `${file}.${randomUUID()}.tmp`;
  const data = `${JSON.stringify(snapshot, null, 2)}\n`;
  if (Buffer.byteLength(data) > MAX_FILE_BYTES) throw new Error('Catalog exceeded its bounded snapshot size.');
  try {
    await writeFile(temporary, data, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
    await rename(temporary, file);
  } finally { await unlink(temporary).catch(() => {}); }
}

function retryAt(response, at) {
  const retry = response.headers.get('retry-after');
  const reset = Number(response.headers.get('x-ratelimit-reset'));
  if (retry && Number.isFinite(Number(retry))) return new Date(at + Math.max(60, Number(retry)) * 1000).toISOString();
  if (retry && Number.isFinite(Date.parse(retry))) return new Date(Math.max(at + 60_000, Date.parse(retry))).toISOString();
  if (response.headers.get('x-ratelimit-remaining') === '0' && Number.isFinite(reset) && reset > 0) return new Date(Math.max(at + 60_000, reset * 1000)).toISOString();
  return new Date(at + 60_000).toISOString();
}

async function fetchPage(url, { fetchImpl, token, etag, timeoutMs, kind }) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = {
      Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10', 'User-Agent': 'resource-catalog/1.0',
      ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(etag ? { 'If-None-Match': etag } : {}),
    };
    let response;
    for (let redirects = 0; redirects <= 3; redirects++) {
      response = await fetchImpl(url, { redirect: 'manual', signal: controller.signal, headers });
      if (![301, 302, 303, 307, 308].includes(response.status)) break;
      const next = new URL(response.headers.get('location') ?? '', url).href;
      if (redirects === 3 || !isSafeApiUrl(next, kind, true)) throw new Error('unsafe-redirect');
      url = next;
    }
    if (response.status === 304 || !response.ok) return { response, body: null };
    if (Number(response.headers.get('content-length')) > 2_000_000) throw new Error('response-too-large');
    const chunks = [];
    let length = 0;
    if (response.body?.getReader) {
      const reader = response.body.getReader();
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          length += value.byteLength;
          if (length > 2_000_000) { controller.abort(); await reader.cancel(); throw new Error('response-too-large'); }
          chunks.push(Buffer.from(value));
        }
      } finally { reader.releaseLock(); }
    } else { chunks.push(Buffer.from(await response.text())); }
    const text = Buffer.concat(chunks).toString('utf8');
    if (Buffer.byteLength(text) > 2_000_000) throw new Error('response-too-large');
    return { response, body: JSON.parse(text) };
  } finally { clearTimeout(timeout); }
}

export async function refreshCatalog(input, options = {}) {
  const config = validateConfig(input);
  const lock = options.snapshotPath ? resolve(options.snapshotPath) : config.project;
  if (inFlight.has(lock)) return inFlight.get(lock);
  const promise = performRefresh(config, options);
  inFlight.set(lock, promise);
  try { return await promise; } finally { inFlight.delete(lock); }
}

async function performRefresh(config, { snapshotPath, token = process.env.GITHUB_TOKEN, fetchImpl = globalThis.fetch, now, timeoutMs = 10_000, sleepImpl = sleep, requestSpacingMs } = {}) {
  if (typeof fetchImpl !== 'function') throw new Error('A fetch implementation is required.');
  if (!Number.isFinite(timeoutMs) || timeoutMs < 1 || timeoutMs > 30_000) throw new Error('timeoutMs must be between 1 and 30000.');
  const attemptedAt = instant(now);
  const at = Date.parse(attemptedAt);
  const previous = await loadStore(snapshotPath, config);
  const sourceCache = {};
  const errors = [];
  const sources = sourcesFor(config);
  let globalCooldown = Object.values(previous?.sourceCache ?? {}).map((source) => source.nextRetryAt).filter((date) => date && Date.parse(date) > at).sort().at(-1) ?? null;
  let requestCount = 0;
  const spacing = requestSpacingMs ?? (token ? 2100 : 6100);
  for (const source of sources) {
    const old = previous?.sourceCache[source.key];
    const fail = (message, nextRetryAt = null) => {
      errors.push({ source: `${source.category}: ${source.query}`, message });
      sourceCache[source.key] = { ...source, items: old?.items ?? [], pages: old?.pages ?? [], fetchedAt: old?.fetchedAt ?? null, stale: true, excluded: old?.excluded ?? false, nextRetryAt };
    };
    if (globalCooldown) { fail('GitHub refresh deferred until the recorded rate-limit cooldown ends.', globalCooldown); continue; }
    let url = source.url;
    const pages = [];
    const items = [];
    let incomplete = false;
    let failure = null;
    let cooldown = null;
    for (let pageIndex = 0; url && pageIndex < (source.kind === 'query' ? config.maxPages : 1); pageIndex++) {
      if (!isSafeApiUrl(url, source.kind)) { failure = 'Rejected an unexpected GitHub pagination URL.'; break; }
      const oldPage = old?.pages.find((page) => page.url === url);
      try {
        if (requestCount++ > 0 && spacing > 0) await sleepImpl(spacing);
        const { response, body } = await fetchPage(url, { fetchImpl, token, etag: oldPage?.etag, timeoutMs, kind: source.kind });
        if (response.status === 403 || response.status === 429) {
          cooldown = retryAt(response, at); globalCooldown = cooldown;
          failure = `GitHub returned ${response.status}; refresh paused to respect its rate limit or access policy.`; break;
        }
        if (response.status === 304) {
          if (!oldPage) { failure = 'GitHub returned an unusable cache response.'; break; }
          const revalidated = oldPage.items.map((item) => ({ ...item, fetchedAt: attemptedAt, stale: false }));
          pages.push({ ...oldPage, items: revalidated }); items.push(...revalidated);
          incomplete ||= oldPage.incomplete;
          url = oldPage.next; continue;
        }
        if (!response.ok) { failure = `GitHub returned HTTP ${response.status}; the previous source data was preserved.`; break; }
        const rawItems = source.kind === 'query' ? body?.items : [body];
        if (!Array.isArray(rawItems) || rawItems.length > 100 || (source.kind === 'query' && typeof body.incomplete_results !== 'boolean')) { failure = 'GitHub returned an invalid repository payload.'; break; }
        if (rawItems.some((repo) => !repo || !Number.isSafeInteger(repo.id) || repo.id < 1 || !repositoryUrl(repo) || positiveInteger(repo.stargazers_count) === null)) { failure = 'GitHub returned malformed repository metadata; the previous source data was preserved.'; break; }
        const normalized = rawItems.map((repo) => normalizeRepository(repo, { category: source.category, sourceQuery: source.query, fetchedAt: attemptedAt, minStars: source.kind === 'seed' ? 0 : config.minStars })).filter(Boolean);
        const link = response.headers.get('link') ?? '';
        const next = link.match(/<([^>]+)>;\s*rel="next"/)?.[1] ?? null;
        if (next && !isSafeApiUrl(next, source.kind)) { failure = 'Rejected an unexpected GitHub pagination URL.'; break; }
        const partial = source.kind === 'query' && body.incomplete_results;
        pages.push({ url, etag: response.headers.get('etag'), items: normalized, next, incomplete: !!partial });
        items.push(...normalized); incomplete ||= !!partial; url = next;
      } catch { failure = 'GitHub request failed or timed out; the previous source data was preserved.'; break; }
    }
    if (failure) { fail(failure, cooldown); continue; }
    if (incomplete) {
      errors.push({ source: `${source.category}: ${source.query}`, message: 'GitHub reported incomplete search results; previous source entries were retained.' });
      const seen = new Set(items.map((item) => item.id));
      items.push(...(old?.items ?? []).filter((item) => !seen.has(item.id)).map((item) => ({ ...item, stale: true })));
    }
    sourceCache[source.key] = { ...source, items: items.slice(0, 300), pages, fetchedAt: attemptedAt, stale: incomplete, excluded: source.kind === 'seed' && !items.length, nextRetryAt: null };
  }
  const snapshot = assemble(config, sourceCache, { now, errors, attemptedAt });
  await writeSnapshot(snapshotPath ? `${snapshotPath}.cache.json` : null, { schemaVersion: 1, project: config.project, attemptedAt, errors, sourceCache });
  await writeSnapshot(snapshotPath, snapshot);
  return snapshot;
}
