from detector import is_native_pdf
from extractor_native import extract_text_native
from extractor_scan import extract_text_scan
from parser import parse_document


def process_document(pdf_path: str, type_document: str) -> dict:
    """
    Pipeline complet pour un document.

    1. Détecte si le PDF est natif ou scanné
    2. Extrait le texte avec la bonne méthode
    3. Parse le texte pour extraire les numéros métier
    4. Retourne le résultat structuré

    Paramètres :
        pdf_path      : chemin local vers le fichier PDF
        type_document : ex. "FACTURE", "BILL_OF_LADING", etc.

    Retour :
    {
        "methode":         "natif" | "ocr",
        "score_confiance": 0.0 à 1.0,
        "pages":           { 1: "texte page 1", ... },
        "donnees_extraites": {
            "numero_bl":          "304448001001" | None,
            "numero_declaration": "2026 15T 32563" | None,
            "numero_facture":     "2607661" | None
        },
        "erreur": None | "message d'erreur"
    }
    """

    # Étape 1 — Détection
    natif = is_native_pdf(pdf_path)

    # Étape 2 — Extraction
    if natif:
        extraction = extract_text_native(pdf_path)
    else:
        extraction = extract_text_scan(pdf_path)

    if "erreur" in extraction:
        return {
            "methode": extraction.get("methode"),
            "score_confiance": 0.0,
            "pages": {},
            "donnees_extraites": {},
            "erreur": extraction["erreur"]
        }

    # Étape 3 — Parsing : on concatène toutes les pages
    full_text = "\n".join(extraction["pages"].values())
    donnees = parse_document(full_text, type_document)

    return {
        "methode": extraction["methode"],
        "score_confiance": extraction["score_confiance"],
        "pages": extraction["pages"],
        "donnees_extraites": donnees,
        "erreur": None
    }

# ─── Test rapide en ligne de commande ────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 3:
        print("Usage : python pipeline.py <chemin_pdf> <type_document>")
        print("Types : BAD_DAKAR_TERMINAL | BAD_SHIPPING | DECLARATION |"
              " BILL_OF_LADING | PROCURATION | CNI_TRANSITAIRE | CNI_CLIENT | FACTURE")
        sys.exit(1)

    chemin = sys.argv[1]
    type_doc = sys.argv[2].upper()

    resultat = process_document(chemin, type_doc)

    print(json.dumps(resultat, ensure_ascii=False, indent=2))
