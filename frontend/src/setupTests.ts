import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'
// Ajoute des vérifications lisibles comme expect(element).toBeInTheDocument()
import '@testing-library/jest-dom/vitest'

// Vide la page entre deux tests, sinon les rendus s'accumulent.
afterEach(cleanup)

// jsdom ne fait pas défiler la page (il écrirait « Not implemented » à chaque appel) ; les tests qui vérifient
// un défilement l'espionnent avec vi.spyOn(window, 'scrollTo').
window.scrollTo = () => {}
