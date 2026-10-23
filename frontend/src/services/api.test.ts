import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchStations, REQUEST_TIMEOUT_MS } from './api'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('fetchStations', () => {
  it('abandonne la requête si le serveur ne répond pas à temps', async () => {
    // On simule un délai déjà écoulé, au lieu d'attendre 10 vraies secondes.
    const timeout = vi.spyOn(AbortSignal, 'timeout').mockReturnValue(
      AbortSignal.abort(new DOMException('Délai dépassé', 'TimeoutError')),
    )
    // Faux serveur muet : il ne répond jamais, il ne fait qu'obéir à l'abandon.
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) =>
      new Promise((_resolve, reject) => {
        if (init.signal?.aborted) reject(init.signal.reason)
      }),
    ))

    await expect(fetchStations('lyon', null)).rejects.toThrow('Délai dépassé')
    expect(timeout).toHaveBeenCalledWith(REQUEST_TIMEOUT_MS)
  })
})
