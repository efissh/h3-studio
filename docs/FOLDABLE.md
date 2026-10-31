# Foldable and responsive layout

The H3 Studio interface reflows using CSS viewport width (no device-name/UA sniffing).
At <600 CSS px the existing compact folded-phone layout is unchanged.
At 600-839 CSS px, the inner screen uses the full available width, with two
model cards and three parameter fields per row in the existing stacked form.
At 840-1350 CSS px, the two real creation cards sit side-by-side (models/compute
at left, generation controls at right). Large portrait viewports and coarse
pointer devices above 1350px get the same expanded layout. No new preview,
phantom jobs, or unauthenticated API paths are added.

Acceptance: in Chrome on the unfolded phone, check portrait and landscape at
roughly 600, 720, 840, 1024 and 1200 CSS px; check that no horizontal page scroll
appears, hardware metrics are horizontally swipeable, model cards remain readable,
and the Generate, Image-to-Video, A/B, job history, theme and Install controls work.
Check 390 CSS px folded mode and desktop 1440x900 to ensure no regressions.
Do not run GPU generation tests just to verify layout.

## Second-pass portrait refinement

A real unfolded-screen screenshot showed that applying a two-column workspace
to a portrait / near-square display made labels and controls too small and left
a large empty region below both cards. This revision prioritizes readability
instead of forcing two columns on every wide device:

- Unfolded **portrait** (600–1350 CSS px; also larger coarse-pointer screens):
  one full-width creation workflow with the two model choices side by side,
  parameters in three equal columns, and larger prompts/touch targets.
- Unfolded **landscape** (840–1350 CSS px, plus larger coarse-pointer screens):
  retain two-column creation workflow but increase card and control typography.
- The narrow folded phone (<600 CSS px) retains its compact layout.
- Wide desktop landscape and all APIs/model settings remain unchanged.

Test with the actual folded/unfolded device in both orientations; report
`window.innerWidth`, `window.innerHeight`, `devicePixelRatio`,
and `document.documentElement.scrollWidth` against `clientWidth`.
Do not infer CSS viewport width from raw screenshot pixel dimensions.

## "Desktop site" / zoomed-out detection hint

If a touch browser renders the page wider than the screen, every CSS pixel is shrunk and the layout looks tiny no matter
how it is styled. Chrome's **Desktop site** mode does this on purpose: it ignores `<meta name="viewport">` and lays the page
out at roughly 980–1280 px. The page now detects this and shows a dismissible hint above the navigation.

- Check (`scaleCheck`, a pure function): `layoutScale = screenSide / innerWidth`, where `screenSide` is the screen side that is
  horizontal in the current orientation (iOS keeps `screen.width` fixed; toolbars only shrink `innerHeight`).
  `layoutScale < 0.87` -> cause `desktop-site`; otherwise `visualViewport.scale < 0.87` -> cause `zoomed-out`.
- Only on touch-first devices (`pointer:coarse`), so a desktop window spanning monitors can never trigger it.
- The hint states the measured numbers (`innerWidth`, `innerHeight`, `screen`, `DPR`, zoom) and how to switch Desktop site off.
  "知道了" hides it for the rest of the browser session (`sessionStorage`); no server call, no new persistent storage.
- Re-evaluated after login and on `resize`, `orientationchange` and visual-viewport zoom (debounced).
- Diagnose on the device: open the page, then in the console run
  `__h3ScaleCheck({innerW:innerWidth,innerH:innerHeight,screenW:screen.width,screenH:screen.height,vvScale:visualViewport.scale})`.
- Tests: `tests/test_scale_hint.py` (static contract; with `node` it also executes the 10 decision cases). The same 10 cases were run in a browser.
