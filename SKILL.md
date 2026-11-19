---
name: weekly-skill
description: Audits source-grounded experimental plans for operational feasibility and version differences using actual case/PDF/SOP/resource/price/booking evidence. Use for 实验方案可行性评估, versioned_feasibility_review, three candidate plans, seven-axis checks (assumptions/variables, controls, equipment/materials, time/cost, parameters, risks/exceptions, ethics/safety), finite-domain arithmetic, evidence locators, uncertainty and change records; not for experiment execution or generic literature review.
---

# Versioned experimental-plan feasibility review

Produce a decision-ready, independently checkable review, not a generic proposal. Only case evidence can establish case facts. Read [review_protocol.md](references/review_protocol.md) before substantive judgments, [tool_interfaces.md](references/tool_interfaces.md) before using a helper, and [examples.md](examples.md) only for the interface pattern. No example is an official case answer.

## Runtime contract

1. Read `/input/case.json`, the actual `task.md` at its provided path, its real `output_contract`, all case-declared public rubrics/thresholds, and cited materials. Inspect `/input/environment/resources.yaml` or the actual resource manifest when present; use the named installed tools. Original documents take precedence over labels.
2. Write under `/app/work`; deliver under `/app/output/result.json`. Preserve the real `case_id` and every original output-contract field, name, level and type. Do not impose a template from this Skill on a different case schema. Include actual scientific results, sources, run status, uncertainties, and change records. Preserve honest partial output with its limits.
3. Locate the installed scripts at `/skills/weekly-skill/scripts` (or resolve them relative to this Skill file if installed elsewhere). Python 3.9+ standard library is sufficient for the helpers. No network, personal file, hidden answer, manuscript dataset, or undeclared dependency is required.
4. Maximum resources are 64 model requests, 900 seconds, and 16,384 tokens per response including reasoning. Target roughly 8–12 focused model requests, leaving a small amount for validation/recovery; never use dozens of raw repeated template mutations. Record real wall-clock epoch (`time.time()` with timestamps) for elapsed time across separate CLI calls; a monotonic clock is valid within its actual process, but process-relative values from separate calls must never be subtracted or substituted for total agent wall time. Target finishing substantive work by 780 seconds when feasible, with the remainder for verification and a truthful partial save. If a stage is not complete, preserve its actual limits rather than sacrificing the seven axes, an entire plan, or fabricated coverage to an internal target. Do not claim timing/model-request compliance without the real execution record; helper timings are not the whole run.

## 1. Inventory and save a recovery point

Create `/app/work` and `/app/output`. Resolve the actual task path without overwriting any input, then try the **optional accelerated workspace**; it performs the inspection itself and writes an initial partial result only for an explicitly compatible literal contract:

```bash
TASK=/input/task.md
[ -f "$TASK" ] || TASK=task.md
[ -f "$TASK" ] || TASK=/app/task.md
python3 /skills/weekly-skill/scripts/review_workspace.py prepare \
  --case /input/case.json --task "$TASK" --out /app/work \
  --resource-root /input --initial-result /app/output/result.json
```

If the printed `supported` is true, edit `/app/work/review_workspace.json` rather than writing a case-specific result generator or another scaffolding framework. Fill actual `judgment`, `observed_facts`, `disposition`, evidence and open gates for each row, then a concise `overall_decision`. Never leave a `judgment` blank merely to satisfy the schema: pending rows have actual pending state and are not `undetermined` scientific conclusions.

For incompatible contracts or unsupported plan structures, use the ordinary workflow instead: run `inspect_case.py --case /input/case.json --task "$TASK" --output /app/work/case_inspection.json` and follow the remaining instructions. The workspace does not infer useful alternate schemas or fabricate plan/check identifiers. For compatible cases, save computational/atomic updates into the same workspace instead of rebuilding its boilerplate. Run `review_workspace.py finalize --case /input/case.json --work /app/work --output /app/output/result.json --validate --allow-partial` after evidence, calculations and summary are complete; use `--evidence /app/output/evidence_map.json` when a supplementary map is actually provided. Any failed gate leaves an honest partial artifact, and unsupported/invalid schemas do not get a fabricated completion.

Always read the resolved task file. If none exists, report that limitation instead of assuming its contents.

Read the targeted inspection fields (including output-contract occurrences, canonical root `case_id`, candidate-list hints, source registry and missing references) with bounded JSON queries; do not dump the entire schema outline. Re-read the actual JSON at identified paths for candidate versions, all case-declared public rubrics/hard thresholds, finite parameter domains, resource/price/booking contracts and source files. An inferred structural role is not a scientific interpretation. Use the raw input to settle meaning.

Immediately write an **actual, clearly partial** `result.json` using the original contract, with the actual `case_id`, null/empty values of the expected types, accurate `partial` status, sources currently identified, pending axes/versions, and an empty or initial change record. Do not use fabricated identifiers or completed findings as placeholders. If a strict/closed schema cannot accommodate fields, keep supplemental notes in `/app/work` until they can be delivered through an allowed field or evidence map. If input cannot be parsed at all, report a real failure rather than purporting to preserve an unreadable contract.

Record a real start epoch (or monotonic timestamp) in `/app/work`. Before each macro-stage—PDF extraction, all three scientific ledgers, arithmetic, comparison, verification—check elapsed time and only launch a new optional expansion when it fits the reserve. An 8–12 request plan ordinarily means one inspection/extraction stage, focused source review, one compact ledger per candidate, one combined arithmetic stage per domain family, and one compact final comparison/validation. Do not rebuild the full answer after every minor edit; retain source-linked components and their actual file versions. Save each completed candidate atomically to the same result file while retaining its version; never let v2/v3 overwrite v1. Preserve model-authored drafts, helper outputs and validation reports under `/app/work`.

## 2. Extract only the evidence that exists

- Use `sha256:` source IDs from the inspection, which hashes original bytes. Register additional actual read files only with a true freshly computed hash.
- The case's explicit citation contract controls scenario namespaces. Otherwise, for organizer scenario facts (prices, staffing, inventory, booking, candidate parameters and version changes), cite the **actual case-file** SHA-256 plus an exact case JSON Pointer. If a case explicitly requires a declared scenario/contract source ID, preserve that exact ID with an exact in-scope case JSON Pointer. The validator recognizes only aliases declared at `scenario_scope.source_id`, `scenario_id`/`scenario_source_id` under that scope, or `contract_id` under `resource_price_booking_contracts`, with their declared scope restrictions; it re-binds them to the actual current case-file hash. An unapproved `scenario:`, `case:`, `derived:`, bare alias without an exact pointer, cross-root pointer, or invented namespace remains an error. Do not globally replace PDF IDs, file-structure provenance, independent derived-text IDs or paper facts with a scenario alias. Keep meaningful non-source aliases in separate metadata fields; support every observation/gate with the field that actually establishes it.
- Read the actual PDFs/documents, including tables and finite-domain/rubric content. With the declared PDF text tool, retain page boundaries. For a scanned or failed page, follow the resource manifest's OCR route; record the real tool/version and pages covered or failed. Render/re-read critical numeric tables where extraction is uncertain.
- Use cited plan/rubric/evidence locators to build a **focused page set**: always inspect every source-bound critical method/parameter, control, limitation, confusion/conflict and finite-domain item at its exact original page. If no locators are given, inspect structure/table of contents and method sections, then targeted referenced terms/pages. Full-document extraction is not all-page semantic proof; do not re-render or re-read the entire PDF repeatedly for unrelated plots/listings. Record pages extracted, pages semantically reviewed, render/OCR boundaries and unread or undigitized portions separately. Do not infer broad coverage from file names, a page count or an abstract.
- Record short, contiguous exact quotes and physical PDF page numbers (starting at 1), section/table/row, or RFC 6901 JSON Pointers. Include bibliography markers when inside the selected span, or choose a shorter intact span that excludes them; never silently delete numbers, units, uncertainty signs or references to force a match. Cite the original scientific source, not merely its filename or your summary. Never infer a missing page or fabricate page text from a label.
- When a source or evidence map references generated extraction text/logs, refresh the registry after extraction **without changing the original resource root**:
  ```bash
  python3 /skills/weekly-skill/scripts/inspect_case.py \
    --case /input/case.json --task "$TASK" \
    --output /app/work/case_inspection.json \
    --additional-resource-root /app/work
  ```
  `evidence.source_id` identifies the original paper; `provided_extraction.source_id` (when supplied) identifies the derived text file's own bytes, and `derived_from_source_id` records its parent. Use exact actual paths and hashes, not invented relationships. Run this extra registration only when derived files are referenced; otherwise it is unnecessary work.
- Reuse extracted evidence by stable IDs instead of repeating entire papers. Keep file contents, derived calculations, reviewer proposals, and external methodological guidance separate. Do not require network access or manufacture an unavailable citation.

## 3. Build one independent evidence ledger per candidate

Read the same review protocol for all candidates and apply all seven axes plus every actual public rubric/hard requirement. Each check must be addressable by the parent `plan_id`/`plan_version` and a real `check_id`/rubric ID with axis; preserve identifiers required by the actual output contract. Retain scope/applicability, observed facts, judgment, precise evidence locator(s), calculation ID when used, uncertainty, and an actionable disposition.

Do **not** copy public rubric requirements, thresholds or whole case sections into the result merely to fill fields: refer to the existing criterion and spend the text on the actual observation and why it passes or fails. Store each check once with an axis, not separate but duplicative seven-axis and rubric tables. A short coverage summary can derive/display the seven-axis set without replicating scientific findings. Share a named gate or source entry for genuinely identical missing items/actions, with point-of-use scope. Never repeat a generic “confirm more” disposition across many checks.

Explicitly cover assumptions/variables, controls, equipment/materials/samples, time/cost, parameter domain, risks/exceptions, ethics/safety. Use `missing` for absent necessary material, `undetermined` for inadequate evidence, `conflict` for unresolved contradictions, and `not_applicable` only with supporting facts. Positive evidence is needed for `met`; absence alone is not proof of either feasibility or physical impossibility.

Before saving each row, resolve **current plan pointer → applicable rubric/threshold → candidate's actual statement or scenario input → external source/finite-domain computation → judgment → this plan's disposition**. Keep `paper_method`, `candidate_commitment`, `scenario_input` and `derived_value` distinct in allowed typed fields, or explicitly label them within `observed_facts`; do not add unsupported fields to a closed contract. A paper's method, an `evidence_id`, a source-fact registry, or similarity to another version cannot prove that the candidate already commits to that exact method. For example, “dried” does not establish “flame-dried”. A written-method `met` needs the current candidate's positive statement for that precise facet; a useful available alternative does not erase its missing commitment. Never invert this into proof that the unmentioned operation was not performed. Do not report an ambiguous `met` where the real conclusion applies to the cited paper but the candidate's method is still undetermined.

Dispositions inherit the current plan pointer even when the wording omits its ID. Except in an explicitly scoped comparison/change record, never copy another candidate's ID or gate into a required action or recheck. Repeated scientific constraints may share concise text only after independently verifying each plan, and must retain their own point-of-use evidence and actions. The linter warns about foreign plan IDs in dispositions; it does not prove semantic correctness or authorize find/replace rewriting.

Reuse actual case calculation IDs exactly. A newly introduced local calculation name needs an adjacent definition, linked source/formula/unit/value and a stable artifact locator; use the same name consistently in observations, rechecks and uncertainty. Prefer an existing calculation plus a clearly named per-plan margin over undefined neighboring IDs and unlabelled formula aliases.

Bind each statement to the correct candidate. Check technical capability, qualified unallocated inventory, capacity/calendar and booking separately. Split equipment occupancy, person-hours, elapsed waiting and assay turnaround. Record applicable approval scope/version/conditions rather than assuming a generic approval. Give a concrete missing item, trigger/next gate, alternative and recheck requirement—not a vague request to “confirm more”.

Do not impose animal-study guidance on materials work, a universal control design, arbitrary statistical power, risk scores, safety thresholds, default prices or expert approval durations. Use only supplied thresholds and appropriately scoped guidance.

## 4. Recompute explicit arithmetic and schedules

Where the input contains finite domains or explicit formulas, adapt **actual** sourced facts to the documented helper input. This is a semantic step: never let a script infer units, domains, ranking objectives or thresholds.

```bash
python3 /skills/weekly-skill/scripts/enumerate_constraints.py \
  /app/work/finite_domains.json --output /app/work/constraint_review.json \
  --audit /app/work/constraint_audit.jsonl --max-combinations 100000
```

Read both completeness and outcomes. A complete exhaustive result with no satisfying assignment is infeasible **only for the declared hard constraints**. Unknown constraints, missing domains, expression errors or partial enumeration cannot prove infeasibility. Unconstrained candidates and soft-constraint satisfaction are not overall scientific feasibility. Preserve constraint/source IDs and representative witness assignments. The helper exits 0 for a completed run, 3 for a recoverable partial result, 1 for a failed run, and 2 for argument errors; a nonzero exit must never make you discard an honest saved partial result or guess its missing conclusions.

For actual finish-to-start dependency data, run:

```bash
python3 /skills/weekly-skill/scripts/schedule_baseline.py \
  /app/work/schedule.json --output /app/work/schedule_result.json
```

Treat CPM makespan as a network baseline, not a promise of a bookable or resource-feasible plan. Check overload intervals, calendars, lead times, releases and booking constraints separately. Retain formulas, input values, unit conversion, rounding and output type. Never coerce missing data to zero or use approximate arithmetic silently.

## 5. Compare versions without inventing an optimum

For stable IDs, compare domain/unit/source changes, every axis's judgment, arithmetic, critical/overloaded steps, missing items, and witness assignments. Identify the specific changed constraint/source that explains a decision reversal. Report trade-offs and deltas, not just rankings.

Only filter by actual hard requirements and optimize by explicitly supplied objectives and tie-breaks. Do not invent weights or choose the longest/most favorable-looking version. Any proposed revision is labelled `observed → proposed`, with basis, affected version, validation/authorization required and recomputation. This is not an approval or a replacement observed fact.

## 6. Deliver and independently verify

Populate the real output contract with actual findings and actionable conditions. Put status, sources, uncertainty and change records in their actual fields. If the contract forbids extra fields, link supplementary `/app/output/evidence_map.json` through actual result JSON Pointers. Include editable artifacts only if requested; if Office/slide/diagram outputs are required, give real rendered PDF/PNG previews, not a claimed rendering.

Before finishing, re-read the saved result and run:

```bash
python3 /skills/weekly-skill/scripts/validate_result.py \
  --case /input/case.json --result /app/output/result.json \
  --inspection /app/work/case_inspection.json --summary \
  > /app/work/validation-report.json
# Add --evidence /app/output/evidence_map.json to this command when a map was created.
python3 /skills/weekly-skill/scripts/package_check.py /skills/weekly-skill
```

Read the saved validator report and all errors; use `warnings_by_code` coverage instead of rereading hundreds of duplicate warnings. Summarize diagnostics by cause and repair only the affected fields/artifacts. Rerun the inspection after a referenced derived file changes, so its hash cannot go stale. Repair actual errors, then rerun until the result is mechanically valid or an honest limitation is explicitly retained. Use the default full JSON report if detailed per-evidence locations are needed; compact summaries do not hide errors.

Fix reported contract, hash, pointer and citation errors against the actual evidence. For critical quotes, read the declared **physical page** with the actual PDF tool, not only the global registry or a different extraction. Prefer a short intact span over a hyphenated/line-broken fragment; record typesetting-only and unrendered/PDF extraction boundaries explicitly rather than enlarging fuzzy matching until text passes.

A validator pass covers mechanics, not scientific completeness. Before delivery, manually confirm:
- every applicable rubric/threshold and all seven axes for each candidate, without copying or inferring applicability across versions;
- each observation's exact actor: candidate actual text, scenario input, paper method, explicit inheritance, or reviewer proposal;
- every disposition's owner, applicability and affected version; only explicit change/compare records may point to another candidate;
- all declared finite combinations, witnesses, formulas, units, rounding and locally defined calculation labels, with structured arithmetic results reconciled against narrative demand/capacity and margins/signs;
- separate declared-constraint feasibility, actual measured performance/document evidence, booking availability, and approval/start gates, without overwriting one with another;
- exact source-decision commitments rather than generic future upgrades, retained unknowns/conflicts, and complete source-linked version changes.

In `overall_decision` or an existing per-plan decision field, preserve the actual decision vocabulary and make every candidate's scientific, resource/date and start-gate outcome independently recognizable, including the actual plan ID. Do not invent a per-plan field when the contract forbids it; use the allowed global summary/work artifact instead. Preserve reporting errors and unresolved gaps when relevant; do not erase them for a green status.

On a late or partial failure, retain the most complete verified result, affected source/pages/versions, failed tool/stage, uncovered checks, specific user action and truthful `partial`/`failed`/`stuck` status. Do not claim a measured improvement over the baseline, a fabricated review score, official case execution, or approval. Return a concise summary and the actual artifact paths; the final decision-ready content belongs in the files.
