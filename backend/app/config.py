# Réglages lus dans l'environnement (fichier backend/.env en local) : aucun secret dans le code.
import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL manquante : copier backend/.env.example en backend/.env")

# true en production (HTTPS) : cookie « Secure » et préfixe « __Host- ». false en local, faute de HTTPS
# (un navigateur refuse un cookie Secure sur http://localhost… sauf Chrome, d'où un réglage explicite).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

# Sites autorisés à appeler l'API depuis un navigateur (CORS) et à envoyer des requêtes qui modifient
# des données (protection CSRF) : le site en développement (npm run dev) et sa version compilée
# (npm run preview, celle qui a la politique de sécurité CSP, voir frontend/vite.config.ts).
ALLOWED_ORIGINS = ["http://localhost:5173", "http://localhost:4173"]

# E-mails : en local, Mailpit (docker-compose.yml) les capture et les affiche sur http://localhost:8025.
SMTP_HOST = os.environ.get("SMTP_HOST", "127.0.0.1")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "1025"))
MAIL_FROM = os.environ.get("MAIL_FROM", "StationAlerte <noreply@stationalerte.local>")
# Rythme de vérification du flux officiel par le surveillant (app/worker.py). 10 min (rythme de la source ; d'abord 60, ramené à 10 par l'utilisateur pour pouvoir tester).
# Jamais moins de 10 min : la source n'est elle-même mise à jour que toutes les 10 minutes.
CHECK_EVERY_MINUTES = int(os.environ.get("CHECK_EVERY_MINUTES", "10"))
if CHECK_EVERY_MINUTES < 10:
    raise RuntimeError("CHECK_EVERY_MINUTES doit valoir au moins 10 (rythme de la source officielle)")

# Adresse du site, pour les liens envoyés par e-mail (réinitialisation du mot de passe).
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

# Espace de démonstration (V8) : routes /demo qui changent la station fictive stationTest depuis le site, sans
# compte. Désactivé par défaut (routes en 404) : à n'activer qu'en local, jamais sur un site public.
DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"
# Fichier de stationTest (app/test_station.py), lu par le surveillant et écrit par l'espace de démonstration.
# Réglable pour Docker, où l'API et le surveillant le partagent dans un volume.
TEST_STATION_FILE = os.environ.get("TEST_STATION_FILE", "")
