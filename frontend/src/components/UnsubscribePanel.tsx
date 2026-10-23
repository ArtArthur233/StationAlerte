import { useState } from 'react'
import { ApiError, unsubscribe } from '../services/api'

type Props = {
  token: string // jeton du lien « Ne plus recevoir d'alertes » de l'e-mail
  onUnsubscribed: () => void // les préférences ont changé : App relit le compte
  onClose: () => void
}

// Arrivée par le lien d'un e-mail d'alerte. Il faut cliquer sur « Confirmer » : certaines messageries et
// logiciels anti-spam ouvrent tous les liens d'un e-mail pour les vérifier, ils ne doivent pas désabonner.
export function UnsubscribePanel({ token, onUnsubscribed, onClose }: Props) {
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [sending, setSending] = useState(false)

  async function confirm() {
    setSending(true)
    try {
      setResult({ ok: true, message: (await unsubscribe(token)).detail })
      onUnsubscribed()
    } catch (error) {
      setResult({
        ok: false,
        message:
          error instanceof ApiError && error.status === 400
            ? error.message
            : 'Le serveur StationAlerte ne répond pas. Réessayez plus tard.',
      })
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="unsubscribe" aria-labelledby="unsubscribe-title">
      <h2 id="unsubscribe-title">Ne plus recevoir d’alertes par e-mail</h2>
      {result === null ? (
        <>
          <p>Vous ne recevrez plus aucun e-mail d’alerte. Votre compte et vos stations favorites sont gardés.</p>
          <div className="unsubscribe__actions">
            <button type="button" className="primary" onClick={confirm} disabled={sending}>
              Confirmer le désabonnement
            </button>
            <button type="button" className="link-button" onClick={onClose}>
              Annuler
            </button>
          </div>
        </>
      ) : (
        <>
          <p role={result.ok ? 'status' : 'alert'} className={result.ok ? undefined : 'load-error'}>
            {result.message}
          </p>
          <button type="button" className="link-button" onClick={onClose}>
            Fermer
          </button>
        </>
      )}
    </section>
  )
}
