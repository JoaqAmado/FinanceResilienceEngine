/**
 * Chart colours (SVG attributes need literal values; these mirror src/styles/tokens.css).
 * Series meaning is fixed across every chart: blue = judges' formula, orange = reality check,
 * aqua = backup plan, slate = no shock. Each series also has its own line pattern, so identity
 * never rests on colour alone.
 */
export const COLORS = {
  judges: '#2a78d6',
  reality: '#eb6834',
  plan: '#1baf7a',
  base: '#64748b',
  accent: '#f47920',
  ink: '#0f172a',
  ink2: '#334155',
  muted: '#64748b',
  grid: '#e2e8f0',
  axis: '#94a3b8',
  surface: '#ffffff',
  histIn: '#a5b4c8',
  histOut: '#cbd5e1',
  histBalance: '#334155',
} as const;

/** stroke-dasharray per series ('' = solid). */
export const DASH = {
  judges: '',
  reality: '6 4',
  plan: '12 5',
  base: '2 4',
} as const;
