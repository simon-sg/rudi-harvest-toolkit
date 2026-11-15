"""Tests unitaires de rudi_client (config explicite, email de repli) — sans réseau."""
import json
import os
import tempfile
import unittest
from unittest import mock

import requests
from rudi_node_write.utils.err import HttpError

from rudi_harvest_toolkit import rudi_client
from rudi_harvest_toolkit.rudi_client import (
    _api_version,
    _dedoublonner_medias_file,
    _identifiants_portail,
    _media_file_deja_complet,
    _organization_id_deterministe,
    _token_portail,
    charger_conf_rudi,
    demander_archivage_organisation,
    demander_creation_organisation,
    demander_detachement_producteur,
    demander_suppression_organisation,
    desactiver_verification_tls,
    email_par_defaut,
    EtatPortailIndisponibleError,
    etat_tache_organisation_portail,
    global_id_pour_local_id,
    IdentifiantsPortailAbsentsError,
    lister_organisations,
    marquer_organisations_traitees,
    noeud_pret,
    organisation_par_id,
    organisation_par_nom,
    organisations_nouvellement_validees,
    renvoyer_ressources_connues,
    supprimer_dataset,
    supprimer_dataset_portail,
    supprimer_organisation,
    valider_alignement_medias,
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


class TestApiVersion(unittest.TestCase):
    def setUp(self):
        # _api_version met en cache par url_catalog — plusieurs tests ci-dessous
        # réutilisent volontairement la même URL, à isoler les uns des autres.
        rudi_client._cache_api_version.clear()

    def test_version_valide_retournee(self):
        conf = {"url": "http://localhost:4032", "url_catalog": "http://localhost:4030/catalog"}
        reponse = mock.Mock(text="1.4.0")
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = reponse
            self.assertEqual(_api_version(conf), "1.4.0")

    def test_reponse_404_retombe_sur_defaut(self):
        # Route répondant mais sans /version (corps JSON d'erreur) : ne doit jamais être
        # pris pour une version valide — sinon ce texte atterrit dans metadata_info.api_version
        # et le nœud rejette la publication avec "Incorrect RUDI metadata version".
        conf = {"url": "http://localhost:4032", "url_catalog": "http://localhost:4030/catalog"}
        reponse = mock.Mock(text='{"message":"Route \'GET /version\' not found"}')
        reponse.raise_for_status = mock.Mock(side_effect=Exception("404"))
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = reponse
            self.assertEqual(_api_version(conf), "1.4.0")

    def test_connexion_impossible_retombe_sur_defaut(self):
        conf = {"url": "http://localhost:4032"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.side_effect = ConnectionError("refusée")
            self.assertEqual(_api_version(conf), "1.4.0")

    def test_mis_en_cache_apres_1_echec_pour_plusieurs_jdd(self):
        # Simule un run à 13 JDD sur un nœud dont le catalog n'est pas joignable sur
        # l'URL déduite : 2 appels réseau (1 tentative + 1 retry avant de figer
        # l'échec en cache) pour le 1er JDD, 0 pour les 12 suivants — pas 13 appels
        # au total, c'est le bug corrigé le 2026-11-14 (65 s perdues en pratique).
        conf = {"url": "http://localhost:4032"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess, \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.sleep"):
            sess.get.side_effect = ConnectionError("refusée")
            for _ in range(13):
                self.assertEqual(_api_version(conf), "1.4.0")
            self.assertEqual(sess.get.call_count, 2)

    def test_echec_transitoire_recupere_par_le_retry(self):
        # Un seul aléa de connexion sur le 1er essai ne doit pas figer la version
        # par défaut pour tout le run si le 2e essai, lui, réussit.
        conf = {"url": "http://localhost:4032"}
        reponse_ok = mock.Mock(text="2.0.0")
        reponse_ok.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess, \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.sleep"):
            sess.get.side_effect = [ConnectionError("refusée"), reponse_ok]
            self.assertEqual(_api_version(conf), "2.0.0")
            self.assertEqual(sess.get.call_count, 2)

    def test_cache_distinct_par_url_catalog(self):
        conf_a = {"url": "http://localhost:4032", "url_catalog": "http://localhost:4030/catalog"}
        conf_b = {"url": "http://localhost:5032", "url_catalog": "http://localhost:5030/catalog"}
        reponse_a = mock.Mock(text="1.4.0")
        reponse_a.raise_for_status = mock.Mock()
        reponse_b = mock.Mock(text="2.0.0")
        reponse_b.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.side_effect = [reponse_a, reponse_b]
            self.assertEqual(_api_version(conf_a), "1.4.0")
            self.assertEqual(_api_version(conf_b), "2.0.0")
            self.assertEqual(_api_version(conf_a), "1.4.0")  # depuis le cache
            self.assertEqual(sess.get.call_count, 2)


class TestNoeudPret(unittest.TestCase):
    def test_reponse_200_pret(self):
        conf = {"url": "http://localhost:4032"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = mock.Mock(status_code=200)
            self.assertTrue(noeud_pret(conf))

    def test_reponse_non_200_pas_pret_sans_exception_sortie(self):
        conf = {"url": "http://localhost:4032"}
        erreur = {}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = mock.Mock(status_code=404)
            self.assertFalse(noeud_pret(conf, erreur_sortie=erreur))
        # Pas une exception : rien à distinguer pour l'appelant (ex. pas de
        # proposition d'ignorer la vérification TLS, qui n'aurait aucun sens ici).
        self.assertNotIn("exception", erreur)

    def test_exception_reseau_remontee_dans_erreur_sortie(self):
        conf = {"url": "http://localhost:4032"}
        erreur = {}
        exc = requests.exceptions.ConnectionError("DNS cassé")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.side_effect = exc
            self.assertFalse(noeud_pret(conf, erreur_sortie=erreur))
        self.assertIs(erreur["exception"], exc)

    def test_erreur_sortie_optionnel(self):
        # Ne doit jamais planter si l'appelant ne fournit pas erreur_sortie (valeur
        # par défaut None) — tous les appelants existants avant ce changement.
        conf = {"url": "http://localhost:4032"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.side_effect = requests.exceptions.SSLError("certificat auto-signé")
            self.assertFalse(noeud_pret(conf))


class TestDesactiverVerificationTls(unittest.TestCase):
    def test_desactive_la_verification_sur_la_session_partagee(self):
        with mock.patch("rudi_harvest_toolkit.http.session") as sess, \
                mock.patch("rudi_harvest_toolkit.http.urllib3.disable_warnings") as avertir:
            desactiver_verification_tls()
            self.assertFalse(sess.verify)
            avertir.assert_called_once()


class TestEmailParDefaut(unittest.TestCase):
    def test_slug_et_domaine(self):
        self.assertEqual(email_par_defaut("Rennes Métropole"), "rennes-metropole@example.org")

    def test_accents_retires(self):
        self.assertEqual(email_par_defaut("Observatoire de l'Environnement"), "observatoire-de-l-environnement@example.org")

    def test_nom_vide_retombe_sur_contact(self):
        self.assertEqual(email_par_defaut(""), "contact@example.org")

    def test_unique_par_nom(self):
        self.assertNotEqual(email_par_defaut("Insee"), email_par_defaut("OEB"))


class TestTokenPortail(unittest.TestCase):
    """Bug réel (2026-11-08, nœud source) : un url_portail enregistré avec un slash
    final (ex. profil interactif) donnait http://portail//oauth2/token (double slash,
    401 côté portail) — seul ce point d'entrée ne normalisait pas, contrairement à tous
    les autres appels portail du fichier."""

    def test_url_portail_avec_slash_final_normalisee(self):
        reponse = mock.Mock(status_code=200)
        reponse.json.return_value = {"access_token": "tok"}
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = reponse
            token = _token_portail("http://portail/", "u", "p")
        self.assertEqual(token, "tok")
        sess.post.assert_called_once_with(
            "http://portail/oauth2/token",
            auth=("u", "p"),
            data={"grant_type": "client_credentials", "username": "u", "password": "p"},
            timeout=30,
        )

    def test_url_portail_sans_slash_final_inchangee(self):
        reponse = mock.Mock(status_code=200)
        reponse.json.return_value = {"access_token": "tok"}
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = reponse
            _token_portail("http://portail", "u", "p")
        sess.post.assert_called_once_with(
            "http://portail/oauth2/token",
            auth=("u", "p"),
            data={"grant_type": "client_credentials", "username": "u", "password": "p"},
            timeout=30,
        )

    def test_appels_repetes_memes_identifiants_un_seul_post(self):
        """Bug réel corrigé le 2026-11-14 : chacun des 9 points d'entrée portail de ce
        fichier redemandait un jeton, soit 6-8 authentifications par run."""
        reponse = mock.Mock(status_code=200)
        reponse.json.return_value = {"access_token": "tok", "expires_in": 3600}
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = reponse
            t1 = _token_portail("http://portail", "u", "p")
            t2 = _token_portail("http://portail", "u", "p")
        self.assertEqual(t1, t2)
        sess.post.assert_called_once()

    def test_identifiants_differents_pas_de_partage_de_cache(self):
        reponse = mock.Mock(status_code=200)
        reponse.json.return_value = {"access_token": "tok", "expires_in": 3600}
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = reponse
            _token_portail("http://portail", "u", "p")
            _token_portail("http://portail", "autre-usr", "p")
        self.assertEqual(sess.post.call_count, 2)

    def test_jeton_expire_redemande(self):
        reponse = mock.Mock(status_code=200)
        reponse.json.return_value = {"access_token": "tok", "expires_in": 40}
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess, \
             mock.patch("rudi_harvest_toolkit.rudi_client.time.time") as m_time:
            sess.post.return_value = reponse
            m_time.return_value = 1_000.0
            _token_portail("http://portail", "u", "p")
            # expires_in=40, marge=30 -> mis en cache 10s ; +11s = expiré
            m_time.return_value = 1_000.0 + 11
            _token_portail("http://portail", "u", "p")
        self.assertEqual(sess.post.call_count, 2)


class TestIdentifiantsPortail(unittest.TestCase):
    """Bug réel corrigé le 2026-11-14 : usr_portail/pwd_portail absents retombait
    silencieusement sur les identifiants du nœud (usr/pwd), qui ne sont presque
    jamais aussi des identifiants ROBOT portail valides — le portail refusait
    l'authentification avec un 401 opaque, sans jamais dire que la vraie cause était
    une configuration incomplète."""

    def test_identifiants_presents_retournes_tels_quels(self):
        conf = {"usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp"}
        self.assertEqual(_identifiants_portail(conf), ("up", "pp"))

    def test_usr_portail_absent_leve_sans_repli_sur_usr(self):
        conf = {"usr": "u", "pwd": "p", "pwd_portail": "pp"}
        with self.assertRaises(IdentifiantsPortailAbsentsError):
            _identifiants_portail(conf)

    def test_pwd_portail_absent_leve_sans_repli_sur_pwd(self):
        conf = {"usr": "u", "pwd": "p", "usr_portail": "up"}
        with self.assertRaises(IdentifiantsPortailAbsentsError):
            _identifiants_portail(conf)

    def test_aucun_des_deux_leve(self):
        conf = {"usr": "u", "pwd": "p"}
        with self.assertRaises(IdentifiantsPortailAbsentsError):
            _identifiants_portail(conf)


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
            params={"organization_status": "VALIDATED"}, timeout=10,
        )


class TestOrganisationParNom(unittest.TestCase):
    _CONF = {"url": "http://n:3032", "usr": "u", "pwd": "p", "url_catalog": "http://n:3030/catalog"}

    def test_trouvee_par_nom_normalise(self):
        orgs = [
            {"organization_id": "org-1", "organization_name": "Commune de Gévezé",
             "organization_status": "DRAFT", "linked_producer_status": None},
        ]
        reponse = mock.Mock()
        reponse.json.return_value = orgs
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = reponse
            # Casse et accents différents : doit matcher quand même.
            resultat = organisation_par_nom(self._CONF, "commune de geveze")
        self.assertEqual(resultat, orgs[0])
        sess.get.assert_called_once_with(
            "http://n:3030/catalog/v1/organizations", timeout=10,
        )

    def test_absente_retourne_none(self):
        reponse = mock.Mock()
        reponse.json.return_value = [{"organization_name": "Autre organisation"}]
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = reponse
            self.assertIsNone(organisation_par_nom(self._CONF, "Commune de Gévezé"))

    def test_erreur_reseau_propagee(self):
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.side_effect = ConnectionError("refusée")
            with self.assertRaises(ConnectionError):
                organisation_par_nom(self._CONF, "Commune de Gévezé")

    def test_erreur_http_propagee(self):
        reponse = mock.Mock()
        reponse.raise_for_status = mock.Mock(side_effect=Exception("500"))
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = reponse
            with self.assertRaises(Exception):
                organisation_par_nom(self._CONF, "Commune de Gévezé")

    def test_statut_absent_du_champ_nest_pas_une_erreur(self):
        # Organisation trouvée mais sans organization_status (champ non garanti selon
        # l'historique de l'organisation) : organisation_par_nom() ne filtre jamais sur
        # ce champ, à l'appelant de décider quoi faire d'un statut absent.
        orgs = [{"organization_id": "org-1", "organization_name": "Commune de Gévezé"}]
        reponse = mock.Mock()
        reponse.json.return_value = orgs
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = reponse
            resultat = organisation_par_nom(self._CONF, "Commune de Gévezé")
        self.assertNotIn("organization_status", resultat)


class TestOrganisationParId(unittest.TestCase):
    _CONF = {"url": "http://n:3032", "usr": "u", "pwd": "p", "url_catalog": "http://n:3030/catalog"}

    def test_trouvee_par_id_exact(self):
        orgs = [
            {"organization_id": "org-1", "organization_name": "Commune de Gévezé"},
            {"organization_id": "org-2", "organization_name": "Commune de Pacé"},
        ]
        reponse = mock.Mock()
        reponse.json.return_value = orgs
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = reponse
            resultat = organisation_par_id(self._CONF, "org-2")
        self.assertEqual(resultat, orgs[1])

    def test_absente_retourne_none(self):
        reponse = mock.Mock()
        reponse.json.return_value = [{"organization_id": "org-1"}]
        reponse.raise_for_status = mock.Mock()
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.return_value = reponse
            self.assertIsNone(organisation_par_id(self._CONF, "org-inconnu"))

    def test_erreur_reseau_propagee(self):
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.get.side_effect = ConnectionError("refusée")
            with self.assertRaises(ConnectionError):
                organisation_par_id(self._CONF, "org-1")


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


class TestValiderAlignementMedias(unittest.TestCase):
    def test_ordre_correct_ne_leve_pas(self):
        medias = [
            {"media_type": "FILE", "media_name": "a.csv"},
            {"media_type": "SERVICE", "media_name": "source-metadata"},
        ]
        valider_alignement_medias(medias, ["/d/a.csv"])

    def test_tolere_un_file_hybride_deja_complet_apres_les_fichiers_reels(self):
        medias = [
            {"media_type": "FILE", "media_name": "a.geojson"},
            {"media_type": "FILE", "media_name": "a.csv", "file_size": 10,
             "checksum": {"hash": "abc"}},
        ]
        valider_alignement_medias(medias, ["/d/a.geojson"])

    def test_leve_si_un_file_hybride_complet_precede_un_fichier_reel(self):
        # Ordre « naturel » mais fautif : le GeoJSON ajouté après le CSV hybride
        # existant — la boucle d'upload écraserait le CSV hybride avec les infos
        # d'upload du GeoJSON, sans jamais uploader le GeoJSON lui-même.
        medias = [
            {"media_type": "FILE", "media_name": "a.csv", "file_size": 10,
             "checksum": {"hash": "abc"}},
            {"media_type": "FILE", "media_name": "a.geojson"},
        ]
        with self.assertRaises(ValueError):
            valider_alignement_medias(medias, ["/d/a.geojson"])

    def test_leve_si_comptage_incoherent(self):
        medias = [{"media_type": "FILE", "media_name": "a.csv"}]
        with self.assertRaises(ValueError):
            valider_alignement_medias(medias, ["/d/a.csv", "/d/b.csv"])

    def test_leve_si_service_precede_un_fichier_reel(self):
        medias = [
            {"media_type": "SERVICE", "media_name": "source-metadata"},
            {"media_type": "FILE", "media_name": "a.csv"},
        ]
        with self.assertRaises(ValueError):
            valider_alignement_medias(medias, ["/d/a.csv"])

    def test_aucun_fichier_et_aucun_media_file_reel_ne_leve_pas(self):
        medias = [{"media_type": "FILE", "media_name": "a.csv", "file_size": 10,
                    "checksum": {"hash": "abc"}}]
        valider_alignement_medias(medias, [])


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
        # Requis par le nœud (400 sinon, constaté le 2026-10-15) : on génère notre propre
        # UUID et le nœud l'accepte tel quel à cette étape.
        self.assertTrue(kwargs["body"]["organization_id"])

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

    def test_organization_id_toujours_envoye_sous_peine_de_400(self):
        """Régression (2026-10-15) : le nœud exige organization_id dans le corps du
        POST (400 "La propriété 'organization_id' doit être définie" sinon, constaté
        contre RM) — absent lors du 1er test du 2026-10-14. La fonction doit toujours
        le générer elle-même, jamais compter sur le nœud pour l'assigner."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.request.return_value = {"organization_id": "uuid-noeud"}
            demander_creation_organisation(conf, self.ORG)
        corps = creer.return_value.connector.request.call_args[1]["body"]
        self.assertIn("organization_id", corps)
        self.assertTrue(corps["organization_id"])

    def test_aucun_identifiant_portail_requis(self):
        """Contrairement à l'ancienne implémentation : ne nécessite ni url_portail, ni
        usr_portail/pwd_portail — seule l'auth nœud habituelle est utilisée."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}  # pas de clé *_portail
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.request.return_value = {"organization_id": "uuid-noeud"}
            resultat = demander_creation_organisation(conf, self.ORG)
        self.assertEqual(resultat, "uuid-noeud")

    def test_organization_id_envoye_est_deterministe(self):
        """2026-11-13 : l'id envoyé au nœud n'est plus un uuid4 aléatoire mais dérivé
        du nom — identique à chaque appel pour le même nom, pour qu'une 2e tentative
        (après un échec ambigu, ou avant que le nœud ait fini d'indexer la 1ère) vise
        la même ressource plutôt que d'en créer une 2e distincte (voir backlog :
        doublon observé en conditions réelles sur le nœud de démo RM)."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.request.return_value = {"organization_id": "uuid-noeud"}
            demander_creation_organisation(conf, self.ORG)
            demander_creation_organisation(conf, self.ORG)
        corps_appel_1 = creer.return_value.connector.request.call_args_list[0][1]["body"]
        corps_appel_2 = creer.return_value.connector.request.call_args_list[1][1]["body"]
        self.assertEqual(corps_appel_1["organization_id"], corps_appel_2["organization_id"])
        self.assertEqual(
            corps_appel_1["organization_id"],
            _organization_id_deterministe(self.ORG["organization_name"]),
        )

    def test_doublon_recupere_explicitement_apres_echec_creation(self):
        """Le nœud refuse la recréation (contrainte d'unicité sur organization_id,
        vérifiée dans le schéma Mongoose du nœud) parce que l'organisation a déjà été
        créée par une tentative précédente avec le même id déterministe — on la
        retrouve explicitement par cet id plutôt que d'abandonner, pour ne pas perdre
        le lien dès ce run."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        org_id_attendu = _organization_id_deterministe(self.ORG["organization_name"])
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer, \
             mock.patch("rudi_harvest_toolkit.rudi_client.organisation_par_id") as par_id:
            creer.return_value.connector.request.side_effect = Exception(
                "400 organization_id already exists")
            par_id.return_value = {"organization_id": org_id_attendu,
                                    "organization_name": self.ORG["organization_name"]}
            resultat = demander_creation_organisation(conf, self.ORG)
        self.assertEqual(resultat, org_id_attendu)
        par_id.assert_called_once_with(conf, org_id_attendu)

    def test_echec_creation_sans_organisation_existante_retourne_none(self):
        """La récupération explicite ne doit pas masquer un vrai échec (nœud
        injoignable, portail en panne...) : si l'organisation n'est pas retrouvée par
        son id déterministe non plus, le comportement best-effort existant (None,
        jamais d'exception) est inchangé."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer, \
             mock.patch("rudi_harvest_toolkit.rudi_client.organisation_par_id") as par_id:
            creer.return_value.connector.request.side_effect = Exception("503 catalog unreachable")
            par_id.return_value = None
            self.assertIsNone(demander_creation_organisation(conf, self.ORG))

    def test_echec_de_la_recuperation_elle_meme_ne_leve_pas(self):
        """Si organisation_par_id() échoue à son tour (nœud injoignable pour de bon),
        la fonction reste best-effort : pas d'exception propagée, retourne None comme
        avant ce correctif."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer, \
             mock.patch("rudi_harvest_toolkit.rudi_client.organisation_par_id") as par_id:
            creer.return_value.connector.request.side_effect = Exception("503 catalog unreachable")
            par_id.side_effect = ConnectionError("injoignable")
            self.assertIsNone(demander_creation_organisation(conf, self.ORG))


class TestDemanderArchivageOrganisation(unittest.TestCase):
    def _session(self, sess, get_statut=200, get_json=None, create_statut=200,
                 create_corps=None, start_statut=200):
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        sess.post.side_effect = [rep_token, mock.Mock(
            status_code=create_statut, text="erreur",
            json=mock.Mock(return_value=create_corps if create_corps is not None else {}))]
        rep_get = mock.Mock(status_code=get_statut)
        rep_get.json.return_value = get_json if get_json is not None else {}
        sess.get.return_value = rep_get
        sess.put.return_value = mock.Mock(status_code=start_statut, text="erreur")
        return sess

    def test_sans_url_portail_no_op_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(demander_archivage_organisation(conf, "uuid-1", "Doublon"))
        sess.get.assert_not_called()
        sess.post.assert_not_called()

    def test_organisation_inconnue_du_portail_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, get_statut=404)
            self.assertFalse(demander_archivage_organisation(conf, "uuid-1", "Doublon"))
        sess.post.assert_called_once()  # seulement le token, jamais le brouillon

    def test_succes_suit_le_flux_draft_archive(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_corps={"asset": {"uuid": "uuid-1"}})
            self.assertTrue(demander_archivage_organisation(conf, "uuid-1", "Doublon"))
        self.assertEqual(sess.get.call_args[0][0],
                         "http://portail.test/strukture/v1/organizations/request/uuid-1")
        args_brouillon, kwargs_brouillon = sess.post.call_args_list[1]
        self.assertEqual(args_brouillon[0], "http://portail.test/strukture/v1/organizations/tasks")
        corps = kwargs_brouillon["json"]
        self.assertEqual(corps["uuid"], "uuid-1")
        self.assertEqual(corps["form"]["type"], "DRAFT_ARCHIVE")
        args_start, kwargs_start = sess.put.call_args
        self.assertEqual(args_start[0], "http://portail.test/strukture/v1/organizations/tasks/start")
        self.assertEqual(kwargs_start["json"]["asset"]["form"]["type"], "DRAFT_ARCHIVE")

    def test_champs_du_formulaire(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_corps={"asset": {}})
            demander_archivage_organisation(conf, "uuid-1", "Doublon", message="msg test")
        form = sess.post.call_args_list[1][1]["json"]["form"]
        section = form["sections"][0]
        self.assertEqual(section["name"], "organization-process-draft/archive-organization")
        champs = {f["definition"]["name"]: f["values"] for f in section["fields"]}
        # Régression du bug réel du 2026-11-14 : sans ce champ, le gateway BPMN
        # ExclusiveGateway_1 route silencieusement vers la branche « Modification »
        # plutôt qu'« Archivage » (confirmé en traçant act_hi_actinst) — la demande
        # est acceptée (200) mais n'archive jamais l'organisation.
        self.assertEqual(champs["draftType"], ["archive"])
        self.assertEqual(champs["organizationArchiveMode"], ["DISENGAGED"])
        self.assertEqual(champs["messageToModerator"], ["msg test"])

    def test_creation_refusee_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, create_statut=400)
            self.assertFalse(demander_archivage_organisation(conf, "uuid-1", "Doublon"))
        sess.put.assert_not_called()

    def test_auth_portail_echoue_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = Exception("réseau indisponible")
            self.assertFalse(demander_archivage_organisation(conf, "uuid-1", "Doublon"))


class TestEtatTacheOrganisationPortail(unittest.TestCase):
    def _session(self, sess, get_statut=200, get_json=None):
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        sess.post.return_value = rep_token
        rep_get = mock.Mock(status_code=get_statut)
        rep_get.json.return_value = get_json if get_json is not None else {}
        sess.get.return_value = rep_get
        return sess

    def test_sans_url_portail_leve_indisponible(self):
        """Pas de url_portail configurée : on ne SAIT pas si l'organisation existe
        encore côté portail — ne doit jamais être confondu avec un None confirmé."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            with self.assertRaises(EtatPortailIndisponibleError):
                etat_tache_organisation_portail(conf, "uuid-1")
        sess.get.assert_not_called()

    def test_organisation_absente_du_portail_retourne_none(self):
        """Bug réel corrigé le 2026-11-16 : la route précédente
        (GET /organizations/{uuid}) exige ADMINISTRATOR/MODERATOR, 401 systématique
        avec une identité PROVIDER pure — confirmé en conditions réelles en finalisant
        K2 de starterkit-tester. Route corrigée vers /organizations/request/{uuid}
        (PROVIDER-accessible, même route déjà utilisée par
        demander_archivage_organisation). Une fois l'archivage validé, l'organisation
        sort du scope de recherche de ce provider et le service lève
        AppServiceBadRequestException("Organization not found") — HTTP 400, pas 404 —
        donc les deux codes sont traités comme « organisation disparue »."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, get_statut=400)
            self.assertIsNone(etat_tache_organisation_portail(conf, "uuid-1"))
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, get_statut=404)
            self.assertIsNone(etat_tache_organisation_portail(conf, "uuid-1"))

    def test_erreur_portail_401_leve_indisponible_pas_none(self):
        """Un 401/500 transitoire ne doit JAMAIS être traité comme une confirmation
        d'archivage (l'organisation peut très bien être toujours vivante)."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, get_statut=401)
            with self.assertRaises(EtatPortailIndisponibleError):
                etat_tache_organisation_portail(conf, "uuid-1")

    def test_archivage_en_attente_renvoie_archive_in_progress(self):
        """``organization_status`` porte directement la valeur dérivée
        ARCHIVE_IN_PROGRESS pendant qu'une demande d'archivage est en attente de
        validation (NodeOrganizationMapper côté portail) — plus de champ
        functional_status/status séparé depuis le changement de route (NodeOrganization,
        pas Organization complète)."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self._session(sess, get_json={
                "organization_status": "ARCHIVE_IN_PROGRESS",
                "linked_producer_status": "DISENGAGED",
            })
            etat = etat_tache_organisation_portail(conf, "uuid-1")
        self.assertEqual(etat, {
            "organization_status": "ARCHIVE_IN_PROGRESS",
            "linked_producer_status": "DISENGAGED",
        })
        self.assertEqual(sess.get.call_args[0][0],
                         "http://portail.test/strukture/v1/organizations/request/uuid-1")

    def test_echec_reseau_leve_indisponible_pas_none(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = Exception("réseau indisponible")
            with self.assertRaises(EtatPortailIndisponibleError):
                etat_tache_organisation_portail(conf, "uuid-1")


class TestDemanderDetachementProducteur(unittest.TestCase):
    """Depuis le 2026-10-15 : détachement via le NŒUD (GET manager/api/catalog/portal/
    organizations/{id}/detach — **sans** segment `admin/`, voir test_succes_... ci-dessous ;
    ce segment fait tomber sur la route front du manager qui redirige silencieusement (308)
    vers l'UI, faux succès confirmé en conditions réelles), auth nœud habituelle. Trouvé en
    capturant le trafic réseau du bouton « détacher » de l'UI nœud (producerCard.js) —
    confirmé par capture HAR réelle contre RM. Plus besoin de url_portail ni d'identifiants
    portail séparés (l'ancien appel portail direct 401ait systématiquement sur RM/R7)."""

    def test_succes_emet_un_get_vers_la_route_nœud(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            self.assertTrue(demander_detachement_producteur(conf, "uuid-org"))
        creer.assert_called_once_with(conf)
        _, kwargs = creer.return_value.connector.request.call_args
        self.assertEqual(kwargs["relative_url"], "catalog/portal/organizations/uuid-org/detach")
        self.assertEqual(kwargs["req_method"], "GET")

    def test_pas_de_segment_admin_dans_le_chemin(self):
        """Régression (2026-10-15) : un chemin avec `admin/` (déduit à tort de la lecture
        du code source du nœud) fait tomber sur la route front du manager, qui redirige
        silencieusement (308) vers l'UI — faux succès, aucune tâche créée. Confirmé en
        conditions réelles (local) avant correction."""
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            demander_detachement_producteur(conf, "uuid-org")
        _, kwargs = creer.return_value.connector.request.call_args
        self.assertNotIn("admin/", kwargs["relative_url"])

    def test_aucun_identifiant_portail_requis(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}  # pas de clé *_portail
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer"):
            self.assertTrue(demander_detachement_producteur(conf, "uuid-org"))

    def test_echec_noeud_retourne_false(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.request.side_effect = Exception("503 catalog unreachable")
            self.assertFalse(demander_detachement_producteur(conf, "uuid-org"))

    def test_409_tache_deja_en_attente_retourne_true(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.request.side_effect = HttpError("Conflict", status=409)
            self.assertTrue(demander_detachement_producteur(conf, "uuid-org"))


class TestDemanderSuppressionOrganisation(unittest.TestCase):
    def test_sans_url_portail_no_op_sans_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            self.assertIsNone(demander_suppression_organisation(conf, "uuid-portail"))
        sess.delete.assert_not_called()
        sess.post.assert_not_called()

    def test_pwd_portail_absent_avertissement_explicite_pas_de_requete(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess, \
             self.assertLogs("rudi_harvest_toolkit.rudi_client", level="WARNING") as logs:
            self.assertFalse(demander_suppression_organisation(conf, "uuid-portail"))
        sess.delete.assert_not_called()
        sess.post.assert_not_called()
        self.assertTrue(any("pwd_portail" in message for message in logs.output))

    def test_succes_emet_un_delete_vers_organizations_request_uuid(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
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
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
                "url_portail": "http://portail.test"}
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.side_effect = Exception("réseau indisponible")
            self.assertFalse(demander_suppression_organisation(conf, "uuid-portail"))
        sess.delete.assert_not_called()

    def test_401_renouvelle_le_token_et_rejoue(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
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
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
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
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
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
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
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
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p", "usr_portail": "up", "pwd_portail": "pp",
                "url_portail": "http://portail.test"}
        rep_token = mock.Mock(status_code=200)
        rep_token.json.return_value = {"access_token": "tok123"}
        rep_del = mock.Mock(status_code=404, text="Not Found")
        with mock.patch("rudi_harvest_toolkit.rudi_client.session") as sess:
            sess.post.return_value = rep_token
            sess.delete.return_value = rep_del
            self.assertFalse(supprimer_dataset_portail(conf, "gid-1"))


class TestGlobalIdPourLocalId(unittest.TestCase):
    def test_trouve(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.filter_metadata_list.return_value = [{"global_id": "gid-1"}]
            self.assertEqual(global_id_pour_local_id(conf, "lid-1"), "gid-1")
        creer.return_value.filter_metadata_list.assert_called_once_with({"local_id": "lid-1"})

    def test_absent_retourne_none(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.filter_metadata_list.return_value = []
            self.assertIsNone(global_id_pour_local_id(conf, "lid-1"))


class TestSupprimerDataset(unittest.TestCase):
    def test_succes(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            self.assertTrue(supprimer_dataset(conf, "gid-1"))
        creer.return_value.connector.del_catalog.assert_called_once_with("resources/gid-1")

    def test_404_traite_comme_succes(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.del_catalog.side_effect = HttpError("Not Found", status=404)
            self.assertTrue(supprimer_dataset(conf, "gid-1"))

    def test_autre_erreur_echoue(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.del_catalog.side_effect = HttpError("panne", status=500)
            self.assertFalse(supprimer_dataset(conf, "gid-1"))


class TestSupprimerOrganisation(unittest.TestCase):
    def test_succes(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            self.assertTrue(supprimer_organisation(conf, "org-1"))
        creer.return_value.connector.delete_org_with_id.assert_called_once_with("org-1")

    def test_404_traite_comme_succes(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.delete_org_with_id.side_effect = HttpError("Not Found", status=404)
            self.assertTrue(supprimer_organisation(conf, "org-1"))

    def test_autre_erreur_echoue(self):
        conf = {"url": "http://n:3032", "usr": "u", "pwd": "p"}
        with mock.patch("rudi_harvest_toolkit.rudi_client._creer_writer") as creer:
            creer.return_value.connector.delete_org_with_id.side_effect = HttpError("conflit", status=409)
            self.assertFalse(supprimer_organisation(conf, "org-1"))


if __name__ == "__main__":
    unittest.main()
