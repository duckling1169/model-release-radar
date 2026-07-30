(function (root, factory) {
  const filters = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = filters;
  root.MrrFilters = filters;
})(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  const taxonomy = new Set(['language', 'vision', 'audio', 'multimodal', 'code', 'embedding', 'agents', 'robotics', 'science', 'safety', 'infrastructure', 'other']);

  function itemTags(item) {
    const tags = item?.enrichment?.tags;
    const controlled = Array.isArray(tags) ? [...new Set(tags.filter((tag) => taxonomy.has(tag)))] : [];
    return controlled.length ? controlled : ['unclassified'];
  }

  function availableTags(items) {
    return [...new Set(items.flatMap(itemTags))].sort();
  }

  function filterItems(items, source, selectedTags) {
    return items.filter((item) => {
      const sourceMatches = source === 'all' || item.source === source;
      const tags = itemTags(item);
      const tagsMatch = !selectedTags.size || tags.some((tag) => selectedTags.has(tag));
      return sourceMatches && tagsMatch;
    });
  }

  return { availableTags, filterItems, itemTags };
});
