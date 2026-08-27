# Copyright (c) 2025 Empa
"""Export BatteryDynamics task JSON files."""

import json
from pathlib import Path
from typing import Any

from aurora_unicycler import _core, _utils


def _record_intervals(record: _core.RecordParams) -> list[dict[str, Any]]:
    """Convert global Unicycler recording settings to per-step intervals."""
    if record.current_mA is not None:
        msg = "BatteryDynamics current-change recording intervals are not yet known."
        raise NotImplementedError(msg)

    intervals: list[dict[str, Any]] = [
        {"property": "dt", "value": record.time_s, "unit": "s"},
    ]
    if record.voltage_V is not None:
        intervals.append(
            {"property": "dV", "value": record.voltage_V * 1000, "unit": "mV"},
        )
    return intervals


def _value(property_name: str, value: float, unit: str) -> dict[str, Any]:
    """Build a literal BatteryDynamics parameter."""
    return {"property": property_name, "value": abs(value), "unit": unit}


def _condition(
    property_name: str,
    value: float,
    unit: str,
    operator: str,
) -> dict[str, Any]:
    """Build a literal BatteryDynamics NEXT condition."""
    return {
        "property": property_name,
        "value": abs(value),
        "unit": unit,
        "operator": operator,
        "action": "NEXT",
    }


def _current(step: _core.ConstantCurrent) -> tuple[float, str]:
    """Return a CC setpoint in a native BatteryDynamics unit."""
    if step.rate_C is not None:
        return step.rate_C, "CA"
    assert step.current_mA is not None  # noqa: S101 - guaranteed by Pydantic
    return step.current_mA, "mA"


def _ocv_step(
    step: _core.OpenCircuitVoltage,
    record_intervals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert an open-circuit step."""
    return {
        "type": "PAUSE",
        "content": {
            "parameters": [],
            "endConditions": [_condition("t_step", step.until_time_s, "s", ">")],
            "recordIntervals": record_intervals,
        },
    }


def _cc_step(
    step: _core.ConstantCurrent,
    record_intervals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert a constant-current step."""
    current, unit = _current(step)
    charging = current > 0
    conditions: list[dict[str, Any]] = []
    if step.until_voltage_V is not None:
        conditions.append(
            _condition("V", step.until_voltage_V, "V", ">" if charging else "<"),
        )
    if step.until_time_s is not None:
        conditions.append(_condition("t_step", step.until_time_s, "s", ">"))

    return {
        "type": "CHARGE_CC" if charging else "DISCHARGE_CC",
        "content": {
            "parameters": [_value("I", current, unit)],
            "endConditions": conditions,
            "recordIntervals": record_intervals,
        },
    }


def _cv_step(
    step: _core.ConstantVoltage,
    previous_step: _core.AnyTechnique | None,
    record_intervals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert CV after a matching CC step, from which I_max and direction are known."""
    if not isinstance(previous_step, _core.ConstantCurrent):
        msg = "BatteryDynamics CV export requires a preceding constant-current step."
        raise NotImplementedError(msg)
    if previous_step.until_voltage_V != step.voltage_V:
        msg = "BatteryDynamics CV export requires the preceding CC voltage to match the CV voltage."
        raise NotImplementedError(msg)

    previous_current, current_unit = _current(previous_step)
    charging = previous_current > 0
    cutoff_current: float | None = None
    cutoff_unit = ""
    if step.until_rate_C is not None:
        cutoff_current = step.until_rate_C
        cutoff_unit = "CA"
    elif step.until_current_mA is not None:
        cutoff_current = step.until_current_mA
        cutoff_unit = "mA"

    if cutoff_current is not None and (cutoff_current > 0) != charging:
        msg = "BatteryDynamics CV cutoff-current direction must match the preceding CC step."
        raise ValueError(msg)

    conditions: list[dict[str, Any]] = []
    if cutoff_current is not None:
        conditions.append(_condition("I", cutoff_current, cutoff_unit, "<"))
    if step.until_time_s is not None:
        conditions.append(_condition("t_step", step.until_time_s, "s", ">"))

    return {
        "type": "CHARGE_CV" if charging else "DISCHARGE_CV",
        "content": {
            "parameters": [
                _value("V", step.voltage_V, "V"),
                _value("I_max", previous_current, current_unit),
            ],
            "endConditions": conditions,
            "recordIntervals": record_intervals,
        },
    }


def _render_method(protocol: _core.BaseProtocol) -> list[dict[str, Any]]:
    """Convert a flat Unicycler method into nested BatteryDynamics steps."""
    record_intervals = _record_intervals(protocol.record)
    # Each node remembers the zero-based source index at which it starts. A Loop
    # replaces the tail beginning at loop_to with a nested LOOP_START/LOOP_END pair.
    nodes: list[tuple[int, list[dict[str, Any]]]] = []

    for index, step in enumerate(protocol.method):
        previous_step = protocol.method[index - 1] if index else None
        if isinstance(step, _core.OpenCircuitVoltage):
            rendered = _ocv_step(step, record_intervals)
        elif isinstance(step, _core.ConstantCurrent):
            rendered = _cc_step(step, record_intervals)
        elif isinstance(step, _core.ConstantVoltage):
            rendered = _cv_step(step, previous_step, record_intervals)
        elif isinstance(step, _core.Loop):
            assert isinstance(step.loop_to, int)  # noqa: S101 - tags already resolved
            loop_start = step.loop_to - 1
            try:
                node_index = next(i for i, node in enumerate(nodes) if node[0] == loop_start)
            except StopIteration as exc:
                msg = f"BatteryDynamics loop start {step.loop_to} cannot be represented."
                raise NotImplementedError(msg) from exc
            nested_steps = [item for _, output in nodes[node_index:] for item in output]
            nodes[node_index:] = [
                (
                    loop_start,
                    [
                        {
                            "type": "LOOP_START",
                            "repetitions": str(step.cycle_count),
                            "steps": nested_steps,
                        },
                        {"type": "LOOP_END"},
                    ],
                ),
            ]
            continue
        else:
            msg = f"BatteryDynamics export does not support step type: {step.step}"
            raise NotImplementedError(msg)
        nodes.append((index, [rendered]))

    rendered_method = [item for _, output in nodes for item in output]
    _assign_step_ids(rendered_method)
    return rendered_method


def _assign_step_ids(steps: list[dict[str, Any]], next_id: int = 1) -> int:
    """Assign sequential IDs in the same pre-order used by the example files."""
    for step in steps:
        step["id"] = next_id
        next_id += 1
        if step["type"] == "LOOP_START":
            next_id = _assign_step_ids(step["steps"], next_id)
    return next_id


def _validate_safety(safety: _core.SafetyParams) -> None:
    """Reject safety settings for which no task-file mapping is known."""
    if safety.max_capacity_mAh is not None:
        msg = "BatteryDynamics task mapping for safety.max_capacity_mAh is not yet known."
        raise NotImplementedError(msg)
    if safety.delay_s is not None:
        msg = "BatteryDynamics task mapping for safety.delay_s is not yet known."
        raise NotImplementedError(msg)


def to_batterydynamics_json(
    protocol: _core.BaseProtocol,
    save_path: Path | str | None = None,
) -> str:
    """Convert a protocol to a self-contained BatteryDynamics task JSON file."""
    protocol = protocol.model_copy(deep=True)
    _utils.validate_capacity_c_rates(protocol)
    _utils.tag_to_indices(protocol)
    _utils.check_for_intersecting_loops(protocol)
    _validate_safety(protocol.safety)

    formulas = [
        {"enabled": False, "name": f"CALC{i}", "operator": "none"} for i in range(1, 5)
    ]
    globals_dict = {"formulas": formulas, "constants": [], "variables": []}
    steps = _render_method(protocol)
    sample_name = protocol.sample.name if protocol.sample.name != "$NAME" else ""

    task = {
        "channelID": None,
        "position": None,
        "taskName": sample_name,
        "batteryID": None,
        "batteryModel": "",
        "batteryNumber": "",
        "protocolID": None,
        "protocolName": "",
        "project": "",
        "batteryC_Ah": (
            protocol.sample.capacity_mAh / 1000
            if protocol.sample.capacity_mAh is not None
            else None
        ),
        "batteryVMax_V": protocol.safety.max_voltage_V,
        "batteryVMin_V": protocol.safety.min_voltage_V,
        "batteryIMax_A": (
            abs(protocol.safety.max_current_mA) / 1000
            if protocol.safety.max_current_mA is not None
            else None
        ),
        "batteryIMin_A": (
            abs(protocol.safety.min_current_mA) / 1000
            if protocol.safety.min_current_mA is not None
            else None
        ),
        "batteryTMax_dC": None,
        "protocolVersion": "2.2",
        "protocolGlobals": json.dumps(globals_dict, separators=(",", ":")),
        "protocolSteps": json.dumps(steps, separators=(",", ":")),
        "optionBits": 0,
        "comment": None,
        "batteryMass_g": None,
    }
    output = json.dumps([task], indent=4)
    if save_path:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(output, encoding="utf-8")
    return output
