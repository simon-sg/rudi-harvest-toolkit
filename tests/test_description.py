"""Tests de description.py — assemblage Markdown pur, vérifié contre
markdown_vers_html() (v3 de rudi-commune-starterkit, Axe 3). Zéro réseau."""
import unittest

from rudi_harvest_toolkit.description import construire_description_structuree
from rudi_harvest_toolkit.markdown import markdown_vers_html

_ARGS = dict(
    quoi="Entreprises actives ayant un établissement sur la commune.",
    comment_construit="Extrait de l'API recherche-entreprises.api.gouv.fr, filtré par code commune.",
    structure_variables=["siren", "nom_complet", "activite_principale"],
    frequence_maj="mensuelle",
    source_label="INSEE (répertoire SIRENE)",
    url_source="https://recherche-entreprises.api.gouv.fr",
)


class TestConstruireDescriptionStructuree(unittest.TestCase):
    def test_contient_toutes_les_parties(self):
        texte = construire_description_structuree(**_ARGS)
        self.assertIn(_ARGS["quoi"], texte)
        self.assertIn(_ARGS["comment_construit"], texte)
        for variable in _ARGS["structure_variables"]:
            self.assertIn(f"- {variable}", texte)
        self.assertIn("mensuelle", texte)
        self.assertIn("[INSEE (répertoire SIRENE)](https://recherche-entreprises.api.gouv.fr)", texte)

    def test_structure_variables_vide_leve(self):
        with self.assertRaises(ValueError):
            construire_description_structuree(**{**_ARGS, "structure_variables": []})

    def test_rendu_html_liste_reconnue(self):
        texte = construire_description_structuree(**_ARGS)
        html = markdown_vers_html(texte)
        self.assertIn("<ul>", html)
        self.assertEqual(html.count("<li>"), len(_ARGS["structure_variables"]))

    def test_rendu_html_lien_source_final(self):
        texte = construire_description_structuree(**_ARGS)
        html = markdown_vers_html(texte)
        self.assertIn('<a href="https://recherche-entreprises.api.gouv.fr"', html)
        self.assertIn("INSEE (répertoire SIRENE)</a>", html)

    def test_rendu_html_pas_de_tableau(self):
        texte = construire_description_structuree(**_ARGS)
        html = markdown_vers_html(texte)
        self.assertNotIn("<table>", html)

    def test_ordre_des_sections(self):
        texte = construire_description_structuree(**_ARGS)
        self.assertLess(texte.index(_ARGS["quoi"]), texte.index(_ARGS["comment_construit"]))
        self.assertLess(texte.index(_ARGS["comment_construit"]), texte.index("Variables publiées"))
        self.assertLess(texte.index("Variables publiées"), texte.index("Mise à jour"))
        self.assertLess(texte.index("Mise à jour"), texte.index("Source :"))

    def test_glossaire_et_limites_absents_par_defaut_sortie_inchangee(self):
        self.assertNotIn("Codes et variables", construire_description_structuree(**_ARGS))
        self.assertNotIn("Limites de couverture", construire_description_structuree(**_ARGS))

    def test_glossaire_rend_chaque_entree(self):
        texte = construire_description_structuree(
            **_ARGS, glossaire={"LFI": "La France insoumise", "LR": "Les Républicains"},
        )
        self.assertIn("- LFI : La France insoumise", texte)
        self.assertIn("- LR : Les Républicains", texte)

    def test_limites_rend_chaque_entree(self):
        texte = construire_description_structuree(
            **_ARGS, limites=["Carte : 8 points sur 10 lignes.", "Pas de second tour."],
        )
        self.assertIn("- Carte : 8 points sur 10 lignes.", texte)
        self.assertIn("- Pas de second tour.", texte)

    def test_glossaire_et_limites_avant_mise_a_jour(self):
        texte = construire_description_structuree(
            **_ARGS, glossaire={"LFI": "La France insoumise"}, limites=["Pas de second tour."],
        )
        self.assertLess(texte.index("Variables publiées"), texte.index("Codes et variables"))
        self.assertLess(texte.index("Codes et variables"), texte.index("Limites de couverture"))
        self.assertLess(texte.index("Limites de couverture"), texte.index("Mise à jour"))

    def test_rendu_html_glossaire_et_limites_sont_des_listes(self):
        texte = construire_description_structuree(
            **_ARGS, glossaire={"LFI": "La France insoumise"}, limites=["Pas de second tour."],
        )
        html = markdown_vers_html(texte)
        self.assertEqual(html.count("<ul>"), 3)


if __name__ == "__main__":
    unittest.main()
