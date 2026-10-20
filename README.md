# Emotion Analyzer

Recognises a speaker's emotion from a short voice recording by combining how it sounds and what is said. It runs offline on a laptop CPU in about one second.

> Work in progress. This README becomes the full user guide (install, run, train, deploy, citations) in Phase 10. The design lives in `specs.md`.

## Install (local, Windows)

Working directory: `E:\AIDS\Project\emotion-analyzer`

```
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e .
git config core.hooksPath .githooks
```

## Run the tests

Working directory: `E:\AIDS\Project\emotion-analyzer`

```
.venv\Scripts\python.exe -m pytest -m "not slow"
```
