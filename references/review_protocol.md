# Source-grounded feasibility review protocol

## Scope and authority

Read the actual `case.json`, `task.md`, named scientific sources, artifacts, and any organizer-supplied rubrics or contracts. Their actual identifiers, schemas, thresholds, finite domains, and output fields govern. This protocol is a method, not an alternative answer key. Do not invent 16 rubrics, a domain, a missing file, or a vendor/ethics fact.

Each case has independently versioned candidate plans. Keep `case_id`, the real `plan_id`/`plan_version`, and source references together. Array position is only an ordinal, never a replacement for a version identifier. Do not pool evidence or variables across candidates.

Distinguish these kinds of statement:

- **Case evidence:** actual required constraints, prices, booking/resource scenarios, approval status, and requested outputs.
- **Scientific evidence:** original papers, manuals, SOPs, and records actually available in the input.
- **Method guidance:** the external references below; useful for structuring review, not proof of a case-specific fact.
- **Inference/proposal:** an explicitly labelled calculation or conditional recommendation, not an observed fact or approval.

Organizer resource, price, and booking contracts define prospective scenarios. Do not describe them as measured future performance, guaranteed vendor commitments, real laboratory inventories, or approvals unless the actual evidence establishes that stronger claim.

## Judgment model

Map these semantics to the exact vocabulary required by the case. Do not mix them with run state.

- `met`: the requirement is applicable, positive evidence matches its scope/version, and the evidence or recomputation passes.
- `unmet`: an applicable requirement conflicts with sufficient evidence or fails an actual hard threshold.
- `missing`: a required or named file, page, field, or needed fact was not supplied.
- `undetermined`: present evidence is inadequate, ambiguous, unreadable, or not decisive.
- `conflict`: two identified sources disagree; keep both, with precision and version context.
- `not_applicable`: a source-supported condition makes the item inapplicable; silence is not such proof.

`missing` is not `unmet` and never `met`. Failure to find an exception is not evidence of absence. If documentation itself is required, its absence can separately fail that documentation requirement while leaving the underlying physical fact undetermined. Distinguish materials problems from expert uncertainty and from parser/tool failure.

Keep run state separate: `success`, `partial`, `failed`, or `stuck`, subject to the actual contract. `partial` means incomplete coverage or a known processing limitation, not a partially true scientific claim. A failed PDF reader must not turn PDF-supported claims into `met` or `unmet`.

## The seven-axis evidence matrix

For every candidate, explicitly review all seven axes and every actual public rubric/hard requirement in the case. Prefer a stable check ID, source-grounded requirement, scope/applicability, expected threshold, observation, judgment, source locator, calculation ID, uncertainty, and actionable disposition. Cover the row even when it is missing or inapplicable.

1. **Assumptions and variables.** Trace objective → testable proposition → experimental/observational unit → independent/response/confounding variables → measurement and judgment criterion. Separate supplied facts from assumptions requiring validation.
2. **Controls and comparisons.** Ask which alternative explanation or bias each control addresses, and whether it matches the study objective. Check groups, allocation/repeats, batch/operator/time effects and analysis assumptions when applicable. Do not prescribe a universal number or kind of controls.
3. **Equipment, materials, and samples.** Bind steps to model, range, precision, accessories, calibration, sample origin/amount/condition, material grade/specification. Separate technical capability, qualified unallocated inventory, calendar capacity, and reservation availability. Resources may be `available`, `outsourcable`, `purchase_required`, `unavailable`, or `unknown`; one axis cannot prove another.
4. **Time and cost.** Split equipment occupancy, person-hours, elapsed waiting, and assay turnaround. Preserve parallel dependencies and avoid adding person-hours to elapsed time. Show actual formula, inputs, units, arithmetic trace, currency, rounding and uncertainties for every total.
5. **Parameter domains.** Record names, values, units, bounds, finite domains, tolerances and their sources. A literature parameter does not establish device capability. Enumerate declared combinations; distinguish impossible, undetermined, and unevaluated combinations.
6. **Risks and exceptions.** Connect step, failure mode, observable trigger, immediate preservation/pause, mitigation, alternative validation, stop condition, escalation role and recheck. Keep controls and residual uncertainty distinct. Do not invent probability, S/O/D, RPN, or acceptable risk levels.
7. **Ethics and safety.** Identify the actual animals, human-derived material, personal data, organisms, and hazardous agents only from supplied material. Check scope, version, validity, decision, authority, required conditions and protocol changes. Missing approval evidence is not evidence of absence or exemption. External guidelines cannot issue an approval.

Use domain-specific guidance only when its actual applicability conditions hold. ARRIVE 2.0 is relevant to animal research, not every chemistry/materials study; its reporting guidance is not an ethics decision. S/O/D ratings require an actually supplied scale. Do not apply a generic sex, randomization, power, humane-endpoint, or retention threshold to unrelated work.

## Evidence and provenance

Use a `sha256:<hex>` source ID computed from actual file bytes. Per judgment retain file/source ID, exact plan reference, page (physical page 1-based), section/table/row or RFC 6901 JSON Pointer as appropriate, and a short verbatim quote where available. Equal repeated text needs surrounding context or a more precise locator. Never invent page, DOI, quotation, authorization ID, or material contents.

Maintain a source registry and actual extraction log: tool/version/arguments, start/end or timestamps where captured, exit status, output paths, covered/failed pages, and error. An OCR pass is a separate extraction activity. Read critical tables and numbers from rendered pages when reliable extraction is uncertain; a cached text layer is not automatically correct.

Do not add fields to a closed output contract. Put supplementary source details in `/app/output/evidence_map.json` and link its entries to actual result JSON Pointers when necessary. Runtime evidence may supplement, never replace, original fields.

## Arithmetic and scheduling

Only equations supported by the actual case, source, or a correctly scoped declared derivation are admitted. Every derived number keeps its inputs and source references. Prefer exact `Decimal` strings; explicitly record unit conversions and any rounding. Never silently truncate, round a repeating division, or treat `NaN`/missing as zero.

Use `scripts/enumerate_constraints.py` after a human/agent adapter has mapped actual facts to its documented format. Do not let the script generate missing domains, dose limits, objective weights, or conversion factors. Its feasible combinations concern only declared hard constraints. If no explicit objective/tie-break exists, preserve alternatives rather than inventing a score or winner.

For sample arithmetic, count only the actual declared groups, experimental units, repeats, collection points, losses and shared controls; never assume a universal multiplication formula. Stock shortage is `max(0, demand - qualified_unallocated_stock)` only when those quantities are explicit and compatible. For explicit MOQ `m`, pack multiple `b`, fixed unit price `p` and fixed charge `f`, order quantity may be `b*max(ceil(shortage/b),ceil(m/b))` when shortage is positive, then cost is `q*p+f`; do not apply this to unstated tiered pricing, tax or contingencies.

Use `scripts/schedule_baseline.py` only for actual finish-to-start task dependencies and explicit durations. Standard CPM supplies a network baseline with implicit unlimited-resource assumptions; resource overload intervals are a separate check, not proof that a feasible resource-constrained schedule exists. Do not invent release dates, lags, working calendars, time zones, transportation components, parallelism, or booking slack. When such inputs matter but are missing, mark the relevant result undetermined.

## Version deltas, dispositions, and change records

Compare candidates by stable IDs. Report observed versus changed parameters, domain/unit/source changes, changes in each axis, added/removed satisfied or failed checks, unresolved items, resource overloads, formulas/results, and witness combinations explaining a decision change. Attribute each difference to a constraint or source rather than merely observing that two answers differ.

Where objective(s) and priority/tie-break are explicit, filter hard constraints before applying them. Otherwise report trade-offs, not a fabricated weighted optimum. Proposed changes require a clear `observed → proposed` record, source/derivation, scope, required validation/authorization, and identity of the original candidate. A counterfactual passing a calculation is not an approved plan.

Every materially adverse or unknown row must lead to a useful disposition: exact missing field/artifact and source to consult; responsible role to confirm when known; before-start or next-stage gate; permitted fallback; required recheck. Do not default to vague “further confirmation”. Never invent an expert, completion date or approval duration.

## Research basis and boundaries

These sources support the review method; they do not supply hidden-case numerical facts:

- [NASA: good requirements](https://www.nasa.gov/reference/appendix-c-how-to-write-a-good-requirement/) and [requirements verification matrix](https://www.nasa.gov/reference/appendix-d-requirements-verification-matrix/): atomic requirements, tolerances/criteria, assumptions, identifiers, provenance and bidirectional verification.
- [NIH: rigor and reproducibility](https://grants.nih.gov/policy-and-compliance/policy-topics/reproducibility/guidance) and [NIST: blocking](https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm): assess premises and account for nuisance variables rather than blindly adding controls.
- [NIST: variables and ranges](https://www.itl.nist.gov/div898/handbook/pri/section3/pri32.htm): important variables/ranges and impossible combinations require attention.
- [ARRIVE 2.0](https://arriveguidelines.org/arrive-guidelines) and [study design](https://arriveguidelines.org/arrive-guidelines/study-design): animal-study planning/reporting and objective-dependent controls, not universal ethics authorization.
- [IEC 60812:2018](https://webstore.iec.ch/en/publication/26359): structured failure-mode analysis; rankings alone do not prove safety or acceptability.
- [GAO schedule assessment guide](https://www.gao.gov/products/gao-16-89g) and [GAO cost guide](https://www.gao.gov/assets/gao-20-195g.pdf): documented calendars, resource constraints, assumptions, calculations and traceable estimates.
- [W3C PROV-DM](https://www.w3.org/TR/prov-dm/), [W3C Web Annotation](https://www.w3.org/TR/annotation-model/), [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901): source derivation, revisions, precise text selectors and JSON Pointers.
- [Python Decimal](https://docs.python.org/3/library/decimal.html): explicit precision, rounding and exceptional arithmetic conditions.

This is a source-scoped feasibility review. It does not replace execution, experimental validation, actual supplier confirmation, statistical design specific to the study, institutional safety review, or an ethics decision.
