#!/usr/bin/env python3
"""Seed the orchestrator task board from config/project-tasks.json (idempotent).

Run from the canonical checkout root:
  ORCH_STATUS_ROOT=$PWD python3 tools/development-orchestrator/config/seed_tasks.py
Existing task ids are left untouched; only missing tasks are assigned.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLI = HERE.parent / "bin" / "ai_status.py"
root = Path(os.environ.get("ORCH_STATUS_ROOT") or os.getcwd())
status = root / "ai-status.json"
existing = set()
if status.exists() and status.read_text(encoding="utf-8").strip():
    existing = {t["id"] for t in json.loads(status.read_text(encoding="utf-8")).get("tasks", [])}
tasks = json.loads((HERE / "project-tasks.json").read_text(encoding="utf-8"))["tasks"]
created = 0
for t in tasks:
    if t["id"] in existing:
        print(f"KEEP   {t['id']}")
        continue
    env = dict(os.environ, AI_NAME="Supervisor", ORCH_STATUS_ROOT=str(root), AI_STATUS_ROOT=str(root),
               TASK_PHASE=t.get("phase", "Implementation"),
               TASK_DEPENDS_ON=",".join(t.get("depends_on", [])),
               TASK_ARTIFACTS=",".join(t.get("artifacts", [])),
               TASK_METADATA_JSON=json.dumps({k: t[k] for k in ("task_spec_ref", "write_scopes") if k in t}, ensure_ascii=False))
    if t.get("summary_zh"):
        env["TASK_SUMMARY_ZH"] = t["summary_zh"]
    subprocess.run([sys.executable, str(CLI), "assign", t["id"], t["owner"], t["reviewer"], t["title"]], env=env, check=True,
                   stdout=subprocess.DEVNULL)
    created += 1
    print(f"ASSIGN {t['id']} owner={t['owner']} reviewer={t['reviewer']}")
print(json.dumps({"created": created, "total": len(tasks)}))
