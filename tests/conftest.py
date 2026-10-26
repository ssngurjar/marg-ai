"""Shared test configuration: Hypothesis profiles (CLAUDE.md §3)."""

import os

from hypothesis import settings

settings.register_profile("dev", max_examples=100, deadline=None)
settings.register_profile("ci", max_examples=300, deadline=None, derandomize=True, print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
