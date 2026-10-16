# JEV Mark Workspace v2 — Design QA

## Target

Latest approved Concept 5 / Concept 4 direction:

- Scenario Workspace as the primary Workbench surface.
- Active JEV provider/model shown as first-class context.
- Evidence, decision schema, guardrails and run controls organised as a minimal document-style workspace.
- Structured result inspector with model and run context.
- Model Evaluation view derived from saved multi-provider scenario runs.

Reference viewport: desktop, approximately 1440 × 1024.

## Implemented checks

| Area | Result | Notes |
| --- | --- | --- |
| Persistent product shell | Passed in fixture | Sidebar, scenario library, model status and workspace remain visible without nested application cards. |
| Existing Workbench behaviour | Passed by inspection | Existing element IDs and event handlers remain in place; the enhancement rearranges the current DOM rather than replacing request logic. |
| Scenario hierarchy | Passed in fixture | Evidence / Request, Decision Schema, Guardrails / Policy and Run are shown as four document sections. |
| Real JEV primitives | Passed in fixture | Choice, Score, Noul and Parallel controls remain available; parallel JSON is progressively disclosed. |
| Active provider context | Passed in fixture | Provider name and gateway state are mirrored from the current `/health`-driven Workbench controls. |
| Result inspector | Passed in fixture | Existing structured result, workflow outcome, field results, references and raw response remain available. |
| Recent model runs | Passed in fixture | Saved comparison runs are shown using the existing local-storage report data. |
| Model Evaluation | Passed in fixture | Acceptable outcomes, model count, scenario count, median duration and the existing field-by-field report are presented together. |
| Logic Lab route | Passed in fixture | Navigation delegates to the existing Logic Grid control. |
| Service Analytics route | Passed by inspection | Navigation uses the existing `/analytics` page; its palette is aligned with the new shell. |
| JavaScript syntax | Passed | `node --check Resources/Web/analytics-portal.js` equivalent passed on the committed source. |
| Browser execution | Passed in fixture | Chromium/Playwright loaded the representative Workbench and Compare states with no page JavaScript errors. |
| Responsive fallback | Passed by inspection | Below 900 px the scenario library collapses, the workspace becomes one column and the result panel moves below the editor. |

## Remaining verification

The connected JEV service Mac was offline during this pass. The following still require the real installed application and gateway:

1. Load the full `/examples` catalogue and switch repeatedly between Choice, Score, Noul and large Parallel cases.
2. Run real requests through local Ollama, Apple Foundation Models, CLM and a TypeSafe profile.
3. Confirm provider status changes and remote-provider warnings update correctly.
4. Exercise partial failures in the 100-question run and verify successful fields remain visible.
5. Verify the full Radioactive Run controls and live board behaviour after the shell rearrangement.
6. Verify Service Analytics against the real protected analytics API.
7. Complete macOS, landscape and narrow-width visual checks using the installed menu-bar application.

## Known polish items

- The existing report toolbar buttons still use the legacy control styling in the representative fixture; the installed app's base styles should reduce this, but it needs visual confirmation.
- The Models navigation item is intentionally informational in this pass because provider selection is still owned by the menu-bar service.
- Model-evaluation charts currently use saved browser runs; durable cross-session evaluation storage is outside this UI-only pass.

**final result: blocked**

Blocker: live visual and interaction verification requires the connected Mac and running JEV gateway.
