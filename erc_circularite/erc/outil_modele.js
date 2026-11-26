/* Modèle de la ligne de démontage et de tri des FRU scrapées, pour l'outil des décideurs.
 *
 * Portage fidèle de erc/ligne.py, qui reste l'implémentation de référence (spécification :
 * docs/Modele_mathematique.md). Les tests tests/test_outil.py vérifient que ce fichier redonne les mêmes
 * résultats que Python sur le jeu de démonstration et sur des scénarios tirés au hasard.
 *
 * Fonctions pures, sans accès à la page : le même fichier est inséré dans l'outil et chargé par node.
 *
 * Conventions
 *   - null, undefined ou NaN = inconnu (None / NaN en Python). Une entrée inconnue rend l'option non
 *     calculable ou le type de FRU « incomplet » ; elle ne devient jamais 0.
 *   - Entrées du modèle : ligne = {heures_operateur_an, taux_horaire_eur, cout_traitement_eur_kg,
 *     cout_installation_eur, amortissement_ans, couts_fixes_annuels_eur} ;
 *     frus = [{fru, scrap_an, poids_fru_kg, ouverture_min, [ouverture_tri_min], [taux_horaire_eur],
 *              pieces: [{piece, n_par_fru, extraction_min, test_min, tri_min, p_reutilisable, valeur_eur,
 *                        delai_semaines, valeur_semaine_eur, transport_eur, poids_kg, prix_recycleur_eur_kg}]}].
 *     Des listes et non des dictionnaires : l'ordre des FRU et des pièces compte et doit rester celui de Python.
 *   - Comme en Python, « ouverture_tri_min » et « taux_horaire_eur » d'un FRU ne retombent sur leur valeur par
 *     défaut (ouverture soignée, taux de la ligne) que si la clé est ABSENTE ; présente et inconnue, elle reste inconnue.
 */
(function (racine) {
  "use strict";

  var OPTIONS = ["réemploi", "recyclage", "jeté"];
  var CHAMPS_REEMPLOI = ["n_par_fru", "extraction_min", "test_min", "p_reutilisable", "valeur_eur"];
  var CHAMPS_RECYCLAGE = ["n_par_fru", "poids_kg", "prix_recycleur_eur_kg", "tri_min"];
  var MAX_PIECES_ENUM = 8;                 // jusqu'à 8 pièces calculables : énumération (3^8 = 6 561) ; au-delà : sans énumérer
  var CLES_LIGNE = ["heures_operateur_an", "taux_horaire_eur", "cout_traitement_eur_kg", "cout_installation_eur",
                    "amortissement_ans", "couts_fixes_annuels_eur"];
  var CLES_FRU = ["scrap_an", "poids_fru_kg", "ouverture_min", "ouverture_tri_min", "taux_horaire_eur"];
  var CLES_PIECE = ["n_par_fru", "extraction_min", "test_min", "tri_min", "p_reutilisable", "valeur_eur", "delai_semaines",
                    "valeur_semaine_eur", "transport_eur", "poids_kg", "prix_recycleur_eur_kg"];
  var CLES_TEMPS = ["ouverture_min", "ouverture_tri_min", "extraction_min", "test_min", "tri_min"];

  // ------------------------------------------------------------------ utilitaires
  function inconnu(v) {
    return v === null || v === undefined || (typeof v === "number" && isNaN(v));
  }
  function possede(o, k) {
    return Object.prototype.hasOwnProperty.call(o, k);
  }
  /** dict.get(k, defaut) de Python : le défaut ne sert que si la clé est absente. */
  function lire(o, k, defaut) {
    return possede(o, k) ? o[k] : defaut;
  }
  /** Entrée facultative (_facultatif de ligne.py) : comptée si elle est saisie, 0 sinon (None, NaN compris). */
  function ou0(v) {
    return inconnu(v) ? 0 : v;
  }
  /** Semaine explicitement marquée incomplète (False, 0, « non », « faux ») : _semaine_incomplete de ligne.py. */
  function semaineIncomplete(v) {
    return !inconnu(v) && ["false", "0", "0.0", "non", "faux"].indexOf(String(v).trim().toLowerCase()) >= 0;
  }
  /** pd.to_numeric(errors="coerce") pour une cellule : nombre, texte numérique, sinon NaN. */
  function nombre(v) {
    if (typeof v === "number") return v;
    if (v === null || v === undefined || typeof v === "boolean") return v === true ? 1 : v === false ? 0 : NaN;
    var t = String(v).trim();
    return t === "" ? NaN : Number(t);
  }
  function somme(valeurs) {
    var s = 0;
    for (var i = 0; i < valeurs.length; i++) s += valeurs[i];
    return s;
  }

  // ------------------------------------------------------------------ options par pièce
  /** Pour chaque pièce : entrées manquantes du réemploi et du recyclage (liste vide = option calculable). */
  function optionsDisponibles(fru) {
    var ouvTri = lire(fru, "ouverture_tri_min", fru.ouverture_min);
    return (fru.pieces || []).map(function (d) {
      var mRe = CHAMPS_REEMPLOI.filter(function (c) { return inconnu(d[c]); });
      if (inconnu(fru.ouverture_min)) mRe.push("ouverture_min");
      var mRc = CHAMPS_RECYCLAGE.filter(function (c) { return inconnu(d[c]); });
      if (inconnu(ouvTri)) mRc.push("ouverture_tri_min");
      return { piece: d.piece, "réemploi": mRe, recyclage: mRc };
    });
  }

  /** Entrées qui empêchent de calculer un type de FRU (liste vide = calculable). Le coût de traitement du recycleur
   *  actuel est lu dans fru._c_trait, qu'optimiserLigne renseigne : présent et inconnu, il bloque le type de FRU. */
  function manques(fru, tauxDefaut) {
    var m = [];
    if (inconnu(fru.scrap_an)) m.push("scrap_an");
    else if (fru.scrap_an < 0) m.push("scrap_an négatif");
    if (inconnu(lire(fru, "taux_horaire_eur", tauxDefaut))) m.push("taux_horaire_eur");
    if (possede(fru, "_c_trait") && inconnu(fru._c_trait)) m.push("cout_traitement_eur_kg");
    var dispo = optionsDisponibles(fru);
    var uneOption = dispo.some(function (o) { return !o["réemploi"].length || !o.recyclage.length; });
    if (!uneOption) {
      m.push("aucune option calculable : " + dispo.map(function (o) {
        return o.piece + " réemploi[" + o["réemploi"].join(", ") + "] recyclage[" + o.recyclage.join(", ") + "]";
      }).join("; "));
    }
    return m;
  }

  /** Une ligne par pièce : valeur nette par FRU de chaque option, HORS ouverture (partagée, donnée à part).
   *  fru._c_trait = coût de traitement du recycleur actuel (€/kg), ajouté par optimiserLigne. */
  function valeursOptions(fru, tauxDefaut) {
    var taux = lire(fru, "taux_horaire_eur", tauxDefaut);
    var tauxConnu = !inconnu(taux);
    var cFourni = possede(fru, "_c_trait");
    var cConnu = !(cFourni && inconnu(fru._c_trait));
    var cTrait = cConnu ? ou0(fru._c_trait) : NaN;
    var chiffrable = tauxConnu && cConnu;        // taux ou coût de traitement inconnu : valeurs NaN, heures et kg donnés
    var dispo = optionsDisponibles(fru);
    var lignes = (fru.pieces || []).map(function (d, i) {
      var n = d.n_par_fru;
      var poidsConnu = !inconnu(d.poids_kg);
      var kg = poidsConnu ? d.poids_kg : 0.0;                   // poids inconnu : aucun traitement évité compté
      // Vente au kilo d'un exemplaire refusé au test : son poids et le prix du recycleur suffisent (pas le temps de tri).
      var kgv = poidsConnu && !inconnu(d.prix_recycleur_eur_kg) ? d.poids_kg * d.prix_recycleur_eur_kg : null;
      var kRe = 0.0, kRc = 0.0, vRe, hRe, vRc, hRc, nonCompte = [];
      if (dispo[i]["réemploi"].length) {
        vRe = NaN; hRe = NaN;
      } else {
        var q = d.p_reutilisable;
        kRe = n * kg * (q + (1 - q) * (kgv !== null ? 1 : 0));
        var bonus = ou0(d.delai_semaines) * ou0(d.valeur_semaine_eur);
        var echec = kgv !== null ? kgv : 0.0;
        hRe = n * (d.extraction_min + d.test_min) / 60;
        vRe = chiffrable ? n * (q * (d.valeur_eur + bonus) + (1 - q) * echec - ou0(d.transport_eur)) - hRe * taux + kRe * cTrait : NaN;
        if (inconnu(d.transport_eur)) nonCompte.push("transport");
        if (inconnu(d.delai_semaines) || inconnu(d.valeur_semaine_eur)) nonCompte.push("délai évité");
        if (kgv === null) nonCompte.push("revente au kilo des exemplaires refusés au test");
        if (!poidsConnu || !cFourni) nonCompte.push("traitement évité");
      }
      if (dispo[i].recyclage.length) {
        vRc = NaN; hRc = NaN;
      } else {
        hRc = n * d.tri_min / 60;
        kRc = n * kg;
        vRc = chiffrable ? n * kgv - hRc * taux + kRc * cTrait : NaN;
        if (!cFourni && nonCompte.indexOf("traitement évité") < 0) nonCompte.push("traitement évité");
      }
      var meilleure = null, vMax = NaN;                         // idxmax sur (réemploi, recyclage, jeté), NaN ignorés
      [["Réemploi", vRe], ["Recyclage", vRc], ["Jeté", 0.0]].forEach(function (o) {
        if (!isNaN(o[1]) && (meilleure === null || o[1] > vMax)) { meilleure = o[0]; vMax = o[1]; }
      });
      return {
        "Pièce": d.piece, "1 Réemploi (€/FRU)": vRe, "2 Recyclage (€/FRU)": vRc, "3 Jeté (€/FRU)": 0.0,
        "Heures réemploi": hRe, "Heures recyclage": hRc, "Kg détournés réemploi": kRe, "Kg détournés recyclage": kRc,
        "Manque réemploi": dispo[i]["réemploi"].join(", "), "Manque recyclage": dispo[i].recyclage.join(", "),
        "Non compté faute de donnée": nonCompte.join(", "),
        "Meilleure option seule": meilleure,
        manque_reemploi: dispo[i]["réemploi"], manque_recyclage: dispo[i].recyclage, non_compte: nonCompte
      };
    });
    var ouvTri = lire(fru, "ouverture_tri_min", fru.ouverture_min);
    return {
      lignes: lignes,
      "Ouverture soignée (€/FRU)": tauxConnu && !inconnu(fru.ouverture_min) ? fru.ouverture_min / 60 * taux : NaN,
      "Ouverture sommaire (€/FRU)": tauxConnu && !inconnu(ouvTri) ? ouvTri / 60 * taux : NaN
    };
  }

  // ------------------------------------------------------------------ toutes les affectations d'un type de FRU
  var _CODES = {};

  /** Affectations de n pièces, mises en cache : ligne i = écriture de i en base 3 (première pièce = chiffre de
   *  poids fort), 0 = réemploi, 1 = recyclage, 2 = jeté. Même ordre que np.indices((3,)*n).reshape(n, -1).T. */
  function codes(n) {
    if (!_CODES[n]) {
      var N = Math.pow(3, n);
      var C = new Uint8Array(N * n), aRe = new Uint8Array(N), aRc = new Uint8Array(N);
      for (var i = 0; i < N; i++) {
        var r = i;
        for (var k = n - 1; k >= 0; k--) {
          var c = r % 3;
          C[i * n + k] = c;
          if (c === 0) aRe[i] = 1; else if (c === 1) aRc[i] = 1;
          r = (r - c) / 3;
        }
      }
      _CODES[n] = { N: N, n: n, C: C, aReemploi: aRe, aRecyclage: aRc };
    }
    return _CODES[n];
  }

  /** Affectations pièce → option d'un type de FRU, et le meilleur plan pour un prix donné de l'heure.
   *  Deux méthodes, même résultat (comme la classe Options de ligne.py) :
   *    énumération  jusqu'à MAX_PIECES_ENUM pièces calculables : toutes les affectations calculables, dans l'ordre de
   *                 Python (une option non calculable n'est jamais choisie : « tout laisser » est toujours calculable) ;
   *    séparable    au-delà : chaque pièce prend seule sa meilleure option, puis on compare « ne pas ouvrir »,
   *                 « ouvrir sans réemploi » et « ouvrir avec au moins un réemploi ». Toutes les pièces sont examinées.
   *  `separable` force la méthode (true ou false) ; laissé vide, elle est choisie d'après le nombre de pièces. */
  function Options(fru, tauxDefaut, separable) {
    var taux = lire(fru, "taux_horaire_eur", tauxDefaut);
    var t = valeursOptions(fru, tauxDefaut).lignes;
    var nbCalculables = t.filter(function (l) { return !(isNaN(l["1 Réemploi (€/FRU)"]) && isNaN(l["2 Recyclage (€/FRU)"])); }).length;
    this.separable = separable === undefined || separable === null ? nbCalculables > MAX_PIECES_ENUM : !!separable;
    if (this.separable) {
      var gardees = t.filter(function (l) { return !(isNaN(l["1 Réemploi (€/FRU)"]) && isNaN(l["2 Recyclage (€/FRU)"])); });
      this.noms = gardees.map(function (l) { return l["Pièce"]; });
      this.noms_ignores = [];
      this.ignorees = 0;
      this.n = gardees.length;
      var zero = function (x) { return isNaN(x) ? 0.0 : x; };
      this.vRe = gardees.map(function (l) { return l["1 Réemploi (€/FRU)"]; });      // NaN = option non calculable
      this.vRc = gardees.map(function (l) { return l["2 Recyclage (€/FRU)"]; });
      this.hRe = gardees.map(function (l) { return zero(l["Heures réemploi"]); });
      this.hRc = gardees.map(function (l) { return zero(l["Heures recyclage"]); });
      this.kRe = gardees.map(function (l) { return zero(l["Kg détournés réemploi"]); });
      this.kRc = gardees.map(function (l) { return zero(l["Kg détournés recyclage"]); });
      this.ouv = ou0(fru.ouverture_min) / 60;
      this.ouvTri = ou0(lire(fru, "ouverture_tri_min", fru.ouverture_min)) / 60;
      this.taux = inconnu(taux) ? NaN : taux;
      this.H = this.M = this.K = this.idx = null;
      return;
    }
    // Tri par meilleure valeur décroissante, inconnus à la fin, ex æquo dans l'ordre d'origine ; 8 premières gardées.
    var ordre = t.map(function (l, i) {
      var a = l["1 Réemploi (€/FRU)"], b = l["2 Recyclage (€/FRU)"];
      return { l: l, i: i, m: isNaN(a) ? b : isNaN(b) ? a : Math.max(a, b) };
    });
    ordre.sort(function (x, y) {
      var xn = isNaN(x.m), yn = isNaN(y.m);
      if (xn || yn) return xn && yn ? x.i - y.i : xn ? 1 : -1;
      return (y.m > x.m ? 1 : y.m < x.m ? -1 : 0) || x.i - y.i;
    });
    var calculables = t.filter(function (l) { return !(isNaN(l["1 Réemploi (€/FRU)"]) && isNaN(l["2 Recyclage (€/FRU)"])); })
      .map(function (l) { return l["Pièce"]; });
    ordre = ordre.slice(0, MAX_PIECES_ENUM);
    var n = ordre.length;
    var noms = ordre.map(function (o) { return o.l["Pièce"]; });
    this.noms = noms;
    // pièces écartées par la limite alors qu'une de leurs options était calculable : elles restent dans le FRU
    this.noms_ignores = calculables.filter(function (p) { return noms.indexOf(p) < 0; });
    this.ignorees = this.noms_ignores.length;
    this.n = n;
    var cd = codes(n), N = cd.N;
    var V = new Float64Array(N), H = new Float64Array(N), K = new Float64Array(N), ok = new Uint8Array(N);
    ok[0] = 1;
    var taille = 1;
    for (var k = 0; k < n; k++) {                               // somme colonne par colonne, dans l'ordre des pièces
      var l = ordre[k].l;
      var v3 = [l["1 Réemploi (€/FRU)"], l["2 Recyclage (€/FRU)"], 0.0];
      var h3 = [l["Heures réemploi"], l["Heures recyclage"], 0.0];
      var k3 = [l["Kg détournés réemploi"], l["Kg détournés recyclage"], 0.0];
      var bon = [!isNaN(v3[0]) ? 1 : 0, !isNaN(v3[1]) ? 1 : 0, 1];
      for (var c0 = 0; c0 < 2; c0++) {                          // np.nan_to_num : NaN → 0 dans les sommes
        if (isNaN(v3[c0])) v3[c0] = 0.0;
        if (isNaN(h3[c0])) h3[c0] = 0.0;
        if (isNaN(k3[c0])) k3[c0] = 0.0;
      }
      for (var i = taille - 1; i >= 0; i--) {
        var sv = V[i], sh = H[i], sk = K[i], so = ok[i];
        for (var c = 2; c >= 0; c--) {
          var j = i * 3 + c;
          V[j] = sv + v3[c]; H[j] = sh + h3[c]; K[j] = sk + k3[c]; ok[j] = so && bon[c] ? 1 : 0;
        }
      }
      taille *= 3;
    }
    var ouv = ou0(fru.ouverture_min) / 60;
    var ouvTri = ou0(lire(fru, "ouverture_tri_min", fru.ouverture_min)) / 60;
    var nb = 0, i2;
    for (i2 = 0; i2 < N; i2++) nb += ok[i2];
    this.idx = new Int32Array(nb);
    this.H = new Float64Array(nb);
    this.M = new Float64Array(nb);
    this.K = new Float64Array(nb);
    var p = 0;
    for (i2 = 0; i2 < N; i2++) {
      if (!ok[i2]) continue;
      var o = cd.aReemploi[i2] ? ouv : cd.aRecyclage[i2] ? ouvTri : 0.0;
      this.idx[p] = i2;
      this.H[p] = H[i2] + o;
      this.M[p] = V[i2] - (o !== 0 ? o * (inconnu(taux) ? NaN : taux) : 0.0);
      this.K[p] = K[i2];
      p++;
    }
  }

  /** [[pièce, option]] hors « jeté » ; liste vide = FRU laissé tel quel. */
  Options.prototype.etiquette = function (p) {
    var cd = codes(this.n), i = this.idx[p], e = [];
    for (var k = 0; k < this.n; k++) {
      var c = cd.C[i * this.n + k];
      if (c < 2) e.push([this.noms[k], OPTIONS[c]]);
    }
    return e;
  };

  /** Même réponse que l'énumération, en un passage sur les pièces (_meilleur_separable de ligne.py).
   *  Les sommes sont faites dans l'ordre des pièces, comme en Python. */
  Options.prototype.meilleurSeparable = function (mu) {
    var n = this.n, VIDE = { e: [], h: 0.0, m: 0.0, k: 0.0 };
    if (!n) return VIDE;
    var rRe = new Array(n), rRc = new Array(n), avec = new Array(n), sans = new Array(n), j;
    var unReemploi = false, reemploiPossible = false;
    for (j = 0; j < n; j++) {
      rRe[j] = isNaN(this.vRe[j]) ? -Infinity : this.vRe[j] - mu * this.hRe[j];
      rRc[j] = isNaN(this.vRc[j]) ? -Infinity : this.vRc[j] - mu * this.hRc[j];
      // à égalité : réemploi, puis recyclage
      avec[j] = rRe[j] >= rRc[j] && rRe[j] >= 0 ? 0 : rRc[j] >= 0 ? 1 : 2;
      sans[j] = rRc[j] >= 0 ? 1 : 2;
      if (avec[j] === 0) unReemploi = true;
      if (isFinite(rRe[j])) reemploiPossible = true;
    }
    if (!unReemploi && reemploiPossible) {              // aucun réemploi choisi : l'imposer à la pièce pour qui il coûte le moins
      var meilleurEcart = -Infinity, jm = 0;
      for (j = 0; j < n; j++) {
        var ecart = rRe[j] - Math.max(rRc[j], 0.0);
        if (ecart > meilleurEcart) { meilleurEcart = ecart; jm = j; }
      }
      avec[jm] = 0;
    }
    var self = this;
    function bilan(code, avecReemploi) {
      var re = false, rc = false, hh = 0.0, mm = 0.0, kk = 0.0, i;
      for (i = 0; i < n; i++) { if (code[i] === 0) re = true; else if (code[i] === 1) rc = true; }
      if (!(re || rc) || (avecReemploi && !re)) return null;
      for (i = 0; i < n; i++) {
        hh += code[i] === 0 ? self.hRe[i] : code[i] === 1 ? self.hRc[i] : 0.0;
        mm += code[i] === 0 ? self.vRe[i] : code[i] === 1 ? self.vRc[i] : 0.0;
        kk += code[i] === 0 ? self.kRe[i] : code[i] === 1 ? self.kRc[i] : 0.0;
      }
      var o = re ? self.ouv : self.ouvTri;
      hh = hh + o;
      mm = mm - (o !== 0 ? o * self.taux : 0.0);
      return { r: mm - mu * hh, code: code, h: hh, m: mm, k: kk };
    }
    var a = bilan(avec, true), b = bilan(sans, false), best = a;
    if (b !== null && (best === null || b.r > best.r)) best = b;       // à égalité, le plan avec réemploi
    if (best === null || !(best.r > 1e-12)) return VIDE;
    var e = [];
    for (j = 0; j < n; j++) if (best.code[j] < 2) e.push([this.noms[j], OPTIONS[best.code[j]]]);
    return { e: e, h: best.h, m: best.m, k: best.k };
  };

  /** Plan qui maximise marge − mu × heures : {e, h, m, k}. Plan vide si rien n'est rentable. */
  Options.prototype.meilleur = function (mu) {
    if (this.separable) return this.meilleurSeparable(mu);
    var M = this.M, H = this.H, best = -Infinity, bi = 0;
    for (var p = 0, nb = M.length; p < nb; p++) {
      var x = M[p] - mu * H[p];
      if (x > best) { best = x; bi = p; }
    }
    if (M.length) {
      var e = this.etiquette(bi);
      if (e.length && M[bi] - mu * H[bi] > 1e-12) return { e: e, h: H[bi], m: M[bi], k: this.K[bi] };
    }
    return { e: [], h: 0.0, m: 0.0, k: 0.0 };
  };

  // ------------------------------------------------------------------ optimisation de la ligne
  function avecTraitement(d, ligne) {
    var c = {};
    for (var k in d) if (possede(d, k)) c[k] = d[k];
    c._c_trait = ligne.cout_traitement_eur_kg;
    return c;
  }

  /** Affectations de chaque type de FRU, calculées une fois. Elles ne dépendent ni des heures disponibles, ni des
   *  coûts fixes, ni du nombre de FRU scrapées : on les réutilise pour la sensibilité aux heures et le rejeu par semaine. */
  function preparer(ligne, frus) {
    var taux = ligne.taux_horaire_eur;
    return frus.map(function (d) {
      if (inconnu(lire(d, "taux_horaire_eur", taux))) return null;
      var dispo = optionsDisponibles(d);
      if (!dispo.some(function (o) { return !o["réemploi"].length || !o.recyclage.length; })) return null;
      return new Options(avecTraitement(d, ligne), taux);
    });
  }

  function memeEtiquette(a, b) {
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) if (a[i][0] !== b[i][0] || a[i][1] !== b[i][1]) return false;
    return true;
  }

  function ligneRes(f, S, n, h, m, d, k) {
    var re = [], rc = [];
    S.forEach(function (x) { (x[1] === "réemploi" ? re : rc).push(x[0]); });
    return {
      "Type de FRU": f, "Décision": S.length && n > 0 ? "traiter" : "jeter telle quelle",
      "1 Réemploi": re.join(", "), "2 Recyclage": rc.join(", "), "FRU traitées / an": n, "FRU scrapées / an": d.scrap_an,
      "Heures par FRU": h, "Marge par FRU (€)": m, "Marge par heure (€)": h ? m / h : NaN,
      "Heures / an": n * h, "Marge variable / an (€)": n * m, "Kg détournés / an": n * k, "Entrées manquantes": "",
      reemploi: re, recyclage: rc
    };
  }

  /** Choix des FRU à démonter et des pièces à extraire, sous la capacité en heures. Valeurs ponctuelles.
   *
   *  Relâché continu résolu par multiplicateur de Lagrange mu sur les heures : chaque type de FRU prend le plan qui
   *  maximise marge − mu × heures ; mu est trouvé par dichotomie. Au point de rupture, les heures restantes sont
   *  données aux types de FRU dont le plan change, dans l'ordre du gain par heure supplémentaire.
   *  `prep` (facultatif) = résultat de preparer(ligne, frus). Renvoie {detail: [lignes], resume: {indicateurs}}. */
  function optimiserLigne(ligne, frus, prep) {
    var taux = ligne.taux_horaire_eur;
    var avec = frus.map(function (d) { return avecTraitement(d, ligne); });
    var incomplets = avec.map(function (d) { return manques(d, taux); });
    var ok = [], opts = [];
    avec.forEach(function (d, i) {
      if (incomplets[i].length) return;
      ok.push(d);
      opts.push(prep && prep[i] ? prep[i] : new Options(d, taux));
    });
    var cap = ligne.heures_operateur_an;
    cap = inconnu(cap) ? Infinity : Math.max(+cap, 0);   // heures inconnues = pas de limite ; négatives = aucune heure

    function choix(mu) {
      return opts.map(function (o) { return o.meilleur(mu); });
    }
    function heures(c) {
      var s = 0;
      for (var i = 0; i < c.length; i++) s += ok[i].scrap_an * c[i].h;
      return s;
    }

    var muLo = 0.0, muHi = 0.0;
    var cHi = choix(0.0), cLo = cHi;
    if (heures(cHi) > cap) {
      muHi = 1.0;
      while (heures(choix(muHi)) > cap && muHi < 1e300) muHi *= 2;
      for (var it = 0; it < 60; it++) {
        var mid = (muLo + muHi) / 2;
        if (heures(choix(mid)) > cap) muLo = mid; else muHi = mid;
      }
      cHi = choix(muHi);
      cLo = choix(muLo);
    }
    // cHi tient dans la capacité ; cLo la dépasse. Les heures restantes basculent une partie des FRU de cHi vers cLo.
    var bascule = {};
    if (muHi > 0) {
      var reste = cap - heures(cHi);
      var candidats = [];
      ok.forEach(function (d, i) {
        if (!memeEtiquette(cLo[i].e, cHi[i].e) && cLo[i].h > cHi[i].h) {
          candidats.push({ i: i, g: (cLo[i].m - cHi[i].m) / (cLo[i].h - cHi[i].h), rang: candidats.length });
        }
      });
      candidats.sort(function (a, b) { return (b.g > a.g ? 1 : b.g < a.g ? -1 : 0) || a.rang - b.rang; });
      for (var q = 0; q < candidats.length; q++) {
        if (reste <= 1e-12) break;
        var i = candidats[q].i;
        var x = Math.min(+ok[i].scrap_an, reste / (cLo[i].h - cHi[i].h));
        reste -= x * (cLo[i].h - cHi[i].h);
        bascule[i] = x;
      }
    }
    var detail = [];
    ok.forEach(function (d, i) {
      var a = cHi[i], n = +d.scrap_an, x = bascule[i] || 0.0, debut = detail.length;
      if (x > 0) {                              // x FRU au plan plus gourmand, le reste au plan sobre
        var b = cLo[i];
        detail.push(ligneRes(d.fru, b.e, x, b.h, b.m, d, b.k));
        if (n - x > 1e-9) detail.push(ligneRes(d.fru, a.e, a.e.length ? n - x : 0.0, a.h, a.m, d, a.k));
      } else {
        detail.push(ligneRes(d.fru, a.e, a.e.length ? n : 0.0, a.h, a.m, d, a.k));
      }
      for (var z = debut; z < detail.length; z++) detail[z]["Pièces non examinées"] = opts[i].noms_ignores.join(", ");
    });
    frus.forEach(function (d, i) {
      if (incomplets[i].length) {
        detail.push({ "Type de FRU": d.fru, "Décision": "incomplet", "Entrées manquantes": incomplets[i].join(", "),
                      "Pièces non examinées": null, manques: incomplets[i] });
      }
    });
    return bilan(ligne, detail, muHi, cap, frus);
  }

  /** Coût fixe d'une année = installation / durée d'amortissement + coûts fixes annuels (_couts_fixes de ligne.py).
   *  Entrée inconnue → NaN. Une durée inférieure à un an compte pour un an ; sans investissement, la durée n'intervient pas. */
  function coutsFixes(ligne) {
    var inv = ligne.cout_installation_eur, fix = ligne.couts_fixes_annuels_eur, duree = ligne.amortissement_ans;
    if (inconnu(inv) || inconnu(fix)) return NaN;
    if (inv === 0) return +fix;
    if (inconnu(duree)) return NaN;
    return inv / Math.max(duree, 1) + fix;
  }

  /** Résultat de la ligne. Coût fixe ou marge inconnus → NaN (jamais 0). */
  function bilan(ligne, detail, mu, cap, frus) {
    frus = frus || [];
    var c = ligne.cout_traitement_eur_kg;
    var masses = [];
    frus.forEach(function (d) {
      if (d && !inconnu(d.scrap_an) && !inconnu(d.poids_fru_kg) && d.scrap_an >= 0) masses.push(d.scrap_an * d.poids_fru_kg);
    });
    var masse = masses.length && masses.length === frus.length ? somme(masses) : NaN;
    var coutActuel = !inconnu(c) ? masse * c : NaN;
    var inv = ligne.cout_installation_eur, fix = ligne.couts_fixes_annuels_eur;
    var fixes = coutsFixes(ligne);
    var calc = detail.filter(function (r) { return r["Décision"] !== "incomplet"; });
    var col = function (nom) { return calc.length ? somme(calc.map(function (r) { return r[nom]; })) : NaN; };
    var marge = col("Marge variable / an (€)"), h = col("Heures / an"), n = col("FRU traitées / an");
    var moy = n ? marge / n : NaN;
    var excedent = !inconnu(fix) ? marge - fix : NaN;
    return {
      detail: detail,
      resume: {
        "Marge variable / an (€)": marge, "Coûts fixes annualisés (€)": fixes, "Résultat / an (€)": marge - fixes,
        "Heures utilisées / an": h, "Capacité (h/an)": cap, "Taux d'occupation": isFinite(cap) && cap ? h / cap : NaN,
        "FRU traitées / an": n, "Marge moyenne par FRU (€)": moy,
        "Seuil de rentabilité (FRU / an)": moy && moy > 0 ? fixes / moy : NaN,
        "Retour sur investissement (ans)": !inconnu(inv) && excedent > 0 ? inv / excedent : NaN,
        "Valeur d'une heure opérateur en plus (€ net)": calc.length ? mu : NaN,
        "Types de FRU incomplets": detail.length - calc.length,
        "Masse des FRU scrapées (kg/an)": masse, "Masse détournée de la benne (kg/an)": col("Kg détournés / an"),
        "Coût actuel de traitement (€/an)": coutActuel
      }
    };
  }

  /** Situation actuelle (tout chez le recycleur actuel) contre ligne de démontage + tri. Flux annuels, € ; coût = négatif.
   *  Les écarts sont calculés directement : ils restent connus quand le coût actuel ne l'est pas (poids d'un FRU manquant).
   *  `base` (facultatif) = résultat déjà calculé de optimiserLigne(ligne, frus). */
  function comparerScenarios(ligne, frus, base) {
    var r = (base || optimiserLigne(ligne, frus)).resume;
    var c = ligne.cout_traitement_eur_kg;
    c = inconnu(c) ? NaN : c;
    var evite = r["Masse détournée de la benne (kg/an)"] * c;
    var actuel = -r["Coût actuel de traitement (€/an)"];
    var margeHorsEvite = r["Marge variable / an (€)"] - evite;
    var fixes = r["Coûts fixes annualisés (€)"];
    var lignes = [
      ["Traitement des FRU par le recycleur actuel", actuel, actuel + evite, evite],
      ["Marge de la ligne : réemploi + vente au kg − main-d'œuvre", 0.0, margeHorsEvite, margeHorsEvite],
      ["Coûts fixes de la ligne (installation amortie + annuels)", 0.0, -fixes, -fixes]
    ];
    lignes.push(["TOTAL", lignes[0][1] + lignes[1][1] + lignes[2][1], lignes[0][2] + lignes[1][2] + lignes[2][2],
                 lignes[0][3] + lignes[1][3] + lignes[2][3]]);
    var masse = r["Masse des FRU scrapées (kg/an)"], detournee = r["Masse détournée de la benne (kg/an)"];
    return {
      lignes: lignes.map(function (l) {
        return { "Poste (€/an)": l[0], "Actuel": l[1], "Avec la ligne": l[2], "Écart": l[3] };
      }),
      attrs: { "Masse scrapée (kg/an)": masse, "Masse détournée (kg/an)": detournee, "Part détournée": masse ? detournee / masse : NaN }
    };
  }

  /** Résultat annuel selon les heures opérateur disponibles (les autres paramètres inchangés). */
  function sensibiliteHeures(ligne, frus, heures, prep) {
    prep = prep || preparer(ligne, frus);
    return heures.map(function (h) {
      var l = {};
      for (var k in ligne) if (possede(ligne, k)) l[k] = ligne[k];
      l.heures_operateur_an = h;
      var r = optimiserLigne(l, frus, prep).resume;
      return { "Heures / an": h, "Résultat / an (€)": r["Résultat / an (€)"], "Marge variable / an (€)": r["Marge variable / an (€)"],
               "FRU traitées / an": r["FRU traitées / an"], "Heures utilisées / an": r["Heures utilisées / an"],
               "Taux d'occupation": r["Taux d'occupation"],
               "Valeur d'une heure opérateur en plus (€ net)": r["Valeur d'une heure opérateur en plus (€ net)"] };
    });
  }

  /** Le modèle rejoué période par période sur le flux réel des FRU scrapées (lignes {Semaine, FRU, "FRU scrapées"}).
   *  Chaque période : capacité = heures annuelles / périodes ; coût fixe = coût fixe annuel / périodes, payé même si peu
   *  de FRU arrivent ; pas de stock d'une période à l'autre. Comme ligne.py : une semaine marquée incomplète
   *  (« Semaine complète ») est écartée, ainsi qu'une semaine où le comptage d'un FRU du modèle est inconnu ;
   *  heures inconnues = pas de limite, 0 heure = rien n'est traité. */
  function resultatParPeriode(ligne, frus, flux, periodesParAn) {
    periodesParAn = periodesParAn || 52;
    var H = ligne.heures_operateur_an;
    var capP = inconnu(H) ? null : Math.max(+H, 0) / periodesParAn;
    var fixeP = coutsFixes(ligne) / periodesParAn;
    var noms = {}, semainesVues = {}, sansComptage = {}, total = {};
    frus.forEach(function (d) { noms[d.fru] = true; });
    (flux || []).forEach(function (r) {
      if (possede(r, "Semaine complète") && semaineIncomplete(r["Semaine complète"])) return;
      var s = r.Semaine;
      if (inconnu(s)) return;
      semainesVues[s] = true;
      if (!noms[r.FRU]) return;
      var v = nombre(r["FRU scrapées"]);
      if (isNaN(v)) { sansComptage[s] = true; return; }
      var cle = s + "\u0000" + r.FRU;
      total[cle] = (total[cle] || 0) + v;
    });
    var semaines = Object.keys(semainesVues).filter(function (s) { return !sansComptage[s]; }).sort();
    var prep = preparer(ligne, frus);
    var lgP = {};
    for (var k in ligne) if (possede(ligne, k)) lgP[k] = ligne[k];
    lgP.heures_operateur_an = capP;
    function avecScrap(valeur) {
      return frus.map(function (d) {
        var c = {};
        for (var k2 in d) if (possede(d, k2)) c[k2] = d[k2];
        c.scrap_an = valeur(d.fru);
        return c;
      });
    }
    var cumul = 0, lignes = [];
    semaines.forEach(function (s) {
      var arrivees = 0;
      var frT = avecScrap(function (f) {
        var v = total[s + "\u0000" + f];
        if (v === undefined) return 0.0;
        arrivees += v;
        return v;
      });
      var r = optimiserLigne(lgP, frT, prep).resume;
      var res = r["Marge variable / an (€)"] - fixeP;
      cumul += res;
      lignes.push({ "Semaine": s, "FRU arrivées": arrivees, "FRU traitées": r["FRU traitées / an"], "Heures utilisées": r["Heures utilisées / an"],
                    "Capacité (h)": capP === null ? NaN : capP, "Marge variable (€)": r["Marge variable / an (€)"],
                    "Coût fixe (€)": fixeP, "Résultat (€)": res, "Valeur d'une heure en plus (€)": r["Valeur d'une heure opérateur en plus (€ net)"],
                    "Résultat cumulé (€)": cumul });
    });
    var attrs = {};
    if (lignes.length) {
      var moyen = avecScrap(function (f) {
        var s2 = 0;
        semaines.forEach(function (s) { s2 += total[s + "\u0000" + f] || 0; });
        return s2 / semaines.length * periodesParAn;
      });
      var annuel = optimiserLigne(ligne, moyen, prep).resume["Résultat / an (€)"];
      var parPeriode = somme(lignes.map(function (l) { return l["Résultat (€)"]; })) / lignes.length * periodesParAn;
      attrs = { "Périodes": lignes.length, "Résultat annualisé, période par période (€)": parPeriode,
                "Résultat du modèle annuel au flux moyen (€)": annuel, "Coût de la variabilité du flux (€/an)": annuel - parPeriode,
                "Périodes en perte": lignes.filter(function (l) { return l["Résultat (€)"] < 0; }).length };
    }
    return { lignes: lignes, attrs: attrs };
  }

  // ------------------------------------------------------------------ des données de l'outil aux entrées du modèle
  /** Générateur pseudo-aléatoire à graine (mulberry32) : renvoie une fonction → nombre uniforme dans [0, 1[. */
  function creerAlea(graine) {
    var a = graine >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /** Valeur d'un paramètre de l'outil {valeur, bas, haut, loi}. Sans `alea` : la valeur centrale. Avec : un tirage
   *  selon la loi (« uniforme » sur [bas, haut], « triangulaire » (bas, valeur, haut), fixe sinon). Inconnu → null. */
  function valeurParametre(p, alea) {
    if (p === null || p === undefined) return null;
    if (typeof p !== "object") return inconnu(p) ? null : p;
    var v = inconnu(p.valeur) ? null : p.valeur;
    if (!alea || v === null) return v;
    var a = p.bas, b = p.haut;
    if (inconnu(a) || inconnu(b) || !(b > a)) return v;
    if (p.loi === "uniforme") return a + (b - a) * alea();
    if (p.loi === "triangulaire") {
      var m = Math.min(Math.max(v, a), b), u = alea(), c = (m - a) / (b - a);
      return u < c ? a + Math.sqrt(u * (b - a) * (m - a)) : b - Math.sqrt((1 - u) * (b - a) * (b - m));
    }
    return v;
  }

  /** Données de l'outil ({ligne: {clé: paramètre}, frus: [...]}) → entrées du modèle {ligne, frus}.
   *  options.alea : tirage Monte-Carlo de chaque paramètre ; sinon valeurs centrales.
   *  options.mult = {prix, valeur, temps} : multiplicateurs globaux des prix des recycleurs, de la valeur de réemploi,
   *  des temps (ouverture, extraction, test, tri). Un paramètre inconnu reste inconnu. */
  function versModele(donnees, options) {
    options = options || {};
    var alea = options.alea || null, mult = options.mult || {};
    var mPrix = inconnu(mult.prix) ? 1 : mult.prix, mVal = inconnu(mult.valeur) ? 1 : mult.valeur, mTemps = inconnu(mult.temps) ? 1 : mult.temps;
    function fois(v, m) { return v === null || m === 1 ? v : v * m; }
    var ligne = {};
    CLES_LIGNE.forEach(function (k) { ligne[k] = valeurParametre((donnees.ligne || {})[k], alea); });
    var frus = (donnees.frus || []).map(function (f) {
      var d = { fru: f.fru };
      CLES_FRU.forEach(function (k) {
        var v = valeurParametre(f[k], alea);
        if (CLES_TEMPS.indexOf(k) >= 0) v = fois(v, mTemps);
        // comme erc/parametres.py : l'ouverture sommaire et le taux propre au FRU, inconnus, laissent jouer le défaut
        if (v === null && (k === "ouverture_tri_min" || k === "taux_horaire_eur")) return;
        d[k] = v;
      });
      d.pieces = (f.pieces || []).map(function (pc) {
        var e = { piece: pc.piece };
        CLES_PIECE.forEach(function (k) {
          if (!possede(pc, k)) return;
          var v = valeurParametre(pc[k], alea);
          if (CLES_TEMPS.indexOf(k) >= 0) v = fois(v, mTemps);
          else if (k === "prix_recycleur_eur_kg") v = fois(v, mPrix);
          else if (k === "valeur_eur") v = fois(v, mVal);
          e[k] = v;
        });
        return e;
      });
      return d;
    });
    return { ligne: ligne, frus: frus };
  }

  /** Quantile par interpolation linéaire (np.quantile) d'une liste triée. */
  function quantile(tries, q) {
    if (!tries.length) return NaN;
    var pos = (tries.length - 1) * q, bas = Math.floor(pos), haut = Math.ceil(pos);
    return tries[bas] + (tries[haut] - tries[bas]) * (pos - bas);
  }

  /** Synthèse d'une liste de résultats annuels tirés (NaN = tirage non calculable, écarté). */
  function resumerTirages(resultats) {
    var x = resultats.filter(function (v) { return !inconnu(v) && isFinite(v); }).sort(function (a, b) { return a - b; });
    var gagnants = x.filter(function (v) { return v > 0; }).length;
    return {
      n: resultats.length, n_calcules: x.length,
      p_rentable: x.length ? gagnants / x.length : NaN,
      p5_mediane_p95: x.length ? [quantile(x, 0.05), quantile(x, 0.5), quantile(x, 0.95)].map(Math.round) : [NaN, NaN, NaN]
    };
  }

  /** Un tirage : toutes les plages sont tirées, la ligne est ré-optimisée. Renvoie le résumé et les types traités. */
  function tirage(donnees, alea, mult) {
    var m = versModele(donnees, { alea: alea, mult: mult });
    var r = optimiserLigne(m.ligne, m.frus);
    var traites = {};
    r.detail.forEach(function (l) { if (l["Décision"] === "traiter") traites[l["Type de FRU"]] = true; });
    return { resume: r.resume, traites: Object.keys(traites) };
  }

  /** Monte-Carlo complet, d'un seul bloc (la page le découpe elle-même pour ne pas se figer). */
  function monteCarlo(donnees, n, graine, mult) {
    var alea = creerAlea(graine === undefined ? 2026 : graine), tirages = [], freq = {};
    for (var i = 0; i < n; i++) {
      var t = tirage(donnees, alea, mult);
      tirages.push(t.resume["Résultat / an (€)"]);
      t.traites.forEach(function (f) { freq[f] = (freq[f] || 0) + 1; });
    }
    var s = resumerTirages(tirages);
    for (var f in freq) if (possede(freq, f)) freq[f] = freq[f] / n;
    s.tirages = tirages;
    s.frequence_traitement = freq;
    return s;
  }

  var api = {
    OPTIONS: OPTIONS, CHAMPS_REEMPLOI: CHAMPS_REEMPLOI, CHAMPS_RECYCLAGE: CHAMPS_RECYCLAGE, MAX_PIECES_ENUM: MAX_PIECES_ENUM,
    CLES_LIGNE: CLES_LIGNE, CLES_FRU: CLES_FRU, CLES_PIECE: CLES_PIECE, CLES_TEMPS: CLES_TEMPS,
    inconnu: inconnu, coutsFixes: coutsFixes, optionsDisponibles: optionsDisponibles, manques: manques, valeursOptions: valeursOptions,
    codes: codes, Options: Options, preparer: preparer, optimiserLigne: optimiserLigne, bilan: bilan,
    comparerScenarios: comparerScenarios, sensibiliteHeures: sensibiliteHeures, resultatParPeriode: resultatParPeriode,
    creerAlea: creerAlea, valeurParametre: valeurParametre, versModele: versModele, quantile: quantile,
    resumerTirages: resumerTirages, tirage: tirage, monteCarlo: monteCarlo,
    // mêmes fonctions sous leur nom dans erc/ligne.py
    options_disponibles: optionsDisponibles, valeurs_options: valeursOptions, optimiser_ligne: optimiserLigne, _bilan: bilan,
    comparer_scenarios: comparerScenarios, resultat_par_periode: resultatParPeriode
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else racine.ERCModele = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
