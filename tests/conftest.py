# SPDX-License-Identifier: GPL-3.0-only
"""Shared test paths."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIRST_ORDER_MODEL = PROJECT_ROOT / "examples" / "control" / "first_order.xcos"
COUPLED_LEO_MODEL = PROJECT_ROOT / "examples" / "space" / "coupled_leo" / "coupled_leo.xcos"
