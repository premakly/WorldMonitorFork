/* ============================================================================
   World Monitor — Note de sécurité (secu.js)
   ---------------------------------------------------------------------------
   Fichier autonome à déposer dans `docs/`, à côté de index.html.
   Une seule ligne à ajouter dans index.html, juste avant </body> :
        <script src="secu.js"></script>

   Ajoute, SANS toucher au reste d'index.html :
     • une colonne « 🛡 Fiab. aéronavale » dans le tableau (triable),
       note = (6 − indice_fiabilité) × intérêt naval ÷ 100 ;
     • la « FIABILITÉ AÉRONAVALE » par média dans les fiches source
       (moyenne des seuls articles à signal naval ≥ 1, sinon 0) ;
     • les paliers de couleur navale étendus : 31-40, 41-50, 50+.
   Réutilise les fonctions/données déjà présentes (DATA, filtered, esc, disp,
   openCountry, openSource, openTheme, openRegion, svgMap, showOverlay,
   isJunk, NONPAYS, setSort, sortKey, sortDir, page, PER).
   ========================================================================== */
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading")
      document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }

  // note de sécurité d'un article
  function secOf(r) {
    return +(((6 - (r.fi == null ? 5 : r.fi)) * (r.nv || 0)) / 100).toFixed(2);
  }

  // paliers navals étendus (31-40, 41-50, 50+)
  var NAV2 = [[10, .09], [20, .16], [30, .23], [40, .30], [50, .38], [1e9, .47]];
  function navAlpha2(nv) { for (var i = 0; i < NAV2.length; i++) if (nv <= NAV2[i][0]) return NAV2[i][1]; return .47; }
  function navStyle2(nv) { return nv > 0 ? ' style="background:rgba(246,193,60,' + navAlpha2(nv) + ')"' : ''; }

  // ---- tableau principal : colonne Sécurité + paliers étendus ----
  function newRenderTable() {
    var rows = filtered().slice();
    rows.forEach(function (r) { if (r.sec === undefined) r.sec = secOf(r); });
    rows.sort(function (a, b) {
      var va = a[sortKey] == null ? '' : a[sortKey], vb = b[sortKey] == null ? '' : b[sortKey];
      return (va < vb ? -1 : va > vb ? 1 : 0) * sortDir;
    });
    var npages = Math.max(1, Math.ceil(rows.length / PER));
    page = Math.min(page, npages - 1);
    document.getElementById('count').innerHTML = '<b>' + rows.length.toLocaleString('fr-FR') + '</b> article(s) dans la sélection';
    document.getElementById('pageinfo').textContent = 'page ' + (page + 1) + ' / ' + npages;
    document.getElementById('tbody').innerHTML = rows.slice(page * PER, (page + 1) * PER).map(function (r) {
      return '<tr' + navStyle2(r.nv) + '>' +
        '<td style="white-space:nowrap">' + (r.d ? r.d.slice(0, 10) : '—') + '</td>' +
        '<td class="mlink" data-m="' + esc(r.m) + '" onclick="openSource(this.dataset.m)" title="Ouvrir la page de cette source">' + esc(r.m) + '</td>' +
        '<td><a href="' + esc(r.l) + '" target="_blank" rel="noopener">' + esc(r.t) + '</a>' +
          (r.lg && r.lg !== 'en' ? ' <span class="badge" title="' + esc(r.tv || '') + '">🌐 ' + esc(r.lg) + '</span>' : '') + '</td>' +
        '<td><span class="badge clickbadge" data-c="' + esc(disp(r.ca)) + '" onclick="openCountry(this.dataset.c)" title="Fiche pays">' + esc(disp(r.ca)) + '</span></td>' +
        '<td><span class="clickbadge" data-r="' + esc(disp(r.rg)) + '" onclick="openRegion(this.dataset.r)" title="Fiche région">' + esc(disp(r.rg)) + '</span></td>' +
        '<td><span class="badge clickbadge" data-t="' + esc(disp(r.sa)) + '" onclick="openTheme(this.dataset.t)" title="Fiche thème">' + esc(disp(r.sa)) + '</span></td>' +
        '<td><b title="indice ' + (r.fi == null ? '—' : r.fi) + '">' + esc(r.no || 'F') + '</b></td>' +
        '<td>' + (r.nv > 0 ? '<span class="badge">⚓ ' + r.nv + '</span>' : '—') + '</td>' +
        '<td>' + (r.sec > 0 ? '<span class="badge" style="color:#e8ecf4" title="(6−fiabilité)×naval÷100">🛡 ' + r.sec.toFixed(2) + '</span>' : '<span style="color:var(--muted)">—</span>') + '</td>' +
        '</tr>';
    }).join('');
  }

  // ---- fiche média : nouvelle NOTE DE SÉCURITÉ + paliers étendus ----
  function newOpenSource(m) {
    var arts = DATA.filter(function (r) { return r.m === m; }).sort(function (a, b) { return a.d < b.d ? 1 : -1; });
    var o = arts[0] || {};
    var rated = arts.find(function (r) { return r.or != null; });
    var counts = {};
    arts.forEach(function (r) { if (r.ca && !isJunk(r.ca) && !NONPAYS.has(r.ca)) counts[r.ca] = (counts[r.ca] || 0) + 1; });

    var naveaux = arts.filter(function (r) { return r.nv >= 1; });
    var note = naveaux.length
      ? (naveaux.reduce(function (s, r) { return s + secOf(r); }, 0) / naveaux.length).toFixed(2)
      : '0.00';

    showOverlay(
      '<h1 style="font-size:1.9rem;margin-bottom:10px">' + esc(m) + '</h1>' +
      '<p style="margin-bottom:16px">' +
        '<span class="badge clickbadge" data-c="' + esc(disp(o.ch)) + '" onclick="openCountry(this.dataset.c)">🏛 Siège : ' + esc(disp(o.ch)) + '</span>' +
        '<span class="badge">🏷 Thème du média : ' + esc(disp(o.sm)) + '</span>' +
        '<span class="badge">📰 ' + arts.length + ' article(s)</span>' +
        '<span class="badge">🛡 Note : <b>' + esc(o.no || 'F') + '</b>' + (o.fi != null ? ' (indice ' + o.fi + ')' : '') + '</span>' +
        (rated ? '<span class="badge">⭐ Note officielle : ' + rated.or + '</span>' : '') +
      '</p>' +
      '<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:0 0 16px">' +
        '<div style="background:linear-gradient(135deg,#12325e,#1d4f8c);border:1px solid #2f6cbf;border-radius:12px;padding:12px 26px;text-align:center">' +
          '<b style="font-size:2.2rem;color:#7db4ff">' + note + '</b>' +
          '<div style="color:#a9c6ee;font-size:.82rem">FIABILITÉ AÉRONAVALE</div>' +
        '</div>' +
        '<div style="color:var(--muted);font-size:.9rem">' +
          '⚓ <b style="color:var(--text)">' + naveaux.length + '</b> article(s) à signal naval sur ' + arts.length + '<br>' +
          '<small>moyenne de (6−fiabilité)×naval÷100 sur les seuls articles à signal naval ≥ 1 (0 s\'il n\'y en a aucun)</small>' +
        '</div>' +
      '</div>' +
      svgMap({ counts: counts, hq: o.ch, height: 300 }) +
      '<p class="count" style="margin:6px 0 14px">Aplat de couleur = nombre d\'articles par pays traité · ★ = pays du siège · survole pour les chiffres, clique pour la fiche pays.</p>' +
      '<table><thead><tr><th>Date</th><th>Titre</th><th>Pays traité</th><th>Thème</th></tr></thead><tbody>' +
      arts.map(function (r) {
        return '<tr' + navStyle2(r.nv) + '>' +
          '<td style="white-space:nowrap">' + (r.d ? r.d.slice(0, 10) : '—') + '</td>' +
          '<td><a href="' + esc(r.l) + '" target="_blank" rel="noopener">' + esc(r.t) + '</a></td>' +
          '<td><span class="badge clickbadge" data-c="' + esc(disp(r.ca)) + '" onclick="openCountry(this.dataset.c)">' + esc(disp(r.ca)) + '</span></td>' +
          '<td><span class="badge clickbadge" data-t="' + esc(disp(r.sa)) + '" onclick="openTheme(this.dataset.t)">' + esc(disp(r.sa)) + '</span></td>' +
          '</tr>';
      }).join('') + '</tbody></table>'
    );
  }

  // ---- en-tête de colonne + légende ----
  // Reconstruit TOUT l'en-tête : écrase toute colonne « Sécurité » laissée par
  // d'anciennes modifs manuelles et garantit 9 colonnes alignées sur le rendu.
  function rebuildHeader() {
    var thead = document.getElementById('thead');
    if (!thead) return;
    var cols = [['d', 'Date'], ['m', 'Média'], ['t', 'Titre'], ['ca', 'Pays traité'],
                ['rg', 'Région'], ['sa', 'Thème'], ['no', 'Note'], ['nv', '⚓ Naval'],
                ['sec', '🛡 Fiab. aéronavale']];
    thead.innerHTML = cols.map(function (c) {
      return '<th style="cursor:pointer" onclick="setSort(\'' + c[0] + '\')">' + c[1] + ' ⇅</th>';
    }).join('');
  }

  function updateLegend() {
    var legends = document.querySelectorAll('.count');
    for (var i = 0; i < legends.length; i++) {
      if (legends[i].textContent.indexOf('signal naval') !== -1) {
        var sw = function (a, t) {
          return '<span style="display:inline-block;width:26px;height:12px;border-radius:3px;background:rgba(246,193,60,' +
            a + ');vertical-align:middle"></span> ' + t + ' ';
        };
        legends[i].innerHTML = '⚓ signal naval : ' +
          sw('.09', '1-10') + sw('.16', '11-20') + sw('.23', '21-30') +
          sw('.30', '31-40') + sw('.38', '41-50') + sw('.47', '50+') +
          '· trier via l\'en-tête ⚓';
        break;
      }
    }
  }

  // --- retire les non-pays (ASEAN, G7, WHO…) et les valeurs indéterminées des filtres pays ---
  function cleanCountryFilters() {
    ['f_ca', 'f_ch'].forEach(function (id) {
      var sel = document.getElementById(id);
      if (!sel) return;
      Array.prototype.slice.call(sel.options).forEach(function (o) {
        if (o.value && (NONPAYS.has(o.value) || (typeof isJunk === 'function' && isJunk(o.value)))) o.remove();
      });
    });
  }

  ready(function () {
    if (typeof filtered !== 'function' || typeof DATA === 'undefined') return;
    rebuildHeader();
    updateLegend();
    window.renderTable = newRenderTable;   // remplace le rendu du tableau
    window.openSource = newOpenSource;     // remplace la fiche média
    if (typeof window.buildFilters === 'function') {
      var _bf = window.buildFilters;
      window.buildFilters = function () { _bf.apply(this, arguments); cleanCountryFilters(); };
      try { window.buildFilters(); } catch (e) {}   // reconstruit les filtres sans les non-pays
    }
    try { newRenderTable(); } catch (e) {}
  });
})();
