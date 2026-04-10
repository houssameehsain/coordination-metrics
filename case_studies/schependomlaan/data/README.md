# Schependomlaan — Dataset Setup

## Source

**Primary:** https://github.com/buildingSMART/Sample-Test-Files

Navigate to: `IFC 2x3/Schependomlaan/`

**Mirror / Dataset page:** https://www.ifcwiki.org/index.php?title=IFC_Wiki

License: Creative Commons Attribution 4.0 International (CC BY 4.0)
Attribution: buildingSMART International

## Files Required

### IFC Models — place in `ifc/`

| Filename | Discipline | Notes |
|---|---|---|
| `IfcOpenHouse_ARCH.ifc` or equivalent | ARC | Architectural shell |
| `IfcOpenHouse_STRUCT.ifc` | STR | Structural frame |
| `IfcOpenHouse_MEP.ifc` | MEP | Mechanical/HVAC |
| Additional subcontractor IFCs | varies | Include all available |

The script detects discipline from filename keywords. Rename files to include
the discipline if the originals use numeric naming (e.g., `model_01_mep.ifc`).

### BCF Issues — place in `bcf/`

BCF (BIM Collaboration Format) files from the buildingSMART dataset document
pre-identified coordination issues. Filename: `*.bcf` or `*.bcfzip`.

These are used for cross-validation against clash-detection results.

### Schedule Data — place in `schedules/`

Excel planning files (`.xlsx`) with activity sequences and milestone dates.
Used by the ECV module for schedule performance index calculation.

## Download Steps

```bash
# Option A: Git clone (large repo — use sparse checkout)
git clone --depth=1 --filter=blob:none --sparse \
  https://github.com/buildingSMART/Sample-Test-Files.git
cd Sample-Test-Files
git sparse-checkout set "IFC 2x3/Schependomlaan"
cp -r "IFC 2x3/Schependomlaan/"*.ifc \
  /path/to/case_studies/schependomlaan/data/ifc/
cp -r "IFC 2x3/Schependomlaan/"*.bcf* \
  /path/to/case_studies/schependomlaan/data/bcf/

# Option B: Download ZIP from GitHub
# https://github.com/buildingSMART/Sample-Test-Files/archive/refs/heads/master.zip
# Extract IFC 2x3/Schependomlaan/ and copy files
```

## Without IFC Files

Same as WBDG — the pipeline generates synthetic data:

```bash
python scripts/generate_clashes.py --project schependomlaan --rounds 8
```

Schependomlaan has more disciplines and a longer timeline, so use `--rounds 8`
for a richer dataset.

## Expected Directory State After Setup

```
schependomlaan/data/
├── ifc/
│   ├── *_ARCH.ifc
│   ├── *_STRUCT.ifc
│   ├── *_MEP.ifc
│   └── (additional models)
├── bcf/
│   └── *.bcf
├── clashes/             (auto-generated)
├── schedules/
│   └── *.xlsx           (optional)
├── rfi_register.csv     (auto-generated)
├── submittal_register.csv
└── meeting_minutes.csv
```
