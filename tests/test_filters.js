const assert = require('node:assert/strict');
const test = require('node:test');
const { availableTags, filterItems, itemTags } = require('../filter.js');

const items = [
  { source: 'arxiv', source_id: 'first', enrichment: { tags: ['vision'] } },
  { source: 'huggingface', source_id: 'second', enrichment: { tags: ['code', 'agents'] } },
  { source: 'arxiv', source_id: 'third', enrichment: { tags: ['language', 'not-a-controlled-tag'] } },
  { source: 'huggingface', source_id: 'fourth' },
];

test('derives controlled classifications and defaults unenriched items to unclassified', () => {
  assert.deepEqual(itemTags(items[2]), ['language']);
  assert.deepEqual(itemTags(items[3]), ['unclassified']);
  assert.deepEqual(availableTags(items), ['agents', 'code', 'language', 'unclassified', 'vision']);
  assert.deepEqual(availableTags([{ source: 'arxiv' }]), ['unclassified']);
});

test('filters sources without changing source-publication order', () => {
  assert.deepEqual(filterItems(items, 'arxiv', new Set()).map((item) => item.source_id), ['first', 'third']);
  assert.deepEqual(filterItems(items, 'huggingface', new Set()).map((item) => item.source_id), ['second', 'fourth']);
});

test('matches any selected tag and intersects it with the selected source', () => {
  assert.deepEqual(filterItems(items, 'all', new Set(['vision', 'agents'])).map((item) => item.source_id), ['first', 'second']);
  assert.deepEqual(filterItems(items, 'huggingface', new Set(['vision', 'agents'])).map((item) => item.source_id), ['second']);
});

test('returns an empty collection when no item matches the filters', () => {
  assert.deepEqual(filterItems(items, 'arxiv', new Set(['code'])), []);
});
