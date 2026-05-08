# AGENTS Guide - Research Pipeline

## Purpose

Dr. Claw Research Lab pipeline directories for survey, ideation, experimentation, publication, and promotion stages.

## Directory Structure

```
Survey/           # Literature survey and industry analysis
├── references/   # BibTeX and paper collections
└── reports/      # Survey reports and summaries

Ideation/         # Research idea generation and refinement
├── ideas/        # Idea documents and proposals
└── references/   # Supporting references

Experiment/       # Experimental work and validation
├── analysis/     # Result analysis
├── code_references/ # Code snippets and references
├── core_code/    # Core experimental implementations
└── datasets/     # Experimental datasets

Publication/      # Paper writing and submission
└── paper/        # LaTeX source and figures

Promotion/        # Research promotion materials
├── audio/        # Podcast/audio content
├── homepage/     # Project website
├── slides/       # Presentation decks
└── video/        # Video content
```

## Integration Points

- **With docs/survey/**: Survey reports feed into `Survey/reports/`
- **With docs/benchmarks/**: Experimental results feed into `Experiment/analysis/`
- **With model/**: Core code experiments may reference model implementations

## Status

Research pipeline in progress. Check `.pipeline/docs/research_brief.json` for current stage.

## Next Steps

- For current stage: check `.pipeline/tasks/tasks.json`
- For system specs: see `docs/architecture/AGENTS.md`
- For benchmarks: see `docs/benchmarks/AGENTS.md`
