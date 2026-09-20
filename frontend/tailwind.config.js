/** Colors map to the CSS custom properties in src/index.css so light and dark
 *  are two selected palettes rather than an automatic inversion. */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        surface: 'var(--surface-1)',
        plane: 'var(--page-plane)',
        ink: 'var(--text-primary)',
        'ink-secondary': 'var(--text-secondary)',
        'ink-muted': 'var(--text-muted)',
        hairline: 'var(--border-hairline)',
        grid: 'var(--gridline)',
        good: 'var(--status-good)',
        warning: 'var(--status-warning)',
        serious: 'var(--status-serious)',
        critical: 'var(--status-critical)',
        's-1': 'var(--series-1)',
        's-2': 'var(--series-2)',
        's-3': 'var(--series-3)',
        's-4': 'var(--series-4)',
      },
      fontFamily: { sans: ['system-ui', '-apple-system', 'Segoe UI', 'sans-serif'] },
    },
  },
  plugins: [],
}
