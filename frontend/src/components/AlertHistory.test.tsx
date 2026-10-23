import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AlertItem } from '../types/station'
import { AlertHistory } from './AlertHistory'

const base: AlertItem = {
  id: 1, createdAt: '2026-10-17T11:05:00Z', status: 'sent', sentAt: '2026-10-17T11:06:00Z',
  stationId: 'TEST-STATIONTEST', stationName: 'stationTest', fuelType: 'GAZOLE', label: null,
  oldStatus: 'AVAILABLE', newStatus: 'UNAVAILABLE', sourceUpdatedAt: '2026-10-17T11:05:00Z',
}

function mockAlerts(...responses: Array<{ status: number; body: unknown }>) {
  const fetchMock = vi.fn()
  for (const { status, body } of responses) {
    fetchMock.mockResolvedValueOnce({ ok: status < 400, status, json: () => Promise.resolve(body) })
  }
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AlertHistory', () => {
  it('liste les alertes avec le changement et l’état de l’e-mail, en texte', async () => {
    mockAlerts({
      status: 200,
      body: [
        base,
        { ...base, id: 2, status: 'pending', sentAt: null },
        { ...base, id: 3, status: 'failed', sentAt: null },
        { ...base, id: 4, status: 'expired', sentAt: null, fuelType: 'AUTRE', label: 'B100' },
      ],
    })
    render(<AlertHistory onUserChange={vi.fn()} />)

    const rows = await screen.findAllByRole('listitem')
    expect(rows).toHaveLength(4)
    expect(rows[0]).toHaveTextContent('stationTest · Gazole : ✓ Déclaré disponible → ✕ Indisponible')
    expect(rows[0]).toHaveTextContent(/E-mail envoyé le 17\/10\/2026/) // l'heure dépend du fuseau du PC
    expect(rows[1]).toHaveTextContent('E-mail en attente d’envoi')
    expect(rows[2]).toHaveTextContent('Échec de l’envoi de l’e-mail')
    expect(rows[3]).toHaveTextContent('Autre carburant (B100)')
    expect(rows[3]).toHaveTextContent('information devenue trop ancienne')
  })

  it('les 3 dernières toujours visibles, les plus anciennes dans une liste à dérouler', async () => {
    mockAlerts({ status: 200, body: [1, 2, 3, 4, 5].map((id) => ({ ...base, id })) })
    render(<AlertHistory onUserChange={vi.fn()} />)

    const toggle = await screen.findByText('Voir les 2 alertes plus anciennes')
    const older = toggle.closest('details')!
    expect(older).not.toHaveAttribute('open') // fermée au départ
    expect(within(older).getAllByRole('listitem', { hidden: true })).toHaveLength(2) // les 4e et 5e
    expect(older.previousElementSibling!.querySelectorAll('li')).toHaveLength(3)

    await userEvent.click(toggle)
    expect(older).toHaveAttribute('open')
    expect(await screen.findByText('Masquer les alertes plus anciennes')).toBeInTheDocument()
  })

  it('3 alertes ou moins : rien à dérouler', async () => {
    mockAlerts({ status: 200, body: [1, 2, 3].map((id) => ({ ...base, id })) })
    render(<AlertHistory onUserChange={vi.fn()} />)
    expect(await screen.findAllByRole('listitem')).toHaveLength(3)
    expect(screen.queryByText(/plus anciennes?/)).not.toBeInTheDocument()
  })

  it('aucune alerte : explique quand il y en aura', async () => {
    mockAlerts({ status: 200, body: [] })
    render(<AlertHistory onUserChange={vi.fn()} />)
    expect(await screen.findByText(/Aucune alerte pour l’instant/)).toBeInTheDocument()
  })

  it('serveur en panne : message d’erreur, pas une liste vide', async () => {
    mockAlerts({ status: 503, body: { detail: 'Base de données indisponible' } })
    render(<AlertHistory onUserChange={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Impossible de charger vos alertes')
  })

  it('« Actualiser » recharge la liste', async () => {
    const fetchMock = mockAlerts({ status: 200, body: [] }, { status: 200, body: [base] })
    render(<AlertHistory onUserChange={vi.fn()} />)
    await screen.findByText(/Aucune alerte/)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Actualiser' }))

    expect(await screen.findAllByRole('listitem')).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('session expirée : on repasse en « Se connecter »', async () => {
    mockAlerts({ status: 401, body: { detail: 'Connexion requise' } })
    const onUserChange = vi.fn()
    render(<AlertHistory onUserChange={onUserChange} />)
    await vi.waitFor(() => expect(onUserChange).toHaveBeenCalledWith(null))
  })
})
