# Design Brief: Agent Hub Global Styles Redesign

## Context
Agent Hub is an AI Delivery Platform — enterprise clients send one-sentence requests, an AI agent team executes them, and deliverables go live. The current design is "dark SaaS with indigo accent" — competent but generic, lacking visual identity.

## Target
Redesign `src/styles/main.css` (the global design system) to give Agent Hub a distinctive, memorable visual identity.

## Design Direction: **"Liquid Metal + Warm Light"**

### Concept
A dark interface that feels alive — not flat-black but deep charcoal with subtle warm undertones. Surfaces feel like brushed metal: slight grain, soft reflections, smooth transitions. Accent colors are used sparingly and deliberately, like indicator lights on a precision instrument.

### Specific Requirements

1. **Palette Rethink**
   - Backgrounds: deep warm charcoal (not pure black), layered with subtle warmth
   - Primary accent: a warm amber/gold (suggests precision, value, AI intelligence) — not the overused indigo
   - Secondary: a cool teal/cyan for contrast against the warm base
   - Tertiary: reserved for critical states (red for errors, green for success)
   - Every color should have a job; no decorative-only colors

2. **Surface & Depth**
   - Cards and panels: subtle inner glow at edges (like light catching brushed metal)
   - Sidebar: distinct material feel from main content (darker, slightly textured)
   - Elevation: 4 deliberate levels (base, raised, overlay, modal) — not arbitrary shadows

3. **Typography**
   - Keep Inter/PingFang SC but with intentional scale hierarchy
   - Headings: tighter tracking, higher weight contrast
   - Use font-weight strategically: 400/500/600/700 — no intermediate weights
   - Monospace for data/tokens only

4. **Motion**
   - All transitions: 200-300ms, cubic-bezier(0.16, 1, 0.3, 1) — snappy, confident
   - Hover states: subtle scale + shadow lift, not just color change
   - Active states: inset shadows, pressed feel
   - Page transitions: fade + slight Y shift (5px)

5. **Light Mode**
   - Warm white/cream base (not sterile white)
   - Soft shadows, visible but gentle borders
   - Must feel equally intentional as dark mode

6. **Anti-Patterns to Avoid**
   - Neon glow effects everywhere (reserve for status indicators)
   - Monospace for UI labels
   - Uniform border-radius (vary by element size)
   - Over-designed scrollbars
   - Gradient text on every heading

## Scope
- Only `src/styles/main.css` (global tokens, sidebar, Element Plus overrides, utilities)
- Must maintain all existing CSS variable names for component compatibility
- Can add new tokens, can change values of existing tokens
