(() => {
  const root = document.documentElement;
  const toggleBtn = document.getElementById('theme-toggle');
  const STORAGE_KEY = 'mrr-theme';
  const sourceNames = { huggingface: 'Hugging Face', arxiv: 'arXiv' };
  const filters = { source: 'all', tags: new Set() };
  const systemPrefersDark = () => window.matchMedia('(prefers-color-scheme: dark)').matches;
  const setText = (id, value) => { document.getElementById(id).textContent = value; };
  const formatNumber = (value) => new Intl.NumberFormat().format(Number(value || 0));
  const clear = (node) => node.replaceChildren();
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  };
  function applyTheme(theme) { root.setAttribute('data-theme', theme); toggleBtn.textContent = theme === 'dark' ? '☀ Light' : '● Dark'; }
  function relativeTime(value) {
    const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }
  applyTheme(localStorage.getItem(STORAGE_KEY) || (systemPrefersDark() ? 'dark' : 'light'));
  toggleBtn.addEventListener('click', () => { const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'; applyTheme(next); localStorage.setItem(STORAGE_KEY, next); });

  function showUnavailable() {
    setText('live-status', 'Update unavailable');
    setText('radar-subtitle', 'We couldn’t load the latest update. Please try again in a moment.');
    ['source-count', 'item-count', 'reconciled-count'].forEach((id) => setText(id, '—'));
    const grid = document.getElementById('radar-grid'); clear(grid); grid.append(element('p', 'empty-state', 'No releases are available right now.'));
    setText('filter-count', 'Releases unavailable');
    const rows = document.getElementById('metrics-rows'); clear(rows); rows.append(element('div', 'table-row table-row-last muted', 'Source counts are unavailable.'));
    setText('table-footnote', 'Only complete updates appear here; the next one will show when it is ready.');
  }
  const itemTags = MrrFilters.itemTags;
  function updateSelected(button, selected) {
    button.classList.toggle('is-selected', selected);
    button.setAttribute('aria-pressed', String(selected));
  }
  function renderTagFilters(items) {
    const tagFilters = document.getElementById('tag-filters');
    const tags = MrrFilters.availableTags(items);
    clear(tagFilters);
    if (!tags.length) {
      filters.tags.clear();
      const unavailable = element('button', 'filter-chip filter-empty', 'Tags appear after a release is categorized');
      unavailable.type = 'button'; unavailable.disabled = true;
      tagFilters.append(unavailable);
      return;
    }
    filters.tags.forEach((tag) => { if (!tags.includes(tag)) filters.tags.delete(tag); });
    tags.forEach((tag) => {
      const button = element('button', `filter-chip ${filters.tags.has(tag) ? 'is-selected' : ''}`, tag);
      button.type = 'button';
      button.dataset.tag = tag;
      button.setAttribute('aria-pressed', String(filters.tags.has(tag)));
      button.addEventListener('click', () => {
        if (filters.tags.has(tag)) filters.tags.delete(tag); else filters.tags.add(tag);
        updateSelected(button, filters.tags.has(tag));
        renderFilteredItems(items);
      });
      tagFilters.append(button);
    });
  }
  function filteredItems(items) {
    return MrrFilters.filterItems(items, filters.source, filters.tags);
  }
  function renderFilteredItems(items) {
    const visible = filteredItems(items);
    setText('filter-count', `${visible.length} ${visible.length === 1 ? 'release' : 'releases'}`);
    const grid = document.getElementById('radar-grid'); clear(grid);
    if (visible.length) visible.forEach((item) => grid.append(renderCard(item)));
    else grid.append(element('p', 'empty-state', 'No releases match these filters. Try another source or tag.'));
  }
  document.getElementById('source-filters').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-source]');
    if (!button) return;
    filters.source = button.dataset.source;
    document.querySelectorAll('#source-filters button').forEach((control) => updateSelected(control, control === button));
    if (window.radarItems) renderFilteredItems(window.radarItems);
  });
  function renderCard(item) {
    const card = element('article', `card ${item.source === 'arxiv' ? 'card-teal' : 'card-indigo'}`);
    const top = element('div', 'card-top'); top.append(element('span', 'card-source', sourceNames[item.source] || item.source));
    const link = element('a', 'card-title', item.title || item.source_id); link.href = item.canonical_url; link.target = '_blank'; link.rel = 'noreferrer';
    card.append(top, link);
    if (item.summary) card.append(element('div', 'card-desc', item.summary));
    if (item.author_or_org) card.append(element('div', 'card-desc card-author', item.author_or_org));
    if (item.enrichment) {
      const tagsForItem = itemTags(item);
      if (tagsForItem.length) {
        const tags = element('div', 'enrichment-tags');
        tagsForItem.forEach((tag) => tags.append(element('span', 'enrichment-tag', tag)));
        card.append(tags);
      }
      if (item.enrichment.explanation) {
        const why = element('div', 'enrichment-why');
        why.append(element('span', 'enrichment-label', 'Why it matters'), document.createTextNode(item.enrichment.explanation));
        card.append(why);
      }
    }
    card.append(element('div', 'card-time', `${relativeTime(item.source_published_at)} · ${new Date(item.source_published_at).toLocaleString()}`));
    return card;
  }
  function renderMetrics(metrics, completedAt) {
    const rows = document.getElementById('metrics-rows'); clear(rows);
    let rawTotal = 0; let displayedTotal = 0;
    metrics.forEach((metric, index) => {
      const raw = Number(metric.raw_window_record_count || 0);
      const firstSeen = Number(metric.silver_inserted_count || 0);
      const goldItems = Number(metric.gold_item_count || 0);
      rawTotal += raw; displayedTotal += goldItems;
      const row = element('div', `table-row ${index === metrics.length - 1 ? 'table-row-last' : ''}`);
      row.append(element('div', '', sourceNames[metric.source] || metric.source), element('div', 'mono', formatNumber(raw)), element('div', 'mono', formatNumber(firstSeen)), element('div', `mono ${metric.source === 'arxiv' ? 'match-indigo' : 'match-teal'}`, formatNumber(goldItems)), element('div', 'align-right mono muted', relativeTime(completedAt)));
      rows.append(row);
    });
    setText('source-count', String(metrics.length)); setText('item-count', formatNumber(displayedTotal)); setText('reconciled-count', `${formatNumber(rawTotal)} → ${formatNumber(displayedTotal)}`);
  }
  function renderSnapshot(snapshot) {
    setText('live-status', `Latest update · ${relativeTime(snapshot.run.completed_at)}`);
    setText('radar-subtitle', `New items from the update ending ${new Date(snapshot.run.window_end).toLocaleString()}.`);
    window.radarItems = snapshot.items;
    renderTagFilters(snapshot.items);
    renderFilteredItems(snapshot.items);
    renderMetrics(snapshot.metrics, snapshot.run.completed_at);
    setText('table-footnote', `Update ${snapshot.run.id} finished ${relativeTime(snapshot.run.completed_at)}. Showing ${snapshot.metrics.length} sources; partial updates stay out of this view.`);
  }
  fetch('/api/radar').then((response) => response.ok ? response.json() : Promise.reject(new Error(`Radar API ${response.status}`))).then((snapshot) => snapshot.status === 'ok' ? renderSnapshot(snapshot) : showUnavailable()).catch(showUnavailable);
})();
