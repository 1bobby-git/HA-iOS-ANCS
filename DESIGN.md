# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-08-05
- Primary product surfaces: ESP32-C6 captive setup portal at `http://192.168.4.1`
- Evidence reviewed:
  - `components/portal_http/portal.html`
  - `components/portal_http/portal.css`
  - `components/portal_http/portal.js`
  - `README.md`
  - `docs/index.html`

## Brand
- Personality: Calm, dependable, practical, and appliance-like.
- Trust signals: Plain-language status, explicit save/test feedback, local-only setup notice, and confirmation gates for destructive actions.
- Avoid: Raw JSON, developer jargon in the primary flow, dense two-column label/input grids, ornamental gradients, and external web assets.

## Product goals
- Goals:
  - Let a non-expert connect Wi-Fi and MQTT without knowing device-specific identifiers.
  - Make Wi-Fi, MQTT, and iPhone/BLE readiness understandable at a glance.
  - Keep enrollment and recovery available without exposing dangerous actions in the primary flow.
- Non-goals:
  - General-purpose MQTT administration.
  - Home Assistant automation editing.
  - Historical notification browsing.
- Success signals:
  - Recommended Client ID and Base topic are populated automatically and remain editable.
  - The primary configuration can be completed in one form on phone or desktop.
  - Wi-Fi scan, save/connect, MQTT test, enrollment, restart, replacement, and reset remain available.

## Personas and jobs
- Primary personas: Device owner configuring the ESP32-C6 from an iPhone or Windows PC.
- User jobs:
  - Select a nearby Wi-Fi network and enter its password.
  - Enter only the MQTT broker details they know.
  - Confirm that Wi-Fi, MQTT, and iPhone notification capture are ready.
  - Enroll or intentionally replace an iPhone.
- Key contexts of use: Captive portal over the device AP, often on a narrow phone screen, with no internet access.

## Information architecture
- Primary navigation: Single vertically scrolling setup screen; no multi-page navigation.
- Core routes/screens:
  - Readiness summary
  - Network and MQTT setup
  - iPhone connection
  - Collapsed device management
- Content hierarchy:
  1. Device identity and live readiness
  2. Wi-Fi selection
  3. MQTT broker essentials
  4. Optional advanced MQTT settings
  5. Save/test actions
  6. BLE enrollment
  7. Dangerous maintenance

## Design principles
- Principle 1: Reveal complexity progressively. Client ID, Base topic, TLS, and CA belong in an advanced disclosure with safe defaults.
- Principle 2: Describe outcomes, not implementation. Use “iPhone connected” and “Broker connected” instead of raw booleans or JSON.
- Tradeoffs: Keep the portal dependency-free and compact even if that limits elaborate animation or rich charts.

## Visual language
- Color: Warm neutral page, white surfaces, deep navy text, blue primary action, teal success, amber attention, and red danger.
- Typography: Native system sans-serif; 16 px minimum form text to avoid mobile zoom; compact monospaced text only for machine identifiers.
- Spacing/layout rhythm: 4/8 px rhythm, 20-24 px card padding, and a centered content column no wider than 840 px.
- Shape/radius/elevation: 12-18 px cards, 10-12 px controls, hairline borders, and one restrained shadow level.
- Motion: Short opacity/transform feedback only; no motion required to understand state.
- Imagery/iconography: Inline CSS shapes or text indicators only; no external icon or image dependency.

## Components
- Existing components to reuse: Embedded HTML, CSS, JavaScript assets and existing HTTP endpoints.
- New/changed components:
  - Header identity block with AP/device name
  - Four readiness status tiles
  - Unified setup form with Wi-Fi and MQTT sections
  - Advanced MQTT disclosure
  - BLE enrollment card
  - Collapsed device-management disclosure
- Variants and states: Neutral, ready/success, pending/attention, unavailable/error, disabled/busy, and destructive.
- Token/component ownership: `components/portal_http/portal.css` owns visual tokens and component styling.

## Accessibility
- Target standard: WCAG 2.1 AA where feasible in the embedded portal.
- Keyboard/focus behavior: Logical DOM order, native controls, visible `:focus-visible` ring, and no hover-only actions.
- Contrast/readability: Text and interactive colors target AA contrast; helper text stays at readable size.
- Screen-reader semantics: Explicit labels, headings, `aria-live` status feedback, `aria-busy` during requests, and semantic `details/summary`.
- Reduced motion and sensory considerations: Respect `prefers-reduced-motion`; never encode status by color alone.

## Responsive behavior
- Supported breakpoints/devices: 320 px mobile through desktop browsers.
- Layout adaptations: One column by default; two-column field rows only above 680 px; status tiles wrap from two columns to four.
- Touch/hover differences: Minimum 44 px targets, generous spacing, and hover effects only as optional enhancement.

## Interaction states
- Loading: Buttons show concise working copy and become temporarily disabled.
- Empty: Wi-Fi selector explains that a scan is required; recommended MQTT identifiers are still populated.
- Error: Persistent inline message with the returned reason; existing values remain intact.
- Success: Inline confirmation and refreshed readiness tiles.
- Disabled: Reduced contrast plus disabled cursor; never rely on opacity alone.
- Offline/slow network, if applicable: Keep current form contents and show a retryable local-device error.

## Content voice
- Tone: Direct, reassuring Korean with familiar technical names preserved where necessary.
- Terminology: “Wi-Fi”, “MQTT 브로커”, “Client ID”, “Base topic”, “iPhone 연결”.
- Microcopy rules: Explain why a field is needed, label generated values as “권장값”, and state that blank secret fields preserve existing secrets.

## Implementation constraints
- Framework/styling system: Plain embedded HTML/CSS/JavaScript; no runtime framework.
- Design-token constraints: Use CSS custom properties in `portal.css`; do not add a second theme layer.
- Performance constraints: No external assets, CDN, web fonts, or large libraries; assets are compiled into ESP32-C6 firmware.
- Compatibility constraints: Current iOS captive browser and modern Windows browsers; keep existing element IDs and API contracts where practical.
- Test/screenshot expectations: Static portal contract tests, JavaScript behavior test for recommended values, firmware build, flash to COM9, and real portal/API smoke verification through DAISO.

## Open questions
- [ ] Confirm whether a future release should allow custom Home Assistant discovery prefixes / owner / low impact.
