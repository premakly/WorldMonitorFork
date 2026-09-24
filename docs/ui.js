/* ============================================================================
   World Monitor — Onglet Graphiques croisés : style + options (ui.js)
   ---------------------------------------------------------------------------
   Fichier autonome à déposer dans `docs/`, à côté de index.html.
   Une seule ligne à ajouter dans index.html, juste avant </body> :
        <script src="ui.js"></script>

   Fait, sans toucher au reste d'index.html :
     • uniformise l'onglet « Graphiques croisés » avec le thème sombre
       (titre + menus sur fond bleu, comme Cartographie et Graphe) ;
     • ajoute une dimension « Jour » sur l'axe X (jour par jour) ;
     • trie Jour / Mois / Année du PLUS RÉCENT au plus ancien.
   ========================================================================== */
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }

  // dimensions temporelles → tri chronologique décroissant (récent d'abord)
  function isDateDim(d) { return d === "jour" || d === "mois" || d === "an"; }

  // renderChart réécrit : identique à l'original, sauf (1) calcul de r.jour,
  // (2) tri des dimensions temporelles du plus récent au plus ancien.
  function newRenderChart() {
    document.getElementById('chartmsg').style.display = 'none';
    var rows = filtered();
    rows.forEach(function (r) { if (r.jour === undefined) r.jour = r.d ? r.d.slice(0, 10) : ''; });
    var dim = cx.value, measure = document.getElementById('cm').value;
    var split = cs.value, type = document.getElementById('ct').value;
    var topN = +document.getElementById('cn').value;
    var mLabel = document.getElementById('cm').selectedOptions[0].text;

    var entries = agg(rows, dim, measure);
    var junkDim = function (v) { return isJunk(v) || ((dim === 'ca' || dim === 'ch') && NONPAYS.has(v)); };
    var exclTotal = entries.filter(function (e) { return junkDim(e[0]); }).reduce(function (s, e) { return s + e[1]; }, 0);
    entries = entries.filter(function (e) { return !junkDim(e[0]); });
    // ---- changement : dates du plus récent au plus ancien ; sinon par valeur ----
    entries.sort(isDateDim(dim)
      ? function (a, b) { return a[0] < b[0] ? 1 : a[0] > b[0] ? -1 : 0; }
      : function (a, b) { return b[1] - a[1]; });
    entries = entries.slice(0, topN);
    var labels = entries.map(function (e) { return e[0]; });

    var datasets;
    if (split && type !== 'pie' && type !== 'doughnut') {
      var splitVals = agg(rows, split, 'count').filter(function (e) {
        return !(isJunk(e[0]) || ((split === 'ca' || split === 'ch') && NONPAYS.has(e[0])));
      }).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 8).map(function (e) { return e[0]; });
      datasets = splitVals.map(function (sv, i) {
        return {
          label: sv,
          data: labels.map(function (l) {
            var sub = rows.filter(function (r) { return disp(r[dim]) === l && disp(r[split]) === sv; });
            var e = agg(sub, dim, measure);
            return e.length ? e[0][1] : 0;
          }),
          backgroundColor: PALETTE[i % PALETTE.length]
        };
      });
    } else {
      datasets = [{
        label: mLabel, data: entries.map(function (e) { return e[1]; }),
        backgroundColor: (type === 'pie' || type === 'doughnut') ? labels.map(function (_, i) { return PALETTE[i % PALETTE.length]; }) : PALETTE[0]
      }];
    }

    var title = mLabel + ' par ' + FIELDS[dim].label.toLowerCase() +
      (split ? ' — découpé par ' + FIELDS[split].label.toLowerCase() : '') +
      ' (' + rows.length.toLocaleString('fr-FR') + ' articles)';
    drawChart({ type: type, labels: labels, datasets: datasets, stacked: !!split && type !== 'pie' && type !== 'doughnut', title: title });
    var note = document.getElementById('chartnote');
    if (exclTotal > 0) {
      note.style.display = 'block';
      note.innerHTML = '<b>' + exclTotal.toLocaleString('fr-FR') + '</b> non classé(s)<br><small>' +
        mLabel.toLowerCase() + ' avec ' + FIELDS[dim].label.toLowerCase() +
        ' indéterminé, inclassable' + ((dim === 'ca' || dim === 'ch') ? ' ou hors-pays (ASEAN, G7, FIFA…)' : '') +
        ' — exclus du graphique</small>';
    } else note.style.display = 'none';
    chart = true;
  }

  ready(function () {
    // 1) thème sombre pour l'onglet + les options (comme carto / graphe)
    if (!document.getElementById("wm-charts-style")) {
      var st = document.createElement("style");
      st.id = "wm-charts-style";
      st.textContent =
        "#tab-charts{background:var(--panel2);border-color:var(--border)}" +
        "#tab-charts .chartctl label{color:var(--muted)}" +
        "#tab-charts select{background:var(--panel);color:var(--text);border-color:var(--border)}" +
        "#tab-charts select:focus{outline:2px solid var(--accent)}" +
        "#tab-charts .hint{color:var(--muted)}";
      document.head.appendChild(st);
    }

    // 2) titre + intro en haut de l'onglet
    var panel = document.getElementById("tab-charts");
    if (panel && !document.getElementById("wm-charts-title")) {
      var intro = document.createElement("p");
      intro.className = "count";
      intro.style.marginBottom = "14px";
      intro.innerHTML = "Compose un graphique à partir de la sélection courante de l'onglet " +
        "<b>Explorer</b> : choisis une dimension, une mesure, un type, puis <b>Créer le graphique</b>.";
      var h = document.createElement("h2");
      h.id = "wm-charts-title";
      h.style.marginBottom = "6px";
      h.textContent = "📊 Graphiques croisés";
      panel.insertBefore(intro, panel.firstChild);
      panel.insertBefore(h, panel.firstChild);
    }

    // 3) dimension « Jour » : ajout dans FIELDS + dans les menus X et découpage
    try {
      if (typeof FIELDS !== "undefined" && !FIELDS.jour) FIELDS.jour = { label: "Jour", filter: false };
      ["cx", "cs"].forEach(function (id) {
        var sel = document.getElementById(id);
        if (sel && !sel.querySelector('option[value="jour"]')) {
          var o = document.createElement("option");
          o.value = "jour"; o.textContent = "Jour";
          sel.appendChild(o);
        }
      });
    } catch (e) {}

    // 4) tri chronologique récent-d'abord : on remplace renderChart
    if (typeof window.renderChart === "function") window.renderChart = newRenderChart;
  });
})();
