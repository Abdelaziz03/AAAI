"""Recette de la machine virtuelle : rien des données dans l'image, pas de port publié, réseau sans sortie, et le
serveur de modèle du conteneur n'est accepté que parce que le réglage d'exemple le déclare."""
import configparser
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from erc import modele as M  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
D = RACINE / "deploiement"


def test_rien_des_donnees_n_entre_dans_l_image():
    ignores = (RACINE / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for chemin in ("artefacts/", "parametres/*", "cortex/", "papier/site/", "papier/manuscrit_site.pdf", "deploiement/volumes/"):
        assert chemin in ignores
    recette = (D / "Dockerfile").read_text(encoding="utf-8")
    assert "USER erc" in recette and recette.index("USER erc") > recette.index("COPY . .")      # le dossier ne tourne pas en administrateur
    assert "EXPOSE" not in recette


def test_reseau_sans_sortie_aucun_port_donnees_en_lecture_seule():
    c = (D / "compose.yaml").read_text(encoding="utf-8")
    lignes = [l.split("#")[0].rstrip() for l in c.splitlines()]
    assert "    internal: true" in lignes
    assert not any(l.strip().startswith("ports:") for l in lignes)
    assert any(l.strip().endswith(":/donnees:ro") for l in lignes)
    for volume in ("parametres", "artefacts", "cortex", "papier_site"):
        assert f"./volumes/{volume}:" in c


def test_le_serveur_du_conteneur_est_prive_parce_qu_il_est_declare():
    r = configparser.ConfigParser()
    r.read(D / "reglage_du_modele.exemple", encoding="utf-8")
    url, confiance = r["modele"]["url"], [x.strip() for x in r["modele"]["serveurs_de_confiance"].split(",") if x.strip()]
    assert url == "http://modele:11434/v1" and confiance == ["modele"]
    assert M.ModeleLocal(url, "un-modele", confiance=confiance).prive is True
    with pytest.raises(ValueError):                             # sans la déclaration, ce serveur est refusé
        M.ModeleLocal(url, "un-modele")
