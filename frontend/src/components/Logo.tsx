// Logo : une goutte de carburant et un point d'alerte. Décoratif (le nom StationAlerte est écrit à côté).
// Même dessin que public/favicon.svg ; ici les couleurs suivent le thème (clair ou sombre).
export function Logo() {
  return (
    <svg className="brand__logo" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="var(--color-accent)" />
      <path d="M15 7.5c-3.6 4.6-6.5 8.4-6.5 11.6a6.5 6.5 0 0 0 13 0c0-3.2-2.9-7-6.5-11.6z" fill="var(--color-on-accent)" />
      <circle cx="24" cy="8.5" r="4" fill="#ffb020" stroke="var(--color-accent)" strokeWidth="2" />
    </svg>
  )
}
