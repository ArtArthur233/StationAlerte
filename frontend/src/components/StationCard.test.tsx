import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Station } from '../types/station'
import { StationCard } from './StationCard'

const recent = new Date().toISOString()
const old = new Date(Date.now() - 5 * 24 * 3600 * 1000).toISOString()

const station: Station = {
  id: '1',
  name: 'Station a',
  address: '1 rue A',
  postalCode: '42000',
  city: 'Saint-Étienne',
  latitude: null,
  longitude: null,
  fuels: [
    { type: 'GAZOLE', label: null, status: 'AVAILABLE', updatedAt: recent, price: 1.789 },
    { type: 'SP98', label: null, status: 'AVAILABLE', updatedAt: old, price: 1.9 },
    { type: 'E10', label: null, status: 'UNAVAILABLE', updatedAt: recent, price: null },
  ],
}

describe('StationCard', () => {
  it('affiche le prix au format français, en retrait s’il est ancien, rien sans prix', () => {
    render(<StationCard station={station} />)
    const [gazole, sp98, e10] = screen.getAllByRole('listitem')

    expect(gazole).toHaveTextContent('1,789 €/L')
    expect(screen.getByText(/1,789/)).not.toHaveClass('fuel-row__price--stale')
    expect(sp98).toHaveTextContent('1,900 €/L')
    expect(screen.getByText(/1,900/)).toHaveClass('fuel-row__price--stale')
    expect(e10).not.toHaveTextContent('€/L')
  })
})
