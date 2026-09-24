/* ============================================================================
   World Monitor — Onglet Graphe pondéré (graph.js)
   ---------------------------------------------------------------------------
   Fichier autonome à déposer dans `docs/`, à côté de index.html.
   Une seule ligne à ajouter dans index.html, juste avant </body> :
        <script src="graph.js"></script>

   Générateur : deux menus « Nœud de départ » / « Nœud d'arrivée » (Média,
   Pays traité, Pays d'origine, Thème article, Thème média), dans le sens
   voulu. Un lien A→B = nombre d'articles reliant A (départ) à B (arrivée),
   flèche = sens, épaisseur = poids.

   Rendu : vis-network (physique ForceAtlas2Based, gravité à la Gephi), chargé
   depuis un CDN au premier affichage. Nouveautés :
     • la disposition se FIGE automatiquement après stabilisation (plus de
       mouvement continu) + bouton ❄ Figer / ▶ Animer ;
     • au SURVOL d'un nœud, seuls ses liens et voisins restent visibles.
   Clic sur un nœud → fiche correspondante (openCountry/openSource/openTheme).
   ========================================================================== */
(function () {
  "use strict";

  var VIS_URL = "https://cdn.jsdelivr.net/npm/vis-network@9.1.9/standalone/umd/vis-network.min.js";

  var DIMS = {
    ch: { label: "Pays d'origine du média", kind: "country" },
    ca: { label: "Pays traité",             kind: "country" },
    m:  { label: "Média",                   kind: "media"   },
    sa: { label: "Thème de l'article",      kind: "theme"   },
    sm: { label: "Thème du média",          kind: "theme"   }
  };
  var COLORS = { source: "#4f8cff", target: "#37c99e", both: "#9b7bf6" };

  var state = {
    src: "ch", tgt: "ca", topN: 30, built: false,
    network: null, visLoading: null,
    nodesDS: null, edgesDS: null, nodesRaw: [], edgesRaw: [], frozen: false
  };

  function ready(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }

  function loadVis() {
    if (window.vis && window.vis.Network) return Promise.resolve();
    if (state.visLoading) return state.visLoading;
    state.visLoading = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = VIS_URL;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error("CDN vis-network injoignable")); };
      document.head.appendChild(s);
    });
    return state.visLoading;
  }

  function isBad(v) {
    return !v || (typeof isJunk === "function" && isJunk(v)) ||
           (typeof NONPAYS !== "undefined" && NONPAYS.has && NONPAYS.has(v));
  }
  function topByValue(obj, n) {
    return Object.keys(obj).sort(function (a, b) { return obj[b] - obj[a]; }).slice(0, n);
  }

  function buildGraphData(rows, srcDim, tgtDim, topN) {
    var edge = {}, srcTot = {}, tgtTot = {};
    rows.forEach(function (r) {
      var a = r[srcDim], b = r[tgtDim];
      if (isBad(a) || isBad(b)) return;
      if (srcDim === tgtDim && a === b) return;
      var k = a + "\n" + b;
      var e = edge[k] || (edge[k] = { from: a, to: b, w: 0 });
      e.w += 1;
      srcTot[a] = (srcTot[a] || 0) + 1;
      tgtTot[b] = (tgtTot[b] || 0) + 1;
    });
    var keepSrc = new Set(topByValue(srcTot, topN));
    var keepTgt = new Set(topByValue(tgtTot, topN));

    var nodes = {};
    function touch(val, role, dim) {
      var n = nodes[val] || (nodes[val] = { id: val, weight: 0, roles: {}, dim: dim });
      n.roles[role] = true;
      return n;
    }
    var edges = [];
    Object.keys(edge).forEach(function (k) {
      var e = edge[k];
      if (!keepSrc.has(e.from) || !keepTgt.has(e.to)) return;
      touch(e.from, "source", srcDim).weight += e.w;
      touch(e.to, "target", tgtDim).weight += e.w;
      edges.push({ from: e.from, to: e.to, value: e.w,
        title: esc(e.from + " → " + e.to + " : " + e.w + " article(s)") });
    });

    var visNodes = Object.keys(nodes).map(function (val) {
      var n = nodes[val];
      var role = (n.roles.source && n.roles.target) ? "both"
               : n.roles.source ? "source" : "target";
      return {
        id: n.id,
        label: n.id.length > 22 ? n.id.slice(0, 21) + "…" : n.id,
        value: n.weight,
        title: esc(n.id + " · " + n.weight + " lien(s)"),
        color: { background: COLORS[role], border: "#0f1420",
                 highlight: { background: COLORS[role], border: "#fff" } },
        font: { color: "#e8ecf4", size: 14, strokeWidth: 3, strokeColor: "#0f1420" },
        _kind: DIMS[n.dim] ? DIMS[n.dim].kind : "country"
      };
    });
    return { nodes: visNodes, edges: edges };
  }

  function openNode(id, kind) {
    if (kind === "media" && typeof openSource === "function") return openSource(id);
    if (kind === "theme" && typeof openTheme === "function") return openTheme(id);
    if (typeof openCountry === "function") return openCountry(id);
  }

  // ---- survol : ne garder que le nœud, ses liens et ses voisins ----
  function highlightNeighbors(nodeId) {
    var conn = {}; conn[nodeId] = 1;
    var connE = {};
    state.edgesRaw.forEach(function (e) {
      if (e.from === nodeId || e.to === nodeId) { conn[e.from] = 1; conn[e.to] = 1; connE[e.id] = 1; }
    });
    state.nodesDS.update(state.nodesRaw.map(function (n) {
      var on = conn[n.id];
      return { id: n.id,
        color: on ? n.color : { background: "#2a3245", border: "#2a3245" },
        font: { color: on ? "#e8ecf4" : "rgba(232,236,244,0.10)", size: 14, strokeWidth: 3, strokeColor: "#0f1420" } };
    }));
    state.edgesDS.update(state.edgesRaw.map(function (e) {
      var on = connE[e.id];
      return { id: e.id, color: { color: on ? "#4f8cff" : "#161c28", opacity: on ? 0.9 : 0.05, highlight: "#4f8cff" } };
    }));
  }
  function resetHighlight() {
    if (!state.nodesDS) return;
    state.nodesDS.update(state.nodesRaw.map(function (n) {
      return { id: n.id, color: n.color,
        font: { color: "#e8ecf4", size: 14, strokeWidth: 3, strokeColor: "#0f1420" } };
    }));
    state.edgesDS.update(state.edgesRaw.map(function (e) {
      return { id: e.id, color: { color: "#8ba0c0", opacity: 0.35, highlight: "#4f8cff" } };
    }));
  }

  // ---- gel / animation de la disposition ----
  function setFrozen(f) {
    state.frozen = f;
    if (state.network) state.network.setOptions({ physics: { enabled: !f } });
    var b = document.getElementById("graphFreeze");
    if (b) b.textContent = f ? "▶ Animer" : "❄ Figer";
  }

  function render() {
    if (!state.built && !injectTab()) return;
    var host = document.getElementById("graphCanvas");
    var info = document.getElementById("graphInfo");
    if (typeof DATA === "undefined" || !DATA.length) { info.textContent = "Données non chargées."; return; }

    info.textContent = "Chargement du moteur de graphe…";
    loadVis().then(function () {
      var g = buildGraphData(DATA, state.src, state.tgt, state.topN);
      if (!g.edges.length) { info.textContent = "Aucun lien pour ce couple de dimensions."; host.innerHTML = ""; return; }
      info.innerHTML = "<b>" + g.nodes.length + "</b> nœuds · <b>" + g.edges.length +
        "</b> liens · " + DIMS[state.src].label.toLowerCase() +
        " <span style='color:#4f8cff'>➜</span> " + DIMS[state.tgt].label.toLowerCase() +
        " · tout le corpus (top " + state.topN + " par côté) · survole un nœud pour isoler ses liens";

      state.nodesRaw = g.nodes;
      state.edgesRaw = g.edges.map(function (e, i) {
        return { id: i, from: e.from, to: e.to, value: e.value, title: e.title,
                 arrows: "to", color: { color: "#8ba0c0", opacity: 0.35, highlight: "#4f8cff" },
                 smooth: { type: "continuous" } };
      });
      state.nodesDS = new vis.DataSet(state.nodesRaw);
      state.edgesDS = new vis.DataSet(state.edgesRaw);

      var options = {
        nodes: { shape: "dot", scaling: { min: 8, max: 46, label: { enabled: true, min: 11, max: 22 } }, borderWidth: 1 },
        edges: { scaling: { min: 0.4, max: 9 }, selectionWidth: 2 },
        interaction: { hover: true, tooltipDelay: 120, hideEdgesOnDrag: true },
        physics: {
          solver: "forceAtlas2Based",
          forceAtlas2Based: { gravitationalConstant: -55, centralGravity: 0.012,
            springLength: 110, springConstant: 0.08, damping: 0.5, avoidOverlap: 0.4 },
          stabilization: { iterations: 220 }
        }
      };
      if (state.network) { state.network.destroy(); state.network = null; }
      state.network = new vis.Network(host, { nodes: state.nodesDS, edges: state.edgesDS }, options);
      setFrozen(false);

      var kindOf = {};
      state.nodesRaw.forEach(function (n) { kindOf[n.id] = n._kind; });
      state.network.on("click", function (p) { if (p.nodes && p.nodes.length) openNode(p.nodes[0], kindOf[p.nodes[0]]); });
      state.network.on("hoverNode", function (p) { highlightNeighbors(p.node); });
      state.network.on("blurNode", function () { resetHighlight(); });
      // fige tout seul une fois la disposition stabilisée
      state.network.once("stabilizationIterationsDone", function () { setFrozen(true); });
    }).catch(function (e) {
      info.textContent = "⚠ Impossible de charger le moteur de graphe (" + e.message + "). Vérifie ta connexion, ou réessaie.";
    });
  }

  function injectTab() {
    var tabs = document.querySelector(".tabs");
    var main = document.querySelector("main");
    if (!tabs || !main) return false;
    if (document.getElementById("tab-graph")) { state.built = true; return true; }

    var tab = document.createElement("div");
    tab.className = "tab";
    tab.dataset.tab = "graph";
    tab.textContent = "🕸️ Graphe";
    tabs.appendChild(tab);

    var dimOpts = function (sel) {
      return Object.keys(DIMS).map(function (k) {
        return '<option value="' + k + '"' + (k === sel ? " selected" : "") + ">" + DIMS[k].label + "</option>";
      }).join("");
    };

    var panel = document.createElement("div");
    panel.className = "panel";
    panel.id = "tab-graph";
    panel.style.display = "none";
    panel.innerHTML =
      '<h2 style="margin-bottom:6px">🕸️ Graphe pondéré</h2>' +
      '<p class="count" style="margin-bottom:12px">Chaque nœud est une entité ; ' +
      'un lien A ➜ B = nombre d\'articles reliant la valeur de départ à celle d\'arrivée ' +
      '(flèche = sens, épaisseur = poids). Survole un nœud pour n\'afficher que ses liens ; ' +
      'clique-le pour ouvrir sa fiche. Molette = zoom, glisser = déplacer.</p>' +
      '<div class="chartctl" style="margin-bottom:12px;align-items:flex-end">' +
        '<div><label style="display:block;font-size:.78rem;color:var(--muted);margin-bottom:5px">Nœud de départ</label>' +
          '<select id="graphSrc">' + dimOpts(state.src) + "</select></div>" +
        '<div style="align-self:center;padding-bottom:8px;color:var(--accent);font-size:1.3rem">➜</div>' +
        '<div><label style="display:block;font-size:.78rem;color:var(--muted);margin-bottom:5px">Nœud d\'arrivée</label>' +
          '<select id="graphTgt">' + dimOpts(state.tgt) + "</select></div>" +
        '<div><label style="display:block;font-size:.78rem;color:var(--muted);margin-bottom:5px">Top N / côté</label>' +
          '<select id="graphTop">' +
            [15, 20, 30, 40, 50].map(function (n) {
              return '<option value="' + n + '"' + (n === state.topN ? " selected" : "") + ">" + n + "</option>";
            }).join("") + "</select></div>" +
        '<div><button class="go" id="graphBtn">▶ Générer</button></div>' +
        '<div><button id="graphSwap" title="Inverser départ et arrivée">⇄ Inverser</button></div>' +
        '<div><button id="graphFreeze" title="Figer / relancer la disposition">❄ Figer</button></div>' +
      "</div>" +
      '<div class="count" id="graphInfo" style="margin-bottom:8px">Choisis tes dimensions puis clique sur <b>&nbsp;Générer&nbsp;</b></div>' +
      '<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-bottom:8px">' +
        '<span class="count"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:' + COLORS.source + ';vertical-align:middle"></span> départ seul</span>' +
        '<span class="count"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:' + COLORS.target + ';vertical-align:middle"></span> arrivée seule</span>' +
        '<span class="count"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:' + COLORS.both + ';vertical-align:middle"></span> les deux</span>' +
      "</div>" +
      '<div id="graphCanvas" style="height:620px;background:#0b1018;border:1px solid var(--border);border-radius:10px"></div>';
    main.appendChild(panel);

    panel.querySelector("#graphSrc").addEventListener("change", function () { state.src = this.value; });
    panel.querySelector("#graphTgt").addEventListener("change", function () { state.tgt = this.value; });
    panel.querySelector("#graphTop").addEventListener("change", function () { state.topN = +this.value; });
    panel.querySelector("#graphBtn").addEventListener("click", render);
    panel.querySelector("#graphSwap").addEventListener("click", function () {
      var s = state.src; state.src = state.tgt; state.tgt = s;
      panel.querySelector("#graphSrc").value = state.src;
      panel.querySelector("#graphTgt").value = state.tgt;
      render();
    });
    panel.querySelector("#graphFreeze").addEventListener("click", function () {
      if (state.network) setFrozen(!state.frozen);
    });

    tab.addEventListener("click", function () {
      document.querySelectorAll(".tab").forEach(function (x) { x.classList.remove("active"); });
      tab.classList.add("active");
      ["explore", "charts", "carto"].forEach(function (k) {
        var el = document.getElementById("tab-" + k); if (el) el.style.display = "none";
      });
      panel.style.display = "";
    });
    document.querySelectorAll(".tab").forEach(function (t) {
      if (t.dataset.tab !== "graph")
        t.addEventListener("click", function () { panel.style.display = "none"; tab.classList.remove("active"); });
    });

    state.built = true;
    return true;
  }

  ready(function () { injectTab(); });
})();
