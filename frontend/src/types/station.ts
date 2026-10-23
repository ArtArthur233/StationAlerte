// Types partagés : ils décrivent la forme des données dans toute l'application.

// AUTRE = fourre-tout pour un carburant que StationAlerte ne connaît pas encore (son nom est dans label).
export type FuelType = 'GAZOLE' | 'SP95' | 'E10' | 'SP98' | 'E85' | 'GPLC' | 'AUTRE'

// Trois états seulement : une donnée absente n'est JAMAIS « indisponible ».
export type AvailabilityStatus = 'AVAILABLE' | 'UNAVAILABLE' | 'UNKNOWN'

export interface FuelInfo {
  type: FuelType
  label: string | null // nom donné par le flux officiel, seulement pour AUTRE (ex. « B100 »)
  status: AvailabilityStatus
  updatedAt: string | null // date ISO 8601, ou null si jamais renseignée
  price?: number | null // prix au litre en euros, à la date updatedAt ; absent en rupture
}

export interface Station {
  id: string
  name: string
  address: string
  postalCode: string
  city: string
  fuels: FuelInfo[]
  latitude: number | null // position GPS en degrés, null si inconnue
  longitude: number | null
}

// Compte connecté, renvoyé par GET /me et POST /auth/login (jamais de mot de passe ni d'empreinte).
export interface User {
  id: number
  email: string
  notifyUnavailable: boolean // alerte quand un carburant surveillé devient indisponible
  notifyAvailable: boolean // alerte quand il redevient disponible
}

// Alerte de l'historique, renvoyée par GET /me/alerts (le changement et l'état de son envoi par e-mail).
export interface AlertItem {
  id: number
  createdAt: string
  status: 'pending' | 'sent' | 'failed' | 'expired'
  sentAt: string | null
  stationId: string
  stationName: string
  fuelType: FuelType
  label: string | null
  oldStatus: AvailabilityStatus
  newStatus: AvailabilityStatus
  sourceUpdatedAt: string | null
}

// Espace de démonstration (V8) : station fictive stationTest et résultat d'un changement de son état.
export const TEST_STATION_ID = 'TEST-STATIONTEST'
export type DemoStatus = AvailabilityStatus | 'NOT_SOLD' // NOT_SOLD : la station ne vend pas ce carburant
export interface DemoChangeResult {
  station: Station
  events: number // changements de disponibilité enregistrés
  alerts: number
  emailsSent: number
  alertsAllowed: boolean // false : surveillant arrêté depuis plus de 20 min, aucune alerte
}

// Station favorite renvoyée par GET /me/favorites, avec les carburants surveillés (vide = aucune alerte).
export type FavoriteStation = Station & { watchedFuels: FuelType[] }

// Rectangle (en degrés) qui contient une ville, renvoyé par GET /cities/bounds.
export interface CityBounds {
  south: number
  west: number
  north: number
  east: number
}

// Version allégée renvoyée par GET /stations/positions, pour afficher toutes les stations sur la carte.
export type StationPosition = Omit<Station, 'fuels' | 'latitude' | 'longitude'> & { latitude: number; longitude: number }

export const FUEL_LABELS: Record<FuelType, string> = {
  GAZOLE: 'Gazole',
  SP95: 'SP95',
  E10: 'SP95-E10',
  SP98: 'SP98',
  E85: 'E85',
  GPLC: 'GPLc',
  AUTRE: 'Autre carburant',
}

// « Gazole », ou « Autre carburant (B100) » : le nom d'origine précise de quel carburant il s'agit.
export function fuelName(fuel: Pick<FuelInfo, 'type' | 'label'>): string {
  return fuel.label ? `${FUEL_LABELS[fuel.type]} (${fuel.label})` : FUEL_LABELS[fuel.type]
}
