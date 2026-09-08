"""Finite reasons for pure graph operations."""

from enum import StrEnum


class GraphReason(StrEnum):
    MISSING = "value_unavailable"
    INVALID_NUMBER = "invalid_number"
    DIVISION_BY_ZERO = "division_by_zero"
    INVALID_BOUNDS = "invalid_bounds"
    WHOLE_NUMBER_REQUIRED = "whole_number_required"
    PORTFOLIO_UNAVAILABLE = "portfolio_unavailable"
    COOLDOWN_ACTIVE = "cooldown_active"
    ALREADY_CONSUMED = "already_consumed"
    RESET = "reset"
    STATE_CAPACITY = "state_capacity_exceeded"
    INVALID_KEY = "invalid_key"
    DISABLED = "disabled"
    PLANNED = "planned"
