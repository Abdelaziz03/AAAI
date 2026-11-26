// Exécute les fonctions sans affichage de la page de revue (bloc LOGIQUE du gabarit) sur un jeu donné en entrée.
//   node tests/composition_logique.mjs <gabarit.html> < entree.json > sortie.json
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const gabarit = readFileSync(process.argv[2], "utf-8");
const debut = gabarit.indexOf("/*__LOGIQUE_DEBUT__*/"), fin = gabarit.indexOf("/*__LOGIQUE_FIN__*/");
if (debut < 0 || fin < 0) throw new Error("bloc LOGIQUE introuvable dans le gabarit");
const module_ = { exports: {} };
new Function("module", "require", gabarit.slice(debut, fin))(module_, createRequire(import.meta.url));
const L = module_.exports;

const e = JSON.parse(readFileSync(0, "utf-8"));
const sondage = new Set(e.sondage || []);
const sortie = {
  csv: L.csvValidations(e.decisions, e.validateur),
  files: Object.fromEntries(["a-valider", "sondage", "acceptees", "validees", "decisions", "toutes"].map(
    f => [f, L.filtrer(e.pieces, f, "", sondage, e.decisions).map(p => p.pn)])),
  recherche: L.filtrer(e.pieces, "toutes", e.recherche || "", sondage, e.decisions).map(p => p.pn),
  compte: L.compter(e.pieces),
  partages: Object.fromEntries(e.pieces.map(p => [p.pn, L.partage(p)])),
  nettoyees: L.nettoyer(e.a_nettoyer || {}, e.pieces),
  motifs: Object.fromEntries(e.pieces.map(p => [p.pn, L.motifDe(p, sondage)])),
};
process.stdout.write(JSON.stringify(sortie));
