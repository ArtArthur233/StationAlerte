import { useCallback, useEffect, useRef, useState } from 'react'
import { AccountMenu } from './components/AccountMenu'
import { Logo } from './components/Logo'
import { ThemeToggle } from './components/ThemeToggle'
import { AlertHistory } from './components/AlertHistory'
import { DemoPanel } from './components/DemoPanel'
import { UnsubscribePanel } from './components/UnsubscribePanel'
import { NotificationSettings } from './components/NotificationSettings'
import { StationCard } from './components/StationCard'
import { StationMap } from './components/StationMap'
import {
  ApiError,
  RESULT_LIMIT,
  addFavorite,
  fetchCurrentUser,
  fetchFavorites,
  fetchStations,
  removeFavorite,
  setWatchedFuels,
} from './services/api'
import { scrollBelowHeader } from './utils/scroll'
import { FUEL_LABELS, TEST_STATION_ID, type FavoriteStation, type FuelType, type Station, type User } from './types/station'
import './App.css'

// En dessous, une recherche renverrait des milliers de stations sans intérêt.
const MIN_QUERY_LENGTH = 2
// On attend une courte pause dans la frappe : taper « lyon » fait 1 appel à l'API, pas 4.
const SEARCH_DELAY_MS = 300

// Liens reçus par e-mail : https://…/#reset=JETON (mot de passe oublié), #confirm=JETON (inscription) ou
// #unsubscribe=JETON (« Ne plus recevoir d'alertes »).
// Le jeton est après « # » : le navigateur ne l'envoie à aucun serveur, ni aux autres sites appelés par la
// page (fond de carte).
function tokenInUrl(name: 'reset' | 'confirm' | 'unsubscribe'): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get(name)
}

// Réponse de l'API et recherche qui l'a produite ; stations à null = échec du chargement.
type SearchResult = { key: string; stations: Station[] | null }
// Favoris et compte qui les a chargés : après un changement de compte, on n'affiche jamais ceux d'un autre.
type FavoritesResult = { userId: number; stations: FavoriteStation[] | null }

export default function App() {
  // L'état : ce que l'utilisateur a saisi, et la dernière réponse reçue.
  const [query, setQuery] = useState('')
  const [fuelType, setFuelType] = useState<FuelType | null>(null)
  const [result, setResult] = useState<SearchResult | null>(null)
  // Compte connecté (donnée reçue de l'API) ; undefined tant que /me n'a pas répondu.
  const [user, setUser] = useState<User | null | undefined>(undefined)
  const [resetToken, setResetToken] = useState(() => tokenInUrl('reset'))
  const [confirmToken, setConfirmToken] = useState(() => tokenInUrl('confirm'))
  const [unsubscribeToken, setUnsubscribeToken] = useState(() => tokenInUrl('unsubscribe'))
  const [favoritesResult, setFavoritesResult] = useState<FavoritesResult | null>(null)
  const [favoritesError, setFavoritesError] = useState<string | null>(null)
  const [pendingFavorite, setPendingFavorite] = useState<string | null>(null) // boutons de la station désactivés pendant l'appel
  // Défilement demandé (clic sur la carte → résultats ; nouveau favori → sa fiche), fait dès que la cible s'affiche.
  const [scrollTarget, setScrollTarget] = useState<'results' | { favorite: string } | null>(null)
  // Incrémenté à chaque changement de stationTest (espace de démonstration) : favoris, alertes et recherche rechargés.
  const [demoVersion, setDemoVersion] = useState(0)
  const resultsRef = useRef<HTMLDivElement>(null)
  const favoritesRef = useRef<HTMLElement>(null)

  // Valeurs dérivées : recalculées à chaque rendu, inutile de les stocker dans un état.
  const q = query.trim()
  const searchKey = `${q}|${fuelType ?? ''}`
  // La réponse affichée doit correspondre à la recherche en cours, sinon on est en train de charger.
  const loading = result?.key !== searchKey
  const stations = loading ? null : result.stations
  const userId = user?.id
  const favoritesLoading = userId !== undefined && favoritesResult?.userId !== userId
  const favorites = favoritesResult !== null && favoritesResult.userId === userId ? favoritesResult.stations : null
  const favoriteIds = new Set(favorites?.map((station) => station.id))

  // Le jeton est gardé en mémoire puis retiré de la barre d'adresse : il ne reste pas dans l'historique
  // du navigateur, et un rechargement de la page ne le réutilise pas.
  useEffect(() => {
    if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search)
  }, [])

  // À l'ouverture : le cookie de session (s'il existe) dit-il qui est connecté ?
  // En cas de panne, on affiche « Se connecter » : le formulaire dira alors que le serveur ne répond pas.
  useEffect(() => {
    fetchCurrentUser()
      .then(setUser)
      .catch(() => setUser(null))
  }, [])

  // Favoris chargés à chaque connexion (ou changement de compte), et après un changement de stationTest.
  useEffect(() => {
    if (userId === undefined) return
    let ignore = false
    fetchFavorites()
      .then((data) => !ignore && setFavoritesResult({ userId, stations: data }))
      .catch(() => !ignore && setFavoritesResult({ userId, stations: null }))
    return () => {
      ignore = true
    }
  }, [userId, demoVersion])

  // Ajout, retrait ou carburants surveillés : même déroulé, puis la liste du serveur fait foi.
  // Renvoie true si le changement a réussi.
  async function changeFavorite(stationId: string, change: () => Promise<void>): Promise<boolean> {
    if (userId === undefined) return false
    setPendingFavorite(stationId)
    setFavoritesError(null)
    try {
      await change()
      setFavoritesResult({ userId, stations: await fetchFavorites() })
      return true
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setUser(null) // session expirée : on repasse en « Se connecter »
      } else {
        setFavoritesError(
          error instanceof ApiError && [400, 404, 409].includes(error.status)
            ? error.message // limite de favoris, carburant plus vendu, favori retiré depuis un autre appareil
            : 'Impossible de modifier vos favoris : le serveur StationAlerte ne répond pas. Réessayez.',
        )
      }
      return false
    } finally {
      setPendingFavorite(null)
    }
  }

  // Après un ajout réussi, la page remonte jusqu'à la fiche dans « Mes stations favorites ».
  async function toggleFavorite(station: Station) {
    const adding = !favoriteIds.has(station.id)
    const done = await changeFavorite(station.id, () => (adding ? addFavorite : removeFavorite)(station.id))
    if (done && adding) setScrollTarget({ favorite: station.id })
  }

  // Clic sur une station de la carte : sa recherche, puis la page descend jusqu'aux résultats.
  // useCallback : StationMap demande une fonction qui garde la même identité (sinon la carte serait recréée).
  const selectFromMap = useCallback((address: string) => {
    // Pendant le chargement, la liste est remplacée par une ligne « Chargement… » : la page raccourcirait et le
    // navigateur la remonterait d'un coup. On garde donc la hauteur actuelle jusqu'à la fin du défilement.
    const results = resultsRef.current
    if (results) results.style.minHeight = `${results.offsetHeight}px`
    setQuery(address)
    setScrollTarget('results')
  }, [])

  useEffect(() => {
    if (scrollTarget === null) return
    const target =
      scrollTarget === 'results'
        ? !loading && resultsRef.current
        : [...(favoritesRef.current?.querySelectorAll<HTMLElement>('[data-station-id]') ?? [])].find(
            (card) => card.dataset.stationId === scrollTarget.favorite,
          )
    if (!target) return // pas encore affichée : on réessaie au prochain rendu (réponse du serveur)
    if (scrollTarget === 'results') {
      // La zone des résultats garde sa hauteur d'avant le clic (selectFromMap). Une fois relâchée, la page sera plus
      // courte de « spare » : on ne descend jamais plus bas que ce qu'elle permettra, sinon elle remonterait d'un coup.
      const results = resultsRef.current!
      const last = results.lastElementChild
      const content = last
        ? last.getBoundingClientRect().bottom - results.getBoundingClientRect().top + parseFloat(getComputedStyle(last).marginBottom)
        : 0
      const spare = Math.max(0, results.offsetHeight - content)
      scrollBelowHeader(target, {
        maxScroll: document.documentElement.scrollHeight - window.innerHeight - spare,
        onDone: () => results.style.removeProperty('min-height'),
      })
    } else {
      scrollBelowHeader(target)
    }
    setScrollTarget(null)
  }, [scrollTarget, loading, favorites])

  // Liste construite à partir des carburants vendus : dans leur ordre, et sans un carburant que la station
  // ne vend plus (l'API le refuserait).
  const toggleWatchedFuel = (station: FavoriteStation, type: FuelType) =>
    changeFavorite(station.id, () =>
      setWatchedFuels(
        station.id,
        station.fuels
          .map((fuel) => fuel.type)
          .filter((t) => (t === type ? !station.watchedFuels.includes(t) : station.watchedFuels.includes(t))),
      ),
    )

  // Raccourci de l'espace de démonstration : tous les carburants de stationTest surveillés (elle est toujours en
  // favori : le serveur l'ajoute à chaque compte), puis la page remonte jusqu'à sa fiche.
  const testFavorite = favorites?.find((s) => s.id === TEST_STATION_ID)
  const watchingAllTest = testFavorite !== undefined && testFavorite.fuels.every((f) => testFavorite.watchedFuels.includes(f.type))
  async function watchTestStation(station: Station) {
    const done = await changeFavorite(station.id, () => setWatchedFuels(station.id, station.fuels.map((fuel) => fuel.type)))
    if (done) setScrollTarget({ favorite: station.id })
  }

  // Bouton ☆ / ★ seulement pour un compte connecté ; stationTest est un favori permanent (pas de bouton).
  const favoriteButton = (station: Station) =>
    userId === undefined
      ? undefined
      : station.id === TEST_STATION_ID
        ? { active: true, onToggle: () => {}, permanent: true }
        : { active: favoriteIds.has(station.id), onToggle: () => toggleFavorite(station), disabled: pendingFavorite === station.id }

  useEffect(() => {
    if (q.length < MIN_QUERY_LENGTH) return
    // Si la recherche change avant la réponse, on ignore celle-ci et on annule l'appel prévu.
    let ignore = false
    const timer = setTimeout(() => {
      fetchStations(q, fuelType)
        .then((data) => !ignore && setResult({ key: searchKey, stations: data }))
        .catch(() => !ignore && setResult({ key: searchKey, stations: null }))
    }, SEARCH_DELAY_MS)
    return () => {
      ignore = true
      clearTimeout(timer)
    }
  }, [q, fuelType, searchKey, demoVersion]) // demoVersion : stationTest a changé, même recherche relancée

  return (
    <>
      <header className="app-header">
        <div className="app-header__bar">
          <div className="brand">
            <Logo />
            <div>
              <h1>StationAlerte</h1>
              <p className="brand__tagline">Surveillez la disponibilité des carburants dans vos stations.</p>
            </div>
          </div>
          <div className="app-header__actions">
            <ThemeToggle />
            <AccountMenu
              user={user}
              onUserChange={setUser}
              resetToken={resetToken}
              onResetDone={() => setResetToken(null)}
              confirmToken={confirmToken}
              onConfirmDone={() => setConfirmToken(null)}
            />
          </div>
        </div>
      </header>

      <main className="container">
        {unsubscribeToken && (
          <UnsubscribePanel
            token={unsubscribeToken}
            // Préférences changées côté serveur : on relit le compte pour que les cases soient à jour.
            onUnsubscribed={() => fetchCurrentUser().then(setUser).catch(() => {})}
            onClose={() => setUnsubscribeToken(null)}
          />
        )}
        {user && (
          <section className="section" aria-labelledby="favorites-title" ref={favoritesRef}>
            <h2 id="favorites-title">Mes stations favorites</h2>
            <NotificationSettings user={user} onUserChange={setUser} />
            {favoritesError && (
              <p role="alert" className="load-error">
                {favoritesError}
              </p>
            )}
            {favoritesLoading ? (
              <p className="result-count">Chargement de vos favoris…</p>
            ) : favorites === null ? (
              <p role="alert" className="load-error">
                Impossible de charger vos favoris : le serveur StationAlerte ne répond pas. Réessayez plus tard.
              </p>
            ) : favorites.length === 0 ? (
              <p className="empty">Aucune station favorite pour l’instant : cherchez une station, puis touchez l’étoile ☆ de sa fiche.</p>
            ) : (
              <div className="station-grid">
                {favorites.map((station) => (
                  <StationCard
                    key={station.id}
                    station={station}
                    favorite={favoriteButton(station)}
                    watch={{
                      fuels: station.watchedFuels,
                      onToggle: (type) => toggleWatchedFuel(station, type),
                      disabled: pendingFavorite === station.id,
                    }}
                  />
                ))}
              </div>
            )}
          </section>
        )}

        {/* key : un autre compte connecté = un nouvel historique, jamais celui du compte précédent. */}
        {user && <AlertHistory key={user.id} onUserChange={setUser} reloadKey={demoVersion} />}

        <section className="section" aria-labelledby="search-title">
          <h2 id="search-title">Trouver une station</h2>
          <div className="filters">
            <label>
              Rechercher une station
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                maxLength={200} // même limite que l'API (au-delà, elle répond 422)
                placeholder="Enseigne, ville, code postal ou adresse"
              />
            </label>
            <label>
              Carburant
              <select
                value={fuelType ?? ''}
                onChange={(e) => setFuelType(e.target.value === '' ? null : (e.target.value as FuelType))}
              >
                <option value="">Tous les carburants</option>
                {Object.entries(FUEL_LABELS).map(([type, label]) => (
                  <option key={type} value={type}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {/* Mentions exigées par la Licence Ouverte (source et date, indiquée pour chaque carburant) et l'ODbL. */}
          <p className="demo-notice" role="note">
            Données officielles : <a href="https://www.prix-carburants.gouv.fr/">prix-carburants.gouv.fr</a>{' '}
            (ministère de l’Économie), Licence Ouverte 2.0. Les disponibilités sont{' '}
            <strong>déclarées par les stations</strong> et interprétées par StationAlerte : vérifiez la date de
            chaque information. Enseignes : © les contributeurs d’
            <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> (ODbL).
          </p>

          {/* Toujours affichée, hors des résultats : elle n'est pas rechargée à chaque recherche.
              Un clic sur une station remplit la recherche avec son adresse (selectFromMap ne change jamais d'identité). */}
          <StationMap query={q} results={stations} onSelectAddress={selectFromMap} />

          {/* Erreur et chargement passent avant la liste : un serveur éteint ne doit jamais ressembler à « aucune station ». */}
          <div ref={resultsRef}>
            {q.length < MIN_QUERY_LENGTH ? (
              <p className="empty">Saisissez une enseigne, une ville, un code postal ou une adresse pour trouver des stations.</p>
            ) : loading ? (
              <p className="result-count">Chargement des stations…</p>
            ) : stations === null ? (
              <p role="alert" className="load-error">
                Impossible de charger les stations : le serveur StationAlerte ou la source officielle ne répond pas.
                Réessayez plus tard.
              </p>
            ) : (
              <>
                <p aria-live="polite" className="result-count">
                  {stations.length} station{stations.length > 1 ? 's' : ''} trouvée{stations.length > 1 ? 's' : ''}
                  {stations.length === RESULT_LIMIT && ' (seules les premières sont affichées : précisez votre recherche)'}
                </p>

                {stations.length === 0 ? (
                  <p className="empty">Aucune station ne correspond à votre recherche.</p>
                ) : (
                  <div className="station-grid">
                    {stations.map((station) => (
                      <StationCard key={station.id} station={station} favorite={favoriteButton(station)} />
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* Tout en bas, séparé des résultats : la seule partie du site qui touche à une station fictive. */}
        <DemoPanel
          user={user}
          watchingAll={watchingAllTest}
          onWatchAll={watchTestStation}
          onChanged={() => setDemoVersion((n) => n + 1)}
        />
      </main>
    </>
  )
}
