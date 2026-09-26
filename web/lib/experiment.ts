// Map UX experiments. Build-time switch, no UI toggle: set NEXT_PUBLIC_MAP_EXPERIMENT=off in web/.env to get the
// stable map on this branch for a side-by-side comparison. Only web/snapmap-experiment defaults to 'snapmap'.
export type MapExperiment = 'snapmap' | 'off';
export const parseExperiment = (v: string | undefined): MapExperiment => (v === 'off' ? 'off' : 'snapmap');
export const MAP_EXPERIMENT: MapExperiment = parseExperiment(process.env.NEXT_PUBLIC_MAP_EXPERIMENT);
