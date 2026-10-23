@echo off
rem Démarre StationAlerte en un double-clic : base PostgreSQL (Docker), API et site (mode développement).
rem Pour montrer le projet sans rien installer d'autre que Docker : lancer-demo.bat.
rem L'API, le surveillant (vérification du flux toutes les 10 min) et le site s'ouvrent chacun dans leur
rem fenêtre ; fermer une fenêtre arrête le programme correspondant.
chcp 65001 >nul
cd /d "%~dp0"

echo [1/5] Docker Desktop...
docker info >nul 2>&1 && goto docker_ok
echo        pas lancé : démarrage (jusqu'à 2 minutes)...
start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set /a tries=0
:wait_docker
timeout /t 2 /nobreak >nul
docker info >nul 2>&1 && goto docker_ok
set /a tries+=1
if %tries% lss 60 goto wait_docker
echo ERREUR : Docker ne répond pas. Lance Docker Desktop à la main, puis relance ce fichier.
pause
exit /b 1
:docker_ok

echo [2/5] Base de données PostgreSQL...
rem Le mode démonstration (lancer-demo.bat) occupe les mêmes ports : il faut l'arrêter d'abord.
docker compose --profile app ps --services --status running 2>nul | findstr /b "api worker site" >nul
if not errorlevel 1 (
  echo ERREUR : le mode démonstration ^(lancer-demo.bat^) tourne encore.
  echo          L'arrêter avec « docker compose --profile app stop », puis relancer ce fichier.
  pause
  exit /b 1
)
docker compose up -d --wait
if errorlevel 1 (
  echo ERREUR : la base n'a pas démarré.
  pause
  exit /b 1
)

echo [3/5] Configuration et tables...
if not exist backend\.env copy backend\.env.example backend\.env >nul
pushd backend
uv run alembic upgrade head
if errorlevel 1 (
  popd
  echo ERREUR : migrations impossibles.
  pause
  exit /b 1
)
popd

echo [4/5] Dépendances du site...
pushd frontend
rem « call » obligatoire : npm est lui-même un .bat, sans call ce script s'arrêterait ici.
call npm install --no-audit --no-fund
if errorlevel 1 (
  popd
  echo ERREUR : npm install a échoué.
  pause
  exit /b 1
)
popd

echo [5/5] Lancement de l'API, du surveillant et du site...
start "StationAlerte - API" /d "%~dp0backend" cmd /k uv run fastapi dev app/main.py
start "StationAlerte - Surveillance" /d "%~dp0backend" cmd /k uv run python -m app.worker
start "StationAlerte - Site" /d "%~dp0frontend" cmd /k npm run dev
rem Laisse le temps au site de démarrer avant d'ouvrir le navigateur.
timeout /t 5 /nobreak >nul
start "" http://localhost:5173

echo.
echo StationAlerte tourne : site http://localhost:5173 - API http://localhost:8000/docs
echo E-mails de test (mot de passe oublié) : http://localhost:8025
echo Pour arrêter : fermer les trois fenêtres, puis « docker compose stop » pour la base et les e-mails.
timeout /t 10
