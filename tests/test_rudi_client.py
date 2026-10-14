"""Tests unitaires de rudi_client (config explicite, email de repli) — sans réseau."""
import json
import os
import tempfile
import unittest
from unittest import mock

from rudi_harvest_toolkit.rudi_client import (
    _dedoublonner_medias_file,
    _media_file_deja_complet,
    charger_conf_rudi,
    demander_creation_organisation,
    demander_detachement_producteur,
    demander_mise_a_jour_organisation,
    demander_suppression_organisation,
    email_par_defaut,
    lister_organisations,
    marquer_organisations_traitees,
    organisations_nouvellement_validees,
    renvoyer_ressources_connues,
    ressources_pour_organisations,
    supprimer_dataset_portail,
    televerser_piece_jointe,
)


class TestChargerConfRudi(unittest.TestCase):
    def test_chemin_absent_retourne_none(self):
        self.assertIsNone(charger_conf_rudi("/chemin/inexistant/rudi_node.json"))

    def test_charge_depuis_chemin_explicite(self):
        conf = {"url": "http://localhost:3030/manager", "usr": "u", "pwd": "p"}
        with tempfile.TemporaryDirectory() as d:
            chemin = os.path.join(d, "rudi_node.json")
            with open(chemin, "w", encoding="utf-8") as f:
                json.dump(conf, f)
            self.assertEqual(charger_conf_rudi(chemin), conf)


class TestEmailParDefaut(unittest.TestCase):
    def test_slug_et_domaine(self):
        self.assertEqual(email_par_defaut("Rennes Métropole"), "rennes-metropole@example.org")

    def test_accents_retires(self):
        self.assertEqual(email_par_defaut("Observatoire de l'Environnement"), "observatoire-de-l-environnement@example.org")

    def test_nom_vide_retombe_sur_contact(self):
        self.assertEqual(email_par_defaut(""), "contact@example.org")

    def test_unique_par_nom(self):
        self.assertNotEqual(email_par_defaut("Insee"), email_par_defaut("OEB"))


class TestListerOrganisations(unittest.TestCase):
    def test_expose_organization_list_sans_writer_public(self):
        orgs = [{"organization_id": "org-1", "organization_name": "Rennes Métropole"}]
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.organization_list = orgs
            self.assertEqual(lister_organisations(conf), orgs)
        creer.assert_called_once_with(conf)

    def test_statut_filtre_via_requete_http_directe(self):
        orgs = [{"organization_id": "org-1", "organization_status": "VALIDATED"}]
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "url_catalog": "http://n:3030/catalog"}
        reponse = mock.Mock(status_code=200)
        reponse.json.return_value = orgs
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = reponse
            self.assertEqual(lister_organisations(conf, statut="VALIDATED"), orgs)
        sess.get.assert_called_once_with(
            "http://n:3030/catalog/v1/organizations",
            params={"organization_status": "VALIDATED"}, timeout=30,
        )


class TestOrganisationsNouvellementValidees(unittest.TestCase):
    def test_exclut_les_organisations_deja_traitees(self):
        with tempfile.TemporaryDirectory() as d:
            chemin_etat = os.path.join(d, "etat_organisations_validees.json")
            with open(chemin_etat, "w", encoding="utf-8") as f:
                json.dump({"organisations_traitees": ["org-1"]}, f)
            with mock.patch("rudi_harvest_toolkit.rudi_client.lister_organisations",
                             return_value=[{"organization_id": "org-1"},
                                          {"organization_id": "org-2"}]):
                self.assertEqual(
                    organisations_nouvellement_validees({"url": "http://n:3032"}, chemin_etat),
                    ["org-2"],
                )

    def test_aucun_etat_prealable_retourne_toutes_les_validees(self):
        with tempfile.TemporaryDirectory() as d:
            chemin_etat = os.path.join(d, "etat_organisations_validees.json")
            with mock.patch("rudi_harvest_toolkit.rudi_client.lister_organisations",
                             return_value=[{"organization_id": "org-9"}]):
                self.assertEqual(
                    organisations_nouvellement_validees({"url": "http://n:3032"}, chemin_etat),
                    ["org-9"],
                )

    def test_ne_modifie_pas_le_fichier_etat(self):
        with tempfile.TemporaryDirectory() as d:
            chemin_etat = os.path.join(d, "etat_organisations_validees.json")
            with mock.patch("rudi_harvest_toolkit.rudi_client.lister_organisations",
                             return_value=[{"organization_id": "org-1"}]):
                organisations_nouvellement_validees({"url": "http://n:3032"}, chemin_etat)
            self.assertFalse(os.path.isfile(chemin_etat))


class TestMarquerOrganisationsTraitees(unittest.TestCase):
    def test_fusionne_avec_etat_existant(self):
        with tempfile.TemporaryDirectory() as d:
            chemin_etat = os.path.join(d, "etat.json")
            marquer_organisations_traitees(chemin_etat, ["org-1"])
            marquer_organisations_traitees(chemin_etat, ["org-2"])
            with open(chemin_etat, encoding="utf-8") as f:
                self.assertEqual(sorted(json.load(f)["organisations_traitees"]),
                                 ["org-1", "org-2"])


class TestRessourcesPourOrganisations(unittest.TestCase):
    def test_filtre_sur_producer_organization_id(self):
        metas = [
            {"global_id": "g1", "producer": {"organization_id": "org-1"}},
            {"global_id": "g2", "producer": {"organization_id": "org-2"}},
            {"global_id": "g3"},  # pas de producer : jamais sélectionnée
        ]
        self.assertEqual(
            [m["global_id"] for m in ressources_pour_organisations(metas, ["org-1"])],
            ["g1"],
        )


class TestRenvoyerRessourcesConnues(unittest.TestCase):
    _SUMMARY_RICHE = [{"lang": "fr", "text": "Un résumé.", "html": "<p>Un résumé.</p>"}]

    def test_un_put_catalog_par_ressource_avec_pause_entre_chaque(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        metas = [
            {"global_id": "g1", "summary": self._SUMMARY_RICHE},
            {"global_id": "g2", "summary": self._SUMMARY_RICHE},
            {"global_id": "g3", "summary": self._SUMMARY_RICHE},
        ]
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer, \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.sleep") as dodo:
            bilan = renvoyer_ressources_connues(conf, metas, pause_s=2.0)
        self.assertEqual(bilan, {"ok": 3, "echecs": []})
        creer.assert_called_once_with(conf)  # un seul writer, jamais un par ressource
        put = creer.return_value.connector.put_catalog
        self.assertEqual(put.call_count, 3)
        for appel, meta in zip(put.call_args_list, metas):
            self.assertEqual(appel.args, ("resources", meta))  # dict brut, sans transformation
            # le résumé riche (summary[].html) traverse intact — pas de round-trip RudiMetadata
            self.assertEqual(appel.args[1]["summary"], self._SUMMARY_RICHE)
        self.assertEqual(dodo.call_count, 2)  # pause entre chaque, pas après la dernière

    def test_un_seul_element_aucune_pause(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer"), \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.sleep") as dodo:
            bilan = renvoyer_ressources_connues(conf, [{"global_id": "g1"}])
        self.assertEqual(bilan, {"ok": 1, "echecs": []})
        dodo.assert_not_called()

    def test_liste_vide(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer"), \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.sleep") as dodo:
            bilan = renvoyer_ressources_connues(conf, [])
        self.assertEqual(bilan, {"ok": 0, "echecs": []})
        dodo.assert_not_called()

    def test_echec_sur_une_ressource_n_interrompt_pas_les_suivantes(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        metas = [{"global_id": "g1"}, {"global_id": "g2"}]
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer, \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.sleep"):
            creer.return_value.connector.put_catalog.side_effect = [None, Exception("500 Internal Server Error")]
            bilan = renvoyer_ressources_connues(conf, metas)
        self.assertEqual(bilan["ok"], 1)
        self.assertEqual(bilan["echecs"], [("g2", "500 Internal Server Error")])

    def test_exception_reseau_comptee_comme_echec(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer, \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.sleep"):
            creer.return_value.connector.put_catalog.side_effect = Exception("réseau indisponible")
            bilan = renvoyer_ressources_connues(conf, [{"global_id": "g1"}])
        self.assertEqual(bilan, {"ok": 0, "echecs": [("g1", "réseau indisponible")]})

    def test_global_id_absent_reste_exploitable(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer, \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.sleep"):
            creer.return_value.connector.put_catalog.side_effect = Exception("boom")
            bilan = renvoyer_ressources_connues(conf, [{"resource_title": "sans global_id"}])
        self.assertEqual(bilan, {"ok": 0, "echecs": [("?", "boom")]})


class TestMediaFileDejaComplet(unittest.TestCase):
    def test_file_size_et_checksum_hash_presents(self):
        media = {"media_type": "FILE", "file_size": 42191,
                "checksum": {"algo": "SHA-256", "hash": "abc123"}}
        self.assertTrue(_media_file_deja_complet(media))

    def test_file_size_absent(self):
        media = {"media_type": "FILE", "checksum": {"algo": "SHA-256", "hash": "abc123"}}
        self.assertFalse(_media_file_deja_complet(media))

    def test_checksum_absent(self):
        media = {"media_type": "FILE", "file_size": 42191}
        self.assertFalse(_media_file_deja_complet(media))

    def test_checksum_sans_hash(self):
        media = {"media_type": "FILE", "file_size": 42191, "checksum": {"algo": "SHA-256"}}
        self.assertFalse(_media_file_deja_complet(media))

    def test_placeholder_mode_copie_non_complet(self):
        # Le FILE "placeholder" posé par mode.py avant upload (mode copie) n'a ni
        # file_size ni checksum tant que publier_dataset() ne l'a pas uploadé.
        media = {"media_type": "FILE", "connector": {"url": "À_RENSEIGNER_APRES_DEPOT_SUR_NOEUD"}}
        self.assertFalse(_media_file_deja_complet(media))


class TestDedoublonnerMediasFile(unittest.TestCase):
    def test_retire_les_doublons_et_realigne_les_fichiers(self):
        medias = [
            {"media_type": "FILE", "media_name": "a.csv"},
            {"media_type": "FILE", "media_name": "b.json"},
            {"media_type": "FILE", "media_name": "a.csv"},
            {"media_type": "FILE", "media_name": "b.json"},
            {"media_type": "SERVICE", "media_name": "source-metadata"},
        ]
        fichiers = ["/d/a.csv", "/d/b.json", "/d/a.csv", "/d/b.json"]
        medias_ok, fichiers_ok = _dedoublonner_medias_file(medias, fichiers)
        self.assertEqual([m["media_name"] for m in medias_ok],
                         ["a.csv", "b.json", "source-metadata"])
        self.assertEqual(fichiers_ok, ["/d/a.csv", "/d/b.json"])

    def test_aucun_doublon_renvoie_les_entrees_inchangees(self):
        medias = [{"media_type": "FILE", "media_name": "a.csv"},
                  {"media_type": "SERVICE", "media_name": "source-metadata"}]
        medias_ok, fichiers_ok = _dedoublonner_medias_file(medias, ["/d/a.csv"])
        self.assertEqual(medias_ok, medias)
        self.assertEqual(fichiers_ok, ["/d/a.csv"])

    def test_service_du_meme_nom_non_dedoublonne(self):
        # Les SERVICE ne sont pas indexés par fichiers_filtres et portent des URLs distinctes.
        medias = [{"media_type": "FILE", "media_name": "a.csv"},
                  {"media_type": "SERVICE", "media_name": "dup"},
                  {"media_type": "SERVICE", "media_name": "dup"}]
        medias_ok, _ = _dedoublonner_medias_file(medias, ["/d/a.csv"])
        self.assertEqual(len(medias_ok), 3)

    def test_fichier_manquant_pour_un_media_file_non_ajoute(self):
        # Plus de médias FILE que de chemins fournis : le FILE en trop est conservé
        # (dédoublonné) mais n'ajoute pas de chemin.
        medias = [{"media_type": "FILE", "media_name": "a.csv"},
                  {"media_type": "FILE", "media_name": "b.json"}]
        _, fichiers_ok = _dedoublonner_medias_file(medias, ["/d/a.csv"])
        self.assertEqual(fichiers_ok, ["/d/a.csv"])


class TestDemanderCreationOrganisation(unittest.TestCase):
    """Depuis le 2026-10-14 : création via le NŒUD (POST catalog/organizations avec
    l'auth nœud habituelle), plus un appel portail direct — voir le docstring de
    demander_creation_organisation() pour le contexte complet (401 invalid_client
    rencontré en conditions réelles contre le portail de préprod RM avec des
    identifiants portail séparés, alors que le compte nœud existant fonctionne pour
    cette même opération via cette route)."""

    ORG = {"organization_id": "org-1", "organization_name": "MyDataBall",
           "organization_summary": "Producteur de données ouvertes."}

    def test_succes_retourne_luuid_cree_sur_le_noeud(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        reponse = {"organization_id": "uuid-noeud", "organization_name": "MyDataBall",
                   "organization_status": "DRAFT"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.request.return_value = reponse
            resultat = demander_creation_organisation(conf, self.ORG)
        self.assertEqual(resultat, "uuid-noeud")
        creer.assert_called_once_with(conf)
        _, kwargs = creer.return_value.connector.request.call_args
        self.assertEqual(kwargs["relative_url"], "catalog/organizations")
        self.assertEqual(kwargs["req_method"], "POST")
        self.assertEqual(kwargs["body"]["organization_name"], "MyDataBall")
        self.assertNotIn("organization_id", kwargs["body"])  # décidé par le nœud/portail, jamais par nous

    def test_transmet_summary_et_url(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        org = {**self.ORG, "organization_url": "https://www.mydataball.fr"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.request.return_value = {"organization_id": "uuid-noeud"}
            demander_creation_organisation(conf, org)
        corps = creer.return_value.connector.request.call_args[1]["body"]
        self.assertEqual(corps["organization_summary"], "Producteur de données ouvertes.")
        self.assertEqual(corps["organization_url"], "https://www.mydataball.fr")

    def test_url_absente_non_envoyee(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.request.return_value = {"organization_id": "uuid-noeud"}
            demander_creation_organisation(conf, self.ORG)
        corps = creer.return_value.connector.request.call_args[1]["body"]
        self.assertNotIn("organization_url", corps)

    def test_reponse_sans_organization_id_retourne_none(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.request.return_value = {"message": "inattendu"}
            self.assertIsNone(demander_creation_organisation(conf, self.ORG))

    def test_echec_noeud_retourne_none(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.request.side_effect = Exception("503 catalog unreachable")
            self.assertIsNone(demander_creation_organisation(conf, self.ORG))

    def test_aucun_identifiant_portail_requis(self):
        """Contrairement à l'ancienne implémentation : ne nécessite ni url_portail, ni
        usr_portail/pwd_portail — seule l'auth nœud habituelle est utilisée."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}  # pas de clé *_portail
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.request.return_value = {"organization_id": "uuid-noeud"}
            resultat = demander_creation_organisation(conf, self.ORG)
        self.assertEqual(resultat, "uuid-noeud")


class TestDemanderMiseAJourOrganisation(unittest.TestCase):
    ORG = {"organization_id": "uuid-portail", "organization_name": "MyDataBall",
           "organization_summary": "Producteur de données ouvertes."}

    def _session(self, sess, get_reponse=None, get_json=None, create_statut=200, create_corps=None,
                 start_statut=200):
        """Câble une session feinte pour le flux DRAFT_UPDATE : token (POST), GET de
        l'organisation, POST du brouillon, PUT du démarrage."""
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        sess.post.side_effect = [rep_token, mock.Mock(status_code=create_statut,
                                                      text="erreur",
                                                      json=mock.Mock(return_value=create_corps if create_corps is not None else {}))]
        rep_get = get_reponse if get_reponse is not None else mock.Mock(status_code=200)
        if get_json is not None:
            rep_get.json.return_value = get_json
        sess.get.return_value = rep_get
        sess.put.return_value = mock.Mock(status_code=start_statut, text="erreur")
        return sess

    def test_sans_url_portail_no_op_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(demander_mise_a_jour_organisation(conf, self.ORG))
        sess.put.assert_not_called()
        sess.post.assert_not_called()
        sess.get.assert_not_called()

    def test_name_ou_id_manquant_false_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertFalse(demander_mise_a_jour_organisation(
                conf, {"organization_id": None, "organization_name": "X"}))
        sess.post.assert_not_called()

    def test_succes_suit_le_flux_draft_update(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_corps={"asset": {"uuid": "uuid-portail"}})
            self.assertTrue(demander_mise_a_jour_organisation(conf, self.ORG))
        # GET de l'organisation puis POST du brouillon puis PUT du démarrage
        self.assertEqual(sess.get.call_args[0][0],
                         "http://portail.test/strukture/v1/organizations/request/uuid-portail")
        self.assertEqual(sess.post.call_count, 2)  # token + brouillon
        args_brouillon, kwargs_brouillon = sess.post.call_args_list[1]
        self.assertEqual(args_brouillon[0], "http://portail.test/strukture/v1/organizations/tasks")
        corps = kwargs_brouillon["json"]
        self.assertEqual(corps["uuid"], "uuid-portail")
        self.assertEqual(corps["name"], "MyDataBall")
        self.assertEqual(corps["form"]["type"], "DRAFT_UPDATE")
        args_start, kwargs_start = sess.put.call_args
        self.assertEqual(args_start[0], "http://portail.test/strukture/v1/organizations/tasks/start")
        # le form est réinjecté dans l'asset de la tâche avant démarrage
        self.assertEqual(kwargs_start["json"]["asset"]["form"]["type"], "DRAFT_UPDATE")
        self.assertEqual(kwargs_start["headers"]["Authorization"], "Bearer tok123")

    def test_champs_du_formulaire_au_format_values_liste(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_corps={"asset": {}})
            demander_mise_a_jour_organisation(conf, self.ORG)
        form = sess.post.call_args_list[1][1]["json"]["form"]
        sections = {s["name"]: s["fields"] for s in form["sections"]}
        champs = {f["definition"]["name"]: f["values"] for f in
                  sections["organization-process-draft/update-organization"]}
        self.assertEqual(champs["name"], ["MyDataBall"])
        self.assertEqual(champs["description"], ["Producteur de données ouvertes."])
        # le format attendu par le portail est « values » (liste), jamais « value »
        champ_nom = next(f for f in sections["organization-process-draft/update-organization"]
                         if f["definition"]["name"] == "name")
        self.assertIn("values", champ_nom)
        self.assertNotIn("value", champ_nom)
        message = sections["organization-process-draft/update-message-to-moderator"]
        self.assertEqual(message[0]["definition"]["name"], "updateMessageToModerator")
        self.assertTrue(message[0]["values"][0])

    def test_description_tronquee_a_1024(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        org = {**self.ORG, "organization_summary": "x" * 2000}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_corps={"asset": {}})
            demander_mise_a_jour_organisation(conf, org)
        corps = sess.post.call_args_list[1][1]["json"]
        self.assertEqual(len(corps["description"]), 1024)

    def test_url_valide_transmise_dans_le_formulaire(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        org = {**self.ORG, "organization_url": "https://www.mydataball.fr/"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_corps={"asset": {}})
            demander_mise_a_jour_organisation(conf, org)
        form = sess.post.call_args_list[1][1]["json"]["form"]
        section = next(s for s in form["sections"]
                       if s["name"] == "organization-process-draft/update-organization")
        champs = {f["definition"]["name"]: f["values"][0] for f in section["fields"]}
        self.assertEqual(champs["url"], "https://www.mydataball.fr/")

    def test_url_non_conforme_ignoree(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        org = {**self.ORG, "organization_url": "pas une url"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_corps={"asset": {}})
            demander_mise_a_jour_organisation(conf, org)
        form = sess.post.call_args_list[1][1]["json"]["form"]
        section = next(s for s in form["sections"]
                       if s["name"] == "organization-process-draft/update-organization")
        noms = [f["definition"]["name"] for f in section["fields"]]
        self.assertNotIn("url", noms)

    def test_organization_inconnue_du_portail_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, get_reponse=mock.Mock(status_code=404))
            self.assertFalse(demander_mise_a_jour_organisation(conf, self.ORG))
        # seule la requête de token a été faite côté POST, pas de brouillon
        sess.put.assert_not_called()

    def test_auth_portail_echoue_false_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = Exception("réseau indisponible")
            self.assertFalse(demander_mise_a_jour_organisation(conf, self.ORG))
        sess.put.assert_not_called()

    def test_creation_brouillon_refusee_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_statut=400)
            self.assertFalse(demander_mise_a_jour_organisation(conf, self.ORG))
        sess.put.assert_not_called()

    def test_demarrage_refuse_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_corps={"asset": {}}, start_statut=400)
            self.assertFalse(demander_mise_a_jour_organisation(conf, self.ORG))

    def test_deja_a_jour_aucune_demande_deposee(self):
        """Le nœud n'expose pas organization_url : sans ce garde-fou, chaque passage
        redéposerait une demande de modification identique."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        org = {**self.ORG, "organization_url": "https://www.mydataball.fr"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, get_json={"organization_summary": "Producteur de données ouvertes.",
                                          "organization_url": "https://www.mydataball.fr"})
            self.assertTrue(demander_mise_a_jour_organisation(conf, org))
        sess.post.assert_called_once()  # token uniquement, pas de brouillon
        sess.put.assert_not_called()

    def test_description_differente_depose_une_demande(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, get_json={"organization_summary": "Ancienne description.",
                                          "organization_url": None},
                          create_corps={"asset": {}})
            self.assertTrue(demander_mise_a_jour_organisation(conf, self.ORG))
        self.assertEqual(sess.post.call_count, 2)  # token + brouillon
        sess.put.assert_called_once()

    def test_image_transmise_comme_champ_organizationImage(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_corps={"asset": {}})
            demander_mise_a_jour_organisation(conf, self.ORG, image_id="img-uuid-1")
        form = sess.post.call_args_list[1][1]["json"]["form"]
        section = next(s for s in form["sections"]
                       if s["name"] == "organization-process-draft/update-organization")
        champ_img = next(f for f in section["fields"]
                         if f["definition"]["name"] == "organizationImage")
        self.assertEqual(champ_img["values"], ["img-uuid-1"])
        self.assertEqual(champ_img["definition"]["type"], "ATTACHMENT")

    def test_image_absente_aucun_champ_image(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_corps={"asset": {}})
            demander_mise_a_jour_organisation(conf, self.ORG)
        form = sess.post.call_args_list[1][1]["json"]["form"]
        section = next(s for s in form["sections"]
                       if s["name"] == "organization-process-draft/update-organization")
        noms = [f["definition"]["name"] for f in section["fields"]]
        self.assertNotIn("organizationImage", noms)

    def test_image_force_le_depot_meme_si_deja_a_jour(self):
        """Le portail n'expose pas « a déjà un logo » : fournir une image doit forcer
        le dépôt malgré une description/url déjà à jour."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        org = {**self.ORG, "organization_url": "https://www.mydataball.fr"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, get_json={"organization_summary": self.ORG["organization_summary"],
                                          "organization_url": "https://www.mydataball.fr"},
                          create_corps={"asset": {}})
            self.assertTrue(demander_mise_a_jour_organisation(conf, org, image_id="img-9"))
        self.assertEqual(sess.post.call_count, 2)  # token + brouillon
        sess.put.assert_called_once()


class TestTeleverserPieceJointe(unittest.TestCase):
    def test_sans_url_portail_no_op_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(televerser_piece_jointe(conf, b"x", "logo.png", "image/png"))
        sess.post.assert_not_called()

    def test_succes_retourne_l_uuid(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            rep_token = mock.Mock(status_code=200)
            rep_token.json.return_value = {"access_token": "tok123"}
            rep_upload = mock.Mock(status_code=201)
            rep_upload.json.return_value = "uuid-image-1"
            sess.post.side_effect = [rep_token, rep_upload]
            self.assertEqual(
                televerser_piece_jointe(conf, b"\x89PNG...", "logo.png", "image/png"),
                "uuid-image-1")
        args, kwargs = sess.post.call_args_list[1]
        self.assertEqual(args[0], "http://portail.test/strukture/v1/attachments")
        self.assertEqual(kwargs["files"]["file"][0], "logo.png")
        self.assertEqual(kwargs["files"]["file"][2], "image/png")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok123")

    def test_uuid_en_corps_texte_brut(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            rep_token = mock.Mock(status_code=200)
            rep_token.json.return_value = {"access_token": "tok123"}
            rep_upload = mock.Mock(status_code=201, text='"uuid-texte"')
            rep_upload.json.side_effect = ValueError("pas du json")
            sess.post.side_effect = [rep_token, rep_upload]
            self.assertEqual(televerser_piece_jointe(conf, b"x", "l.png", "image/png"),
                             "uuid-texte")

    def test_type_non_supporte_ignore_sans_upload(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(televerser_piece_jointe(conf, b"x", "logo.svg", "image/svg+xml"))
        sess.post.assert_not_called()

    def test_taille_excessive_ignoree_sans_upload(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(televerser_piece_jointe(conf, b"x" * (10 * 1024 * 1024 + 1),
                                                      "logo.png", "image/png"))
        sess.post.assert_not_called()

    def test_echec_upload_retourne_none(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            rep_token = mock.Mock(status_code=200)
            rep_token.json.return_value = {"access_token": "tok123"}
            rep_upload = mock.Mock(status_code=400, text="refusé")
            sess.post.side_effect = [rep_token, rep_upload]
            self.assertIsNone(televerser_piece_jointe(conf, b"x", "logo.png", "image/png"))

    def test_auth_portail_echoue_retourne_none(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = Exception("réseau indisponible")
            self.assertIsNone(televerser_piece_jointe(conf, b"x", "logo.png", "image/png"))


class TestDemanderDetachementProducteur(unittest.TestCase):
    def test_sans_url_portail_no_op_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(demander_detachement_producteur(conf, "uuid-portail"))
        sess.delete.assert_not_called()
        sess.post.assert_not_called()

    def test_succes_emet_un_delete_vers_linked_producers_request_uuid(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=200)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertTrue(demander_detachement_producteur(conf, "uuid-portail"))
        args, kwargs = sess.delete.call_args
        self.assertEqual(args[0], "http://portail.test/strukture/v1/linked-producers/request/uuid-portail")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok123")

    def test_auth_portail_echoue_false_sans_delete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = Exception("réseau indisponible")
            self.assertFalse(demander_detachement_producteur(conf, "uuid-portail"))
        sess.delete.assert_not_called()

    def test_401_renouvelle_le_token_et_rejoue(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_401 = mock.Mock(status_code=401, text="Unauthorized")
        rep_ok = mock.Mock(status_code=200)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.side_effect = [rep_401, rep_ok]
            self.assertTrue(demander_detachement_producteur(conf, "uuid-portail"))
        self.assertEqual(sess.post.call_count, 2)  # token initial + renouvellement
        self.assertEqual(sess.delete.call_count, 2)

    def test_echec_404_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=404, text="Not Found")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertFalse(demander_detachement_producteur(conf, "uuid-portail"))


class TestDemanderSuppressionOrganisation(unittest.TestCase):
    def test_sans_url_portail_no_op_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(demander_suppression_organisation(conf, "uuid-portail"))
        sess.delete.assert_not_called()
        sess.post.assert_not_called()

    def test_succes_emet_un_delete_vers_organizations_request_uuid(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=204)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertTrue(demander_suppression_organisation(conf, "uuid-portail"))
        args, kwargs = sess.delete.call_args
        self.assertEqual(args[0], "http://portail.test/strukture/v1/organizations/request/uuid-portail")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok123")

    def test_auth_portail_echoue_false_sans_delete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = Exception("réseau indisponible")
            self.assertFalse(demander_suppression_organisation(conf, "uuid-portail"))
        sess.delete.assert_not_called()

    def test_401_renouvelle_le_token_et_rejoue(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_401 = mock.Mock(status_code=401, text="Unauthorized")
        rep_ok = mock.Mock(status_code=204)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.side_effect = [rep_401, rep_ok]
            self.assertTrue(demander_suppression_organisation(conf, "uuid-portail"))
        self.assertEqual(sess.post.call_count, 2)  # token initial + renouvellement
        self.assertEqual(sess.delete.call_count, 2)

    def test_echec_404_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=404, text="Not Found")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertFalse(demander_suppression_organisation(conf, "uuid-portail"))


class TestSupprimerDatasetPortail(unittest.TestCase):
    def test_sans_url_portail_no_op_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(supprimer_dataset_portail(conf, "gid-1"))
        sess.delete.assert_not_called()
        sess.post.assert_not_called()

    def test_succes_emet_un_delete_vers_kalim_resources(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=200)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertTrue(supprimer_dataset_portail(conf, "gid-1"))
        args, kwargs = sess.delete.call_args
        self.assertEqual(args[0], "http://portail.test/kalim/v1/resources/gid-1")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok123")

    def test_401_renouvelle_le_token_et_rejoue(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_401 = mock.Mock(status_code=401, text="Unauthorized")
        rep_ok = mock.Mock(status_code=200)
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.side_effect = [rep_401, rep_ok]
            self.assertTrue(supprimer_dataset_portail(conf, "gid-1"))
        self.assertEqual(sess.post.call_count, 2)  # token initial + renouvellement
        self.assertEqual(sess.delete.call_count, 2)

    def test_echec_404_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=404, text="Not Found")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertFalse(supprimer_dataset_portail(conf, "gid-1"))


if __name__ == "__main__":
    unittest.main()
