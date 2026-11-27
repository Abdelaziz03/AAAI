#!/bin/sh
# Lance le dossier de bout en bout sur ce poste : diagnostic, calculs, composition des pièces, note de décision.
# Rien n'est envoyé hors du poste.
cd "$(dirname "$0")" || exit 1
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
"$PY" -m erc.diagnostic && "$PY" -m erc.agent
echo
echo "Terminé. Les résultats sont dans artefacts/ (en démonstration : demo/artefacts/)."
