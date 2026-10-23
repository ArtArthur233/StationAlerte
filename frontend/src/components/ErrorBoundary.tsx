import { Component, type ReactNode } from 'react'

// Filet de sécurité : sans lui, une erreur pendant l'affichage (donnée inattendue, bug) efface toute la page
// et laisse un écran blanc. React impose une classe pour cela (pas d'équivalent en fonction).
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    console.error('Erreur d’affichage StationAlerte', error) // visible dans la console (F12) pour le débogage
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <main className="container">
        <p role="alert" className="load-error">
          Une erreur inattendue empêche d’afficher la page. Rechargez-la ; si le problème continue, réessayez plus
          tard.
        </p>
        <button type="button" className="primary" onClick={() => window.location.reload()}>
          Recharger la page
        </button>
      </main>
    )
  }
}
