"""Lecture des sources, une seule fois, avec un état lisible de ce qui est présent, absent ou défectueux.

Aucune source n'est obligatoire : une source absente ou illisible est notée dans `Sources.etat` et les étapes
qui en dépendent rendent des tables vides ou des valeurs « inconnu », jamais des zéros inventés.

Fichiers attendus (noms et colonnes des extractions existantes) :
  projet/ERC_R26_extraction_AAAAMMJJ_AAAAMMJJ.xlsx   Composants_jour, FRU_rebutees, FRU_statut_cohorte
  projet/Classification_matieres/ERC_Classification_Cartes_resultats.xlsx (Classification), ERC_Referentiel_Grades.xlsx (Grades)
  projet/Extraction_R26/poids_items_vwAllItems.csv, fiabilite_ELF_references_ERC.csv, poses_2022_2023_par_reference.csv
  projet/Acquisition/pesees_hebdo.csv, audit_demontage.csv
  racine/ERC_Valorisation_MICV_v1.xlsx (QueryComponents, QueryERC_Flow_In_Out), FRU_info.xlsx, Parts_DI_ULS_Data_upd(2022, 23).xlsb

Ce que la lecture tolère, et dit dans « Contrôles des sources » :
  - un nom d'onglet ou de colonne qui ne diffère que par la casse, les accents, les espaces ou les tirets bas ;
  - une référence saisie comme un nombre (1234567.0), avec des espaces, en minuscules : elle est lue en texte,
    sans espaces, en majuscules ;
  - une date en texte JJ/MM/AAAA, en numéro de série d'Excel, ou avec une heure ;
  - un nombre avec une virgule décimale et des espaces de milliers (« 1 234,5 ») ;
  - un CSV enregistré par Excel en encodage Windows, ou séparé par des virgules ou des tabulations.

Ce qu'elle écarte, toujours avec le nombre de lignes concernées : une ligne sans date ou sans référence lisible,
une quantité illisible, une ligne datée hors de la période annoncée par le nom de son fichier, un poids ou un
MMICV nul ou négatif (traité comme inconnu), un lot d'audit incohérent.

Extractions qui se chevauchent : sur un jour commun à deux fichiers, seul le fichier le plus récent est lu. Le
plus récent est celui dont la période, écrite dans son nom, finit le plus tard (à fin égale : celle qui commence
le plus tard). La date de modification du fichier n'est pas utilisée : une copie ou une synchronisation la change.
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .config import MOTIF_EXTRACTION, Config

F_VALO = "ERC_Valorisation_MICV_v1.xlsx"
F_FRU = "FRU_info.xlsx"
F_FIAB = "Parts_DI_ULS_Data_upd(2022, 23).xlsb"
COLS_EV = ["Jour", "PO", "FRU ITEM", "Component ITEM", "Component Description", "Qte"]
BLOQUANT, A_VERIFIER, INFORMATION = "bloquant", "à vérifier", "information"
REGLE_EXTRACTIONS = ("sur un jour commun à deux extractions, seule l'extraction dont la période (lue dans le nom du fichier) "
                     "finit le plus tard est lue")


class SourceInutilisable(Exception):
    """Source lue mais inutilisable ; le message, en français, dit ce qui manque et où."""


def expliquer(e: BaseException) -> str:
    """Erreur en français lisible sans connaître Python ; le nom technique reste entre crochets pour le support."""
    if isinstance(e, SourceInutilisable):
        return str(e)
    nom = type(e).__name__
    if isinstance(e, PermissionError):
        t = "fichier verrouillé ou accès refusé (ouvert dans Excel ?) : le fermer, puis relancer"
    elif isinstance(e, FileNotFoundError):
        t = "fichier ou dossier introuvable"
    elif isinstance(e, zipfile.BadZipFile):
        t = "le fichier n'est pas un classeur Excel lisible (.xlsx attendu : fichier abîmé ou enregistré dans un autre format)"
    elif isinstance(e, KeyError):
        t = f"colonne ou clé absente : {e.args[0] if e.args else ''}"
    elif isinstance(e, UnicodeError):
        t = "encodage du texte non reconnu"
    elif isinstance(e, pd.errors.EmptyDataError):
        t = "fichier vide"
    elif isinstance(e, pd.errors.ParserError):
        t = f"lignes de longueur inégale, séparateur ou guillemets à vérifier : {e}"
    elif isinstance(e, ImportError):
        t = f"module Python absent, à installer : {getattr(e, 'name', None) or e}"
    elif isinstance(e, ZeroDivisionError):
        t = "division par zéro"
    elif isinstance(e, MemoryError):
        t = "mémoire insuffisante"
    elif isinstance(e, (ValueError, TypeError)):
        t = f"valeur ou format inattendu : {e}"
    elif isinstance(e, OSError):
        t = f"lecture ou écriture impossible : {e.strerror or e}"
    else:
        t = f"erreur inattendue : {e}"
    return f"{t} [{nom}]"


# --------------------------------------------------------------------------- cellules : références, nombres, dates
def ref(x):
    """Référence en texte propre : « 1234567.0 » → « 1234567 », espaces retirés, majuscules ; vide → NaN."""
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return np.nan
    if isinstance(x, (float, np.floating)) and float(x).is_integer():
        x = int(x)                                           # 1234567.0 ou 1.2e7 : un entier, sans notation scientifique
    t = str(x).strip().upper()
    if re.fullmatch(r"\d+\.0+", t):                          # nombre relu comme texte : « 1234567.0 »
        t = t.split(".")[0]
    return t or np.nan


def base_ref(r) -> str:
    """Référence sans suffixe de pièce réparée ou récupérée (-H, -U, -R, -RA)."""
    return re.sub(r"-(H|U|R|RA)$", "", str(r).strip().upper())


def origine(r) -> str:
    r = str(r).strip().upper()
    return "Récupérée" if r.endswith(("-H", "-U")) else "Réparée" if r.endswith(("-R", "-RA")) else "Neuve"


def semaine(j):
    """Lundi de la semaine ISO (Series de dates → Series de dates)."""
    j = pd.to_datetime(j)
    return (j - pd.to_timedelta(j.dt.weekday, unit="D")).dt.normalize()


def _cle(nom) -> str:
    """Nom d'onglet, de colonne ou de flux réduit à l'essentiel : sans accent, sans casse, sans espace ni ponctuation en trop."""
    t = "".join(c for c in unicodedata.normalize("NFKD", str(nom)) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _un_nombre(v) -> float:
    """Une cellule → nombre, ou NaN si elle est vide ou illisible. « 1 234,5 », « 1.234,5 » et « 1,234.5 » valent 1234.5 ;
    avec une seule virgule et sans point, la virgule est la décimale (usage français)."""
    if v is None or isinstance(v, (bool, np.bool_)):
        return np.nan
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v) if np.isfinite(v) else np.nan
    if not isinstance(v, str):
        return np.nan
    t = re.sub(r"[\s   ']", "", v)
    if not t:
        return np.nan
    if "," in t and "." in t:                                # le dernier des deux signes est la décimale
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif t.count(",") == 1:
        t = t.replace(",", ".")
    elif t.count(",") > 1:
        t = t.replace(",", "")
    if not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", t):
        return np.nan
    return float(t)


def _num(s) -> pd.Series:
    """Colonne → nombres (float) ; vide ou illisible → NaN, jamais 0."""
    s = pd.Series(s)
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        return pd.to_numeric(s, errors="coerce").astype(float)
    return pd.Series([_un_nombre(v) for v in s], index=s.index, dtype=float)


_EXCEL_JOUR_0 = pd.Timestamp("1899-12-30")
_RE_JMA = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})(?:[ T]+(\d{1,2})[:h](\d{2})(?::(\d{2})(?:[.,]\d+)?)?)?")
_RE_AMJ = re.compile(r"(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2})(?:[.,]\d+)?)?)?(?:Z|[+-]\d{2}:?\d{2})?")
_RE_SEMAINE = re.compile(r"(\d{4})[\s\-_/]*[SsWw](\d{1,2})")


def _horodatage(a, m, j, h=None, mi=None, sec=None):
    try:
        return pd.Timestamp(year=int(a), month=int(m), day=int(j), hour=int(h or 0), minute=int(mi or 0), second=int(sec or 0))
    except (ValueError, OverflowError):
        return pd.NaT


def _serie_excel(x: float):
    """Numéro de série d'Excel (jours depuis le 30/12/1899) ; seulement entre 1954 et 2119, sinon ce n'est pas une date."""
    if 20000 <= x <= 80000:
        return _EXCEL_JOUR_0 + pd.to_timedelta(round(x * 86400), unit="s")
    if 19000101 <= x <= 21001231 and float(x).is_integer():      # AAAAMMJJ saisi comme un nombre
        t = str(int(x))
        return _horodatage(t[:4], t[4:6], t[6:])
    return pd.NaT


def _une_date(v):
    """Une cellule → date (Timestamp) ou NaT. Lit une date, « JJ/MM/AAAA » (heure facultative), « AAAA-MM-JJ »,
    « AAAAMMJJ », le numéro de série d'Excel et « AAAA-Sss » (lundi de la semaine). Jamais mois/jour à l'américaine."""
    if v is None or isinstance(v, (bool, np.bool_)):
        return pd.NaT
    if isinstance(v, (pd.Timestamp, datetime, date, np.datetime64)):
        t = pd.Timestamp(v)
        return pd.NaT if pd.isna(t) else t.tz_localize(None) if t.tzinfo is not None else t
    if isinstance(v, (int, float, np.integer, np.floating)):
        return _serie_excel(float(v)) if np.isfinite(v) else pd.NaT
    if not isinstance(v, str):
        return pd.NaT
    t = v.strip()
    if not t:
        return pd.NaT
    m = _RE_JMA.fullmatch(t)
    if m:
        j, mo, a = m.group(1), m.group(2), m.group(3)
        return _horodatage(int(a) + 2000 if len(a) == 2 else a, mo, j, m.group(4), m.group(5), m.group(6))
    m = _RE_AMJ.fullmatch(t)
    if m:
        return _horodatage(*m.groups())
    if re.fullmatch(r"\d+(?:[.,]\d+)?", t):
        return _serie_excel(float(t.replace(",", ".")))
    m = _RE_SEMAINE.fullmatch(t)
    if m:
        try:
            return pd.Timestamp(datetime.strptime(f"{m.group(1)} {int(m.group(2))} 1", "%G %V %u"))
        except ValueError:
            return pd.NaT
    try:                                                     # dernier recours : « 1 June 2026 », « Jun 1, 2026 »
        r = pd.to_datetime(t, dayfirst=True, errors="coerce")
        return pd.NaT if pd.isna(r) else pd.Timestamp(r).tz_localize(None) if pd.Timestamp(r).tzinfo is not None else pd.Timestamp(r)
    except Exception:
        return pd.NaT


def _dates(col) -> pd.Series:
    """Colonne → dates (datetime64[ns]), illisible → NaT. Chaque valeur distincte est lue une fois, par `_une_date`."""
    s = pd.Series(col)
    if pd.api.types.is_datetime64_any_dtype(s):
        if getattr(s.dt, "tz", None) is not None:
            s = s.dt.tz_localize(None)
        return s.astype("datetime64[ns]")
    lues = {}
    for v in s:
        try:
            if v not in lues:
                lues[v] = _une_date(v)
        except TypeError:                                    # valeur non hachable : illisible
            pass
    res = [lues.get(v, pd.NaT) if not isinstance(v, (list, dict, set)) else pd.NaT for v in s]
    return pd.Series(pd.to_datetime(pd.Series(res, index=s.index, dtype=object), errors="coerce"), index=s.index).astype("datetime64[ns]")


def _texte(col) -> pd.Series:
    """Colonne de libellés : texte sans espaces autour ; vide → NaN."""
    return pd.Series([np.nan if (v is None or (not isinstance(v, str) and pd.isna(v)) or not str(v).strip()) else str(v).strip()
                      for v in col], index=pd.Series(col).index, dtype=object)


def _liste(valeurs, n=6) -> str:
    v = [str(x) for x in valeurs]
    return ", ".join(v[:n]) + (f" … ({len(v)} au total)" if len(v) > n else "")


def _pl(n, singulier: str, pluriel: str | None = None) -> str:
    """« 1 ligne », « 3 lignes » : le nombre et le mot accordé."""
    n = int(n)
    return f"{n} {singulier if n < 2 else (pluriel or ' '.join(m + 's' for m in singulier.split(' ')))}"


# --------------------------------------------------------------------------- fichiers : CSV et classeurs
def _csv(f, **kw) -> pd.DataFrame:
    """CSV lu en texte, quel que soit son enregistrement : UTF-8 (avec ou sans marque d'ordre), UTF-16 ou Windows
    (cp1252) ; séparateur « ; », tabulation ou « , » reconnu sur la ligne d'en-tête. `attrs["lecture"]` dit ce qui a été reconnu."""
    brut = Path(f).read_bytes()
    encodages = ("utf-16",) if brut[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp1252", "latin-1")
    texte, enc = None, None
    for enc in encodages:
        try:
            texte = brut.decode(enc)
            break
        except UnicodeError:
            continue
    if texte is None:
        raise SourceInutilisable("encodage du fichier non reconnu : l'enregistrer en « CSV UTF-8 (délimité par des points-virgules) »")
    if not texte.strip():
        raise SourceInutilisable("fichier vide")
    entete = next((l for l in texte.splitlines() if l.strip()), "")
    hors_guillemets = re.sub(r'"[^"]*"', "", entete)
    sep = max((";", "\t", ","), key=lambda c: hors_guillemets.count(c))        # à égalité : « ; », le format attendu
    options = dict(sep=sep, dtype=str, keep_default_na=False, na_values=[""], skip_blank_lines=True)
    options.update(kw)
    d = pd.read_csv(io.StringIO(texte), **options)
    d.attrs["lecture"] = {"encodage": enc, "separateur": sep}
    return d


def _note_csv(s: "Sources", source: str, fichier, d: pd.DataFrame) -> None:
    lu = d.attrs.get("lecture", {})
    if lu.get("separateur", ";") != ";":
        s._constat(source, fichier, INFORMATION, "séparateur « {} » au lieu de « ; » : reconnu".format("tabulation" if lu["separateur"] == "\t" else lu["separateur"]))
    if lu.get("encodage") not in (None, "utf-8-sig"):
        s._constat(source, fichier, INFORMATION, f"encodage {'Windows (cp1252)' if lu['encodage'] in ('cp1252', 'latin-1') else lu['encodage']} au lieu d'UTF-8 : reconnu")


def _colonnes(d: pd.DataFrame, attendues, s: "Sources | None" = None, source: str = "", fichier="") -> pd.DataFrame:
    """Renomme vers le nom attendu les colonnes qui n'en diffèrent que par la casse, les accents ou les espaces."""
    presentes = {}
    for c in d.columns:
        presentes.setdefault(_cle(c), c)
    renommer = {}
    for a in attendues:
        if a not in d.columns and _cle(a) in presentes and presentes[_cle(a)] not in attendues:
            renommer[presentes[_cle(a)]] = a
    if renommer:
        d = d.rename(columns=renommer)
        if s is not None:
            s._constat(source, fichier, INFORMATION, "colonnes reconnues malgré leur écriture : " + ", ".join(f"« {k} » lue comme « {v} »" for k, v in renommer.items()))
    return d


def _exiger(d: pd.DataFrame, colonnes, quoi: str = "") -> None:
    manquantes = [c for c in colonnes if c not in d.columns]
    if manquantes:
        if not len(d.columns):
            raise SourceInutilisable(f"{quoi or 'fichier'} vide : aucune colonne")
        raise SourceInutilisable(f"{_pl(len(manquantes), 'colonne')} introuvable{'s' if len(manquantes) > 1 else ''}"
                                 f"{' dans ' + quoi if quoi else ''} : {', '.join('« ' + c + ' »' for c in manquantes)} ; "
                                 f"colonnes présentes : {_liste(d.columns, 12)}")


def _onglet(x: pd.ExcelFile, nom: str, colonnes=()) -> tuple:
    """Onglet `nom` d'un classeur ouvert, reconnu sans casse ni accent. À défaut, le seul onglet du classeur s'il porte
    les colonnes attendues. Renvoie (table ou None, remarque en français)."""
    reels = {}
    for n in x.sheet_names:
        reels.setdefault(_cle(n), n)
    reel = reels.get(_cle(nom))
    if reel is not None:
        return x.parse(reel), ("" if reel == nom else f"onglet « {reel} » lu comme « {nom} »")
    if len(x.sheet_names) == 1 and colonnes:
        d = x.parse(x.sheet_names[0])
        if {_cle(c) for c in colonnes} <= {_cle(c) for c in d.columns}:
            return d, f"onglet « {x.sheet_names[0]} » lu à la place de « {nom} » : seul onglet du fichier, colonnes attendues présentes"
    return None, f"onglet « {nom} » introuvable ; onglets du fichier : {_liste(x.sheet_names, 12)}"


def _lire_onglet(s: "Sources", source: str, f: Path, nom: str, colonnes) -> pd.DataFrame:
    """Onglet d'un classeur, colonnes renommées et exigées ; lève SourceInutilisable avec un message en français."""
    with pd.ExcelFile(f) as x:
        d, remarque = _onglet(x, nom, colonnes)
    if d is None:
        raise SourceInutilisable(remarque)
    if remarque:
        s._constat(source, f.name, INFORMATION, remarque)
    d = _colonnes(d, colonnes, s, source, f.name)
    _exiger(d, colonnes, f"l'onglet « {nom} »")
    return d


def _doublons(s: "Sources", source: str, fichier, d: pd.DataFrame, cle: str, valeurs=()) -> pd.DataFrame:
    """Garde la première ligne de chaque clé et dit combien de lignes en double ont été écartées."""
    double = d.duplicated(cle, keep="first")
    if double.any():
        cols = [c for c in valeurs if c in d.columns]
        differents = 0
        if cols:
            g = d.groupby(cle)[cols].nunique(dropna=True)
            differents = int((g > 1).any(axis=1).sum())
        s._constat(source, fichier, A_VERIFIER if differents else INFORMATION,
                   f"{_pl(double.sum(), 'ligne')} en double sur « {cle} » : la première est gardée"
                   + (f" ; {_pl(differents, 'référence')} avec des valeurs différentes d'une ligne à l'autre" if differents else ""))
    return d[~double]


# --------------------------------------------------------------------------- sources
@dataclass
class Sources:
    cfg: Config
    etat: list = field(default_factory=list)
    controles: list = field(default_factory=list)
    ev: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=COLS_EV + ["Atelier", "Famille"]))
    couverts: set = field(default_factory=set)                 # jours extraits pour les consommations
    couverts_rebut: set = field(default_factory=set)           # jours extraits pour les FRU rebutées (onglet FRU_rebutees lisible)
    fru_rebutees: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["Date rebut", "FRU", "Unités"]))
    regle_date_rebut: str = "aucun onglet FRU_rebutees"
    cohorte: pd.DataFrame = field(default_factory=pd.DataFrame)
    atelier_fru: dict = field(default_factory=dict)
    famille_fru: dict = field(default_factory=dict)
    classification: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(
        columns=["Catégorie proposée", "Benne", "Poids unitaire (kg)", "Source poids", "Fabricant", "Nature réelle", "Niveau de preuve"]))
    qc: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(
        columns=["FRU ITEM", "FRU Description", "Component ITEM", "Component Description", "Total Consumption Quantity", "Total value"]))
    mmicv: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    mmicv_source: pd.Series = field(default_factory=lambda: pd.Series(dtype=object))
    prix_recycleur: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    poids_fru: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    desc_fru: pd.Series = field(default_factory=lambda: pd.Series(dtype=object))
    desc_piece: pd.Series = field(default_factory=lambda: pd.Series(dtype=object))
    elf: pd.DataFrame = field(default_factory=pd.DataFrame)
    poses: pd.Series | None = None
    pesees: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["Semaine", "Flux", "Masse mesurée (kg)", "Cause constatée"]))
    audit: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["Date", "Type de FRU", "Pièce", "Pièces testées", "Pièces bonnes"]))

    @property
    def periode(self) -> str:
        if not self.couverts:
            return "aucun jour extrait"
        return f"du {min(self.couverts):%d/%m/%Y} au {max(self.couverts):%d/%m/%Y}, {len(self.couverts)} jours extraits"

    def etat_df(self) -> pd.DataFrame:
        """Une ligne par fichier attendu. « Détail » reprend les constats bloquants ou à vérifier de « Contrôles des sources »."""
        d = pd.DataFrame(self.etat, columns=["Source", "Fichier", "État", "Lignes", "Détail", "Sert à"])
        if not len(d) or not self.controles:
            return d
        for i, r in d.iterrows():
            plus = [c["Constat"] for c in self.controles if c["Source"] == r["Source"] and c["Fichier"] == r["Fichier"] and c["Gravité"] != INFORMATION
                    and c["Constat"] not in str(r["Détail"])]
            if plus:
                d.at[i, "Détail"] = " ; ".join([str(r["Détail"])] * bool(r["Détail"]) + plus)
        return d

    def controles_df(self) -> pd.DataFrame:
        """Tout ce que la lecture a remarqué : source inutilisable (bloquant), lignes écartées ou valeurs douteuses
        (à vérifier), écart de forme toléré (information)."""
        ordre = {BLOQUANT: 0, A_VERIFIER: 1, INFORMATION: 2}
        d = pd.DataFrame(self.controles, columns=["Source", "Fichier", "Gravité", "Constat"])
        return d.iloc[np.argsort([ordre.get(g, 3) for g in d["Gravité"]], kind="stable")].reset_index(drop=True) if len(d) else d

    def _note(self, source, fichier, etat, lignes=None, detail="", sert=""):
        self.etat.append({"Source": source, "Fichier": str(fichier), "État": etat, "Lignes": lignes, "Détail": detail, "Sert à": sert})

    def _constat(self, source, fichier, gravite, constat):
        self.controles.append({"Source": source, "Fichier": Path(str(fichier)).name if fichier else "", "Gravité": gravite, "Constat": constat})


def _ou(cfg: Config, fichier) -> str:
    """Où un fichier est attendu, sans chemin complet (un chemin peut contenir un nom de personne)."""
    f = Path(str(fichier))
    for base, nom in ((cfg.projet, "dossier des extractions"), (cfg.racine, "dossier des référentiels")):
        try:
            if base is not None:
                rel = f.parent.relative_to(base).as_posix()
                return f"attendu dans le {nom}" + ("" if rel in (".", "") else f", sous-dossier {rel}/")
        except ValueError:
            continue
    return ""


def _essayer(s: Sources, source: str, fichier: Path | None, sert: str, lecteur):
    """Exécute `lecteur()` et note l'état : chargé, absent, ou erreur avec sa cause en français. Renvoie le résultat ou None."""
    if fichier is None or not Path(fichier).exists():
        s._note(source, Path(str(fichier)).name if fichier is not None else "", "absent", detail=_ou(s.cfg, fichier) if fichier is not None else "", sert=sert)
        return None
    try:
        res = lecteur()
        n = len(res) if hasattr(res, "__len__") else None
        s._note(source, Path(fichier).name, "chargé", n, sert=sert)
        return res
    except Exception as e:                                    # source illisible : notée, jamais bloquante
        s._note(source, Path(fichier).name, "erreur", detail=expliquer(e)[:400], sert=sert)
        s._constat(source, Path(fichier).name, BLOQUANT, expliquer(e)[:400])
        return None


# --------------------------------------------------------------------------- extractions R26
SERT_EXTRACTION = "consommations, FRU rebutées"


def _fenetre(f: Path) -> tuple:
    """Période annoncée par le nom du fichier : (premier jour, dernier jour)."""
    m = re.search(r"(\d{8})_(\d{8})", f.stem)
    try:
        a, b = (pd.Timestamp(datetime.strptime(m.group(i), "%Y%m%d")) for i in (1, 2))
    except (AttributeError, ValueError):
        raise SourceInutilisable("nom de fichier illisible : ERC_R26_extraction_AAAAMMJJ_AAAAMMJJ.xlsx attendu, avec les dates de début et de fin de la période")
    if a > b:
        raise SourceInutilisable(f"le nom du fichier annonce une fin ({b:%d/%m/%Y}) avant le début ({a:%d/%m/%Y})")
    return a, b


def _consommations(s: Sources, f: Path, d: pd.DataFrame, a, b, deja: set) -> pd.DataFrame:
    """Onglet Composants_jour d'un fichier → lignes gardées. Lève SourceInutilisable si l'onglet n'apporte rien de sûr."""
    S, n0 = "Extraction R26", len(d)
    d = _colonnes(d, COLS_EV, s, S, f.name)
    _exiger(d, ["Jour", "Component ITEM", "Qte"], "l'onglet « Composants_jour »")
    if not n0:
        raise SourceInutilisable("onglet « Composants_jour » vide : ce fichier n'apporte aucune consommation et ses jours ne comptent pas comme extraits")
    absentes = [c for c in ("PO", "FRU ITEM", "Component Description") if c not in d.columns]
    consequences = {"PO": "réparations par FRU et maximum par PO non calculables", "FRU ITEM": "pièces non rattachées à un FRU ni à un atelier",
                    "Component Description": "type de pièce et risque matière non reconnus"}
    for c in absentes:
        d[c] = np.nan
        s._constat(S, f.name, A_VERIFIER, f"colonne « {c} » absente de « Composants_jour » : {consequences[c]}")
    d = d.copy()
    d["Jour"] = _dates(d["Jour"]).dt.normalize()
    for c in ("Component ITEM", "FRU ITEM", "PO"):
        d[c] = d[c].map(ref)
    d["Component Description"] = _texte(d["Component Description"])
    d["Qte"] = _num(d["Qte"])
    sans_date, sans_ref, sans_qte = d["Jour"].isna(), d["Component ITEM"].isna(), d["Qte"].isna()
    for masque, quoi in ((sans_date, "sans date lisible dans « Jour »"), (sans_ref & ~sans_date, "sans référence de pièce"),
                         (sans_qte & ~sans_date & ~sans_ref, "à la quantité vide ou illisible")):
        if masque.any():
            s._constat(S, f.name, A_VERIFIER, f"{_pl(masque.sum(), 'ligne')} de consommation {quoi} : écartée{'s' if masque.sum() > 1 else ''}, non comptée{'s' if masque.sum() > 1 else ''}")
    d = d[~(sans_date | sans_ref | sans_qte)]
    hors = ~d["Jour"].between(a, b)
    if hors.any():
        s._constat(S, f.name, A_VERIFIER, f"{_pl(hors.sum(), 'ligne')} datée{'s' if hors.sum() > 1 else ''} hors de la période annoncée par le nom du fichier "
                   f"(du {a:%d/%m/%Y} au {b:%d/%m/%Y}) : écartée{'s' if hors.sum() > 1 else ''} ; contenu du {d['Jour'].min():%d/%m/%Y} au {d['Jour'].max():%d/%m/%Y}")
    d = d[~hors]
    if not len(d):
        raise SourceInutilisable(f"aucune consommation lisible entre le {a:%d/%m/%Y} et le {b:%d/%m/%Y} : le nom du fichier ne correspond pas à son contenu ; "
                                 "ses jours ne comptent pas comme extraits")
    premier, dernier = d["Jour"].min(), d["Jour"].max()
    if (premier - a).days > 7:
        s._constat(S, f.name, A_VERIFIER, f"aucune consommation du {a:%d/%m/%Y} au {premier - pd.Timedelta(days=1):%d/%m/%Y} alors que le nom du fichier annonce ces jours : "
                   "ils comptent comme extraits, avec zéro pièce ; vérifier que l'extraction les couvre")
    if (b - dernier).days > 7:
        s._constat(S, f.name, A_VERIFIER, f"aucune consommation du {dernier + pd.Timedelta(days=1):%d/%m/%Y} au {b:%d/%m/%Y} alors que le nom du fichier annonce ces jours : "
                   "ils comptent comme extraits, avec zéro pièce ; vérifier que l'extraction les couvre")
    communs = d["Jour"].isin(deja)
    if communs.any():
        s._constat(S, f.name, INFORMATION, f"{_pl(communs.sum(), 'ligne')} sur des jours déjà couverts par une extraction plus récente : non reprise{'s' if communs.sum() > 1 else ''} ici")
    d = d[~communs]
    identiques = d.duplicated(COLS_EV, keep="first")
    if identiques.any():
        s._constat(S, f.name, A_VERIFIER, f"{_pl(identiques.sum(), 'ligne')} strictement identique{'s' if identiques.sum() > 1 else ''} à une autre (même jour, PO, FRU, pièce, quantité) : "
                   "gardées et comptées ; à vérifier si l'export les a doublées")
    negatives = d["Qte"] < 0
    if negatives.any():
        s._constat(S, f.name, INFORMATION, f"{_pl(negatives.sum(), 'ligne')} à quantité négative (retours) : comptée{'s' if negatives.sum() > 1 else ''} en déduction")
    return d


def _lire_extractions(s: Sources):
    cfg, S = s.cfg, "Extraction R26"
    fichiers = sorted(cfg.projet.glob(MOTIF_EXTRACTION)) if cfg.projet and Path(cfg.projet).is_dir() else []
    if not fichiers:
        s._note(S, MOTIF_EXTRACTION, "absent", detail="aucune extraction dans le dossier des extractions", sert=SERT_EXTRACTION)
    lisibles = []
    for f in fichiers:
        try:
            lisibles.append((f, *_fenetre(f)))
        except SourceInutilisable as e:
            s._note(S, f.name, "erreur", detail=str(e), sert=SERT_EXTRACTION)
            s._constat(S, f.name, BLOQUANT, str(e))
    # La plus récente d'abord : période qui finit le plus tard, puis qui commence le plus tard, puis nom du fichier.
    lisibles.sort(key=lambda t: (t[2], t[1], t[0].name), reverse=True)
    morceaux, rebuts, couverts, couverts_rebut = [], [], set(), set()
    for f, a, b in lisibles:
        jours = set(pd.date_range(a, b))
        try:
            with pd.ExcelFile(f) as x:
                feuilles = {nom: _onglet(x, nom) for nom in ("Composants_jour", "FRU_rebutees", "FRU_statut_cohorte")}
        except Exception as e:
            s._note(S, f.name, "erreur", detail=expliquer(e)[:400], sert=SERT_EXTRACTION)
            s._constat(S, f.name, BLOQUANT, expliquer(e)[:400])
            continue
        for nom, (d, remarque) in feuilles.items():
            if d is not None and remarque:
                s._constat(S, f.name, INFORMATION, remarque)
        n_lignes, etat, detail = 0, "chargé", f"{a:%Y%m%d} → {b:%Y%m%d}"
        d, remarque = feuilles["Composants_jour"]
        try:
            if d is None:
                raise SourceInutilisable(remarque + " : aucune consommation lue de ce fichier, ses jours ne comptent pas comme extraits")
            d = _consommations(s, f, d, a, b, couverts)
            morceaux.append(d)
            n_lignes = len(d)
            couverts |= jours
        except Exception as e:
            etat = "erreur"
            s._constat(S, f.name, BLOQUANT, expliquer(e)[:400])
        d, remarque = feuilles["FRU_rebutees"]
        if d is None:
            s._constat(S, f.name, A_VERIFIER, remarque + " : les FRU rebutées de cette période ne sont pas datées par ce fichier")
        elif not len(d.columns):
            s._constat(S, f.name, A_VERIFIER, "onglet « FRU_rebutees » vide, sans en-tête : les FRU rebutées de cette période ne sont pas datées par ce fichier")
        else:
            if not len(d):
                s._constat(S, f.name, A_VERIFIER, f"onglet « FRU_rebutees » sans aucune ligne : zéro FRU rebutée du {a:%d/%m/%Y} au {b:%d/%m/%Y} ; à vérifier")
            rebuts.append((f.name, d, jours - couverts_rebut, (a, b)))
            couverts_rebut |= jours
        d, remarque = feuilles["FRU_statut_cohorte"]
        if d is not None and len(d) and not len(s.cohorte):
            d = _colonnes(d, ["FRU ITEM", "Statut", "Unites"], s, S, f.name)
            if "FRU ITEM" in d.columns:
                d = d.copy()
                d["FRU ITEM"] = d["FRU ITEM"].map(ref)
            if "Unites" in d.columns:
                d["Unites"] = _num(d["Unites"])
            s.cohorte = d
        s._note(S, f.name, etat, n_lignes, detail, SERT_EXTRACTION)
    debut, fin = (pd.Timestamp(v) if v else None for v in (cfg.debut, cfg.fin))
    dans_la_fenetre = lambda jours: {j for j in jours if (debut is None or j >= debut) and (fin is None or j < fin)}
    if morceaux:
        ev = pd.concat(morceaux, ignore_index=True)[COLS_EV]
        ev = ev[ev["Jour"].isin(dans_la_fenetre(set(ev["Jour"])))]
        # Ordre fixe, indépendant de l'ordre de lecture des fichiers : deux exécutions donnent les mêmes tables.
        s.ev = ev.sort_values(["Jour", "PO", "FRU ITEM", "Component ITEM"], kind="mergesort", na_position="last").reset_index(drop=True)
    s.couverts = dans_la_fenetre(couverts)
    s.fru_rebutees, s.regle_date_rebut, s.couverts_rebut = _fru_rebutees(rebuts, cfg.col_date_rebut, s)
    s.couverts_rebut = dans_la_fenetre(s.couverts_rebut)
    if len(s.fru_rebutees):
        s.fru_rebutees = s.fru_rebutees[s.fru_rebutees["Date rebut"].isin(s.couverts_rebut)].reset_index(drop=True)


def _colonnes_de_dates(d: pd.DataFrame) -> dict:
    """Colonnes qui portent des dates : type date, ou nom contenant « date » ou « jour » et au moins la moitié des valeurs lisibles."""
    dates = {}
    for c in d.columns:
        if str(c).startswith("_"):
            continue
        if pd.api.types.is_datetime64_any_dtype(d[c]):
            dates[c] = _dates(d[c])
        elif re.search(r"date|jour|scrap|rebut", _cle(c)) and d[c].notna().any():
            lues = _dates(d[c])
            if lues.notna().sum() >= 0.5 * d[c].notna().sum():
                dates[c] = lues
    return dates


def _fru_rebutees(morceaux: list, col_date: str | None, s: Sources | None = None):
    """Onglets FRU_rebutees réunis. Renvoie (lignes, règle de date utilisée, jours couverts).

    morceaux : liste de (nom du fichier, onglet, jours propres au fichier, (premier jour, dernier jour) du fichier),
               le fichier le plus récent d'abord. Un fichier ne fournit que les rebuts datés d'un de ses jours propres :
               sur un jour commun à deux extractions, la plus récente gagne, comme pour les consommations.
    La colonne qui date le rebut n'est pas imposée : `col_date` si elle est donnée ; sinon la colonne de date dont le
    nom contient « scrap » ou « rebut » ; sinon la plus tardive des dates de la ligne. La règle est renvoyée pour
    être affichée et confirmée par le responsable du flux.
    Une ligne vaut une FRU, sauf si une colonne de quantité (Unites, Unités, Qte, Quantity) dit autre chose.
    Les doublons ne sont retirés que si une colonne identifie le FRU (PO ou numéro de série).
    """
    S = "Extraction R26"
    vide = pd.DataFrame(columns=["Date rebut", "FRU", "Unités"])
    dire = (lambda fichier, gravite, texte: s._constat(S, fichier, gravite, texte)) if s is not None else (lambda *a: None)
    if not morceaux:
        return vide, "aucun onglet FRU_rebutees dans les extractions", set()
    attendues = ["PO", "FRU ITEM", "Numero de serie", "Unites"] + ([col_date] if col_date else [])
    parties, propres, bornes = [], {}, {}
    for i, (nom, d, jours, (a, b)) in enumerate(morceaux):
        d = _colonnes(d, attendues, s, S, nom).copy()
        d["_fichier"] = i
        parties.append(d)
        propres[i], bornes[i] = jours, (nom, a, b)
    d = pd.concat(parties, ignore_index=True)
    tous_les_jours = set().union(*propres.values())
    col_fru = next((c for c in ("FRU ITEM", "ITEM", "Item") if c in d), None)
    if col_fru is None:
        regle = "colonne « FRU ITEM » introuvable dans FRU_rebutees : FRU rebutées non datées"
        dire(morceaux[0][0], BLOQUANT, regle + f" ; colonnes présentes : {_liste([c for c in d.columns if c != '_fichier'], 12)}")
        return vide, regle, set()
    dates = _colonnes_de_dates(d)
    if col_date and col_date in d.columns:
        jour, regle = _dates(d[col_date]), f"colonne « {col_date} » (choisie)"
    else:
        demande = f"colonne « {col_date} » (demandée par col_date_rebut) introuvable ; " if col_date else ""
        if demande:
            dire(morceaux[0][0], A_VERIFIER, demande + "la date de rebut est cherchée automatiquement")
        if not dates:
            regle = demande + "aucune colonne de date dans FRU_rebutees : renseigner col_date_rebut"
            dire(morceaux[0][0], BLOQUANT, "aucune colonne de date lisible dans « FRU_rebutees » : les FRU rebutées ne peuvent pas être datées ni suivies par semaine ; "
                 "indiquer la colonne par l'option col_date_rebut")
            return vide, regle, set()
        nommee = next((c for c in dates if re.search(r"scrap|rebut", _cle(c))), None)
        if nommee:
            jour, regle = dates[nommee], demande + f"colonne « {nommee} » (trouvée par son nom)"
        else:
            jour = pd.concat(list(dates.values()), axis=1).max(axis=1)
            regle = demande + "plus tardive des dates de la ligne (" + ", ".join(map(str, dates)) + ") : à confirmer"
    col_q = next((c for c in ("Unites", "Unités", "Qte", "Quantity") if c in d), None)
    out = pd.DataFrame({"Date rebut": pd.Series(jour, index=d.index).dt.normalize(), "FRU": d[col_fru].map(ref), "Unités": 1.0, "_fichier": d["_fichier"]})
    if col_q:
        q = _num(d[col_q])
        if q.isna().any():
            dire(morceaux[0][0], A_VERIFIER, f"{_pl(q.isna().sum(), 'ligne')} de FRU_rebutees à la quantité « {col_q} » vide ou illisible : comptée{'s' if q.isna().sum() > 1 else ''} pour une FRU")
        out["Unités"] = q.fillna(1.0)
    for c in ("PO", "Numero de serie"):
        if c in d:
            out[c] = d[c].map(ref)
    for i, (nom, a, b) in bornes.items():
        m = out["_fichier"].eq(i)
        sans = m & (out["Date rebut"].isna() | out["FRU"].isna())
        if sans.any():
            dire(nom, A_VERIFIER, f"{_pl(sans.sum(), 'ligne')} de FRU_rebutees sans date de rebut ou sans référence de FRU lisible : écartée{'s' if sans.sum() > 1 else ''}, non comptée{'s' if sans.sum() > 1 else ''}")
        hors = m & ~sans & ~out["Date rebut"].between(a, b)
        if hors.any():
            dire(nom, A_VERIFIER, f"{_pl(out.loc[hors, 'Unités'].sum(), 'FRU rebutée', 'FRU rebutées')} datée{'s' if hors.sum() > 1 else ''} hors de la période du fichier "
                 f"(du {a:%d/%m/%Y} au {b:%d/%m/%Y}) : non comptée{'s' if hors.sum() > 1 else ''} ; règle de date : {regle}")
        nulles = m & ~sans & ~hors & (out["Unités"] <= 0)
        if nulles.any():
            dire(nom, A_VERIFIER, f"{_pl(nulles.sum(), 'ligne')} de FRU_rebutees à quantité nulle ou négative : écartée{'s' if nulles.sum() > 1 else ''}")
    out = out[out["Date rebut"].notna() & out["FRU"].notna() & (out["Unités"] > 0)]
    out = out[[j in propres[i] for j, i in zip(out["Date rebut"], out["_fichier"])]]
    cles = [c for c in ("PO", "Numero de serie") if c in out and out[c].notna().any()]
    if cles:                                                  # un même FRU (PO, numéro de série) ne compte qu'une fois
        double = out.duplicated(cles + ["FRU"], keep="first") & out[cles].notna().all(axis=1)
        if double.any():
            dire(morceaux[0][0], INFORMATION, f"{_pl(double.sum(), 'ligne')} de FRU_rebutees en double (même {', '.join(cles)} et même FRU) : comptée{'s' if double.sum() > 1 else ''} une seule fois")
        out = out[~double]
    else:
        double = out.duplicated(["Date rebut", "FRU", "Unités", "_fichier"], keep="first")
        if double.any():
            dire(morceaux[0][0], A_VERIFIER, f"{_pl(double.sum(), 'ligne')} de FRU_rebutees identique{'s' if double.sum() > 1 else ''} à une autre, sans PO ni numéro de série pour les distinguer : "
                 "gardées et comptées ; à vérifier si l'export les a doublées")
    out = out.drop(columns="_fichier").sort_values(["Date rebut", "FRU"] + cles, kind="mergesort").reset_index(drop=True)
    return out, regle, tous_les_jours


# --------------------------------------------------------------------------- fiabilité (fichier volumineux, cache)
def _lire_xlsb(fichier: Path, feuille: str, colonne_cle: str, garder: set) -> pd.DataFrame:
    from pyxlsb import open_workbook
    lignes, entete = [], None
    with open_workbook(str(fichier)) as wb:
        with wb.get_sheet(feuille) as sh:
            for row in sh.rows():
                v = [c.v for c in row]
                if entete is None:
                    if colonne_cle in v:
                        entete = v
                    continue
                d = dict(zip(entete, v))
                if any(base_ref(ref(d.get(c))) in garder for c in entete if c and str(c).endswith(("part_no", "PN", "UPN"))):
                    lignes.append(d)
    return pd.DataFrame(lignes)


def _lire_fiabilite(s: Sources):
    cfg = s.cfg
    d_sql = cfg.projet / "Extraction_R26"
    cache, cache_refs = d_sql / "fiabilite_ELF_references_ERC.csv", d_sql / "fiabilite_ELF_references_ERC.refs.txt"
    sert = "défaillances précoces par référence"
    nos_refs = {base_ref(r) for r in set(s.ev["Component ITEM"].dropna()) | set(s.ev["FRU ITEM"].dropna()) | set(s.classification.index)}
    try:
        deja = set(cache_refs.read_text(encoding="utf-8").split()) if cache_refs.is_file() else None
    except (OSError, UnicodeError):
        deja = None
    xlsb = cfg.racine / F_FIAB if cfg.racine else None
    a_jour = cache.is_file() and (deja is None or nos_refs <= deja)
    elf = None
    if cache.is_file() and (a_jour or xlsb is None or not xlsb.is_file()):
        def lire_cache():
            e = _csv(cache)
            _note_csv(s, "Fiabilité (cache)", cache.name, e)
            e = _colonnes(e, ["replacement_part_no", "elf_days"], s, "Fiabilité (cache)", cache.name)
            _exiger(e, ["replacement_part_no", "elf_days"])
            return e
        elf = _essayer(s, "Fiabilité (cache)", cache, sert, lire_cache)
        if elf is not None and not a_jour:
            s.etat[-1]["Détail"] = "cache antérieur aux dernières références : le fichier .xlsb est absent, cache utilisé tel quel"
    elif xlsb is not None and xlsb.is_file():
        def lire():
            e = _lire_xlsb(xlsb, "Parts from ELF (2022, 23)", "failed_part_no", nos_refs)
            try:                                              # seul fichier écrit du côté des sources : le cache documenté
                d_sql.mkdir(parents=True, exist_ok=True)
                e.to_csv(cache, sep=";", index=False, encoding="utf-8-sig")
                cache_refs.write_text(" ".join(sorted(nos_refs)), encoding="utf-8")
            except OSError as err:
                s._constat("Fiabilité (.xlsb, première lecture longue)", xlsb.name, A_VERIFIER,
                           f"cache de fiabilité non écrit ({expliquer(err)}) : la lecture longue du fichier .xlsb sera refaite à chaque exécution")
            _exiger(e, ["replacement_part_no", "elf_days"])
            return e
        elf = _essayer(s, "Fiabilité (.xlsb, première lecture longue)", xlsb, sert, lire)
    else:
        s._note("Fiabilité", F_FIAB, "absent", detail="attendu dans le dossier des référentiels", sert=sert)
    if elf is not None:
        s.elf = elf
    f = d_sql / "poses_2022_2023_par_reference.csv"

    def lire_poses():
        p = _csv(f)
        _note_csv(s, "Pièces posées 2022-2023", f.name, p)
        p = _colonnes(p, ["Référence", "Origine", "Pièces posées"], s, "Pièces posées 2022-2023", f.name)
        _exiger(p, ["Référence", "Origine", "Pièces posées"])
        p["Référence"] = p["Référence"].map(lambda r: base_ref(ref(r)) if not pd.isna(ref(r)) else np.nan)
        p["Pièces posées"] = _num(p["Pièces posées"])
        illisibles = p["Référence"].isna() | p["Origine"].isna() | p["Pièces posées"].isna() | (p["Pièces posées"] < 0)
        if illisibles.any():
            s._constat("Pièces posées 2022-2023", f.name, A_VERIFIER, f"{_pl(illisibles.sum(), 'ligne')} sans référence, sans origine ou au nombre de pièces illisible : écartée{'s' if illisibles.sum() > 1 else ''}")
        p = p[~illisibles]
        return p["Pièces posées"].groupby([p["Référence"], p["Origine"].astype(str).str.strip()]).sum()
    s.poses = _essayer(s, "Pièces posées 2022-2023", f, "dénominateur du taux de défaillance", lire_poses)


# --------------------------------------------------------------------------- référentiels
def _lire_fru_info(s: Sources):
    r, S = s.cfg.racine, "FRU_info"
    f = r / F_FRU if r else None

    def lire():
        with pd.ExcelFile(f) as x:
            fi = x.parse(x.sheet_names[0])
        fi = _colonnes(fi, ["Item", "workshop", "category"], s, S, f.name)
        _exiger(fi, ["Item"])
        fi["Item"] = fi["Item"].map(ref)
        fi = _doublons(s, S, f.name, fi.dropna(subset=["Item"]), "Item", ["workshop", "category"]).set_index("Item")
        for c, quoi in (("workshop", "aucun FRU n'est rattaché à un atelier"), ("category", "famille des FRU inconnue")):
            if c not in fi.columns:
                s._constat(S, f.name, A_VERIFIER, f"colonne « {c} » absente : {quoi}")
        prioritaires = {_cle(a): a for a in s.cfg.ateliers_prioritaires}
        if "workshop" in fi.columns:                          # « mr » ou « MR  » : le même atelier que « MR »
            atelier = _texte(fi["workshop"]).dropna()
            s.atelier_fru = {k: prioritaires.get(_cle(v), v) for k, v in atelier.items()}
        if "category" in fi.columns:
            s.famille_fru = _texte(fi["category"]).dropna().to_dict()
        return fi
    _essayer(s, S, f, "atelier et famille de chaque FRU", lire)


def _lire_classification(s: Sources):
    p = s.cfg.projet
    S = "Classification matières"
    f = p / "Classification_matieres" / "ERC_Classification_Cartes_resultats.xlsx" if p else None

    def lire():
        cl = _lire_onglet(s, S, f, "Classification", ["Référence"])
        cl = _colonnes(cl, list(s.classification.columns), s, S, f.name)
        cl["Référence"] = cl["Référence"].map(ref)
        cl = _doublons(s, S, f.name, cl.dropna(subset=["Référence"]), "Référence", ["Catégorie proposée", "Benne", "Poids unitaire (kg)"]).set_index("Référence")
        absentes = [c for c in s.classification.columns if c not in cl.columns]
        for c in absentes:
            cl[c] = np.nan
        importantes = [c for c in absentes if c in ("Catégorie proposée", "Benne", "Poids unitaire (kg)")]
        if importantes:
            s._constat(S, f.name, A_VERIFIER, f"{_pl(len(importantes), 'colonne')} absente{'s' if len(importantes) > 1 else ''} : "
                       + ", ".join(f"« {c} »" for c in importantes) + " ; type de déchet, benne ou poids inconnus pour toutes les pièces")
        for c in ("Catégorie proposée", "Benne", "Source poids"):
            cl[c] = _texte(cl[c])
        brut = cl["Poids unitaire (kg)"]
        cl["Poids unitaire (kg)"] = _num(brut)
        illisibles = int((cl["Poids unitaire (kg)"].isna() & brut.notna()).sum())
        nuls = cl["Poids unitaire (kg)"].le(0)
        if illisibles:
            s._constat(S, f.name, A_VERIFIER, f"{_pl(illisibles, 'poids unitaire', 'poids unitaires')} illisible{'s' if illisibles > 1 else ''} (texte dans la cellule) : traité{'s' if illisibles > 1 else ''} comme inconnu{'s' if illisibles > 1 else ''}")
        if nuls.any():
            s._constat(S, f.name, A_VERIFIER, f"{_pl(nuls.sum(), 'poids unitaire', 'poids unitaires')} nul{'s' if nuls.sum() > 1 else ''} ou négatif{'s' if nuls.sum() > 1 else ''} : "
                       f"traité{'s' if nuls.sum() > 1 else ''} comme inconnu{'s' if nuls.sum() > 1 else ''} ({_liste(cl.index[nuls])})")
        cl.loc[nuls, "Poids unitaire (kg)"] = np.nan         # un poids nul est un poids inconnu
        s.classification = cl
        return cl
    _essayer(s, S, f, "type de déchet, benne, poids unitaire", lire)
    S2 = "Référentiel des grades"
    f2 = p / "Classification_matieres" / "ERC_Referentiel_Grades.xlsx" if p else None

    def lire_grades():
        gr = _lire_onglet(s, S2, f2, "Grades", ["Catégorie", "Prix recycleur (€/kg)"])
        gr["Catégorie"] = _texte(gr["Catégorie"])
        brut = gr["Prix recycleur (€/kg)"]
        gr["Prix recycleur (€/kg)"] = _num(brut)
        illisibles = int((gr["Prix recycleur (€/kg)"].isna() & brut.notna()).sum())
        if illisibles:
            s._constat(S2, f2.name, A_VERIFIER, f"{_pl(illisibles, 'prix')} illisible{'s' if illisibles > 1 else ''} (texte dans la cellule) : traité{'s' if illisibles > 1 else ''} comme inconnu{'s' if illisibles > 1 else ''}")
        gr = _doublons(s, S2, f2.name, gr.dropna(subset=["Catégorie", "Prix recycleur (€/kg)"]), "Catégorie", ["Prix recycleur (€/kg)"])
        s.prix_recycleur = gr.set_index("Catégorie")["Prix recycleur (€/kg)"].astype(float)
        return gr
    _essayer(s, S2, f2, "prix recycleur par catégorie", lire_grades)


def _lire_valorisation(s: Sources) -> pd.Series:
    """QueryComponents et QueryERC_Flow_In_Out. Renvoie le MMICV de repli (valeur totale ÷ quantité totale)."""
    r = s.cfg.racine
    f = r / F_VALO if r else None
    S = "QueryComponents"
    repli = [pd.Series(dtype=float)]

    def lire_qc():
        qc = _lire_onglet(s, S, f, "QueryComponents", ["FRU ITEM", "Component ITEM"])
        qc = _colonnes(qc, list(s.qc.columns), s, S, f.name)
        for c in ("FRU ITEM", "Component ITEM"):
            qc[c] = qc[c].map(ref)
        qc = qc[qc["FRU ITEM"].notna() & qc["Component ITEM"].notna() & qc["FRU ITEM"].astype(str).ne("TOTAL")].copy()
        absentes = [c for c in s.qc.columns if c not in qc.columns]
        for c in absentes:
            qc[c] = np.nan
        if {"Total Consumption Quantity", "Total value"} & set(absentes):
            s._constat(S, f.name, A_VERIFIER, "colonnes « Total Consumption Quantity » ou « Total value » absentes : pas de MMICV de repli")
        for c in ("Total Consumption Quantity", "Total value"):
            qc[c] = _num(qc[c])
        for c in ("FRU Description", "Component Description"):
            qc[c] = _texte(qc[c])
        s.qc = qc.reset_index(drop=True)
        v = qc.groupby("Component ITEM").agg(v=("Total value", lambda x: x.sum(min_count=1)), q=("Total Consumption Quantity", lambda x: x.sum(min_count=1)))
        m = (v["v"] / v["q"].where(v["q"] > 0)).dropna()
        repli[0] = m[m.gt(0)]
        s.desc_fru = qc.dropna(subset=["FRU Description"]).drop_duplicates("FRU ITEM").set_index("FRU ITEM")["FRU Description"]
        return qc
    _essayer(s, S, f, "nomenclature de consommation, MMICV de repli", lire_qc)
    S2 = "QueryERC_Flow_In_Out"

    def lire_flux():
        fx = _lire_onglet(s, S2, f, "QueryERC_Flow_In_Out", ["ITEM"])
        fx = _colonnes(fx, ["Net weight", "ITEM Description"], s, S2, f.name)
        fx["ITEM"] = fx["ITEM"].map(ref)
        fx = _doublons(s, S2, f.name, fx.dropna(subset=["ITEM"]), "ITEM", ["Net weight"]).set_index("ITEM")
        if "Net weight" in fx.columns:
            w = _num(fx["Net weight"])
            illisibles, nuls = int((w.isna() & fx["Net weight"].notna()).sum()), w.le(0)
            if illisibles:
                s._constat(S2, f.name, A_VERIFIER, f"{_pl(illisibles, 'poids de FRU', 'poids de FRU')} illisible{'s' if illisibles > 1 else ''} : traité{'s' if illisibles > 1 else ''} comme inconnu{'s' if illisibles > 1 else ''}")
            if nuls.any():
                s._constat(S2, f.name, A_VERIFIER, f"{_pl(nuls.sum(), 'poids de FRU', 'poids de FRU')} nul{'s' if nuls.sum() > 1 else ''} ou négatif{'s' if nuls.sum() > 1 else ''} : "
                           f"traité{'s' if nuls.sum() > 1 else ''} comme inconnu{'s' if nuls.sum() > 1 else ''} ({_liste(w.index[nuls])})")
            s.poids_fru = w[w.gt(0)]
        else:
            s._constat(S2, f.name, A_VERIFIER, "colonne « Net weight » absente : poids des FRU inconnu")
        if "ITEM Description" in fx.columns:
            s.desc_fru = _texte(fx["ITEM Description"]).dropna().combine_first(s.desc_fru)
        return fx
    _essayer(s, S2, f, "poids et description des FRU", lire_flux)
    return repli[0]


def _lire_mmicv(s: Sources, repli: pd.Series):
    """MMICV : fiche article d'abord, QueryComponents sinon ; une valeur nulle ou négative est une valeur absente."""
    p, S = s.cfg.projet, "Fiche article (vwAllItems)"
    f = p / "Extraction_R26" / "poids_items_vwAllItems.csv" if p else None
    mm = [pd.Series(dtype=float)]

    def lire():
        pi = _csv(f)
        _note_csv(s, S, f.name, pi)
        pi = _colonnes(pi, ["ITEM", "MMICV USD"], s, S, f.name)
        _exiger(pi, ["ITEM", "MMICV USD"])
        pi["ITEM"] = pi["ITEM"].map(ref)
        pi = pi.dropna(subset=["ITEM"]).copy()
        brut = pi["MMICV USD"]
        pi["MMICV USD"] = _num(brut)
        illisibles, nuls, negatifs = int((pi["MMICV USD"].isna() & brut.notna()).sum()), pi["MMICV USD"].eq(0), pi["MMICV USD"].lt(0)
        for n, quoi in ((illisibles, "illisible (texte dans la cellule)"), (int(nuls.sum()), "nul"), (int(negatifs.sum()), "négatif")):
            if n:
                s._constat(S, f.name, A_VERIFIER if quoi != "nul" else INFORMATION,
                           f"{_pl(n, 'référence')} au MMICV {quoi} : valeur traitée comme inconnue (MMICV de repli de QueryComponents s'il existe)")
        pi = _doublons(s, S, f.name, pi.sort_values("MMICV USD", key=lambda x: x.isna(), kind="mergesort"), "ITEM", ["MMICV USD"])
        m = pi.set_index("ITEM")["MMICV USD"]
        mm[0] = m[m.gt(0)].sort_index()
        return pi
    _essayer(s, S, f, "MMICV unitaire (coût standard)", lire)
    s.mmicv = mm[0].combine_first(repli).astype(float)
    s.mmicv_source = pd.Series(np.where(s.mmicv.index.isin(mm[0].index), "fiche article", "QueryComponents"), index=s.mmicv.index, dtype=object)


# --------------------------------------------------------------------------- terrain : pesées et audit
def _lire_pesees(s: Sources):
    p, S = s.cfg.projet, "Pesées hebdomadaires"
    f = p / "Acquisition" / "pesees_hebdo.csv" if p else None

    def lire():
        pe = _csv(f)
        _note_csv(s, S, f.name, pe)
        attendues = ["Semaine", "Flux", "Masse mesurée (kg)"]
        pe = _colonnes(pe, attendues + ["Incertitude mesure (kg)", "Périmètre", "Commentaire", "Cause constatée"], s, S, f.name)
        _exiger(pe, attendues)
        n0 = len(pe)
        pe["Semaine"] = _dates(pe["Semaine"])
        pe["Flux"] = _texte(pe["Flux"])
        pe["Masse mesurée (kg)"] = _num(pe["Masse mesurée (kg)"]).values
        if "Incertitude mesure (kg)" in pe:
            brut = pe["Incertitude mesure (kg)"]
            pe["Incertitude mesure (kg)"] = _num(brut).values
            n = int((pe["Incertitude mesure (kg)"].isna() & brut.notna()).sum())
            if n:
                s._constat(S, f.name, A_VERIFIER, f"{_pl(n, 'incertitude')} de mesure illisible{'s' if n > 1 else ''} : traitée{'s' if n > 1 else ''} comme inconnue{'s' if n > 1 else ''}")
        if "Cause constatée" not in pe:                           # colonne facultative, saisie par l'atelier après chaque pesée
            pe["Cause constatée"] = None
        for masque, quoi in ((pe["Semaine"].isna(), "sans date de semaine lisible (JJ/MM/AAAA attendu)"), (pe["Flux"].isna() & pe["Semaine"].notna(), "sans nom de flux"),
                             (pe["Masse mesurée (kg)"].isna() & pe["Semaine"].notna() & pe["Flux"].notna(), "à la masse vide ou illisible"),
                             (pe["Masse mesurée (kg)"].lt(0), "à la masse négative")):
            if masque.any():
                s._constat(S, f.name, A_VERIFIER, f"{_pl(masque.sum(), 'pesée')} {quoi} : écartée{'s' if masque.sum() > 1 else ''}")
        pe = pe[pe["Semaine"].notna() & pe["Flux"].notna() & pe["Masse mesurée (kg)"].ge(0)].copy()
        # Nom de flux : rapproché des bennes (ou types de déchet) du classement matière, sans casse ni accent.
        col = "Catégorie proposée" if s.cfg.par_flux == "Type de déchet" else s.cfg.par_flux
        connus = sorted({str(v) for v in s.classification[col].dropna()} | {"(non classé)"}) if col in s.classification else []
        par_cle = {_cle(v): v for v in connus}
        pe["Flux"] = pe["Flux"].map(lambda v: par_cle.get(_cle(v), v))
        inconnus = sorted(set(pe["Flux"]) - set(connus))
        if inconnus and connus:
            s._constat(S, f.name, A_VERIFIER, f"flux inconnu{'s' if len(inconnus) > 1 else ''} du classement matière : {_liste(inconnus)} ; "
                       f"ces pesées ne sont comparées à aucune estimation (flux connus : {_liste(connus, 10)})")
        if s.couverts and len(pe):
            lundi = semaine(pe["Semaine"])
            hors = ~lundi.isin(set(semaine(pd.Series(sorted(s.couverts)))))
            if hors.any():
                s._constat(S, f.name, INFORMATION, f"{_pl(hors.sum(), 'pesée')} sur une semaine sans jour extrait : gardée{'s' if hors.sum() > 1 else ''}, sans estimation en face")
        s.pesees = pe.reset_index(drop=True)
        if n0 and not len(pe):
            raise SourceInutilisable("aucune pesée lisible : voir les contrôles des sources")
        return pe
    _essayer(s, S, f, "masse mesurée par semaine et par flux", lire)


def _lire_audit(s: Sources):
    p, S = s.cfg.projet, "Audit de démontage"
    f = p / "Acquisition" / "audit_demontage.csv" if p else None

    def lire():
        au = _csv(f)
        _note_csv(s, S, f.name, au)
        attendues = list(Sources.__dataclass_fields__["audit"].default_factory().columns)
        au = _colonnes(au, attendues, s, S, f.name)
        _exiger(au, attendues)
        n0 = len(au)
        au["Date"] = _dates(au["Date"])
        for c in ("Pièces testées", "Pièces bonnes"):
            au[c] = _num(au[c]).values
        for c in ("Type de FRU", "Pièce"):
            au[c] = au[c].map(ref)
        t, b = au["Pièces testées"], au["Pièces bonnes"]
        vus = pd.Series(False, index=au.index)
        for masque, quoi in ((au["Date"].isna(), "sans date lisible (JJ/MM/AAAA attendu)"), (au["Type de FRU"].isna() | au["Pièce"].isna(), "sans type de FRU ou sans pièce"),
                             (t.isna() | b.isna(), "au nombre de pièces vide ou illisible"), (t.le(0), "sans pièce testée (zéro ou négatif)"),
                             (b.lt(0), "au nombre de pièces bonnes négatif"), (b.gt(t), "avec plus de pièces bonnes que de pièces testées")):
            m = masque & ~vus
            if m.any():
                s._constat(S, f.name, A_VERIFIER, f"{_pl(m.sum(), 'lot')} d'audit {quoi} : écarté{'s' if m.sum() > 1 else ''}, non appris par le modèle de Rex")
            vus |= masque
        au = au[~vus].copy()
        fru_connus = set(s.ev["FRU ITEM"].dropna()) | set(s.fru_rebutees["FRU"].dropna()) | set(s.qc["FRU ITEM"].dropna()) | set(s.poids_fru.index)
        pieces_connues = set(s.ev["Component ITEM"].dropna()) | set(s.qc["Component ITEM"].dropna()) | set(s.classification.index)
        if fru_connus or pieces_connues:
            etrangers = ~au["Type de FRU"].isin(fru_connus) | ~au["Pièce"].isin(pieces_connues)
            if etrangers.any():
                couples = sorted({f"{a} / {b}" for a, b in zip(au.loc[etrangers, "Type de FRU"], au.loc[etrangers, "Pièce"])})
                s._constat(S, f.name, A_VERIFIER, f"{_pl(etrangers.sum(), 'lot')} d'audit sur un FRU ou une pièce absents des autres sources ({_liste(couples)}) : "
                           "gardés, mais à vérifier (faute de frappe dans la référence ?)")
        doubles = au.duplicated(attendues, keep="first")
        if doubles.any():
            s._constat(S, f.name, A_VERIFIER, f"{_pl(doubles.sum(), 'lot')} d'audit strictement identique{'s' if doubles.sum() > 1 else ''} à un autre : gardé{'s' if doubles.sum() > 1 else ''} ; à vérifier (double saisie ?)")
        s.audit = au.sort_values(["Date", "Type de FRU", "Pièce"], kind="mergesort").reset_index(drop=True)
        if n0 and not len(au):
            raise SourceInutilisable("aucun lot d'audit utilisable : voir les contrôles des sources")
        return au
    _essayer(s, S, f, "pièces testées et pièces bonnes (modèle de Rex)", lire)


def _controles_croises(s: Sources):
    """Ce qui manque quand on rapproche les sources : constats donnés une fois, avec le nombre de références."""
    S, F = "Rapprochement des sources", ""
    if not len(s.ev):
        s._constat("Extraction R26", "", BLOQUANT, "aucune ligne de consommation lue : classements, flux et a priori du modèle de Rex restent vides")
        return
    conso = s.ev.groupby("Component ITEM")["Qte"].sum()
    total = float(conso.sum())
    part = lambda refs: f"{float(conso.reindex(list(refs)).sum()) / total:.0%} des pièces consommées" if total > 0 else "part inconnue"
    frus = sorted(set(s.ev["FRU ITEM"].dropna()) | set(s.fru_rebutees["FRU"].dropna() if len(s.fru_rebutees) else []))
    sans_atelier = [f for f in frus if f not in s.atelier_fru]
    if sans_atelier:
        s._constat(S, F, A_VERIFIER, f"{_pl(len(sans_atelier), 'FRU', 'FRU')} sans atelier dans FRU_info ({_liste(sans_atelier)}) : rangé{'s' if len(sans_atelier) > 1 else ''} dans « (non rattaché) » ; "
                   "à rattacher dans l'onglet Ateliers du classeur de paramètres")
    for manquants, quoi, effet in (
            ([r for r in conso.index if r not in s.classification.index], "absente{s} du classement matière", "type de déchet, benne et poids inconnus"),
            ([r for r in conso.index if r in s.classification.index and pd.isna(s.classification.at[r, "Poids unitaire (kg)"])], "classée{s} mais sans poids unitaire", "masse estimée incomplète"),
            ([r for r in conso.index if r not in s.mmicv.index], "sans MMICV", "valeur inconnue, non comptée dans les totaux")):
        if manquants:
            p = "s" if len(manquants) > 1 else ""
            s._constat(S, F, A_VERIFIER, f"{_pl(len(manquants), 'pièce consommée', 'pièces consommées')} {quoi.format(s=p)} ({part(manquants)} ; {_liste(manquants)}) : {effet}")
    if len(s.fru_rebutees):
        sans_poids = sorted(set(s.fru_rebutees["FRU"]) - set(s.poids_fru.index))
        if sans_poids:
            s._constat(S, F, A_VERIFIER, f"{_pl(len(sans_poids), 'FRU rebuté', 'FRU rebutés')} sans poids ({_liste(sans_poids)}) : masse rebutée inconnue pour ce{'s' if len(sans_poids) > 1 else ''} type{'s' if len(sans_poids) > 1 else ''}")
    sans_prix = sorted({str(c) for c in s.classification["Catégorie proposée"].dropna()} - set(s.prix_recycleur.index)) if len(s.classification) else []
    if sans_prix and len(s.prix_recycleur):
        s._constat(S, F, A_VERIFIER, f"{_pl(len(sans_prix), 'catégorie')} du classement matière sans prix dans le référentiel des grades ({_liste(sans_prix)}) : prix du recycleur inconnu pour ces pièces")


# --------------------------------------------------------------------------- lecture complète
def charger(cfg: Config) -> Sources:
    s = Sources(cfg)
    repli = [pd.Series(dtype=float)]

    def valorisation():
        repli[0] = _lire_valorisation(s)

    def descriptions():
        # Descriptions des pièces, atelier et famille sur chaque consommation
        d1 = s.ev.dropna(subset=["Component Description"]).drop_duplicates("Component ITEM").set_index("Component ITEM")["Component Description"]
        d2 = s.qc.dropna(subset=["Component Description"]).drop_duplicates("Component ITEM").set_index("Component ITEM")["Component Description"]
        s.desc_piece = d1.astype(object).combine_first(d2.astype(object))
        s.ev["Atelier"] = s.ev["FRU ITEM"].map(s.atelier_fru).fillna("(non rattaché)")
        s.ev["Famille"] = s.ev["FRU ITEM"].map(s.famille_fru).fillna("")

    # Chaque lecture est protégée : une source défectueuse est notée et n'empêche jamais de lire les autres.
    for nom, lecture in (("Extraction R26", lambda: _lire_extractions(s)), ("FRU_info", lambda: _lire_fru_info(s)),
                         ("Classification matières", lambda: _lire_classification(s)), ("QueryComponents", valorisation),
                         ("Fiche article (vwAllItems)", lambda: _lire_mmicv(s, repli[0])), ("Descriptions", descriptions),
                         ("Fiabilité", lambda: _lire_fiabilite(s)), ("Pesées hebdomadaires", lambda: _lire_pesees(s)),
                         ("Audit de démontage", lambda: _lire_audit(s)), ("Rapprochement des sources", lambda: _controles_croises(s))):
        try:
            lecture()
        except Exception as e:
            s._note(nom, "", "erreur", detail=expliquer(e)[:400], sert="")
            s._constat(nom, "", BLOQUANT, expliquer(e)[:400])
    return s
