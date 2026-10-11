"""
Publication RUDI partagée entre tous les scripts de moisson.

Élimine le bloc try/except de publication copié dans les scripts de moisson.

La configuration du nœud (`conf`) est désormais **chargée par l'appelant** puis passée
explicitement : plus d'appel caché à ``charger_conf_rudi()`` sans argument à l'intérieur.

Usage :
    from rudi_harvest_toolkit.publish import publier_si_configue
    rudi_publie = publier_si_configue(conf, rudi_metadata, fichiers_filtres)
"""

import threading

from .rudi_client import noeud_pret, publier_dataset

# Les publications peuvent arriver depuis plusieurs threads (workers d'un harvest
# parallélisé). Le get_or_create d'organisations/contacts côté nœud n'est pas
# idempotent sous concurrence (risque de doublons), donc on sérialise la publication —
# le téléchargement/filtrage, lui, peut rester parallèle.
_verrou_publication = threading.Lock()

# local_id des JDD effectivement (re)publiés avec succès depuis le dernier
# demarrer_nouveau_run() — sert de signal "nouveau ou modifié" pour les étapes en aval :
# publier_si_configue() n'est appelé par chaque script de moisson que lorsqu'il y a
# réellement quelque chose de changé à publier (chacun a son propre fast-path "rien de
# changé, on saute" en amont) — ce set est donc déjà exactement le bon périmètre, sans
# nouvelle détection de changement à inventer. Protégé par le même verrou que la
# publication elle-même.
_local_ids_publies_ce_run: set[str] = set()


def demarrer_nouveau_run() -> None:
    """À appeler au début d'un run de pipeline — vide l'accumulateur du run précédent.
    Nécessaire car le process peut vivre plus longtemps qu'un run (dashboard), contrairement
    à un script autonome toujours lancé dans un process frais."""
    with _verrou_publication:
        _local_ids_publies_ce_run.clear()


def local_ids_publies_ce_run() -> set[str]:
    """local_id des JDD (re)publiés avec succès depuis le dernier demarrer_nouveau_run()."""
    with _verrou_publication:
        return set(_local_ids_publies_ce_run)


def enregistrer_local_id_publie(local_id: str | None) -> None:
    """Enregistre un local_id comme publié ce run. Appelé par publier_si_configue() ET par
    d'éventuelles boucles de rattrapage qui appellent publier_dataset() directement — les
    deux chemins doivent alimenter le même accumulateur."""
    if not local_id:
        return
    with _verrou_publication:
        _local_ids_publies_ce_run.add(local_id)


def publier_si_configue(conf: dict | None, rudi_metadata: dict,
                        fichiers_filtres: list[str]) -> bool:
    """Tente de publier sur le nœud RUDI si celui-ci est configuré.

    `conf` est le dict de configuration du nœud (url/usr/pwd) déjà chargé par l'appelant,
    ou None si aucun nœud n'est configuré.

    Retourne True si la publication a réussi, False si elle a échoué
    ou si le nœud n'est pas configuré.
    """
    if not conf:
        print("  [RUDI] conf absente — publication ignorée.")
        return False

    # Sonde préalable : un nœud injoignable échouerait de toute façon, mais après le
    # retry/backoff de la lib de publication et sur une trace peu lisible. Un éventuel
    # rattrapage reprendra ce False au prochain passage.
    if not noeud_pret(conf):
        print("  [RUDI] nœud injoignable — publication différée.")
        return False

    try:
        with _verrou_publication:
            publier_dataset(conf=conf, rudi_metadata=rudi_metadata,
                            fichiers_filtres=fichiers_filtres)
        enregistrer_local_id_publie(rudi_metadata.get("local_id"))
        print("  [RUDI] Publié.")
        return True
    except Exception as e:
        print(f"  [RUDI] Erreur publication : {e}")
        return False
