// Melhorias da tabela: paginação, densidade, colunas visíveis e expansão de células.
// Convive com dashboard.js: respeita linhas ocultas pela busca (atributo hidden / display:none).
(function () {
  const root = document.querySelector('[data-datatable]');
  if (!root) return;
  const table = root.querySelector('#records-table');
  const tbody = table.tBodies[0];
  const store = (k, v) => { try { return v === undefined ? localStorage.getItem('dt:' + k) : localStorage.setItem('dt:' + k, v); } catch (_) { return null; } };

  // Densidade
  const densityBtns = root.querySelectorAll('[data-density]');
  function setDensity(d) {
    root.dataset.density = d;
    densityBtns.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.density === d)));
    store('density', d);
    markOverflow();
  }
  densityBtns.forEach(b => b.addEventListener('click', () => setDensity(b.dataset.density)));

  // Colunas visíveis
  const menu = root.querySelector('[data-column-menu]');
  const headers = Array.from(table.tHead.rows[0].cells);
  const hiddenCols = new Set(JSON.parse(store('hidden-cols') || '[]'));
  function applyCols() {
    headers.forEach((th, i) => {
      const name = th.dataset.col; if (!name) return;
      const hide = hiddenCols.has(name);
      th.classList.toggle('dt-col-hidden', hide);
      for (const row of tbody.rows) if (row.cells.length > 1 && row.cells[i]) row.cells[i].classList.toggle('dt-col-hidden', hide);
    });
    store('hidden-cols', JSON.stringify([...hiddenCols]));
  }
  headers.forEach(th => {
    const name = th.dataset.col; if (!name) return;
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = !hiddenCols.has(name);
    cb.addEventListener('change', () => { cb.checked ? hiddenCols.delete(name) : hiddenCols.add(name); applyCols(); });
    label.append(cb, document.createTextNode(name));
    menu.appendChild(label);
  });

  // Paginação
  const sizeSel = root.querySelector('[data-page-size]');
  const info = root.querySelector('[data-page-info]');
  const btn = n => root.querySelector(`[data-page="${n}"]`);
  let page = 0;
  if (store('page-size')) sizeSel.value = store('page-size');
  const dataRows = () => Array.from(tbody.querySelectorAll('tr[data-record-row]'));
  const filteredOut = r => r.hidden || r.style.display === 'none';
  let busy = false;
  function paginate() {
    if (busy) return; busy = true;
    const size = parseInt(sizeSel.value, 10);
    const visible = dataRows().filter(r => !filteredOut(r));
    const pages = size ? Math.max(1, Math.ceil(visible.length / size)) : 1;
    page = Math.min(page, pages - 1);
    dataRows().forEach(r => r.classList.remove('dt-page-hidden'));
    if (size) visible.forEach((r, i) => { if (i < page * size || i >= (page + 1) * size) r.classList.add('dt-page-hidden'); });
    const from = visible.length ? page * (size || visible.length) + 1 : 0;
    const to = size ? Math.min((page + 1) * size, visible.length) : visible.length;
    info.textContent = `${from}–${to} de ${visible.length} · pág. ${page + 1}/${pages}`;
    btn('first').disabled = btn('prev').disabled = page === 0;
    btn('last').disabled = btn('next').disabled = page >= pages - 1;
    markOverflow();
    busy = false;
  }
  sizeSel.addEventListener('change', () => { page = 0; store('page-size', sizeSel.value); paginate(); });
  btn('first').addEventListener('click', () => { page = 0; paginate(); });
  btn('prev').addEventListener('click', () => { page--; paginate(); });
  btn('next').addEventListener('click', () => { page++; paginate(); });
  btn('last').addEventListener('click', () => { page = 1e9; paginate(); });

  // Reage à busca e à ordenação feitas por dashboard.js
  let t;
  new MutationObserver(() => { if (busy) return; clearTimeout(t); t = setTimeout(paginate, 30); })
    .observe(tbody, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden', 'style'] });
  root.querySelector('#record-search')?.addEventListener('input', () => { page = 0; });

  // Expandir células longas
  function markOverflow() {
    requestAnimationFrame(() => root.querySelectorAll('.dt-cell').forEach(c => {
      c.classList.toggle('is-overflowing', c.scrollHeight > c.clientHeight + 1 || c.scrollWidth > c.clientWidth + 1);
    }));
  }
  tbody.addEventListener('click', e => {
    const cell = e.target.closest('.dt-cell');
    if (!cell || e.target.closest('a,button') || root.dataset.density === 'wrap') return;
    if (window.getSelection().toString()) return;
    cell.classList.toggle('is-expanded');
  });

  setDensity(store('density') || 'normal');
  applyCols();
  paginate();
})();
