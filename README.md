# diploma
# NIR-3: Source Data and Preprocessing

This repository contains source spatial data, preprocessing scripts,
and scenario datasets used in the NIR-3 research project
(Digital Urban Studies, ITMO).

## Scope
- Territory: [to be defined]
- Data sources: OpenStreetMap, planning documentation
- Coordinate system: to be defined
- Linking radius (R_link): 40 m

## Repository structure
/data
  /raw          # original, unmodified data
  /interim      # intermediate processing results
  /processed    # final datasets used in the method
  /scenarios    # modified datasets for scenario analysis

/docs           # dataset passport, specifications, decisions
/notebooks      # data loading and preprocessing notebooks
/reports        # QA reports and figures

## Reproducibility
All preprocessing steps are documented and reproducible.
Parameters are fixed and described in the documentation.
