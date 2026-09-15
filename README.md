# ARBITER

**An evidence-gated decision layer for dental claims.**

ARBITER turns a reviewed benefit specification and a claim into a deterministic
result, a line-by-line effect trace, and the exact plan language supporting each
applied rule. When the supplied evidence cannot determine an answer, it shows a
scoped review state rather than inventing a payment.

The opening demo uses the same two-crown treatment plan under two public dental
plans. Delta pays **$400**; MetLife pays **$700**. Every dollar is linked to the
rule that caused it.

## Run the claim-review demo

```powershell
python -m pip install -e .
python scripts/run_demo.py
```

Open <http://127.0.0.1:8787> in a browser. The opening case, **B01**, shows
the same crown sequence under both plans: Delta's annual maximum exhausts
mid-claim while MetLife's does not. The case picker also includes ordinary,
adversarial, and scoped-abstention examples.

The demo uses the real deterministic engine and a frozen 30-case oracle. Its
AI-audit section shows a six-pass Gemini 3.5 Flash extraction benchmark, where
the model made four unsafe assertions rather than abstaining. The public demo is
reproducible: it does not need an API key or make a live model call.

## Design

- **AI assists extraction; it never decides payment.** A reviewed typed spec is
  the only input to the money path.
- **The money path is deterministic.** Integer cents, explicit stage order,
  canonical line ordering, and pooled accumulators make outcomes replayable.
- **Evidence is first-class.** Every applied provision carries an exact source
  quote; uncertainty is classified and scoped to only the affected claim line.
- **This is a demonstrator, not a carrier payment guarantee.** It uses public
  plans and a frozen benchmark allowance rather than network fee schedules,
  eligibility feeds, clinical policy, or production claim history.

## Verify

```powershell
python -m pytest tests/test_demo.py tests/test_b01.py -q
python -m ruff check src/arbiter/demo tests/test_demo.py
```

The model-assisted brochure compiler under `src/arbiter/compiler/` remains
separate from the adjudication engine: unsupported or ambiguous source material
must remain visible as uncertainty, never become an invented benefit rule.
