import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models, security
from app.api import auth
from app.api.auth import REGISTER_SENT as SENT
from app.main import app
from app.security import hash_password, verify_password

client = TestClient(app)
PASSWORD = "correct-horse-battery"
pytestmark = pytest.mark.usefixtures("api_db")


def register(email="alice@example.fr", password=PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password})


def stored_user(session, email="alice@example.fr") -> models.User:
    return session.scalars(select(models.User).where(models.User.email == email)).one()


def test_inscription_reussie(session, outbox):
    response = register()

    assert response.status_code == 202
    assert response.json() == {"detail": SENT}  # ni identifiant ni e-mail : rien à comparer entre deux cas
    assert stored_user(session).email_verified_at is None  # pas encore confirmé
    [mail] = outbox
    assert (mail["to"], mail["subject"]) == ("alice@example.fr", "StationAlerte : confirmez votre adresse e-mail")
    assert "http://localhost:5173/#confirm=" in mail["body"]


def test_seule_l_empreinte_argon2id_est_stockee(session):
    register()

    password_hash = stored_user(session).password_hash
    assert password_hash.startswith("$argon2id$")
    assert PASSWORD not in password_hash
    assert verify_password(password_hash, PASSWORD)


def test_meme_mot_de_passe_deux_empreintes_differentes():
    # Le « sel » aléatoire : deux comptes avec le même mot de passe n'ont pas la même empreinte.
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_verification_du_mot_de_passe():
    password_hash = hash_password(PASSWORD)
    assert verify_password(password_hash, PASSWORD)
    assert not verify_password(password_hash, PASSWORD + "x")
    assert not verify_password("pas-une-empreinte", PASSWORD)  # empreinte abîmée : refus, pas de plantage


def test_email_mis_en_minuscules(session):
    register(email="Alice@Example.FR")
    assert stored_user(session).email == "alice@example.fr"


@pytest.mark.parametrize("second_email", ["alice@example.fr", "ALICE@example.fr"])
def test_compte_confirme_meme_reponse_et_rien_ne_change(session, outbox, second_email):
    # V7.3 : avant, « Un compte existe déjà » (409) révélait qui est inscrit.
    register()
    user = stored_user(session)
    user.email_verified_at, old_hash = datetime.now(UTC), user.password_hash
    session.flush()
    response = register(email=second_email, password="un-autre-mot-de-passe")

    assert (response.status_code, response.json()) == (202, {"detail": SENT})
    session.refresh(user)
    assert user.password_hash == old_hash  # mot de passe inchangé
    assert outbox[-1]["subject"] == "StationAlerte : vous avez déjà un compte"
    assert "#confirm=" not in outbox[-1]["body"]
    assert len(session.scalars(select(models.User).where(models.User.email == "alice@example.fr")).all()) == 1


@pytest.mark.parametrize("email", ["pas-un-email", "alice@", "@example.fr", "", "a" * 250 + "@example.fr", "al\x00ice@example.fr"])
def test_email_invalide_refuse(email):
    assert register(email=email).status_code == 422


@pytest.mark.parametrize(("length", "status"), [(11, 422), (12, 202), (128, 202), (129, 422)])
def test_longueur_du_mot_de_passe(length, status):
    assert register(password="x" * length).status_code == status


def test_champ_manquant_refuse():
    assert client.post("/auth/register", json={"email": "alice@example.fr"}).status_code == 422


def test_la_reponse_ne_contient_jamais_le_mot_de_passe():
    ok = register()
    refused = register(email="autre@example.fr", password="court-secret")  # trop court : 422

    for response in (ok, refused):
        assert PASSWORD not in response.text
        assert "court-secret" not in response.text  # FastAPI recopiait la valeur refusée dans l'erreur 422
        assert "argon2" not in response.text


@pytest.mark.parametrize("lookalike", ["Ａlice@example.fr", "ＡＲＴＨＵＲ@example.fr", "ａｒｔｈｕｒ@ｅｘａｍｐｌｅ.ｆｒ"])
def test_sosie_unicode_du_meme_email_refuse(session, lookalike):
    # « Ａ » pleine largeur (claviers asiatiques) : sans normalisation NFKC, c'était un second compte.
    register()
    register(email=lookalike)
    assert stored_user(session).email == "alice@example.fr"  # un seul compte (.one() échouerait sinon)


def test_ligature_normalisee(session):
    register(email="ﬁlou@example.fr")
    assert stored_user(session, "filou@example.fr")  # « ﬁ » → « fi »


def test_afflux_refuse_tout_de_suite_sans_bloquer(monkeypatch):
    # Toutes les places de calcul prises : 503 immédiat (et non une attente qui bloquerait le reste du site).
    monkeypatch.setattr(security, "_slots", threading.BoundedSemaphore(1))
    security._slots.acquire()
    response = register()

    assert response.status_code == 503
    assert response.json() == {"detail": "Serveur occupé, réessayez dans un instant"}
    assert response.headers["retry-after"] == "1"


def test_champs_en_trop_ignores(session):
    # Impossible d'imposer sa propre empreinte ou ses préférences à l'inscription.
    client.post("/auth/register", json={
        "email": "alice@example.fr", "password": PASSWORD,
        "passwordHash": "x", "password_hash": "x", "notifyAvailable": True, "notify_available": True, "id": 1,
    })
    user = stored_user(session)
    session.refresh(user)
    assert user.password_hash.startswith("$argon2id$")
    assert user.notify_available is False
    assert user.id != 1


@pytest.mark.parametrize("password", ["mot\x00de-passe-long", "🚗" * 128, " " * 12])
def test_mots_de_passe_inhabituels_acceptes(password):
    # Octet nul, émojis (128 caractères, pas 128 octets), espaces : aucun ne fait planter Argon2.
    assert register(password=password).status_code == 202


@pytest.mark.parametrize("body", ['{"email":', "", "email=a@b.fr&password=x"])
def test_corps_illisible_refuse(body):
    assert client.post("/auth/register", content=body, headers={"Content-Type": "application/json"}).status_code == 422


def test_text_plain_refuse():
    # Un autre site peut envoyer du text/plain sans autorisation CORS : il ne doit pas créer de compte.
    body = '{"email": "csrf@example.fr", "password": "' + PASSWORD + '"}'
    assert client.post("/auth/register", content=body, headers={"Content-Type": "text/plain"}).status_code == 422


# --- Confirmation de l'adresse (V7.3) ---


def confirmation_token(outbox) -> str:
    return next(m["body"] for m in reversed(outbox) if "#confirm=" in m["body"]).split("#confirm=")[1].split()[0]


def login(password=PASSWORD):
    return client.post("/auth/login", json={"email": "alice@example.fr", "password": password})


def test_pas_de_connexion_avant_confirmation_puis_connexion(session, outbox):
    register()
    first_link = confirmation_token(outbox)
    refused = login()
    assert refused.status_code == 401 and refused.json() == {"detail": auth.LOGIN_FAILED}
    assert confirmation_token(outbox) != first_link  # un nouveau lien, l'ancien est annulé
    assert client.post("/auth/confirm-email", json={"token": first_link}).status_code == 400

    assert client.post("/auth/confirm-email", json={"token": confirmation_token(outbox)}).status_code == 204
    assert stored_user(session).email_verified_at is not None
    assert login().status_code == 200


def test_mauvais_mot_de_passe_sur_compte_non_confirme_reste_401(outbox):
    register()
    sent = len(outbox)
    assert login(password="mauvais-mot-de-passe").status_code == 401  # rien ne révèle le compte non confirmé
    assert len(outbox) == sent


def test_lien_de_confirmation_a_usage_unique_et_pas_de_connexion_automatique(outbox):
    register()
    token = confirmation_token(outbox)
    response = client.post("/auth/confirm-email", json={"token": token})
    assert response.status_code == 204 and "set-cookie" not in response.headers
    again = client.post("/auth/confirm-email", json={"token": token})
    assert again.status_code == 400
    assert again.json() == {"detail": "Lien invalide ou expiré. Connectez-vous pour en recevoir un nouveau."}


def test_lien_de_confirmation_expire_apres_24_h(session, outbox):
    register()
    token = confirmation_token(outbox)
    session.execute(models.EmailConfirmationToken.__table__.update().values(created_at=datetime.now(UTC) - timedelta(hours=25)))
    assert client.post("/auth/confirm-email", json={"token": token}).status_code == 400


@pytest.mark.parametrize("token", ["invente", "x" * 100, ""])
def test_lien_invente_refuse(token):
    assert client.post("/auth/confirm-email", json={"token": token}).status_code in (400, 422)


def test_compte_non_confirme_le_nouveau_mot_de_passe_remplace_l_ancien(session, outbox):
    # Quelqu'un a inscrit cette adresse avec SON mot de passe : le vrai propriétaire peut quand même s'inscrire.
    register(password="mot-de-passe-du-pirate")
    register(password=PASSWORD)
    client.post("/auth/confirm-email", json={"token": confirmation_token(outbox)})
    assert login().status_code == 200
    assert login(password="mot-de-passe-du-pirate").status_code == 401


def test_au_plus_3_e_mails_de_confirmation_par_heure(outbox):
    for _ in range(3):
        assert register().status_code == 202
    response = register()
    assert response.status_code == 429  # pas d'inondation d'une boîte e-mail
    assert len(outbox) == 3


def test_renvoi_du_lien_a_la_connexion_aussi_limite(outbox):
    register()
    login()
    login()  # 3 e-mails : l'inscription + 2 renvois
    sent = len(outbox)
    refused = login()
    assert refused.status_code == 401 and refused.json() == {"detail": auth.LOGIN_FAILED}
    assert len(outbox) == sent


def test_inscription_puis_connexion_ne_revele_pas_si_l_adresse_a_un_compte(session, outbox):
    # Attaque (V7.5) : inscrire l'adresse d'un autre avec SON mot de passe, puis se connecter avec.
    # Compte existant (mot de passe inchangé) et adresse libre (compte créé, pas confirmé) : même réponse.
    session.add(models.User(email="inscrit@example.fr", password_hash=hash_password(PASSWORD),
                            email_verified_at=datetime.now(UTC)))
    session.flush()
    answers = []
    for email in ("inscrit@example.fr", "libre@example.fr"):
        client.post("/auth/register", json={"email": email, "password": "mot-de-passe-du-pirate"})
        response = client.post("/auth/login", json={"email": email, "password": "mot-de-passe-du-pirate"})
        answers.append((response.status_code, response.json(), "set-cookie" in response.headers))
    assert answers[0] == answers[1] == (401, {"detail": auth.LOGIN_FAILED}, False)


def test_mot_de_passe_oublie_confirme_aussi_l_adresse(session, outbox):
    register()
    client.post("/auth/password-reset/request", json={"email": "alice@example.fr"})
    reset = next(m["body"] for m in reversed(outbox) if "#reset=" in m["body"]).split("#reset=")[1].split()[0]
    assert client.post("/auth/password-reset/confirm", json={"token": reset, "password": "nouveau-mot-de-passe"}).status_code == 204
    assert stored_user(session).email_verified_at is not None
    assert login(password="nouveau-mot-de-passe").status_code == 200
