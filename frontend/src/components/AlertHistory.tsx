import { useEffect, useState } from 'react'
import { ApiError, fetchAlerts } from '../services/api'
import { fuelName, type AlertItem, type User } from '../types/station'
import { StatusBadge } from './StatusBadge'

const dateFormat = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
// Toujours visibles ; les plus anciennes sont dans une liste à dérouler.
const ALWAYS_VISIBLE = 3

// Le texte dit tout : l'état de l'envoi ne repose jamais sur la seule couleur.
function delivery(alert: AlertItem): string {
  switch (alert.status) {
    case 'sent':
      return `E-mail envoyé le ${dateFormat.format(new Date(alert.sentAt!))}`
    case 'pending':
      return 'E-mail en attente d’envoi'
    case 'failed':
      return 'Échec de l’envoi de l’e-mail'
    case 'expired':
      return 'E-mail non envoyé : information devenue trop ancienne (plus de 2 h)'
  }
}

// onUserChange : setUser de App (identité stable, sinon l'effet ci-dessous rechargerait en boucle).
// reloadKey : change quand App sait qu'une alerte a pu être créée (espace de démonstration) : rechargement.
type Props = { onUserChange: (user: User | null) => void; reloadKey?: number }

// « Mes dernières alertes » : historique des alertes du compte et de leur envoi (GET /me/alerts).
export function AlertHistory({ onUserChange, reloadKey = 0 }: Props) {
  // null = échec du chargement ; undefined = chargement en cours.
  const [alerts, setAlerts] = useState<AlertItem[] | null | undefined>(undefined)
  const [refresh, setRefresh] = useState(0) // incrémenté par « Actualiser » : relance le chargement
  const [showOlder, setShowOlder] = useState(false) // liste des plus anciennes déroulée

  useEffect(() => {
    let ignore = false
    fetchAlerts()
      .then((data) => !ignore && setAlerts(data))
      .catch((error) => {
        if (ignore) return
        if (error instanceof ApiError && error.status === 401) onUserChange(null) // session expirée
        else setAlerts(null)
      })
    return () => {
      ignore = true
    }
  }, [refresh, reloadKey, onUserChange])

  return (
    <section className="section" aria-labelledby="alert-history-title">
      <div className="section__header">
        <h2 id="alert-history-title">Mes dernières alertes</h2>
        <button type="button" onClick={() => setRefresh((n) => n + 1)} disabled={alerts === undefined}>
          Actualiser
        </button>
      </div>
      {alerts === undefined ? (
        <p className="result-count">Chargement de vos alertes…</p>
      ) : alerts === null ? (
        <p role="alert" className="load-error">
          Impossible de charger vos alertes : le serveur StationAlerte ne répond pas. Réessayez plus tard.
        </p>
      ) : alerts.length === 0 ? (
        <p className="empty">
          Aucune alerte pour l’instant. Vous en recevrez une quand un carburant surveillé changera d’état.
        </p>
      ) : (
        <div className="alert-list">
          <ul>{alerts.slice(0, ALWAYS_VISIBLE).map(row)}</ul>
          {alerts.length > ALWAYS_VISIBLE && (
            // <details> : menu déroulant natif, utilisable au clavier et annoncé par les lecteurs d'écran.
            <details className="alert-list__older" onToggle={(e) => setShowOlder(e.currentTarget.open)}>
              <summary>
                {showOlder
                  ? 'Masquer les alertes plus anciennes'
                  : `Voir les ${alerts.length - ALWAYS_VISIBLE} alerte${alerts.length - ALWAYS_VISIBLE > 1 ? 's' : ''} plus ancienne${alerts.length - ALWAYS_VISIBLE > 1 ? 's' : ''}`}
              </summary>
              <ul>{alerts.slice(ALWAYS_VISIBLE).map(row)}</ul>
            </details>
          )}
        </div>
      )}
    </section>
  )
}

function row(alert: AlertItem) {
  return (
    <li key={alert.id} className="alert-row">
      <span className="alert-row__what">
        <strong>{alert.stationName}</strong> · {fuelName({ type: alert.fuelType, label: alert.label })} :{' '}
        <StatusBadge status={alert.oldStatus} /> <span aria-label="devient">→</span>{' '}
        <StatusBadge status={alert.newStatus} />
      </span>
      <span className="alert-row__when">
        Détecté le {dateFormat.format(new Date(alert.createdAt))} · {delivery(alert)}
      </span>
    </li>
  )
}
