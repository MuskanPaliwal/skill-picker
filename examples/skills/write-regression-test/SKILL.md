---
name: write-regression-test
description: Turn a confirmed reproduction into a focused failing automated test before changing production code.
user-invocable: true
---

# Write a regression test

A reproduction proves the bug exists today. A regression test proves it stays
fixed tomorrow.

1. Assert the user-visible behavior, not the current implementation.
2. Watch the test fail for the reported reason before writing the fix.
3. Keep the test at the smallest layer that still catches the bug.
