import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DemoChangeResult, Station, User } from '../types/station'
import { DemoPanel } from './DemoPanel'

const now = new Date().toISOString()
const station = (fuels: Station['fuels']): Station => ({
  id: 'TEST-STATIONTEST', name: 'stationTest', address: 'Station fictive de test', postalCode: '42000',
  city: 'Saint-Étienne', latitude: null, longitude: null, fuels,
})
const gazole = (status: 'AVAILABLE' | 'UNAVAILABLE') => ({ type: 'GAZOLE' as const, label: null, status, updatedAt: now })
const user: User = { id: 1, email: 'demo@test.fr', notifyUnavailable: true, notifyAvailable: true }
const json = (status: number, data: unknown) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(data) })

function mockApi(getResponse: () => Promise<unknown>, putResponse?: () => Promise<unknown>) {
  const fetchMock = vi.fn((_url: string, init?: RequestInit) => (init?.method === 'PUT' ? putResponse!() : getResponse()))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPanel(props: Partial<Parameters<typeof DemoPanel>[0]> = {}) {
  const callbacks = { onWatchAll: vi.fn(), onChanged: vi.fn() }
  render(<DemoPanel user={user} watchingAll={false} {...callbacks} {...props} />)
  return callbacks
}

const choice = (fuel: string, label: string) =>
  within(screen.getByRole('group', { name: `État du carburant ${fuel}` })).getByRole('button', { name: label })

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('DemoPanel', () => {
  it('reste caché quand l’API n’a pas le mode démo (404)', async () => {
    const fetchMock = mockApi(() => json(404, { detail: 'Not Found' }))
    const { container } = render(<DemoPanel user={user} watchingAll={false} onWatchAll={vi.fn()} onChanged={vi.fn()} />)
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('montre l’état actuel de chaque carburant, et dit que la station est fictive', async () => {
    mockApi(() => json(200, station([gazole('UNAVAILABLE')])))
    renderPanel()

    expect(await screen.findByRole('heading', { name: 'Espace de démonstration' })).toBeInTheDocument()
    expect(screen.getByText('Station fictive')).toBeInTheDocument()
    expect(choice('Gazole', 'Indisponible')).toHaveAttribute('aria-pressed', 'true')
    expect(choice('Gazole', 'Disponible')).toHaveAttribute('aria-pressed', 'false')
    expect(choice('SP98', 'Non vendu')).toHaveAttribute('aria-pressed', 'true') // pas vendu par la station
  })

  it('change un état, affiche le résultat et prévient la page', async () => {
    const result: DemoChangeResult = { station: station([gazole('UNAVAILABLE')]), events: 1, alerts: 1, emailsSent: 1, alertsAllowed: true }
    const fetchMock = mockApi(() => json(200, station([gazole('AVAILABLE')])), () => json(200, result))
    const { onChanged } = renderPanel()

    await screen.findByRole('heading', { name: 'Espace de démonstration' })
    await userEvent.click(choice('Gazole', 'Indisponible'))

    const [url, init] = fetchMock.mock.calls.at(-1)!
    expect(url).toMatch(/\/demo\/test-station\/fuels\/GAZOLE$/)
    expect(init).toMatchObject({ method: 'PUT', body: JSON.stringify({ status: 'UNAVAILABLE' }) })
    expect(await screen.findByRole('status')).toHaveTextContent('1 alerte créée, 1 e-mail envoyé')
    expect(choice('Gazole', 'Indisponible')).toHaveAttribute('aria-pressed', 'true')
    expect(onChanged).toHaveBeenCalledOnce()
  })

  it('explique l’absence d’alerte quand le surveillant est arrêté', async () => {
    const result: DemoChangeResult = { station: station([gazole('UNAVAILABLE')]), events: 1, alerts: 0, emailsSent: 0, alertsAllowed: false }
    mockApi(() => json(200, station([gazole('AVAILABLE')])), () => json(200, result))
    renderPanel()

    await screen.findByRole('heading', { name: 'Espace de démonstration' })
    await userEvent.click(choice('Gazole', 'Indisponible'))

    expect(await screen.findByRole('status')).toHaveTextContent('le surveillant est arrêté')
  })

  it('serveur injoignable : message d’erreur', async () => {
    mockApi(() => json(200, station([gazole('AVAILABLE')])), () => Promise.reject(new TypeError('Failed to fetch')))
    const { onChanged } = renderPanel()

    await screen.findByRole('heading', { name: 'Espace de démonstration' })
    await userEvent.click(choice('Gazole', 'Indisponible'))

    expect(await screen.findByRole('alert')).toHaveTextContent('ne répond pas')
    expect(onChanged).not.toHaveBeenCalled()
  })

  it('raccourci « tout surveiller » : demande une connexion, puis appelle la page', async () => {
    mockApi(() => json(200, station([gazole('AVAILABLE')])))
    const { rerender } = render(<DemoPanel user={null} watchingAll={false} onWatchAll={vi.fn()} onChanged={vi.fn()} />)
    const button = await screen.findByRole('button', { name: 'Surveiller tous les carburants de stationTest' })
    expect(button).toBeDisabled()
    expect(screen.getByText(/Connectez-vous pour surveiller/)).toBeInTheDocument()

    const onWatchAll = vi.fn()
    rerender(<DemoPanel user={user} watchingAll={false} onWatchAll={onWatchAll} onChanged={vi.fn()} />)
    await userEvent.click(button)
    expect(onWatchAll).toHaveBeenCalledWith(expect.objectContaining({ id: 'TEST-STATIONTEST' }))

    rerender(<DemoPanel user={user} watchingAll onWatchAll={onWatchAll} onChanged={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Tous les carburants de stationTest sont surveillés' })).toBeDisabled()
  })
})
