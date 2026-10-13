# Bike Box user guide

## The window

* **Canvas** (centre): the live side-view drawing. Each open design is a tab.
* **Parameters** (left): every input, grouped (Frame, Tubes, Fork & headset, Cockpit, Saddle & seatpost,
  Drivetrain, Wheels & brakes, Accessories, Joints, Paint, Rider & fit, Analysis, Manufacturing, Drawing,
  Display, Project). Type in the search box (Ctrl+F) to find any parameter. Hover a label for help and
  its key. Inputs that don't apply to the current mode are hidden.
* **Results** (right): stack, reach, trail, wheelbase, fit numbers, clearances, joint angles, warnings and
  (optionally) the full analysis report.

## Navigating

| Action | How |
|---|---|
| Zoom | mouse wheel (at the cursor), `+` / `-`, View ▸ Zoom |
| Pan | drag on empty space, middle-drag, right-drag, or Space + drag |
| Fit | `F` or View ▸ Fit to window; View ▸ Lock zoom keeps the scale |
| Undo / redo | Ctrl+Z / Ctrl+Shift+Z (every edit, including drags) |

## Designing

1. **Start**: File ▸ New (defaults) or **New from template** (road, endurance, gravel, cyclocross, touring,
   randonneur, track, hardtails, city step-through, mixte, kids, time trial, fat bike, tandem, e-trekking).
2. **Wheels & BB**: rim BSD + tire width/height set the wheel size; BB by drop or height.
3. **Rear end**: chainstay length, or the gap between rear tire and seat tube.
4. **Seat tube**: angle, length (centre-to-top or centre-to-centre), extension, BB offset.
5. **Front end**: choose what drives it — *height* by head tube length, stack or handlebar height;
   *length* by reach, front centre, effective top tube, wheelbase or handlebar reach. The other values
   are computed and shown in Results.
6. **Fork & headset**: axle-to-crown, offset, lower/upper stack, spacers; suspension forks with travel/sag.
7. **Top & down tubes**: junction offsets on the head tube, top tube by angle or seat tube extension.
8. **Seat stays**: on the seat or top tube, conventional/wishbone/mono, dropout type and offsets.
9. **Tubes**: OD, oval/aero profile (side depth + top width), taper, butted walls, bends (curved tubes),
   materials.
10. **Cockpit & saddle**: stem, bars, levers, hand position; saddle by height + seat angle or X/Y.

### Using the parts catalog

Every component section in the left panel has a **“… from catalog…”** button that opens a picker of real,
sourced parts for that component — the fork, stem, handlebar, saddle, seatpost, crankset, cassette, derailleur,
rim, hub, tire, brakes, BB shell, dropouts and lugs. For **tubing** each frame position has its own picker
(*Top tube from catalog…*, *Down tube…*, etc.) that lists only tubes that fit there and applies that one tube —
OD, butted walls and profile — without touching the others; the Material section’s *Tube set from catalog…*
applies a whole set at once. The picker shows what it will change (current → new), the manufacturer’s specs and
the source, and applies as a single undo step. Edit ▸ **Parts libraries** (Ctrl+L) is the full browser across
all 5,300+ catalogued parts, and you can save your own items there.

Parts you apply from the catalog are remembered per component and collected into a **Bill of materials** —
shown in the Results report and exportable as CSV via File ▸ Export ▸ *Bill of materials CSV…*. It lists every
frame tube and the fork with their computed specs (OD, butted wall, length, material), plus each assigned
component with its catalogued name, brand and source.

### Direct manipulation
Drag the blue handles: **saddle** (height; Shift = free move/custom seat angle), **handlebar** (stem length and
spacers), **head tube top** (stack & reach), **rear axle** (chainstay & BB drop; Shift = length only),
**seat tube top**, **front axle**, **pedal** (crank angle).
Double-click a dimension to type a value; Bike Box switches the front-end mode as needed (e.g. editing
*Stack* makes stack a driving dimension). Drag dimensions to move them; right-click to hide/reset them.

### Special frames
* **Step-through, mixte, cargo, braces**: Frame ▸ Advanced ▸ *Remove tubes*, and Edit ▸ *Extra tubes* with end
  points such as `ht_bottom`, `st@0.25`, `rear_axle`, `ht_bottom+0,-40` or `-200,150`. Each extra tube can be
  **painted its own colour** (Paint ▸ *Paint this tube*) and kept **in phase (parallel)** with another tube
  (*In phase with*), so a lateral or twin tube stays parallel as you change the geometry.
* **Tandem**: Frame ▸ Tandem ▸ *Frame type = Tandem*. The captain's front triangle uses the normal inputs;
  set the BB-to-BB distance, stoker seat tube, stoker top tube, mid/lateral tubes, stoker saddle and bars.
* **E-bikes / gearboxes**: Frame ▸ Drive unit: housing size/position, battery on or in the down tube or on a rack.
* **Braze-ons & mounts**: Edit ▸ *Braze-ons & mounts* — place bottle bosses, cable stops/guides, rack and fender
  eyelets and disc mounts on any tube (position along the tube, side offset, boss spacing). They draw on the
  frame and their coordinates appear on the build / cut sheet.

## Dimensions, notes, comparison

* View ▸ **Dimensions** (Ctrl+D): pick from the catalogue, save/restore **dimension states**, manage user dimensions.
* Toolbar: **Measure** (M), **user dimension** (D), **angle dimension**, **note** (N). Points snap to frame
  points and to positions along any tube, including extra tubes, so a dimension follows the geometry.
* View ▸ **Compare designs** (Ctrl+K) overlays other open designs, files or snapshots as coloured ghosts.
* Edit ▸ **Snapshots** saves the current state, shows differences, overlays or restores it.
* View ▸ **Photo underlay**: import a photo (or drop it on the window), then Tools ▸ *Calibrate photo* and
  click two points a known distance apart.

## Fit

Tools ▸ **Fit advisor**: enter body measurements (missing values are estimated from height and inseam), pick a
fitting scheme, review recommendations with ranges, tick and **apply** them. *Edit formulas* lets you write your
own scheme (safe expressions, saved in the design). Turn on the **Rider** checkbox to draw the rider and see joint
angles; Display ▸ *Centre of mass* shows the combined COM and weight distribution.

## Manufacturing

* Tools ▸ **Miter templates** (Ctrl+M): preview every cope, export a full-scale PDF (print at 100% and check the
  50 mm square), SVG or DXF; hole-saw angle/offset; cut list; rotary-axis **G-code** (verify in a simulator first).
* Tools ▸ **Frame fixture numbers**: coordinates and lengths to set a frame up in a jig.
* File ▸ Export ▸ **FreeCAD macro** or **STL** for 3-D work.

## Analysis

Tools ▸ **Analysis report** (Ctrl+R): gearing table, chain/belt length, UCI checks, weight estimate, beam-model
stiffness and stress estimate, clearances. Tools ▸ **Auxiliary views**: top, rear and front views for stay,
tire, chainring, heel and crown clearances; lean angle; steered toe overlap; stay true lengths.

The **3-D clearance view** — the **3-D** button on the toolbar (or View ▸ 3-D clearance view) — opens an
interactive 3-D model of the frame and wheels you can orbit, zoom and pan, docked as a tab beside Results. It
updates live as you edit. Every clearance is drawn as a gap line between the two closest surface points — green
where it meets its threshold, red where it fails — with the measured value, plus a side list you can click to
focus each one. (Needs the optional `pyqtgraph` and `PyOpenGL` packages; the bundled installers include them.)

### Resolving issues

When any clearance or geometry check fails, a **Resolve issues…** button appears above the Results list (also
Tools ▸ **Resolve issues**). It lists every issue — tire/chainring/crank clearance, seat-stay and bridge
clearance, fork crown and blade, steered toe overlap, heel clearance, seatpost insertion too shallow, top/down
tube overlap on the head tube — and for each one offers several ways to address it (e.g. for a seat-tube/tire
clash: lengthen the chainstays *or* fit a narrower tire). Each option shows the resulting clearance, its effect
on the rest of the geometry (stack, reach, wheelbase, trail…), and any new problem it would introduce. The
recommended option is preselected; choose another, or **Leave unchanged**, per issue. A live preview says how
many issues would remain, and **Apply selected** makes all the chosen changes in one undo step.

## Output

* File ▸ Export ▸ **Drawing (PDF/SVG/PNG)** or File ▸ **Print**: paper size, scale (auto or standard), border,
  title block (Edit ▸ Title block, logo image), geometry/tube tables, tables from CSV, monochrome.
* **DXF** (full size, mm, layers), **SVG** of the bike, **spec CSV** (one design or a whole folder),
  **multi-model PDF** of all open designs, **bulk export** of a folder, **animated GIF** morph from another
  design or snapshot.
* **BikeCAD** (`.bcad`): File ▸ Save As and choose the *BikeCAD designs* format — the filename defaults to
  `.bcad` and the core geometry is written as a BikeCAD-readable file (import it back, or open it in BikeCAD).
* File ▸ Export ▸ **Build / cut sheet (PDF)**: one shop document — key geometry, the mitre cut list, the notcher
  setup (hole-saw Ø, notch angle, offset, rotation), tube-bender specs, the bill of materials and fixture numbers.
* File ▸ Export ▸ **CNC notcher & bender (CSV)** (or `bikebox cnc`): the notcher and bender tables on their own.
* View ▸ **Size run**: generate a family of sizes from the current design and export the geometry chart (CSV).
* Headless: `bikebox export design.bikebox out.pdf` (also .svg .png .dxf .csv).

## Customising

Edit ▸ **Preferences**: drawing line/text scale, interface font size, icon size, light/dark theme, default units,
mouse-wheel direction, drag handles, recent-files length, autosave backups. Display parameters (per design)
control drawing mode, wheel detail, line weights, colours, dimension text size/orientation and layers.
Save any design as a **template** (File ▸ Save as template); add your own library items from the libraries dialog.

### Riders & fit schemes

Tools ▸ **Fit advisor** applies a fitting scheme to the rider's body measurements and recommends saddle height,
setback, bar position, cranks and frame size (with sensible ranges). Schemes are literature-based: *Classic road*
(LeMond 0.883 × inseam, KOPS), *Endurance/comfort*, *Gravel & touring*, *Mountain*, **Track** (sprint position:
slightly forward of KOPS, flatter torso ~90–95° torso-to-arm, 20–30° elbow bend — Colby Pearce / Track Cycling
Academy), *Time trial*, and *Knee angle (Holmes)* (25–35°). Tools ▸ **Rider database** saves a rider's
measurements by name and applies them to any design.

### Customers & orders

Tools ▸ **Customer & order** attaches a customer (name, contact, notes), an order number, status and due date to the design, and builds a **quote** from the bill of materials plus labour (hours × rate) and a frame build price. Export the quote as a PDF, and each saved order is logged per user. Prices are your own — the catalog carries specs and weights, not prices.

### Cable & hose routing

Edit ▸ **Cable & hose routing** adds common routes (rear/front shift, rear brake, dropper, Di2, dynamo) as internal or external paths along the tubes. They draw on the frame; internal routes mark entry/exit **ports**, whose coordinates are listed on the build sheet for drilling.
