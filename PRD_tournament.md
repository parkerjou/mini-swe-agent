# PRD: Tournament Multiagent System (SWE-bench)

## Motivation

Single-agent systems commit to one hypothesis early. The tournament architecture runs three structurally distinct agents in parallel — each investigating and fixing the issue in its own way — then uses a judge to select the best patch. Diversity is enforced by prompt, not model.

## Scope

SWE-bench evaluation runs only. Runs in isolated Docker containers. Builds on the existing `DefaultAgent` architecture.

---

## Pipeline

```
┌──────────────────────────────────────────────────┐
│              AGENT STAGE (parallel)               │
│                                                   │
│  StackTraceTracer  │  IssueHypothesis  │  MinimalDiff  │
└────────┬───────────┴────────┬──────────┴──────┬───┘
         │                    │                  │
         └────────────────────┼──────────────────┘
                              │
                  (all agents complete or hit limits)
                              │
                    ┌─────────▼─────────┐
                    │    Judge Agent    │
                    │  (fresh container)│
                    └─────────┬─────────┘
                              │
                         final patch
```

---

## Agent Stage

Three agents run in parallel, each in its own Docker container. Each agent independently investigates the issue and produces a patch. Diversity comes entirely from the system prompt — all three can use the same model.

Each agent exits via the standard SWE-bench submission signal:
```bash
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt
```

If an agent hits its step or cost limit without submitting, it produces no patch.

### 1. StackTraceTracer
- Ignores the issue description
- Starts from the failing test and error output
- Follows the execution path backwards: test → called function → dependencies
- Localizes and fixes the bug purely from execution evidence
- Prompt constraint: "Do not read the issue description. Start from the failing test and work backwards."

### 2. IssueHypothesis
- Reads the PR/issue description deeply before touching any code
- Forms an explicit hypothesis about root cause, then searches the codebase to confirm or refute it
- Implements the fix only after the hypothesis is confirmed
- Prompt constraint: "Write your hypothesis before opening any source file. Then verify it."

### 3. MinimalDiff
- Constrained to the smallest possible change
- Asks "what is the least invasive fix?" before localizing anything
- Biases toward single-line or single-function changes
- Prompt constraint: "Assume the fix is one or two lines. Find where those lines are."

---

## Judge Stage

Runs after all agents have completed or exhausted their budgets. The judge:

1. Receives all available patches (0–3) and the original issue description
2. Gets a **fresh Docker container** (no prior agent changes applied)
3. Applies each patch one at a time, runs the relevant test suite, records results
4. Selects the best patch based on: test results (primary signal), diff size, absence of unrelated changes, code quality
5. Does not modify any patch — evaluates and chooses only

**Selection rules:**
- If 1+ patches pass tests: judge picks the best passing patch
- If 0 patches pass tests: judge picks the least-bad option among available patches
- If 0 patches exist (all agents hit limits without submitting): submit empty patch (abstain)

---

## Orchestration: `TournamentOrchestrator`

### Flow

```
1. Spin up 3 Docker containers (one per agent)
2. Run [StackTraceTracer, IssueHypothesis, MinimalDiff] in parallel
3. Collect patches from agents that completed cleanly
4. If 0 patches: submit empty patch; done
5. Spin up fresh Docker container for judge
6. Judge applies patches, runs tests, selects winner
7. Submit winning patch
8. Save combined trajectory
```

### Config

```yaml
# config/benchmarks/swebench_tournament.yaml

agents:
  model: ...         # cheap or mid-tier model; same for all three
  step_limit: 200
  cost_limit: 2.00

judge:
  model: ...         # most capable model
  step_limit: 100
  cost_limit: 1.00
```

### Combined Trajectory

```json
{
  "info": {
    "model_stats": {
      "instance_cost": "<sum of all agents including judge>",
      "api_calls": "<sum of all agents including judge>"
    },
    "exit_status": "<final exit signal>",
    "submission": "<final patch content>",
    "n_patches_submitted": 2,
    "winning_strategy": "stack_trace_tracer"
  },
  "agents": [
    { "role": "agent", "strategy": "stack_trace_tracer", "patch": "...", "messages": [...], "info": { ... } },
    { "role": "agent", "strategy": "issue_hypothesis", "patch": "...", "messages": [...], "info": { ... } },
    { "role": "agent", "strategy": "minimal_diff", "patch": null, "messages": [...], "info": { ... } },
    { "role": "judge", "selected_strategy": "stack_trace_tracer", "messages": [...], "info": { ... } }
  ],
  "trajectory_format": "mini-swe-agent-tournament-1.0"
}
```

---

## File Structure

```
src/minisweagent/
  agents/
    default.py                        # unchanged
    tournament.py                     # TournamentOrchestrator
  config/
    benchmarks/
      swebench.yaml                   # unchanged
      swebench_tournament.yaml        # tournament config
    templates/
      agent_stack_trace_tracer.jinja2
      agent_issue_hypothesis.jinja2
      agent_minimal_diff.jinja2
      judge_tournament.jinja2
  run/
    benchmarks/
      swebench_tournament.py          # CLI entry point
```

---

## Key Design Principles

- All three strategy agents use the same model; diversity is prompt-only
- Agents are fully independent — no shared state, no shared containers
- The judge's container is fresh; it applies and tests patches itself
- Step/cost limits are the only timeout mechanism; no special hang detection needed
- The judge selects only; it never modifies a patch
