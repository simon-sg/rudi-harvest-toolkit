"""Tests de datagouv.py — métadonnées, ressources et sélection explicite. Zéro réseau."""
import unittest
from unittest import mock

from rudi_harvest_toolkit.datagouv import (
    DATAGOUV_API,
    ErreurSelectionRessource,
    RessourceIntrouvableError,
    SelectionAmbigueError,
    get_dataset_metadata,
    lister_ressources,
    selectionner_ressource,
)

_RESSOURCES = [
    {
        "id": "r-old",
        "title": "Conseillers municipaux 2020",
        "format": "csv",
        "url": "https://exemple.fr/old.csv",
        "last_modified": "2020-05-01T10:00:00+00:00",
    },
    {
        "id": "r-new",
        "title": "Conseillers municipaux 2026",
        "format": "csv",
        "url": "https://exemple.fr/new.csv",
        "last_modified": "2026-01-15T10:00:00Z",
    },
    {
        "id": "r-json",
        "title": "Conseillers municipaux (JSON)",
        "format": "json",
        "url": "https://exemple.fr/data.json",
        "last_modified": "2024-01-01T00:00:00+00:00",
    },
    {
        "id": "r-sans-date",
        "title": "Documentation",
        "format": "pdf",
        "url": "https://exemple.fr/doc.pdf",
    },
]

_METADATA = {"id": "elus", "title": "Élus", "resources": _RESSOURCES}


class TestRecuperation(unittest.TestCase):
    def test_get_dataset_metadata_url_et_timeout(self):
        reponse = mock.Mock()
        reponse.json.return_value = _METADATA
        reponse.raise_for_status = mock.Mock()
        session = mock.Mock()
        session.get.return_value = reponse

        resultat = get_dataset_metadata("elus", session_http=session, timeout=12)

        self.assertEqual(resultat, _METADATA)
        session.get.assert_called_once_with(
            f"{DATAGOUV_API}/datasets/elus/", timeout=12
        )
        reponse.raise_for_status.assert_called_once()

    def test_lister_ressources(self):
        with mock.patch("rudi_harvest_toolkit.datagouv.get_dataset_metadata",
                        return_value=_METADATA) as recuperer:
            ressources = lister_ressources("elus")
        self.assertEqual(ressources, _RESSOURCES)
        recuperer.assert_called_once_with("elus")

    def test_erreur_http_propagee(self):
        reponse = mock.Mock()
        reponse.raise_for_status.side_effect = RuntimeError("404")
        session = mock.Mock()
        session.get.return_value = reponse
        with self.assertRaises(RuntimeError):
            get_dataset_metadata("inconnu", session_http=session)


class TestSelectionExplicite(unittest.TestCase):
    def test_par_index(self):
        self.assertEqual(selectionner_ressource(_METADATA, index=1)["id"], "r-new")
        self.assertEqual(selectionner_ressource(_RESSOURCES, index=0)["id"], "r-old")

    def test_index_hors_bornes(self):
        with self.assertRaises(RessourceIntrouvableError):
            selectionner_ressource(_RESSOURCES, index=99)

    def test_par_motif_nom(self):
        ressource = selectionner_ressource(_METADATA, motif_nom=r"2026")
        self.assertEqual(ressource["id"], "r-new")

    def test_motif_regex_insensible_a_la_casse(self):
        ressource = selectionner_ressource(_METADATA, motif_nom=r"conseillers? municipaux \(json\)")
        self.assertEqual(ressource["id"], "r-json")

    def test_motif_ambigu_leve(self):
        with self.assertRaises(SelectionAmbigueError) as ctx:
            selectionner_ressource(_METADATA, motif_nom=r"conseillers municipaux")
        self.assertIn("ambigu", str(ctx.exception))

    def test_motif_introuvable(self):
        with self.assertRaises(RessourceIntrouvableError):
            selectionner_ressource(_METADATA, motif_nom=r"inexistant")

    def test_par_date_la_plus_recente(self):
        ressource = selectionner_ressource(_METADATA, la_plus_recente=True)
        self.assertEqual(ressource["id"], "r-new")

    def test_date_la_plus_recente_ignore_les_ressources_sans_date(self):
        ressources = [
            {"id": "sans", "title": "sans date"},
            {"id": "a", "title": "a", "last_modified": "2025-01-01T00:00:00Z"},
            {"id": "b", "title": "b", "created_at": "2025-06-01T00:00:00Z"},
        ]
        self.assertEqual(
            selectionner_ressource(ressources, la_plus_recente=True)["id"], "b"
        )

    def test_aucune_date_exploitable(self):
        ressources = [{"id": "x", "title": "x"}]
        with self.assertRaises(RessourceIntrouvableError):
            selectionner_ressource(ressources, la_plus_recente=True)

    def test_filtre_par_format(self):
        ressource = selectionner_ressource(
            _METADATA, la_plus_recente=True, format="json"
        )
        self.assertEqual(ressource["id"], "r-json")
        self.assertEqual(
            selectionner_ressource(_METADATA, index=0, format="csv")["id"], "r-old"
        )

    def test_format_absent(self):
        with self.assertRaises(RessourceIntrouvableError):
            selectionner_ressource(_METADATA, index=0, format="xlsx")

    def test_aucun_mode_refuse(self):
        with self.assertRaises(ErreurSelectionRessource):
            selectionner_ressource(_METADATA)

    def test_plusieurs_modes_refuses(self):
        with self.assertRaises(ErreurSelectionRessource):
            selectionner_ressource(_METADATA, index=0, la_plus_recente=True)
        with self.assertRaises(ErreurSelectionRessource):
            selectionner_ressource(_METADATA, motif_nom="a", index=0)

    def test_egalite_de_date_premiere_ressource(self):
        ressources = [
            {"id": "premier", "title": "a", "last_modified": "2025-01-01T00:00:00Z"},
            {"id": "second", "title": "b", "last_modified": "2025-01-01T00:00:00Z"},
        ]
        self.assertEqual(
            selectionner_ressource(ressources, la_plus_recente=True)["id"], "premier"
        )


if __name__ == "__main__":
    unittest.main()
