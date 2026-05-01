# Phase 2: CI Pipeline

**Goal:** Automated quality gate runs on every push to main.
**Status:** Complete

## Context

Following the stabilization of tests in Phase 1, Phase 2 implements a robust Continuous Integration (CI) pipeline. This ensures that every code change is validated against the test suite and complies with linting standards before being merged. The pipeline must handle the unique requirement of building the LADR binaries (Prover9/Mace4) from source to support theorem-proving tests in the CI environment.

## Requirements

- [x] **TEST-03**: GitHub Actions CI implementation.

## Tasks

### 1. Implementation: GitHub Actions Workflow (TEST-03)

- [x] Create `.github/workflows/ci.yml`.
- [x] **Job: test**
  - [x] OS: `ubuntu-latest`.
  - [x] Step: Checkout code.
  - [x] Step: Set up Python 3.10+ using `astral-sh/setup-uv`.
  - [x] Step: Install dependencies via `uv sync`.
  - [x] Step: Build LADR (`cd ladr && make all`).
  - [x] Step: Run `pytest` with coverage report.
- [x] **Job: lint**
  - [x] Step: Checkout code.
  - [x] Step: Run `trunk-io/trunk-action@v1`.

### 2. Lint Baselining & Noise Reduction

- [x] Configure `.trunk/trunk.yaml` to handle `bandit/B101` (asserts in tests).
- [x] Ensure `trunk check` passes locally on all files (baselining if necessary).

## Verification Plan

### Automated Tests

- [x] Push `.github/workflows/ci.yml` and monitor GitHub Actions.
- [x] Verify `test` job succeeds (confirming LADR built and tests found it).
- [x] Verify `lint` job succeeds.

### Manual Verification

- [x] Review CI logs for `test_proofs.py` to confirm it didn't skip Prover9 tests (unless binaries truly failed to build).
- [x] Add a CI status badge to `README.md`.
