import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { RESULT_LIMIT } from './services/api'
import type { Station } from './types/station'

// Leaflet ne sait pas dessiner dans jsdom (pas de vrai rendu graphique) : la carte est remplacée par un
// bouton qui imite le clic sur une station. Son affichage se vérifie dans le navigateur.
vi.mock('./components/StationMap', () => ({
  StationMap: (props: { query: string; results: Station[] | null; onSelectAddress: (address: string) => void }) => (
    <>
      <button onClick={() => props.onSelectAddress('1 rue A 69001 Lyon')}>Station sur la carte</button>
      <p>Carte cadrée sur {props.results?.length ?? 0} stations</p>
    </>
  ),
}))

// Fausses stations renvoyées par le faux fetch : les tests n'ont pas besoin que l'API tourne.
const station = (id: string): Station => ({
  id, name: `Station ${id}`, address: '1 rue A', postalCode: '69001', city: 'Lyon',
  fuels: [{ type: 'SP98', label: null, status: 'AVAILABLE', updatedAt: null }],
  latitude: 45.76, longitude: 4.83,
})
const stations = [station('a'), station('b')]

// À l'ouverture, l'en-tête demande /me (qui est connecté ?) : par défaut, personne.
const notLoggedIn = () =>
  Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({ detail: 'Connexion requise' }) })

// Remplace le vrai fetch du navigateur par une fonction dont on choisit la réponse.
function mockFetch(response: () => Promise<unknown>, me: () => Promise<unknown> = notLoggedIn) {
  const fetchMock = vi.fn((url: string) =>
    url.endsWith('/me') ? me() : url.endsWith('/me/alerts') ? ok([])() : url.includes('/demo/') ? notFound() : response(),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

// Adresses appelées pour chercher des stations (sans l'appel à /me).
const stationCalls = (fetchMock: ReturnType<typeof mockFetch>) =>
  fetchMock.mock.calls.map(([url]) => url).filter((url) => url.includes('/stations'))

const ok = (data: unknown) => () => Promise.resolve({ ok: true, json: () => Promise.resolve(data) })
// Espace de démonstration absent par défaut (API sans DEMO_MODE) : le panneau ne s'affiche pas.
const notFound = () => Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: 'Not Found' }) })

async function search(text: string) {
  const user = userEvent.setup()
  render(<App />)
  await user.type(screen.getByLabelText('Rechercher une station'), text)
  return user
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

// Test d'intégration : on utilise la page comme un utilisateur (taper, choisir), sans regarder le code interne.
describe('App', () => {
  it('invite à chercher sans appeler l’API tant que rien n’est saisi', () => {
    const fetchMock = mockFetch(ok(stations))
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'StationAlerte' })).toBeInTheDocument()
    expect(screen.getByText(/Saisissez une enseigne/)).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('prix-carburants.gouv.fr')
    expect(stationCalls(fetchMock)).toHaveLength(0)
  })

  it('affiche le compte déjà connecté à l’ouverture (cookie de session)', async () => {
    mockFetch(
      ok(stations.map((s) => ({ ...s, watchedFuels: [] }))), // favoris
      ok({ id: 1, email: 'alice@example.fr', notifyUnavailable: true, notifyAvailable: false }),
    )
    render(<App />)
    // Dans l'en-tête : l'adresse apparaît aussi dans « Les alertes sont envoyées à … ».
    const header = await screen.findByRole('banner')
    expect(await within(header).findByText('alice@example.fr')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Se déconnecter' })).toBeInTheDocument()
  })

  it('lien de désabonnement : affiche le panneau sans rien envoyer, et retire le jeton de l’adresse', async () => {
    window.history.replaceState(null, '', '/#unsubscribe=jeton-desabo')
    const fetchMock = mockFetch(ok(stations))
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Confirmer le désabonnement' })).toBeInTheDocument()
    expect(window.location.hash).toBe('')
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('unsubscribe'))).toBe(false)
  })

  it('lien de confirmation de l’adresse : confirme puis retire le jeton de l’adresse', async () => {
    window.history.replaceState(null, '', '/#confirm=jeton-app')
    const fetchMock = mockFetch(() => Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(null) }))
    render(<App />)

    expect(await screen.findByText(/Adresse e-mail confirmée/)).toBeInTheDocument()
    expect(window.location.hash).toBe('')
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/auth/confirm-email'))).toBe(true)
  })

  it('lien « mot de passe oublié » : ouvre le formulaire et retire le jeton de l’adresse', async () => {
    window.history.replaceState(null, '', '/#reset=jeton-du-lien')
    mockFetch(ok(stations))
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Choisir un nouveau mot de passe' })).toBeInTheDocument()
    expect(window.location.hash).toBe('') // pas dans l'historique, pas réutilisé au rechargement
  })

  it('propose de se connecter quand personne ne l’est', async () => {
    mockFetch(ok(stations))
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Se connecter' })).toBeInTheDocument()
  })

  it('envoie la recherche au backend en un seul appel et affiche les stations', async () => {
    const fetchMock = mockFetch(ok(stations))
    await search('lyon')
    expect(screen.getByText('Chargement des stations…')).toBeInTheDocument()
    // findAll… attend que la réponse (asynchrone) soit arrivée.
    expect(await screen.findAllByRole('article')).toHaveLength(2)
    expect(screen.getByText('Carte cadrée sur 2 stations')).toBeInTheDocument() // la carte reçoit les résultats
    expect(stationCalls(fetchMock)).toHaveLength(1) // 4 lettres tapées, 1 seul appel
    expect(stationCalls(fetchMock)[0]).toContain('q=lyon')
  })

  it('affiche un carburant inconnu avec son nom d’origine', async () => {
    const withOther: Station = {
      ...station('a'),
      fuels: [{ type: 'AUTRE', label: 'B100', status: 'AVAILABLE', updatedAt: null }],
    }
    mockFetch(ok([withOther]))
    await search('lyon')
    expect(await screen.findByText('Autre carburant (B100)')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Autre carburant' })).toBeInTheDocument() // proposé dans le filtre
  })

  it('un clic sur une station de la carte écrit son adresse dans la recherche, puis descend aux résultats', async () => {
    const fetchMock = mockFetch(ok(stations))
    const scrollTo = vi.spyOn(window, 'scrollTo')
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Station sur la carte' }))
    expect(screen.getByLabelText('Rechercher une station')).toHaveValue('1 rue A 69001 Lyon')
    expect(scrollTo).not.toHaveBeenCalled() // pas avant que les résultats soient là
    await screen.findAllByRole('article')
    expect(stationCalls(fetchMock).at(-1)).toContain('q=1+rue+A+69001+Lyon') // URLSearchParams encode l'espace en +
    await waitFor(() => expect(scrollTo).toHaveBeenCalledTimes(1))
  })

  it('transmet le carburant choisi', async () => {
    const fetchMock = mockFetch(ok(stations))
    const user = await search('lyon')
    await screen.findAllByRole('article')
    await user.selectOptions(screen.getByLabelText('Carburant'), 'SP98')
    await screen.findAllByRole('article')
    expect(stationCalls(fetchMock).at(-1)).toContain('fuel=SP98')
  })

  it('indique quand aucune station ne correspond', async () => {
    mockFetch(ok([]))
    await search('nulle part')
    expect(await screen.findByText('Aucune station ne correspond à votre recherche.')).toBeInTheDocument()
  })

  it('demande de préciser quand la limite de résultats est atteinte', async () => {
    mockFetch(ok(Array.from({ length: RESULT_LIMIT }, (_, i) => station(String(i)))))
    await search('lyon')
    expect(await screen.findByText(/précisez votre recherche/)).toBeInTheDocument()
  })

  it('affiche une erreur explicite, pas une liste vide, si le serveur ne répond pas', async () => {
    mockFetch(() => Promise.reject(new TypeError('Failed to fetch')))
    await search('lyon')
    expect(await screen.findByRole('alert')).toHaveTextContent('ne répond pas')
    expect(screen.queryByText(/Aucune station/)).not.toBeInTheDocument()
  })

  it('affiche aussi l’erreur si la source officielle est indisponible (503)', async () => {
    mockFetch(() => Promise.resolve({ ok: false, status: 503 }))
    await search('lyon')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('réponse illisible (page HTML au lieu de JSON) : message d’erreur, pas de plantage', async () => {
    mockFetch(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.reject(new SyntaxError('Unexpected token <')) }))
    await search('lyon')
    expect(await screen.findByRole('alert')).toHaveTextContent('Impossible de charger les stations')
  })

  describe('favoris', () => {
    const ALICE = { id: 1, email: 'alice@example.fr', notifyUnavailable: true, notifyAvailable: false }
    const json = (status: number, body?: unknown) =>
      Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) })

    // Faux serveur avec des favoris en mémoire : PUT et DELETE les modifient, GET les renvoie.
    // demo : stationTest renvoyée par l'espace de démonstration (absent par défaut : 404).
    function mockServer({ me = json(200, ALICE), put, demo }: { me?: Promise<unknown>; put?: () => Promise<unknown>; demo?: Station } = {}) {
      const known = demo ? [demo, ...stations] : stations
      // Le serveur met stationTest en favori permanent de chaque compte.
      let favoriteIds = new Set<string>(demo ? [demo.id, 'a'] : ['a'])
      const watched: Record<string, string[]> = {}
      const fetchMock = vi.fn((url: string, init?: RequestInit) => {
        const path = new URL(url).pathname
        const method = init?.method ?? 'GET'
        const body = init?.body ? JSON.parse(String(init.body)) : undefined
        if (path === '/me') return me
        if (path === '/me/notifications') return put ? put() : json(200, { ...ALICE, ...body })
        if (path === '/me/alerts') return json(200, [])
        if (path.startsWith('/demo/')) return demo ? json(200, demo) : json(404, { detail: 'Not Found' })
        if (path === '/me/favorites') {
          const list = known.filter((s) => favoriteIds.has(s.id))
          return json(200, list.map((s) => ({ ...s, watchedFuels: watched[s.id] ?? [] })))
        }
        if (path.endsWith('/fuels')) {
          if (put) return put()
          watched[path.split('/')[3]] = body.fuels
          return json(204)
        }
        if (path.startsWith('/me/favorites/')) {
          const id = path.split('/').pop()!
          if (method === 'PUT') return put ? put() : (favoriteIds.add(id), json(204))
          favoriteIds = new Set([...favoriteIds].filter((x) => x !== id))
          return json(204)
        }
        return json(200, stations) // recherche
      })
      vi.stubGlobal('fetch', fetchMock)
      return fetchMock
    }

    it('affiche les favoris du compte connecté', async () => {
      mockServer()
      render(<App />)
      const section = await screen.findByRole('region', { name: 'Mes stations favorites' })
      expect(await within(section).findByRole('heading', { name: 'Station a' })).toBeInTheDocument()
      expect(within(section).getByRole('button', { name: 'Retirer des favoris : Station a' })).toBeInTheDocument()
    })

    it('ajoute une station trouvée par la recherche, puis remonte jusqu’à elle', async () => {
      const fetchMock = mockServer()
      const scrollTo = vi.spyOn(window, 'scrollTo')
      const user = await search('lyon')
      await user.click(await screen.findByRole('button', { name: 'Ajouter aux favoris : Station b' }))

      const section = screen.getByRole('region', { name: 'Mes stations favorites' })
      expect(await within(section).findByRole('heading', { name: 'Station b' })).toBeInTheDocument()
      expect(fetchMock.mock.calls.some(([url, init]) => url.endsWith('/me/favorites/b') && init?.method === 'PUT')).toBe(true)
      await waitFor(() => expect(scrollTo).toHaveBeenCalledTimes(1)) // la page remonte jusqu'au nouveau favori
    })

    it('retire une station', async () => {
      mockServer()
      render(<App />)
      await userEvent.setup().click(await screen.findByRole('button', { name: 'Retirer des favoris : Station a' }))
      expect(await screen.findByText(/Aucune station favorite pour l’instant/)).toBeInTheDocument()
    })

    it('pas de bouton favori sans compte connecté', async () => {
      mockFetch(ok(stations))
      await search('lyon')
      await screen.findAllByRole('article')
      expect(screen.queryByRole('button', { name: /favoris/ })).not.toBeInTheDocument()
      expect(screen.queryByRole('region', { name: 'Mes stations favorites' })).not.toBeInTheDocument()
    })

    it('limite atteinte : message de l’API', async () => {
      mockServer({ put: () => json(409, { detail: 'Limite de 50 stations favorites atteinte.' }) })
      const user = await search('lyon')
      await user.click(await screen.findByRole('button', { name: 'Ajouter aux favoris : Station b' }))
      expect(await screen.findByText('Limite de 50 stations favorites atteinte.')).toBeInTheDocument()
    })

    it('session expirée : on repasse en « Se connecter »', async () => {
      mockServer({ put: () => json(401, { detail: 'Connexion requise' }) })
      const user = await search('lyon')
      await user.click(await screen.findByRole('button', { name: 'Ajouter aux favoris : Station b' }))
      expect(await screen.findByRole('button', { name: 'Se connecter' })).toBeInTheDocument()
      expect(screen.queryByRole('region', { name: 'Mes stations favorites' })).not.toBeInTheDocument()
    })

    it('espace de démonstration : stationTest est un favori permanent, le raccourci surveille tous ses carburants', async () => {
      const testStation: Station = {
        ...station('TEST-STATIONTEST'), name: 'stationTest',
        fuels: [
          { type: 'GAZOLE', label: null, status: 'AVAILABLE', updatedAt: new Date().toISOString() },
          { type: 'E10', label: null, status: 'AVAILABLE', updatedAt: new Date().toISOString() },
        ],
      }
      const fetchMock = mockServer({ demo: testStation })
      render(<App />)
      const user = userEvent.setup()
      const demo = await screen.findByRole('region', { name: 'Espace de démonstration' })

      const section = screen.getByRole('region', { name: 'Mes stations favorites' })
      // Favori permanent : une étoile, mais pas de bouton pour la retirer.
      expect(await within(section).findByRole('img', { name: 'Favori permanent : stationTest' })).toBeInTheDocument()
      expect(within(section).queryByRole('button', { name: /Retirer des favoris : stationTest/ })).not.toBeInTheDocument()

      await user.click(within(demo).getByRole('button', { name: 'Surveiller tous les carburants de stationTest' }))

      expect(await within(section).findByRole('checkbox', { name: 'Surveiller Gazole : stationTest', checked: true })).toBeInTheDocument()
      expect(within(section).getByRole('checkbox', { name: 'Surveiller SP95-E10 : stationTest', checked: true })).toBeInTheDocument()
      const [, init] = fetchMock.mock.calls.find(([url]) => url.endsWith('/me/favorites/TEST-STATIONTEST/fuels'))!
      expect(JSON.parse(String(init?.body))).toEqual({ fuels: ['GAZOLE', 'E10'] })
      expect(within(demo).getByRole('button', { name: 'Tous les carburants de stationTest sont surveillés' })).toBeDisabled()
      expect(fetchMock.mock.calls.some(([url, init]) => url.endsWith('/me/favorites/TEST-STATIONTEST') && init?.method === 'PUT')).toBe(false)
    })

    it('un nouveau favori ne surveille rien : il faut cocher', async () => {
      mockServer()
      render(<App />)
      const section = await screen.findByRole('region', { name: 'Mes stations favorites' })
      expect(await within(section).findByText(/Aucun carburant surveillé/)).toBeInTheDocument()
      expect(within(section).getByRole('checkbox', { name: 'Surveiller SP98 : Station a' })).not.toBeChecked()
    })

    it('cocher puis décocher un carburant surveillé', async () => {
      const fetchMock = mockServer()
      render(<App />)
      const user = userEvent.setup()
      const box = await screen.findByRole('checkbox', { name: 'Surveiller SP98 : Station a' })

      await user.click(box)
      expect(await screen.findByRole('checkbox', { name: 'Surveiller SP98 : Station a', checked: true })).toBeInTheDocument()
      expect(screen.queryByText(/Aucun carburant surveillé/)).not.toBeInTheDocument()
      const [, init] = fetchMock.mock.calls.find(([url]) => url.endsWith('/me/favorites/a/fuels'))!
      expect(init?.method).toBe('PUT')
      expect(JSON.parse(String(init?.body))).toEqual({ fuels: ['SP98'] })

      await user.click(screen.getByRole('checkbox', { name: 'Surveiller SP98 : Station a' }))
      expect(await screen.findByRole('checkbox', { name: 'Surveiller SP98 : Station a', checked: false })).toBeInTheDocument()
      expect(JSON.parse(String(fetchMock.mock.calls.findLast(([url]) => url.endsWith('/fuels'))![1]?.body))).toEqual({ fuels: [] })
    })

    it('pas de case « Surveiller » dans les résultats de recherche', async () => {
      mockServer()
      await search('lyon')
      const results = await screen.findAllByRole('article')
      // Station b n'est qu'en résultat de recherche : on surveille seulement depuis « Mes stations favorites ».
      expect(screen.queryByRole('checkbox', { name: /Station b/ })).not.toBeInTheDocument()
      expect(results.length).toBeGreaterThan(0)
    })

    it('carburant refusé par l’API : son message est affiché', async () => {
      mockServer({ put: () => json(400, { detail: 'Carburant non vendu par cette station : SP98' }) })
      render(<App />)
      await userEvent.setup().click(await screen.findByRole('checkbox', { name: 'Surveiller SP98 : Station a' }))
      expect(await screen.findByText('Carburant non vendu par cette station : SP98')).toBeInTheDocument()
    })

    it('préférences d’alerte : valeurs du compte, enregistrement, adresse d’envoi', async () => {
      const fetchMock = mockServer()
      render(<App />)
      const settings = await screen.findByRole('group', { name: 'M’alerter quand un carburant surveillé…' })
      expect(within(settings).getByRole('checkbox', { name: 'devient indisponible' })).toBeChecked()
      expect(within(settings).getByText(/envoyées par e-mail à/)).toHaveTextContent('alice@example.fr')

      await userEvent.setup().click(within(settings).getByRole('checkbox', { name: 'redevient disponible' }))
      expect(await within(settings).findByRole('checkbox', { name: 'redevient disponible', checked: true })).toBeInTheDocument()
      const [, init] = fetchMock.mock.calls.find(([url]) => url.endsWith('/me/notifications'))!
      expect(JSON.parse(String(init?.body))).toEqual({ notifyUnavailable: true, notifyAvailable: true })
    })

    it('préférences d’alerte : erreur affichée, case inchangée', async () => {
      mockServer({ put: () => json(503, { detail: 'Base de données indisponible' }) })
      render(<App />)
      const settings = await screen.findByRole('group', { name: 'M’alerter quand un carburant surveillé…' })
      await userEvent.setup().click(within(settings).getByRole('checkbox', { name: 'redevient disponible' }))
      expect(await within(settings).findByRole('alert')).toHaveTextContent('Impossible d’enregistrer vos préférences')
      expect(within(settings).getByRole('checkbox', { name: 'redevient disponible' })).not.toBeChecked()
    })

    it('affiche « Mes dernières alertes » pour un compte connecté', async () => {
      mockServer()
      render(<App />)
      expect(await screen.findByRole('region', { name: 'Mes dernières alertes' })).toBeInTheDocument()
    })
  })
})
