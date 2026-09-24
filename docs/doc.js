/* ============================================================================
   World Monitor — Onglet Documentation (doc.js)
   ---------------------------------------------------------------------------
   Fichier autonome à déposer dans `docs/`, à côté de index.html.
   Une seule ligne à ajouter dans index.html, juste avant </body>
   (de préférence APRÈS carto.js et graph.js pour que l'onglet soit tout à droite) :
        <script src="doc.js"></script>

   Ajoute un onglet ROUGE « Documentation » à droite de la barre : un mini-blog
   de billets académiques. Pour AJOUTER UN BILLET, copie un bloc dans le tableau
   POSTS ci-dessous (le plus récent en haut). Le corps `body` accepte du HTML
   simple : <h3>, <p>, <ul><li>, <blockquote>, <a href>, <b>, <i>.
   ========================================================================== */
(function () {
  "use strict";

  /* =========================== LES BILLETS ==================================
     Modèle d'un billet :
     {
       id: "identifiant-unique",
       title: "Titre du billet",
       author: "Auteur",
       date: "2026-07-15",
       tags: ["méthodologie", "indice"],
       summary: "Résumé court (affiché en abstract).",
       body: `<p>…</p><h3>Section</h3><p>…</p>`,
       refs: ["Référence 1", "Référence 2"]   // optionnel
     }
     ======================================================================== */
  var POSTS = [
    {
      id: "exemple-methodo",
      title: "Note méthodologique — indice de fiabilité aéronavale",
      author: "World Monitor",
      date: "2026-07-15",
      tags: ["méthodologie", "indice", "exemple"],
      summary: "Billet d'exemple : définition et calcul de l'indice de fiabilité aéronavale utilisé dans l'explorateur. À remplacer par tes propres documents.",
      body:
        '<p>Ce billet est un <b>exemple</b> destiné à montrer la mise en forme de la section Documentation. ' +
        'Remplace-le par tes propres notes ; chaque document devient un billet indépendant.</p>' +
        '<h3>Définition</h3>' +
        '<p>L\'indice de fiabilité aéronavale d\'un article combine la fiabilité de la source et ' +
        'l\'intérêt naval du titre, selon la formule :</p>' +
        '<blockquote>fiabilité aéronavale = (6 − indice de fiabilité) × intérêt naval ÷ 100</blockquote>' +
        '<p>L\'indice de fiabilité va de 1 (source la plus fiable) à 5 ; le terme (6 − indice) inverse ' +
        'l\'échelle pour qu\'une source plus fiable pèse davantage.</p>' +
        '<h3>Interprétation</h3>' +
        '<ul>' +
        '<li>Un article sans signal naval a une note nulle.</li>' +
        '<li>La note par média est la moyenne des seuls articles à signal naval ≥ 1.</li>' +
        '<li>Les valeurs élevées combinent une source fiable et un fort intérêt naval.</li>' +
        '</ul>',
      refs: [
        "World Monitor, catalogue de flux (koala73/worldmonitor).",
        "Barème naval interne (naval.txt)."
      ]
    }
  ];
  /* ====================== FIN DES BILLETS ================================== */

  function ready(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }

  var esc2 = function (s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  };
  function fmtDate(d) {
    var p = String(d || "").split("-");
    return p.length === 3 ? p[2] + "/" + p[1] + "/" + p[0] : (d || "");
  }

  var state = { current: POSTS.length ? POSTS[0].id : null };

  function injectStyle() {
    if (document.getElementById("wm-doc-style")) return;
    var st = document.createElement("style");
    st.id = "wm-doc-style";
    st.textContent =
      ".tab.wm-doc{color:#ff8a8a;border-color:#7a2a35}" +
      ".tab.wm-doc.active{background:#3a1a20;color:#ffb3b3;border-color:#a03a48;font-weight:600}" +
      "#tab-doc .docitem{display:block;width:100%;text-align:left;background:var(--panel);border:1px solid var(--border);" +
        "border-radius:8px;padding:10px 12px;margin-bottom:8px;cursor:pointer;color:var(--text)}" +
      "#tab-doc .docitem:hover{border-color:var(--accent)}" +
      "#tab-doc .docitem.on{border-color:#a03a48;background:#2a1a1f}" +
      "#tab-doc .docitem b{display:block;font-size:.95rem;margin-bottom:3px}" +
      "#tab-doc .docitem small{color:var(--muted)}" +
      "#tab-doc .wm-article{line-height:1.65;color:var(--text);max-width:820px}" +
      "#tab-doc .wm-article h1{font-size:1.7rem;margin-bottom:6px}" +
      "#tab-doc .wm-article h3{margin:20px 0 8px;font-size:1.15rem;color:var(--accent)}" +
      "#tab-doc .wm-article p{margin:0 0 12px}" +
      "#tab-doc .wm-article ul{margin:0 0 12px 20px}" +
      "#tab-doc .wm-article li{margin:4px 0}" +
      "#tab-doc .wm-article blockquote{border-left:3px solid var(--accent);margin:0 0 14px;padding:6px 14px;color:var(--muted);background:var(--panel);border-radius:0 6px 6px 0}" +
      "#tab-doc .wm-meta{color:var(--muted);font-size:.85rem;margin-bottom:14px}" +
      "#tab-doc .wm-abstract{font-style:italic;color:var(--muted);border-left:3px solid var(--accent2);padding:6px 14px;margin:0 0 18px}" +
      "#tab-doc .wm-refs{font-size:.85rem;color:var(--muted);margin-top:24px;border-top:1px solid var(--border);padding-top:12px}" +
      "#tab-doc .wm-chip{display:inline-block;background:var(--panel);border:1px solid var(--border);border-radius:20px;padding:2px 10px;margin:2px 4px 2px 0;font-size:.75rem;color:var(--muted)}";
    document.head.appendChild(st);
  }

  function renderList(filter) {
    var q = (filter || "").toLowerCase();
    var list = document.getElementById("docList");
    var items = POSTS.filter(function (p) {
      return !q || (p.title + " " + p.summary + " " + (p.tags || []).join(" ")).toLowerCase().indexOf(q) !== -1;
    });
    if (!items.length) { list.innerHTML = '<p class="count">Aucun billet.</p>'; return; }
    list.innerHTML = items.map(function (p) {
      return '<button class="docitem' + (p.id === state.current ? " on" : "") + '" data-id="' + esc2(p.id) + '">' +
        "<b>" + esc2(p.title) + "</b>" +
        "<small>" + fmtDate(p.date) + (p.author ? " · " + esc2(p.author) : "") + "</small>" +
        "</button>";
    }).join("");
    Array.prototype.forEach.call(list.querySelectorAll(".docitem"), function (b) {
      b.addEventListener("click", function () { state.current = b.dataset.id; renderList(filter); renderReader(); });
    });
  }

  function renderReader() {
    var reader = document.getElementById("docReader");
    var p = POSTS.filter(function (x) { return x.id === state.current; })[0];
    if (!p) { reader.innerHTML = '<p class="count">Sélectionne un billet à gauche.</p>'; return; }
    reader.innerHTML =
      '<article class="wm-article">' +
        "<h1>" + esc2(p.title) + "</h1>" +
        '<div class="wm-meta">' + fmtDate(p.date) + (p.author ? " · " + esc2(p.author) : "") +
          ((p.tags && p.tags.length) ? "<br>" + p.tags.map(function (t) { return '<span class="wm-chip">' + esc2(t) + "</span>"; }).join("") : "") +
        "</div>" +
        (p.summary ? '<div class="wm-abstract">' + esc2(p.summary) + "</div>" : "") +
        (p.body || "") +
        ((p.refs && p.refs.length)
          ? '<div class="wm-refs"><b>Références</b><ol>' + p.refs.map(function (r) { return "<li>" + esc2(r) + "</li>"; }).join("") + "</ol></div>"
          : "") +
      "</article>";
  }

  function injectTab() {
    var tabs = document.querySelector(".tabs");
    var main = document.querySelector("main");
    if (!tabs || !main) return false;
    if (document.getElementById("tab-doc")) return true;
    injectStyle();

    var tab = document.createElement("div");
    tab.className = "tab wm-doc";
    tab.dataset.tab = "doc";
    tab.textContent = "📕 Documentation";
    tabs.appendChild(tab);

    var panel = document.createElement("div");
    panel.className = "panel";
    panel.id = "tab-doc";
    panel.style.display = "none";
    panel.innerHTML =
      '<h2 style="margin-bottom:6px;color:#ff8a8a">📕 Documentation</h2>' +
      '<p class="count" style="margin-bottom:14px">Notes et billets de méthodologie. Clique un titre à gauche pour le lire.</p>' +
      '<input id="docSearch" type="search" placeholder="Rechercher un billet…" ' +
        'style="width:100%;max-width:420px;padding:9px 14px;border-radius:8px;border:1px solid var(--border);background:var(--panel);color:var(--text);margin-bottom:14px">' +
      '<div style="display:flex;gap:22px;align-items:flex-start;flex-wrap:wrap">' +
        '<aside id="docList" style="width:280px;max-width:100%;flex-shrink:0"></aside>' +
        '<div id="docReader" style="flex:1;min-width:300px"></div>' +
      "</div>";
    main.appendChild(panel);

    panel.querySelector("#docSearch").addEventListener("input", function () { renderList(this.value); });

    // onglet Documentation : afficher / masquer les autres panneaux
    tab.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (x) { x.classList.remove("active"); });
      tab.classList.add("active");
      ["explore", "charts", "carto", "graph"].forEach(function (k) {
        var el = document.getElementById("tab-" + k); if (el) el.style.display = "none";
      });
      panel.style.display = "";
    });
    // clic sur un autre onglet : masquer la Documentation
    document.querySelectorAll(".tab").forEach(function (t) {
      if (t !== tab) t.addEventListener("click", function () {
        panel.style.display = "none"; tab.classList.remove("active");
      });
    });

    renderList("");
    renderReader();
    return true;
  }

  ready(function () { injectTab(); });
})();
