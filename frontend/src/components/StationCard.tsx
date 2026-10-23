import { fuelName, type FuelType, type Station } from '../types/station'
import { displayedStatus, isStale } from '../utils/stations'
import { StatusBadge } from './StatusBadge'

const dateFormat = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
// 3 décimales comme le flux officiel : « 1,789 €/L ».
const priceFormat = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

// favorite : absent quand personne n'est connecté (pas de bouton) ; sinon l'état et l'action du bouton ☆ / ★.
// permanent : favori imposé (stationTest, la station de démonstration) : étoile pleine, sans bouton pour la retirer.
// watch : seulement dans « Mes stations favorites » : une case « Surveiller » par carburant.
type Props = {
  station: Station
  favorite?: { active: boolean; onToggle: () => void; disabled?: boolean; permanent?: boolean }
  watch?: { fuels: FuelType[]; onToggle: (type: FuelType) => void; disabled?: boolean }
}

export function StationCard({ station, favorite, watch }: Props) {
  return (
    <article className="station-card" aria-labelledby={`station-${station.id}`} data-station-id={station.id}>
      <div className="station-card__header">
        <h2 id={`station-${station.id}`}>{station.name}</h2>
        {favorite?.permanent ? (
          <span
            className="favorite-button favorite-button--active favorite-button--permanent"
            role="img"
            aria-label={`Favori permanent : ${station.name}`}
            title="Favori permanent : station de démonstration"
          >
            ★
          </span>
        ) : favorite && (
          <button
            type="button"
            className={favorite.active ? 'favorite-button favorite-button--active' : 'favorite-button'}
            // Le nom de la station est ajouté pour les lecteurs d'écran : dans une liste, on sait quel bouton c'est.
            aria-label={`${favorite.active ? 'Retirer des favoris' : 'Ajouter aux favoris'} : ${station.name}`}
            disabled={favorite.disabled}
            onClick={favorite.onToggle}
          >
            <span aria-hidden="true">{favorite.active ? '★' : '☆'}</span>
          </button>
        )}
      </div>
      <p className="station-card__address">
        {station.address}, {station.postalCode} {station.city}
      </p>

      <ul className="fuel-list">
        {station.fuels.map((fuel) => (
          <li key={fuel.type} className="fuel-row">
            <span className="fuel-row__name">{fuelName(fuel)}</span>
            <StatusBadge status={displayedStatus(fuel)} />
            {fuel.price != null && (
              // Un prix ancien reste affiché (utile), mais en retrait : sa date est juste en dessous.
              <span className={isStale(fuel) ? 'fuel-row__price fuel-row__price--stale' : 'fuel-row__price'}>
                {priceFormat.format(fuel.price)}&nbsp;€/L
              </span>
            )}
            <span className="fuel-row__date">
              {fuel.updatedAt === null
                ? 'Aucune information'
                : `Mis à jour le ${dateFormat.format(new Date(fuel.updatedAt))}`}
              {isStale(fuel) && <strong className="stale"> · Donnée ancienne</strong>}
            </span>
            {watch && (
              <label className="watch-toggle">
                Surveiller
                <input
                  type="checkbox"
                  className="switch"
                  checked={watch.fuels.includes(fuel.type)}
                  disabled={watch.disabled}
                  onChange={() => watch.onToggle(fuel.type)}
                  // Nom complet pour les lecteurs d'écran : « Surveiller Gazole : Station a ».
                  aria-label={`Surveiller ${fuelName(fuel)} : ${station.name}`}
                />
              </label>
            )}
          </li>
        ))}
      </ul>
      {watch && watch.fuels.length === 0 && (
        <p className="watch-hint">Aucun carburant surveillé : activez « Surveiller » pour recevoir des alertes.</p>
      )}
    </article>
  )
}
