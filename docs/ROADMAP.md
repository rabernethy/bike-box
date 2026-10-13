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
- [~] **More frame types** — added **balance / baby bike** (small-wheel single with the drivetrain removed:
  no chainrings, cranks, chain, or their clearances/gearing), **cargo longtail** (an extended rear deck:
  top + lower rails, tail upright and brace, mirrored), and **folder** (a single frame with a folding-hinge
  marker on the down tube). Still open: **recumbents** and **front-loader cargo (long-john/bakfiets)** — these
  need a dedicated non-diamond skeleton (forward BB boom / seat, or a second steering axis + linkage); the
  diamond solver can't represent them without inventing geometry, so they warrant their own build. **S&S
  coupler placement optimiser** also still open.
- [x] **Travel couplings** — frame couplers now have a style: **S&S** (torque couplers on the top and down
  tube, positions adjustable) and **Ritchey Break-Away** (a down-tube coupler just above the BB and a clamp
  joint at the top-tube/seat-cluster). Both show the cut points and a travel-case-fit check (front/rear half
  spans vs the case diagonal) in the report. An auto-placement *optimiser* is still open.

## Ongoing quality
- [~] Performance: profiled the interactive paths (2026-10-13). solve() ~0.3 ms and FEA ~4 ms are already fast;
  the real lag was the parts catalog -- `all_items()` rebuilt and re-copied all ~5.9k items (and re-read the user
  library from disk) on **every** call, so each picker keystroke paid a full rebuild. Now cached + indexed
  (invalidated by the built-in cache or a user-library file change): `items()` 143 ms -> 0.25 ms, `search()`
  65 ms -> 2 ms per keystroke. 3-D libs already import lazily.
- [~] Analysis across panels (2026-10-13): the geometry solve was already cached on the document, but the
  analysis report was not -- and profiling found the **Tire fit** builder was ~700 ms because its max-tire search
  recomputed *all* clearances (including the expensive heel/toe/crank sampling) on each of ~40 probes and threw
  most away. Added a `keys` filter to `clearance_details` so tire-fit computes only the tire/fork contacts, cut
  the binary search to 11 iters (finer than the 0.1 mm it reports), and memoised `full_report`/`analyse` on the
  geometry so all panels/tabs/dialogs share one build. Full report 700 ms -> ~108 ms, recomputed once per edit
  rather than once per consumer.
- [x] Installer size (2026-10-13): module excludes alone don't help (PyInstaller's Qt hook bundles the Qt6
  runtime wholesale), so inspected the real CI artifact (253 MB uncompressed, 105 MB of it PyQt6) and pruned the
  parts the app never loads -- Qt UI translations (~7 MB), the Qt PDF viewer lib (~4 MB; objdump-confirmed
  nothing we ship links it) and the SQL/QML plugins. Download sizes: Linux 96->91, macOS 44->37, Windows
  portable 56->52 MB. The rest (Qt Core/Gui/Widgets, Python, numpy BLAS/LAPACK, Qt ICU data) is all required.
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
