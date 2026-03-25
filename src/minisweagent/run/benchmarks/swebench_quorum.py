#!/usr/bin/env python3

"""Run Quorum multi-agent system on SWE-bench instances.

Quorum pipeline: 3 investigation agents (parallel) -> structured debate (2 rounds) -> fresh implementer.
"""

import concurrent.futures
import json
import time
from pathlib import Path

import typer
from rich.live import Live

from minisweagent.agents.quorum import QuorumOrchestrator
from minisweagent.config import builtin_config_dir, get_config_from_spec
from minisweagent.run.benchmarks.swebench import (
    DATASET_MAPPING,
    filter_instances,
    remove_from_preds_file,
    update_preds_file,
)
from minisweagent.run.benchmarks.utils.batch_progress import RunBatchProgressManager
from minisweagent.utils.log import add_file_handler, logger
from minisweagent.utils.serialize import UNSET, recursive_merge

_HELP_TEXT = """Run Quorum multi-agent system on SWE-bench instances.

[not dim]
FOR SWE-BENCH EVALUATION ONLY. Runs in isolated Docker containers.

Quorum separates investigation from implementation via structured debate:

Phase 1 — Three investigation agents run in parallel, each in its own container:
  - StackTraceTracer: traces execution backwards from failures
  - IssueFirstHypothesizer: forms hypotheses from the bug report, then verifies
  - MinimalDiffFinder: searches for the smallest possible fix

Phase 2 — Two rounds of sequential debate where each agent presents:
  root cause, location, fix direction, evidence, weaknesses, confidence, reactions

Phase 3 — A fresh implementation agent receives the debate transcript and produces
  a patch in SWE-bench submission format.
[/not dim]
"""

DEFAULT_CONFIG_FILE = builtin_config_dir / "benchmarks" / "swebench_quorum.yaml"

app = typer.Typer(rich_markup_mode="rich", add_completion=False)


def process_quorum_instance(
    instance: dict,
    output_dir: Path,
    config: dict,
    progress_manager: RunBatchProgressManager,
) -> None:
    """Process a single SWE-bench instance with the Quorum pipeline."""
    instance_id = instance["instance_id"]
    instance_dir = output_dir / instance_id
    remove_from_preds_file(output_dir / "preds.json", instance_id)
    (instance_dir / f"{instance_id}.traj.json").unlink(missing_ok=True)
    (instance_dir / f"{instance_id}.traj.debate.md").unlink(missing_ok=True)

    task = instance["problem_statement"]
    exit_status = None
    result = None
    submission = ""

    # Register the main instance spinner (used for debate progress updates)
    # and sub-task spinners for each strategy agent + implementer
    progress_manager.on_instance_start(instance_id)
    progress_manager.update_instance_status(instance_id, "Initializing...")
    subtask_ids = {}
    for name in ["stack_trace_tracer", "issue_first", "minimal_diff", "implementer"]:
        subtask_ids[name] = f"{instance_id}/{name}"

    def on_agent_start(strategy: str):
        sid = subtask_ids.get(strategy, f"{instance_id}/{strategy}")
        progress_manager.on_instance_start(sid)
        progress_manager.update_instance_status(sid, "Starting...")

    def on_agent_step(strategy: str, step: int, cost: float):
        if strategy.startswith("debate_"):
            # Debate contributions show round number instead of step
            progress_manager.update_instance_status(instance_id, f"Debate round {step}")
            return
        sid = subtask_ids.get(strategy, f"{instance_id}/{strategy}")
        progress_manager.update_instance_status(sid, f"Step {step:3d} (${cost:.2f})")

    def on_agent_end(strategy: str, status: str):
        sid = subtask_ids.get(strategy, f"{instance_id}/{strategy}")
        progress_manager.remove_spinner(sid)

    orchestrator = QuorumOrchestrator(
        config,
        on_agent_step=on_agent_step,
        on_agent_start=on_agent_start,
        on_agent_end=on_agent_end,
    )

    try:
        result = orchestrator.run(task, instance)
        exit_status = result.get("exit_status", "")
        submission = result.get("submission", "")
    except Exception as e:
        logger.error(f"Error processing quorum instance {instance_id}: {e}", exc_info=True)
        exit_status = type(e).__name__
        submission = ""
        # Recover whatever completed before the failure
        result = result or getattr(orchestrator, "partial_result", None) or {
            "investigation": [], "debate_contributions": [], "implementation": {}
        }
    finally:
        # Clean up any remaining subtask spinners
        for sid in subtask_ids.values():
            progress_manager.remove_spinner(sid)

        if result is not None:
            traj_path = instance_dir / f"{instance_id}.traj.json"
            orchestrator.save(traj_path, result, instance_id)
            logger.info(f"Saved quorum trajectory to '{traj_path}'")

        model_name = config.get("model", {}).get("model_name", "quorum")
        update_preds_file(output_dir / "preds.json", instance_id, model_name, submission)
        progress_manager.on_instance_end(instance_id, exit_status)


# fmt: off
@app.command(help=_HELP_TEXT)
def main(
    subset: str = typer.Option("lite", "--subset", help="SWEBench subset to use or path to a dataset", rich_help_panel="Data selection"),
    split: str = typer.Option("dev", "--split", help="Dataset split", rich_help_panel="Data selection"),
    slice_spec: str = typer.Option("", "--slice", help="Slice specification (e.g., '0:5' for first 5 instances)", rich_help_panel="Data selection"),
    filter_spec: str = typer.Option("", "--filter", help="Filter instance IDs by regex", rich_help_panel="Data selection"),
    shuffle: bool = typer.Option(False, "--shuffle", help="Shuffle instances", rich_help_panel="Data selection"),
    output: str = typer.Option("", "-o", "--output", help="Output directory", rich_help_panel="Basic"),
    workers: int = typer.Option(1, "-w", "--workers", help="Number of worker threads for parallel instance processing", rich_help_panel="Basic"),
    model: str | None = typer.Option(None, "-m", "--model", help="Model for all agents (override)", rich_help_panel="Basic"),
    impl_model: str | None = typer.Option(None, "--impl-model", help="Model for implementation agent (defaults to base model)", rich_help_panel="Basic"),
    model_class: str | None = typer.Option(None, "--model-class", help="Model class to use", rich_help_panel="Advanced"),
    redo_existing: bool = typer.Option(False, "--redo-existing", help="Redo existing instances", rich_help_panel="Data selection"),
    config_spec: list[str] = typer.Option([str(DEFAULT_CONFIG_FILE)], "-c", "--config", help="Config files or key=value overrides", rich_help_panel="Basic"),
    environment_class: str | None = typer.Option(None, "--environment-class", help="Environment type (default: docker)", rich_help_panel="Advanced"),
) -> None:
    # fmt: on
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Results will be saved to {output_path}")
    add_file_handler(output_path / "minisweagent.log")

    from datasets import load_dataset

    dataset_path = DATASET_MAPPING.get(subset, subset)
    logger.info(f"Loading dataset {dataset_path}, split {split}...")
    instances = list(load_dataset(dataset_path, split=split))

    instances = filter_instances(instances, filter_spec=filter_spec, slice_spec=slice_spec, shuffle=shuffle)
    if not redo_existing and (output_path / "preds.json").exists():
        existing_instances = list(json.loads((output_path / "preds.json").read_text()).keys())
        logger.info(f"Skipping {len(existing_instances)} existing instances")
        instances = [instance for instance in instances if instance["instance_id"] not in existing_instances]
    logger.info(f"Running quorum on {len(instances)} instances...")

    logger.info(f"Building config from specs: {config_spec}")
    configs = [get_config_from_spec(spec) for spec in config_spec]
    overrides: dict = {
        "environment": {"environment_class": environment_class or UNSET},
        "model": {"model_name": model or UNSET, "model_class": model_class or UNSET},
    }
    if impl_model:
        overrides["quorum"] = {"implementation": {"model": {"model_name": impl_model}}}
    configs.append(overrides)
    config = recursive_merge(*configs)

    progress_manager = RunBatchProgressManager(len(instances), output_path / f"exit_statuses_{time.time()}.yaml")

    def process_futures(futures: dict[concurrent.futures.Future, str]):
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except concurrent.futures.CancelledError:
                pass
            except Exception as e:
                instance_id = futures[future]
                logger.error(f"Error in future for instance {instance_id}: {e}", exc_info=True)
                progress_manager.on_uncaught_exception(instance_id, e)

    with Live(progress_manager.render_group, refresh_per_second=4):
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(process_quorum_instance, instance, output_path, config, progress_manager): instance[
                    "instance_id"
                ]
                for instance in instances
            }
            try:
                process_futures(futures)
            except KeyboardInterrupt:
                logger.info("Cancelling all pending jobs. Press ^C again to exit immediately.")
                for future in futures:
                    if not future.running() and not future.done():
                        future.cancel()
                process_futures(futures)


if __name__ == "__main__":
    app()
