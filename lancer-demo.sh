#!/bin/sh
# Lance StationAlerte en mode démonstration sur Mac ou Linux (équivalent de lancer-demo.bat sous Windows) :
# tout tourne dans Docker (base, e-mails, API, surveillant, site), sans Python, uv ni Node.js.
# Usage, depuis le dossier du projet : sh lancer-demo.sh   (ou ./lancer-demo.sh)
set -e
cd "$(dirname "$0")"

echo "[1/5] Docker..."
if ! docker info >/dev/null 2>&1; then
  echo "ERREUR : Docker ne répond pas. Lance Docker Desktop (ou le service Docker), puis relance ce script."
  exit 1
fi

echo "[2/5] Ports libres..."
# Une API déjà lancée hors Docker (mode développement) bloquerait celle de Docker.
if curl -s -o /dev/null http://localhost:8000/docs && \
   ! docker compose --profile app ps --services --status running 2>/dev/null | grep -qx api; then
  echo "ERREUR : le port 8000 est déjà pris (API lancée hors Docker ?). Arrête-la, puis relance ce script."
  exit 1
fi

echo "[3/5] Construction et démarrage (premier lancement : quelques minutes)..."
docker compose --profile app up -d --build

echo "[4/5] Premier import des stations par le surveillant..."
tries=0
until [ "$(curl -s -o /dev/null -w '%{http_code}' 'http://localhost:8000/stations?limit=1')" = "200" ]; do
  tries=$((tries + 1))
  if [ "$tries" -ge 90 ]; then
    echo "ERREUR : l'API ne répond pas après 3 minutes. Voir « docker compose logs api worker »."
    exit 1
  fi
  sleep 2
done

echo "[5/5] Compte de démonstration (demo@test.fr / demo-stationalerte)..."
docker compose exec -T worker python -m app.demo creer

URL=http://localhost:4173
# Ouvre le navigateur : « open » sur Mac, « xdg-open » sous Linux ; sinon, l'adresse est affichée.
(open "$URL" 2>/dev/null || xdg-open "$URL" 2>/dev/null) >/dev/null || true

echo
echo "StationAlerte tourne dans Docker : site $URL - API http://localhost:8000/docs"
echo "E-mails de test : http://localhost:8025"
echo "Pour arrêter : docker compose --profile app stop"
