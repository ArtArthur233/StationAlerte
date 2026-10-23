// Fait défiler la page jusqu'à l'élément, juste sous la barre du haut (fixe, et plus haute sur mobile quand on
// est connecté : scrollIntoView mettrait le haut de l'élément dessous).
// Animation faite ici plutôt que behavior: 'smooth' : le défilement natif du navigateur est très rapide sur les
// grandes distances, au point de ressembler à un saut.

let frame = 0

// onDone : appelée quand la page est arrivée (ou que l'utilisateur a repris la main).
// maxScroll : défilement maximal si la page va raccourcir à la fin (par défaut, celui de la page actuelle).
type Options = { onDone?: () => void; maxScroll?: number }

export function scrollBelowHeader(element: Element, { onDone, maxScroll: limit }: Options = {}) {
  const header = document.querySelector('.app-header')?.getBoundingClientRect().height ?? 0
  const maxScroll = limit ?? document.documentElement.scrollHeight - window.innerHeight
  const target = Math.max(0, Math.min(maxScroll, element.getBoundingClientRect().top + window.scrollY - header - 12))
  const start = window.scrollY
  const distance = target - start
  cancelAnimationFrame(frame) // une nouvelle demande remplace celle en cours

  // Moins de mouvement demandé par l'appareil, ou déjà sur place : directement à la cible.
  if (distance === 0 || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    window.scrollTo(0, target)
    onDone?.()
    return
  }

  // 0,6 s pour un petit déplacement, jusqu'à 1,2 s pour un long : la vitesse reste lisible.
  const duration = Math.min(1200, Math.max(600, 500 + Math.abs(distance) * 0.5))
  const begin = performance.now()
  // Molette ou doigt pendant l'animation : l'utilisateur reprend la main, on s'arrête.
  const stop = () => {
    cancelAnimationFrame(frame)
    window.removeEventListener('wheel', stop)
    window.removeEventListener('touchstart', stop)
    onDone?.()
  }
  window.addEventListener('wheel', stop, { passive: true })
  window.addEventListener('touchstart', stop, { passive: true })

  const step = (now: number) => {
    const t = Math.min(1, (now - begin) / duration)
    const eased = t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2 // accélère, puis ralentit en arrivant
    window.scrollTo(0, start + distance * eased)
    if (t < 1) frame = requestAnimationFrame(step)
    else stop()
  }
  frame = requestAnimationFrame(step)
}
