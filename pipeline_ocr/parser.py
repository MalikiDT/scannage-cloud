import re
from typing import Optional

# ─── Patterns numéro B/L ─────────────────────────────────────────────────────
#
# Confusions OCR observées sur les documents réels :
#   "B/L No."     → lu "BI. No."      (slash absent, L/I confondus)
#   "S328990172"  → lu "$328990172"   (S confondu avec $)
#   "Booking No." → présent sur les BL Grimaldi (non couvert avant)
#   "Num B/L"     → en-tête de colonne de tableau ; la valeur est sur la
#                   ligne suivante, pas inline → pattern multilignes nécessaire

BL_LABELS = [
    r"(?:Booking|Ref\.?)\s+No\.?\s*[:\-]?\s*",          # Booking No. / Ref. No.
    r"COREOR\s+Vehicule\s*[:\-]?\s*",                    # BAD Dakar Terminal
    r"Num[eé]ro\s+de\s+B/?L\s*[:\-]?\s*",               # français
    r"\bCN\s*[:\-]?\s*",                                 # abréviation
    r"B[/I1]?\.?\s*L\s*No\.?\s*[:\-]?\s*",              # B/L | BL | BI. No.
    r"BI\.\s*No\.?\s*[:\-]?\s*",                         # BI. No. (confusion slash→I)
    r"Num\s+B/?L\s*[:\-]?\s*",                           # inline
    r"Marks\s+and\s+Nos\.?\s*[:\-]?\s*",                 # colonne BL
]

# Tolère un $ initial (S confondu avec $ par Tesseract)
BL_VALUE = r"\$?([A-Z0-9]{8,25})"
BL_PATTERNS = [re.compile(label + BL_VALUE, re.IGNORECASE) for label in BL_LABELS]

# Pattern tableau : "Num B/L" en tête, valeur N lignes plus bas
BL_TABLE_PATTERN = re.compile(
    r"Num\s+B/?L.*?(\b[A-Z]\d{8,}\b)",
    re.IGNORECASE | re.DOTALL,
)

# ─── Patterns numéro de déclaration ──────────────────────────────────────────
#
# Format attendu : "2026 18N 20055"
#
# Confusions OCR sur les cases de formulaire douanier :
#   "2026"  → "(202: 6)"   (case bornée, le bord devient ":" + espace)
#   "18N"   → "(aan }"     (1→a, 8→a, bords de case → accolades)
#   "20055" → "(20055 )"   (relativement propre)
#
# Stratégie en 3 passes :
#   1. Strict     — texte propre / PDF natif
#   2. Souple     — tolère les séparateurs OCR entre les 3 tokens
#   3. Reconstruct— quand les cases sont trop corrompues :
#                   * numéro après le label "déclaration"
#                   * bureau depuis "Bureau <mot> 18N"
#                   * année depuis n'importe quel "20XX" dans le texte

DECL_STRICT = re.compile(
    r"\b(20\d{2})\s+(\d{2}[A-Z])\s+(\d{4,6})\b",
    re.MULTILINE,
)

_SEP = r"[\s\(\)\{\}\[\]|:,.]*"
DECL_SOUPLE = re.compile(
    r"(20\d{2})" + _SEP + r"(\d{2}[A-Z])" + _SEP + r"(\d{4,6})",
    re.IGNORECASE,
)

# ─── Patterns faux positifs BL ────────────────────────────────────────────────

FAUX_POSITIFS_BL = {
    "REPUBLIQUE", "SENEGAL", "MINISTERE", "TRANSITAIRE",
    "CONTAINER", "CONTAINERS", "LIVORNO", "GRIMALDI",
}

# ─── Patterns numéro de facture ───────────────────────────────────────────────

FACTURE_PATTERNS = [
    re.compile(r"Facture\s+N[°o]\.?\s*[:\-]?\s*(\d{5,10})", re.IGNORECASE),
    re.compile(r"FACTURE\s+N[°o]\.?\s*[:\-]?\s*(\d{5,10})", re.IGNORECASE),
]

# ─── Fonctions d'extraction ───────────────────────────────────────────────────

def _normalize_bl(raw: str) -> str:
    """Corrige $ → S en début de numéro B/L (confusion OCR courante)."""
    raw = raw.strip()
    if raw.startswith("$"):
        raw = "S" + raw[1:]
    return raw.upper()


def extract_numero_bl(text: str) -> Optional[str]:
    # 1. Patterns contextuels (label + valeur inline)
    for pattern in BL_PATTERNS:
        match = pattern.search(text)
        if match:
            return _normalize_bl(match.group(1))

    # 2. Pattern tableau (valeur sur ligne suivante)
    match = BL_TABLE_PATTERN.search(text)
    if match:
        return _normalize_bl(match.group(1))

    # 3. Fallback : suite alphanumérique commençant par une lettre
    fallback = re.search(r"\b[A-Z]\d{8,20}\b", text)
    if fallback:
        candidate = fallback.group(0).upper()
        if candidate not in FAUX_POSITIFS_BL:
            return candidate

    return None


def extract_numero_declaration(text: str) -> Optional[str]:
    """
    Cherche un numéro de déclaration au format : AAAA XXN NNNNN
    Exemples : 2026 18N 20055 / 2025 15T 32563

    3 passes pour gérer les degrés de corruption OCR.
    """
    # Passe 1 — texte propre (PDF natif ou OCR de qualité)
    m = DECL_STRICT.search(text)
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}"

    # Passe 2 — séparateurs parasites entre les 3 tokens (légère corruption)
    m = DECL_SOUPLE.search(text)
    if m:
        # Vérifier qu'on n'a pas matché le Manifeste/Sommier à la place
        # (même format, mais précédé par le mot "Manifeste" ou "Sommier")
        start = m.start()
        prefix = text[max(0, start - 30):start]
        if not re.search(r"Manifeste|Sommier", prefix, re.IGNORECASE):
            return f"{m.group(1)} {m.group(2)} {m.group(3)}"

    # Passe 3 — reconstruction depuis 3 sources indépendantes
    # (cas des cases de formulaire très corrompues par Tesseract)
    bureau_m = re.search(r"Bureau\s+\w+\s+(\d{2}[A-Z])", text, re.IGNORECASE)
    label_m  = re.search(r"d.claration", text, re.IGNORECASE)
    year_m   = re.search(r"\b(20\d{2})\b", text)

    if bureau_m and label_m and year_m:
        bureau  = bureau_m.group(1)
        annee   = year_m.group(1)
        context = text[label_m.end() : label_m.end() + 200]
        # Premier nombre ≥ 4 chiffres dans le contexte du label, hors année
        candidats = [n for n in re.findall(r"\b(\d{4,6})\b", context) if n != annee]
        if candidats:
            return f"{annee} {bureau} {candidats[0]}"

    return None


def extract_numero_facture(text: str) -> Optional[str]:
    """Cherche le numéro de facture (type FACTURE uniquement)."""
    for pattern in FACTURE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


# ─── Dispatcher par type de document ─────────────────────────────────────────

DOCUMENT_FIELDS = {
    "BAD_DAKAR_TERMINAL": ["numero_bl", "numero_declaration"],
    "BAD_SHIPPING":       ["numero_bl"],
    "DECLARATION":        ["numero_bl", "numero_declaration"],
    "BILL_OF_LADING":     ["numero_bl"],
    "PROCURATION":        ["numero_bl"],
    "CNI_TRANSITAIRE":    [],
    "CNI_CLIENT":         [],
    "FACTURE":            ["numero_bl", "numero_facture"],
}

EXTRACTORS = {
    "numero_bl":          extract_numero_bl,
    "numero_declaration": extract_numero_declaration,
    "numero_facture":     extract_numero_facture,
}


def parse_document(full_text: str, type_document: str) -> dict:
    """
    Lance uniquement les extracteurs pertinents pour ce type de document.
    Retourne un dict des champs trouvés avec leur valeur (ou None si absent).
    """
    champs_cibles = DOCUMENT_FIELDS.get(type_document, [])
    resultats = {}
    for champ in champs_cibles:
        extracteur = EXTRACTORS.get(champ)
        if extracteur:
            resultats[champ] = extracteur(full_text)
    return resultats