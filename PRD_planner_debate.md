# Quorum: Multi-Agent Code Repair via Parallel Investigation and Structured Debate

**Status:** Draft
**Date:** 2026-03-24
**Target benchmark:** SWE-bench Lite

---

## Motivation

Single-agent approaches to automated code repair tend to lock into one line of reasoning early. If the agent's initial hypothesis is wrong, it spends the rest of its budget trying to make a bad theory work. The cost of exploration is high because a single agent must do everything sequentially — investigate, decide, and implement — with no external check on its reasoning.

Quorum addresses this by separating investigation from implementation entirely and introducing structured disagreement between investigation agents. Three agents explore the problem independently using distinct reasoning strategies, debate their findings in two rounds, and hand off a full debate transcript to a fresh implementation agent. The implementer benefits from multiple investigated hypotheses, explicitly stated weaknesses, and a map of what has been ruled out — all without inheriting any single agent's tunnel vision.

The key insight is that diversity of reasoning strategy matters more than diversity of model. All three investigation agents can be the same cheap model; what makes them different is how they are prompted to approach the problem. This keeps costs low while still producing meaningfully independent perspectives.

## Architecture Overview

Quorum is a three-phase pipeline: parallel investigation, sequential debate, and fresh implementation.

```
┌──────────────────────────────────────────────────────────────┐
│                    Phase 1: Investigation                     │
│                                                              │
│   ┌────────────────┐ ┌────────────────┐ ┌────────────────┐  │
│   │ Agent 1:       │ │ Agent 2:       │ │ Agent 3:       │  │
│   │ Stack Trace    │ │ Issue-First    │ │ Minimal Diff   │  │
│   │ Tracer         │ │ Hypothesizer   │ │ Finder         │  │
│   └────────────────┘ └────────────────┘ └────────────────┘  │
│         │                   │                  │             │
│         ▼                   ▼                  ▼             │
│   20 steps each, fully independent, cheap model              │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                      Phase 2: Debate                         │
│                                                              │
│   Round 1:  Agent 1 → Agent 2 → Agent 3                     │
│   Round 2:  Agent 1 → Agent 2 → Agent 3                     │
│                                                              │
│   Fixed ordering, cheap model                                │
│   Each contribution: root cause, evidence, weaknesses,       │
│   confidence, reactions to prior positions                    │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                   Phase 3: Implementation                     │
│                                                              │
│   Fresh implementer agent receives:                          │
│     - Original issue                                         │
│     - Full debate transcript (both rounds)                   │
│                                                              │
│   Mid-tier model, full tool access, no step limit            │
│   Writes patch, runs tests, iterates until passing           │
└──────────────────────────────────────────────────────────────┘
```

## Phase 1: Parallel Investigation

Three agents run in parallel with no information sharing. Each agent receives the original issue and has full tool access (file reads, grep, test execution) for up to 20 steps. The agents differ only in their prompt-enforced reasoning strategy.

### Agent 1: Stack Trace Tracer

Starts from the failing test and error output. Follows the execution path backwards through the call stack to localize the root cause. Works purely from execution evidence. Ignores the issue description until it has formed an independent hypothesis from the code and test output.

### Agent 2: Issue-First Hypothesizer

Reads the bug report deeply before touching any code. Forms an explicit structured hypothesis about the root cause — what's broken, why, and where — then searches the codebase to confirm or refute that hypothesis. Treats the issue description as the primary evidence source and the code as validation.

### Agent 3: Minimal Diff Finder

Explicitly constrained to find the smallest possible change that could fix the issue. Before localizing anything, asks: what is the least invasive edit that could explain this failure? Searches for single-line or single-expression changes first, expanding scope only if necessary.

### Design rationale

These three strategies are chosen to produce structurally different exploration paths. The Stack Trace Tracer (Agent 1) is bottom-up (starts from symptoms), the Issue-First Hypothesizer (Agent 2) is top-down (starts from the description), and the Minimal Diff Finder (Agent 3) is constraint-first (starts from a prior about fix size). On problems where the root cause is obvious from the stack trace, Agent 1 will converge quickly. On problems where the issue description is the key signal, Agent 2 will. On problems where the fix is simple but the failure is confusing, Agent 3 will. The goal is that at least one agent lands close to the right answer.

### Investigation step budget

Each agent receives a fixed budget of **20 tool-call steps**. This is sufficient for most SWE-bench Lite problems (typically localized to 1-3 files) while keeping costs low on a cheap model. Each agent is told explicitly in its prompt how many steps it has and is expected to form a definitive opinion by the end of that budget.

The budget is uniform across all three agents. This avoids tuning complexity. If future evaluation shows that certain reasoning strategies systematically under- or over-utilize their budget, asymmetric budgets can be revisited.

## Phase 2: Sequential Debate

After all three investigation agents complete, a two-round sequential debate begins. The ordering is fixed: Agent 1, then Agent 2, then Agent 3, repeated for a second round.

### Round 1

Agent 1 states its full position with no prior context from the other agents. Agent 2 reads Agent 1's contribution, then states its own — it may agree, disagree, or refine. Agent 3 reads both Agent 1 and Agent 2's contributions, then states its own.

### Round 2

The same sequence repeats. Now every agent has seen every other agent's first-round position. Agent 1 can respond to challenges raised by Agents 2 and 3. Agent 2 can update based on Agent 1's revision and its memory of Agent 3. Agent 3 reads the full transcript and makes its final statement.

The second round is where positions either converge or crystallize into clear disagreement. Both outcomes are useful to the implementer.

### Debate contribution structure

Each agent's contribution in each round must include:

- **Root cause** — a one-sentence claim about what is broken and why
- **Location** — specific file(s) and code regions involved
- **Proposed fix direction** — what the fix looks like conceptually (not a patch, but a description)
- **Supporting evidence** — what the agent observed during investigation that supports this claim
- **Weaknesses** — where the agent's own position is uncertain or could be wrong
- **Confidence** — a stated confidence level with brief justification
- **Reactions** — responses to other agents' positions (from round 1 onward)

This structure ensures the implementer receives self-contained, actionable positions rather than raw investigation logs. Each contribution must include enough context for someone who did not watch the investigation to understand the reasoning.

### No judge, no voting

There is no aggregation step after the debate. No agent is declared the winner. No vote is taken. The full debate transcript — all six contributions across two rounds — is passed directly to the implementer. Synthesis is the implementer's job.

## Phase 3: Implementation

A fresh agent is instantiated with no prior context. It receives two inputs: the original issue and the full debate transcript (both rounds, all contributions). It does not receive raw investigation logs, tool call histories, or any other artifacts from Phases 1 or 2.

The implementer is a mid-tier or strong model with full tool access (file reads, writes, grep, test execution). It has no step limit. It operates like a standard agent — the existing mini-swe-agent loop — with the sole difference that its initial context is enriched by the debate transcript.

### Implementer autonomy

The implementer uses its own judgment to synthesize the debate. It is not instructed to follow any particular agent, identify a consensus, or apply a specific synthesis strategy. It may agree with one agent, combine ideas from multiple agents, or discard the debate entirely and investigate independently. The debate transcript is context, not a directive.

### Test execution and iteration

The implementer writes patches and runs tests as part of its normal agent loop, consistent with the default mini-swe-agent behavior. If tests fail, the implementer sees the failure output and can iterate — reading more files, revising its approach, or trying a different fix. There is no special retry mechanism or external verification step. The agent runs until tests pass or it exhausts its own capabilities.

## Model Assignment

| Phase | Model tier | Rationale |
|---|---|---|
| Investigation (×3) | Cheap | Reading and reasoning over code; no generation required |
| Debate (×2 rounds) | Cheap | Structured natural language output; low complexity |
| Implementation | Mid-tier or strong | Responsible for final patch quality; needs strong code generation |

Using cheap models for investigation and debate keeps the total cost of the pipeline comparable to a single strong-model agent run, while providing significantly more coverage of the problem space.

## Design Principles

**Epistemic independence.** Investigation agents form hypotheses without seeing each other's reasoning. This prevents herding — if Agent 1 reaches a wrong conclusion, Agents 2 and 3 are unaffected. Diversity of conclusions is a feature, not a failure mode.

**Prompt-enforced diversity.** All investigation agents can be the same model. Diversity comes from reasoning strategy, not model heterogeneity. This is cheaper and more controllable than using different models.

**Structured debate over raw sharing.** Agents exchange finished positions with stated weaknesses, not raw exploration logs. This compresses 60 tool calls worth of investigation into a tractable artifact for the implementer.

**Implicit synthesis.** No judge or voting mechanism. The implementer — the strongest model in the pipeline — reads the full debate and makes its own decision. This avoids the failure mode of a weak judge misranking strong evidence.

**Negative knowledge transfer.** The debate transcript contains not just hypotheses but also ruled-out territory and stated weaknesses. The implementer knows what not to try, not just what to try.

**Clean role separation.** Investigation, debate, and implementation are fully separated with no shared agent state. Each phase produces a well-defined artifact consumed by the next phase.

## Progress Reporting

The orchestrator must report progress to the user at each phase transition and during long-running phases. Progress reporting is lightweight — status updates only, no streaming of agent internals.

### Investigation phase

Report which agents are running and how many steps each has completed. Example output:

```
Investigation in progress
  Stack Trace Tracer:      step 14/20
  Issue-First Hypothesizer: step 8/20
  Minimal Diff Finder:     step 20/20 (complete)
```

Updates should be emitted at a reasonable cadence (e.g., every step or every few seconds), not only at the end. Since agents run in parallel, their step counts advance independently.

### Debate phase

Report the current round and which agent is contributing. Example output:

```
Debate in progress
  Round 2: Agent 1 (Stack Trace Tracer) contributing
```

Each contribution is a single model call, so updates here are per-contribution rather than continuous.

### Implementation phase

Report that the implementer is active and its current step count. Example output:

```
Implementation in progress
  Implementer: step 12
```

Since the implementer has no step limit, only the current step count is shown (no denominator).

## Resolved Design Decisions

**Debate contribution enforcement: prompt discipline only.** The structured contribution format (root cause, location, evidence, weaknesses, confidence, reactions) is enforced through the debate prompt, not through schema validation. If a model omits a field, the debate still functions — the implementer simply has less information from that agent. This avoids the complexity of validation logic, retry prompting, and fallback handling. The failure mode is graceful degradation, not pipeline failure.

**Implementer prompt: maximum autonomy.** The implementer receives the original issue and the full debate transcript with no synthesis instructions. It is not told to identify consensus, weight positions, or follow any particular agent. The implementer is the strongest model in the pipeline and is trusted to synthesize effectively on its own. If evaluation reveals systematic issues (e.g., consistent recency bias toward Agent 3, or ignoring the debate entirely), lightweight prompt adjustments can be introduced without changing the architecture.

**Investigation budget: uniform.** All three agents receive the same 20-step budget. Asymmetric budgets were considered but rejected in favor of simplicity. This decision can be revisited if evaluation shows consistent under- or over-utilization by specific reasoning strategies.

**Debate ordering: fixed.** Agent ordering in the debate is fixed (1→2→3) across all runs. Randomization was considered but adds complexity for uncertain benefit. If evaluation reveals ordering bias (e.g., Agent 3 consistently dominates because it speaks last), randomization can be introduced.

## Evaluation Plan

**Cost profiling.** The expected cost per run should be benchmarked: 3 cheap investigation runs + 6 cheap debate contributions + 1 uncapped mid-tier implementation run. If the implementation phase dominates cost, the investigation/debate phases are essentially free. If investigation dominates (unlikely), the step budget may need adjustment.

**Baseline comparisons.** Quorum should be evaluated against three baselines on SWE-bench Lite to isolate where value comes from:

1. **Single agent** — one mid-tier agent with no debate context (tests whether the debate adds value over a single agent)
2. **Extended single agent** — one mid-tier agent given 3× the step budget (tests whether the value comes from more compute or from the multi-agent structure)
3. **Best of 3** — three independent agents each produce patches; the first one that passes tests wins (tests whether the value comes from the debate or simply from running more attempts)

These baselines distinguish between "more agents help" and "structured debate helps."

## Future Considerations

**Information sharing during investigation.** The current design keeps investigation fully independent. A future iteration could introduce a shared document for negative findings only (ruled-out files, ruled-out hypotheses, confirmed observations) to reduce redundant exploration. This would require a schema and enforcement mechanism, and would need to be evaluated against the current independent design to confirm it improves results.

**Asymmetric model assignment.** If specific reasoning strategies consistently underperform on cheap models (e.g., the Minimal Diff Finder requires stronger reasoning about code structure), individual agents could be upgraded to a mid-tier model while keeping the others cheap.
