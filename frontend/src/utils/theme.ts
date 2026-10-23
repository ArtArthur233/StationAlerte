import { useSyncExternalStore } from 'react'

// Thème clair ou sombre : l'attribut data-theme de <html>, posé au chargement par public/theme.js.
type Theme = 'light' | 'dark'

const root = document.documentElement

function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange)
  observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] })
  return () => observer.disconnect()
}

// Se met à jour quand le thème change (bouton, ou réglage de l'appareil tant qu'aucun choix n'est enregistré).
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, () => (root.dataset.theme === 'dark' ? 'dark' : 'light'))
}

// Choix fait avec le bouton : appliqué tout de suite et retenu par le navigateur.
export function chooseTheme(theme: Theme) {
  root.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#171a20' : '#ffffff')
  try {
    localStorage.setItem('theme', theme)
  } catch {
    // stockage bloqué : le choix vaut seulement jusqu'au rechargement
  }
}
