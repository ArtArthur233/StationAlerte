import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StationCard } from './StationCard'
import { ErrorBoundary } from './ErrorBoundary'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ErrorBoundary', () => {
  it('affiche la page normalement', () => {
    render(
      <ErrorBoundary>
        <p>Contenu</p>
      </ErrorBoundary>,
    )
    expect(screen.getByText('Contenu')).toBeInTheDocument()
  })

  it('une erreur d’affichage donne un message et un bouton, pas un écran blanc', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {}) // React signale l'erreur dans la console
    // Exemple réel : une date illisible ferait planter le formatage de la date sur la fiche d'une station.
    const broken = {
      id: 'x', name: 'Station', address: 'a', postalCode: '42000', city: 'c', latitude: null, longitude: null,
      fuels: [{ type: 'GAZOLE' as const, label: null, status: 'AVAILABLE' as const, updatedAt: 'pas-une-date' }],
    }
    render(
      <ErrorBoundary>
        <StationCard station={broken} />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Une erreur inattendue empêche d’afficher la page')
    expect(screen.getByRole('button', { name: 'Recharger la page' })).toBeInTheDocument()
  })
})
