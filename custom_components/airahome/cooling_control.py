"""Decision logic for the cooling dew-point safety net (Phase 3).

Pure functions, no Home Assistant or BLE dependencies, so the policy can be
unit-tested directly. The manager that owns timing (rate-limiting) and performs
the actual BLE writes lives elsewhere and calls :func:`decide_cooling_action`
each time fresh humidity data arrives.

Policy:
- Hold the cooling supply floor (``minimum_supply_setpoint``) at
  ``dew_point + margin`` so flow can never drop to the condensation point.
- Raise the floor promptly (small deadband) but lower it lazily (larger
  deadband): raising is safety, lowering is only comfort/efficiency.
- If ``dew_point + margin`` exceeds the max cooling supply, cooling cannot stay
  above the dew point -> auto-suspend rather than clamp-and-condense.
- Resume from suspend only once there is hysteresis headroom, to avoid flapping.
- Missing/stale humidity -> fail safe by suspending.
"""
from __future__ import annotations

from typing import NamedTuple


class CoolingAction(NamedTuple):
    """A decision. ``write_floor``/``suspend`` are None when no action is needed."""

    target_floor: float | None      # dew_point + margin, clamped (informational)
    write_floor: float | None       # new minimum_supply_setpoint to write, or None
    suspend: bool | None            # True=disable cooling, False=resume, None=leave as-is
    reason: str


def decide_cooling_action(
    *,
    dew_point_c: float | None,
    applied_floor_c: float | None,
    supply_min_c: float,
    supply_max_c: float,
    margin_c: float,
    currently_suspended: bool,
    data_stale: bool,
    raise_deadband_c: float = 0.5,
    lower_deadband_c: float = 1.0,
    resume_hysteresis_c: float = 1.0,
) -> CoolingAction:
    """Decide the cooling supply floor / suspend action for the current conditions.

    ``applied_floor_c`` is the ``minimum_supply_setpoint`` currently believed to be
    on the device (None if unknown). Timing/rate-limiting is the caller's job.
    """
    # 1. Fail safe: no trustworthy humidity reading.
    if data_stale or dew_point_c is None:
        return CoolingAction(
            None, None,
            True if not currently_suspended else None,
            "no or stale humidity data -> suspend cooling",
        )

    target = dew_point_c + margin_c

    # 2. Too humid to cool without condensing -> suspend.
    if target > supply_max_c:
        return CoolingAction(
            target, None,
            True if not currently_suspended else None,
            f"dew point + margin ({target:.1f}) exceeds max supply ({supply_max_c:.1f}) -> suspend",
        )

    desired = min(max(target, supply_min_c), supply_max_c)

    # 3. Currently suspended: only resume once past the hysteresis band.
    suspend: bool | None = None
    if currently_suspended:
        if target <= supply_max_c - resume_hysteresis_c:
            suspend = False  # resume
        else:
            return CoolingAction(
                target, None, None,
                "within resume hysteresis band -> stay suspended",
            )

    # 4. Decide whether to move the floor (asymmetric deadband).
    if applied_floor_c is None:
        return CoolingAction(target, desired, suspend, "no known applied floor -> set")
    delta = desired - applied_floor_c
    if delta >= raise_deadband_c:
        reason, write = "raise floor (dew point rising)", desired
    elif -delta >= lower_deadband_c:
        reason, write = "lower floor (drier)", desired
    elif suspend is False:
        reason, write = "resume: reassert floor", desired
    else:
        reason, write = "within deadband -> no floor change", None
    return CoolingAction(target, write, suspend, reason)
