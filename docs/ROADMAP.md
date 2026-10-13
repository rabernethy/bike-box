# Bike Box roadmap (prioritised)

Reset 2026-10-13 after the v0.1.x feature run. Ordered by priority: **P0** = do
next (correctness, trust, core safety gaps), **P1** = high-value features, **P2**
= bigger/later. Each line says *why*. `(partial)` = some support exists.

## P0 — correctness & trust (do next)
- [x] **Validated the core math** (tests/test_validation.py): geometry identities (wheelbase, front centre,
  BB drop, seat-tube, standard trail formula), BikeCAD round-trip across all 24 front-end/seat modes, and the
  mitre cope engine proven exact (cut points lie on the receiver surface; plane-cut depth = od/tan θ).
- [ ] **Code-sign & notarise the apps** — macOS Gatekeeper and Windows SmartScreen both warn on the current
  unsigned installers, which blocks real adoption. Needs an Apple Developer ID + a Windows cert from the owner;
  I can wire the CI once certs exist.
- [x] **Live clearance badges** — a 'Clearances' toolbar toggle draws red/amber gap markers with values at each
  tight/failing clearance, live as you edit (uses the validated clearance data).
- [ ] **Disc caliper/rotor clearance geometry** — deferred: needs the hub rotor-offset + caliper mount geometry
  the model doesn't yet capture; an approximate check would risk false warnings (against the trust goal).

## P1 — high-value features
- [ ] **STEP/IGES export** — the top "pro" interchange ask (CAD, CNC, FEA). Needs a solid-modelling dependency
  (OpenCASCADE/cadquery) — evaluate bundle-size vs value before committing.
- [x] **Shop CNC outputs** — tube-notcher setup (hole-saw Ø, notch angle, offset, rotation, long/short points)
  and tube-bender specs (radius, included angle, arc length) in the build sheet + `cnc` CSV export. Flat-pattern
  dropout/gusset DXF still open (needs plate outlines the model doesn't carry).
- [x] **Fit-to-rider auto-size** — the size run now recommends the best size for the current rider (matches the
  fit scheme's target stack/reach + standover feasibility). Aero/CdA estimate still open.
- [ ] **Customer / order management** — link a design to a customer, a build spec and a quote from the BOM; track
  jobs. (The owner has related sessions, so this is a real workflow need.)
- [ ] **Cable / hose / Di2 routing** — internal/external paths and port/stop placement, exported with the frame.
- [ ] **Catalog depth** — fill remaining tube gaps (Reynolds matrix, True Temper OX Gold, KVA MS2), add
  lugs/fork-crown geometry and headset/BB-standard matrices; CSV import of a shop's own stock + prices.

## P2 — bigger / later
- [ ] **Full suspension** — pivot locations, shock, leverage curve, anti-squat; opens the MTB market.
- [ ] **FEA upgrade** — real load cases (pedalling/braking/impact/fatigue), stress plots on the 3-D model,
  stiffness (BB/head-tube/torsional).
- [ ] **Project history & sharing** — named revisions with diffs, a shareable read-only link / web viewer.
- [ ] **3-D polish** — shaded materials & paint, section cut-planes, exploded view, turntable/GIF export,
  measurement in 3-D.
- [ ] **UI polish** — keyboard-shortcut editor, multi-select + numeric nudge, guide/grid snapping, theme/DPI.
- [ ] **More frame types** — recumbents, cargo/longtail, folders, S&S coupler placement optimiser.

## Ongoing quality
- [ ] Performance: cache solves across panels; profile large catalogs; trim the ~200 MB bundle.
- [ ] Test coverage: a real-GL smoke test in CI (currently import-level only); BikeCAD round-trip fixtures.
- [ ] Docs & presence: screenshots, a short website/README gallery, example designs.

## Done (v0.1.0 – v0.1.7)
- Parametric geometry + solver; tandem, tall-bike, mixte/step-through; extra tubes (paint, in-phase), junction
  drag, head-tube stick-out; lossless measurement-mode switching.
- Clearances in 3-D; "Resolve issues" options engine; interactive **3-D clearance view** (orbit, live, pass/fail
  gap lines); oval/aero tubes with true elliptical sections; minimum standover.
- Parts catalog (17 categories, ~5,600 sourced items) with in-context pickers, per-tube selection, bill of
  materials **with weights**; tube + dropout catalog expanded from manufacturer/CAD data.
- Compatibility checker (seatpost, thru-axle, belt break, derailleur capacity, disc mount/rotor, chainline,
  wheel sizes); maximum-tire-size; stack/reach fit-target.
- Fit advisor with literature schemes (road/endurance/gravel-touring/MTB/**track**/TT/Holmes) + **rider database**.
- Size-run generator; build/cut sheet PDF; **full-size 1:1 tiled template**; headless `bom`/`buildsheet`/`sizes`.
- Drawing/SVG/DXF/PNG, STL, FreeCAD macro, CSV, GIF morph, mitre templates.
- BikeCAD `.bcad` import **and** export; renamed to Bike Box (GPL-3.0); Win/mac/Linux installers via CI (v7
  actions); 3-D view bundles and runs on all three platforms.
