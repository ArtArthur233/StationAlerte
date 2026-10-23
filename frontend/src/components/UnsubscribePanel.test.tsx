import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { UnsubscribePanel } from './UnsubscribePanel'

function mockUnsubscribe(status: number, body: unknown) {
  const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
    Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('UnsubscribePanel', () => {
  it('rien n’est envoyé avant le clic (les anti-spams ouvrent les liens tout seuls)', () => {
    const fetchMock = mockUnsubscribe(200, { detail: 'ok' })
    render(<UnsubscribePanel token="jeton" onUnsubscribed={vi.fn()} onClose={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Ne plus recevoir d’alertes par e-mail' })).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('confirmer : désabonné, message de l’API, compte relu', async () => {
    const detail = "C'est fait : vous ne recevrez plus d'alertes par e-mail."
    const fetchMock = mockUnsubscribe(200, { detail })
    const onUnsubscribed = vi.fn()
    render(<UnsubscribePanel token="jeton" onUnsubscribed={onUnsubscribed} onClose={vi.fn()} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Confirmer le désabonnement' }))

    expect(await screen.findByRole('status')).toHaveTextContent(detail)
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ token: 'jeton' })
    expect(onUnsubscribed).toHaveBeenCalled()
  })

  it('lien expiré : message de l’API', async () => {
    mockUnsubscribe(400, { detail: 'Lien de désabonnement invalide ou expiré.' })
    const onUnsubscribed = vi.fn()
    render(<UnsubscribePanel token="vieux" onUnsubscribed={onUnsubscribed} onClose={vi.fn()} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Confirmer le désabonnement' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Lien de désabonnement invalide ou expiré.')
    expect(onUnsubscribed).not.toHaveBeenCalled()
  })
})
