# Contributing to Angelique

Thank you for contributing to Angelique. This guide explains how to propose improvements and submit code safely.

## Development Workflow

1. Create a feature branch from `main`.
2. Install the Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Run tests if available:

```bash
pytest
```

## Code Guidelines

- Keep tool integrations decoupled in `core/tools.py`.
- Add new skills under `skills/` and register them in the tool registry.
- Self-evolution logic lives in `skills/self_evolution/code_generator.py`.
- Avoid LLM hallucinations by preferring deterministic tool routing in `brain/cognitive_loop.py`.

## Commit Messages

- Use clear, descriptive commits.
- Prefer one feature or fix per commit.

## Pull Requests

- Explain the problem and your solution.
- Include verification steps.
- Keep changes small and focused.
