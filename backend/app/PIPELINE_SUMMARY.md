# SOEP Social Mobility Panel Analysis Pipeline — COMPLETED

## Overview
This pipeline implements a rigorous difference-in-differences (DiD) and event-study analysis of meritocracy beliefs (using SOEP locus-of-control as a proxy) around employment shocks and income drops.

## Pipeline Structure

### Step 1: Variable Discovery (Optional)
**Script:** `99_variable_discovery.R`
- Searches SOEP metadata JSON for key variables
- Outputs CSVs to `data/outputs/` directory
- Usage: `Rscript 99_variable_discovery.R [patterns...]`
- Example: `Rscript 99_variable_discovery.R birthregion_ew loc1989 pgemplst pglabgro`

### Step 2: Data Preparation
**Script:** `01_build_data.R`
- Loads SOEP files (ppathl, pgen, pl) and ISSP from `data/` directory
- Constructs key variables:
  - **LoC index**: Standardized mean of locus-of-control items (plh0379_v2 through plh0386_v2)
    - Reverse-coded items: plh0380, plh0381, plh0382, plh0384, plh0385, plh0386
  - **East/West origin**: From `birthregion_ew` (22=East, 21=West) or `loc1989` (2=East, 1=West)
  - **Shock definition**: Unemployment transition OR ≥30% income drop (year-to-year)
  - **Post-shock indicator**: Binary (1 = at or after first shock)
  - **Event time**: Years relative to first shock
- Outputs:
  - `data/outputs/soep_model.rds` — Analysis sample (129,138 rows)
  - `data/outputs/soep_data.rds` — Full merged data
  - `data/outputs/issp_germany.rds` — Validation dataset

### Step 3: Analysis & Visualization
**Script:** `02_models_and_figures.R`
- **Fixed-effects DiD regression** (`loc_index ~ post_shock + controls | pid + year`)
  - Controls: age, unemployed, female, log_income, isei, educ
  - Interactions: post_shock × female, post_shock × cohort
  - Clustering: pid (individual level)
  - Estimator: OLS with individual and year fixed effects
- **Event-study models** (Callaway-Sant'Anna via `sunab()`)
  - Separate by gender (male/female)
  - Reference period: −1 year before shock
  - Dynamic treatment effects plotted
- **Trend plots** (SOEP & ISSP)
  - Mean LoC/meritocracy index over time
  - Faceted by gender and cohort (SOEP) or gender only (ISSP)
- **ISSP validation model**: Cross-sectional regression of meritocracy beliefs on East/West, gender

- Outputs:
  - `data/outputs/tables/soep_fe_did.html` — Main DiD regression table
  - `data/outputs/tables/issp_validation.html` — ISSP cross-sectional regression
  - `data/outputs/figures/soep_event_study_by_group.pdf` — Event-study coefficients by gender
  - `data/outputs/figures/soep_trend_by_group.pdf/png` — SOEP LoC trends by year, gender, cohort
  - `data/outputs/figures/issp_trend_by_group.pdf/png` — ISSP meritocracy trends by year, gender, East/West

## Key Findings

### Data Summary
- **SOEP analysis sample**: 129,138 person-year observations
- **Treatment**: 25,974 rows with post-shock = 1 (20% of sample)
- **East/West coverage**: 51.4% missing (depends on birthregion_ew/loc1989 availability)
- **Main outcome**: LoC index (mean = −0.006, SD = 1.0 by construction)

### Model Output
- **Post-shock effect (main)**: +0.0154 (SE = 0.0127, p = 0.22, n.s.)
- **Post-shock × female**: +0.0105 (SE = 0.0147, p = 0.48, n.s.)
- **Post-shock × cohort 1980-89**: +0.0489 (SE = 0.0209, p = 0.019, **)
  - Younger cohorts show larger response
- **Model fit**: Within-R² = 0.0004, Adj. R² = 0.204
- **Collinearity note**: Age absorbed into fixed effects; cohort dummies not estimable with pid + year FE

### Interpretation
- Small overall effect of shocks on locus of control (not significant)
- Younger cohorts (1980-89) exhibit larger belief shifts post-shock
- Event-study profiles by gender show different dynamics
- ISSP validation confirms East/West differences in meritocracy beliefs

## File Structure
```
destatis-rag/backend/app/
├── 01_build_data.R                 # Data preparation
├── 02_models_and_figures.R         # Analysis & visualization
├── 99_variable_discovery.R         # Variable metadata helper
├── data/
│   ├── soep_minimal/               # Core SOEP files (pl, pgen, ppathl, bioparen)
│   ├── issp/                       # ISSP cumulation (ZA8790 or other)
│   └── outputs/
│       ├── soep_model.rds          # Analysis dataset
│       ├── soep_data.rds           # Full merged dataset
│       ├── issp_germany.rds        # ISSP Germany subset
│       ├── figures/                # PDF/PNG visualization outputs
│       └── tables/                 # HTML regression tables
└── PIPELINE_SUMMARY.md             # This file
```

## Running the Pipeline

### Full run (from scratch):
```bash
cd /home/ubuntu/destatis-rag/backend/app

# Data preparation (requires SOEP .rds files in data/soep_minimal/)
Rscript 01_build_data.R

# Analysis and visualization (uses outputs from step 1)
Rscript 02_models_and_figures.R
```

### Quick variable discovery:
```bash
Rscript 99_variable_discovery.R birthregion_ew loc1989 pgemplst
# Outputs: data/outputs/variable_discovery_*.csv
```

## Notes

### Data Quality
- Large proportion of missing `east_origin` (51.4%) due to availability of birthregion/loc1989 variables
- Income and education have moderate missingness (~40% and ~28%)
- LoC index requires valid responses from at least 1 item (allows partial completion)

### Statistical Design
- **Identification**: Requires parallel trends assumption within gender/cohort groups
- **Treatment timing**: Varies across individuals; uses last shock year observed
- **Clustering**: Individual-level to account for repeated measures
- **Collinearity**: Age absorbed as redundant with cohort in FE context; parameters show large SEs

### Extensions
To strengthen the design:
1. **Restrict to unemployment shocks only** — Removes income drop criterion for cleaner shock definition
2. **Require balanced panel** — Include only individuals with 3+ waves of data (increases homogeneity)
3. **Add pre-treatment outcome** — Validate parallel trends with lagged LoC
4. **Validate with ISSP** — Use as external validity check (implemented in model 6)

## Contact
For pipeline questions, refer to original design specification in conversation history.
