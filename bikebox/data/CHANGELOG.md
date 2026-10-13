# Bike Box — What's New

## 0.1.20
- **Slide any tube** by dragging it, and the **bottom bracket is now moveable** — drag it for BB height, or sideways to move it fore/aft between the wheels. The frame stays connected as you drag.
- **High-resolution app icon** — crisp on high-DPI (e.g. 2560×1440) displays.
- **Unlock input limits** (View ▸ *Unlock input limits*) lets inputs go beyond their normal min/max.
- Designs save to / open from a cross-platform **Documents/Bike Box** folder by default.
- In the extra-tube editor the colour swatch is always clickable and ticks "Paint this tube".
- Tidier, consistent toolbar (no more New/Open/Save buttons duplicating the File menu).

## 0.1.19
- **Click any part** on the drawing — wheels, fork, saddle, bars, cranks, battery, couplers, and more, not just tubes — to jump straight to its editing section.
- **Updates live in Settings** (Help ▸ Settings…): a *Check for updates* button and a *Download & install* button that fetches the right installer for your OS. The old automatic startup check is now opt-in and off by default.

## 0.1.18
- A proper **Remove-tubes** panel: a checkbox per tube that updates the drawing live (was a text box under Advanced).
- **Update check & What's New**: Bike Box can check GitHub for a newer version on startup (toggle it in the Help menu) and this What's New page shows what changed.

## 0.1.17
- Numeric fields are now **scrubbable**: click and drag left/right to change a value in real time, instead of the arrows one step at a time.
- **Click a tube or part** on the drawing to jump straight to its editing section on the left.
- A proper **Remove-tubes** panel: a checkbox per tube (top/down/seat tube, chainstays, seat stays) that updates the drawing live.
- The **battery** option is hidden unless a drive unit (gearbox or mid-motor) is selected.
- The **Resolve-issues** dialog renders its option styling correctly and fits smaller / high-DPI screens.
- The cargo **longtail** deck now draws in the side view.

## 0.1.16
- New frame types: **balance / baby bike** (a small-wheel single with no drivetrain), **cargo longtail** (an extended rear deck) and **folder** (a down-tube hinge).
- **Travel couplings** gained a style: **S&S** torque couplers and **Ritchey Break-Away**, with a travel-case fit check.

## 0.1.15
- The analysis report is computed once per geometry and shared across panels — switching tabs and dragging are much snappier.
- Smaller installers: unused Qt runtime (translations, PDF viewer, SQL/QML plug-ins) is no longer bundled.

## 0.1.14
- The parts catalog is cached and indexed, so the part pickers stay instant on the full ~6,000-item catalog.

## 0.1.13
- **STEP and IGES export**: every tube exports as a 3-D B-rep solid for CAD, alongside STL.

## 0.1.12
- **Aerodynamic estimate**: a first-order CdA and steady-state power figure in the analysis report.

## 0.1.11 and earlier
- Fit-to-rider auto-size, cable/hose routing, customer/order management with quotes, shop CNC outputs (tube notcher & bender), BikeCAD `.bcad` import/export, the interactive 3-D clearance view, and the parts catalog with in-context pickers.
