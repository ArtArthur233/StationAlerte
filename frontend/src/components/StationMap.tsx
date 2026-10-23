import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { fetchCityBounds, fetchStationPositions } from '../services/api'
import type { Station } from '../types/station'
import { markerRadius } from '../utils/map'
import { useTheme } from '../utils/theme'

// Fond « Plan IGN » de la Géoplateforme : service public gratuit, sans clé, Licence Ouverte.
const IGN_TILES =
  'https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2' +
  '&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/png&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}'
const IGN_ATTRIBUTION = '<a href="https://www.ign.fr/">© IGN</a> Plan IGN'
const FRANCE_CENTER: L.LatLngTuple = [46.6, 2.4]

// Leaflet attend de vraies couleurs, pas des variables CSS : on lit celles du thème en cours (clair ou sombre).
function markerStyle(element: HTMLElement) {
  const css = getComputedStyle(element)
  return {
    fillColor: css.getPropertyValue('--color-marker').trim() || '#2f5bea',
    color: css.getPropertyValue('--color-marker-border').trim() || '#ffffff',
  }
}

type Props = {
  // Recherche en cours et ses résultats (null pendant le chargement) : la carte se cadre dessus.
  query: string
  results: Station[] | null
  // Doit garder la même identité (ex. un setState) : sinon la carte serait recréée à chaque rendu.
  onSelectAddress: (address: string) => void
}

// Affiche toutes les stations ; un clic sur l'une d'elles envoie son adresse à onSelectAddress.
export function StationMap({ query, results, onSelectAddress }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  // La carte Leaflet, gardée entre les rendus pour que l'effet de cadrage puisse la déplacer.
  const mapRef = useRef<L.Map | null>(null)
  const markersRef = useRef<L.CircleMarker[]>([])
  // Tous les points dans un même calque : le bouton « Masquer les stations » le retire de la carte d'un coup.
  const layerRef = useRef<L.LayerGroup | null>(null)
  const [showStations, setShowStations] = useState(true)
  const theme = useTheme()
  const [failed, setFailed] = useState(false)

  // Leaflet n'est pas un composant React : on crée la carte dans un effet et on la détruit au démontage.
  useEffect(() => {
    // Canevas : ~9 800 points dessinés sur un seul canevas, au lieu de 9 800 éléments SVG trop lents.
    // tolerance : un clic jusqu'à 6 px autour d'un point le sélectionne (plus facile au doigt), sans le grossir.
    const map = L.map(containerRef.current!, { renderer: L.canvas({ tolerance: 6 }) }).setView(FRANCE_CENTER, 6)
    L.tileLayer(IGN_TILES, { attribution: IGN_ATTRIBUTION, maxZoom: 18 }).addTo(map)
    mapRef.current = map
    const layer = L.layerGroup().addTo(map)
    layerRef.current = layer

    let ignore = false
    fetchStationPositions()
      .then((positions) => {
        if (ignore) return
        const style = markerStyle(containerRef.current!)
        markersRef.current = positions.map((station) =>
          // Un cercle plutôt que l'épingle par défaut, dont les images se perdent avec Vite.
          L.circleMarker([station.latitude, station.longitude], {
            // Semi-transparents : les noms des villes et la carte restent lisibles sous les points.
            radius: markerRadius(map.getZoom()), weight: 1, opacity: 0.8, fillOpacity: 0.6, ...style,
          })
            // Sans virgule : chaque mot vient des champs de la station, la recherche mot par mot la retrouve.
            .on('click', () => onSelectAddress(`${station.address} ${station.postalCode} ${station.city}`))
            .addTo(layer),
        )
      })
      .catch(() => !ignore && setFailed(true))
    map.on('zoomend', () => {
      const radius = markerRadius(map.getZoom())
      for (const marker of markersRef.current) marker.setRadius(radius)
    })

    return () => {
      ignore = true
      map.remove()
      mapRef.current = null
      layerRef.current = null
      markersRef.current = []
    }
  }, [onSelectAddress])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !layerRef.current) return
    if (showStations) layerRef.current.addTo(map)
    else layerRef.current.remove()
  }, [showStations])

  // Changement de thème : les points prennent les couleurs du nouveau thème, sans recréer la carte.
  useEffect(() => {
    const style = markerStyle(containerRef.current!)
    for (const marker of markersRef.current) marker.setStyle(style)
  }, [theme])

  // À chaque nouveau résultat : zoom sur la ville cherchée. Si la recherche n'en est pas une (« leclerc »)
  // ou si l'API ne répond pas, zoom sur le périmètre des stations trouvées (sans descendre jusqu'à la rue).
  useEffect(() => {
    if (results === null) return // recherche en cours : la carte ne bouge pas
    const points: L.LatLngTuple[] = results.flatMap((station) =>
      station.latitude === null || station.longitude === null ? [] : [[station.latitude, station.longitude]],
    )
    let ignore = false
    fetchCityBounds(query)
      .then((city): L.LatLngTuple[] => (city ? [[city.south, city.west], [city.north, city.east]] : points))
      .catch(() => points)
      .then((bounds) => {
        if (!ignore && bounds.length > 0) mapRef.current?.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 })
      })
    return () => {
      ignore = true
    }
  }, [query, results])

  return (
    <>
      {failed && (
        <p role="alert" className="load-error">
          Impossible d’afficher les stations sur la carte : le serveur StationAlerte ne répond pas.
        </p>
      )}
      <div className="station-map-wrapper">
        <div ref={containerRef} className="station-map" role="region" aria-label="Carte de toutes les stations" />
        <button type="button" className="map-toggle" onClick={() => setShowStations((shown) => !shown)}>
          {showStations ? 'Masquer les stations' : 'Afficher les stations'}
        </button>
      </div>
    </>
  )
}
