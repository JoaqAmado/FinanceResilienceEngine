/**
 * Chart colours (SVG attributes need literal values; these mirror src/styles/tokens.css).
 * Series meaning is fixed across every chart: blue = judges' formula, orange = reality check,
 * aqua = backup plan, slate = no shock. Each series also has its own line pattern, so identity
 * never rests on colour alone.
 */
export const COLORS = {
  judges: '#2a78d6',
  reality: '#eb6834',
  plan: '#12946a', // same hue as before, darkened to clear 3:1 on white
  base: '#64748b',
  accent: '#f47920',
  ink: '#13233f',
  ink2: '#2b3a55',
  muted: '#5b6474', // tick labels: 5.97:1 on white
  grid: '#efe4d6',
  axis: '#b8a68e', // axis line, decorative
  surface: '#ffffff',
  histIn: '#c9b9a3', // warm sand, not orange: orange means "reality check" in this app
  histOut: '#e3d6c4',
  histBalance: '#2b3a55',
  cursor: 'rgba(244, 121, 32, 0.08)', // peach hover column
} as const;

/** stroke-dasharray per series ('' = solid). */
export const DASH = {
  judges: '',
  reality: '6 4',
  plan: '12 5',
  base: '2 4',
} as const;
