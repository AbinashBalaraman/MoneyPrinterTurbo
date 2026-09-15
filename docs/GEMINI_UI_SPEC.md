# Gemini UI parity spec — AutoShorts / FlowKit dashboard

**Date:** 2026-09-15 · **Task:** task_0001 · **Author:** gemini-ui-spec
**Status:** visual direction FROZEN by four owner decisions (see §0.1).
**Scope:** the whole app, not only the chat route. One shared shell + per-page
content rules — explicitly *not* six independent skins.

**Read-only guarantee:** no file under `flowkit/dashboard/src` was modified to
produce this document. The only files written are this doc and two throwaway
calculators under `.tmp/` (`contrast_calc.py`, `contrast_pairs2.py`). The Vite
dev server and the FastAPI agent were not started.

---

## §0 Provenance — what is measured, what is not, and why

### §0.1 The reference screenshot is not reachable from this session — read this first

The brief for this task requires every measurement to be *derived from the
reference screenshot* rather than guessed, and requires each number to be
stated both as raw px on that screenshot and as its value at a 1440x900 target
viewport.

**I could not do the first half, and I am flagging it rather than papering over
it.** The attached Gemini screenshot was delivered into the lead session's
conversation. It is not present anywhere on this machine that I can read, and I
have no vision access to it. I did not assume that — I searched:

| Location searched | Result |
|---|---|
| `docs/` | `api.jpg`, `webui.jpg`, `webui-en.jpg` (the retired Streamlit `webui/` per `docs/ARCHITECTURE.md:159`), `ARCHITECTURE.md`, `CHAT_UI_REVIEW.md`, `IMPLEMENTATION.md`, `MoneyPrinterTurbo.ipynb`, `voice-list.txt`. **No Gemini capture.** |
| `%TEMP%` (5 images, all inspected) | `{97AB2857-…}.png` 306x306 = a generic blue "i" info glyph. `screen.png`, `screen2.png`, `screen3.png` 1366x768 = the same Edge/Codex terminal desktop session from 2026-09-08 (`screen2.png` is a blank `google.com` tab). `stragy-audit-landing.png`. **None is Gemini.** |
| `.workbuddy-ai/` | Contains only `memory/` (`MEMORY.md`, four daily notes). No images. |

So I verified 5 images individually rather than asserting "it isn't there".

Consequence for this document: **zero geometry rows below are pipette-measured
from the reference.** Every number carries an explicit provenance label, and
§0.4 gives a one-pass protocol that converts the whole table from *derived* to
*measured* in minutes.

This is the top risk to "visually indistinguishable" (§8, R1). It is not
recoverable by effort inside this task — it needs the image or its numbers.

### §0.2 Provenance legend used throughout

| Label | Meaning | Trust |
|---|---|---|
| `[CODE]` | Verified by reading a file in this repo. `file:line` always given. Arithmetic on Tailwind v4's scale (1 unit = 0.25rem = 4px) is shown so it can be re-checked. | High |
| `[CANVAS]` | Arithmetic on the brief-supplied canvas of 1363x604 CSS px. The arithmetic is written out. | Medium — depends on the canvas figure being right |
| `[M3-DOC]` | A documented Google Material 3 / Gemini web value. **Not** verified against the screenshot and **not** verified against a fetched primary source: `m3.material.io/styles/color/roles` and `gemini.google.com` both returned JavaScript shells with no hex values, and a DuckDuckGo HTML search returned a bot challenge. | Low — treat as a candidate |
| `[TARGET-SPEC]` | A deliberate design decision made in this spec, because parity and usability conflict. Outranked by `[CODE]`/measurements when they disagree. | Decision |
| `[INFER]` | My inference. Needs confirmation; listed in §7. | Low |

I am not aware of any row below that would deserve a "measured" label.

### §0.3 The reference screenshot is a BROKEN RENDER — do not copy its sidebar layout

The brief states the reference viewport is ~1363x604 CSS px and that its sidebar
labels are vertically clipped/overlapping. That is not a stylistic choice; it is
the predictable consequence of a fixed-height rail that does not fit. The
arithmetic, using Gemini-class rail metrics `[M3-DOC]`:

```
  available rail height at the reference viewport .............. 604 px
  brand row        (py-4 + 22px mark + 1px divider)  = 16+16+22+1 =  55 px
  pre-nav rows     (segmented toggle 32 + 3 rows of 40) = 32+120  = 152 px
  "Notebooks" grp  (1 header 28 + 3 rows of 40)      =  28+120   = 148 px
  "Recents" group  (1 header 28 + 4 rows of 40)      =  28+160   = 188 px
  user footer      (py-3.5 + 32px row + 1px divider) = 14+14+32+1 =  61 px
                                                       TOTAL      = 704 px
  overflow vs the 604 px viewport .................................. 100 px
```

100 px of content with nowhere to go inside a `flex-col` that cannot shrink is
what "clipped/overlapping labels" looks like. **The reference is a cramped
browser window, so its sidebar is an accident of that window size, not intent.**

Two rules follow, and they are requirements, not preferences:

1. **The rail's row group must scroll independently** (`overflow-y:auto`, plus
   `min-height:0` on the flex child so it can actually shrink). Brand row and
   user footer stay pinned. At 604 px the rail scrolls; at 900 px it does not.
2. **Never copy a row height or padding from the reference's compressed rows.**
   The reference's rows are compressed by the overflow. Take row metrics from
   §1.2, not from the screenshot.

For AutoShorts this is worse, not better: the agreed rail has **more rows than
Gemini's** (§0.6 item 2), so it overflows at *every* realistic viewport except a
tall one. Scroll is mandatory, not defensive.

### §0.4 Measurement protocol — the one pass that makes this table measured

Run this once against the reference image at its native 1363x604 and record the
values into §1's `measured?` column. Every number in §1 is a placeholder for
exactly one of these readings.

```
  R1  sidebar/rail right edge x            (the divider hairline)
  R2  collapsed-rail right edge x          (if the reference shows collapsed state)
  R3  y of the first nav row's text baseline, and y of the second
      -> row height = difference
  R4  y of a section-header text baseline vs the row above -> header height
  R5  composer: left x, right x, top y, bottom y
      -> max-width = right-left; height = bottom-top
  R6  composer corner radius: the corner arc's horizontal extent, read at the
      vertical midpoint of the composer's left edge
  R7  hero heading cap-height in px and its y -> derive font-size (cap height is
      ~0.70em in Google Sans and ~0.70em in Geist, so this survives the swap)
  R8  main-area top-right icon: right edge inset from viewport right, top inset
  R9  icon glyph bounding box inside a nav row -> icon size
  R10 icon's rightmost pixel to the label's first pixel -> icon-text gap
  R11 pipette: page background, rail background, hovered row, selected row,
      divider, primary text, secondary text, placeholder, accent glyph
  R12 main area's left gutter (rail edge -> hero text's left extent)
```

Two readings to take with care, because they are the ones most often got wrong:

- **R6, the composer radius.** Read the arc's horizontal extent at the vertical
  midpoint, not at the top edge, or a 28 px radius reads as ~20 px.
- **R11, the background.** Pipette a large flat region, never a single pixel —
  compression noise moves hex values by 2-4 units on flat greys.