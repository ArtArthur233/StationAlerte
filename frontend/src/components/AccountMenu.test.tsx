import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccountMenu } from './AccountMenu'

const ALICE = { id: 1, email: 'alice@example.fr', notifyUnavailable: true, notifyAvailable: false }
const json = (status: number, body: unknown) =>
  Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) })

// Faux serveur : une réponse par adresse appelée ; on garde chaque appel pour vérifier ce qui a été envoyé.
function mockApi(responses: Record<string, () => Promise<unknown>>) {
  const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
    const response = responses[new URL(url).pathname]
    return response ? response() : Promise.reject(new TypeError('Failed to fetch'))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function fillAndSubmit(email: string, password: string, submitLabel = 'Se connecter') {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('E-mail'), email)
  await user.type(screen.getByLabelText('Mot de passe'), password)
  await user.click(screen.getByRole('button', { name: submitLabel }))
}

async function openForm(mode: 'login' | 'register' = 'login') {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Se connecter' }))
  if (mode === 'register') await user.click(screen.getByRole('button', { name: 'Créer un compte' }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AccountMenu', () => {
  it('n’affiche rien tant qu’on ne sait pas qui est connecté', () => {
    const { container } = render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={undefined} onUserChange={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('connecte avec le cookie de session et le bon corps de requête', async () => {
    const fetchMock = mockApi({ '/auth/login': () => json(200, ALICE) })
    const onUserChange = vi.fn()
    render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={null} onUserChange={onUserChange} />)
    await openForm()
    await fillAndSubmit('alice@example.fr', 'correct-horse-battery')

    expect(onUserChange).toHaveBeenCalledWith(ALICE)
    const [, init] = fetchMock.mock.calls[0]
    expect(init?.method).toBe('POST')
    expect(init?.credentials).toBe('include') // le navigateur garde et renvoie le cookie
    expect(JSON.parse(String(init?.body))).toEqual({ email: 'alice@example.fr', password: 'correct-horse-battery' })
  })

  it.each([
    // Même message pour un compte pas encore confirmé (V7.5) : personne ne peut savoir qui est inscrit.
    [401, 'E-mail ou mot de passe incorrect. Si vous venez de vous inscrire, confirmez d’abord votre adresse.'],
    [429, 'Trop d’essais de connexion. Réessayez dans 15 minutes.'],
    [503, 'Serveur occupé, réessayez dans un instant'],
  ])('affiche le message de l’API (%i)', async (status, detail) => {
    mockApi({ '/auth/login': () => json(status, { detail }) })
    const onUserChange = vi.fn()
    render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={null} onUserChange={onUserChange} />)
    await openForm()
    await fillAndSubmit('alice@example.fr', 'mauvais-mot-de-passe')

    expect(await screen.findByRole('alert')).toHaveTextContent(detail)
    expect(onUserChange).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Mot de passe')).toHaveValue('mauvais-mot-de-passe') // on corrige sans tout retaper
  })

  it('serveur injoignable : message clair, pas de plantage', async () => {
    mockApi({})
    render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={null} onUserChange={vi.fn()} />)
    await openForm()
    await fillAndSubmit('alice@example.fr', 'correct-horse-battery')
    expect(await screen.findByRole('alert')).toHaveTextContent('Le serveur StationAlerte ne répond pas')
  })

  it('inscription : message « vérifiez vos e-mails », pas de connexion automatique', async () => {
    const fetchMock = mockApi({ '/auth/register': () => json(202, { detail: "Si cette adresse est valide, un e-mail vient de vous être envoyé. Ouvrez-le pour terminer l'inscription." }) })
    const onUserChange = vi.fn()
    render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={null} onUserChange={onUserChange} />)
    await openForm('register')

    expect(screen.getByText('12 caractères minimum.')).toBeInTheDocument()
    expect(screen.getByLabelText('Mot de passe')).toHaveAttribute('minlength', '12')
    expect(screen.getByLabelText('Mot de passe')).toHaveAttribute('autocomplete', 'new-password')
    await fillAndSubmit('alice@example.fr', 'correct-horse-battery', 'Créer mon compte')

    expect(fetchMock.mock.calls.map(([url]) => new URL(url).pathname)).toEqual(['/auth/register'])
    expect(onUserChange).not.toHaveBeenCalled() // l'adresse doit d'abord être confirmée (V7.3)
    expect(await screen.findByRole('status')).toHaveTextContent("Si cette adresse est valide, un e-mail vient de vous être envoyé. Ouvrez-le pour terminer l'inscription.")
    expect(screen.getByRole('heading', { name: 'Connexion' })).toBeInTheDocument() // prêt pour la suite
    expect(screen.getByLabelText('Mot de passe')).toHaveValue('')
  })

  it('lien de confirmation valable : adresse confirmée, formulaire de connexion ouvert', async () => {
    const fetchMock = mockApi({ '/auth/confirm-email': () => json(204, null) })
    const onConfirmDone = vi.fn()
    render(
      <AccountMenu resetToken={null} onResetDone={vi.fn()} confirmToken="jeton-ok" onConfirmDone={onConfirmDone} user={null} onUserChange={vi.fn()} />,
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Adresse e-mail confirmée : vous pouvez maintenant vous connecter.')
    expect(screen.getByRole('heading', { name: 'Connexion' })).toBeInTheDocument()
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ token: 'jeton-ok' })
    expect(onConfirmDone).toHaveBeenCalled()
  })

  it('lien de confirmation expiré : message de l’API', async () => {
    const detail = 'Lien invalide ou expiré. Connectez-vous pour en recevoir un nouveau.'
    mockApi({ '/auth/confirm-email': () => json(400, { detail }) })
    render(<AccountMenu resetToken={null} onResetDone={vi.fn()} confirmToken="jeton-expire" user={null} onUserChange={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(detail)
  })

  it.each([
    [429, { detail: 'Trop de demandes pour cette adresse e-mail. Réessayez dans une heure.' }, 'Trop de demandes pour cette adresse'],
    [422, { detail: [] }, 'mot de passe trop court (12 caractères minimum)'],
  ])('inscription refusée (%i)', async (status, body, message) => {
    mockApi({ '/auth/register': () => json(status, body) })
    render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={null} onUserChange={vi.fn()} />)
    await openForm('register')
    await fillAndSubmit('alice@example.fr', 'correct-horse-battery', 'Créer mon compte')
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
  })

  it('le champ mot de passe masque la saisie et limite la longueur', async () => {
    render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={null} onUserChange={vi.fn()} />)
    await openForm()
    const password = screen.getByLabelText('Mot de passe')
    expect(password).toHaveAttribute('type', 'password')
    expect(password).toHaveAttribute('maxlength', '128')
    expect(password).toHaveAttribute('autocomplete', 'current-password')
  })

  it('déconnexion', async () => {
    const fetchMock = mockApi({ '/auth/logout': () => Promise.resolve({ ok: true, status: 204 }) })
    const onUserChange = vi.fn()
    render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={ALICE} onUserChange={onUserChange} />)
    expect(screen.getByText('alice@example.fr')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Se déconnecter' }))

    expect(onUserChange).toHaveBeenCalledWith(null)
    expect(fetchMock.mock.calls[0][1]?.credentials).toBe('include')
  })

  it('déconnexion impossible : on reste connecté et on le dit', async () => {
    mockApi({})
    const onUserChange = vi.fn()
    render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={ALICE} onUserChange={onUserChange} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Se déconnecter' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Déconnexion impossible')
    expect(onUserChange).not.toHaveBeenCalled()
  })

  describe('mot de passe oublié', () => {
    const SENT = 'Si un compte existe pour cette adresse, un e-mail vient d’être envoyé. Le lien est valable 30 minutes.'

    it('demande un lien et affiche la réponse de l’API', async () => {
      const fetchMock = mockApi({ '/auth/password-reset/request': () => json(202, { detail: SENT }) })
      render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={null} onUserChange={vi.fn()} />)
      const user = userEvent.setup()
      await user.click(screen.getByRole('button', { name: 'Se connecter' }))
      await user.click(screen.getByRole('button', { name: 'Mot de passe oublié ?' }))

      expect(screen.queryByLabelText('Mot de passe')).not.toBeInTheDocument() // seulement l'e-mail
      await user.type(screen.getByLabelText('E-mail'), 'alice@example.fr')
      await user.click(screen.getByRole('button', { name: 'Recevoir un lien' }))

      expect(await screen.findByRole('status')).toHaveTextContent(SENT)
      expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ email: 'alice@example.fr' })
    })

    it('trop de demandes : message de l’API', async () => {
      const detail = 'Trop de demandes de réinitialisation. Réessayez dans une heure.'
      mockApi({ '/auth/password-reset/request': () => json(429, { detail }) })
      render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={null} onUserChange={vi.fn()} />)
      const user = userEvent.setup()
      await user.click(screen.getByRole('button', { name: 'Se connecter' }))
      await user.click(screen.getByRole('button', { name: 'Mot de passe oublié ?' }))
      await user.type(screen.getByLabelText('E-mail'), 'alice@example.fr')
      await user.click(screen.getByRole('button', { name: 'Recevoir un lien' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(detail)
    })
  })

  describe('nouveau mot de passe (arrivée par le lien de l’e-mail)', () => {
    async function fillNewPassword(password: string, confirmation = password) {
      const user = userEvent.setup()
      await user.type(screen.getByLabelText('Nouveau mot de passe'), password)
      await user.type(screen.getByLabelText('Confirmer le mot de passe'), confirmation)
      await user.click(screen.getByRole('button', { name: 'Enregistrer le mot de passe' }))
    }

    it('s’ouvre directement, enregistre, puis invite à se reconnecter', async () => {
      const fetchMock = mockApi({ '/auth/password-reset/confirm': () => Promise.resolve({ ok: true, status: 204 }) })
      const onResetDone = vi.fn()
      const onUserChange = vi.fn()
      render(<AccountMenu resetToken="jeton-du-lien" onResetDone={onResetDone} user={null} onUserChange={onUserChange} />)

      expect(screen.getByRole('heading', { name: 'Choisir un nouveau mot de passe' })).toBeInTheDocument()
      expect(screen.getByLabelText('Nouveau mot de passe')).toHaveAttribute('minlength', '12')
      await fillNewPassword('nouveau-mot-de-passe')

      expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ token: 'jeton-du-lien', password: 'nouveau-mot-de-passe' })
      expect(await screen.findByRole('status')).toHaveTextContent('Mot de passe modifié. Connectez-vous')
      expect(screen.getByRole('heading', { name: 'Connexion' })).toBeInTheDocument()
      expect(onResetDone).toHaveBeenCalled()
      expect(onUserChange).toHaveBeenCalledWith(null) // l'API a coupé toutes les sessions
    })

    it('les deux saisies doivent être identiques (vérifié avant l’envoi)', async () => {
      const fetchMock = mockApi({})
      render(<AccountMenu resetToken="jeton-du-lien" onResetDone={vi.fn()} user={null} onUserChange={vi.fn()} />)
      await fillNewPassword('nouveau-mot-de-passe', 'autre-mot-de-passe!')

      expect(await screen.findByRole('alert')).toHaveTextContent('Les deux mots de passe ne sont pas identiques.')
      expect(fetchMock).not.toHaveBeenCalled()
    })

    it('lien expiré : message de l’API', async () => {
      const detail = 'Lien invalide ou expiré. Faites une nouvelle demande.'
      mockApi({ '/auth/password-reset/confirm': () => json(400, { detail }) })
      render(<AccountMenu resetToken="vieux-jeton" onResetDone={vi.fn()} user={null} onUserChange={vi.fn()} />)
      await fillNewPassword('nouveau-mot-de-passe')
      expect(await screen.findByRole('alert')).toHaveTextContent(detail)
    })

    it('fonctionne même si on est déjà connecté', () => {
      render(<AccountMenu resetToken="jeton-du-lien" onResetDone={vi.fn()} user={ALICE} onUserChange={vi.fn()} />)
      expect(screen.getByRole('heading', { name: 'Choisir un nouveau mot de passe' })).toBeInTheDocument()
    })
  })

  describe('supprimer mon compte', () => {
    async function openDelete() {
      const user = userEvent.setup()
      await user.click(screen.getByRole('button', { name: 'Supprimer mon compte' }))
      return user
    }

    it('mot de passe redemandé, puis compte supprimé et déconnexion', async () => {
      const fetchMock = mockApi({ '/me': () => json(204, null) })
      const onUserChange = vi.fn()
      render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={ALICE} onUserChange={onUserChange} />)
      const user = await openDelete()
      expect(screen.getByText(/Cette action est/)).toHaveTextContent('définitive')
      await user.type(screen.getByLabelText('Mot de passe'), 'correct-horse-battery')
      await user.click(screen.getByRole('button', { name: 'Supprimer définitivement' }))

      const [url, init] = fetchMock.mock.calls[0]
      expect(new URL(url).pathname).toBe('/me')
      expect(init?.method).toBe('DELETE')
      expect(JSON.parse(String(init?.body))).toEqual({ password: 'correct-horse-battery' })
      expect(onUserChange).toHaveBeenCalledWith(null)
    })

    it('mauvais mot de passe : message de l’API, compte gardé', async () => {
      const detail = "Mot de passe incorrect : le compte n'a pas été supprimé."
      mockApi({ '/me': () => json(403, { detail }) })
      const onUserChange = vi.fn()
      render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={ALICE} onUserChange={onUserChange} />)
      const user = await openDelete()
      await user.type(screen.getByLabelText('Mot de passe'), 'pas-le-bon')
      await user.click(screen.getByRole('button', { name: 'Supprimer définitivement' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(detail)
      expect(onUserChange).not.toHaveBeenCalled()
    })

    it('« Annuler » revient au compte sans rien envoyer', async () => {
      const fetchMock = mockApi({})
      render(<AccountMenu resetToken={null} onResetDone={vi.fn()} user={ALICE} onUserChange={vi.fn()} />)
      const user = await openDelete()
      await user.click(screen.getByRole('button', { name: 'Annuler' }))
      expect(screen.getByRole('button', { name: 'Se déconnecter' })).toBeInTheDocument()
      expect(fetchMock).not.toHaveBeenCalled()
    })
  })
})
