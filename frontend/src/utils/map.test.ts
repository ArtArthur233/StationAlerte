import { describe, expect, it } from 'vitest'
import { markerRadius } from './map'

describe('markerRadius', () => {
  it('grossit les points avec le zoom, de la France entière à la rue', () => {
    expect([5, 6, 8, 10, 12, 13, 18].map(markerRadius)).toEqual([3, 3, 4, 5, 7, 9, 9])
  })
})
