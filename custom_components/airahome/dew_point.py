"""Dew-point helpers for the cooling condensation safety net.

Cooling with a low supply-water temperature risks condensation on pipes and
emitters whenever their surface drops to the indoor air's dew point. These
helpers compute the dew point from the room air temperature and relative
humidity, and turn it into a recommended cooling supply-temperature floor.

Pure functions with no Home Assistant dependencies so they can be unit-tested
directly.
"""
from __future__ import annotations

import math

# Magnus-Tetens formula with the Alduchov-Eskridge (1996) coefficients, which
# give <0.4% error over roughly -40..50 C / 1..100 %RH.
_MAGNUS_A = 17.625
_MAGNUS_B = 243.04  # degrees C


def dew_point(temperature_c: float | None, relative_humidity_pct: float | None) -> float | None:
    """Return the dew point in C for an air temperature and relative humidity.

    Returns ``None`` when an input is missing or the humidity is outside the
    ``0 < RH <= 100`` range where the formula is defined.
    """
    if temperature_c is None or relative_humidity_pct is None:
        return None
    if not 0 < relative_humidity_pct <= 100:
        return None
    gamma = math.log(relative_humidity_pct / 100.0) + _MAGNUS_A * temperature_c / (_MAGNUS_B + temperature_c)
    return _MAGNUS_B * gamma / (_MAGNUS_A - gamma)


def cooling_supply_floor(
    dew_point_c: float | None,
    margin_c: float,
    supply_min_c: float,
    supply_max_c: float,
) -> tuple[float | None, bool]:
    """Recommended cooling supply floor as ``(floor, cooling_advised)``.

    The target floor is ``dew_point + margin``. ``cooling_advised`` is ``False``
    when that target exceeds ``supply_max`` — the flow could not stay the margin
    above the dew point without dropping below the device's maximum cooling
    supply, so cooling should be suspended rather than clamped (clamping to the
    max would put the flow at/below the dew point and actively condense). The
    returned ``floor`` is always clamped into ``[supply_min, supply_max]`` so it
    is safe to apply directly as a ``minimum_supply_setpoint``.
    """
    if dew_point_c is None:
        return None, False
    target = dew_point_c + margin_c
    cooling_advised = target <= supply_max_c
    floor = min(max(target, supply_min_c), supply_max_c)
    return floor, cooling_advised
