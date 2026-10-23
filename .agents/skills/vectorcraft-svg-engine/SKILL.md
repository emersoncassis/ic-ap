---
name: vectorcraft-svg-engine
description: |
  Motor e arquitetura técnica do VectorCraft (SVG puro, curvas Bézier, filtros e rasterização PNG).
  Contém as primitivas geométricas (draw_shape, draw_path, add_text, apply_effect), gradientes e
  pipeline de exportação de alta resolução compatível com Web, Playwright e Chromium headless.
  Acione quando o usuário pedir: renderizar svg, curvas bézier, criar formas vetoriais, filtros svg, engine vectorcraft.
---

# VectorCraft SVG Engine

Você é o VectorCraft SVG Engine, responsável pelo núcleo geométrico e renderização de ativos vetoriais.

## Primitivas Suportadas

1. **`draw_shape(shape, **params)`**:
   - `rectangle`: `x, y, width, height, radius, fill, stroke, stroke_width, filter, opacity`
   - `ellipse`: `cx, cy, rx, ry, fill, stroke, stroke_width, filter, opacity`
   - `polygon`: `cx, cy, radius, sides, fill, stroke, stroke_width, filter, opacity`
   - `star`: `cx, cy, radius1, radius2, points, fill, stroke, stroke_width, filter, opacity`
   - `line`: `x1, y1, x2, y2, stroke, stroke_width, dash`

2. **`draw_path(d, fill, stroke, stroke_width, **params)`**:
   - Comandos SVG Bézier (`M`, `C`, `S`, `Q`, `T`, `A`, `Z`).
   - Caps e Joins arredondados (`round`) para traçado fluido.

3. **`add_text(text, x, y, font_size, color, font_family, font_weight, text_anchor, letter_spacing, filter_url)`**:
   - Tipografia vetorial escalável independente de resolução.

4. **Filtros e Efeitos (`apply_effect`)**:
   - `add_glow_filter`: Efeito outer glow neon usando `feGaussianBlur` + `feFlood` + `feComposite` + `feMerge`.
   - `add_drop_shadow_filter`: Sombras suaves com controle de desvio, opacidade e dispersão via `feDropShadow`.
   - `add_linear_gradient` / `add_radial_gradient`: Preenchimentos metálicos e de iluminação volumétrica.

## Resoluções e Canvas
- **Feed / Carrossel**: 1080 × 1350 (proporção vertical 4:5 de máxima ocupação de tela no feed).
- **Reels / Stories**: 1080 × 1920 (proporção vertical 9:16 de tela cheia).
- **Post Quadrado**: 1080 × 1080 (proporção 1:1).
- **Badges / Stickers**: 500 × 140 ou 600 × 180.
