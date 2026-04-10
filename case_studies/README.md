# Case Studies: coordination-metrics

Two end-to-end controlled validations of coordination-metrics on real open-license BIM datasets.

## Datasets

| Case Study | Source | License | Scale |
|---|---|---|---|
| WBDG Duplex Apartment | US General Services Administration / WBDG | Public Domain | 4 discipline models (ARC/ELE/MEP/PLB), residential |
| WBDG Medical Clinic | US General Services Administration / WBDG | Public Domain | 5 discipline models (ARC/STR/ELE/MEP/PLB), healthcare |

---

## Quick Start

### 1. Install dependencies

```bash
cd /path/to/coordination-metrics
pip install -e .
pip install ifcopenshell  # optional but recommended for real clash detection
```

### 2. Run the full pipeline

```bash
cd case_studies/scripts

# Step 1: Generate clashes from IFC models (or synthetic fallback)
python generate_clashes.py --project wbdg_duplex --rounds 6
python generate_clashes.py --project wbdg_clinic --rounds 6

# Step 2: Generate supplementary coordination data (RFIs, submittals, meetings)
python prepare_data.py --project wbdg_duplex
python prepare_data.py --project wbdg_clinic

# Step 3: Run coordination-metrics analysis
python run_analysis.py --project wbdg_duplex
python run_analysis.py --project wbdg_clinic

# Step 4: Generate publication figures
python generate_visuals.py --project wbdg_duplex --format png --dpi 300
python generate_visuals.py --project wbdg_clinic --format png --dpi 300
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

## Large IFC Files

For IFC files over 30MB, the pipeline automatically uses placement-based bounding box extraction instead of full geometry processing. Use `--fast` to force placement mode for all files, or `--max-geom-mb N` to set the threshold.

```bash
python generate_clashes.py --project wbdg_clinic --rounds 6 --max-geom-mb 50
```

---

## Directory Layout

```
case_studies/
├── README.md                    (this file)
├── wbdg_duplex/
│   ├── data/
│   │   ├── ifc/                 IFC model files
│   │   ├── clashes/             generated clash XMLs
│   │   └── README.md
│   └── output/                  analysis results
├── wbdg_clinic/
│   ├── data/
│   │   ├── ifc/                 5 disciplines (ARC/STR/MEP/ELE/PLB)
│   │   ├── clashes/
│   │   └── README.md
│   └── output/
└── scripts/
    ├── generate_clashes.py      IFC clash detection + round simulation
    ├── prepare_data.py          causal RFI / submittal / meeting generation
    ├── run_analysis.py          full coordination-metrics pipeline
    └── generate_visuals.py      publication-quality figures
```
