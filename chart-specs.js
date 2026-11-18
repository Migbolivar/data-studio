/* BMOPS Data Studio — generador de especificaciones de gráficos
 *
 * Problema que resuelve: la versión anterior solo pintaba gráficos si había
 * columnas de texto (categóricas) y/o de fecha. Con un dataset puramente
 * numérico como el clásico Wine (13 features + class), se quedaba en 1 gráfico
 * de 4 porque `class` es numérica aunque en realidad sea una categoría.
 *
 * Aquí se detectan columnas "categóricas de verdad" (texto, o números con muy
 * pocos valores únicos como class=1/2/3) y se generan SIEMPRE cuatro gráficos,
 * degradando a histogramas/dispersión cuando no hay categorías.
 *
 * Se puede probar sin navegador: module.exports al final.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ChartSpecs = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const toNum = (v) => {
    if (typeof v === 'number') return isFinite(v) ? v : NaN;
    if (v === null || v === undefined) return NaN;
    const n = parseFloat(String(v).replace(/[^0-9.,-]/g, '').replace(',', '.'));
    return isFinite(n) ? n : NaN;
  };

  const isIntLike = (v) => {
    const n = toNum(v);
    return isFinite(n) && Math.abs(n - Math.round(n)) < 1e-9;
  };

  const uniq = (arr) => Array.from(new Set(arr));
  const mean = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0);
  const cv = (arr) => {
    if (!arr.length) return 0;
    const m = mean(arr);
    const v = mean(arr.map((x) => (x - m) ** 2));
    return m === 0 ? 0 : Math.sqrt(v) / Math.abs(m);
  };

  const fmt = (v) => {
    if (!isFinite(v)) return '—';
    const a = Math.abs(v);
    if (a >= 1000) return v.toLocaleString('es-ES', { maximumFractionDigits: 0 });
    if (a >= 10) return v.toLocaleString('es-ES', { maximumFractionDigits: 1 });
    return v.toLocaleString('es-ES', { maximumFractionDigits: 2 });
  };

  const PALETTE = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#06b6d4', '#a855f7', '#eab308', '#14b8a6'];

  /* ---------- detección de tipos ---------- */
  function detectTypes(rows, columns) {
    const numeric = [];
    const text = [];
    const date = [];
    const categoricalNumeric = [];

    columns.forEach((col) => {
      const raw = rows.map((r) => r[col]).filter((v) => v !== null && v !== undefined && v !== '');
      if (!raw.length) return;

      const nums = raw.map(toNum);
      const numericRatio = nums.filter(isFinite).length / raw.length;
      const uniqueRaw = uniq(raw.map(String));

      const looksDate = raw.slice(0, 60).every((v) => {
        if (typeof v === 'number') return false;
        const s = String(v).trim();
        return /^\d{4}-\d{2}(-\d{2})?/.test(s) || /^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$/.test(s);
      });
      if (looksDate && uniqueRaw.length > 2) { date.push(col); return; }

      if (numericRatio >= 0.9) {
        numeric.push(col);
        // entero y con pocos valores distintos => categoría disfrazada (class, año, código)
        if (uniqueRaw.length <= 20 && raw.every(isIntLike)) categoricalNumeric.push(col);
        return;
      }

      if (uniqueRaw.length <= 40) { text.push(col); return; }
      // texto libre de alta cardinalidad: no se usa para agrupar
    });

    return { numeric, text, date, categoricalNumeric };
  }

  const pickCategory = (rows, types) => {
    const candidates = [...types.text, ...types.categoricalNumeric]
      .map((col) => ({ col, n: uniq(rows.map((r) => String(r[col]))).length }))
      .filter((c) => c.n >= 2 && c.n <= 20)
      .sort((a, b) => a.n - b.n);           // menos categorías primero: más legible
    return candidates.length ? candidates[0].col : null;
  };

  const numericFeatures = (rows, types, exclude) =>
    types.numeric
      .filter((c) => c !== exclude && !types.categoricalNumeric.includes(c))
      .map((col) => ({ col, spread: cv(rows.map((r) => toNum(r[col])).filter(isFinite)) }))
      .filter((x) => x.spread > 0)
      .sort((a, b) => b.spread - a.spread)
      .map((x) => x.col);

  const countBy = (rows, col) => {
    const m = new Map();
    rows.forEach((r) => {
      const k = r[col] === null || r[col] === undefined || r[col] === '' ? 'N/A' : String(r[col]);
      m.set(k, (m.get(k) || 0) + 1);
    });
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  };

  const meanBy = (rows, catCol, numCol) => {
    const acc = new Map();
    rows.forEach((r) => {
      const k = String(r[catCol]);
      const v = toNum(r[numCol]);
      if (!isFinite(v)) return;
      const cur = acc.get(k) || { sum: 0, n: 0 };
      cur.sum += v; cur.n += 1;
      acc.set(k, cur);
    });
    return [...acc.entries()]
      .map(([k, s]) => [k, s.sum / s.n, s.n])
      .sort((a, b) => b[1] - a[1]);
  };

  const histogram = (values, bins) => {
    const vals = values.filter(isFinite);
    if (!vals.length) return { labels: [], data: [] };
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const step = (max - min) / bins || 1;
    const buckets = Array(bins).fill(0);
    vals.forEach((v) => {
      const i = Math.min(Math.floor((v - min) / step), bins - 1);
      buckets[i] += 1;
    });
    const labels = Array.from({ length: bins }, (_, i) => `${fmt(min + i * step)}–${fmt(min + (i + 1) * step)}`);
    return { labels, data: buckets };
  };

  const baseScales = (horizontal) => ({
    x: horizontal
      ? { grid: { color: 'rgba(140,140,170,0.18)' }, ticks: { color: '#a0a0b8' } }
      : { grid: { display: false }, ticks: { color: '#a0a0b8', maxRotation: 45 } },
    y: horizontal
      ? { grid: { display: false }, ticks: { color: '#a0a0b8' } }
      : { grid: { color: 'rgba(140,140,170,0.18)' }, ticks: { color: '#a0a0b8' } },
  });


  /* Nombres de categoría: salen del archivo, nunca de una lista fija.
   * - columna de texto -> sus valores
   * - columna de códigos -> se busca otra columna que actúe de etiqueta
   *   (una fila = un nombre por código); si no existe, "<columna> <valor>".
   */
  function resolveCategoryLabels(rows, catCol) {
    const labels = new Map();
    if (!rows.length || !catCol) return labels;

    const valores = uniq(rows.map((r) => String(r[catCol])));
    const esCodigo = rows.every((r) => {
      const n = toNum(r[catCol]);
      return isFinite(n) && Math.abs(n - Math.round(n)) < 1e-9;
    });
    if (!esCodigo) {                       // columna de texto: el valor ya es el nombre
      valores.forEach((v) => labels.set(v, v));
      return labels;
    }

    // ¿hay una columna de texto con correspondencia 1:1 con los códigos?
    const otras = Object.keys(rows[0]).filter((c) => c !== catCol);
    let mejor = null;
    otras.forEach((col) => {
      const pares = new Map();
      let ok = true;
      rows.forEach((r) => {
        const k = String(r[catCol]);
        const v = r[col];
        if (v === null || v === undefined || v === '') return;
        if (typeof v === 'number') { ok = false; return; }
        if (pares.has(k) && pares.get(k) !== String(v)) ok = false;
        else pares.set(k, String(v));
      });
      if (ok && pares.size === valores.length) {
        const unicosNombre = uniq([...pares.values()]);
        if (unicosNombre.length === valores.length && (!mejor || col.length < mejor.col.length)) {
          mejor = { col, pares };
        }
      }
    });

    valores.forEach((v) => {
      labels.set(v, mejor ? mejor.pares.get(v) : `${catCol} ${v}`);
    });
    return labels;
  }

  /* Aplica filtros {columna: valor | {min,max}} a las filas. */
  function applyFilters(rows, filters) {
    const keys = Object.keys(filters || {});
    if (!keys.length) return rows;
    return rows.filter((r) => keys.every((col) => {
      const f = filters[col];
      if (f === null || f === undefined || f === '') return true;
      if (typeof f === 'object') {
        const v = toNum(r[col]);
        if (!isFinite(v)) return false;
        if (f.min !== undefined && f.min !== '' && v < toNum(f.min)) return false;
        if (f.max !== undefined && f.max !== '' && v > toNum(f.max)) return false;
        return true;
      }
      return String(r[col]) === String(f);
    }));
  }

  /* Definiciones de filtros derivadas del archivo: categóricos, rangos y fecha. */
  function buildFilterDefs(rows, columns, types) {
    const defs = [];
    if (!rows.length) return defs;

    const cats = [...types.text, ...types.categoricalNumeric];
    const nText = new Map(types.text.map((c) => [c, uniq(rows.map((r) => String(r[c]))).length]));
    cats.forEach((col) => {
      const nCol = uniq(rows.map((r) => String(r[col]))).length;
      const etiquetada = [...nText.values()].includes(nCol) && !types.text.includes(col);
      if (etiquetada) return;              // el nombre ya lo aporta la columna de texto
      const labels = resolveCategoryLabels(rows, col);
      const counts = new Map();
      rows.forEach((r) => {
        const k = String(r[col]);
        counts.set(k, (counts.get(k) || 0) + 1);
      });
      if (counts.size < 2 || counts.size > 20) return;
      defs.push({
        col, kind: 'select',
        options: [...counts.entries()]
          .sort((a, b) => b[1] - a[1])
          .map(([value, n]) => ({ value, label: labels.get(value) || value, n })),
      });
    });

    const features = numericFeatures(rows, types, null).slice(0, 2);
    features.forEach((col) => {
      const vals = rows.map((r) => toNum(r[col])).filter(isFinite);
      if (vals.length < 2) return;
      defs.push({
        col, kind: 'range',
        min: Math.min(...vals), max: Math.max(...vals),
        step: (Math.max(...vals) - Math.min(...vals)) / 100 || 1,
      });
    });

    if (types.date.length) {
      defs.push({ col: types.date[0], kind: 'date' });
    }

    return defs;
  }

  /* Plugin de Chart.js: escribe el valor encima de cada barra / punto / porción. */
  const dataLabelsPlugin = {
    id: 'bmopsDataLabels',
    afterDatasetsDraw(chart, _args, opts) {
      const cfg = (opts || {});
      if (cfg.enabled === false) return;
      const { ctx } = chart;
      ctx.save();
      ctx.font = `600 ${cfg.fontSize || 10}px Inter, system-ui, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      chart.data.datasets.forEach((ds, di) => {
        const meta = chart.getDatasetMeta(di);
        if (!meta || meta.hidden) return;
        const fmt = cfg.format || ((v) => (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('es-ES') : (Math.round(v * 100) / 100).toLocaleString('es-ES')));
        meta.data.forEach((el, i) => {
          const raw = ds.data[i];
          if (raw === null || raw === undefined || !isFinite(raw)) return;
          let text = fmt(raw);
          if (chart.config.type === 'doughnut' || chart.config.type === 'pie') {
            const total = ds.data.reduce((a, b) => a + (isFinite(b) ? b : 0), 0);
            text = total ? `${Math.round((raw / total) * 1000) / 10}%` : text;
            const p = el.tooltipPosition();
            ctx.fillStyle = '#0a0a0f';
            ctx.fillText(text, p.x, p.y);
            return;
          }
          if (chart.options.indexAxis === 'y') {
            ctx.fillStyle = cfg.color || '#e8e8f0';
            ctx.textAlign = 'left';
            ctx.fillText(text, el.x + 6, el.y);
            ctx.textAlign = 'center';
          } else {
            ctx.fillStyle = cfg.color || '#e8e8f0';
            ctx.fillText(text, el.x, el.y - 9);
          }
        });
      });
      ctx.restore();
    },
  };

  /* ---------- generador principal ---------- */
  function buildChartSpecs(input) {
    const rows = (input && input.rows) || [];
    const columns = (input && input.columns) || (rows[0] ? Object.keys(rows[0]) : []);
    const types = (input && input.types) || detectTypes(rows, columns);
    const specs = [];

    if (!rows.length) return specs;

    const cat = pickCategory(rows, types);
    const catLabels = cat ? resolveCategoryLabels(rows, cat) : new Map();
    const labelOf = (v) => catLabels.get(String(v)) || String(v);
    const features = numericFeatures(rows, types, cat);
    const f1 = features[0];
    const f2 = features[1] || features[0];
    const counts = cat ? countBy(rows, cat) : [];

    /* 1 · distribución por categoría, o histograma del primer feature */
    if (cat) {
      specs.push({
        id: 'chart1',
        title: `Distribución por ${cat} (registros)`,
        config: {
          type: 'bar',
          data: {
            labels: counts.slice(0, 15).map((e) => labelOf(e[0]).substring(0, 22)),
            datasets: [{
              label: 'Registros',
              data: counts.slice(0, 15).map((e) => e[1]),
              backgroundColor: counts.slice(0, 15).map((_, i) => `hsla(${250 + i * 15},70%,65%,0.7)`),
              borderColor: counts.slice(0, 15).map((_, i) => `hsl(${250 + i * 15},70%,65%)`),
              borderWidth: 1, borderRadius: 6,
            }],
          },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: baseScales(false) },
        },
      });
    } else if (f1) {
      const h = histogram(rows.map((r) => toNum(r[f1])), 10);
      specs.push({
        id: 'chart1',
        title: `Distribución de ${f1}`,
        config: {
          type: 'bar',
          data: { labels: h.labels, datasets: [{ label: 'Frecuencia', data: h.data, backgroundColor: 'rgba(99,102,241,0.6)', borderRadius: 6 }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: baseScales(false) },
        },
      });
    }

    /* 2 · serie temporal, o media del feature más disperso por categoría */
    if (types.date.length) {
      const col = types.date[0];
      const byDate = new Map();
      rows.forEach((r) => {
        let d = r[col];
        if (typeof d === 'number') d = new Date((d - 25569) * 86400 * 1000).toISOString().slice(0, 10);
        else { const p = new Date(d); if (!isNaN(p)) d = p.toISOString().slice(0, 10); }
        if (d) byDate.set(d, (byDate.get(d) || 0) + 1);
      });
      const entries = [...byDate.entries()].sort();
      specs.push({
        id: 'chart2',
        title: `Tendencia temporal (${col})`,
        config: {
          type: 'line',
          data: {
            labels: entries.map((e) => e[0]),
            datasets: [{ label: 'Registros', data: entries.map((e) => e[1]), borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)', fill: true, tension: 0.4, pointRadius: 3, pointBackgroundColor: '#6366f1' }],
          },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { color: '#a0a0b8', maxTicksLimit: 10, maxRotation: 45 } }, y: { grid: { color: 'rgba(140,140,170,0.18)' }, ticks: { color: '#a0a0b8' } } } },
        },
      });
    } else if (cat && f1) {
      const m = meanBy(rows, cat, f1);
      specs.push({
        id: 'chart2',
        title: `Media de ${f1} por ${cat}`,
        config: {
          type: 'bar',
          data: {
            labels: m.map((e) => labelOf(e[0]).substring(0, 22)),
            datasets: [{ label: `Media de ${f1}`, data: m.map((e) => Number(e[1].toFixed(4))), backgroundColor: 'rgba(34,197,94,0.65)', borderColor: '#22c55e', borderWidth: 1, borderRadius: 6 }],
          },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: baseScales(false) },
        },
      });
    } else if (f1) {
      const vals = rows.map((r) => toNum(r[f1]));       // dispersión mínima: histograma de reserva
      const h = histogram(vals, 10);
      specs.push({
        id: 'chart2',
        title: `Histograma de ${f1}`,
        config: {
          type: 'bar',
          data: { labels: h.labels, datasets: [{ label: 'Frecuencia', data: h.data, backgroundColor: 'rgba(34,197,94,0.6)', borderRadius: 6 }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: baseScales(false) },
        },
      });
    }

    /* 3 · composición: tarta por categoría, o reparto de valores del feature 2 */
    if (cat) {
      specs.push({
        id: 'chart3',
        title: `Composición por ${cat} (%)`,
        config: {
          type: 'doughnut',
          data: {
            labels: counts.slice(0, 8).map((e) => labelOf(e[0]).substring(0, 20)),
            datasets: [{ data: counts.slice(0, 8).map((e) => e[1]), backgroundColor: counts.slice(0, 8).map((_, i) => `hsla(${i * 45},70%,60%,0.85)`), borderColor: '#111118', borderWidth: 2 }],
          },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: '#a0a0b8', padding: 12, font: { size: 11 } } } } },
        },
      });
    } else if (f2) {
      const m = meanBy(rows.map((r, i) => ({ ...r, __i: String(i + 1) })), '__i', f2).slice(0, 8);
      specs.push({
        id: 'chart3',
        title: `Reparto de ${f2} (top 8 registros)`,
        config: {
          type: 'doughnut',
          data: { labels: m.map((e) => `#${e[0]}`), datasets: [{ data: m.map((e) => Number(e[1].toFixed(2))), backgroundColor: m.map((_, i) => PALETTE[i % PALETTE.length]), borderColor: '#111118', borderWidth: 2 }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: '#a0a0b8', padding: 12, font: { size: 11 } } } } },
        },
      });
    }

    /* 4 · barras horizontales: media del segundo feature por categoría */
    if (cat && f2) {
      const m = meanBy(rows, cat, f2);
      specs.push({
        id: 'chart4',
        title: `Media de ${f2} por ${cat}`,
        config: {
          type: 'bar',
          data: { labels: m.map((e) => labelOf(e[0]).substring(0, 22)), datasets: [{ label: `Media de ${f2}`, data: m.map((e) => Number(e[1].toFixed(4))), backgroundColor: 'rgba(99,102,241,0.7)', borderRadius: 6 }] },
          options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: baseScales(true) },
        },
      });
    } else if (f1) {
      const rowsSorted = rows
        .map((r, i) => ({ label: `#${i + 1}`, v: toNum(r[f1]) }))
        .filter((x) => isFinite(x.v))
        .sort((a, b) => b.v - a.v)
        .slice(0, 10);
      specs.push({
        id: 'chart4',
        title: `Top 10 · ${f1}`,
        config: {
          type: 'bar',
          data: { labels: rowsSorted.map((x) => x.label), datasets: [{ label: f1, data: rowsSorted.map((x) => x.v), backgroundColor: 'rgba(99,102,241,0.7)', borderRadius: 6 }] },
          options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: baseScales(true) },
        },
      });
    }

    return specs;
  }

  return { buildChartSpecs, detectTypes, toNum, meanBy, countBy, histogram, resolveCategoryLabels, applyFilters, buildFilterDefs, dataLabelsPlugin };
});
