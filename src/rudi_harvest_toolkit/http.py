import urllib3
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Session HTTP partagée par tous les connecteurs : pool de connexions (évite une
# poignée TCP/TLS par appel sur les ~200+ JDD moissonnés) + retry/backoff sur les
# erreurs transitoires (429, 5xx, erreurs réseau). Pas de retry sur les 4xx
# (404/403...), qui doivent propager immédiatement.
_retry = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=False,
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
session.headers["User-Agent"] = (
    "rudi-harvest-toolkit/0.1.0 "
    "(https://github.com/anomalyco/rudi-harvest-toolkit; contact@example.org)"
)


def desactiver_verification_tls() -> None:
    """Désactive la vérification du certificat TLS pour le reste du run (session
    partagée par tous les connecteurs — pas de retour en arrière possible sans
    relancer le processus).

    Risque réel : une attaque de l'ordinateur au milieu pourrait alors intercepter
    identifiants et données sans que rien ne le signale. À n'appeler qu'après une
    confirmation explicite de l'utilisateur final (voir les appelants dans
    rudi-commune-starterkit) — jamais par défaut, jamais sans confirmation."""
    session.verify = False
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
