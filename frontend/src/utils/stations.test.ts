import { describe, expect, it } from 'vitest'
import { displayedStatus, isStale } from './stations'

const now = new Date('2026-01-10T12:00:00Z')

describe('displayedStatus', () => {
  it('garde le statut quand la donnée est récente', () => {
    expect(displayedStatus({ type: 'SP98', label: null, status: 'UNAVAILABLE', updatedAt: '2026-01-10T10:00:00Z' }, now))
      .toBe('UNAVAILABLE')
  })

  it("devient UNKNOWN sans date, jamais UNAVAILABLE", () => {
    expect(displayedStatus({ type: 'SP98', label: null, status: 'AVAILABLE', updatedAt: null }, now)).toBe('UNKNOWN')
  })

  it('devient UNKNOWN quand la donnée est ancienne', () => {
    const fuel = { type: 'SP98', label: null, status: 'AVAILABLE', updatedAt: '2026-01-07T12:00:00Z' } as const
    expect(isStale(fuel, now)).toBe(true)
    expect(displayedStatus(fuel, now)).toBe('UNKNOWN')
  })

  it('une rupture reste fiable 7 jours, pas seulement 48 h', () => {
    expect(displayedStatus({ type: 'E10', label: null, status: 'UNAVAILABLE', updatedAt: '2026-01-07T12:00:00Z' }, now))
      .toBe('UNAVAILABLE')
    expect(displayedStatus({ type: 'E10', label: null, status: 'UNAVAILABLE', updatedAt: '2026-01-02T12:00:00Z' }, now))
      .toBe('UNKNOWN')
  })
})
