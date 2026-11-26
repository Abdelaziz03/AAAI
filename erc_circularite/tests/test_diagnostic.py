"""Diagnostic du poste et archive : ce que le dossier dit de lui-même sans rien demander à l'extérieur."""
import json
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "outils"))
import erc  # noqa: E402
from erc import diagnostic as DG, modele as M  # noqa: E402
import empaqueter as EMP  # noqa: E402


class Serveur(BaseHTTPRequestHandler):
    modeles = ["qwen3.5:9b", "qwen3.8:27b-q4_K_M", "nomic-embed-text:latest"]

    def _json(self, objet):
        corps = json.dumps(objet).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        self._json({"data": [{"id": m} for m in type(self).modeles]})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
        question = corps["messages"][1]["content"]
        if question.startswith("Affirmation"):
            if corps.get("reasoning_effort") == "none":
                return self._json({"choices": [{"message": {"content": '{"verdict": "oui"}'}}]})
            return self._json({"choices": [{"message": {"content": "", "reasoning": 'je regarde {"verdict": "oui"}'}}]})
        if question.startswith("Désignation"):
            return self._json({"choices": [{"message": {"content": '{"classe": "Câble", "indice": "Cable"}'}}]})
        self._json({"choices": [{"message": {"content": '{"classe": "Câble", "citation": "conducteurs en cuivre étamé, gaine en PVC souple"}'}}]})

    def log_message(self, *a):
        pass


@pytest.fixture()
def port():
    s = HTTPServer(("127.0.0.1", 0), Serveur)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_port
    s.shutdown()


def nvidia(sortie=None, erreur=None):
    def commande(*a, **k):
        if erreur:
            raise erreur
        return subprocess.CompletedProcess(a, 0, stdout=sortie, stderr="")
    return commande


def test_carte_graphique_lue_absente_ou_bloquee():
    g = DG.carte_graphique(nvidia("NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU, 8151\n"))
    assert g["cartes"] == [{"nom": "NVIDIA RTX PRO 2000 Blackwell Generation Laptop GPU", "memoire_go": 8.0}] and g["raison"] is None
    assert [c["memoire_go"] for c in DG.carte_graphique(nvidia("Carte A, 24564\nCarte B, 16376\n"))["cartes"]] == [24.0, 16.0]
    assert "introuvable" in DG.carte_graphique(nvidia(erreur=FileNotFoundError()))["raison"]
    assert "PermissionError" in DG.carte_graphique(nvidia(erreur=PermissionError()))["raison"]                 # bloqué par la sécurité du poste
    assert DG.carte_graphique(nvidia(""))["cartes"] == []


def test_modele_qui_tient_dans_la_carte():
    assert DG.besoin_memoire_go("qwen3.8:27b-q4_K_M") == pytest.approx(18.2, abs=0.5)                          # environ 17 Go de poids, plus le contexte
    assert DG.besoin_memoire_go("qwen3.5:9b") < 8 and DG.besoin_memoire_go("qwen3.8:27b-q8_0") > 30 and DG.besoin_memoire_go("qwen3.8:27b-bf16") > 55
    assert DG.besoin_memoire_go("gemma4:e4b") == pytest.approx(4.0, abs=0.1) and DG.besoin_memoire_go("modele-sans-taille") is None
    assert DG.besoin_memoire_go("qwen3.5:9b") is not None and DG.besoin_memoire_go("qwen3.5") is None            # « 3.5 » n'est pas une taille
    noms = ["qwen3.5:9b", "qwen3.8:27b-q4_K_M", "gemma4:12b", "nomic-embed-text:latest", "inconnu"]
    assert DG.choisir_modele(noms, 8.0) == "qwen3.5:9b" and DG.choisir_modele(noms, 12.0) == "gemma4:12b" and DG.choisir_modele(noms, 24.0) == "qwen3.8:27b-q4_K_M"
    assert DG.choisir_modele(noms, None) == "qwen3.5:9b" and DG.choisir_modele(noms, 2.0) == "qwen3.5:9b"       # carte inconnue ou trop petite : le plus petit
    assert DG.choisir_modele(["nomic-embed-text:latest", "inconnu"], 24.0) is None
    assert (DG.modele_conseille(8.0), DG.modele_conseille(24.0), DG.modele_conseille(None)) == ("qwen3.5:9b", "qwen3.8:27b-q4_K_M", "qwen3.5:4b")


def test_diagnostic_sans_serveur_puis_avec(tmp_path, port, monkeypatch):
    for v in ("ERC_MODELE_URL", "ERC_MODELE_NOM", "ERC_MODELE_CLE"):
        monkeypatch.delenv(v, raising=False)
    cfg = erc.charger_config(dossier=tmp_path, demo=True)
    carte = nvidia("NVIDIA RTX PRO 2000, 8151\n")
    r = DG.diagnostiquer(cfg, carte, serveurs=[("Aucun", 9)])
    assert r["Python"]["Convient"] and all(p["Version"] for p in r["Paquets"] if p["Nécessaire"])
    assert r["Carte graphique"]["Mémoire retenue (Go)"] == 8.0 and r["Modèle conseillé pour cette carte"]["À télécharger"] == "qwen3.5:9b"
    assert r["Serveurs de modèle sur ce poste"] == [] and any("Sans modèle, le dossier fonctionne" in a for a in r["À faire"])
    assert any("démonstration" in a for a in r["À faire"]) and r["À faire"][-1].startswith("Lancer le dossier")
    texte = DG.en_texte(r)
    assert "À FAIRE, DANS L'ORDRE" in texte and str(tmp_path) not in texte                                     # ni chemin complet ni nom de machine
    # un serveur tourne sur le poste : le diagnostic le voit et propose le modèle qui tient dans la carte
    ici = [("Serveur de test", port)]
    r = DG.diagnostiquer(cfg, carte, serveurs=ici)
    assert r["Serveurs de modèle sur ce poste"][0]["Modèles"] == sorted(Serveur.modeles)
    assert any("« qwen3.5:9b »" in a and "--regler" in a for a in r["À faire"])
    assert any("« qwen3.8:27b-q4_K_M »" in a for a in DG.diagnostiquer(cfg, nvidia("Carte, 24564\n"), serveurs=ici)["À faire"])
    # --regler écrit le réglage une fois, avec le champ qui coupe le raisonnement sur ce serveur, et ne le réécrit jamais
    fait = DG.regler(cfg, carte, serveurs=ici)
    reglage = M.lire_reglage(cfg)
    assert "écrit" in fait and reglage.url == f"http://localhost:{port}/v1" and reglage.nom == "qwen3.5:9b" and reglage.corps == {"reasoning_effort": "none"}
    assert "n'est pas réécrit" in DG.regler(cfg, nvidia("Carte, 24564\n"), serveurs=ici) and M.lire_reglage(cfg).nom == "qwen3.5:9b"
    r = DG.diagnostiquer(cfg, carte, serveurs=ici)
    assert r["Réglage du modèle"]["Réponse"] == "prêt" and not any("ne répond pas" in a for a in r["À faire"])
    assert "rien n'a été écrit" in DG.regler(erc.charger_config(dossier=tmp_path / "autre", demo=True), carte, serveurs=[("Aucun", 9)])
    assert DG.main(["--demo", "--dossier", str(tmp_path)]) == 0 and (cfg.artefacts / "Diagnostic.txt").is_file()


def test_archive_complete_sans_donnees_et_empreintes(tmp_path):
    archive = EMP.empaqueter(tmp_path)
    assert archive.name == f"ERC_circularite_{erc.__version__}.zip"
    with zipfile.ZipFile(archive) as z:
        noms = z.namelist()
        z.extractall(tmp_path / "poste")
    assert all(n.startswith("erc_circularite/") for n in noms)
    for attendu in ("README.md", "INSTALLATION.md", "requirements.txt", "EMPREINTES.txt", "erc/ligne.py", "erc/gepa.py", "erc/outil_gabarit.html",
                    "docs/Modele_local.md", "notebooks/07_Composition_des_pieces.ipynb", "tests/test_ligne.py", "parametres/.gitkeep"):
        assert f"erc_circularite/{attendu}" in noms, attendu
    interdits = ("/artefacts/", "/cortex/", "/demo/", "__pycache__", ".pyc", "chemins.json", "modele_local.cfg", "consignes_modele.json", "ERC_Parametres.xlsx")
    assert not [n for n in noms if any(i in n for i in interdits)]                                            # ni résultats, ni paramètres saisis, ni démonstration générée
    poste = tmp_path / "poste" / "erc_circularite"
    assert DG.verifier_empreintes(poste)["etat"] == "intact"
    (poste / "erc" / "ligne.py").write_text("modifié", encoding="utf-8")
    (poste / "README.md").unlink()
    v = DG.verifier_empreintes(poste)
    assert v["etat"] == "différent" and "1 fichier(s) modifié(s), 1 absent(s)" in v["detail"]
    assert DG.verifier_empreintes(tmp_path)["etat"] == "sans objet"
