# Bike Box roadmap (prioritised)

Reset 2026-10-13 after the v0.1.x feature run. Ordered by priority: **P0** = do
next (correctness, trust, core safety gaps), **P1** = high-value features, **P2**
= bigger/later. Each line says *why*. `(partial)` = some support exists.

## P0 — correctness & trust (do next)
- [x] **Validated the core math** (tests/test_validation.py): geometry identities (wheelbase, front centre,
  BB drop, seat-tube, standard trail formula), BikeCAD round-trip across all 24 front-end/seat modes, and the
  mitre cope engine proven exact (cut points lie on the receiver surface; plane-cut depth = od/tan θ).
- [ ] **Code-sign & notarise the apps** — PINNED: needs paid certs (Apple Developer US$99/yr + a Windows
  code-signing cert). CI scaffolding was written and then reverted to avoid dead config; re-add when certs exist.
- [x] **Live clearance badges** — a 'Clearances' toolbar toggle draws red/amber gap markers with values at each
  tight/failing clearance, live as you edit (uses the validated clearance data).
- [ ] **Disc caliper/rotor clearance geometry** — deferred: needs the hub rotor-offset + caliper mount geometry
  the model doesn't yet capture; an approximate check would risk false warnings (against the trust goal).

## P1 — high-value features
- [x] **STEP/IGES export** — the top "pro" interchange ask (CAD, CNC, FEA). Each tube exports as a faceted B-rep
  **solid** (STEP AP214 `manifold_solid_brep`; IGES 5.3 MSBO type 186) from the same tessellation the 3-D view
  and STL use. Evaluated the kernel route (OpenCASCADE/cadquery) and rejected it: a few-hundred-MB dependency
  would bloat every installer, so the writers are hand-rolled and validated by re-parsing their own output back
  into closed, orientable manifolds (Euler V−E+F=2, every edge shared by exactly two faces) matching the source.
  Tubes are the outer envelope and **un-mitred** — they run full centre-to-centre length and interpenetrate at
  joints, ready to be coped in CAD. (A true analytic-surface / mitred-solid export would need a kernel.)
- [x] **Shop CNC outputs** — tube-notcher setup (hole-saw Ø, notch angle, offset, rotation, long/short points)
  and tube-bender specs (radius, included angle, arc length) in the build sheet + `cnc` CSV export. Flat-pattern
  dropout/gusset DXF still open (needs plate outlines the model doesn't carry).
- [x] **Fit-to-rider auto-size** — the size run now recommends the best size for the current rider (matches the
  fit scheme's target stack/reach + standover feasibility).
- [x] **Aero / CdA estimate** — first-order drag area from rider anatomy (Du Bois BSA) and position
  (saddle-to-bar drop), with steady-state power at a chosen speed (air drag + rolling + drivetrain), in the
  analysis report. Clearly labelled an estimate — real CdA must be measured.
- [x] **Customer / order management** — a design carries a customer + order (status, due, pricing); a quote is
  built from the BOM + labour + frame price and exports as PDF; orders are logged per user. (Catalog has no
  prices, so line prices are the shop's own.)
- [x] **Cable / hose routing** — add internal/external routes (presets for shift/brake/dropper/Di2/dynamo);
  drawn on the frame with entry/exit ports listed on the build sheet.
- [x] **CSV import of a shop's own stock + prices** (Parts libraries ▸ Import stock CSV) — imported prices feed
  the quote. Remaining tube gaps (Reynolds matrix, True Temper OX Gold, KVA MS2) and lugs/fork-crown geometry
  still open (need web-sourced data).

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
