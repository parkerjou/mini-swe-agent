"""Quorum orchestrator: parallel investigation -> structured debate -> fresh implementation."""

import json
import logging
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import litellm
from jinja2 import StrictUndefined, Template

from minisweagent.agents.default import DefaultAgent
from minisweagent.models import GLOBAL_MODEL_STATS, get_model
from minisweagent.models.utils.retry import retry
from minisweagent.utils.serialize import recursive_merge

logger = logging.getLogger("quorum")

INVESTIGATION_STRATEGIES = ["stack_trace_tracer", "issue_first", "minimal_diff"]

STRATEGY_LABELS = {
    "stack_trace_tracer": "Stack Trace Tracer",
    "issue_first": "Issue-First Hypothesizer",
    "minimal_diff": "Minimal Diff Finder",
}

DEBATE_CONTRIBUTION_PROMPT = """\
You have just completed your investigation of the issue. Now you are participating in a structured debate \
with two other investigators who explored the same issue using different strategies.

{% if prior_contributions %}
## Prior contributions in this debate

{% for c in prior_contributions %}
### {{ c.agent_label }} (Round {{ c.round }})

{{ c.content }}

{% endfor %}
{% endif %}

## Your task

Based on your investigation, provide a structured contribution with ALL of the following sections:

**Root cause:** A one-sentence claim about what is broken and why.

**Location:** Specific file(s) and code regions involved.

**Proposed fix direction:** What the fix looks like conceptually (not a patch, but a description of the change).

**Supporting evidence:** What you observed during investigation that supports this claim.

**Weaknesses:** Where your own position is uncertain or could be wrong.

**Confidence:** Your confidence level (low / medium / high) with brief justification.

{% if prior_contributions %}
**Reactions:** Your responses to the other investigators' positions — where you agree, disagree, or see gaps.
{% endif %}

Provide your contribution now. Be specific and concise.
"""

# Roles that the LLM API will accept. The agent loop uses "exit" internally
# but that must be stripped before sending messages back to the model.
_VALID_API_ROLES = {"system", "user", "assistant", "tool"}


def _strip_non_api_messages(messages: list[dict]) -> list[dict]:
    """Remove messages with roles the LLM API doesn't understand (e.g. 'exit')."""
    return [m for m in messages if m.get("role") in _VALID_API_ROLES]


def _format_debate_transcript(contributions: list[dict]) -> str:
    """Format all debate contributions into a readable transcript for the implementer."""
    parts = []
    for c in contributions:
        header = f"### {c['agent_label']} — Round {c['round']}"
        parts.append(f"{header}\n\n{c['content']}")
    return "\n\n---\n\n".join(parts)


class QuorumOrchestrator:
    """Runs 3 investigation agents in parallel, conducts a structured debate,
    then hands the debate transcript to a fresh implementation agent.

    Phase 1: Three investigation agents explore the issue independently using
             distinct reasoning strategies (20 steps each, cheap model).
    Phase 2: Two rounds of sequential debate (Agent 1 → 2 → 3, repeated).
             Each agent sees prior contributions and produces a structured position.
    Phase 3: A fresh implementation agent receives the original issue plus the
             full debate transcript and produces a patch.
    """

    def __init__(
        self,
        config: dict,
        *,
        on_agent_step: Callable | None = None,
        on_agent_start: Callable | None = None,
        on_agent_end: Callable | None = None,
    ):
        self.config = config
        self.on_agent_step = on_agent_step
        self.on_agent_start = on_agent_start
        self.on_agent_end = on_agent_end

    def run(self, task: str, instance: dict) -> dict:
        """Run the full Quorum pipeline: investigate -> debate -> implement.

        Partial results are stored on ``self.partial_result`` as each phase
        completes, so callers can retrieve whatever was finished if this method
        raises.
        """
        quorum_config = self.config.get("quorum", {})

        self.partial_result: dict = {
            "exit_status": "Error",
            "submission": "",
            "investigation": [],
            "debate_transcript": "",
            "debate_contributions": [],
            "implementation": {},
            "total_cost": 0.0,
            "total_calls": 0,
        }

        # Phase 1: Parallel investigation
        logger.info("Phase 1: Starting parallel investigation")
        investigation_results = self._run_investigation(task, instance)
        self.partial_result["investigation"] = investigation_results

        # Phase 2: Sequential debate
        logger.info("Phase 2: Starting structured debate")
        debate_rounds = quorum_config.get("debate", {}).get("rounds", 2)
        contributions: list[dict] = []
        try:
            contributions = self._run_debate(investigation_results, debate_rounds)
        finally:
            # Strip non-serializable objects regardless of debate success/failure
            for r in investigation_results:
                r.pop("agent", None)
                r.pop("model", None)
            self.partial_result["debate_contributions"] = contributions
        debate_transcript = _format_debate_transcript(contributions)
        self.partial_result["debate_transcript"] = debate_transcript

        # Phase 3: Fresh implementation
        logger.info("Phase 3: Starting implementation")
        impl_result = self._run_implementation(task, instance, debate_transcript)
        self.partial_result["implementation"] = impl_result

        # Aggregate costs
        total_cost = sum(r.get("cost", 0) for r in investigation_results)
        total_calls = sum(r.get("n_calls", 0) for r in investigation_results)
        total_cost += sum(c.get("cost", 0) for c in contributions)
        total_calls += len(contributions)  # each contribution is one model call
        total_cost += impl_result.get("cost", 0)
        total_calls += impl_result.get("n_calls", 0)

        result = {
            "exit_status": impl_result.get("exit_status", ""),
            "submission": impl_result.get("submission", ""),
            "investigation": investigation_results,
            "debate_transcript": debate_transcript,
            "debate_contributions": contributions,
            "implementation": impl_result,
            "total_cost": total_cost,
            "total_calls": total_calls,
        }
        self.partial_result = result
        return result

    # ── Phase 1: Investigation ──────────────────────────────────────────

    def _run_investigation(self, task: str, instance: dict) -> list[dict]:
        """Run 3 investigation agents in parallel, each in its own container."""
        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self._run_investigator, strategy, task, instance): strategy
                for strategy in INVESTIGATION_STRATEGIES
            }
            for future in as_completed(futures):
                strategy = futures[future]
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.error(f"Investigation agent {strategy} failed: {e}", exc_info=True)
                    results.append(
                        {
                            "strategy": strategy,
                            "exit_status": type(e).__name__,
                            "submission": "",
                            "messages": [],
                            "agent": None,
                            "model": None,
                            "cost": 0.0,
                            "n_calls": 0,
                            "traceback": traceback.format_exc(),
                        }
                    )
        # Sort to fixed order for deterministic debate
        order = {s: i for i, s in enumerate(INVESTIGATION_STRATEGIES)}
        results.sort(key=lambda r: order.get(r["strategy"], 99))
        return results

    def _run_investigator(self, strategy: str, task: str, instance: dict) -> dict:
        """Run a single investigation agent."""
        quorum_config = self.config.get("quorum", {})
        investigation_config = quorum_config.get("investigation", {})
        strategy_config = investigation_config.get("agents", {}).get(strategy, {})

        # Build agent config
        agent_config = {**self.config.get("agent", {})}
        agent_config["system_template"] = strategy_config["system_template"]
        if "instance_template" in strategy_config:
            agent_config["instance_template"] = strategy_config["instance_template"]
        if "step_limit" in investigation_config:
            agent_config["step_limit"] = investigation_config["step_limit"]
        if "cost_limit" in investigation_config:
            agent_config["cost_limit"] = investigation_config["cost_limit"]

        # Create environment (own container)
        env = _create_environment(self.config, instance)

        # Create model — use investigation-specific model config if provided
        model_config = recursive_merge(
            self.config.get("model", {}),
            investigation_config.get("model", {}),
        )
        model = get_model(config=model_config)

        agent = _CallbackAgent(
            model,
            env,
            strategy=strategy,
            on_step=self.on_agent_step,
            **agent_config,
        )

        if self.on_agent_start:
            self.on_agent_start(strategy)

        try:
            info = agent.run(task)
        except Exception:
            if self.on_agent_end:
                self.on_agent_end(strategy, "Error")
            raise
        finally:
            env.cleanup()

        exit_status = info.get("exit_status", "")
        if self.on_agent_end:
            self.on_agent_end(strategy, exit_status)

        return {
            "strategy": strategy,
            "exit_status": exit_status,
            "submission": info.get("submission", ""),
            "messages": agent.messages,
            "agent": agent,
            "model": model,
            "cost": agent.cost,
            "n_calls": agent.n_calls,
            "info": agent.serialize()["info"],
        }

    # ── Phase 2: Debate ─────────────────────────────────────────────────

    def _run_debate(self, investigation_results: list[dict], n_rounds: int = 2) -> list[dict]:
        """Run sequential debate rounds. Each agent contributes in fixed order.

        The debate is a pure-text exchange: each agent's model is called without
        tool definitions so it produces a free-form text response (not tool calls).
        The agent's investigation message history is included for context, but
        internal-only messages (role="exit") are stripped before sending to the API.
        """
        contributions: list[dict] = []

        for round_num in range(1, n_rounds + 1):
            for result in investigation_results:
                strategy = result["strategy"]
                agent = result.get("agent")
                model = result.get("model")

                if agent is None or model is None:
                    # Agent failed during investigation, skip in debate
                    logger.warning(f"Skipping {strategy} in debate round {round_num} (no agent)")
                    continue

                label = STRATEGY_LABELS.get(strategy, strategy)
                logger.info(f"Debate round {round_num}: {label} contributing")

                if self.on_agent_step:
                    self.on_agent_step(f"debate_{strategy}", round_num, 0)

                # Build the debate prompt with prior contributions visible
                debate_prompt = Template(DEBATE_CONTRIBUTION_PROMPT, undefined=StrictUndefined).render(
                    prior_contributions=contributions
                )

                # Build message list: investigation history (sans exit messages) + debate prompt
                messages = _strip_non_api_messages(agent.messages)
                messages.append({"role": "user", "content": debate_prompt})

                # Call the model directly WITHOUT tools — we want a pure text response.
                # This bypasses LitellmModel.query() which forces tool parsing via _parse_actions.
                response = _query_text_only(model, messages)

                content = response.get("content", "") or ""
                cost = response.get("extra", {}).get("cost", 0.0)

                contribution = {
                    "strategy": strategy,
                    "agent_label": label,
                    "round": round_num,
                    "content": content,
                    "cost": cost,
                }
                contributions.append(contribution)

        return contributions

    # ── Phase 3: Implementation ─────────────────────────────────────────

    def _run_implementation(self, task: str, instance: dict, debate_transcript: str) -> dict:
        """Run a fresh implementation agent with the debate transcript as context."""
        quorum_config = self.config.get("quorum", {})
        impl_config = quorum_config.get("implementation", {})

        # Build agent config
        agent_config = {**self.config.get("agent", {})}
        if "system_template" in impl_config:
            agent_config["system_template"] = impl_config["system_template"]
        if "instance_template" in impl_config:
            agent_config["instance_template"] = impl_config["instance_template"]
        if "step_limit" in impl_config:
            agent_config["step_limit"] = impl_config["step_limit"]
        if "cost_limit" in impl_config:
            agent_config["cost_limit"] = impl_config["cost_limit"]

        # Fresh environment
        env = _create_environment(self.config, instance)

        # Use implementation-specific model config if provided
        model_config = recursive_merge(
            self.config.get("model", {}),
            impl_config.get("model", {}),
        )
        model = get_model(config=model_config)

        agent = _CallbackAgent(
            model,
            env,
            strategy="implementer",
            on_step=self.on_agent_step,
            **agent_config,
        )

        if self.on_agent_start:
            self.on_agent_start("implementer")

        try:
            info = agent.run(task=task, debate_transcript=debate_transcript)
        except Exception:
            if self.on_agent_end:
                self.on_agent_end("implementer", "Error")
            raise
        finally:
            env.cleanup()

        exit_status = info.get("exit_status", "")
        if self.on_agent_end:
            self.on_agent_end("implementer", exit_status)

        return {
            "exit_status": exit_status,
            "submission": info.get("submission", ""),
            "messages": agent.messages,
            "cost": agent.cost,
            "n_calls": agent.n_calls,
            "info": agent.serialize()["info"],
        }

    # ── Persistence ─────────────────────────────────────────────────────

    def save(self, path: Path, result: dict, instance_id: str) -> dict:
        """Save the combined Quorum trajectory."""
        data = {
            "info": {
                "model_stats": {
                    "instance_cost": result.get("total_cost", 0),
                    "api_calls": result.get("total_calls", 0),
                },
                "exit_status": result.get("exit_status", ""),
                "submission": result.get("submission", ""),
            },
            "instance_id": instance_id,
            "investigation": [
                {
                    "strategy": r.get("strategy"),
                    "exit_status": r.get("exit_status"),
                    "messages": r.get("messages", []),
                    "info": r.get("info", {}),
                }
                for r in result.get("investigation", [])
            ],
            "debate_transcript": result.get("debate_transcript", ""),
            "debate_contributions": result.get("debate_contributions", []),
            "implementation": {
                "exit_status": result.get("implementation", {}).get("exit_status"),
                "messages": result.get("implementation", {}).get("messages", []),
                "info": result.get("implementation", {}).get("info", {}),
            },
            "trajectory_format": "mini-swe-agent-quorum-1.0",
        }

        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))
            # Save debate transcript as a standalone readable file
            debate_path = path.with_suffix(".debate.md")
            debate_path.write_text(self._format_debate_artifact(result, instance_id))
        return data

    @staticmethod
    def _format_debate_artifact(result: dict, instance_id: str) -> str:
        """Format the full debate as a readable Markdown artifact."""
        parts = [f"# Quorum Debate — {instance_id}\n"]

        # Investigation summaries
        parts.append("## Investigation Summaries\n")
        for r in result.get("investigation", []):
            label = STRATEGY_LABELS.get(r.get("strategy", ""), r.get("strategy", "unknown"))
            status = r.get("exit_status", "unknown")
            submission = r.get("submission", "").strip()
            parts.append(f"### {label} (exit: {status})\n")
            if submission:
                parts.append(f"{submission}\n")
            else:
                parts.append("*(no submission)*\n")

        # Debate contributions
        parts.append("## Debate Contributions\n")
        for c in result.get("debate_contributions", []):
            parts.append(f"### {c.get('agent_label', '?')} — Round {c.get('round', '?')}\n")
            parts.append(f"{c.get('content', '*(empty)*')}\n")

        # Final transcript (as sent to implementer)
        parts.append("## Full Transcript (as sent to implementer)\n")
        parts.append(result.get("debate_transcript", "*(empty)*"))
        parts.append("")

        return "\n".join(parts)


def _query_text_only(model, messages: list[dict]) -> dict:
    """Query the model for a pure text response (no tool calls).

    Uses the model's own ``_prepare_messages_for_api`` so that Anthropic
    thinking-block reordering and cache-control markers are applied exactly as
    during a normal query.  Temporarily injects ``tool_choice="none"`` into the
    model's kwargs so that the model's own ``_query`` method (and its
    backend-specific auth, error handling, etc.) is used, but no tool calls are
    produced.

    Falls back to calling ``litellm.completion`` directly if the model does not
    expose ``_query`` (shouldn't happen in practice).
    """
    # Use the model's full preprocessing pipeline when available
    if hasattr(model, "_prepare_messages_for_api"):
        prepared = model._prepare_messages_for_api(messages)
    else:
        prepared = [{k: v for k, v in msg.items() if k != "extra"} for msg in messages]

    abort_exceptions = getattr(model, "abort_exceptions", [KeyboardInterrupt])

    # Temporarily inject tool_choice="none" so tools are sent but never selected.
    # This lets us reuse model._query (with its auth, error handling, and
    # backend-specific transport) without triggering tool-call parsing issues.
    # Skip for textbased models — their _query sends no tools, so tool_choice
    # would be a spurious (and potentially unsupported) parameter.
    _uses_tool_calls = "textbased" not in type(model).__name__.lower()
    original_kwargs = model.config.model_kwargs
    if _uses_tool_calls:
        model.config.model_kwargs = {**original_kwargs, "tool_choice": "none"}
    try:
        for attempt in retry(logger=logger, abort_exceptions=abort_exceptions):
            with attempt:
                if hasattr(model, "_query"):
                    response = model._query(prepared)
                else:
                    response = litellm.completion(
                        model=model.config.model_name,
                        messages=prepared,
                        **model.config.model_kwargs,
                    )
    finally:
        if _uses_tool_calls:
            model.config.model_kwargs = original_kwargs

    # Use the model's cost calculation — let it raise on strict cost_tracking,
    # matching the behavior of the normal agent loop.
    cost = 0.0
    if hasattr(model, "_calculate_cost"):
        cost = model._calculate_cost(response).get("cost", 0.0)
    else:
        try:
            cost = litellm.cost_calculator.completion_cost(response, model=model.config.model_name)
            if cost <= 0.0:
                cost = 0.0
        except Exception:
            pass
    GLOBAL_MODEL_STATS.add(cost)

    # Normalize response to dict — litellm returns objects, openrouter/requesty return dicts
    if hasattr(response, "choices"):
        message = response.choices[0].message.model_dump()
    else:
        message = dict(response["choices"][0]["message"])

    message["extra"] = {
        "cost": cost,
        "timestamp": time.time(),
    }
    return message


class _CallbackAgent(DefaultAgent):
    """DefaultAgent with step callbacks for progress reporting."""

    def __init__(self, *args, strategy: str = "", on_step: Callable | None = None, **kwargs):
        self._strategy = strategy
        self._on_step = on_step
        super().__init__(*args, **kwargs)

    def step(self) -> list[dict]:
        if self._on_step:
            self._on_step(self._strategy, self.n_calls + 1, self.cost)
        return super().step()


def _create_environment(config: dict, instance: dict):
    """Create a Docker environment for a SWE-bench instance."""
    from minisweagent.run.benchmarks.swebench import get_sb_environment

    return get_sb_environment(config, instance)
