const assert = require('node:assert/strict');
const test = require('node:test');
const radar = require('../api/radar.js').__test;

test('decodes BigQuery rows including nullable values', () => {
  assert.deepEqual(radar.decodeRow([{ name: 'source', type: 'STRING' }, { name: 'summary', type: 'STRING' }], [{ v: 'huggingface' }, { v: null }]), { source: 'huggingface', summary: null });
});

test('decodes nullable nested enrichment records and repeated tags', () => {
  const fields = [{ name: 'enrichment', type: 'RECORD', fields: [{ name: 'tags', type: 'STRING', mode: 'REPEATED' }, { name: 'explanation', type: 'STRING' }] }];
  assert.deepEqual(radar.decodeRow(fields, [{ v: { f: [{ v: [{ v: 'code' }, { v: 'agents' }] }, { v: 'Grounded source context.' }] } }]), { enrichment: { tags: ['code', 'agents'], explanation: 'Grounded source context.' } });
  assert.deepEqual(radar.decodeRow(fields, [{ v: null }]), { enrichment: null });
});

test('builds a snapshot from the newest complete run only', async () => {
  const calls = [];
  const snapshot = await radar.buildSnapshot({ headers: {} }, {
    googleAccessToken: async () => 'short-lived-token',
    bigQuery: async (_token, sql, parameters) => {
      calls.push({ sql, parameters });
      if (sql === radar.LATEST_RUN_SQL) return [{ run_id: 'complete-run', window_start: '2026-07-29 00:00:00+00', window_end: '2026-07-30 00:00:00+00', completed_at: '2026-07-30 00:01:00+00' }];
      if (sql === radar.METRICS_SQL) return [{ source: 'arxiv', gold_item_count: '1' }];
      return [{ source: 'arxiv', source_id: '1234.5678', title: 'A paper' }];
    },
  });
  assert.equal(snapshot.status, 'ok');
  assert.equal(snapshot.run.id, 'complete-run');
  assert.equal(snapshot.items[0].source_id, '1234.5678');
  assert.match(radar.ITEMS_SQL, /mrr_enrichment\.item_enrichments/);
  assert.match(radar.ITEMS_SQL, /LEFT JOIN latest_enrichment/);
  assert.doesNotMatch(radar.ITEMS_SQL, /model_id|prompt_version|input_hash|failure_reason/i);
  assert.deepEqual(calls[1].parameters, radar.runParameter('complete-run'));
  assert.deepEqual(calls[2].parameters, radar.runParameter('complete-run'));
});

test('returns null when Gold has no fully successful run', async () => {
  assert.equal(await radar.buildSnapshot({ headers: {} }, { googleAccessToken: async () => 'short-lived-token', bigQuery: async () => [] }), null);
});

test('rejects non-GET requests without contacting Google Cloud', async () => {
  const response = { headers: {}, setHeader(name, value) { this.headers[name] = value; }, status(code) { this.statusCode = code; return this; }, json(body) { this.body = body; return this; } };
  await require('../api/radar.js')({ method: 'POST', headers: {} }, response);
  assert.equal(response.statusCode, 405);
  assert.equal(response.headers.Allow, 'GET');
  assert.deepEqual(response.body, { status: 'method_not_allowed' });
});
