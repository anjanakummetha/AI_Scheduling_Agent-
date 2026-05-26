# Iconic Founders UI Style Guide

Use the Iconic Founders visual system for dashboard UI.

## Palette

- Near black: `#11100f`
- Soft panel black: `#211f1c`
- Gold: `#d8b25d`
- Highlight gold: `#f1d48a`
- Muted text: `#b7ad99`
- Primary text: `#f7f4ea`

## Direction

- Premium, calm, executive dashboard.
- Dark background with restrained gold accents.
- Rounded cards, subtle borders, and soft shadows.
- Use gold for primary actions, key labels, and section accents.
- Keep destructive actions red and visually distinct.

## Implementation

- Shared CSS lives in `app/dashboard/static/theme.css`.
- Prefer reusable classes from the theme over inline styles.
- Future dashboard pages should include `/static/theme.css`.
