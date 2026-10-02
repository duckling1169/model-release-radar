(() => {
  const root = document.documentElement;
  const STORAGE_KEY = 'mrr-theme';
  const sourceNames = { huggingface: 'Hugging Face', arxiv: 'arXiv' };
  const stageCopy = {
    huggingface: [
      ['Fetched', 'Records returned while paging back to the window.', 'raw_response_record_count'],
      ['In window', 'New public model repos created during the UTC day.', 'raw_window_record_count'],
      ['Qualified', 'Declare a task, or ship weights or a config.', 'silver_qualified_count'],
      ['Listed', 'Models in the feed below.', 'gold_item_count'],
    ],
    arxiv: [
      ['Fetched', 'Entries in the latest announcement feed.', 'raw_response_record_count'],
      ['In window', 'New and cross-listed papers announced that day.', 'raw_window_record_count'],
      ['Qualified', 'Parsed and in cs.AI, cs.CL or cs.LG.', 'silver_qualified_count'],
      ['Listed', 'Papers in the feed below.', 'gold_item_count'],
    ],
  };
  const state = { snapshot: null, source: 'huggingface', listSource: 'all', query: '', tags: new Set() };
  const $ = (id) => document.getElementById(id);
  const number = (value) => new Intl.NumberFormat().format(Number(value || 0));
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  };
  function relativeTime(value) {
    const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
    return `${Math.floor(seconds / 86400)} d ago`;
  }

  function storedTheme() {
    try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
  }
  if (storedTheme()) root.dataset.theme = storedTheme();
  $('theme-toggle').addEventListener('click', () => {
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem(STORAGE_KEY, root.dataset.theme); } catch { /* per-viewer convenience only */ }
  });

  function renderOverview() {
    const metric = state.snapshot.metrics.find((row) => row.source === state.source) || {};
    const stages = stageCopy[state.source].map(([name, desc, field]) => ({ name, desc, value: Number(metric[field] || 0) }));
    $('stages').replaceChildren(...stages.map((stage, index) => {
      const cell = element('div', 'stage');
      cell.append(element('span', `icon step-${index}`, String(index + 1)), element('div', 'stage-name', stage.name), element('div', 'stage-desc', stage.desc), element('div', 'stage-num', number(stage.value)));
      return cell;
    }));
    // Funnel bands: square-root scaled so the smaller stages stay visible.
    const max = Math.max(...stages.map((stage) => stage.value), 1);
    const y = (value) => 100 - Math.max(Math.sqrt(value / max), 0.04) * 92;
    const svgNs = 'http://www.w3.org/2000/svg';
    $('funnel').replaceChildren(...stages.map((stage, index) => {
      const next = stages[index + 1] || stage;
      const x0 = index * 100; const x1 = x0 + 100;
      const path = document.createElementNS(svgNs, 'path');
      path.setAttribute('d', `M${x0},${y(stage.value)} C${x0 + 50},${y(stage.value)} ${x0 + 50},${y(next.value)} ${x1},${y(next.value)} L${x1},100 L${x0},100 Z`);
      path.setAttribute('class', `band band-${index}`);
      return path;
    }));
    const [, inWindow, qualified] = stages;
    $('excluded').textContent = number(Math.max(inWindow.value - qualified.value, 0));
    $('excluded-desc').textContent = state.source === 'arxiv'
      ? 'Announced papers that failed to parse or match a category.'
      : 'No task, model artifact or config. Kept in Silver with a reason.';
    document.querySelectorAll('#source-tabs .tab').forEach((tab) => {
      const active = tab.dataset.source === state.source;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', String(active));
    });
  }

  function renderTags() {
    const tags = MrrFilters.availableTags(state.snapshot.items).filter((tag) => tag !== 'unclassified');
    const container = $('tag-filters');
    container.hidden = !tags.length;
    container.replaceChildren(...tags.map((tag) => {
      const button = element('button', `chip ${state.tags.has(tag) ? 'is-active' : ''}`, tag);
      button.type = 'button';
      button.setAttribute('aria-pressed', String(state.tags.has(tag)));
      button.addEventListener('click', () => {
        if (state.tags.has(tag)) state.tags.delete(tag); else state.tags.add(tag);
        renderTags(); renderRows();
      });
      return button;
    }));
  }

  function renderRow(item) {
    const row = element('li', 'row');
    row.append(element('span', `dot ${item.source}`));
    const main = element('div', 'row-main');
    const link = element('a', 'row-title', item.title || item.source_id);
    link.href = item.canonical_url; link.target = '_blank'; link.rel = 'noreferrer';
    main.append(link);
    MrrFilters.itemTags(item).filter((tag) => tag !== 'unclassified').forEach((tag) => main.append(element('span', 'pill', tag)));
    if (item.enrichment?.explanation) main.append(element('div', 'row-why', item.enrichment.explanation));
    const author = element('div', 'row-cell row-author');
    author.append(element('span', 'cell-label', item.source === 'arxiv' ? 'Authors' : 'Owner'), element('span', 'cell-value', item.author_or_org || '—'));
    const source = element('div', 'row-cell');
    source.append(element('span', 'cell-label', 'Source'), element('span', 'cell-value', sourceNames[item.source] || item.source));
    const time = element('time', 'row-time', relativeTime(item.source_published_at));
    time.dateTime = item.source_published_at; time.title = new Date(item.source_published_at).toLocaleString();
    row.append(main, author, source, time);
    return row;
  }

  function renderRows() {
    const query = state.query.trim().toLowerCase();
    const visible = MrrFilters.filterItems(state.snapshot.items, state.listSource, state.tags)
      .filter((item) => !query || `${item.title} ${item.author_or_org || ''}`.toLowerCase().includes(query));
    $('release-count').textContent = number(visible.length);
    $('rows').replaceChildren(...(visible.length ? visible.map(renderRow) : [element('li', 'row-empty', 'No releases match these filters.')]));
  }

  function render(snapshot) {
    state.snapshot = snapshot;
    const { run } = snapshot;
    const day = new Date(run.window_start).toLocaleDateString(undefined, { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric' });
    $('live-status').lastChild.textContent = `Updated ${relativeTime(run.completed_at)}`;
    $('window-label').textContent = `${day} · UTC window`;
    snapshot.metrics.forEach((metric) => {
      const count = document.querySelector(`[data-count="${metric.source}"]`);
      if (count) count.textContent = number(metric.gold_item_count);
    });
    $('updated').textContent = relativeTime(run.completed_at);
    $('updated-desc').textContent = `Run ${run.id}. Partial runs never replace a complete one.`;
    renderOverview(); renderTags(); renderRows();
  }

  function unavailable() {
    $('live-status').classList.add('is-down');
    $('live-status').lastChild.textContent = 'Update unavailable';
    $('rows').replaceChildren(element('li', 'row-empty', 'The latest update couldn’t be loaded. Try again in a moment.'));
  }

  $('source-tabs').addEventListener('click', (event) => {
    const tab = event.target.closest('[data-source]');
    if (!tab || !state.snapshot) return;
    state.source = tab.dataset.source; renderOverview();
  });
  $('source-filter').addEventListener('change', (event) => { state.listSource = event.target.value; if (state.snapshot) renderRows(); });
  $('search').addEventListener('input', (event) => { state.query = event.target.value; if (state.snapshot) renderRows(); });

  fetch('/api/radar')
    .then((response) => (response.ok ? response.json() : Promise.reject(new Error(`Radar API ${response.status}`))))
    .then((snapshot) => (snapshot.status === 'ok' ? render(snapshot) : unavailable()))
    .catch(unavailable);
})();
