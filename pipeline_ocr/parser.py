import re
from typing import Optional

# ─── Patterns de recherche ───────────────────────────────────────────────────

# Numéro B/L : suite alphanumérique de 10-15 caractères
# Précédé par : COREOR Vehicule, Numero de B/L, CN, B/L No, Num B/L
BL_LABELS = [
    r"COREOR\s+Vehicule\s*[:\-]?\s*",
    r"Num[eé]ro\s+de\s+B/?L\s*[:\-]?\s*",
    r"\bCN\s*[:\-]?\s*",
    r"B/?L\s*No\.?\s*[:\-]?\s*",
    r"Num\s+B/?L\s*[:\-]?\s*",
    r"Marks\s+and\s+Nos\.?\s*[:\-]?\s*"
]
BL_VALUE = r"([A-Z0-9]{8,25})"
BL_PATTERNS = [re.compile(label + BL_VALUE, re.IGNORECASE) for label in BL_LABELS]

# Numéro de déclaration : AAAA XX(chiffres+lettres) suite_chiffres
# Exemples : "2026 15T 32563", "2025 18N 5104"
DECL_PATTERN = re.compile(
    r"\b(20\d{2})\s+(\d{2}[A-Z])\s+(\d{4,6})\b"
)

# Numéro de facture : précédé par "Facture N°" ou "Facture No"
FACTURE_LABELS = [
    r"Facture\s+N[°o]\.?\s*[:\-]?\s*",
    r"FACTURE\s+N[°o]\.?\s*[:\-]?\s*",
]
FACTURE_VALUE = r"(\d{5,10})"
FACTURE_PATTERNS = [
    re.compile(label + FACTURE_VALUE, re.IGNORECASE)
    for label in FACTURE_LABELS
]

# ─── Fonctions d'extraction ───────────────────────────────────────────────────

def extract_numero_bl(text: str) -> Optional[str]:
    for pattern in BL_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()

    # fallback intelligent
    fallback = re.search(r"\b[A-Z]{3,}[A-Z0-9]{8,}\b", text)
    if fallback:
        return fallback.group(0)

    return None

def extract_numero_declaration(text: str) -> Optional[str]:
    """
    Cherche un numéro de déclaration au format : AAAA XXN NNNNN
    Exemples : 2026 15T 32563 / 2025 18N 5104
    Retourne le numéro formaté avec espaces.
    """
    match = DECL_PATTERN.search(text)
    if match:
        return f"{match.group(1)} {match.group(2)} {match.group(3)}"
    return None


def extract_numero_facture(text: str) -> Optional[str]:
    """
    Cherche le numéro de facture dans le texte.
    Ne s'applique que sur les documents de type FACTURE.
    """
    for pattern in FACTURE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


# ─── Dispatcher par type de document ─────────────────────────────────────────

# Mapping : type_document → liste des champs qu'il peut fournir
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

    Exemple de retour :
    {
        "numero_bl": "304448001001",
        "numero_declaration": "2026 15T 32563",
        "numero_facture": None
    }
    """
    champs_cibles = DOCUMENT_FIELDS.get(type_document, [])
    resultats = {}

    for champ in champs_cibles:
        extracteur = EXTRACTORS.get(champ)
        if extracteur:
            resultats[champ] = extracteur(full_text)

    return resultats
