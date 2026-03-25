#!/usr/bin/env python3

"""Run tournament multi-agent system on SWE-bench instances."""

import concurrent.futures
import json
import time
from pathlib import Path

import typer
from rich.live import Live

from minisweagent.agents.tournament import TournamentOrchestrator
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

_HELP_TEXT = """Run tournament multi-agent system on SWE-bench instances.

[not dim]
FOR SWE-BENCH EVALUATION ONLY. Runs in isolated Docker containers.

Runs 3 strategy agents in parallel, each investigating and patching the issue
independently in its own Docker container:
  - StackTraceTracer: starts from failing tests, traces backwards
  - IssueHypothesis: forms a hypothesis from the PR description, then verifies
  - MinimalDiff: finds the smallest possible change

A judge agent then gets a fresh Docker container, applies each patch, runs tests,
and selects the best one. The winning patch is submitted in SWE-bench format.
[/not dim]
"""

DEFAULT_CONFIG_FILE = builtin_config_dir / "benchmarks" / "swebench_tournament.yaml"

app = typer.Typer(rich_markup_mode="rich", add_completion=False)


def process_tournament_instance(
    instance: dict,
    output_dir: Path,
    config: dict,
    progress_manager: RunBatchProgressManager,
) -> None:
    """Process a single SWE-bench instance with the tournament pipeline."""
    instance_id = instance["instance_id"]
    instance_dir = output_dir / instance_id
    remove_from_preds_file(output_dir / "preds.json", instance_id)
    (instance_dir / f"{instance_id}.traj.json").unlink(missing_ok=True)

    task = instance["problem_statement"]
    exit_status = None
    result = None
    submission = ""

    # Register sub-tasks for each strategy agent
    subtask_ids = {}
    for strategy in ["stack_trace_tracer", "issue_hypothesis", "minimal_diff", "judge"]:
        subtask_id = f"{instance_id}/{strategy}"
        subtask_ids[strategy] = subtask_id

    def on_agent_start(strategy: str):
        sid = subtask_ids[strategy]
        progress_manager.on_instance_start(sid)
        progress_manager.update_instance_status(sid, "Starting...")

    def on_agent_step(strategy: str, step: int, cost: float):
        sid = subtask_ids[strategy]
        progress_manager.update_instance_status(sid, f"Step {step:3d} (${cost:.2f})")

    def on_agent_end(strategy: str, status: str):
        sid = subtask_ids[strategy]
        _remove_subtask(progress_manager, sid)

    orchestrator = TournamentOrchestrator(
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
        logger.error(f"Error processing tournament instance {instance_id}: {e}", exc_info=True)
        exit_status = type(e).__name__
        submission = ""
        result = result or {"agents": [], "judge": None}
    finally:
        # Clean up any remaining subtask spinners
        for sid in subtask_ids.values():
            _remove_subtask(progress_manager, sid)

        if result is not None:
            traj_path = instance_dir / f"{instance_id}.traj.json"
            orchestrator.save(traj_path, result, instance_id)
            logger.info(f"Saved tournament trajectory to '{traj_path}'")

        model_name = config.get("model", {}).get("model_name", "tournament")
        update_preds_file(output_dir / "preds.json", instance_id, model_name, submission)
        progress_manager.on_instance_end(instance_id, exit_status)


def _remove_subtask(progress_manager: RunBatchProgressManager, subtask_id: str):
    """Remove a subtask spinner without advancing the main progress bar."""
    with progress_manager._lock:
        if subtask_id in progress_manager._spinner_tasks:
            try:
                progress_manager._task_progress_bar.remove_task(progress_manager._spinner_tasks[subtask_id])
            except KeyError:
                pass
            del progress_manager._spinner_tasks[subtask_id]


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
    model: str | None = typer.Option(None, "-m", "--model", help="Model for strategy agents", rich_help_panel="Basic"),
    judge_model: str | None = typer.Option(None, "--judge-model", help="Model for judge (defaults to strategy model)", rich_help_panel="Basic"),
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
    logger.info(f"Running tournament on {len(instances)} instances...")

    logger.info(f"Building config from specs: {config_spec}")
    configs = [get_config_from_spec(spec) for spec in config_spec]
    overrides = {
        "environment": {"environment_class": environment_class or UNSET},
        "model": {"model_name": model or UNSET, "model_class": model_class or UNSET},
    }
    if judge_model:
        overrides["tournament"] = {"judge": {"model": {"model_name": judge_model}}}
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
                executor.submit(process_tournament_instance, instance, output_path, config, progress_manager): instance[
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
