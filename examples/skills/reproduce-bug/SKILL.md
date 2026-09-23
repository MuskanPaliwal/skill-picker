---
name: reproduce-bug
description: Create the smallest reliable reproduction for a reported bug. Use when a failure is unclear, intermittent, user-reported, or not yet proven locally.
user-invocable: true
---

# Reproduce a bug

Start from the report, not the code. Establish the exact conditions that make
the failure appear, then remove everything that does not change the outcome.

1. Capture the reported symptom, environment, and frequency.
2. Build a runnable case that fails on demand.
3. Shrink it until every remaining line matters.
