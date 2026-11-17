# Ticket: Menu bar decision overlays, usage pulse, and Ollama selection sync

- **Date**: 2026-11-04
- **Branch**: `codex/proxy-batching`
- **Status**: implemented and verified locally; committed with this ticket

## Summary

Reworks the JEV Menu Bar popover into a compact decision surface: a 12-hour
usage pulse built on the analytics store, inline text-and-chevron triggers that
open anchored overlay popovers (backend selector, Ollama Decision Models, Logs),
a single Start Services / Shut Down Services toggle, and a stale-selection prune
in the Ollama System One profile store. Includes a session retrospective with
environment improvement proposals.

## Changes

### Usage pulse

- New `Sources/JevMenuBar/UsageHistory.swift`: read-only SQLite reader over the
  analytics database (`requests.started_at`), bucketing the last 12 hours into
  72 ten-minute slots; `UsagePulseView` draws bars over the divider's baseline
  with hour ticks (labels every fourth hour, 24-hour format) and a request
  count caption. Refreshes every 2 minutes in the background; degrades to a
  flat baseline with "usage history unavailable" when the store is missing.

### Header

- Removed the "Routes to" caption, the header Start button, and the
  Test-selected-provider button row.
- Backend lines: family label (grey) with provider, model name with an inline
  chevron selector, `Test` link only while configured, port link right-justified.
- Error and test-failure messages render below the model line in orange; simple
  states keep the small grey label; the status dot is top-aligned with the title.

### Backend selector

- The model name plus accent chevron toggles a transient popover listing the
  same sections as the former dropdown (Local Ollama, On-device Apple,
  Contrastive (CLM), System One API) with a checkmark on the selection.

### Ollama Decision Models panel

- The DisclosureGroup became an anchored overlay popover (420×440) titled
  "Ollama Decision Models" with Model / Batch / Image Input columns.
- Batch values are always visible; selected models get an editable field with
  stepper, unselected models show the stored number.
- Image Input cells are read-only bordered boxes; the tick marks a selected
  model that Ollama reports as image-capable. The manual image-input toggle is
  gone from the UI.
- Refresh moved into the panel (lower left); the batch guidance
  "Batch range: 1 - 512 | Ollama default: 64" is right-aligned beside it.

### Logs selector

- Auths, Gateway log and Model log links consolidated into one "Logs" chevron
  trigger centered between "Start at login" and the services toggle; selecting
  an entry opens it as before.

### Services toggle

- One bottom-row link toggles Start Services ↔ Shut Down Services. Remote
  backends report `configured` while serving, so both `running` and
  `configured` count as up.

### Ollama selection sync

- `OllamaSystemOneStore.pruneUnavailableModels` runs on every provider refresh
  and removes System One rows whose model is no longer downloaded. This fixes
  leaked profiles (for example `Ollama · clef-flash:9b` after its model was
  uninstalled) that previously survived because rows were only removed by
  explicitly unchecking a model.
- Checkbox toggles no longer run the heavy Ollama CLI discovery; they sync the
  gateway profile list with a lightweight HTTP reload instead, removing the
  1–2 second control freeze after every toggle. The panel's Refresh button
  still performs the full discovery pass.

## Retro (yiddiy improve retro)

### What was learnt

- **SwiftUI `Group` trap**: modifiers on a conditional `Group` apply to its
  children; with the condition unmet the group has no children and frames,
  overlays and borders silently vanish. Cells are now built as `ZStack`s with
  always-present shapes.
- **`Menu` is unstyleable inside `MenuBarExtra`**: the borderless style still
  forces its own leading arrow regardless of `menuIndicator(.hidden)`.
  Deterministic triggers use plain buttons plus manually popped `NSMenu`s or
  anchored `NSPopover`s.
- **Popover lifecycle**: `.task`/`onAppear` do not reliably re-fire when a
  `MenuBarExtra` window reopens (macOS 13), so continuously-current data needs
  its own background cadence.
- **Offscreen verification works**: compiling real reader code against the live
  SQLite store (ASCII render) and an `ImageRenderer` harness for SwiftUI layout
  caught data and layout issues without screenshots; screenshot automation of
  the menu bar popover from a full-screen Space did not.

### Improvement proposals (not implemented in this ticket)

1. **Swift guardrail gap (high)**: CI runs only Python/JS checks on Ubuntu, its
   PR trigger paths exclude `Sources/**`, and the Ollama store check is a
   manual `swiftc` invocation. Add a macOS job running `swift build` plus the
   compiled store checks and include `Sources/**` in PR paths.
2. **SwiftUI gotcha standards (medium)**: record the `Group`-modifier trap, the
   `Menu` chrome limitation, and the popover lifecycle in a small
   `CODING_STANDARDS.md` with a pointer to a menu-bar UI notes document.
3. **Render harness (medium)**: promote the offscreen `ImageRenderer` and
   ASCII-render techniques into a repeatable script so popover layout verifies
   before install.
4. **Navigation (low)**: `main.swift` still carries most views; overlay panels
   could split into files the way `UsageHistory.swift` did.
5. **Tool economy (low)**: fold the post-install health check into
   `scripts/install_menubar.sh` as a flag.

### Tracking

Proposals are tracked on GitHub under epic
[Holovkat/jev-mark#20](https://github.com/Holovkat/jev-mark/issues/20):
#15 (CI guardrail), #16 (coding standards), #17 (render harness),
#18 (view split), #19 (install health flag).

## Verification

- `swift build` and the release build (via `scripts/install_menubar.sh`) pass.
- Ollama store checks compile and pass, including new prune coverage:
  ```sh
  swiftc Sources/JevMenuBar/TypesafeAPI.swift tests/ollama_store.swift -o /tmp/jev-ollama-store-tests
  /tmp/jev-ollama-store-tests
  ```
- Live gateway checks after reinstall: `/health` reports `ok` on the selected
  backend, and `/providers` lists exactly the still-downloadable Ollama
  selection (`Ollama · d1:3b`) with the stale `Ollama · clef-flash:9b` profile
  pruned.
- 12-hour request totals from the new reader match a direct SQL count of the
  analytics store.
- Known limit: menu-bar popover visuals were verified offscreen (ImageRenderer)
  and by operator screenshots; native UI automation remains unreliable from a
  full-screen Space.

## Files

- `Sources/JevMenuBar/UsageHistory.swift` (new)
- `Sources/JevMenuBar/main.swift`
- `Sources/JevMenuBar/TypesafeAPI.swift`
- `tests/ollama_store.swift`
- `docs/multimodal.md`, `docs/service-analytics.md`, `docs/README.md`
- `docs/tickets/2026-11-04-menubar-decision-overlays.md` (this ticket)
