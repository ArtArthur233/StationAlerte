# Mots de passe : seule leur empreinte Argon2id est stockée, jamais le mot de passe lui-même.
import hashlib
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# Réglages par défaut d'argon2-cffi (RFC 9106 : Argon2id, 3 passes, 64 Mio, 4 fils), au-dessus du minimum
# OWASP (19 Mio, 2 passes). Environ 40 ms par calcul : imperceptible pour un humain, ruineux pour un robot
# qui essaie des millions de mots de passe. Les réglages sont écrits dans chaque empreinte.
_hasher = PasswordHasher()

# Au plus 4 calculs en même temps : 64 Mio chacun, sans limite 40 inscriptions simultanées demanderaient 2,5 Go.
_slots = threading.BoundedSemaphore(4)


class Busy(Exception):
    """Toutes les places de calcul Argon2 sont prises (afflux d'inscriptions ou de connexions)."""


@contextmanager
def _slot() -> Iterator[None]:
    # Sans attendre : une requête qui attendrait garderait un des 40 fils partagés par tout le site.
    # Constaté le 16/10/2026 : 200 inscriptions simultanées bloquaient une recherche de station 16 s.
    if not _slots.acquire(blocking=False):
        raise Busy
    try:
        yield
    finally:
        _slots.release()


def hash_password(password: str) -> str:
    with _slot():
        return _hasher.hash(password)  # un « sel » aléatoire est ajouté : deux mots identiques ≠ deux empreintes


def verify_password(password_hash: str, password: str) -> bool:
    with _slot():
        try:
            return _hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):  # mauvais mot de passe ou empreinte illisible
            return False


def needs_rehash(password_hash: str) -> bool:
    # Vrai si l'empreinte a été calculée avec d'anciens réglages : on la recalcule à la connexion.
    return _hasher.check_needs_rehash(password_hash)


@cache
def dummy_hash() -> str:
    # Empreinte d'un mot de passe que personne n'a : pour un e-mail inconnu, on vérifie quand même contre elle,
    # pour que la réponse prenne le même temps qu'avec un vrai compte (sinon le chrono révèle qui est inscrit).
    return _hasher.hash(secrets.token_urlsafe(32))


def new_token() -> tuple[str, str]:
    """Renvoie (jeton à donner à l'utilisateur, empreinte à stocker en base) : sessions, liens de réinitialisation."""
    token = secrets.token_urlsafe(32)  # 32 octets = 256 bits aléatoires : impossible à deviner
    return token, token_digest(token)


def token_digest(token: str) -> str:
    # SHA-256 et non Argon2 : un jeton de 256 bits aléatoires ne se devine pas, inutile de le ralentir,
    # et la base doit pouvoir le retrouver à chaque requête. Une copie de la table ne donne aucun jeton.
    return hashlib.sha256(token.encode()).hexdigest()
