const PROJECT_ID = 'project-90394262-994e-4667-90d';
const PROJECT_NUMBER = '334011635171';
const GOLD_DATASET = 'mrr_gold';
const ENRICHMENT_DATASET = 'mrr_enrichment';
const EXPECTED_SOURCES = 2;
const MAXIMUM_BYTES_BILLED = '1073741824';

function configured(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Missing ${name}`);
  return value;
}

function oidcToken(req) {
  const value = req.headers['x-vercel-oidc-token'] || process.env.VERCEL_OIDC_TOKEN;
  if (!value || Array.isArray(value)) throw new Error('Missing Vercel OIDC token');
  return value;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${response.status} ${body.error_description || body.error?.message || 'request failed'}`);
  return body;
}

async function googleAccessToken(req) {
  if (configured('GCP_PROJECT_ID') !== PROJECT_ID || configured('GCP_PROJECT_NUMBER') !== PROJECT_NUMBER) {
    throw new Error('Unexpected GCP project configuration');
  }
  const poolId = configured('GCP_WORKLOAD_IDENTITY_POOL_ID');
  const providerId = configured('GCP_WORKLOAD_IDENTITY_POOL_PROVIDER_ID');
  const serviceAccount = configured('GCP_SERVICE_ACCOUNT_EMAIL');
  const audience = `//iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${poolId}/providers/${providerId}`;
  const token = await fetchJson('https://sts.googleapis.com/v1/token', {
    method: 'POST', headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ audience, grant_type: 'urn:ietf:params:oauth:grant-type:token-exchange', requested_token_type: 'urn:ietf:params:oauth:token-type:access_token', subject_token_type: 'urn:ietf:params:oauth:token-type:jwt', subject_token: oidcToken(req), scope: 'https://www.googleapis.com/auth/cloud-platform' }),
  });
  const impersonated = await fetchJson(`https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${encodeURIComponent(serviceAccount)}:generateAccessToken`, {
    method: 'POST', headers: { authorization: `Bearer ${token.access_token}`, 'content-type': 'application/json' }, body: JSON.stringify({ scope: ['https://www.googleapis.com/auth/cloud-platform'] }),
  });
  return impersonated.accessToken;
}

function decodeValue(field, value) {
  if (value === null || value === undefined) return null;
  if (field.type === 'RECORD') return decodeRow(field.fields || [], value.f || []);
  if (field.mode === 'REPEATED') return value.map((entry) => decodeValue({ ...field, mode: 'NULLABLE' }, entry.v));
  return value;
}

function decodeRow(fields, cells) {
  return Object.fromEntries(fields.map((field, index) => [field.name, decodeValue(field, cells[index]?.v)]));
}

async function bigQuery(accessToken, sql, queryParameters = []) {
  const result = await fetchJson(`https://bigquery.googleapis.com/bigquery/v2/projects/${PROJECT_ID}/queries`, {
    method: 'POST', headers: { authorization: `Bearer ${accessToken}`, 'content-type': 'application/json' },
    body: JSON.stringify({ query: sql, useLegacySql: false, location: 'US', maximumBytesBilled: MAXIMUM_BYTES_BILLED, parameterMode: 'NAMED', queryParameters, timeoutMs: 10000 }),
  });
  if (!result.jobComplete) throw new Error('BigQuery query did not complete within the API timeout');
  return (result.rows || []).map((row) => decodeRow(result.schema.fields, row.f));
}

const LATEST_RUN_SQL = `SELECT run_id,
    FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E6SZ', MAX(window_start), 'UTC') AS window_start,
    FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E6SZ', MAX(window_end), 'UTC') AS window_end,
    FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E6SZ', MAX(processed_at), 'UTC') AS completed_at
  FROM \`${PROJECT_ID}.${GOLD_DATASET}.daily_source_metrics\` GROUP BY run_id
  HAVING COUNT(DISTINCT source) = ${EXPECTED_SOURCES} AND COUNTIF(source_status = 'succeeded') = ${EXPECTED_SOURCES}
  ORDER BY completed_at DESC LIMIT 1`;
const METRICS_SQL = `SELECT source, raw_page_count, raw_response_record_count, raw_window_record_count, silver_parsed_count, silver_inserted_count, silver_duplicate_count, silver_qualified_count, gold_item_count, source_status,
    FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E6SZ', processed_at, 'UTC') AS processed_at
  FROM \`${PROJECT_ID}.${GOLD_DATASET}.daily_source_metrics\` WHERE run_id = @run_id ORDER BY source`;
const ITEMS_SQL = `WITH latest_enrichment AS (
    SELECT source, source_id, tags, explanation
    FROM \`${PROJECT_ID}.${ENRICHMENT_DATASET}.item_enrichments\`
    WHERE status = 'succeeded'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY source, source_id ORDER BY created_at DESC, enrichment_id DESC) = 1
  )
  SELECT item.source, item.source_id,
    FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E6SZ', source_published_at, 'UTC') AS source_published_at,
    item.title, item.summary, item.canonical_url, item.author_or_org,
    FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E6SZ', item.observed_at, 'UTC') AS observed_at,
    IF(enrichment.source IS NULL, NULL, STRUCT(enrichment.tags AS tags, enrichment.explanation AS explanation)) AS enrichment
  FROM \`${PROJECT_ID}.${GOLD_DATASET}.radar_items\` item
  LEFT JOIN latest_enrichment enrichment USING (source, source_id)
  WHERE item.bronze_run_id = @run_id
  ORDER BY item.source_published_at DESC, item.source, item.source_id LIMIT 50`;

function runParameter(runId) {
  return [{ name: 'run_id', parameterType: { type: 'STRING' }, parameterValue: { value: runId } }];
}

async function buildSnapshot(req, dependencies = { googleAccessToken, bigQuery }) {
  const accessToken = await dependencies.googleAccessToken(req);
  const runs = await dependencies.bigQuery(accessToken, LATEST_RUN_SQL);
  if (!runs.length) return null;
  const run = runs[0];
  const [metrics, items] = await Promise.all([dependencies.bigQuery(accessToken, METRICS_SQL, runParameter(run.run_id)), dependencies.bigQuery(accessToken, ITEMS_SQL, runParameter(run.run_id))]);
  return { status: 'ok', generated_at: new Date().toISOString(), run: { id: run.run_id, window_start: run.window_start, window_end: run.window_end, completed_at: run.completed_at }, metrics, items };
}

module.exports = async function handler(req, res) {
  if (req.method !== 'GET') { res.setHeader('Allow', 'GET'); return res.status(405).json({ status: 'method_not_allowed' }); }
  try {
    const snapshot = await buildSnapshot(req);
    if (!snapshot) return res.status(503).json({ status: 'unavailable' });
    res.setHeader('Cache-Control', 'public, s-maxage=300, stale-while-revalidate=3600');
    return res.status(200).json(snapshot);
  } catch (error) {
    console.error('radar snapshot unavailable', error);
    return res.status(503).json({ status: 'unavailable' });
  }
};
module.exports.__test = { buildSnapshot, decodeRow, LATEST_RUN_SQL, METRICS_SQL, ITEMS_SQL, runParameter };
