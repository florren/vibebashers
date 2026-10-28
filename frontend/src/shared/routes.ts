export const ROUTES = {
  trace: '/trace',
  traceObject: (kind: string, ref: string) => `/trace/${encodeURIComponent(kind)}/${encodeURIComponent(ref)}`,
  journey: '/journey',
  journeyObject: (ref: string) => `/journey/${encodeURIComponent(ref)}`,
} as const
