import pytest


@pytest.fixture(autouse=True)
def _vider_cache_token_portail():
    """Le cache mémoire-process du jeton OAuth2 portail (rudi_client._token_portail,
    bug réel corrigé le 2026-11-14) ne doit jamais fuiter entre deux tests : sans ça,
    un test qui mocke session.post et vérifie assert_called_once_with() pourrait
    recevoir un HIT de cache laissé par un test précédent utilisant la même
    (url_portail, usr, pwd), et échouer de façon non déterministe selon l'ordre
    d'exécution."""
    from rudi_harvest_toolkit import rudi_client

    rudi_client._vider_cache_token_portail()
    yield
    rudi_client._vider_cache_token_portail()
