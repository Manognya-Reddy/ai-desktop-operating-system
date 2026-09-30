"""
Ablation experiment runner (spec section 25 / H3).

Runs the retrieval evaluation harness once per signal configuration and
reports how Top-1/Top-3/MRR change as each signal is removed. Since the
benchmark's synthetic project folders carry no real git/browser/terminal
data, the ablations that are informative in this offline harness are
semantic vs keyword-only; git/browser/terminal ablations are included for
completeness and will show their real effect once run against actual
developer workspaces with real git/browser/terminal signal.

Usage (from experiments/evaluation/):
    python run_ablation.py [--no-semantic]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

CONFIGS = {
    "full_pcm": {},
    "no_semantic": {"PCM_SIGNAL_SEMANTIC": "false"},
    "no_git": {"PCM_SIGNAL_GIT": "false"},
    "no_browser": {"PCM_SIGNAL_BROWSER": "false"},
    "no_terminal": {"PCM_SIGNAL_TERMINAL": "false"},
    "no_recent_activity": {"PCM_SIGNAL_RECENT_ACTIVITY": "false"},
    "files_only": {
        "PCM_SIGNAL_SEMANTIC": "false", "PCM_SIGNAL_GIT": "false",
        "PCM_SIGNAL_BROWSER": "false", "PCM_SIGNAL_TERMINAL": "false",
        "PCM_SIGNAL_RECENT_ACTIVITY": "false",
    },
}


def run_config(name: str, env_overrides: dict, force_no_semantic: bool):
    import subprocess
    env = os.environ.copy()
    for k in ["PCM_SIGNAL_SEMANTIC", "PCM_SIGNAL_GIT", "PCM_SIGNAL_BROWSER",
              "PCM_SIGNAL_TERMINAL", "PCM_SIGNAL_RECENT_ACTIVITY"]:
        env.pop(k, None)
    env.update(env_overrides)
    if force_no_semantic:
        env["PCM_SIGNAL_SEMANTIC"] = "false"

    script = os.path.join(os.path.dirname(__file__), "run_retrieval_eval.py")
    args = [sys.executable, script]
    if force_no_semantic:
        args.append("--no-semantic")
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": result.stderr[-2000:]}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "could not parse output", "raw": result.stdout[-2000:]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-semantic", action="store_true")
    args = parser.parse_args()

    all_results = {}
    for name, overrides in CONFIGS.items():
        print(f"Running config: {name}")
        all_results[name] = run_config(name, overrides, args.no_semantic)

    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)
    out_path = os.path.join(results_dir, "ablation_results.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nWrote ablation results to {out_path}")
    print(json.dumps(all_results, indent=2))


if __name__ == "__main__":
    main()
