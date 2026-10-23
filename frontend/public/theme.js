// Thème appliqué AVANT le premier affichage (sinon un éclair clair au chargement en mode sombre) :
// le choix fait avec le bouton lune / soleil s'il y en a un, sinon le réglage de l'appareil, suivi s'il change.
// Fichier séparé plutôt que script dans index.html : compatible avec une politique CSP stricte (V8.3).
;(function () {
  var media = window.matchMedia('(prefers-color-scheme: dark)')
  function saved() {
    try {
      return localStorage.getItem('theme')
    } catch {
      return null // stockage bloqué (navigation privée stricte) : on suit l'appareil
    }
  }
  function apply() {
    var theme = saved() || (media.matches ? 'dark' : 'light')
    document.documentElement.dataset.theme = theme
    var meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.content = theme === 'dark' ? '#171a20' : '#ffffff'
  }
  apply()
  media.addEventListener('change', apply)
})()
