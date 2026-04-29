# Skill: DESIGN.md Visual Identity Specification

Use this skill to create a DESIGN.md file that documents your project's visual identity for AI coding agents.

## When to Use

- Initialize a new project with design tokens
- Document existing design system for agents
- Generate UI components that match brand identity

## The Format

A DESIGN.md file has two layers:

1. **YAML front matter** — Machine-readable design tokens
2. **Markdown body** — Human-readable design rationale

```md
---
name: Brand Name
colors:
  primary: "#HexColor"
  secondary: "#HexColor"
  accent: "#HexColor"
typography:
  h1:
    fontFamily: Font Name
    fontSize: 3rem
    fontWeight: 700
components:
  button:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: 8px
---

## Overview

Brief description of the design direction.

## Colors

- **Primary:** Usage and rationale
- **Secondary:** Usage and rationale
```

## Sample DESIGN.md

```md
---
name: TrendForge
colors:
  background: "#0D0D12"
  surface: "#16161D"
  primary: "#534AB7"
  accent: "#EF9F27"
  text-primary: "#FFFFFF"
  text-secondary: "#A0A0B0"
  border: "#2A2A35"
typography:
  h1:
    fontFamily: Space Grotesk
    fontSize: 2.5rem
    fontWeight: 700
  h2:
    fontFamily: Space Grotesk
    fontSize: 1.75rem
    fontWeight: 600
  body:
    fontFamily: Inter
    fontSize: 1rem
    fontWeight: 400
  caption:
    fontFamily: Inter
    fontSize: 0.875rem
rounded:
  sm: 6px
  md: 12px
  lg: 16px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#FFFFFF"
    rounded: "{rounded.md}"
    padding: "12px 24px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-primary}"
    border: "1px solid {colors.border}"
    rounded: "{rounded.md}"
  card:
    backgroundColor: "{colors.surface}"
    border: "1px solid {colors.border}"
    rounded: "{rounded.lg}"
    padding: "{spacing.lg}"
  input:
    backgroundColor: "{colors.surface}"
    border: "1px solid {colors.border}"
    textColor: "{colors.text-primary}"
    placeholderColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
---

## Overview

Dark-themed professional content creation platform. Inspired by 
premium DAW interfaces and code editors. High contrast for readability
in low-light environments.

## Colors

- **Background (#0D0D12):** Main app background, near-black
- **Surface (#16161D):** Cards, inputs, elevated surfaces
- **Primary (#534AB7):** Brand purple, CTAs and highlights
- **Accent (#EF9F27):** Warm orange for notifications and alerts
- **Text Primary (#FFFFFF):** High contrast white for main content
- **Text Secondary (#A0A0B0):** Muted for metadata and captions

## Typography

- **Space Grotesk:** Headlines — modern, geometric, distinctive
- **Inter:** Body text — highly readable at small sizes

## Components

- Buttons use solid fills with subtle rounded corners
- Cards have thin borders, not shadows
- Inputs use background surfaces with clear focus states