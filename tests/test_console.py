"""Tests de configurer_sortie_console() — restaure le comportement print() d'avant
la migration vers logging (voir CHANGELOG 0.5.9), au-delà de la simple configuration
du handler (test de bout en bout via une vraie fonction émettrice du module)."""
import io
import logging
import unittest
from unittest import mock

from rudi_harvest_toolkit.console import configurer_sortie_console
from rudi_harvest_toolkit.publish import publier_si_configue


class TestConfigurerSortieConsole(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("rudi_harvest_toolkit")
        self._handlers_origine = list(self.logger.handlers)
        self._niveau_origine = self.logger.level
        self._propagate_origine = self.logger.propagate
        self.logger.handlers = []

    def tearDown(self):
        self.logger.handlers = self._handlers_origine
        self.logger.setLevel(self._niveau_origine)
        self.logger.propagate = self._propagate_origine

    def test_installe_un_handler_stdout_texte_brut(self):
        configurer_sortie_console()
        self.assertEqual(len(self.logger.handlers), 1)
        handler = self.logger.handlers[0]
        self.assertEqual(handler.formatter._fmt, "%(message)s")
        self.assertEqual(self.logger.level, logging.INFO)
        self.assertFalse(self.logger.propagate)

    def test_idempotent_pas_de_doublon_de_handler(self):
        configurer_sortie_console()
        configurer_sortie_console()
        configurer_sortie_console()
        self.assertEqual(len(self.logger.handlers), 1)

    def test_reaffecte_le_flux_a_chaque_appel(self):
        # Contrairement à logging.StreamHandler(flux) seul (qui figerait le flux du
        # 1er appel) : un appelant qui redirige stdout entre deux appels (ex. tests)
        # doit voir le handler suivre, pas écrire dans un buffer mort.
        tampon_1 = io.StringIO()
        tampon_2 = io.StringIO()
        configurer_sortie_console(flux=tampon_1)
        configurer_sortie_console(flux=tampon_2)
        self.logger.warning("message")
        self.assertEqual(tampon_1.getvalue(), "")
        self.assertEqual(tampon_2.getvalue(), "message\n")

    def test_message_reel_du_toolkit_identique_a_lancien_print(self):
        # Bout en bout, pas seulement la configuration du handler : appelle une
        # vraie fonction émettrice (publier_si_configue) et vérifie le texte exact
        # qu'affichait l'ancien print("  [RUDI] conf absente — publication ignorée.").
        tampon = io.StringIO()
        configurer_sortie_console(flux=tampon)
        self.assertFalse(publier_si_configue(None, {}, []))
        self.assertEqual(tampon.getvalue(), "  [RUDI] conf absente — publication ignorée.\n")

    def test_pas_de_doublon_si_basicconfig_racine_configure_par_ailleurs(self):
        # propagate=False : un appelant qui configure logging.basicConfig() au
        # niveau racine (cas courant d'une application plus large) ne doit pas
        # voir les messages du toolkit apparaître deux fois.
        tampon = io.StringIO()
        with mock.patch("logging.lastResort", None):
            root_handler = logging.StreamHandler(tampon)
            root_handler.setFormatter(logging.Formatter("ROOT:%(message)s"))
            logging.getLogger().addHandler(root_handler)
            try:
                configurer_sortie_console(flux=tampon)
                self.logger.warning("message")
            finally:
                logging.getLogger().removeHandler(root_handler)
        self.assertEqual(tampon.getvalue(), "message\n")


if __name__ == "__main__":
    unittest.main()
