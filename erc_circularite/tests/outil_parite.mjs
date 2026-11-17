// Rejoue en JavaScript (erc/outil_modele.js) les cas préparés par tests/test_outil.py et écrit les résultats en JSON.
//
//     node tests/outil_parite.mjs <cas.json>  >  resultats.json
//
// cas.json : {"cas": [{"nom", "ligne", "frus", ["flux"], ["donnees"], ["monte_carlo": {"n", "graine"}]}]}
// Sortie   : {"resultats": [{"nom", "resume", "plan", "scenarios", "options", ["periodes"], ["modele"], ["monte_carlo"]}], "ms_max"}
// NaN s'écrit null, l'infini "inf" : JSON ne connaît ni l'un ni l'autre.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const ici = dirname(fileURLToPath(import.meta.url));
const M = require(join(ici, "..", "erc", "outil_modele.js"));

function propre(o) {
  if (typeof o === "number") {
    if (Number.isNaN(o)) return null;
    if (!Number.isFinite(o)) return o > 0 ? "inf" : "-inf";
    return o;
  }
  if (Array.isArray(o)) return o.map(propre);
  if (o && typeof o === "object") {
    const r = {};
    for (const [k, v] of Object.entries(o)) r[k] = propre(v);
    return r;
  }
  return o === undefined ? null : o;
}

const fichier = process.argv[2];
if (!fichier) {
  console.error("usage : node tests/outil_parite.mjs <cas.json>");
  process.exit(2);
}
const entree = JSON.parse(readFileSync(fichier, "utf-8"));
let msMax = 0;
const resultats = entree.cas.map((cas) => {
  const sortie = { nom: cas.nom };
  let ligne = cas.ligne, frus = cas.frus;
  if (cas.donnees) {                       // données de l'outil : conversion par versModele (valeurs centrales)
    const m = M.versModele(cas.donnees);
    sortie.modele = m;
    if (!ligne) { ligne = m.ligne; frus = m.frus; }
  }
  const t0 = performance.now();
  const r = M.optimiserLigne(ligne, frus);
  const ms = performance.now() - t0;
  sortie.ms = ms;
  if (ms > msMax) msMax = ms;
  sortie.resume = r.resume;
  sortie.plan = r.detail;
  sortie.scenarios = M.comparerScenarios(ligne, frus, r);
  const cTrait = ligne.cout_traitement_eur_kg;
  sortie.options = frus.map((d) => {
    const v = M.valeursOptions(Object.assign({}, d, { _c_trait: cTrait }), ligne.taux_horaire_eur);
    return { fru: d.fru, lignes: v.lignes, ouverture_soignee: v["Ouverture soignée (€/FRU)"], ouverture_sommaire: v["Ouverture sommaire (€/FRU)"] };
  });
  if (cas.flux) sortie.periodes = M.resultatParPeriode(ligne, frus, cas.flux);
  if (cas.monte_carlo && cas.donnees) {
    const mc = M.monteCarlo(cas.donnees, cas.monte_carlo.n, cas.monte_carlo.graine);
    sortie.monte_carlo = { p_rentable: mc.p_rentable, p5_mediane_p95: mc.p5_mediane_p95, n_calcules: mc.n_calcules,
                           frequence_traitement: mc.frequence_traitement, tirages: mc.tirages };
  }
  return sortie;
});

// Mesure de vitesse : 10 types de FRU x 8 pièces, toutes options calculables, capacité saturée.
function casDeVitesse() {
  const alea = M.creerAlea(7);
  const frus = [];
  for (let f = 0; f < 10; f++) {
    const pieces = [];
    for (let p = 0; p < 8; p++) {
      pieces.push({ piece: `P-${f}-${p}`, n_par_fru: 1 + Math.floor(alea() * 3), extraction_min: 2 + 10 * alea(), test_min: 1 + 20 * alea(),
                    tri_min: 0.5 + 2 * alea(), p_reutilisable: alea(), valeur_eur: 5 + 200 * alea(), poids_kg: 0.05 + alea(),
                    prix_recycleur_eur_kg: 0.1 + 8 * alea(), delai_semaines: null, valeur_semaine_eur: null, transport_eur: null });
    }
    frus.push({ fru: `FRU-${f}`, rebut_an: 50 + 300 * alea(), poids_fru_kg: 5 + 70 * alea(), ouverture_min: 10 + 40 * alea(),
                ouverture_tri_min: 5 + 10 * alea(), pieces });
  }
  const ligne = { heures_operateur_an: null, taux_horaire_eur: 42, cout_traitement_eur_kg: 0.25, cout_installation_eur: 30000,
                  amortissement_ans: 5, couts_fixes_annuels_eur: 6000 };
  const libre = M.optimiserLigne(ligne, frus).resume["Heures utilisées / an"];
  ligne.heures_operateur_an = libre * 0.6;
  M.optimiserLigne(ligne, frus);                     // mise en route
  let total = 0;
  const n = 5;
  for (let i = 0; i < n; i++) {
    const t0 = performance.now();
    M.optimiserLigne(ligne, frus);
    total += performance.now() - t0;
  }
  return total / n;
}

process.stdout.write(JSON.stringify({ resultats: propre(resultats), ms_max: msMax, ms_10_fru_8_pieces: casDeVitesse() }));
