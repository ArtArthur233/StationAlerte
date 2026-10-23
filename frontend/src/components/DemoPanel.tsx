import { useEffect, useState } from 'react'
import { changeTestStationFuel, fetchTestStation } from '../services/api'
import { FUEL_LABELS, type DemoChangeResult, type DemoStatus, type FuelType, type Station, type User } from '../types/station'

// Les six carburants connus (AUTRE n'a pas de sens pour une station fictive).
const FUELS: FuelType[] = ['GAZOLE', 'SP95', 'E10', 'SP98', 'E85', 'GPLC']
const CHOICES: { status: DemoStatus; label: string }[] = [
  { status: 'AVAILABLE', label: 'Disponible' },
  { status: 'UNAVAILABLE', label: 'Indisponible' },
  { status: 'UNKNOWN', label: 'Inconnu' },
  { status: 'NOT_SOLD', label: 'Non vendu' },
]
const MAILPIT_URL = 'http://localhost:8025'

// Ce qu'a donné le changement, en clair : pourquoi il y a (ou non) une alerte.
function outcome(result: DemoChangeResult): string {
  if (result.events === 0) {
    return 'Enregistré. Aucun changement de disponibilité : même état, ou carburant ajouté / retiré (jamais d’alerte dans ce cas).'
  }
  if (!result.alertsAllowed) {
    return 'Changement enregistré, mais aucune alerte : le surveillant est arrêté depuis plus de 20 minutes (règle de sécurité). Lancez-le, puis réessayez.'
  }
  if (result.alerts === 0) {
    return 'Changement enregistré. Aucune alerte : personne ne surveille ce carburant avec la préférence correspondante (« Inconnu » n’alerte jamais).'
  }
  const s = (n: number) => (n > 1 ? 's' : '')
  return `${result.alerts} alerte${s(result.alerts)} créée${s(result.alerts)}, ${result.emailsSent} e-mail${s(result.emailsSent)} envoyé${s(result.emailsSent)} : voir « Mes dernières alertes » et Mailpit.`
}

type Props = {
  user: User | null | undefined
  // true si tous les carburants de stationTest sont surveillés (le raccourci n'a plus rien à faire).
  watchingAll: boolean
  onWatchAll: (station: Station) => void
  onChanged: () => void // App recharge favoris, alertes et résultats de recherche
}

// Espace de démonstration (V8) : changer l'état de la station fictive stationTest depuis le site, pour essayer
// surveillance, alertes et e-mails. Masqué si l'API n'a pas le mode démo (404) ou ne répond pas.
export function DemoPanel({ user, watchingAll, onWatchAll, onChanged }: Props) {
  // undefined = chargement ; null = pas encore créée ; 'off' = mode démo absent : rien n'est affiché.
  const [station, setStation] = useState<Station | null | undefined | 'off'>(undefined)
  const [pending, setPending] = useState<FuelType | null>(null)
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null)

  useEffect(() => {
    let ignore = false
    fetchTestStation()
      .then((data) => !ignore && setStation(data))
      .catch(() => !ignore && setStation('off'))
    return () => {
      ignore = true
    }
  }, [])

  if (station === undefined || station === 'off') return null

  const statusOf = (type: FuelType): DemoStatus => station?.fuels.find((fuel) => fuel.type === type)?.status ?? 'NOT_SOLD'

  async function change(type: FuelType, status: DemoStatus) {
    setPending(type)
    setMessage(null)
    try {
      const result = await changeTestStationFuel(type, status)
      setStation(result.station)
      setMessage({ text: outcome(result), error: false })
      onChanged()
    } catch {
      setMessage({ text: 'Impossible de changer stationTest : le serveur StationAlerte ne répond pas. Réessayez.', error: true })
    } finally {
      setPending(null)
    }
  }

  return (
    <section className="section demo-zone" aria-labelledby="demo-title">
      <div className="demo-zone__header">
        <h2 id="demo-title">Espace de démonstration</h2>
        <span className="demo-zone__badge">Station fictive</span>
      </div>
      <p>
        Ici, vous décidez de l’état des carburants de <strong>stationTest</strong>, une station <strong>fictive</strong>{' '}
        (toutes les autres sont réelles). Chaque changement suit le vrai chemin : historique, alertes et e-mails.
      </p>
      <ol className="demo-zone__steps">
        <li>Connectez-vous, par exemple avec le compte de démonstration <code>demo@test.fr</code> / <code>demo-stationalerte</code>.</li>
        <li>stationTest est toujours dans vos favoris : surveillez ses carburants (bouton ci-dessous).</li>
        <li>Changez un état : par exemple Gazole « Disponible », puis « Indisponible ».</li>
        <li>
          L’alerte apparaît dans « Mes dernières alertes », et l’e-mail dans{' '}
          <a href={MAILPIT_URL} target="_blank" rel="noreferrer">Mailpit</a> (boîte de réception de test).
        </li>
      </ol>

      <button type="button" disabled={!user || !station || watchingAll} onClick={() => station && onWatchAll(station)}>
        {watchingAll ? 'Tous les carburants de stationTest sont surveillés' : 'Surveiller tous les carburants de stationTest'}
      </button>
      {!user && <p className="watch-hint">Connectez-vous pour surveiller ses carburants et recevoir les alertes.</p>}
      {user && !station && <p className="watch-hint">Choisissez d’abord un état ci-dessous : la station sera créée.</p>}

      <ul className="demo-zone__fuels">
        {FUELS.map((type) => (
          <li key={type}>
            <span className="fuel-row__name">{FUEL_LABELS[type]}</span>
            {/* Boutons à bascule : aria-pressed dit aux lecteurs d'écran lequel est l'état actuel. */}
            <div className="demo-zone__choices" role="group" aria-label={`État du carburant ${FUEL_LABELS[type]}`}>
              {CHOICES.map(({ status, label }) => (
                <button
                  key={status}
                  type="button"
                  aria-pressed={statusOf(type) === status}
                  data-status={status} // couleur de l'état choisi (App.css), en plus du texte
                  disabled={pending !== null}
                  onClick={() => statusOf(type) !== status && change(type, status)}
                >
                  {label}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ul>
      {message && (
        <p role={message.error ? 'alert' : 'status'} className={message.error ? 'load-error' : 'demo-zone__result'}>
          {message.text}
        </p>
      )}
    </section>
  )
}
