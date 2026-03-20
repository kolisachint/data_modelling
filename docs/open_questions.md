# Open Questions

Running list of ambiguities, conflicts, and unresolved items.
Add items here whenever something cannot be resolved from the workbook alone.
Review this file with business and engineering stakeholders before any model work begins.

Format: `[ ]` open · `[x]` resolved (add resolution note inline)

---

## Platform & Infrastructure

- [ ] **BQ-01** What are the BigQuery project ID(s) for dev, staging, and production?
- [ ] **BQ-02** What are the dataset naming conventions — confirm `raw_`, `stg_`, `int_`, `mart_` prefixes or alternatives?
- [ ] **BQ-03** Is there an existing Terraform module for BQ resources, or will one be created from scratch?
- [ ] **BQ-04** What IAM roles/service accounts should have access to each dataset layer?

## dbt

- [ ] **DBT-01** Which dbt version is in use (or planned)? Core or Cloud?
- [ ] **DBT-02** What is the target `profiles.yml` setup — single project, multi-env targets?
- [ ] **DBT-03** Are there existing dbt packages in use (e.g., `dbt_utils`, `dbt_expectations`)?
- [ ] **DBT-04** What is the materialization strategy for each layer (view / table / incremental)?

## Orchestration

- [ ] **ORC-01** What Composer/Airflow version and environment are in use?
- [ ] **ORC-02** How are dbt runs triggered — via `BashOperator`, `DbtCloudRunJobOperator`, or Cosmos?
- [ ] **ORC-03** What is the expected refresh cadence for each model layer?

## Data Model (to be populated after workbook review)

- [ ] **DM-01** _(Add entity/column-specific questions here after workbook is read)_

## Source Systems

- [ ] **SRC-01** What are the source systems feeding into the data platform?
- [ ] **SRC-02** How is raw data landed into BigQuery — Fivetran, Dataflow, custom ingestion?
- [ ] **SRC-03** Are there any CDC (change data capture) patterns in use?

## Governance

- [ ] **GOV-01** Who is the data owner for each domain?
- [ ] **GOV-02** Are there any data retention or deletion requirements?
- [ ] **GOV-03** Is column-level security (BigQuery column masking / policy tags) required?

---

## Resolved

_(None yet — move items here with resolution notes once answered)_

---

## Extracted from Workbook (sample_data_model.xlsx, 2026-03-18)

### Notes / Open Items from Workbook

- [ ] # | Type | Description | Owner | Status
- [ ] 1 | Open Question | Should line_total be stored or always derived? | Data Team | Open
- [ ] 2 | Open Question | Confirm ISO currency codes — CRM uses 3-char, OMS uses symbol | J. Smith | Open
- [ ] 3 | TBD | Partitioning strategy for Order table — by order_date? | Platform | Open
- [ ] 4 | TBD | dbt version to use — Core 1.8 or Cloud? | Platform | Open
- [ ] 5 | Assumption | customer_code is stable and can be used as a join key across systems | Data Team | Review
- [ ] 6 | Note | PIM system does not provide created_at — will default to load time | A. Lee | Accepted
- [ ] Legend: | Open = unresolved | TBD = needs decision | Assumption = flagged | Note = informational


---

## Extracted from Workbook (sample_data_model.xlsx, 2026-03-18)

### Notes / Open Items from Workbook

- [ ] # | Type | Description | Owner | Status
- [ ] 1 | Open Question | Should line_total be stored or always derived? | Data Team | Open
- [ ] 2 | Open Question | Confirm ISO currency codes — CRM uses 3-char, OMS uses symbol | J. Smith | Open
- [ ] 3 | TBD | Partitioning strategy for Order table — by order_date? | Platform | Open
- [ ] 4 | TBD | dbt version to use — Core 1.8 or Cloud? | Platform | Open
- [ ] 5 | Assumption | customer_code is stable and can be used as a join key across systems | Data Team | Review
- [ ] 6 | Note | PIM system does not provide created_at — will default to load time | A. Lee | Accepted
- [ ] Legend: | Open = unresolved | TBD = needs decision | Assumption = flagged | Note = informational

