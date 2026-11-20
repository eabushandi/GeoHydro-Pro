# GeoHydro Pro v0.3.0 — User Acceptance Test Report

## 1. Test summary

| | |
|---|---|
| Software version | 0.3.0 (Help ▸ About) |
| Installation file | GeoHydroPro-0.3.0-Setup.exe / win64.zip |
| Tester | |
| Organisation / role | |
| Test period | from ____________ to ____________ |
| Guide used | UAT_GUIDE_v0.3.0 |

## 2. Test environment

| Item | Value |
|---|---|
| Windows edition and version (Settings ▸ System ▸ About) | |
| OS build | |
| Processor | |
| Memory (RAM) | |
| Graphics adapter and driver version | |
| Screen resolution and display scaling | |
| Antivirus product | |
| Installation type (per user / all users / portable) | |
| Installation folder | |
| Self-test report attached (INS-04) | Yes / No |
| Self-test result line | |

## 3. Test results

Result: **P** = Pass, **F** = Fail, **B** = Blocked (could not run), **N/A** = not
applicable. For every F, add an entry to the defect log (§4) and give its number in
Notes.

| ID | Test | Result | Actual value / observation | Notes / defect no. |
|---|---|---|---|---|
| INS-01 | Installer starts | | | |
| INS-02 | Per-user installation | | | |
| INS-03 | Start menu entries | | | |
| INS-04 | Installation self-test | | | |
| INS-05 | Sample projects open | | | |
| INS-06 | File association | | | |
| INS-07 | Portable zip | | | |
| INS-08 | Uninstall and reinstall | | | |
| SET-01 | Start page and layout | | | |
| SET-02 | Display scaling | | | |
| SET-03 | Default units | | | |
| SET-04 | New project and default CRS | | | |
| SET-05 | CRS tool | | | |
| SET-06 | Language | | | |
| IMP-01 | Import the XYZ dataset | | | |
| IMP-02 | Dataset views | | | |
| IMP-03 | Quality control on faulty data | | | |
| IMP-04 | Excel and geographic data | | | |
| IMP-05 | Export to CSV | | | |
| GRD-01 | Linear triangulation | | | |
| GRD-02 | Minimum curvature, natural neighbour and IDW | | | |
| GRD-03 | Cross-validation | | | |
| GRD-04 | Kriging with variogram | | | |
| GRD-05 | Grid file export and re-import | | | |
| GM-01 | Grid calculator | | | |
| GM-02 | Exactness check by difference | | | |
| GM-03 | Filter | | | |
| GM-04 | Slope | | | |
| GM-05 | Aspect | | | |
| GM-06 | Hillshade | | | |
| GM-07 | Curvature | | | |
| GM-08 | Volumes | | | |
| GM-09 | Profile | | | |
| GM-10 | Clip | | | |
| MAP-01 | Contour map | | | |
| MAP-02 | Contour properties | | | |
| MAP-03 | Colour relief and filled contours | | | |
| MAP-04 | Post map | | | |
| MAP-05 | Multiple layers | | | |
| MAP-06 | Page elements | | | |
| MAP-07 | Text box and logo | | | |
| MAP-08 | Export for publication | | | |
| GIS-01 | Vector import | | | |
| GIS-02 | Raster import | | | |
| GIS-03 | Buffer refused in degrees | | | |
| GIS-04 | Reproject | | | |
| GIS-05 | Buffer, measures, dissolve | | | |
| GIS-06 | Points to point dataset | | | |
| GIS-07 | Point density | | | |
| GIS-08 | Blank a grid with a polygon | | | |
| GIS-09 | Integrated map | | | |
| GIS-10 | Symbology | | | |
| GIS-11 | GIS demo project | | | |
| UND-01 | Undo and redo | | | |
| PRJ-01 | Save and reopen | | | |
| PRJ-02 | Processing history | | | |
| PRJ-03 | Older project files | | | |
| PRJ-04 | Output console | | | |
| PLN-01 | Planned items disabled and labelled | | | |
| PLN-02 | Feature checklist | | | |

**Totals:** Pass ____  Fail ____  Blocked ____  N/A ____  (of 60)

## 4. Defect log

Severity:
**Critical**: crash, data loss, wrong numerical result without warning, or the
program cannot be installed or started.
**Major**: a documented feature does not work, or works only with a workaround.
**Minor**: incorrect behaviour with an easy workaround, or a misleading message.
**Cosmetic**: layout, wording, icons.

| No. | Test ID | Severity | Description | Steps to reproduce | Expected | Actual | Screenshot / file |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | | |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |
| 5 | | | | | | | |

## 5. Known issues observed

Tick each known issue from the guide (§7.1) that you also saw.

| Issue | Seen? | Comment |
|---|---|---|
| K1 Natural neighbour hull-node error | | |
| K2 Undo/Redo ribbon buttons without icon | | |
| K3 Colour scale of a near-constant grid | | |
| K4 UAT dataset not in installer | | |
| K5 SmartScreen / antivirus warning (unsigned) | | |

## 6. Usability and performance observations

| Topic | Observation |
|---|---|
| Start-up time (seconds, first start / later starts) | |
| Responsiveness while gridding and drawing maps | |
| Readability at your display scaling | |
| Clarity of messages and warnings | |
| Anything confusing or missing | |

## 7. Acceptance decision

Criteria (guide §8): all INS and PRJ tests pass; every exact value in guide §5
matches within tolerance; no open Critical or Major defect.

| Decision | Tick one |
|---|---|
| **Accepted**: v0.3.0 is confirmed on this Windows version | |
| **Accepted with conditions**: listed minor defects to be fixed in v0.3.1 | |
| **Not accepted**: Critical or Major defects must be fixed and retested | |

Conditions or comments:

&nbsp;

&nbsp;

| | Name | Signature | Date |
|---|---|---|---|
| Tester | | | |
| Approved by | | | |

Attachments: self-test report, Output Console log, screenshots of failures, exported
test files (PNG, TIFF, PDF of MAP-08).
