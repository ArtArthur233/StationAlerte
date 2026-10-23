import { useEffect, useState, type FormEvent } from 'react'
import {
  ApiError,
  confirmEmail,
  confirmPasswordReset,
  deleteAccount,
  login,
  logout,
  register,
  requestPasswordReset,
} from '../services/api'
import type { User } from '../types/station'

// Mêmes règles que l'API (backend/app/schemas.py) : le navigateur prévient avant même l'envoi.
const MIN_PASSWORD_LENGTH = 12
const MAX_PASSWORD_LENGTH = 128

type Mode = 'login' | 'register' | 'forgot' | 'reset'

const TITLES: Record<Mode, string> = {
  login: 'Connexion',
  register: 'Créer un compte',
  forgot: 'Mot de passe oublié',
  reset: 'Choisir un nouveau mot de passe',
}
const SUBMIT_LABELS: Record<Mode, string> = {
  login: 'Se connecter',
  register: 'Créer mon compte',
  forgot: 'Recevoir un lien',
  reset: 'Enregistrer le mot de passe',
}

// Messages de l'API (400, 401, 403, 409, 429, 503) déjà rédigés en français ; les autres cas sont traduits ici.
function errorMessage(error: unknown, mode: Mode): string {
  if (error instanceof ApiError && [400, 401, 403, 409, 429, 503].includes(error.status)) return error.message
  if (error instanceof ApiError && error.status === 422) {
    return mode === 'register' || mode === 'reset'
      ? `E-mail invalide, ou mot de passe trop court (${MIN_PASSWORD_LENGTH} caractères minimum).`
      : 'E-mail invalide.'
  }
  return 'Le serveur StationAlerte ne répond pas. Réessayez plus tard.'
}

// En développement, React lance chaque effet deux fois (StrictMode). Un lien de confirmation ne sert qu'une
// fois : le second appel répondrait « Lien invalide ». Un seul appel par jeton, gardé ici.
const confirmations = new Map<string, Promise<void>>()
function confirmOnce(token: string): Promise<void> {
  if (!confirmations.has(token)) confirmations.set(token, confirmEmail(token))
  return confirmations.get(token)!
}

type Props = {
  user: User | null | undefined // undefined : on ne sait pas encore (réponse de /me en attente)
  onUserChange: (user: User | null) => void
  resetToken: string | null // jeton du lien « mot de passe oublié » reçu par e-mail, s'il y en a un
  onResetDone: () => void
  confirmToken?: string | null // jeton du lien de confirmation de l'adresse reçu par e-mail (V7.3)
  onConfirmDone?: () => void
}

// En-tête : « Se connecter » (connexion, inscription, mot de passe oublié), ou le compte connecté.
export function AccountMenu({ user, onUserChange, resetToken, onResetDone, confirmToken = null, onConfirmDone }: Props) {
  // Arrivée par le lien de l'e-mail : le formulaire « nouveau mot de passe » s'ouvre directement.
  const [open, setOpen] = useState(resetToken !== null || confirmToken !== null)
  const [mode, setMode] = useState<Mode>(resetToken !== null ? 'reset' : 'login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null) // message de réussite (lien envoyé, mot de passe changé)
  const [submitting, setSubmitting] = useState(false)
  const [deleting, setDeleting] = useState(false) // formulaire « Supprimer mon compte » ouvert

  // Arrivée par le lien de confirmation : l'adresse est confirmée, puis le formulaire de connexion s'affiche.
  useEffect(() => {
    if (confirmToken === null) return
    let ignore = false
    confirmOnce(confirmToken)
      .then(() => !ignore && setInfo('Adresse e-mail confirmée : vous pouvez maintenant vous connecter.'))
      .catch((caught) => !ignore && setError(errorMessage(caught, 'login')))
      .finally(() => !ignore && onConfirmDone?.())
    return () => {
      ignore = true
    }
  }, [confirmToken, onConfirmDone])

  if (user === undefined) return null

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
    setInfo(null)
  }

  if (user && mode !== 'reset') {
    async function handleLogout() {
      setError(null)
      try {
        await logout()
        onUserChange(null)
      } catch {
        setError('Déconnexion impossible : le serveur ne répond pas. Réessayez.')
      }
    }

    async function handleDelete(event: FormEvent) {
      event.preventDefault()
      setError(null)
      setSubmitting(true)
      try {
        await deleteAccount(password)
        setPassword('')
        setDeleting(false)
        setOpen(true)
        setMode('login')
        setInfo('Votre compte a été supprimé, avec vos favoris et vos alertes.')
        onUserChange(null)
      } catch (caught) {
        setError(errorMessage(caught, 'login'))
      } finally {
        setSubmitting(false)
      }
    }

    if (deleting) {
      return (
        <form className="account account--form" onSubmit={handleDelete} aria-label="Supprimer mon compte">
          <h2>Supprimer mon compte</h2>
          <p className="account__hint">
            Cette action est <strong>définitive</strong> : vos stations favorites, vos alertes et vos préférences seront
            supprimées. Pour confirmer, saisissez votre mot de passe.
          </p>
          <label>
            Mot de passe
            <input
              type="password"
              required
              maxLength={MAX_PASSWORD_LENGTH}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error && <p role="alert" className="account__error">{error}</p>}
          <div className="account__actions">
            <button type="submit" className="danger" disabled={submitting}>
              Supprimer définitivement
            </button>
            <button
              type="button"
              className="link-button"
              onClick={() => {
                setDeleting(false)
                setPassword('')
                setError(null)
              }}
            >
              Annuler
            </button>
          </div>
        </form>
      )
    }

    return (
      <div className="account">
        <span className="account__email">
          Connecté : <strong>{user.email}</strong>
        </span>
        <button type="button" onClick={handleLogout}>
          Se déconnecter
        </button>
        <button type="button" className="link-button" onClick={() => setDeleting(true)}>
          Supprimer mon compte
        </button>
        {error && <p role="alert" className="account__error">{error}</p>}
      </div>
    )
  }

  if (!open) {
    return (
      <div className="account">
        <button type="button" className="primary" onClick={() => setOpen(true)}>
          Se connecter
        </button>
      </div>
    )
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setInfo(null)
    if (mode === 'reset' && password !== passwordConfirm) {
      setError('Les deux mots de passe ne sont pas identiques.')
      return
    }
    setSubmitting(true)
    try {
      if (mode === 'forgot') {
        setInfo((await requestPasswordReset(email)).detail)
      } else if (mode === 'reset') {
        await confirmPasswordReset(resetToken ?? '', password)
        // Toutes les sessions ont été coupées par l'API : on se reconnecte avec le nouveau mot de passe.
        setPassword('')
        setPasswordConfirm('')
        onResetDone()
        onUserChange(null)
        switchMode('login')
        setInfo('Mot de passe modifié. Connectez-vous avec votre nouveau mot de passe.')
      } else if (mode === 'register') {
        // Pas de connexion automatique : l'adresse doit d'abord être confirmée par le lien reçu (V7.3).
        const { detail } = await register(email, password)
        setPassword('')
        setMode('login')
        setInfo(detail)
      } else {
        const connected = await login(email, password)
        setPassword('') // le mot de passe ne reste pas en mémoire une fois utilisé
        setOpen(false)
        onUserChange(connected)
      }
    } catch (caught) {
      setError(errorMessage(caught, mode))
    } finally {
      setSubmitting(false)
    }
  }

  const needsEmail = mode !== 'reset'
  const needsPassword = mode !== 'forgot'
  const newPassword = mode === 'register' || mode === 'reset'

  return (
    <form className="account account--form" onSubmit={handleSubmit} aria-label={TITLES[mode]}>
      <h2>{TITLES[mode]}</h2>
      {mode === 'forgot' && <p className="account__hint">Indiquez votre e-mail : vous recevrez un lien pour choisir un nouveau mot de passe.</p>}
      {needsEmail && (
        <label>
          E-mail
          <input type="email" required maxLength={254} autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
      )}
      {needsPassword && (
        <label>
          {mode === 'reset' ? 'Nouveau mot de passe' : 'Mot de passe'}
          <input
            type="password"
            required
            // Pour un nouveau mot de passe seulement : si la règle change, les anciens comptes doivent pouvoir se connecter.
            minLength={newPassword ? MIN_PASSWORD_LENGTH : undefined}
            maxLength={MAX_PASSWORD_LENGTH}
            autoComplete={newPassword ? 'new-password' : 'current-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
      )}
      {mode === 'reset' && (
        <label>
          Confirmer le mot de passe
          <input
            type="password"
            required
            minLength={MIN_PASSWORD_LENGTH}
            maxLength={MAX_PASSWORD_LENGTH}
            autoComplete="new-password"
            value={passwordConfirm}
            onChange={(e) => setPasswordConfirm(e.target.value)}
          />
        </label>
      )}
      {newPassword && <p className="account__hint">{MIN_PASSWORD_LENGTH} caractères minimum.</p>}
      {error && <p role="alert" className="account__error">{error}</p>}
      {info && <p role="status" className="account__info">{info}</p>}
      <div className="account__actions">
        <button type="submit" disabled={submitting}>
          {SUBMIT_LABELS[mode]}
        </button>
        {mode === 'login' && (
          <>
            <button type="button" className="link-button" onClick={() => switchMode('register')}>
              Créer un compte
            </button>
            <button type="button" className="link-button" onClick={() => switchMode('forgot')}>
              Mot de passe oublié ?
            </button>
          </>
        )}
        {(mode === 'register' || mode === 'forgot') && (
          <button type="button" className="link-button" onClick={() => switchMode('login')}>
            {mode === 'register' ? 'J’ai déjà un compte' : 'Retour à la connexion'}
          </button>
        )}
        <button
          type="button"
          className="link-button"
          onClick={() => {
            if (mode === 'reset') onResetDone()
            switchMode('login')
            setOpen(false)
          }}
        >
          Annuler
        </button>
      </div>
    </form>
  )
}
