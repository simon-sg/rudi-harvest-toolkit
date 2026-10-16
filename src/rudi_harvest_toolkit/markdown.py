"""
Convertit en HTML minimal le sous-ensemble de Markdown réellement utilisé par les
descriptions sources (data.gouv.fr en particulier écrit ses descriptions en Markdown :
gras, listes à puces, liens, paragraphes séparés par une ligne vide).

Alimente `summary[].html` des métadonnées RUDI (voir pivot.py::construire_rudi_metadata).
Le portail (depuis sa v3.3.2) injecte ce champ en HTML (innerHTML) à la place de
`summary[].text` quand il est présent. Sans lui, le Markdown source s'affichait tel
quel sur la fiche catalogue : texte littéral « **gras** »/« - puce », et retours à la
ligne perdus (le rendu HTML ignore les \n hors balises).

Volontairement pas un parseur Markdown complet : aucune dépendance ajoutée (voir
CLAUDE.md « Dépendances » — stdlib + requests pour tout le pipeline de moisson), et
seuls les éléments réellement observés dans les sources moissonnées sont gérés — gras,
italique, liens, listes (à puces ou numérotées), paragraphes, retours à la ligne simples
au sein d'un paragraphe, et pseudo-titres `# `/`## `. Tout le texte est échappé avant
insertion : aucune balise ni attribut de la source n'est jamais reproduit tel quel dans
la sortie (liens restreints aux schémas http/https, pour éviter une injection via un
schéma `javascript:`/`data:`).

Les URLs http(s) laissées en texte brut par la source (hors syntaxe `[texte](url)` —
ex. data.gouv.fr écrit souvent « Jeu de données source : https://... » sans crochets)
sont elles aussi rendues cliquables (constaté en démo RM le 2026-10-16 : sans ça, le lien
restait affiché tel quel, non cliquable, sur la fiche catalogue du portail).
"""
import re

_RE_GRAS = re.compile(r"\*\*(.+?)\*\*")
_RE_ITALIQUE_ETOILE = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
# toute balise <a> déjà générée (liens markdown ou autolink) contient un attribut
# target="_blank" — un seul underscore, qui peut sinon s'appairer avec n'importe quel
# autre underscore plus loin dans le texte (ex. 2 liens dans le même paragraphe, ou une
# URL/un identifiant en snake_case) et faire croire à de l'italique à travers la balise.
# Exclure ", < et > du contenu empêche la regex de jamais franchir une balise générée.
_RE_ITALIQUE_TIRET = re.compile(r"(?<!_)_([^_\n\"<>]+?)_(?!_)")
_RE_LIEN = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_RE_LIEN_HTML = re.compile(r"<a\b[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)
_RE_URL_BRUTE = re.compile(r"https?://\S+", re.IGNORECASE)
_PONCTUATION_FINALE = ".,;:!?)"
_RE_PUCE = re.compile(r"^[-*+]\s+(.*)")
_RE_NUMEROTE = re.compile(r"^\d+[.)]\s+(.*)")
_RE_TITRE = re.compile(r"^(#{1,6})\s+(.*)")


def _echapper(texte: str) -> str:
    """Échappe les caractères qui ont un sens en HTML — appliqué avant toute mise en
    forme, pour que le Markdown source ne puisse jamais injecter de balise/attribut."""
    return texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _lien_securise(url: str) -> str | None:
    """N'autorise que http(s) — évite l'injection via un schéma javascript:/data: etc.
    None si le schéma n'est pas autorisé (le lien est alors dégradé en texte simple)."""
    if re.match(r"^https?://", url, re.IGNORECASE):
        return url.replace('"', "&quot;")
    return None


def _remplacer_url_brute(m: re.Match) -> str:
    """Convertit une URL http(s) trouvée en texte brut en lien cliquable. Rogne la
    ponctuation finale usuelle (fin de phrase, parenthèse fermante) hors du lien."""
    url = m.group(0)
    fin = ""
    while url and url[-1] in _PONCTUATION_FINALE:
        fin = url[-1] + fin
        url = url[:-1]
    href = _lien_securise(url) if url else None
    if href is None:
        return m.group(0)
    return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{url}</a>{fin}'


def _autolier_urls_brutes(texte: str) -> str:
    """Rend cliquables les URLs http(s) laissées en texte brut (hors syntaxe
    `[texte](url)`, déjà convertie en `<a>` avant cet appel) — sans jamais retoucher un
    `<a>` déjà généré, pour ne pas lier deux fois la même URL ni casser son `href`."""
    morceaux = []
    position = 0
    for m in _RE_LIEN_HTML.finditer(texte):
        morceaux.append(_RE_URL_BRUTE.sub(_remplacer_url_brute, texte[position:m.start()]))
        morceaux.append(m.group(0))
        position = m.end()
    morceaux.append(_RE_URL_BRUTE.sub(_remplacer_url_brute, texte[position:]))
    return "".join(morceaux)


def _inline(texte_echappe: str) -> str:
    """Applique liens/gras/italique sur un texte déjà échappé (HTML-safe)."""

    def _remplacer_lien(m: re.Match) -> str:
        url = _lien_securise(m.group(2))
        if url is None:
            return m.group(1)
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{m.group(1)}</a>'

    texte = _RE_LIEN.sub(_remplacer_lien, texte_echappe)
    texte = _autolier_urls_brutes(texte)
    texte = _RE_GRAS.sub(r"<strong>\1</strong>", texte)
    texte = _RE_ITALIQUE_ETOILE.sub(r"<em>\1</em>", texte)
    texte = _RE_ITALIQUE_TIRET.sub(r"<em>\1</em>", texte)
    return texte


def _ligne_liste(ligne: str) -> tuple[str, str] | None:
    """Retourne (type_liste, contenu) si `ligne` est un item de liste ("ul"/"ol"), None sinon."""
    m = _RE_PUCE.match(ligne)
    if m:
        return "ul", m.group(1)
    m = _RE_NUMEROTE.match(ligne)
    if m:
        return "ol", m.group(1)
    return None


def markdown_vers_html(texte: str | None) -> str:
    """Convertit le sous-ensemble de Markdown décrit en tête de module en HTML.

    Chaîne vide si `texte` est vide/absent. Chaque bloc source (séparé par une ligne
    vide) devient une liste (<ul>/<ol>) si toutes ses lignes sont des items ; si seule
    une phrase d'intro précède des items collés sans ligne vide (style data.gouv.fr
    courant), elle devient un paragraphe d'intro suivi de la liste. Un bloc qui tient
    en une ligne commençant par `#` devient un titre (<p><strong>). Sinon, paragraphe
    (<p>, les retours à la ligne simples internes devenant <br>).
    """
    if not (texte or "").strip():
        return ""

    blocs_html = []
    for bloc in re.split(r"\n\s*\n", texte.strip()):
        lignes = [l.strip() for l in bloc.splitlines() if l.strip()]
        if not lignes:
            continue

        items = [_ligne_liste(l) for l in lignes]
        if all(items):
            type_liste = items[0][0]
            puces = "".join(f"<li>{_inline(_echapper(contenu))}</li>" for _, contenu in items)
            blocs_html.append(f"<{type_liste}>{puces}</{type_liste}>")
            continue

        # Phrase d'intro collée à une liste sans ligne vide entre les deux (style
        # data.gouv.fr courant, ex. "... sont de trois types :\n- item\n- item") :
        # découpée en paragraphe d'intro + liste, plutôt que de tout retomber en
        # paragraphe <br> faute de bloc 100% liste.
        premier_item = next((i for i, it in enumerate(items) if it is not None), None)
        if premier_item and all(items[premier_item:]) and len({it[0] for it in items[premier_item:]}) == 1:
            intro = "<br>".join(_inline(_echapper(l)) for l in lignes[:premier_item])
            type_liste = items[premier_item][0]
            puces = "".join(
                f"<li>{_inline(_echapper(contenu))}</li>" for _, contenu in items[premier_item:]
            )
            blocs_html.append(f"<p>{intro}</p>")
            blocs_html.append(f"<{type_liste}>{puces}</{type_liste}>")
            continue

        m_titre = _RE_TITRE.match(lignes[0]) if len(lignes) == 1 else None
        if m_titre:
            blocs_html.append(f"<p><strong>{_inline(_echapper(m_titre.group(2)))}</strong></p>")
            continue

        paragraphe = "<br>".join(_inline(_echapper(l)) for l in lignes)
        blocs_html.append(f"<p>{paragraphe}</p>")

    return "\n".join(blocs_html)
