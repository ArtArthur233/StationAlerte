import type { AvailabilityStatus } from '../types/station'

// Icône + texte : l'état reste lisible sans les couleurs (daltonisme, impression).
const STATUS_DISPLAY: Record<AvailabilityStatus, { icon: string; label: string }> = {
  // « Déclaré » : c'est la station qui l'affirme, personne ne vérifie le stock.
  AVAILABLE: { icon: '✓', label: 'Déclaré disponible' },
  UNAVAILABLE: { icon: '✕', label: 'Indisponible' },
  UNKNOWN: { icon: '?', label: 'Inconnu' },
}

export function StatusBadge({ status }: { status: AvailabilityStatus }) {
  const { icon, label } = STATUS_DISPLAY[status]
  return (
    <span className={`badge badge--${status.toLowerCase()}`}>
      <span aria-hidden="true">{icon}</span> {label}
    </span>
  )
}
