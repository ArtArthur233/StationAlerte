import type { AvailabilityStatus, FuelInfo } from '../types/station'

// Au-delà de ce délai, une information n'est plus jugée fiable.
const STALE_AFTER_HOURS = 48
// Une rupture de stock peut durer plusieurs jours : même seuil que RUPTURE_TRUSTED_FOR côté backend.
const UNAVAILABLE_STALE_AFTER_HOURS = 7 * 24

export function isStale(fuel: FuelInfo, now: Date = new Date()): boolean {
  if (fuel.updatedAt === null) return false // pas de date : c'est « inconnu », pas « ancien »
  const maxHours = fuel.status === 'UNAVAILABLE' ? UNAVAILABLE_STALE_AFTER_HOURS : STALE_AFTER_HOURS
  const ageHours = (now.getTime() - new Date(fuel.updatedAt).getTime()) / 3_600_000
  return ageHours > maxHours
}

// Statut réellement affiché : une info absente ou trop vieille devient UNKNOWN.
export function displayedStatus(fuel: FuelInfo, now: Date = new Date()): AvailabilityStatus {
  if (fuel.updatedAt === null || isStale(fuel, now)) return 'UNKNOWN'
  return fuel.status
}
