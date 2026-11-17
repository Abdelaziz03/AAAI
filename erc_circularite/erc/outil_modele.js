/* Modèle de la ligne de démontage et de tri des FRU rebutées, pour l'outil des décideurs.
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
 *     frus = [{fru, rebut_an, poids_fru_kg, ouverture_min, [ouverture_tri_min], [taux_horaire_eur],
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
  var MAX_PIECES_ENUM = 8;                 // 3^8 = 6 561 combinaisons par type de FRU
  var CLES_LIGNE = ["heures_operateur_an", "taux_horaire_eur", "cout_traitement_eur_kg", "cout_installation_eur",
                    "amortissement_ans", "couts_fixes_annuels_eur"];
  var CLES_FRU = ["rebut_an", "poids_fru_kg", "ouverture_min", "ouverture_tri_min", "taux_horaire_eur"];
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
  /** « v or 0 » de Python pour un nombre : inconnu ou nul → 0. */
  function ou0(v) {
    return (v === null || v === undefined || v === 0) ? 0 : v;
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

  /** Entrées qui empêchent de calculer un type de FRU (liste vide = calculable). */
  function manques(fru, tauxDefaut) {
    var m = [];
    if (inconnu(fru.rebut_an)) m.push("rebut_an");
    if (inconnu(lire(fru, "taux_horaire_eur", tauxDefaut))) m.push("taux_horaire_eur");
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
    var cTrait = ou0(fru._c_trait);
    var dispo = optionsDisponibles(fru);
    var lignes = (fru.pieces || []).map(function (d, i) {
      var n = d.n_par_fru;
      var kg = inconnu(d.poids_kg) ? 0.0 : d.poids_kg;         // poids inconnu : aucun traitement évité compté
      var kgv = dispo[i].recyclage.length ? null : d.poids_kg * d.prix_recycleur_eur_kg;
      var kRe = 0.0, kRc = 0.0, vRe, hRe, vRc, hRc;
      if (dispo[i]["réemploi"].length) {
        vRe = NaN; hRe = NaN;
      } else {
        var q = d.p_reutilisable;
        kRe = n * kg * (q + (1 - q) * (kgv !== null ? 1 : 0));
        var bonus = ou0(d.delai_semaines) * ou0(d.valeur_semaine_eur);
        var echec = kgv !== null ? kgv : 0.0;
        hRe = n * (d.extraction_min + d.test_min) / 60;
        vRe = tauxConnu ? n * (q * (d.valeur_eur + bonus) + (1 - q) * echec - ou0(d.transport_eur)) - hRe * taux + kRe * cTrait : NaN;
      }
      if (dispo[i].recyclage.length) {
        vRc = NaN; hRc = NaN;
      } else {
        hRc = n * d.tri_min / 60;
        kRc = n * kg;
        vRc = tauxConnu ? n * kgv - hRc * taux + kRc * cTrait : NaN;
      }
      var meilleure = null, vMax = NaN;                         // idxmax sur (réemploi, recyclage, jeté), NaN ignorés
      [["Réemploi", vRe], ["Recyclage", vRc], ["Jeté", 0.0]].forEach(function (o) {
        if (!isNaN(o[1]) && (meilleure === null || o[1] > vMax)) { meilleure = o[0]; vMax = o[1]; }
      });
      return {
        "Pièce": d.piece, "1 Réemploi (€/FRU)": vRe, "2 Recyclage (€/FRU)": vRc, "3 Jeté (€/FRU)": 0.0,
        "Heures réemploi": hRe, "Heures recyclage": hRc, "Kg détournés réemploi": kRe, "Kg détournés recyclage": kRc,
        "Manque réemploi": dispo[i]["réemploi"].join(", "), "Manque recyclage": dispo[i].recyclage.join(", "),
        "Meilleure option seule": meilleure,
        manque_reemploi: dispo[i]["réemploi"], manque_recyclage: dispo[i].recyclage
      };
    });
    var ouvTri = lire(fru, "ouverture_tri_min", fru.ouverture_min);
    return {
      lignes: lignes,
      // Écart voulu avec ligne.py : une ouverture de 0 minute coûte 0 € (ligne.py affiche « inconnu »).
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

  /** Toutes les affectations pièce → option d'un type de FRU : heures, marge et kg détournés par FRU.
   *  Seules les affectations calculables sont gardées (dans l'ordre de Python) : une option non calculable
   *  n'est jamais choisie, puisque « tout laisser » (marge 0, 0 heure) est toujours calculable. */
  function Options(fru, tauxDefaut) {
    var taux = lire(fru, "taux_horaire_eur", tauxDefaut);
    var t = valeursOptions(fru, tauxDefaut).lignes;
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
    ordre = ordre.slice(0, MAX_PIECES_ENUM);
    var n = ordre.length;
    this.noms = ordre.map(function (o) { return o.l["Pièce"]; });
    this.ignorees = Math.max((fru.pieces || []).length - n, 0);   // pièces au-delà de MAX_PIECES_ENUM : laissées dans le FRU
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
      this.M[p] = V[i2] - o * taux;
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

  /** Plan qui maximise marge − mu × heures : {e, h, m, k}. Plan vide si rien n'est rentable. */
  Options.prototype.meilleur = function (mu) {
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
   *  coûts fixes, ni du nombre de FRU rebutées : on les réutilise pour la sensibilité aux heures et le rejeu par semaine. */
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
      "1 Réemploi": re.join(", "), "2 Recyclage": rc.join(", "), "FRU traitées / an": n, "FRU rebutées / an": d.rebut_an,
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
    var incomplets = frus.map(function (d) { return manques(d, taux); });
    var ok = [], opts = [];
    frus.forEach(function (d, i) {
      if (incomplets[i].length) return;
      ok.push(d);
      opts.push(prep && prep[i] ? prep[i] : new Options(avecTraitement(d, ligne), taux));
    });
    var cap = ligne.heures_operateur_an;
    cap = (cap === null || cap === undefined) ? Infinity : +cap;
    if (cap < 0) cap = 0;                       // ligne.py ne se termine pas sur une capacité négative : ramenée à 0 ici

    function choix(mu) {
      return opts.map(function (o) { return o.meilleur(mu); });
    }
    function heures(c) {
      var s = 0;
      for (var i = 0; i < c.length; i++) s += ok[i].rebut_an * c[i].h;
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
        var x = Math.min(+ok[i].rebut_an, reste / (cLo[i].h - cHi[i].h));
        reste -= x * (cLo[i].h - cHi[i].h);
        bascule[i] = x;
      }
    }
    var detail = [];
    ok.forEach(function (d, i) {
      var a = cHi[i], n = +d.rebut_an, x = bascule[i] || 0.0;
      if (x > 0) {                              // x FRU au plan plus gourmand, le reste au plan sobre
        var b = cLo[i];
        detail.push(ligneRes(d.fru, b.e, x, b.h, b.m, d, b.k));
        if (n - x > 1e-9) detail.push(ligneRes(d.fru, a.e, a.e.length ? n - x : 0.0, a.h, a.m, d, a.k));
      } else {
        detail.push(ligneRes(d.fru, a.e, a.e.length ? n : 0.0, a.h, a.m, d, a.k));
      }
    });
    frus.forEach(function (d, i) {
      if (incomplets[i].length) {
        detail.push({ "Type de FRU": d.fru, "Décision": "incomplet", "Entrées manquantes": incomplets[i].join(", "),
                      manques: incomplets[i] });
      }
    });
    return bilan(ligne, detail, muHi, cap, frus);
  }

  /** Résultat de la ligne. Coût fixe ou marge inconnus → NaN (jamais 0). */
  function bilan(ligne, detail, mu, cap, frus) {
    frus = frus || [];
    var c = ligne.cout_traitement_eur_kg;
    var masses = [];
    frus.forEach(function (d) {
      if (!inconnu(d.rebut_an) && !inconnu(d.poids_fru_kg)) masses.push(d.rebut_an * d.poids_fru_kg);
    });
    var masse = masses.length && masses.length === frus.length ? somme(masses) : NaN;
    var coutActuel = (c !== null && c !== undefined) ? masse * c : NaN;
    var inv = ligne.cout_installation_eur, fix = ligne.couts_fixes_annuels_eur;
    var invConnu = inv !== null && inv !== undefined, fixConnu = fix !== null && fix !== undefined;
    var amort = ligne.amortissement_ans;
    amort = Math.max(amort ? amort : 1, 1);
    var fixes = invConnu && fixConnu ? inv / amort + fix : NaN;
    var calc = detail.filter(function (r) { return r["Décision"] !== "incomplet"; });
    var col = function (nom) { return calc.length ? somme(calc.map(function (r) { return r[nom]; })) : NaN; };
    var marge = col("Marge variable / an (€)"), h = col("Heures / an"), n = col("FRU traitées / an");
    var moy = n ? marge / n : NaN;
    var excedent = fixConnu ? marge - fix : NaN;
    return {
      detail: detail,
      resume: {
        "Marge variable / an (€)": marge, "Coûts fixes annualisés (€)": fixes, "Résultat / an (€)": marge - fixes,
        "Heures utilisées / an": h, "Capacité (h/an)": cap, "Taux d'occupation": isFinite(cap) && cap ? h / cap : NaN,
        "FRU traitées / an": n, "Marge moyenne par FRU (€)": moy,
        "Seuil de rentabilité (FRU / an)": moy && moy > 0 ? fixes / moy : NaN,
        "Retour sur investissement (ans)": invConnu && excedent > 0 ? inv / excedent : NaN,
        "Valeur d'une heure opérateur en plus (€ net)": calc.length ? mu : NaN,
        "Types de FRU incomplets": detail.length - calc.length,
        "Masse des FRU rebutées (kg/an)": masse, "Masse détournée de la benne (kg/an)": col("Kg détournés / an"),
        "Coût actuel de traitement (€/an)": coutActuel
      }
    };
  }

  /** Situation actuelle (tout chez le recycleur actuel) contre ligne de démontage + tri. Flux annuels, € ; coût = négatif.
   *  `base` (facultatif) = résultat déjà calculé de optimiserLigne(ligne, frus). */
  function comparerScenarios(ligne, frus, base) {
    var r = (base || optimiserLigne(ligne, frus)).resume;
    var c = ligne.cout_traitement_eur_kg;
    c = (c !== null && c !== undefined) ? c : NaN;
    var evite = r["Masse détournée de la benne (kg/an)"] * c;
    var actuel = -r["Coût actuel de traitement (€/an)"];
    var margeHorsEvite = r["Marge variable / an (€)"] - evite;
    var lignes = [
      ["Traitement des FRU par le recycleur actuel", actuel, actuel + evite],
      ["Marge de la ligne : réemploi + vente au kg − main-d'œuvre", 0.0, margeHorsEvite],
      ["Coûts fixes de la ligne (installation amortie + annuels)", 0.0, -r["Coûts fixes annualisés (€)"]]
    ];
    lignes.push(["TOTAL", lignes[0][1] + lignes[1][1] + lignes[2][1], lignes[0][2] + lignes[1][2] + lignes[2][2]]);
    var masse = r["Masse des FRU rebutées (kg/an)"], detournee = r["Masse détournée de la benne (kg/an)"];
    return {
      lignes: lignes.map(function (l) {
        return { "Poste (€/an)": l[0], "Actuel": l[1], "Avec la ligne": l[2], "Écart": l[2] - l[1] };
      }),
      attrs: { "Masse rebutée (kg/an)": masse, "Masse détournée (kg/an)": detournee, "Part détournée": masse ? detournee / masse : NaN }
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

  /** Le modèle rejoué période par période sur le flux réel des FRU rebutées (lignes {Semaine, FRU, "FRU rebutées"}).
   *  Chaque période : capacité = heures annuelles / périodes ; coût fixe = (installation amortie + fixes annuels) / périodes,
   *  payé même si peu de FRU arrivent ; pas de stock d'une période à l'autre. */
  function resultatParPeriode(ligne, frus, flux, periodesParAn) {
    periodesParAn = periodesParAn || 52;
    var H = ligne.heures_operateur_an, inv = ligne.cout_installation_eur, fix = ligne.couts_fixes_annuels_eur;
    var connus = inv !== null && inv !== undefined && fix !== null && fix !== undefined;
    var amort = ligne.amortissement_ans;
    var fixeP = connus ? (inv / Math.max(amort ? amort : 1, 1) + fix) / periodesParAn : NaN;
    var noms = {}, semainesVues = {}, semaines = [], total = {};
    frus.forEach(function (d) { noms[d.fru] = true; });
    (flux || []).forEach(function (r) {
      var s = r.Semaine;
      if (!semainesVues[s]) { semainesVues[s] = true; semaines.push(s); }
      if (noms[r.FRU]) {
        var cle = s + "\u0000" + r.FRU;
        total[cle] = (total[cle] || 0) + (inconnu(r["FRU rebutées"]) ? 0 : +r["FRU rebutées"]);
      }
    });
    semaines.sort();
    var prep = preparer(ligne, frus);
    var lgP = {};
    for (var k in ligne) if (possede(ligne, k)) lgP[k] = ligne[k];
    lgP.heures_operateur_an = H ? H / periodesParAn : null;     // comme ligne.py : 0 heure ou inconnu = pas de limite
    function avecRebut(valeur) {
      return frus.map(function (d) {
        var c = {};
        for (var k2 in d) if (possede(d, k2)) c[k2] = d[k2];
        c.rebut_an = valeur(d.fru);
        return c;
      });
    }
    var cumul = 0, lignes = [];
    semaines.forEach(function (s) {
      var arrivees = 0;
      var frT = avecRebut(function (f) {
        var v = total[s + "\u0000" + f];
        if (v === undefined) return 0.0;
        arrivees += v;
        return v;
      });
      var r = optimiserLigne(lgP, frT, prep).resume;
      var res = r["Marge variable / an (€)"] - fixeP;
      cumul += res;
      lignes.push({ "Semaine": s, "FRU arrivées": arrivees, "FRU traitées": r["FRU traitées / an"], "Heures utilisées": r["Heures utilisées / an"],
                    "Capacité (h)": H ? H / periodesParAn : NaN, "Marge variable (€)": r["Marge variable / an (€)"],
                    "Coût fixe (€)": fixeP, "Résultat (€)": res, "Valeur d'une heure en plus (€)": r["Valeur d'une heure opérateur en plus (€ net)"],
                    "Résultat cumulé (€)": cumul });
    });
    var attrs = {};
    if (lignes.length) {
      var present = {};
      for (var cle in total) if (possede(total, cle)) present[cle.split("\u0000")[1]] = true;
      var moyen = avecRebut(function (f) {
        if (!present[f]) return 0.0;
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
    inconnu: inconnu, optionsDisponibles: optionsDisponibles, manques: manques, valeursOptions: valeursOptions,
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
