// Taille des points selon le zoom : petits sur la France entière (sinon un tapis de points), assez gros pour être
// touchés du doigt à l'échelle d'une ville.
export function markerRadius(zoom: number): number {
  if (zoom <= 6) return 3
  if (zoom <= 8) return 4
  if (zoom <= 10) return 5
  if (zoom <= 12) return 7
  return 9
}
