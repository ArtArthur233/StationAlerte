# Architecture de StationAlerte

Trois schémas : la vue d'ensemble, le backend et les routes de l'API. Ils sont écrits en **Mermaid** (du texte) : GitHub les affiche comme des diagrammes, et les mettre à jour revient à modifier quelques lignes de ce fichier. Pour les voir dans VS Code : extension « Markdown Preview Mermaid Support ».

**Code couleur**, le même dans les trois schémas :

| Couleur | Élément |
|---|---|
| 🟦 bleu | site (navigateur, React) |
| 🟩 vert | API (FastAPI) |
| 🟧 orange | surveillant et commandes en ligne |
| 🟪 violet | base de données PostgreSQL |
| 🩷 rose | e-mails (Mailpit) |
| 🟥 rouge | sécurité |
| ⬜ gris pointillé | services publics extérieurs |
| 🟨 jaune | fichiers |



---

## 1. Vue d'ensemble

Quatre programmes : le **site** (dans le navigateur), l'**API**, le **surveillant** et la **base de données**, plus **Mailpit** qui capture les e-mails. Les flèches pointillées vont vers des services publics extérieurs.

```mermaid
%%{init: {"theme": "dark", "themeVariables": {"background": "transparent", "lineColor": "#9ca3af", "edgeLabelBackground": "#374151", "textColor": "#f9fafb"}}}%%
flowchart TB
    user(["👤 Visiteur"])
    site["🖥️ Site React + TypeScript<br/>dans le navigateur<br/>Vite en dev : 5173 · nginx en Docker : 4173"]
    storage[("localStorage<br/>choix du thème")]
    ign["🌐 Géoplateforme IGN<br/>tuiles du Plan IGN"]
    api["⚙️ API FastAPI<br/>port 8000"]
    geo["🌐 geo.api.gouv.fr<br/>communes"]
    db[("🐘 PostgreSQL 17<br/>port 5432")]
    worker["⏱️ Surveillant · app/worker.py<br/>toutes les 10 min"]
    feed["🌐 prix-carburants.gouv.fr<br/>flux instantané ZIP / XML"]
    files[/"📄 data/osm_brands.json<br/>data/test_station.json"/]
    osm["🌐 OpenStreetMap Overpass<br/>enseignes"]
    mailpit["✉️ Mailpit<br/>SMTP 1025 · boîte web 8025"]

    user --> site
    site --- storage
    site -.->|"images de carte"| ign
    site <==>|"JSON + cookie de session<br/>CORS, CSRF"| api
    api -.->|"rectangle d'une ville"| geo
    api <-->|"SQL"| db
    db <-->|"import, alertes, ménage"| worker
    worker -.->|"télécharge le flux"| feed
    worker ---|"lit"| files
    osm -.->|"à la main :<br/>python -m app.integrations.osm"| files
    worker -->|"e-mails d'alerte"| mailpit
    api -->|"e-mails des comptes<br/>et de la démo"| mailpit
    mailpit -.->|"le visiteur lit ses e-mails<br/>(boîte web, port 8025)"| user

    classDef front fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#111827
    classDef back fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#111827
    classDef work fill:#ffedd5,stroke:#ea580c,stroke-width:2px,color:#111827
    classDef data fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#111827
    classDef mail fill:#fce7f3,stroke:#db2777,stroke-width:2px,color:#111827
    classDef ext fill:#e5e7eb,stroke:#6b7280,stroke-width:2px,stroke-dasharray:5 3,color:#111827
    classDef file fill:#fef9c3,stroke:#ca8a04,stroke-width:2px,color:#111827
    classDef person fill:#ffffff,stroke:#111827,stroke-width:2px,color:#111827
    class site,storage front
    class api back
    class worker work
    class db data
    class mailpit mail
    class ign,geo,feed,osm ext
    class files file
    class user person
```

Points clés :
- **L'API ne télécharge jamais le flux officiel** : seul le surveillant le fait. Le site reste rapide même si la source est en panne.
- **Aucun secret dans le site** : il n'a que l'adresse de l'API. Le cookie de session est `HttpOnly`, illisible par JavaScript.
- **Aucun e-mail ne sort du PC** : tout arrive dans Mailpit.

---

## 2. Backend : les modules Python

`backend/app/`. Une flèche `A --> B` veut dire « A utilise B ».

**Côté API** (ce qui répond au site) :

```mermaid
%%{init: {"theme": "dark", "themeVariables": {"background": "transparent", "lineColor": "#9ca3af", "edgeLabelBackground": "#374151", "textColor": "#f9fafb"}}}%%
flowchart TB
    main["⚙️ main.py<br/>FastAPI, routes des stations,<br/>protections communes"]

    hRoutes["api/ : routes par sujet"]
    auth["auth.py<br/>comptes, sessions"]
    fav["favorites.py<br/>favoris, surveillance"]
    alertsapi["alerts.py<br/>historique"]
    demoapi["demo.py<br/>espace de démo"]

    hUsed["modules utilisés"]
    services["services.py<br/>recherche SQL"]
    geopy["🌐 integrations/geo.py<br/>API Géo"]
    security["🔒 security.py<br/>Argon2id, jetons"]
    teststation["test_station.py<br/>station fictive"]
    alerts["alerts.py<br/>règles d'alerte"]
    emails["alert_emails.py<br/>envoi des alertes"]
    mailer["✉️ integrations/mailer.py<br/>SMTP → Mailpit"]

    main --> hRoutes ~~~ auth ~~~ fav ~~~ alertsapi ~~~ demoapi
    main --> hUsed ~~~ services ~~~ geopy ~~~ security ~~~ teststation ~~~ alerts ~~~ emails ~~~ mailer
    services --> geopy
    auth --> security
    auth --> mailer
    fav --> teststation
    demoapi --> teststation
    demoapi --> alerts
    demoapi --> emails
    emails --> mailer

    classDef back fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#111827
    classDef logic fill:#ecfdf5,stroke:#059669,stroke-width:2px,color:#111827
    classDef sec fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#111827
    classDef ext fill:#e5e7eb,stroke:#6b7280,stroke-width:2px,stroke-dasharray:5 3,color:#111827
    classDef mail fill:#fce7f3,stroke:#db2777,stroke-width:2px,color:#111827
    classDef work fill:#ffedd5,stroke:#ea580c,stroke-width:2px,color:#111827
    classDef heading fill:transparent,stroke:transparent,color:#f9fafb,font-weight:bold
    class main,auth,fav,alertsapi,demoapi back
    class services,alerts,emails logic
    class security sec
    class geopy ext
    class mailer mail
    class teststation work
    class hRoutes,hUsed heading
```

**Côté surveillant** (ce qui tourne en fond toutes les 10 minutes) et commandes en ligne :

```mermaid
%%{init: {"theme": "dark", "themeVariables": {"background": "transparent", "lineColor": "#9ca3af", "edgeLabelBackground": "#374151", "textColor": "#f9fafb"}}}%%
flowchart TB
    workerpy["⏱️ worker.py<br/>boucle, verrou unique"]
    clis["⌨️ test_station.py · demo.py<br/>commandes en ligne"]
    sync["sync.py<br/>import du flux"]

    hImport["import : une seule transaction"]
    prix["🌐 integrations/prix_carburants.py<br/>lecture du XML officiel"]
    osmpy["🌐 integrations/osm.py<br/>enseignes"]
    teststation["test_station.py<br/>station fictive"]
    services["services.py<br/>save_stations"]
    alerts["alerts.py<br/>règles d'alerte"]

    hAfter["après l'import"]
    emails["alert_emails.py<br/>un e-mail par compte"]
    mailer["✉️ integrations/mailer.py<br/>SMTP → Mailpit"]
    house["🧹 housekeeping.py<br/>ménage"]

    workerpy --> sync
    clis --> sync
    sync --> hImport ~~~ prix ~~~ osmpy ~~~ teststation ~~~ services ~~~ alerts
    sync --> prix
    prix --> osmpy
    sync --> teststation
    sync --> services
    sync --> alerts
    workerpy --> hAfter ~~~ emails ~~~ mailer ~~~ house
    emails --> alerts
    emails --> mailer
    workerpy --> house

    classDef work fill:#ffedd5,stroke:#ea580c,stroke-width:2px,color:#111827
    classDef wlogic fill:#fff7ed,stroke:#f97316,stroke-width:2px,color:#111827
    classDef ext fill:#e5e7eb,stroke:#6b7280,stroke-width:2px,stroke-dasharray:5 3,color:#111827
    classDef mail fill:#fce7f3,stroke:#db2777,stroke-width:2px,color:#111827
    classDef heading fill:transparent,stroke:transparent,color:#f9fafb,font-weight:bold
    class workerpy,clis,sync work
    class teststation,services,alerts,emails,house wlogic
    class prix,osmpy ext
    class mailer mail
    class hImport,hAfter heading
```

Partout : `models.py` (tables), `schemas.py` (forme du JSON), `database.py` (connexion) et `config.py` (réglages lus dans `.env`). Ces liens-là ne sont pas dessinés.

---

## 3. Routes de l'API

Toutes les requêtes passent d'abord par les mêmes protections. En italique sous chaque route : les tables qu'elle lit ou modifie. Documentation interactive : http://localhost:8000/docs.

```mermaid
%%{init: {"theme": "dark", "themeVariables": {"background": "transparent", "lineColor": "#9ca3af", "edgeLabelBackground": "#374151", "textColor": "#f9fafb"}}}%%
flowchart TB
    req(["🖥️ Requête du site"])

    hMw["🔒 protections communes (main.py)"]
    cors["CORS : seulement localhost:5173 et :4173"]
    csrf["CSRF : écriture refusée (403)<br/>si l'origine est un autre site"]
    headers["En-têtes : nosniff, no-referrer,<br/>frame-ancestors 'none'"]
    errors["Erreurs propres : 422 sans la valeur reçue,<br/>503 base ou source indisponible, 400"]

    hPublic["🌍 sans compte"]
    s1["GET /stations?q&fuel&limit<br/><i>stations, fuels</i>"]
    s2["GET /stations/positions<br/><i>stations (en cache)</i>"]
    s3["GET /stations/{id}<br/>GET /stations/{id}/fuels<br/><i>stations, fuels</i>"]
    s4["GET /cities/bounds?q<br/><i>🌐 geo.api.gouv.fr</i>"]
    a1["POST /auth/register<br/>POST /auth/confirm-email<br/><i>users, jetons, journal</i>"]
    a2["POST /auth/login<br/>POST /auth/logout<br/><i>users, sessions, journal</i>"]
    a3["POST /auth/password-reset/request<br/>POST /auth/password-reset/confirm<br/><i>users, jetons, sessions</i>"]
    a4["POST /auth/unsubscribe<br/><i>users, jetons</i>"]
    d1["GET /demo/test-station<br/>PUT /demo/test-station/fuels/…<br/><i>stations, alertes · 404 sans DEMO_MODE</i>"]

    hPrivate["🔑 avec session (sinon 401)"]
    m1["GET /me · DELETE /me<br/>PUT /me/notifications<br/><i>users, sessions</i>"]
    m2["GET /me/favorites<br/>PUT · DELETE /me/favorites/{id}<br/>PUT /me/favorites/{id}/fuels<br/><i>favorites, favorite_fuels</i>"]
    m3["GET /me/alerts<br/><i>alerts, availability_events</i>"]

    req --> hMw ~~~ cors ~~~ csrf ~~~ headers ~~~ errors
    errors --> hPublic ~~~ s1 ~~~ s2 ~~~ s3 ~~~ s4 ~~~ a1 ~~~ a2 ~~~ a3 ~~~ a4 ~~~ d1
    errors --> hPrivate ~~~ m1 ~~~ m2 ~~~ m3

    classDef front fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#111827
    classDef sec fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#111827
    classDef back fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#111827
    classDef priv fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#111827
    classDef heading fill:transparent,stroke:transparent,color:#f9fafb,font-weight:bold
    class req front
    class cors,csrf,headers,errors sec
    class s1,s2,s3,s4,a1,a2,a3,a4,d1 back
    class m1,m2,m3 priv
    class hMw,hPublic,hPrivate heading
```
