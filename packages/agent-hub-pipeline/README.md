# agent-hub-pipeline

Installable slice of **Agent Hub** pipeline logic that depends only on the Python standard library:

- Output length hints and continuation detection (`needs_output_top_up`)
- Markdown code-block extraction for deploy artifacts (`extract_code_blocks_from_content`)
- Worktree build command detection (`detect_build_command`)
- Worktree quality heuristics (`verify_worktree_code_quality`)

The full async `execute_stage` / `execute_full_pipeline` stack remains in `backend/app/services/pipeline_engine.py` (SQLAlchemy, LLM, SSE). This package is the reusable core you can publish or import from other projects.

```bash
pip install -e ./packages/agent-hub-pipeline
```
