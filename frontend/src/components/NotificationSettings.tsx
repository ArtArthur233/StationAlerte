import { useState } from 'react'
import { ApiError, setNotifications } from '../services/api'
import type { User } from '../types/station'

type Props = {
  user: User
  onUserChange: (user: User | null) => void
}

// Préférences du compte : quels changements des carburants surveillés déclencheront un e-mail.
export function NotificationSettings({ user, onUserChange }: Props) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(change: Partial<Pick<User, 'notifyUnavailable' | 'notifyAvailable'>>) {
    setSaving(true)
    setError(null)
    try {
      // Les deux réglages sont toujours envoyés ensemble : PUT remplace tout.
      const { notifyUnavailable, notifyAvailable } = user
      onUserChange(await setNotifications({ notifyUnavailable, notifyAvailable, ...change }))
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onUserChange(null) // session expirée
      else setError('Impossible d’enregistrer vos préférences : le serveur StationAlerte ne répond pas. Réessayez.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <fieldset className="alert-settings" disabled={saving}>
      <legend>M’alerter quand un carburant surveillé…</legend>
      <label>
        <span>devient indisponible</span>
        <input
          type="checkbox"
          className="switch"
          checked={user.notifyUnavailable}
          onChange={(e) => save({ notifyUnavailable: e.target.checked })}
        />
      </label>
      <label>
        <span>redevient disponible</span>
        <input
          type="checkbox"
          className="switch"
          checked={user.notifyAvailable}
          onChange={(e) => save({ notifyAvailable: e.target.checked })}
        />
      </label>
      <p>
        Les alertes sont envoyées par e-mail à <strong>{user.email}</strong>, au plus 10 minutes après le changement.
      </p>
      {error && (
        <p role="alert" className="load-error">
          {error}
        </p>
      )}
    </fieldset>
  )
}
