import { readFileSync } from 'node:fs';
import { downloadNames, readAsset, scoredGames } from '../../lib/data';

export function getStaticPaths() {
  return [
    ...downloadNames.map(file => ({ params: { file }, props: { asset: file } })),
    ...['main.pdf', 'main.tex'].map(file => ({ params: { file }, props: { paper: file } })),
    ...[...new Set(scoredGames().map(row => row.season))].map(season => ({ params: { file: season + '-forecasts.json' }, props: { season } })),
  ];
}

export function GET({ props }) {
  if (props.season) {
    return Response.json(scoredGames().filter(row => row.season === props.season));
  }
  if (props.paper) return new Response(readFileSync('../paper/' + props.paper));
  return new Response(readAsset('downloads/' + props.asset));
}
