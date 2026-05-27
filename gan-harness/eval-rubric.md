# Design Evaluation Rubric

## Design Quality (weight: 0.35)
- Visual hierarchy: clear distinction between primary/secondary/tertiary content
- Spatial rhythm: spacing is intentional, not uniform
- Color harmony: palette feels cohesive and purposeful
- Typography: scale, weight, and spacing work together
- Consistency: design tokens used systematically across all elements

## Originality (weight: 0.30)
- Distinctive identity: recognizable as Agent Hub, not a generic template
- Memorable moments: at least 2-3 design details that surprise and delight
- Creative use of depth, texture, or material metaphors
- Avoids overused patterns (neon-on-black, uniform glassmorphism, standard SaaS layouts)
- Palette choices show independent thinking

## Craft (weight: 0.25)
- Light mode feels equally intentional as dark mode
- Hover/focus/active states are designed, not default
- Element Plus overrides feel native to the design system
- Transitions are smooth, durations are appropriate
- No visual glitches at common viewport sizes (no side effects)
- Scrollbars, focus rings, selection colors are considered

## Functionality (weight: 0.10)
- All existing CSS variable names preserved (components must not break)
- Both light and dark modes are complete
- Sidebar, main content, scroll behavior all work correctly
- Element Plus components render correctly in both modes
- No regression in layout or readability

## Scoring
Each dimension scored 1-10. Weighted average ≥ 7.5 to pass.

1-3: Broken / Template-level
4-5: Functional but generic
6-7: Competent, on-brand
8-9: Distinctive, award-worthy
10: Reference-quality, best-in-class
