import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { ThemeToggle } from './ThemeToggle'

afterEach(() => {
  delete document.documentElement.dataset.theme
  localStorage.clear()
})

describe('ThemeToggle', () => {
  it('passe en mode sombre puis en mode clair, et retient le choix', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)

    await user.click(screen.getByRole('button', { name: 'Passer en mode sombre' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('theme')).toBe('dark')

    await user.click(screen.getByRole('button', { name: 'Passer en mode clair' }))
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('theme')).toBe('light')
  })

  it('suit un changement de thème venu d’ailleurs (réglage de l’appareil)', async () => {
    render(<ThemeToggle />)
    document.documentElement.dataset.theme = 'dark'
    expect(await screen.findByRole('button', { name: 'Passer en mode clair' })).toBeInTheDocument()
  })
})
