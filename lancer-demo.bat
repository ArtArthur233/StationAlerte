@echo off
rem Lance StationAlerte en mode démonstration, en un double-clic : tout tourne dans Docker (base, e-mails,
rem API, surveillant, site), sans Python, uv ni Node.js. Pour développer, utiliser plutôt lancer-dev.bat.
rem Les deux ne peuvent pas tourner en même temps (mêmes ports, un seul surveillant).
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

echo [2/5] Ports libres...
rem L'API de lancer-dev.bat (port 8000) bloquerait celle de Docker.
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul
if not errorlevel 1 (
  docker compose --profile app ps --services --status running 2>nul | findstr /b "api" >nul
  if errorlevel 1 (
    echo ERREUR : le port 8000 est déjà pris, sans doute par lancer-dev.bat.
    echo          Ferme les fenêtres « StationAlerte - API / Surveillance / Site », puis relance ce fichier.
    pause
    exit /b 1
  )
)

echo [3/5] Construction et démarrage (premier lancement : quelques minutes)...
docker compose --profile app up -d --build
if errorlevel 1 (
  echo ERREUR : le démarrage a échoué.
  pause
  exit /b 1
)

echo [4/5] Premier import des stations par le surveillant...
set /a tries=0
:wait_api
timeout /t 2 /nobreak >nul
set code=000
for /f %%c in ('curl -s -o nul -w "%%{http_code}" "http://localhost:8000/stations?limit=1"') do set code=%%c
if "%code%"=="200" goto api_ok
set /a tries+=1
if %tries% lss 90 goto wait_api
echo ERREUR : l'API ne répond pas après 3 minutes. Voir « docker compose logs api worker ».
pause
exit /b 1
:api_ok

echo [5/5] Compte de démonstration (demo@test.fr / demo-stationalerte)...
docker compose exec -T worker python -m app.demo creer
start "" http://localhost:4173

echo.
echo StationAlerte tourne dans Docker : site http://localhost:4173 - API http://localhost:8000/docs
echo E-mails de test : http://localhost:8025
echo Pour arrêter : « docker compose --profile app stop » depuis ce dossier (ou Docker Desktop, bouton Stop).
timeout /t 15
