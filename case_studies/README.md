# Case Studies: coordination-metrics

Three end-to-end demonstrations of coordination-metrics on real open-license datasets.

## Datasets

| Case Study | Source | License | Scale |
|---|---|---|---|
| WBDG Duplex Apartment | US General Services Administration / WBDG | Public Domain | 3 discipline models (ARC/ELE/PLB), residential |
| WBDG Medical Clinic | US General Services Administration / WBDG | Public Domain | 4 discipline models (ARC/MEP/ELE/PLB), healthcare |
| Schependomlaan | buildingSMART International | CC BY 4.0 | ~6 subcontractor models, residential complex |

---

## Quick Start

### 1. Install dependencies

```bash
cd /path/to/coordination-metrics
pip install -e ".[dev]"
pip install ifcopenshell  # optional but recommended for real clash detection
```

### 2. Download datasets

**WBDG Duplex:**
```bash
# See case_studies/wbdg_duplex/data/README.md for download instructions
```

**WBDG Clinic:**
```bash
# See case_studies/wbdg_clinic/data/README.md for download instructions
```

**Schependomlaan:**
```bash
# See case_studies/schependomlaan/data/README.md for download instructions
```

### 3. Run the full pipeline

```bash
cd case_studies/scripts

# Generate supplementary coordination data (RFIs, submittals, meetings)
python prepare_data.py --project wbdg_duplex
python prepare_data.py --project schependomlaan

# Run clash detection and simulate coordination rounds
python generate_clashes.py --project wbdg_duplex --rounds 5
python generate_clashes.py --project wbdg_clinic --rounds 6
python generate_clashes.py --project schependomlaan --rounds 8

# Run coordination-metrics analysis
python run_analysis.py --project wbdg_duplex
python run_analysis.py --project wbdg_clinic
python run_analysis.py --project schependomlaan

# Generate publication figures
python generate_visuals.py --project wbdg_duplex --format png --dpi 300
python generate_visuals.py --project wbdg_clinic --format png --dpi 300
python generate_visuals.py --project schependomlaan --format svg
```

Results land in each project's `output/` directory.

---

## Pipeline Architecture

```
IFC files  ──► generate_clashes.py ──► clash_round_XX.xml
                                             │
RFI / submittal / meeting CSVs ──────────────┤
(from prepare_data.py)                       │
                                             ▼
                                    run_analysis.py
                                             │
                          ┌──────────────────┼──────────────────┐
                          ▼                  ▼                   ▼
                 coordination_report.html  full_analysis.json  charts/
                                             │
                                             ▼
                                    generate_visuals.py
                                             │
                                             ▼
                                    output/figures/
```

## No IFC Files? No Problem

`generate_clashes.py` falls back to synthetic clash generation when no IFC files are present. The simulation parameters are calibrated to realistic project distributions so the analysis pipeline produces meaningful output either way.

```bash
python generate_clashes.py --project wbdg_duplex --rounds 6
# Works without IFC files — generates synthetic clash data
```

---

## Directory Layout

```
case_studies/
├── README.md                    (this file)
├── wbdg_duplex/
│   ├── data/
│   │   ├── ifc/                 drop IFC files here
│   │   ├── clashes/             generated clash XMLs (git-ignored)
│   │   └── README.md
│   └── output/                  analysis results (git-ignored)
├── wbdg_clinic/
│   ├── data/
│   │   ├── ifc/                 4 disciplines (ARC/MEP/ELE/PLB)
│   │   ├── clashes/
│   │   └── README.md
│   └── output/
├── schependomlaan/
│   ├── data/
│   │   ├── ifc/
│   │   ├── bcf/
│   │   ├── clashes/
│   │   ├── schedules/
│   │   └── README.md
│   └── output/
├── scripts/
│   ├── generate_clashes.py      IFC clash detection + round simulation
│   ├── prepare_data.py          RFI / submittal / meeting data generation
│   ├── run_analysis.py          full coordination-metrics pipeline
│   └── generate_visuals.py      publication-quality figures
└── paper/
    ├── main.tex
    ├── references.bib
    └── figures/
```
