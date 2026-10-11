# Feature parity with BikeCAD Pro

BikeCAD Pro's product page lists 25 Pro features; its user guide covers the general feature set.
This table maps each Pro feature to FrameWright and is honest about gaps.

| BikeCAD Pro feature | FrameWright | Where |
|---|---|---|
| Export a frame model to FreeCAD | ✅ FreeCAD macro (hollow tubes, tapered HT, mirrored stays, mitre booleans) + STL | File ▸ Export |
| AI estimate of frame weight and in-plane / transverse / eccentric loading | ✅ Physics-based instead: per-tube weight estimate and a 3-D beam FEA with 7 load cases (stiffness, stress, safety factor) | Tools ▸ Analysis report |
| Full Fit Advisor with customisable formulas and interface | ✅ Six built-in fitting schemes, editable formula schemes (safe expression evaluator), apply with undo | Tools ▸ Fit advisor |
| Multi-model PDFs | ✅ One sheet per design + overlay comparison page | File ▸ Export ▸ Multi-model PDF |
| Specs for thousands of designs in one CSV | ✅ Driving (input) and driven (`calc:`) columns | File ▸ Export ▸ Spec sheet CSV (folder) |
| Import photos as reference underlays | ✅ Position, scale, rotate, mirror, opacity, two-point calibration, drag-and-drop | View ▸ Photo underlay |
| Templates | ✅ 16 built-in + user templates | File ▸ New from template / Save as template |
| Customise interface (icons, look and feel, splash, title-block logo) | ✅ Font/icon size, light/dark, splash image, logo | Edit ▸ Preferences, Edit ▸ Title block |
| Customise paint palettes | ✅ Custom colours persist across sessions; per-tube colours, fades, panels | Paint parameters |
| Libraries of standard parts | ✅ 14 categories incl. 53 tube sets imported from your parts DB; user items | Edit ▸ Parts libraries |
| All dimensions + user dimensions | ✅ 40-dimension catalogue, dimension states, distance/horizontal/vertical/angle user dimensions | View ▸ Dimensions, toolbar |
| On-screen notes | ✅ With leaders; drag, edit, delete | Toolbar ▸ Add note |
| Auxiliary views: stays, lean angle, fork crown clearance, toe overlap | ✅ Top/rear/front views, lean, steered toe overlap, stay true lengths | Tools ▸ Auxiliary views |
| Snapshot and compare with later changes | ✅ Differences list, ghost overlay, restore | Edit ▸ Snapshots |
| Find and fix problematic curved tubes | ✅ Warnings for over-semicircle bends and radii under 3×OD | Results ▸ warnings |
| UCI compliance check | ✅ Saddle setback, BB height, front/rear centre, length, width, wheels, tube sections, weight | Tools ▸ UCI check |
| Miter templates incl. elliptical tubes and variable-diameter head tubes | ✅ Plus 3-D stays, offsets, multiple receivers, true-scale tiled PDF | Tools ▸ Miter templates |
| G-code for CNC miters | ✅ Rotary (A+X), wrapped and flat modes, kerf, lead-in | Miter templates ▸ Export G-code |
| CSV, animated GIF, dimensioned PDF/SVG/bitmap | ✅ | File ▸ Export |
| Drag and drop designs | ✅ Designs and photos | Drop on the window |
| Save and retrieve locally or online | ◐ Local files only (no cloud service) | File menu |
| Chain or belt length calculator | ✅ Derailleur, single speed (whole/half link), belt tooth counts with matching chainstays | Tools ▸ Gearing & chain/belt |
| Animated GIF morphing one model into another | ✅ From another open design or a snapshot | File ▸ Export ▸ Animated GIF |
| Tables on drawings | ✅ Geometry, tube/cut tables, CSV import | Drawing export ▸ Tables from CSV |
| Centre of mass for bike and rider | ✅ With front/rear weight distribution | Display ▸ Centre of mass |

## Beyond the Pro list (user-guide topics)

Six front-end definitions, BB drop/height, rear end by chainstay or tire gap, curved/tapered/oval tubes,
butted walls, tube extensions and offsets, lugs (4 styles, angle warnings), fillets, bridges, braze-ons,
bottle bosses and bottles, fenders, racks, couplers with a travel-case check, dropout types (vertical,
horizontal, track, sliding, thru) with axle position in the slot, offset dropouts, wishbone/mono stays,
step-through/mixte/cargo via extra tubes, **tandems**, **e-bike motors/gearboxes and batteries**,
suspension forks with sag, quill/threadless stems, five bar types, levers and hand positions, seatmasts and
droppers, decals/logos (text and images), title blocks, standard drawing scales, printing, DXF, units,
display modes, wheel detail levels, toe overlap, lean angle, gearing tables, chainline, fixture numbers.

## Not done yet

* **BikeCAD `.bcad` import**: the format is Java Properties XML with undocumented keys; it needs sample
  files to map and test. FrameWright currently reports the file contents and refuses to guess.
* **Translations**: the interface is English only.
* **Online design archive / cloud save**: not planned (local files and git work well for this).
* Fork crown mitres, inner-wall miter templates and aero-bar (top view) components.
