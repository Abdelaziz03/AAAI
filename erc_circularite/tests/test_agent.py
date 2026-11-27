"""Agents : un modèle pilote le dossier par des outils fermés, et la note ne contient que des chiffres du dossier.
Le modèle est une doublure qui suit un scénario ; aucun vrai modèle n'est appelé."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import erc  # noqa: E402
from erc import agent as AG, modele as M  # noqa: E402


@pytest.fixture()
def cfg(tmp_path):
    c = erc.charger_config(dossier=tmp_path, demo=True)
    c.figures, c.n_monte_carlo = False, 20
    return c


class Scenario:
    """Doublure d'un modèle privé : le pilote suit `actions`, le rédacteur écrit `note(preuves, tour)`, le relecteur rend `reserves`."""
    prive, nature, modele = True, "ce poste", "agent-test"

    def __init__(self, actions, note=None, reserves=()):
        self.actions, self.note, self.reserves, self.appels = list(actions), note, list(reserves), 0
        self.vus, self.redactions = [], 0

    def converser(self, messages, schema=None):
        self.appels += 1
        self.vus.append([dict(m) for m in messages])
        a = self.actions.pop(0) if self.actions else {"outil": "terminer", "arguments": {"constats": ["fin du scénario"]}}
        if isinstance(a, Exception):
            raise a
        return a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)

    def demander(self, consigne, contenu, schema=None):
        self.appels += 1
        if schema is not None:                                 # relecteur
            return json.dumps({"reserves": self.reserves}, ensure_ascii=False)
        self.redactions += 1
        return self.note(contenu, self.redactions)


def gain(preuves: str) -> str:
    return next(l for l in preuves.splitlines() if "Gain annuel" in l).split(" : ")[1].split(" (")[0]


def test_nombres_et_nombres_non_fondes():
    lus = [(v, d) for v, d, _ in AG.nombres("Gain 42 361 € ; 24 645,5 kg ; taux 15,3 % ; P95 ; FRU-A100 ; 900 h ; rev.2 ; 3 pièces")]
    assert lus == [(42361.0, 0), (24645.5, 1), (15.3, 1), (900.0, 0), (3.0, 0)]                                 # ni « P95 », ni « A100 », ni « rev.2 »
    preuves = ["Gain annuel : 42 361 € ; proportion 0.1534 ; masse 24665.49 kg ; 900 h"]
    assert AG.non_fondes("Le gain est de 42 361 €, soit 15,3 % ; 24 665 kg détournés en 900 h, en 3 étapes.", preuves) == []
    assert AG.non_fondes("Le gain est de 42 000 € et le retour de 1,7 an.", preuves) == ["42 000", "1,7"]         # arrondi libre ou nombre inventé
    assert AG.non_fondes("7 pièces", []) == [] and AG.non_fondes("12 pièces", []) == ["12"]


def test_plan_fixe_sans_modele_note_entierement_fondee(cfg):
    r = AG.executer(cfg)
    assert r["mode"].startswith("plan fixe") and r["nombres_non_fondes"] == [] and r["appels_au_modele"] == 0
    assert [j["quoi"] for j in r["journal"]] == [f"outil {n}" for n, _ in AG.PLAN_FIXE]
    note = r["fichiers"]["Note de décision"].read_text(encoding="utf-8")
    assert note == r["note"] and "DÉMONSTRATION" in note and "Gain annuel par rapport à la situation actuelle" in note
    for titre in ("## Recommandation", "## Ce qui la fonde", "## Ce qui manque pour en être sûr", "## Prochaines actions"):
        assert titre in note
    assert r["fichiers"]["Journal"].read_text(encoding="utf-8").count("\n") == 6 and "[indicateurs]" in r["fichiers"]["Preuves"].read_text(encoding="utf-8")
    assert str(cfg.dossier) not in note
    assert AG.main(["--demo", "--dossier", str(cfg.dossier.parent), "--sans-modele"]) == 0


def test_agents_outils_fermes_note_reecrite_et_reserves(cfg):
    actions = [{"outil": "diagnostic", "arguments": {}}, {"outil": "lancer_etape", "arguments": {"etape": "synthese"}},
               {"outil": "shell", "arguments": {"commande": "rm -rf /"}},                                    # hors de la liste fermée
               {"outil": "lire_table", "arguments": {"etape": "ligne", "nom": "Table inventée", "chemin": "/etc/passwd"}},
               {"outil": "lire_table", "arguments": {"etape": "ligne", "nom": "Plan optimal", "lignes": 3}},
               {"outil": "indicateurs", "arguments": {}}, {"outil": "composition", "arguments": {}}, {"outil": "file_de_revue", "arguments": {}},
               {"outil": "terminer", "arguments": {"constats": ["La ligne dégage un gain annuel positif.", "Des pièces restent à valider."]}}]
    note = lambda preuves, tour: (f"## Recommandation\nInstaller la ligne : gain de {gain(preuves)}" + (" et 123 456 € d'économies annexes" if tour == 1 else "") +
                                  ".\n## Ce qui la fonde\nLes indicateurs.\n## Ce qui manque pour en être sûr\nDes données.\n## Prochaines actions\nValider les pièces.")
    m = Scenario(actions, note, reserves=["La note ne dit pas que les données sont fictives."])
    r = AG.executer(cfg, m)
    quoi = [j["quoi"] for j in r["journal"]]
    assert r["mode"] == "agents sur le modèle « agent-test »" and r["nombres_non_fondes"] == []
    assert "note réécrite" in quoi and m.redactions == 2 and "123 456" not in r["note"]                        # le nombre inventé a été retiré
    assert gain("\n".join(l for l in open(r["fichiers"]["Preuves"], encoding="utf-8"))) in r["note"]
    assert "## Réserves du relecteur" in r["note"] and "données sont fictives" in r["note"]
    resultats = {j["quoi"]: j.get("resultat", "") for j in r["journal"]}
    assert resultats["outil shell"].startswith("Outil inconnu") and "outil limites" in quoi                    # l'essentiel oublié par le pilote est fait quand même
    table = [j for j in r["journal"] if j["quoi"] == "outil lire_table"]
    assert table[0]["resultat"].startswith("Table inconnue") and table[1]["resultat"].startswith("ligne / Plan optimal")
    assert "/etc/passwd" not in json.dumps([j.get("resultat") for j in r["journal"]])                         # un argument hors contrat est ignoré
    assert m.vus[1][-1]["content"].startswith("Résultat de diagnostic") and m.appels == r["appels_au_modele"]
    assert set(p.name for p in (cfg.artefacts / "agent").iterdir()) == {"Note_de_decision.md", "Preuves.txt", "Journal.jsonl"}


def test_nombre_invente_maintenu_signale_en_tete(cfg):
    note = lambda preuves, tour: f"## Recommandation\nGain de {gain(preuves)}, plus 987 654 € promis.\n"
    r = AG.executer(cfg, Scenario([{"outil": "indicateurs", "arguments": {}}, {"outil": "terminer", "arguments": {"constats": ["ok"]}}], note))
    assert r["nombres_non_fondes"] == ["987 654"] and "Attention : nombres absents des preuves" in r["note"] and "987 654" in r["note"].split("##")[0]


def test_pilote_defaillant_le_plan_fixe_termine(cfg):
    for actions in (["je réfléchis", "toujours pas du JSON"],                                                  # deux réponses illisibles
                    [M.Indisponible("TimeoutError")],                                                         # modèle en panne
                    [{"outil": "diagnostic", "arguments": {}}] * 50):                                         # ne conclut jamais
        m = Scenario(actions, lambda p, t: "note")
        r = AG.executer(cfg, m, pas_max=5)
        assert r["mode"] == "plan fixe : le modèle n'a pas pu piloter" and r["nombres_non_fondes"] == [] and m.redactions == 0
        assert {f"outil {n}" for n, _ in AG.PLAN_FIXE} <= {j["quoi"] for j in r["journal"]} and "## Ce qui la fonde" in r["note"]
        assert m.appels <= 5

    class Exterieur(Scenario):
        prive = False
    with pytest.raises(PermissionError, match="n'est pas privé"):
        AG.executer(cfg, Exterieur([]))


def test_outils_erreurs_et_conversation_raccourcie(cfg):
    s = AG.Session(cfg)
    assert AG.appeler(s, "test", "lancer_etape", {"etape": "inconnue"}).startswith("Étape inconnue")
    AG.OUTILS["casse"] = ("outil d'essai", {}, lambda s: 1 / 0)
    try:
        assert AG.appeler(s, "test", "casse") == "Erreur de l'outil « casse » : ZeroDivisionError." and "casse" not in s.faits
    finally:
        AG.OUTILS.pop("casse")
    assert len(AG.appeler(s, "test", "lancer_etape", {"etape": "classement"})) <= AG.TAILLE_RESULTAT + 2
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "début"}] + [{"role": "user", "content": "x" * 3000} for _ in range(10)]
    court = AG._raccourcir(messages)
    assert sum(len(m["content"]) for m in court) < 10 * 3000 and court[-1]["content"] == "x" * 3000 and court[2]["content"].endswith("(raccourci)")
