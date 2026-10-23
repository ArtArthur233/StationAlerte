import type {
  AlertItem, CityBounds, DemoChangeResult, DemoStatus, FavoriteStation, FuelType, Station, StationPosition, User,
} from '../types/station'

// shortcut: adresse de l'API écrite en dur (la même en mode Docker) ; à passer en variable VITE_API_URL si elle change.
const API_URL = 'http://localhost:8000'
// Au-delà, on abandonne : sinon un serveur bloqué laisserait la page sur « Chargement… » pour toujours.
export const REQUEST_TIMEOUT_MS = 10_000
// Nombre maximal de stations renvoyées par recherche (le backend accepte jusqu'à 100).
export const RESULT_LIMIT = 50

// Erreur renvoyée par l'API : on garde le code HTTP (401, 429…) et son message, déjà rédigé en français.
export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // Réponse sans JSON (serveur frontal, panne…) : message générique ci-dessous.
  }
  return `Erreur HTTP ${response.status}`
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    // Envoie le cookie de session. Il est HttpOnly : le site ne peut ni le lire ni le voler, seulement le transmettre.
    credentials: 'include',
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  })
  // fetch ne lève pas d'erreur sur un code 404 ou 500 : il faut le vérifier soi-même.
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

function sendJson<T>(method: 'POST' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
  return request(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
}

const postJson = <T>(path: string, body?: unknown) => sendJson<T>('POST', path, body)

// La recherche est faite par le backend : près de 10 000 stations, impossible de tout charger dans le navigateur.
export function fetchStations(query: string, fuelType: FuelType | null): Promise<Station[]> {
  // URLSearchParams encode les caractères spéciaux (accents, espaces) dans l'adresse.
  const params = new URLSearchParams({ q: query, limit: String(RESULT_LIMIT) })
  if (fuelType) params.set('fuel', fuelType)
  return request(`/stations?${params}`)
}

// Toutes les stations, mais seulement leur position et leur adresse (sans les carburants) : pour la carte.
export function fetchStationPositions(): Promise<StationPosition[]> {
  return request('/stations/positions')
}

// Rectangle de la ville cherchée, ou null si la recherche n'est pas une ville (ex. « leclerc »).
export function fetchCityBounds(query: string): Promise<CityBounds | null> {
  return request(`/cities/bounds?${new URLSearchParams({ q: query })}`)
}

// --- Comptes ---

// Compte connecté, ou null si personne ne l'est (l'API répond 401).
export async function fetchCurrentUser(): Promise<User | null> {
  try {
    return await request<User>('/me')
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}

export function login(email: string, password: string): Promise<User> {
  return postJson('/auth/login', { email, password })
}

// Toujours la même réponse, que l'adresse ait déjà un compte ou non : la suite se passe par e-mail (V7.3).
export function register(email: string, password: string): Promise<{ detail: string }> {
  return postJson('/auth/register', { email, password })
}

// Lien de confirmation reçu par e-mail (https://…/#confirm=JETON). Ne connecte pas : il faut ensuite se connecter.
export function confirmEmail(token: string): Promise<void> {
  return postJson('/auth/confirm-email', { token })
}

export function logout(): Promise<void> {
  return postJson('/auth/logout')
}

// Toujours la même réponse, que le compte existe ou non (l'API ne révèle pas qui est inscrit).
export function requestPasswordReset(email: string): Promise<{ detail: string }> {
  return postJson('/auth/password-reset/request', { email })
}

export function confirmPasswordReset(token: string, password: string): Promise<void> {
  return postJson('/auth/password-reset/confirm', { token, password })
}

// --- Favoris (compte connecté) ---

export function fetchFavorites(): Promise<FavoriteStation[]> {
  return request('/me/favorites')
}

export function addFavorite(stationId: string): Promise<void> {
  return request(`/me/favorites/${encodeURIComponent(stationId)}`, { method: 'PUT' })
}

export function removeFavorite(stationId: string): Promise<void> {
  return request(`/me/favorites/${encodeURIComponent(stationId)}`, { method: 'DELETE' })
}

// La liste envoyée remplace l'ancienne : [] = plus aucun carburant surveillé dans cette station.
export function setWatchedFuels(stationId: string, fuels: FuelType[]): Promise<void> {
  return sendJson('PUT', `/me/favorites/${encodeURIComponent(stationId)}/fuels`, { fuels })
}

// Renvoie le compte à jour.
export function setNotifications(prefs: Pick<User, 'notifyUnavailable' | 'notifyAvailable'>): Promise<User> {
  return sendJson('PUT', '/me/notifications', prefs)
}

// Les 20 dernières alertes du compte connecté, les plus récentes d'abord.
export function fetchAlerts(): Promise<AlertItem[]> {
  return request('/me/alerts')
}

// Supprime le compte et tout ce qui lui appartient. Le mot de passe est redemandé : une session volée ne suffit pas.
export function deleteAccount(password: string): Promise<void> {
  return sendJson('DELETE', '/me', { password })
}

// Lien « Ne plus recevoir d'alertes » des e-mails (https://…/#unsubscribe=JETON) : sans connexion.
export function unsubscribe(token: string): Promise<{ detail: string }> {
  return postJson('/auth/unsubscribe', { token })
}

// --- Espace de démonstration (local uniquement : l'API répond 404 sans DEMO_MODE=true) ---

// stationTest, ou null si elle n'a pas encore été créée.
export function fetchTestStation(): Promise<Station | null> {
  return request('/demo/test-station')
}

// Change l'état d'un carburant de stationTest ; sans compte.
export function changeTestStationFuel(fuel: FuelType, status: DemoStatus): Promise<DemoChangeResult> {
  return sendJson('PUT', `/demo/test-station/fuels/${fuel}`, { status })
}
