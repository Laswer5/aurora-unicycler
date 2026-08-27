# Copyright (c) 2025 Empa
"""Tests for BatteryDynamics task export."""

import json
from pathlib import Path

import pytest

from aurora_unicycler import (
    ConstantCurrent,
    ConstantVoltage,
    CyclingProtocol,
    ImpedanceSpectroscopy,
    Loop,
    OpenCircuitVoltage,
    RecordParams,
    SafetyParams,
    SampleParams,
    Tag,
)


def _task_protocol() -> CyclingProtocol:
    """Build a representative supported protocol."""
    return CyclingProtocol(
        sample=SampleParams(name="cell-001", capacity_mAh=2000),
        record=RecordParams(time_s=10, voltage_V=0.01),
        safety=SafetyParams(
            max_voltage_V=4.3,
            min_voltage_V=2.5,
            max_current_mA=2000,
            min_current_mA=-1500,
        ),
        method=[
            Tag(tag="cycle"),
            ConstantCurrent(
                rate_C=0.5,
                until_voltage_V=4.2,
                until_time_s=3600,
            ),
            ConstantVoltage(
                voltage_V=4.2,
                until_rate_C=0.05,
                until_time_s=600,
            ),
            OpenCircuitVoltage(until_time_s=60),
            ConstantCurrent(current_mA=-500, until_voltage_V=2.5),
            Loop(loop_to="cycle", cycle_count=3),
        ],
    )


def test_to_batterydynamics_json() -> None:
    """Task metadata, embedded JSON, steps, units, and loops are exported."""
    output = json.loads(_task_protocol().to_batterydynamics_json())
    assert len(output) == 1
    task = output[0]
    assert task["taskName"] == "cell-001"
    assert task["channelID"] is None
    assert task["protocolID"] is None
    assert task["protocolName"] == ""
    assert task["batteryC_Ah"] == 2
    assert task["batteryVMax_V"] == 4.3
    assert task["batteryVMin_V"] == 2.5
    assert task["batteryIMax_A"] == 2
    assert task["batteryIMin_A"] == 1.5
    assert task["protocolVersion"] == "2.2"

    globals_dict = json.loads(task["protocolGlobals"])
    assert globals_dict["constants"] == []
    assert globals_dict["variables"] == []
    assert [formula["name"] for formula in globals_dict["formulas"]] == [
        "CALC1",
        "CALC2",
        "CALC3",
        "CALC4",
    ]

    steps = json.loads(task["protocolSteps"])
    assert [step["id"] for step in steps] == [1, 6]
    assert [step["type"] for step in steps] == ["LOOP_START", "LOOP_END"]
    assert steps[0]["repetitions"] == "3"
    nested = steps[0]["steps"]
    assert [step["id"] for step in nested] == [2, 3, 4, 5]
    assert [step["type"] for step in nested] == [
        "CHARGE_CC",
        "CHARGE_CV",
        "PAUSE",
        "DISCHARGE_CC",
    ]

    charge = nested[0]["content"]
    assert charge["parameters"] == [{"property": "I", "value": 0.5, "unit": "CA"}]
    assert charge["endConditions"] == [
        {"property": "V", "value": 4.2, "unit": "V", "operator": ">", "action": "NEXT"},
        {
            "property": "t_step",
            "value": 3600,
            "unit": "s",
            "operator": ">",
            "action": "NEXT",
        },
    ]
    assert charge["recordIntervals"] == [
        {"property": "dt", "value": 10, "unit": "s"},
        {"property": "dV", "value": 10, "unit": "mV"},
    ]

    cv = nested[1]["content"]
    assert cv["parameters"] == [
        {"property": "V", "value": 4.2, "unit": "V"},
        {"property": "I_max", "value": 0.5, "unit": "CA"},
    ]
    assert cv["endConditions"][0] == {
        "property": "I",
        "value": 0.05,
        "unit": "CA",
        "operator": "<",
        "action": "NEXT",
    }


def test_to_batterydynamics_json_save(tmp_path: Path) -> None:
    """The returned and saved JSON are identical."""
    path = tmp_path / "task.json"
    output = _task_protocol().to_batterydynamics_json(path)
    assert path.read_text(encoding="utf-8") == output


def test_nested_loops() -> None:
    """Nested Unicycler loops become nested BatteryDynamics loop containers."""
    protocol = CyclingProtocol(
        record=RecordParams(time_s=1),
        method=[
            Tag(tag="outer"),
            OpenCircuitVoltage(until_time_s=1),
            Tag(tag="inner"),
            ConstantCurrent(current_mA=1, until_time_s=1),
            Loop(loop_to="inner", cycle_count=2),
            Loop(loop_to="outer", cycle_count=3),
        ],
    )
    task = json.loads(protocol.to_batterydynamics_json())[0]
    steps = json.loads(task["protocolSteps"])
    outer = steps[0]
    assert outer["type"] == "LOOP_START"
    assert outer["repetitions"] == "3"
    assert [step["type"] for step in outer["steps"]] == [
        "PAUSE",
        "LOOP_START",
        "LOOP_END",
    ]
    inner = outer["steps"][1]
    assert inner["repetitions"] == "2"
    assert [step["type"] for step in inner["steps"]] == ["CHARGE_CC"]
    assert [step["id"] for step in steps] == [1, 6]


@pytest.mark.parametrize(
    ("protocol", "match"),
    [
        (
            CyclingProtocol(
                record=RecordParams(time_s=1, current_mA=0.1),
                method=[OpenCircuitVoltage(until_time_s=1)],
            ),
            "current-change recording",
        ),
        (
            CyclingProtocol(
                record=RecordParams(time_s=1),
                method=[ConstantVoltage(voltage_V=4.2, until_time_s=1)],
            ),
            "requires a preceding constant-current",
        ),
        (
            CyclingProtocol(
                record=RecordParams(time_s=1),
                method=[
                    ImpedanceSpectroscopy(
                        amplitude_V=0.01,
                        start_frequency_Hz=1000,
                        end_frequency_Hz=1,
                    ),
                ],
            ),
            "does not support step type: impedance_spectroscopy",
        ),
    ],
)
def test_unknown_mappings_fail_explicitly(protocol: CyclingProtocol, match: str) -> None:
    """Unknown mappings are rejected rather than silently approximated."""
    with pytest.raises(NotImplementedError, match=match):
        protocol.to_batterydynamics_json()


def test_unknown_safety_mappings_fail_explicitly() -> None:
    """Unsupported safety fields are rejected rather than omitted."""
    protocol = CyclingProtocol(
        record=RecordParams(time_s=1),
        safety=SafetyParams(max_capacity_mAh=10),
        method=[OpenCircuitVoltage(until_time_s=1)],
    )
    with pytest.raises(NotImplementedError, match="max_capacity_mAh"):
        protocol.to_batterydynamics_json()
