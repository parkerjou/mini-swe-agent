"""Tournament orchestrator: 3 strategy agents in parallel -> judge selects best patch."""

import json
import logging
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from minisweagent.agents.default import DefaultAgent
from minisweagent.models import get_model
from minisweagent.utils.serialize import recursive_merge

logger = logging.getLogger("tournament")

STRATEGIES = ["stack_trace_tracer", "issue_hypothesis", "minimal_diff"]


class TournamentOrchestrator:
    """Runs 3 strategy agents in parallel, then a judge picks the best patch.

    Each strategy agent gets its own Docker container and independently
    investigates + fixes the issue. The judge gets a fresh container,
    applies each patch, runs tests, and selects the winner.
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
        """Run the full tournament pipeline. Returns dict with submission, exit_status, trajectory data."""
        # Phase 1: Run 3 strategy agents in parallel
        agent_results = self._run_strategy_agents(task, instance)

        # Collect patches from agents that submitted
        patches = []
        for result in agent_results:
            if result["exit_status"] == "Submitted" and result["submission"]:
                patches.append({"strategy": result["strategy"], "content": result["submission"]})

        # Phase 2: Judge
        if not patches:
            logger.info("No patches submitted by any agent. Abstaining.")
            return {
                "exit_status": "Abstain",
                "submission": "",
                "agents": agent_results,
                "judge": None,
                "n_patches_submitted": 0,
                "winning_strategy": None,
            }

        try:
            judge_result = self._run_judge(task, instance, patches)
        except Exception as e:
            logger.error(f"Judge failed with exception: {e}; falling back to first available patch.", exc_info=True)
            fallback = patches[0]
            return {
                "exit_status": "JudgeError",
                "submission": fallback["content"],
                "agents": agent_results,
                "judge": None,
                "n_patches_submitted": len(patches),
                "winning_strategy": fallback["strategy"],
            }

        return {
            "exit_status": judge_result.get("exit_status", "Submitted"),
            "submission": judge_result.get("submission", ""),
            "agents": agent_results,
            "judge": judge_result,
            "n_patches_submitted": len(patches),
            "winning_strategy": judge_result.get("winning_strategy"),
        }

    def _run_strategy_agents(self, task: str, instance: dict) -> list[dict]:
        """Run all strategy agents in parallel, each in its own container."""
        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self._run_single_agent, strategy, task, instance): strategy for strategy in STRATEGIES
            }
            for future in as_completed(futures):
                strategy = futures[future]
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.error(f"Strategy agent {strategy} failed with exception: {e}", exc_info=True)
                    results.append(
                        {
                            "role": "agent",
                            "strategy": strategy,
                            "exit_status": type(e).__name__,
                            "submission": "",
                            "messages": [],
                            "cost": 0.0,
                            "n_calls": 0,
                            "traceback": traceback.format_exc(),
                        }
                    )
        return results

    def _run_single_agent(self, strategy: str, task: str, instance: dict) -> dict:
        """Run a single strategy agent in its own Docker container."""
        tournament_config = self.config.get("tournament", {})
        strategy_config = tournament_config.get("strategies", {}).get(strategy, {})

        # Build agent config: base agent config + strategy-specific overrides
        agent_config = {**self.config.get("agent", {})}
        agent_config["system_template"] = strategy_config["system_template"]
        if "instance_template" in strategy_config:
            agent_config["instance_template"] = strategy_config["instance_template"]

        # Create environment (own container)
        env = _create_environment(self.config, instance)

        # Create model
        model = get_model(config=self.config.get("model", {}))

        # Create agent with progress callback
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
            "role": "agent",
            "strategy": strategy,
            "exit_status": exit_status,
            "submission": info.get("submission", ""),
            "messages": agent.messages,
            "cost": agent.cost,
            "n_calls": agent.n_calls,
            "info": agent.serialize()["info"],
        }

    def _run_judge(self, task: str, instance: dict, patches: list[dict]) -> dict:
        """Run the judge agent on a fresh container to evaluate patches."""
        tournament_config = self.config.get("tournament", {})
        judge_config = tournament_config.get("judge", {})

        agent_config = {**self.config.get("agent", {})}
        agent_config["system_template"] = judge_config["system_template"]
        agent_config["instance_template"] = judge_config["instance_template"]
        if judge_config.get("step_limit"):
            agent_config["step_limit"] = judge_config["step_limit"]
        if judge_config.get("cost_limit"):
            agent_config["cost_limit"] = judge_config["cost_limit"]

        # Fresh container for judge
        env = _create_environment(self.config, instance)

        # Judge can use a different (more capable) model
        judge_model_config = recursive_merge(
            self.config.get("model", {}),
            judge_config.get("model", {}),
        )
        model = get_model(config=judge_model_config)

        agent = _CallbackAgent(
            model,
            env,
            strategy="judge",
            on_step=self.on_agent_step,
            **agent_config,
        )

        if self.on_agent_start:
            self.on_agent_start("judge")

        try:
            info = agent.run(task=task, patches=patches)
        except Exception:
            if self.on_agent_end:
                self.on_agent_end("judge", "Error")
            raise
        finally:
            env.cleanup()

        exit_status = info.get("exit_status", "")
        if self.on_agent_end:
            self.on_agent_end("judge", exit_status)

        # Parse winning strategy from first line of submission.
        # Judge is instructed to output "SELECTED_STRATEGY: <name>" before the patch.
        raw_submission = info.get("submission", "")
        winning_strategy = None
        submission = raw_submission
        if raw_submission:
            first_line, _, rest = raw_submission.partition("\n")
            if first_line.startswith("SELECTED_STRATEGY:"):
                parsed = first_line.split(":", 1)[1].strip()
                if parsed in STRATEGIES:
                    winning_strategy = parsed
                    submission = rest
                else:
                    logger.warning(f"Judge reported unknown strategy {parsed!r}; ignoring SELECTED_STRATEGY header")

        # Fallback: infer winning strategy by matching submission content against inputs
        if winning_strategy is None and submission:
            for patch in patches:
                if patch["content"].strip() == submission.strip():
                    winning_strategy = patch["strategy"]
                    logger.info(f"Inferred winning_strategy={winning_strategy!r} by exact content match")
                    break

        if winning_strategy is None:
            logger.warning("Could not determine winning_strategy from judge submission")

        return {
            "role": "judge",
            "exit_status": exit_status,
            "submission": submission,
            "winning_strategy": winning_strategy,
            "messages": agent.messages,
            "cost": agent.cost,
            "n_calls": agent.n_calls,
            "info": agent.serialize()["info"],
        }

    def save(self, path: Path, result: dict, instance_id: str) -> dict:
        """Save the combined tournament trajectory."""
        total_cost = sum(a.get("cost", 0) for a in result.get("agents", []))
        total_calls = sum(a.get("n_calls", 0) for a in result.get("agents", []))
        if result.get("judge"):
            total_cost += result["judge"].get("cost", 0)
            total_calls += result["judge"].get("n_calls", 0)

        data = {
            "info": {
                "model_stats": {
                    "instance_cost": total_cost,
                    "api_calls": total_calls,
                },
                "exit_status": result.get("exit_status", ""),
                "submission": result.get("submission", ""),
                "n_patches_submitted": result.get("n_patches_submitted", 0),
                "winning_strategy": result.get("winning_strategy"),
            },
            "instance_id": instance_id,
            "agents": [
                {
                    "role": a.get("role", "agent"),
                    "strategy": a.get("strategy"),
                    "exit_status": a.get("exit_status"),
                    "patch": a.get("submission"),
                    "messages": a.get("messages", []),
                    "info": a.get("info", {}),
                }
                for a in result.get("agents", [])
            ],
            "trajectory_format": "mini-swe-agent-tournament-1.0",
        }
        if result.get("judge"):
            j = result["judge"]
            data["agents"].append(
                {
                    "role": "judge",
                    "strategy": "judge",
                    "exit_status": j.get("exit_status"),
                    "selected_strategy": result.get("winning_strategy"),
                    "messages": j.get("messages", []),
                    "info": j.get("info", {}),
                }
            )

        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))
        return data


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
