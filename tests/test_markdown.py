"""Tests du convertisseur Markdown léger -> HTML — logique pure, aucun réseau."""
import unittest

from rudi_harvest_toolkit.markdown import markdown_vers_html


class TestMarkdownVersHtml(unittest.TestCase):
    def test_vide(self):
        self.assertEqual(markdown_vers_html(""), "")
        self.assertEqual(markdown_vers_html(None), "")
        self.assertEqual(markdown_vers_html("   \n\n  "), "")

    def test_paragraphe_simple(self):
        self.assertEqual(markdown_vers_html("Un texte simple."), "<p>Un texte simple.</p>")

    def test_deux_paragraphes(self):
        html = markdown_vers_html("Premier paragraphe.\n\nSecond paragraphe.")
        self.assertEqual(html, "<p>Premier paragraphe.</p>\n<p>Second paragraphe.</p>")

    def test_retour_a_la_ligne_simple_devient_br(self):
        html = markdown_vers_html("Première phrase.\nSeconde phrase.")
        self.assertEqual(html, "<p>Première phrase.<br>Seconde phrase.</p>")

    def test_gras(self):
        self.assertEqual(markdown_vers_html("Du **texte en gras** ici."),
                          "<p>Du <strong>texte en gras</strong> ici.</p>")

    def test_italique_etoile_et_tiret(self):
        self.assertEqual(markdown_vers_html("Du *texte en italique*."),
                          "<p>Du <em>texte en italique</em>.</p>")
        self.assertEqual(markdown_vers_html("Du _texte en italique_."),
                          "<p>Du <em>texte en italique</em>.</p>")

    def test_liste_a_puces(self):
        html = markdown_vers_html("- simplification à 5m\n- simplification à 50m")
        self.assertEqual(html, "<ul><li>simplification à 5m</li><li>simplification à 50m</li></ul>")

    def test_liste_numerotee(self):
        html = markdown_vers_html("1. premier\n2. second")
        self.assertEqual(html, "<ol><li>premier</li><li>second</li></ol>")

    def test_liste_precedee_d_une_phrase_d_intro_sans_ligne_vide(self):
        # Style data.gouv.fr courant : la phrase d'intro est collée aux puces, sans
        # ligne vide entre les deux (même bloc) — doit devenir intro + <ul>, pas un
        # paragraphe <br> avec les "- " laissés tels quels.
        texte = (
            "Les arbres gérés sont de trois types :\n"
            "- les arbres d'alignement ;\n"
            "- les arbres remarquables ;\n"
            "- les arbres d'ornement."
        )
        html = markdown_vers_html(texte)
        self.assertEqual(
            html,
            "<p>Les arbres gérés sont de trois types :</p>"
            "\n<ul><li>les arbres d'alignement ;</li>"
            "<li>les arbres remarquables ;</li>"
            "<li>les arbres d'ornement.</li></ul>",
        )

    def test_lien_markdown(self):
        html = markdown_vers_html("Voir [le site](https://example.org/page).")
        self.assertEqual(
            html,
            '<p>Voir <a href="https://example.org/page" target="_blank" '
            'rel="noopener noreferrer">le site</a>.</p>',
        )

    def test_lien_schema_non_http_degrade_en_texte(self):
        html = markdown_vers_html("Cliquer [ici](javascript:alert(1)) surtout pas.")
        self.assertNotIn("javascript:", html)
        self.assertNotIn("<a ", html)
        self.assertIn("ici", html)

    def test_titre_pseudo_markdown(self):
        html = markdown_vers_html("## Descriptif du contenu\n\nLa suite.")
        self.assertEqual(html, "<p><strong>Descriptif du contenu</strong></p>\n<p>La suite.</p>")

    def test_echappement_html_de_la_source(self):
        html = markdown_vers_html("Une balise <script>alert(1)</script> & une esperluette.")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)

    def test_cas_reel_data_gouv_osm_communes(self):
        # Extrait réel de la description data.gouv.fr du JDD "Découpage administratif
        # communal français issu d'OpenStreetMap" (API data.gouv.fr, consulté en 2026).
        texte = (
            "Exports du découpage administratif français au niveau communal.\n\n"
            "**Descriptif du contenu des fichiers \"communes\"**\n\n"
            "**Format**\n\n"
            "Ces fichiers sont proposés au format shapefile, avec plusieurs niveaux de "
            "détails:\n\n"
            "- simplification à 5m\n"
            "- simplification à 50m\n"
            "- simplification à 100m\n\n"
            "Plus d'infos: [http://prev.openstreetmap.fr/36680-communes]"
            "(http://prev.openstreetmap.fr/36680-communes)"
        )
        html = markdown_vers_html(texte)
        # Pas de syntaxe Markdown littérale résiduelle dans la sortie.
        self.assertNotIn("**", html)
        self.assertNotIn("- simplification", html)
        self.assertIn("<ul>", html)
        self.assertIn("<strong>Descriptif du contenu des fichiers", html)
        self.assertIn('<a href="http://prev.openstreetmap.fr/36680-communes"', html)

    def test_url_brute_devient_cliquable(self):
        # Style data.gouv.fr courant : l'URL n'est pas en syntaxe [texte](url).
        html = markdown_vers_html(
            "Jeu de données source : https://www.data.gouv.fr/datasets/abc123"
        )
        self.assertEqual(
            html,
            '<p>Jeu de données source : <a href="https://www.data.gouv.fr/datasets/abc123" '
            'target="_blank" rel="noopener noreferrer">'
            "https://www.data.gouv.fr/datasets/abc123</a></p>",
        )

    def test_url_brute_ponctuation_finale_de_phrase_exclue_du_lien(self):
        html = markdown_vers_html("Voir https://example.org/page. Suite du texte.")
        self.assertIn('<a href="https://example.org/page"', html)
        self.assertIn("</a>. Suite du texte.", html)

    def test_url_brute_schema_non_http_jamais_transformee(self):
        html = markdown_vers_html("Ne pas suivre ftp://exemple.fr/fichier ici.")
        self.assertNotIn("<a ", html)
        self.assertIn("ftp://exemple.fr/fichier", html)

    def test_deux_liens_dans_le_meme_paragraphe_ne_se_corrompent_pas_mutuellement(self):
        # Chaque <a> généré porte target="_blank" (un seul underscore) : la regex
        # d'italique _..._ ne doit jamais s'appairer à travers deux balises <a>.
        html = markdown_vers_html(
            "Voir [ce site](https://example.com) ou directement https://example.org/page."
        )
        self.assertEqual(html.count("<a "), 2)
        self.assertEqual(html.count("<em>"), 0)
        self.assertIn('<a href="https://example.com" target="_blank"', html)
        self.assertIn('<a href="https://example.org/page" target="_blank"', html)

    def test_italique_tiret_legitime_toujours_reconnu(self):
        html = markdown_vers_html("Un _vrai_ italique.")
        self.assertEqual(html, "<p>Un <em>vrai</em> italique.</p>")

    def test_url_dans_texte_deja_lien_markdown_non_doublee(self):
        # Le label d'un lien [url](url) ne doit pas être re-transformé par l'autolink.
        html = markdown_vers_html("[https://example.com](https://example.com)")
        self.assertEqual(html.count("<a "), 1)

    def test_underscores_de_noms_de_colonnes_snake_case_jamais_italique(self):
        # Cas réel signalé sur une fiche catalogue (nœud local, 2026-10-16) : une liste
        # de noms de colonnes en snake_case faisait croire à de l'italique entre deux
        # identifiants sans rapport (ex. "code<em>insee, nom</em>structure").
        texte = (
            "Les enregistrements comportent les champs suivants : id, site, "
            "code_insee, nom_structure, adresse, accueil_permanence, "
            "ouverture_projet, ouverture_rdv."
        )
        html = markdown_vers_html(texte)
        self.assertNotIn("<em>", html)
        self.assertIn("code_insee, nom_structure", html)
        self.assertIn("accueil_permanence, ouverture_projet, ouverture_rdv", html)

    def test_italique_tiret_en_debut_et_fin_de_phrase(self):
        html = markdown_vers_html("_Début_ et _fin_ de phrase.")
        self.assertEqual(html, "<p><em>Début</em> et <em>fin</em> de phrase.</p>")


if __name__ == "__main__":
    unittest.main()
