"""Configuration de la sortie console pour les messages de ce module.

Ce module utilise `logging` (pas `print()`, voir CHANGELOG 0.5.9) : une bibliothèque
partagée (ce toolkit, utilisé par plusieurs projets) ne doit pas décider
unilatéralement d'écrire sur stdout — c'est à l'application appelante de choisir.

Sans configuration explicite côté appelant, `logging` NE SE COMPORTE PAS comme
l'ancien `print()` : les messages de niveau ``INFO`` sont silencieusement perdus
(rien ne les affiche par défaut), mais ``WARNING``/``ERROR``, eux, ne disparaissent
PAS — Python les affiche quand même sur stderr via son handler de secours
(``logging.lastResort``), en texte brut sans aucun formatage de notre part. C'est le
cas le plus trompeur : un appelant qui ne capture que stdout perd les avertissements
sans jamais s'en rendre compte, loin d'un "tout disparaît" qu'on remarquerait vite.

:func:`configurer_sortie_console` installe un handler stdout en texte brut qui
reproduit l'ancien comportement ``print()`` à l'identique (tous les niveaux à partir
de INFO, sur stdout, sans timestamp/niveau ajoutés par ``logging`` — déjà présents
dans le texte des messages eux-mêmes, ex. ``[RUDI]``). Idempotente et sûre à appeler
plusieurs fois, y compris dans une boucle de menu (n'ajoute jamais de handler en
double, pas de messages dupliqués) ; réaffecte aussi le flux à chaque appel plutôt que
de le figer à la création (utile si l'appelant redirige stdout entre deux appels, ex.
en test).
"""
import logging
import sys

_NOM_LOGGER = "rudi_harvest_toolkit"


def configurer_sortie_console(flux=None) -> None:
    """Installe (ou met à jour) un handler texte brut sur le logger de ce module,
    pour que ses messages (statuts, avertissements, erreurs) apparaissent sur la
    console exactement comme avant la migration print() -> logging.

    ``flux`` : par défaut ``sys.stdout``, résolu à CHAQUE appel plutôt qu'une seule
    fois à la création du handler (contrairement à ``logging.StreamHandler(flux)``
    tout seul, qui figerait un flux obsolète si l'appelant redirige stdout ensuite).

    Définit aussi ``propagate = False`` : évite un double affichage si l'application
    appelante configure par ailleurs ``logging.basicConfig()`` au niveau racine — bon
    choix pour un outil autonome (CLI), à reconsidérer si ce module est utilisé dans
    une pile applicative plus large qui centralise ses logs au niveau racine.
    """
    flux = flux if flux is not None else sys.stdout
    logger = logging.getLogger(_NOM_LOGGER)
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(flux)
            break
    else:
        handler = logging.StreamHandler(flux)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
