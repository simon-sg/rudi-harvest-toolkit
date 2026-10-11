"""Tests de la fonction pivot construire_rudi_metadata() — logique pure, aucun réseau.

Fige les nouveaux paramètres explicites issus du découplage : `geography=None` par
défaut, `producer` pré-formé par l'appelant, `contacts_source` obligatoire.
"""
import unittest

from rudi_harvest_toolkit.pivot import (
    LICENCE_ETALAB,
    construire_licence,
    construire_rudi_metadata,
    media_filtre,
    media_metadata_page,
    media_source,
    parser_date_http,
)

_CONTACT = {"contact_name": "Prod", "email": "prod@example.org"}


class TestMediaHelpers(unittest.TestCase):
    def test_media_ids_deterministes(self):
        self.assertEqual(media_filtre("insee:x", "f.csv", "RM")["media_id"],
                         media_filtre("insee:x", "f.csv", "RM")["media_id"])
        self.assertNotEqual(media_filtre("insee:x", "f.csv", "RM")["media_id"],
                            media_filtre("insee:y", "f.csv", "RM")["media_id"])
        self.assertEqual(media_metadata_page("p", "https://u", "c")["media_id"],
                         media_metadata_page("p", "https://u", "c")["media_id"])

    def test_media_source_est_un_service(self):
        m = media_source("p", "https://u", "c")
        self.assertEqual(m["media_type"], "SERVICE")
        self.assertEqual(m["media_name"], "source-data")
        self.assertEqual(m["connector"]["url"], "https://u")


class TestConstruireRudiMetadata(unittest.TestCase):
    def _args(self, **surcharge):
        args = dict(
            local_id="00000000-0000-5000-8000-000000000001",
            titre="T — Rennes Métropole", synopsis="S", description="D",
            theme="economy", keywords=["a", "b", "a"],
            producer={"organization_name": "Prod"},
            url_source="https://src", url_fiche="https://fiche",
            medias=[],
            contacts_source=[dict(_CONTACT)],
        )
        args.update(surcharge)
        return args

    def _construire(self, **surcharge):
        return construire_rudi_metadata(**self._args(**surcharge))

    def test_auto_append_source_et_metadata(self):
        meta = self._construire()
        noms = [m["media_name"] for m in meta["available_formats"]]
        self.assertEqual(noms, ["source-data", "source-metadata"])

    def test_pas_d_auto_append_si_desactive(self):
        meta = self._construire(ajouter_medias_source=False)
        self.assertEqual(meta["available_formats"], [])

    def test_keywords_dedupliques_ordre_conserve(self):
        meta = self._construire()
        self.assertEqual(meta["keywords"], ["a", "b"])

    def test_licence_defaut_et_surcharge(self):
        self.assertEqual(self._construire()["access_condition"]["licence"], LICENCE_ETALAB)
        custom = {"licence_type": "CUSTOM"}
        self.assertEqual(self._construire(licence=custom)["access_condition"]["licence"], custom)

    def test_dates_prime_sur_date_source(self):
        meta = self._construire(dates={"created": "2024-01-01T00:00:00Z"},
                                date_source="Wed, 12 Feb 2025 09:41:37 GMT")
        self.assertEqual(meta["dataset_dates"], {"created": "2024-01-01T00:00:00Z"})

    def test_dates_derivees_de_date_source_si_absentes(self):
        meta = self._construire(date_source="Wed, 12 Feb 2025 09:41:37 GMT")
        self.assertEqual(meta["dataset_dates"], {"updated": "2025-02-12T09:41:37Z"})

    def test_metadata_dates_optionnel(self):
        sans = self._construire()
        self.assertNotIn("metadata_dates", sans["metadata_info"])
        avec = self._construire(metadata_dates={"updated": "2025-01-01T00:00:00Z"})
        self.assertIn("metadata_dates", avec["metadata_info"])

    def test_titre_tronque_a_150(self):
        meta = self._construire(titre="a" * 300)
        self.assertEqual(len(meta["resource_title"]), 150)
        self.assertTrue(meta["resource_title"].endswith("…"))

    def test_summary_html_genere_depuis_markdown(self):
        meta = self._construire(description="Un **gras** et une liste :\n\n- un\n- deux")
        self.assertEqual(meta["summary"][0]["text"], "Un **gras** et une liste :\n\n- un\n- deux")
        self.assertIn("<strong>gras</strong>", meta["summary"][0]["html"])
        self.assertIn("<ul><li>un</li><li>deux</li></ul>", meta["summary"][0]["html"])

    def test_summary_sans_html_si_description_vide(self):
        meta = self._construire(description="")
        self.assertNotIn("html", meta["summary"][0])

    # --- Découplage : geography / producer / contacts_source ------------------

    def test_geography_absent_par_defaut(self):
        self.assertNotIn("geography", self._construire())

    def test_geography_present_si_fournie(self):
        bbox = {"bbox": [1, 2, 3, 4]}
        self.assertEqual(self._construire(geography=bbox)["geography"], bbox)

    def test_producer_pre_forme_conserve_tel_quel(self):
        producer = {
            "organization_name": "INSEE",
            "organization_caption": "Institut national de la statistique",
            "organization_summary": "L'INSEE produit des statistiques.",
        }
        meta = self._construire(producer=producer)
        self.assertEqual(meta["producer"], producer)

    def test_producer_non_mute_par_la_fonction(self):
        producer = {"organization_name": "Prod"}
        self._construire(producer=producer)
        self.assertEqual(producer, {"organization_name": "Prod"})

    def test_contacts_source_transmis(self):
        contacts = [{"contact_name": "Alice", "email": "alice@example.org"}]
        meta = self._construire(contacts_source=contacts)
        self.assertEqual(meta["contacts"], contacts)

    def test_contacts_source_obligatoire(self):
        args = self._args()
        del args["contacts_source"]
        with self.assertRaises(TypeError):
            construire_rudi_metadata(**args)


class TestParserDateHttp(unittest.TestCase):
    def test_format_http(self):
        self.assertEqual(parser_date_http("Wed, 12 Feb 2025 09:41:37 GMT"),
                         "2025-02-12T09:41:37Z")

    def test_format_iso(self):
        self.assertEqual(parser_date_http("2025-01-15T10:30:00.000Z"),
                         "2025-01-15T10:30:00Z")

    def test_format_iso_offset_converti_utc(self):
        self.assertEqual(parser_date_http("2025-01-15T12:30:00+02:00"),
                         "2025-01-15T10:30:00Z")

    def test_none(self):
        self.assertIsNone(parser_date_http(None))
        self.assertIsNone(parser_date_http(""))


class TestConstruireLicence(unittest.TestCase):
    _TABLE = {
        "lov2": {"licence_type": "STANDARD", "licence_label": "etalab-2.0"},
        "ODbL": {"licence_type": "STANDARD", "licence_label": "odbl-1.0"},
    }

    def test_libelle_connu_insensible_a_la_casse(self):
        bloc = construire_licence("odbl", "https://x", self._TABLE)
        self.assertEqual(bloc, {"licence_type": "STANDARD", "licence_label": "odbl-1.0"})

    def test_libelle_connu_insensible_aux_espaces(self):
        bloc = construire_licence("  lov2  ", None, self._TABLE)
        self.assertEqual(bloc["licence_label"], "etalab-2.0")

    def test_libelle_inconnu_passthrough_custom(self):
        bloc = construire_licence("Ma licence maison", "https://exemple.fr/licence", self._TABLE)
        self.assertEqual(bloc["licence_type"], "CUSTOM")
        self.assertEqual(bloc["custom_licence_label"], [{"lang": "fr", "text": "Ma licence maison"}])
        self.assertEqual(bloc["custom_licence_uri"], "https://exemple.fr/licence")

    def test_libelle_inconnu_sans_url_omet_uri(self):
        bloc = construire_licence("Inconnue", None, self._TABLE)
        self.assertEqual(bloc["licence_type"], "CUSTOM")
        self.assertNotIn("custom_licence_uri", bloc)

    def test_libelle_vide_retourne_none(self):
        self.assertIsNone(construire_licence("", "https://x", self._TABLE))
        self.assertIsNone(construire_licence(None, "https://x", self._TABLE))

    def test_bloc_retourne_independant_de_la_table(self):
        bloc = construire_licence("lov2", None, self._TABLE)
        bloc["licence_label"] = "modifié"
        self.assertEqual(self._TABLE["lov2"]["licence_label"], "etalab-2.0")


if __name__ == "__main__":
    unittest.main()
