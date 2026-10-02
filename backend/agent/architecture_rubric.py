from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# Reviewer explanations must retain the repair context through generation.
MAX_REVIEW_REASON_CHARS = 2_000

STAGED_REVIEW_STANDARD = (
    "Evaluate the requested explanation or design at its selected depth. Block a "
    "demonstrated contradiction, a missing requested behavior, an unusable main "
    "flow, or a violated required control. Optional implementation detail, naming "
    "preferences, and a different valid decomposition are not blockers. State the "
    "specific broken behavior when rejecting; omission alone does not prove a "
    "runtime failure. Compatible internal operations may share an owner; do not "
    "expand the graph just to illustrate each checklist item."
)

_EXECUTION_OUTPUT_DELIVERY_REQUIREMENT = (
    "When a declared consumer needs execution output to continue work or answer, "
    "trace that output across the complete route to the consumer. Every "
    "intermediary contract on that output route must carry the actual output. "
    "Name the actual needed output data in each forwarding connection. "
    "Generic 'success', 'failure', or 'outcome' does not "
    "imply a result payload. For example, in an agent loop the planner must receive "
    "tool observations or result content, with execution status as accompanying "
    "data. A commit/status-only contract is valid when its consumer needs only "
    "commit information. "
    "A validation verdict, acknowledgment, or commit status alone is insufficient. "
    "Direct delivery, explicit forwarding, or declared persistence with a consumer "
    "read can satisfy output delivery. Preserve this output route during scoped "
    "edits and repairs."
)

_ACTION_APPROVAL_DELIVERY_REQUIREMENT = (
    "For each declared policy or approval gate, trace its final allow, reject, or "
    "halt decision to the owner that dispatches the action or to the executor "
    "before the effect. Every intermediary must forward that decision with its "
    "action identity and scope. A preliminary validation verdict or an invocation "
    "label saying 'approved' does not establish delivery of the final approval. "
    "Rejected or halted actions must reach a bounded observable outcome without "
    "execution. Direct delivery, explicit forwarding, authoritative persisted "
    "decision reads, or declared same-owner enforcement can satisfy this path; "
    "do not require duplicate gates or services."
)

RUBRIC_CRITERIA = {
    "domain_specificity": (
        "components",
        "Use component names and boundaries specific to the requested system.",
    ),
    "objective_fidelity": (
        "components",
        "Depict the requested subject and make its goal and constraints visible in component responsibilities. A named educational, research, or comparison subject establishes diagram scope without an invented business use case; represent its relevant mechanisms or contrasting paths. A broad teaching request needs a map of the requested subject or lifecycle. A single assumed product cannot replace that subject; examples must remain subordinate to its breadth. For an applied system design, establish the user's business domain, goal, and workflow from the request or accepted context. Retrieved examples cannot choose the user's domain or goal. Assumptions may fill implementation details but cannot invent a missing business goal or workflow. The diagram request is already admitted; do not ask whether a diagram is wanted. For new designs, select the initiating primary runtime actor as the root; centrality of an AI service does not determine the root. Primary membership selects components for the main walkthrough. Every primary member must be naturally reachable outward from that root using directed runtime, control, feedback, or deployment contracts, which may pass through non-primary supporting components. Walkthrough order does not establish causal execution order or satisfy required runtime and control behavior. Keep independent ingress and supporting components in the design; mark them non-primary when they do not belong in the walkthrough. Do not invent reverse or control edges to repair an unsuitable root or primary membership. Determine initiation from declared behavior. A component that pulls or requests data may initiate an outward request with a return response; inbound responses and independent inputs do not disqualify that root. Require contracts consistent with the declared responsibilities, without inventing requests for push-only sources. At the component stage, assess whether declared responsibilities and assumptions support a feasible directed path; connections are authored in the next stage. Missing edges or absent peer names in responsibilities are not component defects. Identify a specific incompatible responsibility when rejecting root or primary membership; do not demand connection-stage evidence here. Scoped edits preserve the accepted root and primary membership outside the authorized write set. Instructions to explain, cite or ground the response in sources, or draw its flow govern the response; include those capabilities in the designed runtime only when explicitly requested as system features.",
    ),
    "runtime_completeness": (
        "connections",
        "Connect observations and accepted processing to measurable outcomes. Require decisions and actions only when accepted component responsibilities own them. For observation-only designs, a durable telemetry sink is a complete outcome. For every requested behavior, identify the owner and its actual trigger or change-input contract. A read, response, or incidental reachability does not invoke an unrelated write or adjustment.",
    ),
    "safe_action_boundary": (
        "connections",
        "Put policy, exact-action approval, audit, and recovery controls on external mutations. "
        + _ACTION_APPROVAL_DELIVERY_REQUIREMENT,
    ),
    "edge_semantics": (
        "connections",
        "Give each directed edge one distinct necessary contract, consolidate duplicate interactions, and keep reverse or parallel contracts compatible. Classify each interaction by its actual behavior; feedback and deployment contracts cannot substitute for required runtime or control interactions. Each read or request that expects returned data needs its matching payload from the authoritative owner back to the requester. An unrelated reverse verdict or acknowledgment does not supply that payload. "
        + _EXECUTION_OUTPUT_DELIVERY_REQUIREMENT,
    ),
    "assumption_hygiene": (
        "composition",
        "Record material unknowns as assumptions instead of facts.",
    ),
    "selected_depth": (
        "components",
        "Match component ownership and operational detail to the selected UI depth without importing deeper criteria.",
    ),
    "novice_clarity": (
        "composition",
        "Use authored groups and sequence to make the entry, main path, controls, and outcomes easy to locate in the screenshot.",
    ),
    "logical_flow": (
        "connections",
        "Start the primary operational path at its real trigger and follow directed contracts to an observable outcome. Require the runtime and control paths needed for invocation, authorization, and execution; walkthrough reachability alone does not establish those paths.",
    ),
    "succinctness": (
        "components",
        "Keep node labels and responsibilities concise and distinct.",
    ),
    "mece_scope": (
        "components",
        "Give each material responsibility one clear owner, remove needless duplicates, and exclude mechanics used to author this response unless explicitly requested as runtime features of the subject system.",
    ),
    "authored_composition": (
        "composition",
        "Use title, groups, and one primary sequence to expose the operational spine while secondary paths remain subordinate.",
    ),
    "brief_coverage": (
        "components",
        "Give every requested responsibility of the subject system a component owner; response instructions do not create runtime responsibilities.",
    ),
    "branch_completion": (
        "connections",
        "Route normal, alternate, rejection, and fallback branches to a rejoin or observable outcome.",
    ),
    "independent_risk_coverage": (
        "components",
        "Give each material independently reviewed risk a named responsibility owner.",
    ),
    "gate_preserving_reuse": (
        "connections",
        "Preserve validation, authorization, policy, and approval gates required by the request, accepted responsibilities, or applicable maturity criteria. Cache, memory, replay, retry, and shortcut paths cannot bypass those gates: store accepted post-gate artifacts or rejoin the required gate with its identity and version scope. Prototype memory or reuse alone does not require a new approval or version gate.",
    ),
    "topology_enforced_guarantees": (
        "connections",
        "Express each guarantee with directed components and edges. Labels and assumptions alone are not proof.",
    ),
    "controlled_external_effects": (
        "connections",
        "Trace each material mutation through authoritative observation, typed proposal, policy, exact-action approval, execution, authoritative target, reconciled outcome, and canonical audit state.",
    ),
    "race_and_ambiguity_safety": (
        "connections",
        "Converge alternative delivery paths before action, deduplicate atomically at the durable writer, reconcile timeout-after-commit by the same key, and send compensation through the normal controls.",
    ),
    "canonical_state_and_trust": (
        "connections",
        "Keep lifecycle authority out of caches and projections. Validate model actions deterministically and connect material claims to provenance and audit evidence.",
    ),
    "controlled_learning_and_release": (
        "connections",
        "Route feedback through versioned evidence, offline evaluation, reviewed immutable release, canary, separate promotion, and separate rollback before live changes.",
    ),
    "safe_factual_failure": (
        "connections",
        "End failed factual retrieval in clarification or abstention, bound validation retries, and scope caches by identity, version, provenance, invalidation, and revalidation.",
    ),
    "pre_effect_durability_and_freshness": (
        "connections",
        "Reserve a stable operation identity durably before a retryable effect, then revalidate authorization, policy, freshness, and fencing before execution.",
    ),
    "complete_reconciliation": (
        "connections",
        "Branch status read-back into COMMITTED, NOT_FOUND with same-key retry under valid authorization, and bounded STILL_UNKNOWN escalation. Route late anomalies to correlated, bounded compensation.",
    ),
    "complete_trust_and_release_scope": (
        "connections",
        "Keep retrieved bytes untrusted, verify material claim entailment, use access and release-complete cache keys, audit every terminal branch, curate hostile traces, and draw separate promotion and rollback edges.",
    ),
    "state_order_integrity": (
        "connections",
        "Represent required order with separate responsibilities and transitions. Split lookup/write, reserve/send, validate/deliver, and promote/rollback phases when order matters.",
    ),
    "streaming_integrity": (
        "connections",
        "For continuous streams, define bounded backpressure, ordering or event-time rules, replay and deduplication ownership, late-data handling, and compatible schema evolution.",
    ),
}

RUBRIC_CODES = tuple(RUBRIC_CRITERIA)
RUBRIC_CODE_OWNERS = {
    code: owner for code, (owner, _requirement) in RUBRIC_CRITERIA.items()
}

# Screenshot readability is useful reviewer guidance, but it has no typed,
# server-checkable closure rule. Keep its wire code stable without allowing a
# subjective preference to withhold an otherwise valid graph.
ADVISORY_RUBRIC_CODES = frozenset({"novice_clarity"})
PROTOTYPE_ADVISORY_RUBRIC_CODES = frozenset(
    {
        "logical_flow",
        "authored_composition",
        "branch_completion",
    }
)


def advisory_rubric_codes(resolved_depth: str) -> frozenset[str]:
    """Return criteria that cannot withhold a graph at the selected UI depth."""
    if resolved_depth == "production":
        return ADVISORY_RUBRIC_CODES
    return ADVISORY_RUBRIC_CODES | PROTOTYPE_ADVISORY_RUBRIC_CODES


COMPOSITION_REPAIR_PROFILES = {
    "assumption_hygiene": ("assumptions",),
}


def required_composition_repair_fields(criteria: list[str]) -> list[str]:
    """Return server-owned composition authority required by hard criteria."""
    required = {
        field
        for criterion in criteria
        for field in COMPOSITION_REPAIR_PROFILES.get(criterion, ())
    }
    return [
        field
        for field in ("title", "groups", "sequence", "assumptions")
        if field in required
    ]


TOPOLOGY_PROOF_REQUIREMENTS = {
    "state_effect_reconciliation": (
        "Show a directed witness from durable operation reservation through execution and authoritative read-back to every reconciliation outcome."
    ),
    "authorization_and_compensation": (
        "Show exact-action authorization before execution and route compensation through policy, approval, execution, reconciliation, and audit."
    ),
    "retrieval_and_reuse_trust": (
        "Show untrusted retrieval, claim validation, access and release-scoped reuse, invalidation, and audited terminal outcomes."
    ),
    "audit_and_provenance": (
        "Show provenance and audit paths for material inputs, decisions, actions, and terminal outcomes."
    ),
    "learning_and_release": (
        "Show curated versioned evidence, offline evaluation, reviewed release, canary, promotion, rollback, and recorded outcomes."
    ),
}


# Legacy review still uses the proof protocol above. Staged review checks each
# production obligation once, selected by the accepted system's capabilities.
STAGED_PRODUCTION_REQUIREMENTS = {
    "authorization_and_compensation": (
        "For external mutations, connect authoritative observation, a typed exact-action "
        "proposal, policy and approval, execution, and the authoritative target. Compensation must "
        "use the same policy, approval, execution, reconciliation, and audit controls. "
        "For each external effect executor, trace the exact approved action payload and "
        "stable operation identity from canonical proposal or operation ownership into "
        "execution before the write. A direct or delegated request, an executor pull "
        "with its authoritative reply, or declared same-owner state can supply them; "
        "the executor may reserve the identity durably with canonical state. An "
        "authorization verdict or incidental reachability alone supplies neither "
        "payload nor identity. "
        "Cover compensation explicitly in the existing validation and approval invocation "
        "and response contracts. Shared controls suffice when those contracts cover both "
        "normal and compensation actions; duplicate control paths are unnecessary. "
        "Review normal and compensation behavior separately even when one component "
        "produces both proposals: its normal input does not establish rollback initiation. "
        "For compensation, identify the initiating operator, incident, event, or explicit "
        "autonomous responsibility, and trace the original or applied operation reference "
        "or recovery input to its proposal producer. Direct, delegated, combined, or "
        "declared same-owner internal paths are valid; do not demand duplicate services "
        "or edges or an incoming edge for an explicit autonomous action. "
        "Identify the compensation proposal's producer and follow its direct or delegated "
        "invocation to each shared control. A validator's broad responsibility or another "
        "producer's validation path does not establish that invocation."
    ),
    "state_effect_reconciliation": (
        "Assess each write separately against declared retry, redelivery, competing delivery, "
        "or uncertain-commit recovery. A datastore or committed/rejected reply alone does not "
        "declare retries. Missing implementation detail is advisory unless it contradicts an "
        "explicitly requested guarantee or establishes unsafe behavior. "
        "Accept a declared atomic durable commit of the effect and same-operation deduplication "
        "with safe same-key replay; separate pre-effect reservation and read-back are unnecessary "
        "within that boundary. A key alone proves neither atomicity nor safe replay. "
        "Check-before-write without race protection, or a dedup marker committed separately "
        "before or after the effect, does not establish this guarantee. "
        "Effects outside that atomic boundary require durable identity and safe target-side "
        "idempotency or reconciliation before retry. For uncertain non-idempotent effects, "
        "reserve identity durably before execution and read back authoritative status: COMMITTED "
        "records success, NOT_FOUND permits safe same-key retry, and STILL_UNKNOWN has bounded "
        "escalation. Preserve applicable authorization, policy, freshness, fencing, atomic writer "
        "deduplication across delivery paths, and bounded compensation for late anomalies. "
        "A response contract may describe these outcomes together."
    ),
    "retrieval_and_reuse_trust": (
        "Apply each obligation to the declared retrieval or reuse path, its artifact, "
        "and its consumer. Establish applicability separately for each obligation below; "
        "cite the declared behavior that activates it. A generic retriever or tool mention "
        "does not establish reusable artifacts or a factual-answer dependency. An overview "
        "label does not exempt declared behavior from applicable controls. "
        "A system-level retrieval_or_reuse capability does not mean "
        "every generator performs factual retrieval. Identify the material factual claim "
        "or required factual-retrieval dependency before rejecting missing entailment "
        "validation or retrieval-failure handling; apply this equally to internal and "
        "external sources. Outcome-data reads and reuse for evaluation do not establish "
        "a factual-retrieval dependency for an unrelated creative generator. "
        "For a declared path that consumes retrieved bytes, identify those bytes and their "
        "consumer. Treat retrieved bytes as untrusted. For the identified material factual "
        "claims, validate material factual claim entailment "
        "before delivery or reuse. Failed required factual retrieval must end in "
        "clarification, abstention, or a bounded validated retry. Discard rejected/stale "
        "artifacts on an applicable validation or reuse path. A factual RAG answer activates "
        "claim validation and required-evidence failure handling; a private answer cache "
        "reused across requests activates access and artifact lifecycle controls. "
        "When the candidate explicitly makes example or creative reuse optional, "
        "a missing or rejected result may lead to fresh generation through the same "
        "validation and approval controls. Do not infer optionality or allow unsupported "
        "facts to replace missing evidence. State this outcome in the owning responsibility "
        "or response contract; a separate fallback component or edge is unnecessary. "
        "Before requiring reuse scope or lifecycle controls, identify the declared artifact "
        "reused across requests or releases and its consuming path. A retrieval call alone "
        "does not establish such reuse. For that reuse, scope reuse by access "
        "identity, version, and provenance, including model/prompt/index release when "
        "applicable; name invalidation and revalidation ownership. Shortcuts cannot bypass "
        "these controls."
    ),
    "learning_and_release": (
        "Route feedback through curated versioned evidence, including hostile traces, "
        "offline evaluation, reviewed immutable release, and canary. Keep promotion and "
        "rollback as distinct controlled operations for every serving target receiving a "
        "canary, and record their outcomes. A transition for one target cannot promote "
        "or roll back another target's release."
    ),
    "audit_and_provenance": (
        "Give lifecycle state one authoritative owner; caches and projections cannot own "
        "it. For every producer of model-proposed actions, identify the executable owner "
        "that deterministically validates those proposals' structure and allowed constraints "
        "before approval or execution. A named compatible owner may perform this "
        "deterministic validation internally. Its responsibility or a connection contract "
        "may establish the covered producer, proposal structure and allowed constraints, "
        "and validation before approval or execution. An explicit connection contract "
        "does not need duplicate wording in the owner's responsibility. A shared "
        "validator may cover multiple producers when their responsibilities or contracts "
        "establish that coverage. A vague 'validate' label without an executable owner, "
        "deterministic checks, and pre-execution order is insufficient. Validation of one "
        "producer does not establish validation of another. Typed proposals and human "
        "approval alone do not establish deterministic validation. Retain provenance and "
        "correlated audit evidence for material inputs, decisions, actions, and terminal "
        "outcomes."
    ),
    "streaming_integrity": (
        "Apply when the request or candidate contracts declare continuous or unbounded "
        "delivery. Determine applicability from declared delivery behavior and completion "
        "boundaries. Near-real-time timing, asynchronous transport, generic event ingestion, "
        "or the word 'stream' alone does not establish continuous streaming. Cite the "
        "behavior that makes these controls necessary. For such streams, name ownership "
        "of bounded backpressure, ordering or "
        "event-time rules, replay and deduplication, late-data handling, and schema "
        "compatibility. Component responsibilities or channel contracts may specify "
        "these properties; each property does not need a separate edge."
    ),
}


def staged_review_requirements(
    stage: str,
    maturity: str,
    required_production_guarantees: Sequence[str] = (),
) -> dict[str, str]:
    """Give staged generation and review the same applicable acceptance criteria."""
    if stage not in {"components", "connections"}:
        raise ValueError("stage must be components or connections")
    if maturity not in {"prototype", "production"}:
        raise ValueError("maturity must be prototype or production")
    # Wire rule order is versioned; the production extension begins at index 16.
    excluded = set(advisory_rubric_codes(maturity))
    # The staged production rules below replace overlapping legacy checks.
    excluded.update(RUBRIC_CODES[16:])
    # Staged construction has no independently reviewed upstream risk artifact.
    excluded.add("independent_risk_coverage")
    # Component review establishes control ownership before components freeze;
    # connection review checks the required contracts and transitions.
    excluded.update({"domain_specificity", "succinctness", "selected_depth"})
    requirements = {
        code: requirement
        for code, (owner, requirement) in RUBRIC_CRITERIA.items()
        if owner == stage and code not in excluded
    }
    if stage == "connections":
        if "branch_completion" in requirements:
            requirements["branch_completion"] = (
                "Route each required or declared normal, denial, failure, alternate, "
                "and fallback path to a rejoin or observable outcome. A typed response "
                "carrying the applicable outcomes, or the same executable owner handling "
                "them, can close those paths without a separate component or edge. Do not "
                "require a path for an optional exception that the request and accepted "
                "design do not declare. Block a missing required path or a path that "
                "bypasses a required control."
            )
        requirements["edge_semantics"] = (
            "Require contracts compatible with their source, recipient, payload, and "
            "declared behavior. Block a missing required input or answer return, a "
            "contradictory direction, or a path that bypasses a required control. Follow "
            "the complete declared path: an orchestrator may invoke work directly or "
            "delegate invocation and receive the result through another component. "
            "An unrelated verdict or acknowledgment cannot replace required data. "
            "A redundant intermediate return or duplicate description is advisory only when "
            "an independent declared route already delivers all required output and it "
            "neither changes execution nor violates a required control; identify that concrete "
            "failure when rejecting. Feedback and deployment contracts cannot substitute "
            "for required runtime or control interactions. "
            + _EXECUTION_OUTPUT_DELIVERY_REQUIREMENT
        )
    if stage == "components":
        if maturity == "production":
            requirements["brief_coverage"] += (
                " Before responsibilities freeze, check executable ownership feasibility "
                "for downstream_controls activated by the declared behavior and "
                "responsibilities, including when a capability flag needs correction in "
                "this review. Each applicable control operation needs a compatible "
                "declared owner; storage of evidence alone does not own evaluation or "
                "approval. Compatible operations may share an existing owner; do not "
                "require separate components. Assess ownership only here, not edges, "
                "sequence, or payload proofs. Do not introduce capabilities or features "
                "solely to satisfy conditional guidance. Report all missing or incompatible "
                "owners in this pass, citing the affected component indexes and the "
                "declared behavior that activates each obligation. Respect supplied edit "
                "scope: a finding about frozen baseline responsibilities grants no "
                "authority to change them."
                " Give applicable required production controls executable ownership "
                "before component responsibilities freeze. When this system owns an "
                "update or release of a model, prompt, ranking, or live configuration, "
                "require ownership of curated versioned evidence including hostile "
                "traces, offline evaluation, reviewed immutable release, canary, "
                "promotion, rollback, and recorded outcomes. Compatible controls may "
                "share an existing executable owner. Upstream curation or evaluation "
                "may be supplied by an explicitly declared external dependency with "
                "those responsibilities. A metrics-only monitor, passive artifact "
                "store, or the word 'reviewed' alone does not establish curation or "
                "evaluation ownership. Assess responsibility feasibility at this stage; "
                "do not require edges or transition proof before connections are "
                "authored. Frozen inference without an owned update or release does "
                "not require these learning and release controls. For every producer "
                "of model-proposed actions, require executable ownership of deterministic "
                "validation of proposal structure and allowed constraints before approval "
                "or execution. This applies independently of external_effects and "
                "learning_or_release, including model-selected read-only tools, internal "
                "tools, and code execution. A compatible existing owner may perform "
                "this validation internally. At the component stage, establish ownership "
                "and responsibility feasibility without requiring edges or transition "
                "proof. Answer-only inference without model-proposed actions does not "
                "require this per-action validation."
            )
        requirements["mece_scope"] = (
            "Give each material responsibility a clear executable owner. Block "
            "conflicting material ownership that makes required behavior or controls "
            "ambiguous. Distinguish the operations in a dataflow: producing an input, "
            "evaluating it, storing evidence, approving a decision, and executing the "
            "decision can have different owners. Sharing an artifact, outcome, or "
            "subject does not establish conflicting ownership. Identify the same "
            "executable operation and its competing authority when rejecting; a "
            "missing handoff is assessed in the connection stage unless the component "
            "responsibilities contradict that handoff. Also block mechanics outside "
            "the requested subject scope that replace "
            "or misrepresent the requested system. Redundant decomposition, compatible "
            "shared ownership, and naming preferences are advisory unless they cause "
            "concrete behavior or control harm. Mechanics used to author this response "
            "are not runtime features unless explicitly requested."
        )
        requirements["capability_classification"] = (
            "Classify capabilities from the candidate responsibilities and assumptions: "
            "external_effects means a component owns a declared write to state in an "
            "external system. Classify the behavior represented by the diagram. Topic "
            "names, recommendations, drafts, internal bookkeeping, and read-only "
            "provider calls do not establish an external write. When rejecting "
            "external_effects=false, cite the responsible component, its mutation, "
            "and the external target in the candidate responsibilities or assumptions. "
            "Do not invent an external system or write from an ambiguous description. "
            "An explicitly owned external write requires external_effects=true and "
            "its applicable controls, including when a human approves the write. "
            "retrieval_or_reuse "
            "means it retrieves or reuses stored artifacts; learning_or_release means "
            "this system owns an update or release of a model, prompt, ranking, or live "
            "configuration. Offline or batch training and human-approved updates or "
            "releases count; automatic feedback and immediate live deployment are not "
            "required. A no-automatic-loop assumption does not negate an explicitly "
            "owned update or release. "
            "Check each flag independently against named component responsibilities "
            "and assumptions, and report every unsupported flag in the same review. "
            "Internal dataset curation or publication and a passive downstream consumer "
            "alone do not imply external_effects or learning_or_release. Require an "
            "owner in this system for the external write or the update or release, "
            "respectively. Frozen inference without an owned update or release does "
            "not imply learning_or_release."
        )
        requirements = {
            "capability_classification": requirements["capability_classification"],
            **{code: rule for code, rule in requirements.items() if code != "capability_classification"},
        }
    elif maturity == "production":
        requirements["topology_enforced_guarantees"] = (
            "Show necessary directed contracts between components, including controls "
            "that must precede cross-boundary actions. Compatible internal operations "
            "may stay with one executable owner whose responsibility states the behavior. "
            "A typed response may contain success and rejection outcomes. A title or "
            "assumption cannot substitute for an owner or a required interaction."
        )
        # Transport mechanics guide authoring. Explicit requested behavior and
        # contradictions remain covered by runtime completeness and edge semantics.
        requirements["state_effect_reconciliation"] = STAGED_PRODUCTION_REQUIREMENTS[
            "state_effect_reconciliation"
        ]
        for guarantee in required_production_guarantees:
            if guarantee not in TOPOLOGY_PROOF_REQUIREMENTS:
                raise ValueError(f"unknown production guarantee: {guarantee!r}")
            requirements[guarantee] = STAGED_PRODUCTION_REQUIREMENTS[guarantee]
    else:
        requirements["safe_action_boundary"] = (
            "Preserve every explicitly requested approval, audit, recovery, or other "
            "action control. For a concrete declared external mutation, require "
            "appropriate authorization before the action and visible failure or denial "
            "handling. An existing owner may apply a lightweight guardrail before "
            "dispatch; a separate approval stage is not required unless explicitly "
            "requested. Generic educational "
            "tool or environment labels, code execution, or an external_effects flag "
            "alone do not require distinct approval, audit, or rollback mechanisms. "
            "Read-only tool calls and internal memory operations do not require a new "
            "approval stage unless explicitly requested. Identify the concrete mutation "
            "or requested control when rejecting a candidate. "
            + _ACTION_APPROVAL_DELIVERY_REQUIREMENT
        )
    return requirements


def repair_requirements(
    contract: dict[str, Any],
    topology_proofs: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return compact acceptance criteria for only the failed review items."""
    component_layer = (contract.get("layers") or {}).get("components")
    component_operations = (
        component_layer.get("existing_node_operations")
        if isinstance(component_layer, dict)
        else None
    )
    findings = {
        str(finding)
        for layer in (contract.get("layers") or {}).values()
        if isinstance(layer, dict)
        for finding in (layer.get("blocking_findings") or [])
    }
    requirements = [
        {
            "criterion": code,
            "owner_layer": owner,
            "requirement": " ".join(
                part
                for part in (
                    requirement,
                    _format_repair_node_operations(component_operations)
                    if owner == "components"
                    else "",
                )
                if part
            ),
        }
        for code, (owner, requirement) in RUBRIC_CRITERIA.items()
        if f"Repair {code.replace('_', ' ')} in the {owner} layer." in findings
    ]
    requirements.extend(
        {
            "criterion": f"topology_proof:{guarantee}",
            "owner_layer": "connections",
            "requirement": " ".join(
                part
                for part in (
                    TOPOLOGY_PROOF_REQUIREMENTS[guarantee],
                    _format_repair_obligations(proof.get("repair_obligations")),
                    _format_repair_edge_operations(proof.get("repair_edge_operations")),
                )
                if part
            ),
        }
        for proof in topology_proofs
        if isinstance(proof, dict)
        and proof.get("status") == "fail"
        and isinstance(proof.get("guarantee"), str)
        and (guarantee := proof["guarantee"]) in TOPOLOGY_PROOF_REQUIREMENTS
    )
    return requirements


def _format_repair_obligations(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    obligations = [
        obligation
        for obligation in value
        if isinstance(obligation, dict)
        and all(
            isinstance(obligation.get(field), str) and obligation[field].strip()
            for field in ("source", "target", "required_contract")
        )
    ]
    if not obligations:
        return ""
    return "Required additions: " + "; ".join(
        f"{obligation['source']} -> {obligation['target']}: "
        f"{obligation['required_contract']}"
        for obligation in obligations
    )


def _format_repair_node_operations(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    operations = [operation for operation in value if isinstance(operation, dict)]
    if not operations:
        return ""
    return "Required existing-node updates: " + "; ".join(
        f"update {operation.get('node_id', '?')}: "
        + ", ".join(
            f"{field}={item!s}"
            for field, item in sorted((operation.get("set") or {}).items())
        )
        for operation in operations
    )


def _format_repair_edge_operations(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    operations = [operation for operation in value if isinstance(operation, dict)]
    if not operations:
        return ""
    return "Required existing-edge operations: " + "; ".join(
        _format_repair_edge_operation(operation) for operation in operations
    )


def _format_repair_edge_operation(operation: dict[str, Any]) -> str:
    selector = operation.get("edge_selector") or {}
    identity = (
        f"{selector.get('source', '?')} -> {selector.get('target', '?')}: "
        f"{selector.get('label', '?')}"
    )
    kind = operation.get("kind")
    if kind == "update":
        return f"update {identity} to {str((operation.get('set') or {}).get('label') or '')}"
    if kind == "replace":
        replacements = _format_repair_obligations(
            operation.get("replacement_obligations")
        ).removeprefix("Required additions: ")
        return f"replace {identity} with {replacements}"
    return f"remove {identity}"
