import urllib3
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Session HTTP partagée par tous les connecteurs : pool de connexions (évite une
# poignée TCP/TLS par appel sur les ~200+ JDD moissonnés) + retry/backoff sur les
# erreurs transitoires (429, 5xx, erreurs réseau). Pas de retry sur les 4xx
# (404/403...), qui doivent propager immédiatement.
#
# allowed_methods volontairement restreint aux méthodes idempotentes (GET/HEAD/
# OPTIONS/PUT/DELETE) — PAS POST : plusieurs appels POST de rudi_client.py créent
# une ressource côté portail sans clé d'idempotence (ex. tâche de création
# d'organisation, strukture/v1/organizations/tasks) ; un 5xx transitoire après que
# la requête a déjà été traitée côté serveur (réponse perdue en route) ferait
# retenter le même POST et créerait une 2e ressource en double. Un POST en échec
# propage donc immédiatement, comme un 4xx — c'est à l'appelant de décider s'il
# retente (voir le commentaire de packaging/entrypoint.py côté starterkit).
_retry = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS", "PUT", "DELETE"]),
)
_adapter = HTTPAdapter(max_retries=_retry, pool_maxsize=10)

# Timeout par défaut : filet de sécurité si un appel oublie timeout= (un seul
# oubli suffit à bloquer un run entier). Les timeout= explicites priment toujours.
_TIMEOUT_DEFAUT = 30


class _SessionAvecTimeout(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", _TIMEOUT_DEFAUT)
        return super().request(method, url, **kwargs)


session = _SessionAvecTimeout()
session.mount("https://", _adapter)
session.mount("http://", _adapter)
session.headers["User-Agent"] = "rudi-harvest-toolkit (https://github.com/simon-sg/rudi-harvest-toolkit)"


def desactiver_verification_tls() -> None:
    """Désactive la vérification du certificat TLS pour le reste du run (session
    partagée par tous les connecteurs — pas de retour en arrière possible sans
    relancer le processus).

    Risque réel : une attaque de l'ordinateur au milieu pourrait alors intercepter
    identifiants et données sans que rien ne le signale. À n'appeler qu'après une
    confirmation explicite de l'utilisateur final (voir les appelants dans
    rudi-commune-starterkit) — jamais par défaut, jamais sans confirmation.

    **Limite connue (documentée le 2026-11-14, pas corrigée — dépend d'une lib
    tierce)** : n'affecte QUE cette ``session`` ``requests`` partagée (appels
    annexes : résolution commune/SIREN, Wikipédia, data.gouv.fr, INSEE...). Le vrai
    chemin de publication/catalogue vers le nœud RUDI (``rudi_node_write``, lib
    tierce) passe par ``http.client.HTTPSConnection`` brut, qui ne partage pas cette
    session et n'expose aucun moyen de désactiver sa vérification TLS. Concrètement :
    sur un nœud de test au certificat auto-signé, un utilisateur qui confirme
    « ignorer le certificat » voit les appels annexes réussir, mais la publication
    elle-même échouera quand même sur l'erreur TLS — cette fonction ne résout pas ce
    cas précis malgré son nom. Corriger ça nécessiterait de patcher/contribuer à
    ``rudi_node_write`` (hors de ce dépôt)."""
    session.verify = False
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
