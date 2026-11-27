"""Chiffres du manuscrit : les expériences synthétiques vérifient les résultats qu'elles illustrent, rien de nominatif
ne sort du dossier, et toute macro employée par le manuscrit est bien écrite par `erc.papier`."""
import math
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import erc  # noqa: E402
from erc import composition as C, cortex as K, ligne as L, papier as P  # noqa: E402

PAPIER = Path(__file__).resolve().parent.parent / "papier"


@pytest.fixture()
def cfg(tmp_path):
    c = erc.charger_config(dossier=tmp_path / "dossier", demo=True)
    c.figures, c.n_monte_carlo = False, 20
    return c


# ------------------------------------------------------------------ mise en forme
def test_formats_et_inconnu():
    assert P.nombre(12345.6) == r"12\,346" and P.nombre(0.125, 2) == "0.12" and P.nombre(None) == "n/a" and P.nombre(float("nan")) == "n/a"
    assert P.pourcent(0.256) == r"26\%" and P.pourcent(None) == "n/a"
    assert P.petit(0.0321) == "0.0321" and P.petit(0.0) == "0" and P.petit(1.1e-7) == r"$1.1\times10^{-7}$" and P.petit(None) == "n/a"
    assert P.duree(float("nan")) == "---" and P.duree(3.14159) == "3.1"


# ------------------------------------------------------------------ proposition 1 : prix d'un type sans énumération
def test_prix_separable_egale_l_enumeration_et_rend_le_seuil():
    seuil = L.MAX_PIECES_ENUM
    r = P.exp_prix(tailles_enum=(3, 9), tailles=(40,), prix=8)
    assert r["ecart"] < 1e-9
    assert L.MAX_PIECES_ENUM == seuil and all(n <= seuil for n in L._CODES)        # le seuil levé pour la mesure est rendu
    assert [x["n"] for x in r["rangs"]] == [3, 9, 40] and math.isnan(r["rangs"][-1]["enum_ms"])


# ------------------------------------------------------------------ proposition 5 : écart de variabilité
def test_ecart_de_variabilite_nul_a_flux_constant_et_jamais_negatif():
    r = P.exp_variabilite(semaines=8, types=2, parts=(0.5, 1.2))
    constant = r["rangs"][0]
    assert constant["loi"] == "Constant" and all(abs(constant[p]) < 1e-9 for p in r["parts"])
    assert all(x[p] >= -1e-9 for x in r["rangs"] for p in r["parts"])


# ------------------------------------------------------------------ proposition 9 : fusion
def test_borne_de_fusion_domine_la_simulation():
    r = P.exp_fusion(essais=4000)
    for x in r["rangs"]:
        marge = 4 * math.sqrt(max(x["erreur"] * (1 - x["erreur"]), 1e-4) / r["essais"])
        assert x["erreur"] <= x["borne"] + marge, x
    assert P.borne_fusion(1 / 9, 9, 50) == 1.0                  # source au hasard : aucune information, quel que soit le nombre
    assert P.borne_fusion(1.0, 9, 1) == 0.0 and P.borne_fusion(0.0, 2, 1) == 0.0   # toujours juste, ou toujours fausse entre deux valeurs


@pytest.mark.parametrize("r, n, delta", [(0.9, 9, 0.02), (0.6, 9, 0.02), (0.75, 5, 0.001), (0.05, 9, 0.1)])
def test_assertions_suffisantes(r, n, delta):
    k = P.assertions_suffisantes(r, n, delta)
    assert P.borne_fusion(r, n, k) <= delta and (k == 1 or P.borne_fusion(r, n, k - 1) > delta)


def _fiabilite_connue(r: float) -> pd.DataFrame:
    return pd.DataFrame({"Type de source": ["document"], "_a": [r * 1e7], "_b": [(1 - r) * 1e7]})


def test_la_fusion_du_cortex_suit_la_regle_des_comptes():
    """Fiabilité connue (loi Bêta très serrée) : la classe retenue est la plus nommée si la source vaut mieux que le
    hasard, la moins nommée si elle vaut moins, et la probabilité est celle de la proposition 9."""
    classes = ["A", "B", "C", "D"]
    n = len(classes) + 1
    with K.Cortex(":memory:") as cx:
        for i, c in enumerate(["A", "A", "B", "A", "C"]):
            cx.affirmer(C.DOMAINE, "x", C.ATTRIBUT, c, "document", f"site-{i}")
        r = 0.7
        b = cx.croyance(C.DOMAINE, "x", C.ATTRIBUT, classes, None, _fiabilite_connue(r))
        q = (1 - r) / (n - 1)
        poids = {c: (r / q) ** k for c, k in {"A": 3, "B": 1, "C": 1, "D": 0, K.HORS: 0}.items()}
        assert b["retenue"] == "A" and math.isclose(b["probabilite"], poids["A"] / sum(poids.values()), rel_tol=1e-4)
    with K.Cortex(":memory:") as cx:
        for i, c in enumerate(["A", "B", "C", "une classe hors liste"]):
            cx.affirmer(C.DOMAINE, "x", C.ATTRIBUT, c, "document", f"site-{i}")
        b = cx.croyance(C.DOMAINE, "x", C.ATTRIBUT, classes, None, _fiabilite_connue(0.02))
        assert b["retenue"] == "D"                              # la seule valeur que cette source, presque toujours fausse, n'a pas nommée
        hasard = cx.croyance(C.DOMAINE, "x", C.ATTRIBUT, classes, None, _fiabilite_connue(1 / n))
        assert all(math.isclose(v, 1 / n, rel_tol=1e-4) for v in hasard["probabilites"].values())


# ------------------------------------------------------------------ proposition 10 : fiabilité par strates
def test_biais_des_validations_reunies_et_estimateur_par_strates():
    r = P.exp_strates(essais=20000)
    assert math.isclose(r["attendu_ensemble"] - r["vraie"], (r["r_acc"] - r["r_file"]) * (r["k_acc"] / (r["k_acc"] + r["k_file"]) - r["n_acc"] / (r["n_acc"] + r["n_file"])))
    assert abs(r["ensemble"] - r["attendu_ensemble"]) < 0.005 and abs(r["strates"] - r["vraie"]) < 0.005
    assert r["eqm_strates"] < r["eqm_ensemble"]
    sans_biais = P.exp_strates(k_acc=80, k_file=20, essais=20000)        # validations en proportion des strates : plus de biais
    assert abs(sans_biais["attendu_ensemble"] - sans_biais["vraie"]) < 1e-12


# ------------------------------------------------------------------ lemme 1 : invariant de budget
def test_la_chaine_ne_depense_jamais_plus_que_le_plafond():
    r = P.exp_chaine(pieces=60)
    assert r["ratio_max"] <= 1 + 1e-9 and r["exces_max"] <= 1e-9
    assert r["appels_sous_le_minimum"] == 0                     # enjeu sous la moins chère des actions : aucun appel
    assert r["appels"] < r["appels_exhaustif"] and r["cout"] <= r["enjeu_total"]
    assert r["acceptees"] + r["revue"] + r["laissees"] == r["pieces"]
    assert math.isclose(sum(c["part_enjeu"] for c in r["cinquiemes"]), 1.0)


def test_apprentissage_le_tirage_a_posteriori_corrige_l_a_priori():
    r = P.exp_apprentissage()["rangs"]
    assert r[0]["testees"] == 0 and r[1]["testees"] == 0 and r[2]["testees"] > 0.8 and r[2]["regret"] < r[0]["regret"] / 5


# ------------------------------------------------------------------ écriture, confidentialité, cohérence avec le manuscrit
@pytest.fixture(scope="module")
def ecrit(tmp_path_factory):
    d = tmp_path_factory.mktemp("papier")
    c = erc.charger_config(dossier=d / "dossier", demo=True)
    c.figures, c.n_monte_carlo = False, 20
    return P.ecrire(c, dossier=d / "papier")


def test_rien_de_nominatif_ne_sort(ecrit):
    textes = "".join(f.read_text(encoding="utf-8") for f in ecrit["dossier"].glob("*.tex"))
    for interdit in ("FRU-", "P-10", "P-30", "CARCASSE", "BET-", "PN0"):
        assert interdit not in textes
    assert r"\newcommand{\DonneesDemo}{1}" in textes            # le bandeau « démonstration » sera affiché
    assert {f.name for f in ecrit["dossier"].glob("*.pdf")} == {"fig_prix.pdf", "fig_variabilite.pdf", "fig_regret.pdf", "fig_architecture.pdf"}


def test_echelle_ne_touche_que_les_montants_de_l_etude_de_cas(cfg):
    un, demi = P.etude_de_cas(cfg), P.etude_de_cas(cfg, echelle=0.5)
    assert math.isclose(demi["resultat"], 0.5 * un["resultat"]) and math.isclose(demi["mu"], 0.5 * un["mu"])
    assert demi["heures"] == un["heures"] and demi["types"] == un["types"] and math.isclose(demi["gamma_rel"], un["gamma_rel"])
    assert un["partages"] <= 1                                  # proposition 3 : au plus un type partagé entre deux plans


def test_toute_macro_du_manuscrit_est_ecrite(ecrit):
    definies = set(re.findall(r"\\newcommand\{\\(\w+)\}", (ecrit["dossier"] / "macros.tex").read_text(encoding="utf-8")))
    sources = [PAPIER / "document.tex", *sorted((PAPIER / "sections").glob("*.tex"))]
    employees = set()
    for f in sources:
        employees |= set(re.findall(r"\\((?:Syn|Cas|Cout|Seuil|Donnees|Echelle)[A-Za-z]+)", f.read_text(encoding="utf-8")))
    assert employees and not employees - definies, sorted(employees - definies)
    corps = {m for f in sources for m in re.findall(r"\\corps\{(\w+)\}", f.read_text(encoding="utf-8"))}
    assert corps and all((ecrit["dossier"] / f"{c}.tex").is_file() for c in corps)


def test_references_citees_existent():
    cles = set(re.findall(r"@\w+\{(\w+),", (PAPIER / "references.bib").read_text(encoding="utf-8")))
    citees = set()
    for f in sorted((PAPIER / "sections").glob("*.tex")):
        for groupe in re.findall(r"\\cite[tp]?\{([^}]+)\}", f.read_text(encoding="utf-8")):
            citees |= {c.strip() for c in groupe.split(",")}
    assert citees and not citees - cles, sorted(citees - cles)


def test_les_chiffres_du_site_ont_leur_dossier_jamais_empaquete(tmp_path):
    assert P.dossier_des_sorties(tmp_path, True).name == "genere" and P.dossier_des_sorties(tmp_path, False).name == "site"
    assert P.nom_du_manuscrit(True) == "manuscrit" and P.nom_du_manuscrit(False) == "manuscrit_site"
    ignores = (PAPIER.parent / ".gitignore").read_text(encoding="utf-8")
    assert "/papier/site/" in ignores and "/papier/manuscrit_site.pdf" in ignores
    sys.path.insert(0, str(PAPIER.parent / "outils"))
    import empaqueter
    faux = tmp_path / "poste"
    for nom in ("papier/site/macros.tex", "papier/manuscrit_site.pdf", "papier/manuscrit_site.tex", "papier/manuscrit.aux", "papier/genere/macros.tex",
                "papier/document.tex", "erc/__init__.py"):
        (faux / nom).parent.mkdir(parents=True, exist_ok=True)
        (faux / nom).write_text("x", encoding="utf-8")
    noms = {f.as_posix() for f in empaqueter.fichiers(faux)}
    assert noms == {"papier/manuscrit_site.tex", "papier/genere/macros.tex", "papier/document.tex", "erc/__init__.py"}
    for enveloppe, dossier in (("manuscrit.tex", "genere"), ("manuscrit_site.tex", "site")):
        assert "\\newcommand{\\genere}{" + dossier + "}" in (PAPIER / enveloppe).read_text(encoding="utf-8")


@pytest.mark.skipif(not (shutil.which("pdflatex") and shutil.which("bibtex")), reason="pdflatex ou bibtex absent : compilation non essayée")
def test_le_manuscrit_compile(tmp_path, ecrit):
    d = tmp_path / "papier"
    shutil.copytree(PAPIER, d, ignore=shutil.ignore_patterns("*.pdf", "genere", "site"))
    shutil.copytree(ecrit["dossier"], d / "genere")
    pdf = P.compiler(d)
    assert pdf is not None and pdf.is_file() and pdf.stat().st_size > 100_000
    assert not (d / "manuscrit.aux").exists()


def test_archive_overleaf_se_compile_seule(tmp_path, ecrit):
    """L'archive pour Overleaf contient le texte et les chiffres, rien d'autre, et document.tex s'y compile tel quel."""
    d = tmp_path / "papier"
    shutil.copytree(PAPIER, d, ignore=shutil.ignore_patterns("*.pdf", "*.zip", "genere", "site"))
    shutil.copytree(ecrit["dossier"], d / "genere")
    archive = P.archive_overleaf(d, demo=True)
    assert archive.name == "Manuscrit_Overleaf.zip"
    with zipfile.ZipFile(archive) as z:
        noms = set(z.namelist())
        z.extractall(tmp_path / "overleaf")
    assert {"document.tex", "references.bib", "genere/macros.tex", "genere/fig_architecture.pdf", "sections/A_proofs.tex", "LISEZ-MOI.txt"} <= noms
    assert not [n for n in noms if n.startswith("site/") or "manuscrit" in n]          # ni chiffres du site, ni enveloppes, ni PDF
    with pytest.raises(FileNotFoundError):
        P.archive_overleaf(d, demo=False)                       # pas de chiffres du site : rien à empaqueter, et c'est dit
    (d / "site").mkdir()
    for f in (d / "genere").iterdir():
        shutil.copy(f, d / "site" / f.name)
    site = P.archive_overleaf(d, demo=False)
    with zipfile.ZipFile(site) as z:
        assert site.name == "Manuscrit_Overleaf_site.zip" and "genere/macros.tex" in z.namelist() and "ATTENTION" in z.read("LISEZ-MOI.txt").decode("utf-8")
    assert "/papier/Manuscrit_Overleaf_site.zip" in (PAPIER.parent / ".gitignore").read_text(encoding="utf-8")
    if not (shutil.which("pdflatex") and shutil.which("bibtex")):
        pytest.skip("pdflatex ou bibtex absent : compilation de l'archive non essayée")
    o = tmp_path / "overleaf"
    for commande in (["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "document.tex"], ["bibtex", "document"],
                     ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "document.tex"]):
        r = subprocess.run(commande, cwd=o, capture_output=True, text=True, errors="replace")
        assert r.returncode == 0, r.stdout[-1500:]
    assert (o / "document.pdf").stat().st_size > 100_000
