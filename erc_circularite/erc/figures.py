"""Figures du dossier : un seul système visuel pour toutes les étapes.

    tracer(etape, ctx) -> [(nom, description, figure matplotlib), ...]

Le pipeline appelle `tracer` après chaque étape, enregistre chaque figure en PNG dans artefacts/<étape>/figures/
et l'inscrit au manifeste. Les données sont lues dans `ctx.res[étape]`.

Règles tenues par toutes les figures
    - une table vide ou sans les colonnes attendues : la figure n'est pas produite, sans erreur ;
    - une valeur inconnue est écrite « inconnu » ou laissée vide, jamais tracée à zéro ;
    - titres, axes et unités en français, nombres au format français (espace des milliers, virgule décimale) ;
    - en mode démonstration, chaque figure porte la mention « Démonstration : données fictives » ;
    - aucune figure à deux échelles verticales : deux grandeurs = deux cadres ;
    - dans une figure, une couleur a un seul rôle, et les mêmes objets gardent leur couleur d'une figure à l'autre
      (origine d'une pièce posée, réemploi et recyclage, gain et perte) ; la couleur n'est jamais le seul repère :
      la forme du marqueur, une étiquette ou la légende disent la même chose.

Les figures sont construites avec l'API objet de matplotlib (aucun état global, rien ne s'affiche tout seul).
"""
from __future__ import annotations

import math
import textwrap
import traceback

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.transforms import blended_transform_factory

# --------------------------------------------------------------------------- palette et tailles
# Source des couleurs : palette de référence du guide de visualisation utilisé pour ce dossier. Les séries ont été
# contrôlées avec son script de validation (clarté, saturation, écart entre couleurs voisines pour les visions
# daltoniennes ΔE ≥ 8, écart en vision normale ΔE ≥ 15) : 5 premières teintes en voisinage, 3 premières deux à deux.
SURFACE = "#fcfcfb"                                   # fond des figures
ENCRE, ENCRE_2, ENCRE_3 = "#0b0b0b", "#52514e", "#898781"     # texte principal, secondaire, discret
GRILLE, AXE = "#e1e0d9", "#c3c2b7"                    # quadrillage, lignes d'axe
BLEU, ORANGE, VERT_EAU, JAUNE, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
ROUGE = "#e34948"                                     # pôle « perte » des figures à deux pôles (bleu = gain)
BLEU_CLAIR, BLEU_FONCE = "#86b6ef", "#104281"         # même teinte, plus claire et plus foncée (ordre, provenance)
GRIS, GRIS_FONCE = "#c3c2b7", "#898781"               # contexte, « autres », référence
SERIE = [BLEU, ORANGE, VERT_EAU, JAUNE, MAGENTA]      # ordre fixe : la 1re série est toujours bleue, etc.
# Origine d'une pièce posée : couleur ET marqueur, les mêmes dans toutes les figures de fiabilité.
ORIGINES = {"Neuve": (BLEU, "o"), "Réparée": (ORANGE, "s"), "Récupérée": (VERT_EAU, "^")}

T_TITRE, T_SOUS, T_AXE, T_GRAD, T_ETIQ, T_NOTE = 12.5, 9.3, 9.0, 8.5, 8.0, 7.6     # tailles de texte (points)
LARGEUR = 8.6                                         # largeur des figures (pouces) ; enregistrées à 150 points par pouce
MENTION_DEMO = "Démonstration : données fictives"
# Police fournie avec matplotlib sur tous les systèmes : les figures ont la même mise en page sur chaque poste,
# quels que soient les réglages locaux. Appliquée seulement pendant la construction des figures (voir `tracer`).
REGLAGES = {"font.family": ["DejaVu Sans"]}
ESP = "\u202f"                                        # espace fine insécable (milliers, avant % et €)


# --------------------------------------------------------------------------- nombres et textes
def _fr(x, dec: int = 0, unite: str = "", signe: bool = False) -> str:
    """Nombre au format français ; « inconnu » si la valeur est absente."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "inconnu"
    if not math.isfinite(x):
        return "inconnu"
    x = round(x, dec)
    if x == 0:
        x = 0.0                                       # pas de « −0 »
    s = f"{abs(x):,.{dec}f}".replace(",", ESP).replace(".", ",")
    prefixe = "−" if x < 0 else ("+" if signe and x > 0 else "")
    return prefixe + s + unite


def _pct(x, dec: int = 0, signe: bool = False) -> str:
    """Fraction (0,25) écrite en pourcentage (25 %)."""
    try:
        return _fr(float(x) * 100, dec, ESP + "%", signe)
    except (TypeError, ValueError):
        return "inconnu"


def _fmt(dec: int = 0, unite: str = "", pct: bool = False) -> FuncFormatter:
    """Graduations au format français."""
    if pct:
        return FuncFormatter(lambda v, _p: _pct(v, dec))
    return FuncFormatter(lambda v, _p: _fr(v, dec, unite))


def _court(texte, n: int) -> str:
    """Texte ramené à n caractères, coupé proprement."""
    s = "" if texte is None or (isinstance(texte, float) and math.isnan(texte)) else " ".join(str(texte).split())
    return s if len(s) <= n else s[: max(n - 1, 1)].rstrip(" ,;:-") + "…"


def _lib(reference, description, n: int = 30) -> str:
    """« Référence · description courte »."""
    d = _court(description, n)
    return f"{reference} · {d}" if d else str(reference)


def _pluriel(n, singulier: str, pluriel: str | None = None) -> str:
    return f"{_fr(n)} {singulier if abs(n) < 2 else (pluriel or singulier + 's')}"


def _num(t: pd.DataFrame, colonne: str) -> pd.Series:
    return pd.to_numeric(t[colonne], errors="coerce")


def _vrai(s: pd.Series) -> pd.Series:
    """Colonne oui/non en booléens, qu'elle vienne du calcul (bool) ou d'un fichier relu (texte)."""
    if s.dtype == bool:
        return s
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "1.0", "oui", "vrai"])


# --------------------------------------------------------------------------- mesure des textes
_POLICES: dict = {}


def _largeur_texte(texte: str, taille: float, gras: bool = False) -> float:
    """Largeur d'un texte en pouces, mesurée dans la police des figures ; estimée si la mesure est impossible."""
    try:
        if gras not in _POLICES:
            from matplotlib import font_manager
            prop = font_manager.FontProperties(family=REGLAGES["font.family"], weight="bold" if gras else "normal")
            _POLICES[gras] = font_manager.get_font(font_manager.findfont(prop))
        police = _POLICES[gras]
        police.set_size(taille, 720)                  # mesure à haute résolution : sans les arrondis d'un tracé à l'écran
        police.set_text(str(texte), 0.0)
        return police.get_width_height()[0] / 64.0 / 720.0 * 1.02
    except Exception:
        return len(str(texte)) * taille * (0.66 if gras else 0.6) / 72.0


def _plier(texte: str, largeur: float, taille: float, gras: bool = False) -> list:
    """Coupe un texte en lignes qui tiennent dans `largeur` pouces."""
    lignes, courant = [], ""
    for mot in str(texte or "").split(" "):
        if not mot:
            continue
        essai = (courant + " " + mot).strip()
        if courant and _largeur_texte(essai, taille, gras) > largeur:
            lignes.append(courant)
            courant = mot
        else:
            courant = essai
    return lignes + [courant] if courant else lignes


def _colonnes_legende(poignees, largeur: float, maxi: int) -> int:
    """Plus grand nombre de colonnes (≤ maxi) pour que la légende tienne dans `largeur` pouces."""
    em = T_GRAD / 72.0
    largeurs = [_largeur_texte(h.get_label(), T_GRAD) + (1.5 + 0.5) * em for h in poignees]
    for c in range(max(min(maxi, len(largeurs)), 1), 1, -1):
        lignes = int(math.ceil(len(largeurs) / float(c)))
        total = sum(max(largeurs[i:i + lignes]) for i in range(0, len(largeurs), lignes)) + 1.5 * em * (c - 1)
        if total <= largeur:
            return c
    return 1


# --------------------------------------------------------------------------- accès aux données du contexte
def _table(ctx, etape: str, nom: str, colonnes=()):
    """Table d'une étape si elle existe, n'est pas vide et porte les colonnes demandées ; sinon None."""
    t = (getattr(ctx, "res", None) or {}).get(etape, {}).get(nom)
    if not isinstance(t, pd.DataFrame) or not len(t) or any(c not in t.columns for c in colonnes):
        return None
    return t


def _objet(ctx, etape: str, nom: str) -> dict:
    o = (getattr(ctx, "res", None) or {}).get(etape, {}).get(nom)
    return o if isinstance(o, dict) else {}


def _demo(ctx) -> bool:
    return bool(getattr(getattr(ctx, "cfg", None), "demo", False))


def _periode(ctx) -> str:
    p = getattr(getattr(ctx, "src", None), "periode", "")
    return p if isinstance(p, str) else ""


def _descriptions(ctx) -> dict:
    """Référence de pièce → description, depuis le classement."""
    t = _table(ctx, "classement", "Classement tous ateliers", ["Référence", "Description"])
    return {} if t is None else dict(zip(t["Référence"].astype(str), t["Description"]))


def _descriptions_fru(ctx) -> dict:
    t = _table(ctx, "classement", "FRU rebutées", ["FRU", "Description FRU"])
    d = {} if t is None else dict(zip(t["FRU"].astype(str), t["Description FRU"]))
    for f, v in (_objet(ctx, "ligne", "Modèle").get("frus") or {}).items():
        if isinstance(v, dict) and v.get("description"):
            d.setdefault(str(f), v["description"])
    return d


# --------------------------------------------------------------------------- cadre commun des figures
def _figure(largeur: float, hauteur: float) -> Figure:
    try:
        fig = Figure(figsize=(largeur, hauteur), layout="constrained")
    except TypeError:                                 # matplotlib < 3.5
        fig = Figure(figsize=(largeur, hauteur), constrained_layout=True)
    fig.patch.set_facecolor(SURFACE)
    return fig


def _trait(couleur, libelle, marqueur=None, epaisseur=1.8, plein=True, taille=6.5, style="-"):
    """Entrée de légende : trait, marqueur, ou les deux."""
    return Line2D([], [], color=couleur, linewidth=epaisseur, linestyle=style if epaisseur else "none", marker=marqueur,
                  markersize=taille, markerfacecolor=couleur if plein else SURFACE, markeredgecolor=couleur if not plein else SURFACE,
                  markeredgewidth=1.3 if not plein else 0.8, label=libelle)


def _pave(couleur, libelle, hachure=None, bord=None, alpha=None):
    """Entrée de légende : aplat de couleur (barres, bandes)."""
    return Patch(facecolor=couleur, edgecolor=bord or "none", hatch=hachure, linewidth=0, alpha=alpha, label=libelle)


def _cadre(ctx, h_corps: float, titre: str, sous_titre: str = "", note: str = "", legende=None, colonnes: int = 4,
           largeur: float = LARGEUR):
    """Figure à la mise en page commune. Renvoie (figure, emplacement du corps).

    De haut en bas : titre et sous-titre, légende (facultative), corps (les axes), pied (note de lecture à gauche,
    mention de démonstration à droite). Les hauteurs sont en pouces ; celle du corps est choisie par chaque figure.
    """
    demo = _demo(ctx)
    utile = largeur - 0.2                                         # largeur disponible une fois les marges retirées
    l_titre = _plier(titre, utile, T_TITRE, gras=True) or [""]
    l_sous = _plier(sous_titre, utile, T_SOUS)
    l_note = _plier(note, utile - (_largeur_texte(MENTION_DEMO, T_NOTE) + 0.3 if demo else 0.0), T_NOTE)
    if legende:
        colonnes = _colonnes_legende(legende, utile, colonnes)
    n_leg = int(math.ceil(len(legende) / float(colonnes))) if legende else 0
    h_tete = 0.08 + 0.235 * len(l_titre) + 0.18 * len(l_sous)
    h_leg = 0.21 * n_leg + 0.07 if n_leg else 0.0
    n_pied = max(len(l_note), 1 if demo else 0)
    h_pied = 0.145 * n_pied + 0.05 if n_pied else 0.0
    hauteurs = [h_tete] + ([h_leg] if n_leg else []) + [h_corps] + ([h_pied] if n_pied else [])
    fig = _figure(largeur, sum(hauteurs) + 0.25)
    gs = fig.add_gridspec(len(hauteurs), 1, height_ratios=hauteurs)
    rang = 0

    # Titre, légende et pied occupent toute la largeur de la figure (abscisse en fraction de figure), dans la hauteur
    # de leur bande (ordonnée en fraction de bande) : ils ne dépendent pas de la largeur des graduations du corps.
    gauche, droite = 0.06 / largeur, 1 - 0.06 / largeur

    tete = fig.add_subplot(gs[rang]); rang += 1
    tete.axis("off")
    repere = blended_transform_factory(fig.transFigure, tete.transAxes)
    t = tete.text(gauche, 1, "\n".join(l_titre), transform=repere, ha="left", va="top", fontsize=T_TITRE, fontweight="bold",
                  color=ENCRE, linespacing=1.15)
    t.set_in_layout(False)
    if l_sous:
        y = 1 - (0.235 * len(l_titre) + 0.05) / h_tete
        t = tete.text(gauche, y, "\n".join(l_sous), transform=repere, ha="left", va="top", fontsize=T_SOUS, color=ENCRE_2, linespacing=1.25)
        t.set_in_layout(False)

    if n_leg:
        bande = fig.add_subplot(gs[rang]); rang += 1
        bande.axis("off")
        leg = bande.legend(handles=list(legende), loc="center left", bbox_to_anchor=(gauche, 0.5),
                           bbox_transform=blended_transform_factory(fig.transFigure, bande.transAxes), ncol=colonnes, frameon=False,
                           fontsize=T_GRAD, handlelength=1.5, handletextpad=0.5, columnspacing=1.5, borderaxespad=0, borderpad=0, labelspacing=0.35)
        for txt in leg.get_texts():
            txt.set_color(ENCRE_2)
        leg.set_in_layout(False)

    corps = gs[rang]; rang += 1

    if n_pied:
        pied = fig.add_subplot(gs[rang])
        pied.axis("off")
        repere = blended_transform_factory(fig.transFigure, pied.transAxes)
        if l_note:
            t = pied.text(gauche, 1, "\n".join(l_note), transform=repere, ha="left", va="top", fontsize=T_NOTE, color=ENCRE_3, linespacing=1.25)
            t.set_in_layout(False)
        if demo:
            t = pied.text(droite, 1, MENTION_DEMO, transform=repere, ha="right", va="top", fontsize=T_NOTE, color=ENCRE_3, style="italic")
            t.set_in_layout(False)
    return fig, corps


def _axe(ax, grille="y", xlabel=None, ylabel=None, titre=None):
    """Habillage commun d'un cadre : fond, axes discrets, quadrillage plein et fin, textes gris."""
    ax.set_facecolor(SURFACE)
    for cote in ("top", "right"):
        ax.spines[cote].set_visible(False)
    for cote in ("left", "bottom"):
        ax.spines[cote].set_color(AXE)
        ax.spines[cote].set_linewidth(0.8)
    if grille == "x":                                 # barres horizontales : pas de trait vertical à gauche
        ax.spines["left"].set_visible(False)
    ax.tick_params(axis="both", labelsize=T_GRAD, colors=ENCRE_2, length=0, pad=4)
    ax.set_axisbelow(True)
    ax.grid(False)
    if grille in ("x", "y"):
        ax.grid(True, axis=grille, color=GRILLE, linewidth=0.8)
    elif grille == "xy":
        ax.grid(True, axis="both", color=GRILLE, linewidth=0.8)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=T_AXE, color=ENCRE_2, labelpad=5)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=T_AXE, color=ENCRE_2, labelpad=6)
    if titre:
        ax.set_title(titre, loc="left", fontsize=T_AXE + 0.3, color=ENCRE, fontweight="bold", pad=6)


def _etiquette(ax, texte, xy, decalage=(4, 0), ha="left", va="center", taille=T_ETIQ, couleur=ENCRE_2, gras=False, fond=False, **kw):
    """Étiquette posée à côté d'un point de données, décalée de quelques points. `fond` : sur un aplat de la couleur du
    fond, pour rester lisible au-dessus d'un trait de repère."""
    if fond:
        kw["bbox"] = {"facecolor": SURFACE, "edgecolor": "none", "pad": 1.2}
        kw.setdefault("zorder", 5)
    return ax.annotate(texte, xy, xytext=decalage, textcoords="offset points", ha=ha, va=va, fontsize=taille, color=couleur,
                       fontweight="bold" if gras else "normal", annotation_clip=False, **kw)


def _zero(ax, sens="v"):
    """Ligne du zéro, plus marquée que le quadrillage."""
    (ax.axvline if sens == "v" else ax.axhline)(0, color=ENCRE_2, linewidth=0.9, zorder=1.5)


def _semaines(dates: pd.Series):
    """Dates de semaine → (rangs entiers depuis la première semaine, fonction rang → libellé « jj/mm »)."""
    d = pd.to_datetime(dates, errors="coerce")
    debut = d.min()
    rangs = ((d - debut).dt.days / 7.0).round()
    plusieurs_annees = d.dt.year.nunique() > 1
    def libelle(i):
        j = debut + pd.Timedelta(days=7 * int(i))
        return j.strftime("%d/%m/%y") if plusieurs_annees else j.strftime("%d/%m")
    return rangs, libelle, debut


def _graduer_semaines(ax, n: int, libelle, maxi: int = 12):
    pas = max(int(math.ceil(n / float(maxi))), 1)
    pos = list(range(0, n, pas))
    ax.set_xticks(pos)
    ax.set_xticklabels([libelle(i) for i in pos])
    ax.set_xlim(-0.7, n - 0.3)


def _annee(debut, fin) -> str:
    return str(debut.year) if debut.year == fin.year else f"{debut.year}-{fin.year}"


def _placer_etiquettes(ax, points, tous, larg: float, haut: float, taille=T_ETIQ):
    """Étiquette des points d'un nuage sans chevauchement : essaie six positions autour du point et garde la moins
    encombrée. `points` : [(x, y, texte)] ; `tous` : [(x, y)] de tous les points tracés ; larg, haut : taille du cadre en pouces."""
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    fx = lambda x: (x - x0) / (x1 - x0)
    fy = lambda y: (y - y0) / (y1 - y0)
    lig = taille * 1.25 / 72.0 / haut                                        # hauteur d'une ligne, en fraction du cadre
    dx, dy = 7 / 72.0 / larg, 7 / 72.0 / haut
    places, pts = [], [(fx(x), fy(y)) for x, y in tous]
    positions = [(1, 0, "left", "center"), (-1, 0, "right", "center"), (0, 1, "center", "bottom"), (0, -1, "center", "top"),
                 (1, 1, "left", "bottom"), (1, -1, "left", "top")]
    for x, y, texte in sorted(points, key=lambda p: -p[1]):
        px, py, w = fx(x), fy(y), _largeur_texte(texte, taille) / larg
        meilleur = None
        for sx, sy, ha, va in positions:
            gx = px + sx * dx - (w if ha == "right" else w / 2 if ha == "center" else 0)
            gy = py + sy * dy - (lig if va == "top" else lig / 2 if va == "center" else 0)
            boite = (gx, gy, gx + w, gy + lig)
            cout = sum(10.0 for b in places if boite[0] < b[2] and b[0] < boite[2] and boite[1] < b[3] and b[1] < boite[3])
            cout += sum(3.0 for qx, qy in pts if (qx, qy) != (px, py) and boite[0] - 0.01 < qx < boite[2] + 0.01 and boite[1] - 0.015 < qy < boite[3] + 0.015)
            cout += 20.0 * (boite[0] < 0 or boite[2] > 1 or boite[1] < 0 or boite[3] > 1)
            if meilleur is None or cout < meilleur[0]:
                meilleur = (cout, sx, sy, ha, va, boite)
        _, sx, sy, ha, va, boite = meilleur
        places.append(boite)
        _etiquette(ax, texte, (x, y), decalage=(7 * sx, 7 * sy), ha=ha, va=va, taille=taille, couleur=ENCRE)


# =========================================================================== 1. classement
def _top_mmicv(ctx):
    t = _table(ctx, "classement", "Classement tous ateliers", ["Référence", "MMICV total (USD)"])
    if t is None:
        return None
    v = _num(t, "MMICV total (USD)")
    d = t.assign(_v=v)
    d = d[d["_v"] > 0].sort_values("_v", ascending=False).head(15)
    if not len(d):
        return None
    sans, nuls = int(v.isna().sum()), int((v <= 0).sum())
    n = len(d)
    desc = d["Description"] if "Description" in d else pd.Series([""] * n, index=d.index)
    part = _num(d, "Part du MMICV total") if "Part du MMICV total" in d else pd.Series(np.nan, index=d.index)
    titre = f"Les {n} pièces au MMICV total le plus élevé" if len(t) > n else "MMICV total des pièces consommées"
    sous = "Quantité consommée × MMICV unitaire, tous ateliers" + (f" ; {_periode(ctx)}" if _periode(ctx) else "") + ". Entre parenthèses : part du MMICV total."
    note = "Le MMICV est un coût standard : une référence provisoire, ni un prix de revente ni une valeur de réemploi."
    if sans:
        note += f" {_pluriel(sans, 'pièce')} sans MMICV connu : non classée{'s' if sans > 1 else ''}, et non comptée{'s' if sans > 1 else ''} à zéro."
    if nuls:
        note += f" {_pluriel(nuls, 'pièce')} au MMICV total nul : non tracée{'s' if nuls > 1 else ''}."
    fig, corps = _cadre(ctx, 0.55 + 0.29 * n, titre, sous, note)
    ax = fig.add_subplot(corps)
    y = np.arange(n)
    ax.barh(y, d["_v"].to_numpy(float), height=0.62, color=BLEU, edgecolor="none", zorder=2)
    for yi, vi, pi in zip(y, d["_v"], part):
        _etiquette(ax, _fr(vi) + (f"  ({_pct(pi, 0 if pi >= 0.01 else 1)})" if np.isfinite(pi) else ""), (vi, yi))
    ax.set_yticks(y)
    ax.set_yticklabels([_lib(r, de, 34) for r, de in zip(d["Référence"], desc)])
    ax.invert_yaxis()
    ax.set_xlim(0, float(d["_v"].max()) * 1.2)
    ax.xaxis.set_major_formatter(_fmt())
    _axe(ax, "x", xlabel="MMICV total sur la période (USD)")
    return ("Les pièces consommées classées par MMICV total (quantité × coût standard). Lecture : plus la barre est longue, plus la pièce "
            "pèse dans le coût standard consommé ; ce n'est pas ce que rapporterait son réemploi.", fig)


def _preselection(ctx, etape: str, nom_table: str, titre: str = "Pré-sélection des pièces : valeur consommée et gisement de FRU rebutées"):
    t = _table(ctx, etape, nom_table, ["Référence", "MMICV total (USD)", "FRU rebutées (nomenclature)", "Sur le front de Pareto"])
    if t is None:
        return None
    d = t.assign(_x=_num(t, "FRU rebutées (nomenclature)"), _y=_num(t, "MMICV total (USD)"), _p=_vrai(t["Sur le front de Pareto"]))
    hors = int(d[["_x", "_y"]].isna().any(axis=1).sum())
    d = d.dropna(subset=["_x", "_y"])
    if not len(d):
        return None
    actifs = t.attrs.get("Critères actifs") or _objet(ctx, etape, "Notes").get("criteres_actifs") or []
    court = {"MMICV total (USD)": "valeur", "FRU rebutées (nomenclature)": "gisement", "Score risque matière (0-1)": "risque matière",
             "Risque supply retenu": "risque d'approvisionnement", "Fiabilité réemploi (1/rapport)": "fiabilité du réemploi"}
    sous = "En bleu : pièces qu'aucune autre ne dépasse sur tous les critères à la fois (front de Pareto)."
    if actifs:
        sous += f" Le front est calculé sur {len(actifs)} critères ({', '.join(court.get(c, c) for c in actifs)}), pas seulement sur les deux axes."
    note = ("Gisement = FRU rebutées dont la nomenclature de consommation contient la pièce ; le nombre de pièces par FRU reste inconnu "
            "avant un audit de démontage. Le MMICV est un coût standard, pas une valeur de revente.")
    if hors:
        note += f" {_pluriel(hors, 'pièce')} sans valeur connue sur un des deux axes : non tracée{'s' if hors > 1 else ''}."
    legende = [_trait(BLEU, "Sur le front de Pareto", "o", epaisseur=0, taille=8), _trait(GRIS_FONCE, "Dépassée par une autre pièce", "o", epaisseur=0, taille=6)]
    h = 4.3
    fig, corps = _cadre(ctx, h, titre, sous, note, legende, colonnes=2)
    ax = fig.add_subplot(corps)
    a, b = d[~d["_p"]], d[d["_p"]]
    ax.plot(a["_x"], a["_y"], linestyle="none", marker="o", markersize=6, markerfacecolor=GRIS_FONCE, markeredgecolor=SURFACE, markeredgewidth=0.9, zorder=2)
    ax.plot(b["_x"], b["_y"], linestyle="none", marker="o", markersize=8.5, markerfacecolor=BLEU, markeredgecolor=SURFACE, markeredgewidth=1.1, zorder=3)
    ax.set_xlim(0, max(float(d["_x"].max()), 1.0) * 1.12)
    ax.set_ylim(0, max(float(d["_y"].max()), 1.0) * 1.1)
    ax.xaxis.set_major_formatter(_fmt())
    ax.yaxis.set_major_formatter(_fmt())
    _axe(ax, "xy", xlabel="FRU rebutées sur la période dont la nomenclature contient la pièce", ylabel="MMICV total consommé (USD)")
    desc = b["Description"] if "Description" in b else pd.Series([""] * len(b), index=b.index)
    points = [(x, y, _lib(r, de, 20)) for x, y, r, de in zip(b["_x"], b["_y"], b["Référence"], desc)][:14]
    _placer_etiquettes(ax, points, list(zip(d["_x"], d["_y"])), LARGEUR - 1.1, h - 0.6)
    description = ("Chaque point est une pièce : en abscisse le nombre de FRU rebutées qui la contiennent (gisement), en ordonnée son MMICV total "
                   "consommé (valeur). Les points bleus forment le front de Pareto : ce sont les candidates à examiner en premier.")
    if etape == "fiabilite":
        description += " La fiabilité du réemploi est ajoutée aux critères quand elle a pu être calculée : le front peut différer de celui de l'étape classement."
    return (description, fig)


# =========================================================================== 2. flux
def _fru_par_semaine(ctx):
    t = _table(ctx, "flux", "FRU rebutées par semaine", ["Semaine", "FRU", "FRU rebutées"])
    if t is None:
        return None
    d = t.assign(_s=pd.to_datetime(t["Semaine"], errors="coerce"), _n=_num(t, "FRU rebutées")).dropna(subset=["_s"])
    if not len(d) or not d["_n"].notna().any():
        return None
    rangs, libelle, debut = _semaines(d["_s"])
    d = d.assign(_r=rangs.astype(int))
    piv = d.pivot_table(index="_r", columns="FRU", values="_n", aggfunc="sum", fill_value=0)
    if not len(piv) or not len(piv.columns):
        return None
    totaux = piv.sum().sort_values(ascending=False)
    tetes, reste = list(totaux.index[:5]), list(totaux.index[5:])
    complet = _vrai(d["Semaine complète"]).groupby(d["_r"]).min() if "Semaine complète" in d else pd.Series(True, index=piv.index)
    jours = _num(d, "Jours extraits").groupby(d["_r"]).first() if "Jours extraits" in d else pd.Series(np.nan, index=piv.index)
    n_sem = int(piv.index.max()) + 1
    descf = _descriptions_fru(ctx)
    series = [(f, piv[f].to_numpy(float), SERIE[i], _lib(f, descf.get(str(f), ""), 26)) for i, f in enumerate(tetes)]
    if reste:
        series.append(("autres", piv[reste].sum(axis=1).to_numpy(float), GRIS, f"Autres types ({len(reste)})"))
    legende = [_pave(c, lab) for _, _, c, lab in series]
    incompletes = [int(r) for r in piv.index if not bool(complet.get(r, True))]
    if incompletes:
        legende.append(_pave(SURFACE, "Semaine incomplète (moins de 7 jours extraits)", hachure="/////", bord=ENCRE_2))
    total = piv.sum(axis=1)
    moyenne = float(total[[r for r in piv.index if r not in incompletes]].mean()) if len(piv.index) > len(incompletes) else np.nan
    if np.isfinite(moyenne):
        legende.append(_trait(ENCRE_2, f"Moyenne des semaines complètes : {_fr(moyenne, 1)} FRU par semaine", epaisseur=1.0))
    fin = debut + pd.Timedelta(days=7 * (n_sem - 1))
    sous = f"Une barre par semaine, du lundi au dimanche ({_annee(debut, fin)}). Une semaine extraite sans rebut compte pour zéro ; une semaine non extraite n'a pas de barre."
    note = "Date de rebut : " + _court(_objet(ctx, "flux", "Notes").get("regle_date_rebut", "règle non précisée"), 150) + "."
    fig, corps = _cadre(ctx, 3.3, "FRU rebutées par semaine et par type de FRU", sous, note, legende, colonnes=3)
    ax = fig.add_subplot(corps)
    x, bas = piv.index.to_numpy(float), np.zeros(len(piv))
    for _, v, c, _lab in series:
        ax.bar(x, v, width=0.72, bottom=bas, color=c, edgecolor=SURFACE, linewidth=0.9, zorder=2)
        bas = bas + v
    for r in incompletes:
        h = float(total.get(r, 0.0))
        if h > 0:
            ax.bar([r], [h], width=0.72, facecolor="none", edgecolor=ENCRE_2, hatch="/////", linewidth=0, zorder=3)
        j = jours.get(r, np.nan)
        _etiquette(ax, f"{_fr(j)} j" if np.isfinite(j) else "incomplète", (r, h), decalage=(0, 3), ha="center", va="bottom", taille=T_NOTE)
    if np.isfinite(moyenne):
        ax.axhline(moyenne, color=ENCRE_2, linewidth=1.0, zorder=2.5)
    _graduer_semaines(ax, n_sem, libelle)
    ax.set_ylim(0, float(total.max()) * 1.12 + 0.5)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
    ax.yaxis.set_major_formatter(_fmt())
    _axe(ax, "y", xlabel="Semaine (date du lundi)", ylabel="FRU rebutées")
    return ("Le flux d'entrée du modèle de ligne : nombre de FRU rebutées chaque semaine, empilé par type de FRU (les cinq types les plus "
            "fréquents, puis les autres). Les semaines incomplètes sont hachurées et ne servent pas à calculer le rebut annuel.", fig)


def _estime_contre_pese(ctx):
    cols = ["Semaine", "Flux", "Estimé bas (kg)", "Estimé central (kg)", "Estimé haut (kg)", "Masse mesurée (kg)", "Dans la marge"]
    t = _table(ctx, "flux", "Estimé contre pesé", cols)
    if t is None:
        return None
    d = t.assign(_s=pd.to_datetime(t["Semaine"], errors="coerce"), _c=_num(t, "Estimé central (kg)"), _b=_num(t, "Estimé bas (kg)"),
                 _h=_num(t, "Estimé haut (kg)"), _m=_num(t, "Masse mesurée (kg)")).dropna(subset=["_s"])
    d["_u"] = _num(d, "Incertitude mesure (kg)") if "Incertitude mesure (kg)" in d else np.nan
    d["_j"] = _num(d, "Jours extraits") if "Jours extraits" in d else np.nan
    if not len(d):
        return None
    rangs, libelle, debut = _semaines(d["_s"])
    d["_r"] = rangs.astype(int)
    n_sem = int(d["_r"].max()) + 1
    poids = d.groupby("Flux").agg(c=("_c", "sum"), nc=("_c", "count"), nm=("_m", "count"))
    traces = [f for f in poids.sort_values("c", ascending=False).index if poids.at[f, "nc"] or poids.at[f, "nm"]]
    muets = [str(f) for f in poids.index if f not in traces]
    if not traces:
        return None
    en_trop, traces = traces[6:], traces[:6]
    legende = [_trait(BLEU, "Masse estimée (valeur centrale)"), _pave(BLEU, "Marge d'erreur de l'estimation (bas à haut)", alpha=0.2),
               _trait(ENCRE, "Pesée dans la marge", "o", epaisseur=0), _trait(ORANGE, "Pesée hors de la marge", "D", epaisseur=0)]
    if (d["_j"] < 7).any():
        legende.append(_pave(GRILLE, "Semaine incomplète"))
    sous = ("Estimation = pièces consommées × poids unitaires. Bas : seules les pièces au poids connu ; haut : les autres comptées au poids moyen "
            "du flux. Barre verticale d'une pesée : son incertitude. Échelle verticale propre à chaque flux.")
    note = ""
    if muets:
        note += "Flux sans aucun poids connu, donc sans estimation ni tracé : " + ", ".join(muets) + ". "
    if en_trop:
        note += "Flux non tracés (au-delà de six) : " + ", ".join(str(f) for f in en_trop) + ". "
    if not d["_m"].notna().any():
        note += "Aucune pesée enregistrée : l'estimation n'est pas encore vérifiée."
    fig, corps = _cadre(ctx, 1.85 * len(traces) + 0.35, "Masse estimée contre masse pesée, par semaine et par flux", sous, note.strip(), legende, colonnes=2)
    grille = corps.subgridspec(len(traces), 1, hspace=0.12)
    premier = None
    for i, f in enumerate(traces):
        ax = fig.add_subplot(grille[i], sharex=premier) if premier is not None else fig.add_subplot(grille[i])
        premier = premier or ax
        g = d[d["Flux"].eq(f)].sort_values("_r")
        serie = g.set_index("_r").reindex(range(n_sem))
        for r in g.loc[g["_j"] < 7, "_r"]:
            ax.axvspan(r - 0.5, r + 0.5, color=GRILLE, linewidth=0, zorder=0.5)
        xs = np.arange(n_sem, dtype=float)
        ax.fill_between(xs, serie["_b"].to_numpy(float), serie["_h"].to_numpy(float), color=BLEU, alpha=0.2, linewidth=0, zorder=2)
        ax.plot(xs, serie["_c"].to_numpy(float), color=BLEU, linewidth=1.8, solid_capstyle="round", marker="o", markersize=2.8, zorder=3)   # le point garde visible une semaine isolée
        m = g[g["_m"].notna()]
        if len(m):
            u = m["_u"].fillna(0).to_numpy(float)
            if (u > 0).any():
                ax.errorbar(m["_r"], m["_m"], yerr=u, fmt="none", ecolor=ENCRE_2, elinewidth=1.0, capsize=0, zorder=3.5)
            dans = m["Dans la marge"].astype(str)
            for etat, marq, coul, taille in (("oui", "o", ENCRE, 6.5), ("non", "D", ORANGE, 6.5)):
                k = m[dans.eq(etat)]
                ax.plot(k["_r"], k["_m"], linestyle="none", marker=marq, markersize=taille, markerfacecolor=coul, markeredgecolor=SURFACE, markeredgewidth=0.9, zorder=4)
            k = m[~dans.isin(["oui", "non"])]                    # pesée sans estimation en face : ni dans la marge ni dehors
            ax.plot(k["_r"], k["_m"], linestyle="none", marker="o", markersize=6, markerfacecolor=SURFACE, markeredgecolor=ENCRE_2, markeredgewidth=1.2, zorder=4)
        compar = m[m["Dans la marge"].astype(str).isin(["oui", "non"])]
        n_oui = int(compar["Dans la marge"].astype(str).eq("oui").sum())
        bilan = ((f"{_pluriel(n_oui, 'pesée')} sur {_fr(len(compar))} dans la marge" if n_oui else f"aucune pesée sur {_fr(len(compar))} dans la marge")
                 if len(compar) else "aucune semaine comparable (pas de pesée)")
        haut = np.nanmax([np.nanmax(serie["_h"].to_numpy(float)) if serie["_h"].notna().any() else 0.0,
                          np.nanmax(serie["_c"].to_numpy(float)) if serie["_c"].notna().any() else 0.0,
                          float((m["_m"] + m["_u"].fillna(0)).max()) if len(m) else 0.0])
        ax.set_ylim(0, haut * 1.15 if haut > 0 else 1.0)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
        ax.yaxis.set_major_formatter(_fmt(1 if haut < 10 else 0))
        _axe(ax, "y", ylabel="kg par semaine", titre=f"{f} : {bilan}")
        if i < len(traces) - 1:
            ax.tick_params(labelbottom=False)
        else:
            ax.set_xlabel("Semaine (date du lundi)", fontsize=T_AXE, color=ENCRE_2, labelpad=5)
    _graduer_semaines(premier, n_sem, libelle)
    return ("Pour chaque flux de déchets : la masse estimée chaque semaine à partir des consommations (trait et bande bleus) et la masse pesée "
            "sur le terrain (points). Une pesée hors de la bande (losange orange) signale un écart à expliquer avant d'utiliser le flux dans le modèle.", fig)


def _cumul(ctx):
    t = _table(ctx, "flux", "Estimé contre pesé", ["Semaine", "Flux", "Cumul estimé (kg)", "Cumul mesuré (kg)"])
    if t is None:
        return None
    d = t.assign(_s=pd.to_datetime(t["Semaine"], errors="coerce"), _e=_num(t, "Cumul estimé (kg)"), _m=_num(t, "Cumul mesuré (kg)")).dropna(subset=["_s", "_e", "_m"])
    if not len(d):
        return None
    flux = list(d.groupby("Flux")["_e"].max().sort_values(ascending=False).index[:4])
    n = len(flux)
    if not n:
        return None
    legende = [_trait(BLEU, "Cumul estimé", "o"), _trait(ENCRE, "Cumul pesé", "s")]
    sous = ("Cumul sur les seules semaines où une pesée et une estimation existent. Le cumul absorbe les décalages d'une semaine à l'autre "
            "(bacs vidés plus tard) : un écart qui persiste en cumul vient d'ailleurs. Échelle verticale propre à chaque flux.")
    fig, corps = _cadre(ctx, 3.0, "Cumul estimé contre cumul pesé, par flux", sous, "", legende, colonnes=2)
    grille = corps.subgridspec(1, n, wspace=0.08)
    for i, f in enumerate(flux):
        ax = fig.add_subplot(grille[i])
        g = d[d["Flux"].eq(f)].sort_values("_s")
        x = np.arange(len(g))
        ax.plot(x, g["_e"], color=BLEU, linewidth=1.8, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=0.9, zorder=3)
        ax.plot(x, g["_m"], color=ENCRE, linewidth=1.8, marker="s", markersize=5.5, markeredgecolor=SURFACE, markeredgewidth=0.9, zorder=3)
        fe, fm = float(g["_e"].iloc[-1]), float(g["_m"].iloc[-1])
        haut_e = fe >= fm                                        # étiquettes à droite du dernier point, écartées l'une de l'autre
        _etiquette(ax, _fr(fe, 1) + " kg", (x[-1], fe), decalage=(8, 2 if haut_e else -2), va="bottom" if haut_e else "top")
        _etiquette(ax, _fr(fm, 1) + " kg", (x[-1], fm), decalage=(8, -2 if haut_e else 2), va="top" if haut_e else "bottom")
        ecart = (fm - fe) / fe if fe else np.nan
        pas = max(int(math.ceil(len(g) / 6.0)), 1)
        ax.set_xticks(list(x[::pas]))
        ax.set_xticklabels([s.strftime("%d/%m") for s in g["_s"].iloc[::pas]])
        ax.set_xlim(-0.4, (len(g) - 1) * (1.22 if n > 1 else 1.1) + 0.5)
        ax.set_ylim(0, max(fe, fm, float(g["_e"].max()), float(g["_m"].max())) * 1.18)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.yaxis.set_major_formatter(_fmt())
        _axe(ax, "y", xlabel="Semaine pesée (date du lundi)", ylabel="kg cumulés" if i == 0 else None,
             titre=f"{f} : écart cumulé final {_pct(ecart, 0, signe=True)}")
    return ("Masse cumulée estimée et masse cumulée pesée, flux par flux, sur les semaines comparables. Lecture : deux courbes qui se suivent "
            "valident l'estimation ; deux courbes qui s'écartent régulièrement désignent une cause permanente (périmètre de la benne, poids manquants).", fig)


def _rebut_annuel(ctx):
    t = _table(ctx, "flux", "Rebut annuel", ["FRU", "Rebut annuel moyen"])
    if t is None:
        return None
    d = t.assign(_m=_num(t, "Rebut annuel moyen"))
    d["_b"] = _num(d, "Rebut annuel bas (5 %)") if "Rebut annuel bas (5 %)" in d else np.nan
    d["_h"] = _num(d, "Rebut annuel haut (95 %)") if "Rebut annuel haut (95 %)" in d else np.nan
    inconnus = [str(f) for f in d.loc[d["_m"].isna(), "FRU"]]
    d = d.dropna(subset=["_m"]).sort_values("_m", ascending=False)
    en_trop, d = len(d) - 20, d.head(20)
    if not len(d):
        return None
    n = len(d)
    sem = _num(d, "Semaines complètes") if "Semaines complètes" in d else pd.Series(dtype=float)
    sous = "Moyenne hebdomadaire des semaines complètes × 52. Trait : intervalle à 90 % obtenu en ré-échantillonnant les semaines."
    if len(sem) and sem.notna().any():
        sous += f" Base : {_fr(sem.min())} à {_fr(sem.max())} semaines complètes." if sem.min() != sem.max() else f" Base : {_fr(sem.max())} semaines complètes."
    note = "Ces valeurs (bas, moyen, haut) alimentent le modèle de ligne quand le rebut annuel n'est pas saisi dans le classeur de paramètres."
    if inconnus:
        note += " Rebut annuel inconnu (non tracé) : " + ", ".join(inconnus) + "."
    if en_trop > 0:
        note += f" {_pluriel(en_trop, 'autre type', 'autres types')} dans la table."
    fig, corps = _cadre(ctx, 0.6 + 0.34 * n, "Rebut annuel estimé par type de FRU", sous, note)
    ax = fig.add_subplot(corps)
    y = np.arange(n)
    descf = _descriptions_fru(ctx)
    for yi, (_, r) in zip(y, d.iterrows()):
        if np.isfinite(r["_b"]) and np.isfinite(r["_h"]):
            ax.plot([r["_b"], r["_h"]], [yi, yi], color=BLEU, linewidth=2.2, solid_capstyle="round", zorder=2)
            texte = f"{_fr(r['_m'])}  ({_fr(r['_b'])} à {_fr(r['_h'])})"
        else:
            texte = f"{_fr(r['_m'])}  (intervalle inconnu)"
        ax.plot([r["_m"]], [yi], linestyle="none", marker="o", markersize=7.5, markerfacecolor=BLEU, markeredgecolor=SURFACE, markeredgewidth=1.0, zorder=3)
        _etiquette(ax, texte, (np.nanmax([r["_h"], r["_m"]]), yi), decalage=(8, 0))
    ax.set_yticks(y)
    ax.set_yticklabels([_lib(f, descf.get(str(f), ""), 36) for f in d["FRU"]])
    ax.invert_yaxis()
    ax.set_ylim(n - 0.4, -0.6)
    ax.set_xlim(0, float(np.nanmax(d[["_m", "_h"]].to_numpy(float))) * 1.38)
    ax.xaxis.set_major_formatter(_fmt())
    _axe(ax, "x", xlabel="FRU rebutées par an")
    return ("Le rebut annuel de chaque type de FRU, tiré du suivi hebdomadaire : point = estimation moyenne, trait = intervalle à 90 %. "
            "Un intervalle large dit que la période observée est trop courte ou le flux trop irrégulier pour dimensionner la ligne à l'unité près.", fig)


def _par_type_de_dechet(ctx):
    t = _table(ctx, "flux", "Synthèse par benne", ["Benne", "Type de déchet", "Pièces"])
    if t is None:
        return None
    d = t.assign(_p=_num(t, "Pièces"))
    d["_kg"] = _num(d, "Kg (poids connus)") if "Kg (poids connus)" in d else np.nan
    d["_ref"] = _num(d, "Références") if "Références" in d else np.nan
    d["_con"] = _num(d, "Références au poids connu") if "Références au poids connu" in d else np.nan
    d["Benne"] = d["Benne"].fillna("(sans benne)").astype(str)
    d["Type de déchet"] = d["Type de déchet"].fillna("(non classé)").astype(str)
    d = d[d["_p"] > 0].sort_values(["Benne", "_p"], ascending=[True, False]).head(24)
    if not len(d):
        return None
    n = len(d)
    sous = "À gauche : pièces consommées sur la période. À droite : leur masse, calculée avec les seules références dont le poids unitaire est connu."
    note = "« Poids inconnu » : aucune référence de ce type n'a de poids unitaire ; la masse n'est pas comptée à zéro, elle manque. Une masse partielle est signalée."
    fig, corps = _cadre(ctx, 0.6 + 0.3 * n, "Pièces consommées et masse par benne et type de déchet", sous, note)
    grille = corps.subgridspec(1, 2, wspace=0.06)
    ax1 = fig.add_subplot(grille[0])
    ax2 = fig.add_subplot(grille[1], sharey=ax1)
    y = np.arange(n)
    ax1.barh(y, d["_p"].to_numpy(float), height=0.6, color=BLEU, edgecolor="none", zorder=2)
    for yi, v in zip(y, d["_p"]):
        _etiquette(ax1, _fr(v), (v, yi))
    kg_max = float(np.nanmax(d["_kg"].to_numpy(float))) if d["_kg"].notna().any() else 1.0
    for yi, (_, r) in zip(y, d.iterrows()):
        aucun = (np.isfinite(r["_con"]) and r["_con"] == 0) or not np.isfinite(r["_kg"])
        if aucun:
            _etiquette(ax2, "poids inconnu", (0, yi), couleur=ENCRE_3, style="italic")
            continue
        ax2.barh([yi], [r["_kg"]], height=0.6, color=BLEU, edgecolor="none", zorder=2)
        partiel = np.isfinite(r["_ref"]) and np.isfinite(r["_con"]) and r["_con"] < r["_ref"]
        _etiquette(ax2, _fr(r["_kg"], 1) + " kg" + (f"  (partiel : {_fr(r['_con'])} réf. sur {_fr(r['_ref'])} au poids connu)" if partiel else ""), (r["_kg"], yi))
    ax1.set_yticks(y)
    ax1.set_yticklabels([f"{b} · {_court(ty, 26)}" for b, ty in zip(d["Benne"], d["Type de déchet"])])
    ax1.invert_yaxis()
    ax1.set_ylim(n - 0.4, -0.6)
    ax1.set_xlim(0, float(d["_p"].max()) * 1.25)
    ax2.set_xlim(0, kg_max * 1.35)
    ax1.xaxis.set_major_formatter(_fmt())
    ax2.xaxis.set_major_formatter(_fmt())
    ax1.xaxis.set_major_locator(MaxNLocator(nbins=4))
    ax2.xaxis.set_major_locator(MaxNLocator(nbins=4))
    _axe(ax1, "x", xlabel="Pièces consommées")
    _axe(ax2, "x", xlabel="Masse des pièces au poids connu (kg)")
    ax2.tick_params(labelleft=False)
    return ("Ce que les ateliers consomment, rangé par benne puis par type de déchet : nombre de pièces et masse correspondante. "
            "Lecture : la masse n'est fiable que pour les types dont les poids unitaires sont connus.", fig)


# =========================================================================== 3. fiabilité
def _rangees_par_reference(d: pd.DataFrame, ctx, maxi: int = 12):
    """Rangées d'un tracé « référence × origine » : les origines d'une même référence sont serrées autour de sa ligne."""
    refs = list(pd.unique(d["Référence"]))[:maxi]
    desc = _descriptions(ctx)
    ordre = list(ORIGINES) + sorted(set(d["Origine posée"].astype(str)) - set(ORIGINES))
    lignes, centres, etiquettes, pas = [], [], [], 0.27
    for i, r in enumerate(refs):
        g = d[d["Référence"].eq(r)]
        presentes = [o for o in ordre if (g["Origine posée"].astype(str) == o).any()]
        for j, o in enumerate(presentes):
            lignes.append((i + (j - (len(presentes) - 1) / 2.0) * pas, g[g["Origine posée"].astype(str).eq(o)].iloc[0], o))
        centres.append(i)
        etiquettes.append(_lib(r, desc.get(str(r), ""), 26))
    return lignes, centres, etiquettes, len(pd.unique(d["Référence"])) - len(refs)


def _habiller_references(ax, centres, etiquettes):
    for i in centres[::2]:
        ax.axhspan(i - 0.5, i + 0.5, color="#f3f2ee", linewidth=0, zorder=0.4)
    ax.set_yticks(centres)
    ax.set_yticklabels(etiquettes)
    ax.set_ylim(len(centres) - 0.5, -0.5)


def _legende_origines(d: pd.DataFrame, suffixe: str = ""):
    presentes = [o for o in ORIGINES if (d["Origine posée"].astype(str) == o).any()]
    autres = sorted(set(d["Origine posée"].astype(str)) - set(ORIGINES))
    return [_trait(ORIGINES[o][0], f"Pièce posée {o.lower()}{suffixe}", ORIGINES[o][1]) for o in presentes] + \
           [_trait(GRIS_FONCE, f"Origine « {o} »", "D") for o in autres]


def _taux_precoce(ctx):
    t = _table(ctx, "fiabilite", "Fiabilité par référence", ["Référence", "Origine posée", "Taux ELF moyen", "IC90 bas", "IC90 haut"])
    if t is None:
        return None
    d = t.assign(_t=_num(t, "Taux ELF moyen"), _b=_num(t, "IC90 bas"), _h=_num(t, "IC90 haut"))
    sans = int(d["_t"].isna().sum())
    d = d.dropna(subset=["_t"])
    if not len(d):
        return None
    lignes, centres, etiquettes, en_trop = _rangees_par_reference(d, ctx)
    note = ("Le fichier de fiabilité ne contient que des défaillances : c'est un taux de défaillance précoce, pas une durée de vie. "
            "Le taux n'existe que si le nombre de pièces posées sur la même période est fourni.")
    if sans:
        note += f" {_pluriel(sans, 'ligne')} sans dénominateur : taux inconnu, non tracé."
    if en_trop > 0:
        note += f" {_pluriel(en_trop, 'autre référence', 'autres références')} dans la table."
    sous = ("Défaillances précoces rapportées aux pièces posées sur la même période. Point : taux moyen ; trait : intervalle à 90 %. "
            "À droite : défaillances / pièces posées.")
    fig, corps = _cadre(ctx, 0.55 + 0.62 * len(centres), "Taux de défaillance précoce par référence et par origine de la pièce posée", sous, note,
                        _legende_origines(d), colonnes=3)
    ax = fig.add_subplot(corps)
    for y, r, o in lignes:
        coul, marq = ORIGINES.get(o, (GRIS_FONCE, "D"))
        if np.isfinite(r["_b"]) and np.isfinite(r["_h"]):
            ax.plot([r["_b"], r["_h"]], [y, y], color=coul, linewidth=2.0, solid_capstyle="round", zorder=2)
        ax.plot([r["_t"]], [y], linestyle="none", marker=marq, markersize=7.5, markerfacecolor=coul, markeredgecolor=SURFACE, markeredgewidth=1.0, zorder=3)
        if "Défaillances ELF" in d and "Pièces posées (même période)" in d:
            ax.text(1.015, y, f"{_fr(r['Défaillances ELF'])} / {_fr(r['Pièces posées (même période)'])}", transform=ax.get_yaxis_transform(),
                    ha="left", va="center", fontsize=T_NOTE, color=ENCRE_2)
    _habiller_references(ax, centres, etiquettes)
    ax.set_xlim(0, float(np.nanmax(d[["_t", "_h"]].to_numpy(float))) * 1.08)
    haut = ax.get_xlim()[1]
    ax.xaxis.set_major_formatter(_fmt(1 if haut < 0.2 else 0, pct=True))
    _axe(ax, "x", xlabel="Taux de défaillance précoce (défaillances pour 100 pièces posées)")
    return ("Pour chaque référence, le taux de défaillance précoce d'une pièce neuve, réparée ou récupérée, avec son intervalle à 90 %. "
            "Lecture : deux intervalles qui se recouvrent ne permettent pas de dire qu'une origine est moins fiable que l'autre.", fig)


def _kaplan_meier(ctx):
    t = _table(ctx, "fiabilite", "Courbes de Kaplan-Meier", ["Référence", "Origine posée", "t", "S(t)"])
    if t is None:
        return None
    d = t.assign(_t=_num(t, "t"), _s=_num(t, "S(t)")).dropna(subset=["_t", "_s"])
    if not len(d):
        return None
    refs = list(pd.unique(d["Référence"]))[:6]
    d = d[d["Référence"].isin(refs)]
    n = len(refs)
    ncol = 2 if n == 4 else min(n, 3)
    nlig = int(math.ceil(n / float(ncol)))
    desc = _descriptions(ctx)
    sous = ("Parmi les pièces qui ont défailli : part de celles qui tenaient encore après t jours. Toutes les courbes finissent à 0 % parce que "
            "le fichier ne contient que des défaillances, aucune pièce encore en service.")
    note = "Ces courbes comparent la vitesse des défaillances précoces entre origines ; elles ne donnent ni une durée de vie ni une probabilité de panne."
    fig, corps = _cadre(ctx, 2.35 * nlig + 0.2, "Délai avant défaillance des pièces défaillantes, par origine (Kaplan-Meier)", sous, note,
                        _legende_origines(d), colonnes=3)
    grille = corps.subgridspec(nlig, ncol, wspace=0.05, hspace=0.1)
    tmax = float(d["_t"].max())
    premier = None
    for i, r in enumerate(refs):
        ax = fig.add_subplot(grille[i // ncol, i % ncol], sharex=premier, sharey=premier) if premier is not None else fig.add_subplot(grille[0, 0])
        premier = premier or ax
        g = d[d["Référence"].eq(r)]
        effectifs = []
        for o in list(ORIGINES) + sorted(set(g["Origine posée"].astype(str)) - set(ORIGINES)):
            k = g[g["Origine posée"].astype(str).eq(o)].sort_values("_t")
            if not len(k):
                continue
            coul, marq = ORIGINES.get(o, (GRIS_FONCE, "D"))
            x, s = np.r_[0.0, k["_t"].to_numpy(float)], np.r_[1.0, k["_s"].to_numpy(float)]
            ax.step(x, s, where="post", color=coul, linewidth=1.8, zorder=3)
            pas = max(len(x) // 5, 1)
            ax.plot(x[1::pas], s[1::pas], linestyle="none", marker=marq, markersize=5.5, markerfacecolor=coul, markeredgecolor=SURFACE, markeredgewidth=0.8, zorder=4)
            nb = _num(k, "défaillances").sum() if "défaillances" in k else len(k)
            effectifs.append(f"{o.lower()} : {_fr(nb)}")
        ax.text(0.98, 0.96, "défaillances\n" + "\n".join(effectifs), transform=ax.transAxes, ha="right", va="top", fontsize=T_NOTE, color=ENCRE_2, linespacing=1.3)
        derniere_ligne, premiere_colonne = i // ncol == nlig - 1 or i + ncol >= n, i % ncol == 0
        _axe(ax, "y", xlabel="Jours depuis la pose" if derniere_ligne else None, ylabel="Part encore en service" if premiere_colonne else None,
             titre=_lib(r, desc.get(str(r), ""), 20 if ncol == 3 else 34))
        if not derniere_ligne:
            ax.tick_params(labelbottom=False)
        if not premiere_colonne:
            ax.tick_params(labelleft=False)
    premier.set_xlim(0, tmax * 1.04)
    premier.set_ylim(0, 1.04)
    premier.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    premier.yaxis.set_major_formatter(_fmt(pct=True))
    premier.xaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
    premier.xaxis.set_major_formatter(_fmt())
    return ("Courbes de Kaplan-Meier des références qui cumulent le plus de défaillances précoces, une courbe par origine de la pièce posée. "
            "Lecture : une courbe qui descend plus tôt signale des défaillances plus rapides après la pose.", fig)


def _forme_weibull(ctx):
    t = _table(ctx, "fiabilite", "Fiabilité par référence", ["Référence", "Origine posée", "Forme Weibull k"])
    if t is None:
        return None
    d = t.assign(_k=_num(t, "Forme Weibull k"))
    intervalle = "k bas (5 %)" in d and "k haut (95 %)" in d
    d["_b"] = _num(d, "k bas (5 %)") if intervalle else np.nan
    d["_h"] = _num(d, "k haut (95 %)") if intervalle else np.nan
    sans = int(d["_k"].isna().sum())
    d = d.dropna(subset=["_k"])
    if not len(d):
        return None
    lignes, centres, etiquettes, en_trop = _rangees_par_reference(d, ctx)
    sous = ("k < 1 : défaillances surtout au début (mortalité infantile). k proche de 1 : risque constant. k > 1 : le risque croît avec l'âge (usure). "
            + ("Trait : intervalle à 90 % sur k." if intervalle else "À droite : nombre de défaillances datées qui fondent l'estimation."))
    note = ("Forme estimée sur des défaillances précoces seulement (fenêtre d'observation tronquée) : elle décrit le début de vie, "
            "pas la durée de vie. ")
    if not intervalle:
        note += "L'intervalle d'incertitude sur k n'est pas calculé : avec peu de défaillances, k est imprécis. "
    if sans:
        note += f"{_pluriel(sans, 'ligne')} avec moins de 3 défaillances : k inconnu, non tracé. "
    if en_trop > 0:
        note += f"{_pluriel(en_trop, 'autre référence', 'autres références')} dans la table."
    legende = _legende_origines(d) + [_pave("#e9e8e2", "Zone 0,9 à 1,1 : risque constant")]
    fig, corps = _cadre(ctx, 0.75 + 0.62 * len(centres), "Forme de Weibull k des défaillances précoces, par référence et origine", sous, note.strip(),
                        legende, colonnes=4)
    ax = fig.add_subplot(corps)
    haut = max(float(np.nanmax(d[["_k", "_h"]].to_numpy(float))) * 1.12, 1.6)
    ax.axvspan(0.9, 1.1, color="#e9e8e2", linewidth=0, zorder=0.6)        # seuils de lecture de erc.fiabilite.lecture_forme
    ax.axvline(1.0, color=ENCRE_2, linewidth=0.9, zorder=1.5)
    for y, r, o in lignes:
        coul, marq = ORIGINES.get(o, (GRIS_FONCE, "D"))
        if np.isfinite(r["_b"]) and np.isfinite(r["_h"]):
            ax.plot([r["_b"], r["_h"]], [y, y], color=coul, linewidth=2.0, solid_capstyle="round", zorder=2)
        ax.plot([r["_k"]], [y], linestyle="none", marker=marq, markersize=7.5, markerfacecolor=coul, markeredgecolor=SURFACE, markeredgewidth=1.0, zorder=3)
        if "elf_days renseigné" in d:
            ax.text(1.015, y, f"n = {_fr(r['elf_days renseigné'])}", transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=T_NOTE, color=ENCRE_2)
    _habiller_references(ax, centres, etiquettes)
    ax.set_xlim(0, haut)
    for x, texte, ha in ((0.86, "mortalité infantile", "right"), (1.14, "usure", "left")):
        ax.text(x, 1.01, texte, transform=ax.get_xaxis_transform(), ha=ha, va="bottom", fontsize=T_NOTE, color=ENCRE_2)
    ax.text(1.0, 1.01, "k = 1", transform=ax.get_xaxis_transform(), ha="center", va="bottom", fontsize=T_NOTE, color=ENCRE, fontweight="bold")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=7, steps=[1, 2, 5, 10]))
    ax.xaxis.set_major_formatter(_fmt(1))
    _axe(ax, "x", xlabel="Forme de Weibull k")
    return ("La forme k dit comment le risque de défaillance évolue avec l'âge de la pièce, ce qui conditionne l'intérêt d'un réemploi : "
            "sous 1, une pièce qui a déjà tourné est plus sûre qu'une neuve ; au-dessus de 1, l'âge du donneur compte.", fig)


def _age_du_donneur(ctx):
    t = _table(ctx, "fiabilite", "Vie résiduelle (grille illustrative)", ["Forme k", "Âge du donneur (j)", "P(tenir la garantie)"])
    if t is None:
        return None
    d = t.assign(_k=_num(t, "Forme k"), _a=_num(t, "Âge du donneur (j)"), _p=_num(t, "P(tenir la garantie)")).dropna(subset=["_k", "_a", "_p"])
    ks = sorted(d["_k"].unique())[:3]
    if not ks or d["_a"].nunique() < 2:
        return None
    garantie = _objet(ctx, "fiabilite", "Notes").get("garantie_jours")
    teintes = [BLEU_CLAIR, BLEU, BLEU_FONCE][3 - len(ks):] if len(ks) < 3 else [BLEU_CLAIR, BLEU, BLEU_FONCE]
    marques = ["o", "s", "^"]
    lecture = {k: str(v) for k, v in zip(d["_k"], d["Lecture"])} if "Lecture" in d else {}
    legende = [_trait(c, f"k = {_fr(k, 1)}" + (f" : {lecture[k]}" if k in lecture else ""), m) for k, c, m in zip(ks, teintes, marques)]
    sous = ("Calcul théorique (loi de Weibull, échelle arbitraire de 1 000 jours)" + (f", garantie de {_fr(garantie)} jours" if garantie else "")
            + ". Ce ne sont pas des mesures de l'atelier : seule la tendance se lit.")
    fig, corps = _cadre(ctx, 3.1, "Illustration : effet de l'âge du donneur sur la tenue de la garantie, selon la forme k", sous, "", legende, colonnes=3)
    ax = fig.add_subplot(corps)
    for k, c, m in zip(ks, teintes, marques):
        g = d[d["_k"].eq(k)].sort_values("_a")
        ax.plot(g["_a"], g["_p"], color=c, linewidth=1.8, marker=m, markersize=6.5, markeredgecolor=SURFACE, markeredgewidth=0.9, zorder=3)
        _etiquette(ax, f"k = {_fr(k, 1)}", (float(g["_a"].iloc[-1]), float(g["_p"].iloc[-1])), decalage=(7, 0))
    ax.set_ylim(0, 1.0)
    ax.set_xlim(-0.03 * float(d["_a"].max()), float(d["_a"].max()) * 1.1)
    ax.yaxis.set_major_formatter(_fmt(pct=True))
    ax.xaxis.set_major_formatter(_fmt())
    _axe(ax, "y", xlabel="Âge de la pièce au moment du réemploi (jours)", ylabel="Probabilité de tenir la garantie")
    return ("Illustration théorique, sans données de l'atelier : selon la forme k, une pièce déjà âgée tient mieux (k < 1), aussi bien (k = 1) "
            "ou moins bien (k > 1) la période de garantie qu'une pièce neuve. Sert à lire la figure des formes k.", fig)


# =========================================================================== 4. modèle de Rex
def _q_par_piece(ctx):
    t = _table(ctx, "rex", "A posteriori", ["Type de FRU", "Pièce", "q moyen", "q bas (5 %)", "q haut (95 %)"])
    if t is None:
        return None
    d = t.assign(_q=_num(t, "q moyen"), _b=_num(t, "q bas (5 %)"), _h=_num(t, "q haut (95 %)"))
    d["_q0"] = _num(d, "q0") if "q0" in d else np.nan
    d["_n"] = _num(d, "Pièces testées").fillna(0) if "Pièces testées" in d else 0.0
    d = d.dropna(subset=["_q"])
    if not len(d):
        return None
    desc, descf = _descriptions(ctx), _descriptions_fru(ctx)
    rangees, graduations, y, gardes, coupes = [], [], 0.0, 0, 0
    for f in pd.unique(d["Type de FRU"]):
        g = d[d["Type de FRU"].eq(f)]
        if gardes + len(g) > 44 and gardes:
            coupes += len(g)
            continue
        graduations.append((y, _lib(f, descf.get(str(f), ""), 30), True))
        y += 1.0
        for _, r in g.iterrows():
            rangees.append((y, r))
            graduations.append((y, _lib(r["Pièce"], desc.get(str(r["Pièce"]), ""), 26), False))
            y += 1.0
        y += 0.5
        gardes += len(g)
    legende = [_trait(BLEU, "Après audit : moyenne et intervalle à 90 %", "o"),
               _trait(BLEU_CLAIR, "Sans audit : a priori seul et son intervalle à 90 %", "D", plein=False, taille=6),
               _trait(ENCRE_2, "A priori q0 tiré de la consommation", "D", epaisseur=0, plein=False, taille=6)]
    sous = ("q = probabilité qu'une pièce extraite d'un FRU rebuté soit réutilisable. L'audit de démontage déplace l'a priori et resserre l'intervalle ; "
            "sans pièce testée, la valeur n'est qu'une hypothèse tirée de la consommation.")
    note = ("L'a priori q0 dépend du nombre de pièces par FRU, inconnu avant un audit de démontage (le maximum observé sur un PO n'est qu'un minimum). "
            "À droite : pièces testées lors de l'audit.")
    if coupes:
        note += f" {_pluriel(coupes, 'couple')} (FRU, pièce) non tracé{'s' if coupes > 1 else ''} : voir la table."
    fig, corps = _cadre(ctx, 0.5 + 0.235 * y, "Probabilité de réemploi q par type de FRU et par pièce", sous, note, legende, colonnes=2)
    ax = fig.add_subplot(corps)
    for yi, r in rangees:
        audit = r["_n"] > 0
        coul = BLEU if audit else BLEU_CLAIR
        if np.isfinite(r["_b"]) and np.isfinite(r["_h"]):
            ax.plot([r["_b"], r["_h"]], [yi, yi], color=coul, linewidth=2.0, solid_capstyle="round", zorder=2)
        if audit:
            ax.plot([r["_q"]], [yi], linestyle="none", marker="o", markersize=7.5, markerfacecolor=BLEU, markeredgecolor=SURFACE, markeredgewidth=1.0, zorder=4)
        if np.isfinite(r["_q0"]):
            ax.plot([r["_q0"]], [yi], linestyle="none", marker="D", markersize=5.5, markerfacecolor=SURFACE, markeredgecolor=ENCRE_2 if audit else BLEU, markeredgewidth=1.3, zorder=3)
        elif not audit:
            ax.plot([r["_q"]], [yi], linestyle="none", marker="o", markersize=6, markerfacecolor=SURFACE, markeredgecolor=BLEU, markeredgewidth=1.3, zorder=3)
        ax.text(1.015, yi, _pluriel(r["_n"], "testée") if audit else "aucun test", transform=ax.get_yaxis_transform(), ha="left", va="center",
                fontsize=T_NOTE, color=ENCRE_2 if audit else ENCRE_3)
    ax.set_yticks([g[0] for g in graduations])
    ax.set_yticklabels([g[1] for g in graduations])
    ax.set_ylim(y - 1.0, -0.6)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(_fmt(pct=True))
    _axe(ax, "x", xlabel="Probabilité qu'une pièce extraite soit réutilisable (q)")
    for etiq, g in zip(ax.get_yticklabels(), graduations):
        if g[2]:
            etiq.set_fontweight("bold")
            etiq.set_color(ENCRE)
    return ("Pour chaque couple (type de FRU, pièce) : la probabilité q qu'une pièce extraite soit réutilisable, avec son intervalle à 90 %, "
            "l'a priori tiré de la consommation (losange) et le nombre de pièces testées. C'est la valeur transmise au modèle de ligne.", fig)


def _regret(ctx):
    t = _table(ctx, "rex", "Banc d'essai (courbes de regret)")
    if t is None:
        return None
    politiques = [c for c in t.columns if c != "Pièce n°" and pd.api.types.is_numeric_dtype(t[c]) and t[c].notna().any()]
    if not politiques or len(t) < 2:
        return None
    x = (_num(t, "Pièce n°") + 1).to_numpy(float) if "Pièce n°" in t else np.arange(1, len(t) + 1, dtype=float)
    if not np.isfinite(x).all():
        x = np.arange(1, len(t) + 1, dtype=float)
    couleurs = {"Thompson": BLEU, "Glouton": ORANGE, "A priori seul": GRIS_FONCE}
    libres = [VERT_EAU, JAUNE, MAGENTA]                           # règles de décision au nom inconnu : teintes suivantes
    groupes = []                                                  # courbes confondues : un seul trait, une seule étiquette
    for p in politiques:
        v = t[p].to_numpy(float)
        for g in groupes:
            if np.allclose(g[1], v, rtol=1e-9, atol=1e-9, equal_nan=True):
                g[0].append(p)
                break
        else:
            groupes.append(([p], v))
    param = _objet(ctx, "rex", "Notes").get("banc_essai") or {}
    banc = _table(ctx, "rex", "Banc d'essai des politiques")
    if not param and banc is not None:
        param = dict(banc.attrs)
    sous = "Simulation, pas des données de l'atelier"
    if param:
        morceaux = [(f"part réelle de pièces bonnes {_fr(param.get('q vrai'), 2)}", "q vrai"), (f"a priori {_fr(param.get('q0'), 2)}", "q0"),
                    (f"réemploi choisi au-dessus de {_fr(param.get('Seuil q* (réemploi si q > q*)'), 2)}", "Seuil q* (réemploi si q > q*)")]
        sous += " : " + ", ".join(m for m, cle in morceaux if param.get(cle) is not None)
    sous += ". Regret = gain perdu par rapport à une règle qui connaîtrait la vraie part de pièces bonnes."
    legende, traces = [], []
    for noms, v in groupes:
        coul = next((couleurs[n] for n in noms if n in couleurs and n != "A priori seul"), None) or couleurs.get(noms[0]) or (libres.pop(0) if libres else GRIS)
        nom = " et ".join(noms) + (" (courbes confondues)" if len(noms) > 1 else "")
        legende.append(_trait(coul, nom))
        traces.append((nom, v, coul))
    fig, corps = _cadre(ctx, 3.3, "Banc d'essai synthétique : regret cumulé des règles de décision", sous,
                        "Le banc d'essai démontre la méthode (tester de temps en temps une pièce jugée mauvaise pour corriger un a priori trop pessimiste). Il ne décrit pas l'atelier.",
                        legende, colonnes=3)
    ax = fig.add_subplot(corps)
    for nom, v, coul in traces:
        ax.plot(x, v, color=coul, linewidth=1.9, solid_capstyle="round", zorder=3)
        fin = float(v[-1])
        if np.isfinite(fin):
            _etiquette(ax, f"{_fr(fin)} €", (x[-1], fin), decalage=(6, 0))
    ax.set_xlim(0, float(x[-1]) * 1.1)
    ax.set_ylim(0, float(np.nanmax([np.nanmax(v) for _, v, _c in traces])) * 1.08)
    ax.xaxis.set_major_formatter(_fmt())
    ax.yaxis.set_major_formatter(_fmt())
    _axe(ax, "y", xlabel="Pièces traitées depuis le début", ylabel="Regret cumulé moyen (€)")
    return ("Banc d'essai SYNTHÉTIQUE du choix réemploi ou recyclage : regret cumulé de trois règles de décision quand l'a priori est trop pessimiste. "
            "Lecture : une courbe qui s'aplatit a appris ; une droite qui monte répète la même erreur à chaque pièce.", fig)


def _metriques(ctx):
    t = _table(ctx, "rex", "Métriques", ["Modèle"])
    if t is None:
        return None
    # Repères : 0,25 = Brier d'un pile ou face ; ln 2 = log-perte d'un pile ou face ; 0,90 = couverture visée d'un intervalle à 90 %.
    cadres = [(c, titre, repere, texte, pct) for c, titre, repere, texte, pct in (
        ("Brier", "Brier (0 = parfait)", 0.25, "pile ou face", False),
        ("Log-perte", "Log-perte (plus bas = mieux)", math.log(2), "pile ou face", False),
        ("Écart absolu moyen", "Écart absolu moyen (plus bas = mieux)", None, "", True),
        ("Couverture IC90", "Couverture de l'intervalle à 90 %", 0.90, "cible", True)) if c in t and _num(t, c).notna().any()]
    if not cadres:
        return None
    ordre = ["Bêta-binomial"] + [m for m in t["Modèle"].astype(str) if m != "Bêta-binomial"]
    d = t.assign(_m=t["Modèle"].astype(str)).set_index("_m").reindex([m for m in ordre if m in set(t["Modèle"].astype(str))])
    n = len(d)
    lots = _num(t, "Lots").max() if "Lots" in t else np.nan
    pieces = _num(t, "Pièces").max() if "Pièces" in t else np.nan
    sous = "Chaque lot de l'audit est prédit avant d'être appris, puis sert à mettre le modèle à jour"
    if np.isfinite(lots) and np.isfinite(pieces):
        sous += f" ({_fr(lots)} lots, {_fr(pieces)} pièces testées)"
    sous += ". En bleu : le modèle retenu ; en gris : les deux références simples qu'il doit battre."
    legende = [_pave(BLEU, "Modèle retenu (Bêta-binomial)"), _pave(GRIS_FONCE, "Références à battre")]
    fig, corps = _cadre(ctx, 0.85 + 0.36 * n, "Qualité de prédiction du modèle de Rex et de ses références", sous,
                        "Écart absolu moyen : écart entre taux prédit et taux observé d'un lot. Couverture : part des lots tombés dans l'intervalle annoncé (elle n'existe que pour le modèle qui donne un intervalle).",
                        legende, colonnes=2)
    grille = corps.subgridspec(1, len(cadres), wspace=0.06)
    y = np.arange(n)
    for i, (c, titre, repere, texte, pct) in enumerate(cadres):
        ax = fig.add_subplot(grille[i])
        v = _num(d, c).to_numpy(float)
        haut = max(float(np.nanmax(v)), repere or 0.0) * 1.42
        if c == "Couverture IC90":
            haut = 1.3
        for yi, vi, m in zip(y, v, d.index):
            if not np.isfinite(vi):
                _etiquette(ax, "sans objet", (0, yi), couleur=ENCRE_3, style="italic")
                continue
            ax.barh([yi], [vi], height=0.58, color=BLEU if m == "Bêta-binomial" else GRIS_FONCE, edgecolor="none", zorder=2)
            _etiquette(ax, _pct(vi, 1) if pct else _fr(vi, 3), (vi, yi), fond=True)
        if repere is not None:
            ax.axvline(repere, color=ENCRE_2, linewidth=0.9, zorder=2.5)
            ax.text(repere, 1.0, f"{texte} : {_pct(repere) if pct else _fr(repere, 2)}", transform=ax.get_xaxis_transform(), ha="center", va="bottom",
                    fontsize=T_NOTE, color=ENCRE_2)
        ax.set_yticks(y)
        ax.set_yticklabels(list(d.index))
        ax.set_ylim(n - 0.45, -0.75)
        ax.set_xlim(0, haut)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=3))
        if c == "Couverture IC90":
            ax.set_xticks([0, 0.5, 1.0])
        ax.xaxis.set_major_formatter(_fmt(0 if pct else 2, pct=pct))
        _axe(ax, "x")
        ax.set_title("\n".join(textwrap.wrap(titre, 24)), loc="left", fontsize=T_GRAD, color=ENCRE, fontweight="bold", pad=16)
        if i:
            ax.tick_params(labelleft=False)
    return ("Quatre mesures de la qualité de prédiction, pour le modèle retenu et ses deux références. Lecture : sur les trois premières, la barre la "
            "plus courte gagne ; la couverture doit être proche de 90 %. Si une référence fait mieux, l'a priori n'apporte rien sur ces données.", fig)


def _reglage_n0(ctx):
    t = _table(ctx, "rex", "Réglage de N0", ["N0", "Log-perte"])
    if t is None:
        return None
    d = t.assign(_n=_num(t, "N0"), _l=_num(t, "Log-perte")).dropna(subset=["_n", "_l"]).sort_values("_n")
    if len(d) < 2:
        return None
    d["_c"] = _num(d, "Couverture IC90") if "Couverture IC90" in d else np.nan
    retenu = _objet(ctx, "rex", "Notes").get("N0")
    x = np.arange(len(d))
    mini = int(np.argmin(d["_l"].to_numpy(float)))
    deux = d["_c"].notna().any()
    sous = "N0 = poids de l'a priori, en pièces équivalentes : plus il est grand, plus il faut de pièces testées pour s'en écarter."
    n_min = d["_n"].iloc[mini]
    note = f"L'axe de la log-perte ne part pas de zéro : les écarts sont faibles. Sur ces données, elle est la plus basse pour N0\u00a0=\u00a0{_fr(n_min)}."
    if retenu is not None:
        note += f" Le modèle utilise N0\u00a0=\u00a0{_fr(retenu)} (valeur fixée dans le code)" + ("." if float(retenu) == float(n_min) else " : à revoir si l'écart se confirme sur l'audit réel.")
    fig, corps = _cadre(ctx, 2.7, "Réglage de la force de l'a priori N0 du modèle de Rex", sous, note)
    grille = corps.subgridspec(1, 2 if deux else 1, wspace=0.08)
    ax = fig.add_subplot(grille[0])
    ax.plot(x, d["_l"], color=BLEU, linewidth=1.8, marker="o", markersize=6.5, markeredgecolor=SURFACE, markeredgewidth=0.9, zorder=3)
    _etiquette(ax, f"minimum : {_fr(d['_l'].iloc[mini], 3)}", (x[mini], float(d["_l"].iloc[mini])), decalage=(0, -8), ha="center" if 0 < mini < len(d) - 1 else ("left" if mini == 0 else "right"), va="top")
    etendue = float(d["_l"].max() - d["_l"].min()) or 0.01
    ax.set_ylim(float(d["_l"].min()) - etendue * 0.35, float(d["_l"].max()) + etendue * 0.2)
    ax.yaxis.set_major_formatter(_fmt(3))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    axes = [ax]
    _axe(ax, "y", xlabel="N0 (pièces équivalentes)", titre="Log-perte (plus bas = mieux)")
    if deux:
        ax2 = fig.add_subplot(grille[1])
        ax2.plot(x, d["_c"], color=BLEU, linewidth=1.8, marker="o", markersize=6.5, markeredgecolor=SURFACE, markeredgewidth=0.9, zorder=3)
        ax2.axhline(0.90, color=ENCRE_2, linewidth=0.9, zorder=2)
        _etiquette(ax2, "cible : 90 %", (x[0], 0.90), decalage=(0, -4), ha="left", va="top", taille=T_NOTE)
        ax2.set_ylim(min(float(d["_c"].min()), 0.9) - 0.08, 1.02)
        ax2.yaxis.set_major_formatter(_fmt(pct=True))
        ax2.yaxis.set_major_locator(MaxNLocator(nbins=5))
        _axe(ax2, "y", xlabel="N0 (pièces équivalentes)", titre="Couverture de l'intervalle à 90 %")
        axes.append(ax2)
    for a in axes:
        a.set_xticks(list(x))
        a.set_xticklabels([_fr(v) for v in d["_n"]])
        a.set_xlim(-0.4, len(d) - 0.6)
        if retenu is not None and float(retenu) in set(d["_n"].astype(float)):
            xr = float(x[list(d["_n"].astype(float)).index(float(retenu))])
            a.axvline(xr, color=ENCRE_2, linewidth=0.9, zorder=1.5)
            a.text(xr, 1.0, "N0 utilisé", transform=a.get_xaxis_transform(), ha="center", va="bottom", fontsize=T_NOTE, color=ENCRE_2)
            a.title.set_position((0, 1.0))
            a.set_title(a.get_title(loc="left"), loc="left", fontsize=T_AXE + 0.3, color=ENCRE, fontweight="bold", pad=16)
    return ("Effet de la force de l'a priori N0 sur la qualité de prédiction. Lecture : l'axe vertical de la log-perte ne part pas de zéro, "
            "les écarts entre valeurs de N0 sont faibles ; la couverture doit rester proche de 90 %.", fig)


# =========================================================================== 5. ligne de démontage et de tri
def _nom_carcasse() -> str:
    try:
        from .parametres import CARCASSE
        return CARCASSE
    except Exception:
        return "CARCASSE"


def _options_par_piece(ctx):
    t = _table(ctx, "ligne", "Options par pièce", ["Type de FRU", "Pièce", "1 Réemploi (€/FRU)", "2 Recyclage (€/FRU)"])
    if t is None:
        return None
    d = t.dropna(subset=["Type de FRU", "Pièce"])
    if not len(d):
        return None
    d = d.assign(_re=_num(d, "1 Réemploi (€/FRU)"), _rc=_num(d, "2 Recyclage (€/FRU)"))
    for c, k in (("Manque réemploi", "_mre"), ("Manque recyclage", "_mrc")):
        d[k] = d[c].fillna("").astype(str) if c in d else ""
    frus = list(pd.unique(d["Type de FRU"]))
    en_trop, frus = frus[6:], frus[:6]
    carcasse = _nom_carcasse()
    desc, descf = _descriptions(ctx), _descriptions_fru(ctx)
    modele = _objet(ctx, "ligne", "Modèle").get("frus") or {}
    tailles = [int(d["Type de FRU"].eq(f).sum()) for f in frus]
    legende = [_pave(BLEU, "Réemploi : démontage soigné, test, pièce réutilisée"), _pave(ORANGE, "Recyclage trié : pièce vendue au kilo"),
               _trait(ENCRE_3, "Inconnu : une donnée manque, la valeur n'est pas calculée", "s", epaisseur=0, plein=False, taille=5)]
    sous = ("Valeur nette par FRU de chaque option, par rapport à la pièce laissée dans le FRU (zéro). Hors ouverture du FRU, payée une seule fois "
            "et indiquée dans le titre de chaque cadre. Le chiffre écrit est celui de la meilleure option.")
    note = "Les valeurs de réemploi reposent sur le MMICV (coût standard) et sur la probabilité q du modèle de Rex : ce sont des estimations, pas des recettes."
    if en_trop:
        note += f" {_pluriel(len(en_trop), 'autre type', 'autres types')} de FRU dans la table."
    fig, corps = _cadre(ctx, sum(0.33 * n + 0.66 for n in tailles) + 0.25, "Valeur du réemploi et du recyclage trié, pièce par pièce", sous, note, legende, colonnes=1)
    grille = corps.subgridspec(len(frus), 1, height_ratios=[0.33 * n + 0.66 for n in tailles], hspace=0.06)
    finis = d.loc[d["Type de FRU"].isin(frus), ["_re", "_rc"]].to_numpy(float)
    bas = min(float(np.nanmin(finis)) if np.isfinite(finis).any() else 0.0, 0.0)
    haut = max(float(np.nanmax(finis)) if np.isfinite(finis).any() else 1.0, 1.0)
    marge = (haut - bas) * 0.12
    premier = None
    for i, f in enumerate(frus):
        ax = fig.add_subplot(grille[i], sharex=premier) if premier is not None else fig.add_subplot(grille[i])
        premier = premier or ax
        g = d[d["Type de FRU"].eq(f)]
        y = np.arange(len(g), dtype=float)
        for yi, (_, r) in zip(y, g.iterrows()):
            meilleure = np.nanmax([r["_re"], r["_rc"]]) if np.isfinite([r["_re"], r["_rc"]]).any() else np.nan
            for dy, v, coul, manque, nom in ((-0.19, r["_re"], BLEU, r["_mre"], "réemploi"), (0.19, r["_rc"], ORANGE, r["_mrc"], "recyclage")):
                if np.isfinite(v):
                    ax.barh([yi + dy], [v], height=0.34, color=coul, edgecolor="none", zorder=2)
                    if v == meilleure and v > 0:
                        _etiquette(ax, _fr(v, 1 if abs(v) < 100 else 0) + " €", (v, yi + dy), taille=T_NOTE + 0.2, couleur=ENCRE)
                    continue
                if nom == "réemploi" and str(r["Pièce"]) == carcasse:
                    texte = "sans objet : la carcasse ne se réemploie pas"
                else:
                    champs = [c.strip() for c in manque.split(",") if c.strip()]
                    texte = "inconnu" + (f" : il manque {', '.join(champs[:3])}" + ("…" if len(champs) > 3 else "") if champs else "")
                ax.plot([0], [yi + dy], linestyle="none", marker="s", markersize=4.5, markerfacecolor=SURFACE, markeredgecolor=coul, markeredgewidth=1.2, zorder=3)
                _etiquette(ax, texte, (0, yi + dy), decalage=(6, 0), taille=T_NOTE, couleur=ENCRE_3, style="italic")
        _zero(ax)
        libelles = []
        for p in g["Pièce"]:
            de = desc.get(str(p)) or ((modele.get(f) or {}).get("pieces") or {}).get(p, {}).get("description", "")
            libelles.append("Carcasse (châssis et reste du FRU)" if str(p) == carcasse else _lib(p, de, 26))
        ax.set_yticks(list(y))
        ax.set_yticklabels(libelles)
        ax.set_ylim(len(g) - 0.45, -0.55)
        soignee = _num(g, "Ouverture soignée (€/FRU)").iloc[0] if "Ouverture soignée (€/FRU)" in g else np.nan
        sommaire = _num(g, "Ouverture sommaire (€/FRU)").iloc[0] if "Ouverture sommaire (€/FRU)" in g else np.nan
        ouverture = (f"Ouverture du FRU, payée une fois : {_fr(soignee, 2)} € pour réemployer, {_fr(sommaire, 2)} € pour trier seulement"
                     if np.isfinite(soignee) or np.isfinite(sommaire) else "Ouverture du FRU : coût inconnu (temps d'ouverture manquant)")
        _axe(ax, "x")
        ax.set_title(_lib(f, descf.get(str(f), ""), 60), loc="left", fontsize=T_AXE + 0.3, color=ENCRE, fontweight="bold", pad=18)
        ax.annotate(ouverture, (0, 1), xycoords="axes fraction", xytext=(0, 5), textcoords="offset points", ha="left", va="bottom",
                    fontsize=T_NOTE, color=ENCRE_2, annotation_clip=False)
        if i < len(frus) - 1:
            ax.tick_params(labelbottom=False)
        else:
            ax.set_xlabel("Valeur nette par FRU, par rapport à la pièce laissée dans le FRU (€)", fontsize=T_AXE, color=ENCRE_2, labelpad=5)
    premier.set_xlim(bas - marge * (1.0 if bas < 0 else 0.25), haut + marge)
    premier.xaxis.set_major_formatter(_fmt())
    return ("Pour chaque pièce de chaque type de FRU : ce que rapporte le réemploi (bleu) et ce que rapporte le recyclage trié (orange), par FRU "
            "traité, comparés à la pièce laissée dans le FRU. Une option dont une donnée manque est écrite « inconnu », jamais tracée à zéro.", fig)


def _actuel_contre_ligne(ctx):
    t = _table(ctx, "ligne", "Actuel contre ligne", ["Poste (€/an)", "Actuel", "Avec la ligne"])
    if t is None:
        return None
    d = t.assign(_a=_num(t, "Actuel"), _l=_num(t, "Avec la ligne"), _p=t["Poste (€/an)"].fillna("(poste sans nom)").astype(str))
    total = d[d["_p"].str.upper().eq("TOTAL")]
    d = pd.concat([d[~d["_p"].str.upper().eq("TOTAL")], total], ignore_index=True)
    n = len(d)
    ecart = float(total["_l"].iloc[0] - total["_a"].iloc[0]) if len(total) else np.nan
    attrs = _objet(ctx, "ligne", "Notes").get("actuel_contre_ligne") or dict(t.attrs)
    sous = "Flux annuels au centre des plages de paramètres : un coût est négatif, un gain positif."
    if np.isfinite(ecart):
        sous += f" Total avec la ligne moins total actuel : {_fr(ecart, signe=True)} € par an."
    elif len(total):
        sous += " Un poste est inconnu : le total n'est pas calculé."
    note = ""
    m, md, part = attrs.get("Masse rebutée (kg/an)"), attrs.get("Masse détournée (kg/an)"), attrs.get("Part détournée")
    if m is not None and md is not None and np.isfinite(m) and np.isfinite(md):
        note = f"Masse détournée de la benne actuelle : {_fr(md)} kg par an sur {_fr(m)} kg rebutés" + (f" ({_pct(part)})." if part is not None and np.isfinite(part) else ".")
    note += " Estimation : les types de FRU aux paramètres incomplets sont exclus du calcul."
    legende = [_pave(GRIS_FONCE, "Situation actuelle : tout part chez le recycleur actuel"), _pave(BLEU, "Avec la ligne de démontage et de tri")]
    fig, corps = _cadre(ctx, 0.65 + 0.78 * n, "Situation actuelle contre ligne de démontage et de tri, poste par poste", sous, note.strip(), legende, colonnes=2)
    ax = fig.add_subplot(corps)
    valeurs = d[["_a", "_l"]].to_numpy(float)
    bas = min(float(np.nanmin(valeurs)) if np.isfinite(valeurs).any() else 0.0, 0.0)
    haut = max(float(np.nanmax(valeurs)) if np.isfinite(valeurs).any() else 1.0, 0.0)
    etendue = (haut - bas) or 1.0
    y = np.arange(n, dtype=float)
    for yi, (_, r) in zip(y, d.iterrows()):
        for dy, v, coul in ((-0.17, r["_a"], GRIS_FONCE), (0.17, r["_l"], BLEU)):
            if not np.isfinite(v):
                _etiquette(ax, "inconnu", (0, yi + dy), couleur=ENCRE_3, style="italic")
                continue
            ax.barh([yi + dy], [v], height=0.3, color=coul, edgecolor="none", zorder=2)
            _etiquette(ax, _fr(v) + " €", (v, yi + dy), decalage=(4 if v >= 0 else -4, 0), ha="left" if v >= 0 else "right",
                       gras=r["_p"].upper() == "TOTAL", couleur=ENCRE if r["_p"].upper() == "TOTAL" else ENCRE_2)
    if len(total) and n > 1:
        ax.axhline(n - 1.5, color=AXE, linewidth=0.9, zorder=1)
    _zero(ax)
    ax.set_yticks(list(y))
    ax.set_yticklabels(["\n".join(textwrap.wrap(p if p.upper() != "TOTAL" else "Total", 30)) for p in d["_p"]])
    ax.set_ylim(n - 0.45, -0.55)
    ax.set_xlim(bas - etendue * (0.2 if bas < 0 else 0.02), haut + etendue * 0.2)
    ax.xaxis.set_major_formatter(_fmt())
    _axe(ax, "x", xlabel="Euros par an")
    for etiq, p in zip(ax.get_yticklabels(), d["_p"]):
        if p.upper() == "TOTAL":
            etiq.set_fontweight("bold")
            etiq.set_color(ENCRE)
    return ("Le coût annuel de la situation actuelle (tous les FRU rebutés partent chez le recycleur actuel) comparé au bilan avec la ligne, poste par "
            "poste puis au total. Lecture : l'écart entre les deux barres du total est le gain annuel attendu de la ligne.", fig)


def _semaine_par_semaine(ctx):
    t = _table(ctx, "ligne", "Période par période", ["Semaine", "Résultat (€)"])
    if t is None:
        return None
    d = t.assign(_s=pd.to_datetime(t["Semaine"], errors="coerce"), _r=_num(t, "Résultat (€)")).dropna(subset=["_s"]).sort_values("_s")
    if not len(d) or not d["_r"].notna().any():
        return None
    rangs, libelle, debut = _semaines(d["_s"])
    x = rangs.to_numpy(float)
    n_sem = int(x.max()) + 1
    d["_c"] = _num(d, "Résultat cumulé (€)") if "Résultat cumulé (€)" in d else np.nan
    if not d["_c"].notna().any():
        d["_c"] = d["_r"].cumsum()
    r = d["_r"].to_numpy(float)
    pertes, inconnues = int((r < 0).sum()), int(np.isnan(r).sum())
    attrs = _objet(ctx, "ligne", "Notes").get("periode_par_periode") or dict(t.attrs)
    sous = (f"Le modèle rejoué sur le flux réel de chaque semaine : coût fixe payé chaque semaine, pas de stock d'une semaine à l'autre. "
            f"{_pluriel(pertes, 'semaine')} en perte sur {_fr(len(d) - inconnues)}.")
    a, b, c = (attrs.get(k) for k in ("Résultat annualisé, période par période (€)", "Résultat du modèle annuel au flux moyen (€)", "Coût de la variabilité du flux (€/an)"))
    note = ""
    if all(v is not None and np.isfinite(v) for v in (a, b, c)):
        note = (f"Résultat annualisé semaine par semaine : {_fr(a)} € ; modèle annuel au flux moyen : {_fr(b)} € ; "
                f"l'écart, {_fr(c)} € par an, est le coût de l'irrégularité du flux.")
    if inconnues:
        note += f" {_pluriel(inconnues, 'semaine')} au résultat inconnu : sans barre."
    legende = [_pave(BLEU, "Semaine bénéficiaire"), _pave(ROUGE, "Semaine en perte")] if pertes else None
    fig, corps = _cadre(ctx, 4.5, "Résultat de la ligne semaine par semaine, puis cumulé", sous, note.strip(), legende, colonnes=2)
    grille = corps.subgridspec(2, 1, height_ratios=[1.15, 1.0], hspace=0.1)
    ax1 = fig.add_subplot(grille[0])
    ax2 = fig.add_subplot(grille[1], sharex=ax1)
    ax1.bar(x, np.nan_to_num(r), width=0.7, color=[ROUGE if v < 0 else BLEU for v in np.nan_to_num(r)], edgecolor=SURFACE, linewidth=0.8, zorder=2)
    for xi, v in zip(x, r):
        if v < 0:
            _etiquette(ax1, _fr(v) + " €", (xi, v), decalage=(0, -3), ha="center", va="top", taille=T_NOTE)
    _zero(ax1, "h")
    etendue = float(np.nanmax(r) - min(np.nanmin(r), 0.0)) or 1.0
    ax1.set_ylim(min(float(np.nanmin(r)), 0.0) - etendue * 0.14, float(np.nanmax(r)) + etendue * 0.08)
    ax1.yaxis.set_major_formatter(_fmt())
    ax1.yaxis.set_major_locator(MaxNLocator(nbins=5))
    _axe(ax1, "y", ylabel="€ par semaine", titre="Résultat de la semaine (marge variable moins coût fixe)")
    ax1.tick_params(labelbottom=False)
    cum = d["_c"].to_numpy(float)
    ax2.plot(x, cum, color=BLEU, linewidth=1.9, marker="o", markersize=4.5, markeredgecolor=SURFACE, markeredgewidth=0.7, solid_capstyle="round", zorder=3)
    if np.isfinite(cum[-1]):
        _etiquette(ax2, _fr(cum[-1]) + " €", (x[-1], cum[-1]), decalage=(0, 7), ha="right", va="bottom", couleur=ENCRE)
    _zero(ax2, "h")
    ax2.set_ylim(min(float(np.nanmin(cum)), 0.0) * 1.1 - 1.0, max(float(np.nanmax(cum)), 0.0) * 1.2 + 1.0)
    ax2.yaxis.set_major_formatter(_fmt())
    ax2.yaxis.set_major_locator(MaxNLocator(nbins=5))
    _axe(ax2, "y", xlabel="Semaine (date du lundi)", ylabel="€ cumulés", titre="Résultat cumulé depuis la première semaine")
    _graduer_semaines(ax1, n_sem, libelle)
    return ("En haut, le résultat de chaque semaine : la marge dégagée sur les FRU arrivés cette semaine-là, moins le coût fixe hebdomadaire. "
            "En bas, le cumul. Lecture : les semaines creuses coûtent le coût fixe ; les semaines chargées saturent les heures disponibles.", fig)


def _monte_carlo(ctx):
    t = _table(ctx, "ligne", "Monte-Carlo (tirages)", ["Résultat / an (€)"])
    if t is None:
        return None
    v = _num(t, "Résultat / an (€)")
    inconnus = int(v.isna().sum())
    x = v.dropna().to_numpy(float)
    if len(x) < 5:
        return None
    p5, med, p95 = (float(q) for q in np.quantile(x, [0.05, 0.5, 0.95]))
    rentable = float((x > 0).mean())
    bas, haut = min(float(x.min()), 0.0), max(float(x.max()), 0.0)
    etendue = (haut - bas) or 1.0
    largeur = (float(x.max()) - float(x.min())) / 28.0 or etendue / 28.0
    debut = math.floor(float(x.min()) / largeur) * largeur        # bornes alignées sur zéro : aucune classe à cheval sur le seuil
    bornes = debut + largeur * np.arange(int(math.ceil((float(x.max()) - debut) / largeur)) + 2)
    effectifs, bornes = np.histogram(x, bins=bornes)
    centres = (bornes[:-1] + bornes[1:]) / 2
    sous = (f"{_fr(len(x))} tirages des plages de paramètres ; la ligne est ré-optimisée à chaque tirage. "
            f"Part des tirages où la ligne est rentable : {_pct(rentable)}.")
    note = "Les plages viennent du classeur de paramètres : des plages trop étroites donnent une assurance qui n'existe pas. Les types de FRU incomplets sont exclus."
    if inconnus:
        note += f" {_pluriel(inconnus, 'tirage')} sans résultat calculable : non compté{'s' if inconnus > 1 else ''}."
    pertes = bool((x <= 0).any())
    legende = [_pave(BLEU, "Tirages rentables"), _pave(ROUGE, "Tirages en perte")] if pertes else None
    fig, corps = _cadre(ctx, 3.3, "Résultat annuel de la ligne : distribution des tirages de Monte-Carlo", sous, note, legende, colonnes=2)
    ax = fig.add_subplot(corps)
    ax.bar(centres, effectifs, width=largeur, color=[ROUGE if c < 0 else BLEU for c in centres], edgecolor=SURFACE, linewidth=0.8, zorder=2)
    sommet = float(effectifs.max())
    ax.set_ylim(0, sommet * 1.3)
    ax.set_xlim(bas - etendue * 0.04, haut + etendue * 0.05)
    ax.axvline(0, color=ENCRE, linewidth=1.3, zorder=3)
    ax.text(0, 0.985, " seuil de rentabilité : 0 € " if bas < 0 else " seuil de rentabilité : 0 €", transform=ax.get_xaxis_transform(),
            ha="left" if p5 > etendue * 0.3 + bas or bas == 0 else "right", va="top", fontsize=T_NOTE, color=ENCRE)
    for q, nom, ha in ((p5, "P5", "right"), (med, "médiane", "center"), (p95, "P95", "left")):
        ax.plot([q, q], [0, sommet * 1.1], color=ENCRE_2, linewidth=1.0, zorder=2.6)
        ax.text(q, sommet * 1.115, f"{nom}\n{_fr(q)} €", ha=ha, va="bottom", fontsize=T_NOTE, color=ENCRE, linespacing=1.2)
    ax.xaxis.set_major_formatter(_fmt())
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
    _axe(ax, "y", xlabel="Résultat annuel de la ligne par rapport à la situation actuelle (€)", ylabel="Nombre de tirages")
    return ("Ce que devient le résultat annuel quand tous les paramètres incertains varient dans leurs plages. Lecture : P5 et P95 encadrent neuf "
            "tirages sur dix ; la part de la distribution à gauche de zéro est le risque que la ligne ne soit pas rentable.", fig)


def _sensibilite_heures(ctx):
    t = _table(ctx, "ligne", "Sensibilité aux heures", ["Heures / an", "Résultat / an (€)"])
    if t is None:
        return None
    d = t.assign(_h=_num(t, "Heures / an"), _r=_num(t, "Résultat / an (€)")).dropna(subset=["_h"]).sort_values("_h")
    if len(d) < 2 or not d["_r"].notna().any():
        return None
    col_v = "Valeur d'une heure opérateur en plus (€ net)"
    d["_v"] = _num(d, col_v) if col_v in d else np.nan
    capacite = (_objet(ctx, "ligne", "Notes").get("resume") or {}).get("Capacité (h/an)")
    capacite = float(capacite) if capacite is not None and np.isfinite(capacite) else None
    deux = d["_v"].notna().any()
    sous = "La ligne est ré-optimisée pour chaque niveau d'heures disponibles, les autres paramètres restant au centre de leur plage."
    note = ("Valeur d'une heure en plus : marge nette qu'apporterait une heure opérateur supplémentaire ; elle tombe à zéro quand tous les FRU "
            "rentables sont déjà traités. C'est l'argument chiffré pour demander, ou non, des heures.")
    fig, corps = _cadre(ctx, 4.6 if deux else 2.8, "Sensibilité du résultat aux heures opérateur disponibles", sous, note)
    grille = corps.subgridspec(2 if deux else 1, 1, hspace=0.1)
    ax1 = fig.add_subplot(grille[0])
    axes = [ax1]
    ax1.plot(d["_h"], d["_r"], color=BLEU, linewidth=1.9, marker="o", markersize=6.5, markeredgecolor=SURFACE, markeredgewidth=0.9, zorder=3)
    r = d["_r"].to_numpy(float)
    etendue = float(np.nanmax(r) - min(np.nanmin(r), 0.0)) or 1.0
    ax1.set_ylim(min(float(np.nanmin(r)), 0.0) - etendue * 0.06, float(np.nanmax(r)) + etendue * 0.2)
    if float(np.nanmin(r)) < 0:
        _zero(ax1, "h")
    ax1.yaxis.set_major_formatter(_fmt())
    ax1.yaxis.set_major_locator(MaxNLocator(nbins=5))
    _axe(ax1, "y", ylabel="€ par an", titre="Résultat annuel de la ligne")
    if deux:
        ax2 = fig.add_subplot(grille[1], sharex=ax1)
        axes.append(ax2)
        ax2.plot(d["_h"], d["_v"], color=BLEU, linewidth=1.9, marker="o", markersize=6.5, markeredgecolor=SURFACE, markeredgewidth=0.9, zorder=3)
        ax2.set_ylim(0, max(float(d["_v"].max()), 1.0) * 1.25)
        ax2.yaxis.set_major_formatter(_fmt())
        ax2.yaxis.set_major_locator(MaxNLocator(nbins=5))
        _axe(ax2, "y", ylabel="€ par heure", titre="Valeur d'une heure opérateur supplémentaire")
        ax1.tick_params(labelbottom=False)
    axes[-1].set_xlabel("Heures opérateur disponibles par an", fontsize=T_AXE, color=ENCRE_2, labelpad=5)
    ax1.set_xlim(0, float(d["_h"].max()) * 1.04)
    ax1.xaxis.set_major_formatter(_fmt())
    if capacite is not None:
        for a in axes:
            a.axvline(capacite, color=ENCRE_2, linewidth=0.9, zorder=1.6)
        ax1.text(capacite, 1.0, f" capacité actuelle : {_fr(capacite)} h par an", transform=ax1.get_xaxis_transform(), ha="left", va="top",
                 fontsize=T_NOTE, color=ENCRE)
        proche = d.iloc[(d["_h"] - capacite).abs().to_numpy().argmin()]
        if abs(float(proche["_h"]) - capacite) < 1e-6 * max(capacite, 1.0) and np.isfinite(proche["_r"]):
            ax1.plot([capacite], [proche["_r"]], linestyle="none", marker="o", markersize=9.5, markerfacecolor=BLEU_FONCE, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=4)
            _etiquette(ax1, _fr(proche["_r"]) + " €", (capacite, float(proche["_r"])), decalage=(8, -9), ha="left", va="top", couleur=ENCRE)
            if deux and np.isfinite(proche["_v"]):
                axes[1].plot([capacite], [proche["_v"]], linestyle="none", marker="o", markersize=9.5, markerfacecolor=BLEU_FONCE, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=4)
                _etiquette(axes[1], _fr(proche["_v"], 1) + " € par heure", (capacite, float(proche["_v"])), decalage=(8, 8), ha="left", va="bottom", couleur=ENCRE)
    return ("En haut, le résultat annuel selon les heures opérateur accordées à la ligne ; en bas, ce que rapporterait une heure de plus. "
            "Lecture : tant que la courbe du haut monte, les heures manquent ; quand elle plafonne, ajouter des heures ne rapporte plus rien.", fig)


def _preparation(ctx):
    t = _table(ctx, "ligne", "Paramètres effectifs", ["FRU", "Paramètre", "État"])
    if t is None:
        return None
    obtenir = _table(ctx, "ligne", "Données à obtenir", ["Paramètre"])
    bloquants = set(obtenir["Paramètre"].astype(str)) if obtenir is not None else None
    d = t.dropna(subset=["FRU", "État"])
    if not len(d):
        return None
    d = d.assign(_e=d["État"].astype(str), _f=d["FRU"].astype(str))
    if bloquants is not None:                 # un paramètre manquant absent de « Données à obtenir » est facultatif : il ne bloque aucun calcul
        d.loc[d["_e"].eq("manquant") & d["Paramètre"].astype(str).isin(bloquants), "_e"] = "manquant, bloque un calcul"
        d.loc[d["_e"].eq("manquant"), "_e"] = "manquant, facultatif"
    etats = [("saisi", BLEU_FONCE, "Saisi dans le classeur de paramètres", "white"), ("tiré des données", BLEU_CLAIR, "Tiré des données", ENCRE),
             ("manquant, facultatif", GRIS, "Manquant, facultatif (ne bloque aucun calcul)", ENCRE),
             ("manquant, bloque un calcul", ORANGE, "Manquant, bloque un calcul", "white"), ("manquant", ORANGE, "Manquant", "white")]
    etats = [e for e in etats if d["_e"].eq(e[0]).any()]
    if not etats:
        return None
    compte = d.groupby(["_f", "_e"]).size().unstack(fill_value=0)
    ordre = [f for f in pd.unique(d["_f"])][:16]
    en_trop = d["_f"].nunique() - len(ordre)
    compte = compte.reindex(ordre)
    descf = _descriptions_fru(ctx)
    n = len(ordre)
    sous = ("Nombre de paramètres du modèle de ligne, selon leur provenance. Un paramètre manquant n'est jamais remplacé par zéro : "
            "le calcul qui en dépend reste vide et le type de FRU est signalé incomplet.")
    note = "Les paramètres qui bloquent un calcul sont listés, avec le service à qui les demander, dans la table « Données à obtenir »."
    if en_trop > 0:
        note += f" {_pluriel(en_trop, 'autre type', 'autres types')} de FRU dans la table."
    fig, corps = _cadre(ctx, 0.6 + 0.4 * n, "État de préparation des paramètres, par type de FRU", sous, note, [_pave(c, lab) for _, c, lab, _ in etats], colonnes=2)
    ax = fig.add_subplot(corps)
    y = np.arange(n, dtype=float)
    gauche = np.zeros(n)
    maxi = float(compte.sum(axis=1).max())
    for e, coul, _lab, encre in etats:
        v = compte[e].to_numpy(float) if e in compte else np.zeros(n)
        ax.barh(y, v, left=gauche, height=0.6, color=coul, edgecolor=SURFACE, linewidth=1.0, zorder=2)
        for yi, vi, gi in zip(y, v, gauche):
            if vi >= maxi * 0.035:                # le nombre n'est écrit que s'il tient dans le segment
                ax.text(gi + vi / 2.0, yi, _fr(vi), ha="center", va="center", fontsize=T_NOTE, color=encre, zorder=3)
        gauche = gauche + v
    for yi, f in zip(y, ordre):
        nb = int(compte.at[f, "manquant, bloque un calcul"]) if "manquant, bloque un calcul" in compte else None
        if nb is None:
            nb_m = int(compte.at[f, "manquant"]) if "manquant" in compte else 0
            texte = f"{_fr(nb_m)} manquant{'s' if nb_m > 1 else ''}" if nb_m else "aucun manquant"
        else:
            texte = f"{_fr(nb)} à obtenir" if nb else "complet pour le calcul"
        _etiquette(ax, texte, (float(compte.loc[f].sum()), yi), decalage=(6, 0), couleur=ENCRE if nb else ENCRE_2, gras=bool(nb))
    ax.set_yticks(list(y))
    ax.set_yticklabels(["Paramètres généraux de la ligne" if f == "(ligne)" else _lib(f, descf.get(f, ""), 28) for f in ordre])
    ax.set_ylim(n - 0.45, -0.55)
    ax.set_xlim(0, maxi * 1.24)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
    ax.xaxis.set_major_formatter(_fmt())
    _axe(ax, "x", xlabel="Nombre de paramètres")
    return ("Où en est la collecte des paramètres du modèle : pour la ligne et pour chaque type de FRU, combien de paramètres sont saisis, tirés "
            "des données ou manquants. Lecture : seuls les segments orange empêchent un calcul ; ils désignent les données à obtenir en priorité.", fig)


# =========================================================================== catalogue et point d'entrée
CATALOGUE = [
    # (étape, nom de la figure, fonction qui la trace)
    ("classement", "Top MMICV", _top_mmicv),
    ("classement", "Pré-sélection", lambda ctx: _preselection(ctx, "classement", "Priorisation")),
    ("flux", "FRU rebutées par semaine", _fru_par_semaine),
    ("flux", "Rebut annuel par type de FRU", _rebut_annuel),
    ("flux", "Pièces et masse par type de déchet", _par_type_de_dechet),
    ("flux", "Estimé contre pesé", _estime_contre_pese),
    ("flux", "Cumul estimé contre pesé", _cumul),
    ("fiabilite", "Taux de défaillance précoce", _taux_precoce),
    ("fiabilite", "Kaplan-Meier", _kaplan_meier),
    ("fiabilite", "Forme de Weibull", _forme_weibull),
    ("fiabilite", "Âge du donneur (illustration)", _age_du_donneur),
    ("fiabilite", "Pré-sélection avec fiabilité", lambda ctx: _preselection(
        ctx, "fiabilite", "Priorisation avec fiabilité", "Pré-sélection des pièces, la fiabilité du réemploi ajoutée aux critères")),
    ("rex", "Probabilité de réemploi", _q_par_piece),
    ("rex", "Métriques par modèle", _metriques),
    ("rex", "Réglage de N0", _reglage_n0),
    ("rex", "Banc d'essai (regret)", _regret),
    ("ligne", "Préparation des paramètres", _preparation),
    ("ligne", "Options par pièce", _options_par_piece),
    ("ligne", "Actuel contre ligne", _actuel_contre_ligne),
    ("ligne", "Semaine par semaine", _semaine_par_semaine),
    ("ligne", "Monte-Carlo", _monte_carlo),
    ("ligne", "Sensibilité aux heures", _sensibilite_heures),
    ("synthese", "Préparation des paramètres", _preparation),
]
NOMS = {}                                             # étape → noms des figures, dans l'ordre de lecture
for _e, _n, _f in CATALOGUE:
    NOMS.setdefault(_e, []).append(_n)


def _figer(fig) -> None:
    """Calcule la mise en page tout de suite : tous les textes (graduations comprises) sont créés avec les réglages du
    dossier, et une figure impossible à dessiner est écartée ici, sans faire perdre les autres."""
    if hasattr(fig, "draw_without_rendering"):        # matplotlib ≥ 3.5
        fig.draw_without_rendering()
    else:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        FigureCanvasAgg(fig).draw()


def tracer(etape: str, ctx) -> list:
    """Figures d'une étape : liste de (nom, description, figure). Une figure sans données est simplement absente ;
    une figure qui échoue est inscrite aux anomalies du contexte et n'empêche pas les autres."""
    figures = []
    for e, nom, fonction in CATALOGUE:
        if e != etape:
            continue
        try:
            with matplotlib.rc_context(REGLAGES):
                resultat = fonction(ctx)
                if resultat is not None:
                    _figer(resultat[1])
        except Exception as erreur:
            anomalies = getattr(ctx, "anomalies", None)
            if isinstance(anomalies, list):
                anomalies.append({"Étape": etape, "Calcul": f"figure « {nom} »", "Erreur": f"{type(erreur).__name__}: {erreur}"[:400],
                                  "Détail": traceback.format_exc(limit=3)[-600:]})
            continue
        if resultat is not None:
            description, fig = resultat
            figures.append((nom, description, fig))
    return figures
