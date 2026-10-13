# Bike Box roadmap

A living list of missing features and enhancements. Items marked **(partial)** have
some support already; **(bug)** are known defects. Tick items off as they land.

## Geometry & frame types
- [ ] Full-suspension (pivot locations, shock, leverage curve, anti-squat); softtail; URT
- [ ] Recumbents; cargo/longtail/bakfiets models; trikes/tadpoles; cargo-box front ends
- [ ] Folding hinges; S&S/coupler **placement** solver *(couplers exist; no optimizer)*
- [ ] Fat/plus auto-standards; expanded geometry preset library (beyond the 17 templates)
- [ ] Belt-drive splitter / eccentric BB / sliding-dropout tensioning geometry *(belt in gearing only)*
- [ ] Segmented/curved tubes with multiple bends; richer S-bend stays (beyond single sagitta)
- [ ] Integrated seatmast; sloping/horizontal TT auto-modes; twin-plate / monostay rear ends
- [ ] IGH / gearbox chainline + chainstay interaction
- [ ] Parametric linked constraints ("keep trail constant while…"); target-geometry solver
- [ ] (bug) Verify tall-bike/tandem edge cases in clearance paths and extra-tube attach on tall frames

## Fit & ergonomics
- [ ] Rider database (body measurements); fit-to-rider sizing from inseam/height/flexibility
- [ ] Pedaling dynamics, KOPS, saddle-setback optimizer, cleat/Q-factor fit
- [ ] Stack/reach fit-envelope overlay vs a target fit coordinate
- [ ] Position presets (TT/road/gravel/MTB); aero position + simple CdA estimate
- [ ] Standover at multiple points; step-through clearance for a given rider

## Components & drivetrain
- [x] Braze-on / mount **placement UI** (bottle bosses, cable stops, disc mount, rack/fender eyelets) — drawn + in the build sheet
- [ ] Full cable/hose/Di2 routing paths (internal/external); housing-stop/port placement
- [ ] Derailleur capacity, chain wrap, b-gap, max/min sprocket, crank-to-frame envelope
- [ ] Brake mount standards (IS/post/flat-mount) + rotor-size placement + caliper clearance
- [ ] Dropout/hanger database incl. UDH; thru-axle thread/length picker
- [ ] Dynamo/light/fender/rack load & mount modeling; kickstand plate placement
- [ ] E-bike motor mounts (mid-drive BB standards), battery fit, wiring

## Clearances & safety
- [ ] Crank-arm-to-chainstay 3D envelope through full rotation *(partial via cs_crank)*
- [ ] Toe-overlap with real shoe size + fender; heel-to-stay through the pedal stroke
- [ ] Tire-to-everything at max size + mud-clearance target; chainring-to-tire for 1x/2x
- [ ] Suspension travel-sweep clearance (fork + rear); bottom-out checks
- [ ] Standover/top-tube safety; min-insertion enforcement across sizes

## Structural / analysis
- [ ] FEA upgrade: tube FE with joints, load cases (pedaling/braking/impact/fatigue), stress on the 3D model
- [ ] Stiffness metrics (BB, head-tube, torsional); compliance; natural frequency
- [ ] Material comparison for a design; butting optimizer (weight vs stiffness)
- [ ] Ride-quality/flex indicators; wheel/tire compliance
- [x] Weight breakdown by part fed from the catalog BOM (BOM shows per-part weight + total)
- [ ] Carbon layup schedule for carbon tubes

## Catalog & data
- [ ] Fill tube gaps (Reynolds full matrix, True Temper OX Gold, KVA MS2, discontinued Dedacciai)
- [ ] Lugs / bi-lams / fork-crown catalog with geometry; BB-shell standards; headset matrix
- [ ] Live/online catalog updates; user-contributed catalog sharing; CSV import of a shop's stock
- [ ] Tube-in-stock inventory; price/weight per part; vendor part-number cross-reference
- [x] Component compatibility checker (seatpost fit, thru-axle, FD/rings, belt break, chainline, wheel sizes)

## Manufacturing / output
- [ ] Full-size 1:1 tiling for the whole frame *(mitre templates exist; whole-frame tiling missing)*
- [ ] Fixture/jig setup generator for specific jigs; tube blocks; mitre-fixture angles
- [ ] CNC/laser: flat-pattern dropouts, gusset DXF, tube-notch G-code *(gcode.py exists — verify coverage)*
- [ ] STEP/IGES export *(today STL + FreeCAD macro only)*
- [ ] Notcher miter report incl. hole-saw sizes *(partial in the cut list)*
- [ ] Tube-bender specs (radius, sweep, spring-back)
- [ ] Weld/braze order sheet; QC checklist; serial-number/decal placement sheet

## Visualization / UI
- [ ] Release the 3-D view; shaded materials/paint, section cut-planes, exploded view
- [ ] Real-time clearance readout while dragging; on-canvas clearance badges
- [ ] Turntable/animation export of the 3-D model; AR/web viewer
- [ ] 3-D measurement tool and annotations
- [ ] Theme polish, DPI scaling, keyboard-shortcut editor, customizable panels
- [ ] Multi-select + numeric nudge on canvas; guide/grid snapping; onion-skin editing
- [ ] Dedicated side-by-side size-comparison view *(size-run exists)*

## Import / export / interop
- [ ] BikeCAD export fidelity audit; import other formats (CAD, OpenSCAD, Rattlecad)
- [ ] Shareable web embed/link; PNG with the geometry table baked in
- [ ] Project bundle (design + photo + catalog refs) in one file
- [ ] Reconstruct a frame from a pasted geometry chart

## Workflow / collaboration
- [ ] Named revisions / diffs beyond undo; cloud sync
- [ ] Customer/order management: link a design to a customer + build spec
- [ ] Quoting from BOM + labor; shop job tracking
- [ ] Comment/review mode; shareable read-only design

## Quality / infra & current bugs
- [ ] (bug) 3-D build untested on macOS/Windows (pyqtgraph/PyOpenGL bundling) — verify before relying on it
- [ ] (bug) CI uses deprecated Node-20 actions — bump checkout/setup-python/upload-artifact
- [ ] (bug) macOS app unsigned (Gatekeeper warning) — code-sign / notarize
- [ ] Aero tubes approximated as ellipse (teardrop not modeled); mesh bends approximated
- [ ] Headless CLI should export build sheet / BOM / size chart too (currently GUI-only)
- [ ] GL viewer has import-level tests only (no GL context in CI)
- [ ] Performance: cache solves, profile large catalogs; trim packaging size (~200 MB)

## Done (recent)
- Catalog in-context pickers + per-tube selection; picked-part shown per section; bill of materials
- Tube + dropout catalog expanded from manufacturer/CAD sources (tubing 431, dropouts 189)
- Oval/aero tubes render with true elliptical sections (2-D, 3-D, STL)
- Interactive 3-D clearance view
- Size-run generator; build / cut sheet PDF; braze-on / mount placement
- Resolve-issues options engine; extra-tube paint & in-phase; seat-stay oval section
- BikeCAD .bcad import **and** export; renamed to Bike Box; Win/mac/Linux installers via CI
