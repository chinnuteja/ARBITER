# ARBITER

**A proof layer for dental-benefit decisions.**

ARBITER takes a dental claim and a human-reviewed plan specification, calculates
the modeled plan payment, and produces a line-by-line explanation linked to the
plan language that caused each step. If the available documents cannot support
a decision, ARBITER identifies the missing evidence instead of guessing.

> AI can help read the contract. AI never decides the dollars.

**[Open the deployed preview](https://arbiter-k254aa7ct-tejas-projects-822e4136.vercel.app/)**

The fastest path is: open B01, compare the two outcomes, inspect either trace,
and follow its source-clause links back to the reviewed brochure text.

## The 20-second example

The opening demonstration compares the same modeled treatment under the 2026
Delta Dental and MetLife FEDVIP Standard options:

| Input | Value |
|---|---:|
| Procedure | Two approved D2740 porcelain crowns |
| Teeth | 3 and 14 |
| Network | In-network |
| Synthetic benchmark allowance | $1,000 per crown |
| Annual maximum already used | $1,100 |

Both brochures say the member pays 65% of the plan allowance for in-network
Class C services. The modeled plan share is therefore 35%, or $350 per crown.

| Plan | Published annual maximum | Maximum remaining | Modeled payment |
|---|---:|---:|---:|
| Delta Standard | $1,500 | $400 | **$400** |
| MetLife Standard | $2,000 | $900 | **$700** |

Delta's maximum runs out on the second line; MetLife's does not. The $300
difference is produced by the deterministic engine, not written into the UI.

### What this example assumes

The comparison is intentionally explicit about what the public brochures cannot
prove on their own:

- The two crowns are on different teeth, with no prior crown on either tooth
  inside the applicable replacement or frequency window.
- Both crowns have already passed the carrier's dental or clinical review, are
  covered as submitted, and are not reduced to an alternate benefit.
- The $1,000 amount is a frozen synthetic benchmark used identically for both
  plans. It is not a carrier fee schedule or a reimbursement quote.
- The member enters the claim with $1,100 already applied to the relevant annual
  maximum.

The result is therefore a **verified modeled comparison**, not a promise that a
real carrier will pay these amounts for an arbitrary patient or crown.

## What ARBITER demonstrates

```text
Public plan brochure
        │
        ▼
AI-assisted extraction ──► exact-span verification ──► human-reviewed typed spec
                                                               │
Claim + history + pricing + accumulator balances               │
        │                                                      │
        └──────────────────────► deterministic engine ◄────────┘
                                      │
                                      ├── modeled dollars
                                      ├── accumulator changes
                                      ├── rule-by-rule trace
                                      └── cited clauses or scoped abstention
```

The engine applies eligibility, frequency, alternate-benefit, benchmark-price,
deductible, coinsurance, annual-maximum, and final-split stages in a declared
order. It uses integer cents, canonical claim-line ordering, and keyed
accumulator pools so the same reviewed input can be replayed exactly.

## Core technical decisions

These choices define the trust boundary of the prototype. They are product
decisions as much as implementation details.

| Decision | Why it exists |
|---|---|
| **Keep AI outside the money path** | A model may propose rules, but only a reviewed, versioned specification can be executed. Identical approved inputs therefore produce identical outputs. |
| **Track provenance at field level** | One provision can contain a sourced amount, a derived normalization, and an ambiguous basis. Wrapping only the whole rule would hide that difference. |
| **Use discriminated `PlanValue[T]` states** | `sourced`, `derived`, `assumed`, `ambiguous`, `not-stated`, and `missing-source` values cannot be silently confused with one another. |
| **Verify exact source spans** | Every sourced value must resolve to an exact quote on a hash-bound canonical PDF page. A plausible citation is not enough. |
| **Represent balances as named pools** | Deductibles, annual maxima, and frequency limits can be shared or separate across networks, classes, and codes. `pool_id` makes that contract interpretation explicit. |
| **Scope ambiguity to affected lines** | An unclear orthodontic or examination clause must not poison an unrelated claim. Candidate interpretations continue until they produce different decisions. |
| **Separate missing documents from plan silence** | “The brochure does not say” is different from “the required fee schedule, history, or clinical policy was never supplied.” The engine reports the missing evidence class. |
| **Declare ordering and rounding** | Lines are canonically ordered once at claim entry, and integer-cent rounding happens only at declared stages. Neither behavior is left to incidental runtime details. |
| **Return proposed immutable deltas** | Adjudication does not mutate stored balances. A complete result proposes a keyed accumulator delta that can be validated, committed, or negated for reversal. |
| **Freeze the oracle before engine evaluation** | Thirty cases contain 60 hand-authored plan expectations. Corrections are logged rather than silently rewriting the benchmark to match the implementation. |

### Deterministic execution contract

For each claim, ARBITER validates the member, plan, coverage tier, document set,
pricing source, history source, and accumulator identifiers before evaluating a
line. Lines are sorted once by service date, source sequence, and line ID. Each
stage emits an `Effect` containing its before value, after value, rule ID,
assumptions, and acceptable source-clause IDs.

A complete determination can propose accumulator changes. An incomplete
determination cannot. This prevents a partially understood claim from quietly
changing deductible, maximum, or frequency balances.

## Why this matters for a dental-benefits administrator

Fast adjudication is only half the problem. An employer, operator, support agent,
auditor, or member may still need to know:

- why a line was covered or denied;
- which balance changed;
- why the member owes a particular amount;
- which contract sentence supports the decision; and
- whether the available documents were actually sufficient to decide.

ARBITER explores how that proof can be produced as part of the calculation
rather than reconstructed afterward.

## Evidence and uncertainty

The reviewed sources are the official 2026 U.S. Office of Personnel Management
brochures:

- [Delta Dental FEDVIP brochure — 02AP-05](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/02AP-05.pdf)
- [MetLife FEDVIP brochure — 02AP-11](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/02AP-11.pdf)

Every reviewed value is classified as sourced, derived, assumed, ambiguous, or
missing-source. Ambiguity is scoped: an unclear examination-pool clause should
not block an unrelated filling. Missing claim history, fee schedules, or
clinical policy remain distinct missing-document states.

## AI compiler audit

The extraction compiler and payment engine are deliberately separate. The
compiler proposes structured rules and citations; exact-span validation and
human review gate what can enter the deterministic money path.

The included frozen benchmark records three independent Gemini 3.5 Flash passes
per plan. Across six completed calls, the model made four unsafe assertions on
fields whose reviewed state was ambiguous or missing-source. These outputs never
entered the engine. The result illustrates the design requirement: fluent
extraction is useful, but unsupported certainty must be caught before money
moves.

## Run locally

Requirements: Python 3.12 or newer.

```powershell
python -m pip install -e .
python scripts/run_demo.py
```

Open <http://127.0.0.1:8787>. No API key is required for the public demo because
it runs the frozen reviewed artifacts and deterministic engine.

### Read-only demo API

| Endpoint | Purpose |
|---|---|
| `GET /api/cases` | List the 30 reviewed scenarios |
| `GET /api/case/B01` | Re-run one scenario through both reviewed specs |
| `GET /api/benchmark` | Return the frozen compiler-evaluation summary |

## Verify the claims

```powershell
python scripts/validate_gold_spec.py data/specs/delta-standard-2026.gold.json
python scripts/validate_gold_spec.py data/specs/metlife-standard-2026.gold.json
python scripts/validate_case_oracle.py
python scripts/run_engine_oracle.py
python -m pytest
python -m ruff check .
```

The test suite checks all 60 plan-specific oracle outcomes, the B01 arithmetic
and assumptions, accumulator conservation, canonical ordering, source-bound
figures, compiler scoring, and the demo API.

## Deploy to Vercel

`app.py` is the FastAPI entrypoint and `pyproject.toml` declares it for Vercel.
Import the repository into Vercel and deploy with the default Python settings.
The hosted demonstrator is read-only and requires no model credential.

Deployed preview:
[arbiter-k254aa7ct-tejas-projects-822e4136.vercel.app](https://arbiter-k254aa7ct-tejas-projects-822e4136.vercel.app/)

## What this is—and is not

ARBITER is a working, evidence-linked adjudication demonstrator:

- two human-reviewed public plan specifications;
- 30 frozen synthetic cases and 60 plan outcomes;
- deterministic execution with clause-level traces;
- scoped ambiguity and missing-document abstentions; and
- a separately evaluated brochure-to-spec compiler.

It is **not yet a production claims platform**. A production deployment would
still need carrier-specific fee schedules, enrollment and provider-network
feeds, complete clinical policies, claim-history integrations, authorization
and PHI controls, operational review queues, appeals and reversals, monitoring,
and plan-owner approval of compiled rules. The current public interface does not
accept and compile an arbitrary uploaded brochure end to end.

That boundary is deliberate: the repository demonstrates the difficult core—
turning reviewed benefit language into reproducible dollars and evidence—without
pretending that missing production inputs already exist.

## Repository map

| Path | Contents |
|---|---|
| `src/arbiter/core/` | Typed claim models, evaluators, accumulators, and engine |
| `src/arbiter/compiler/` | Document segmentation, prompting, span checks, and scoring |
| `src/arbiter/demo/` | Demo service and browser interface |
| `data/specs/` | Human-reviewed, evidence-bearing plan specifications |
| `data/cases/` | Frozen benchmark schedule, case oracle, and correction ledger |
| `data/documents/` | Hash-bound source brochures and source manifest |
| `tests/` | Engine, oracle, compiler, property, and demo verification |
| `docs/` | Architecture decisions and staged review records |

The complete design rationale is in [02-ARCHITECTURE.md](02-ARCHITECTURE.md).
