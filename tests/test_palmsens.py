"""Tests for PalmSens MethodSCRIPT conversion."""

from __future__ import annotations

import pytest

from aurora_unicycler import (
    ConstantCurrent,
    ConstantVoltage,
    CyclingProtocol,
    ImpedanceSpectroscopy,
    Loop,
    OpenCircuitVoltage,
    RecordParams,
    Tag,
    VoltageScan,
)
from aurora_unicycler.palmsens import PalmSensDevice


def test_palmsens_device_normalization() -> None:
    """Device can be provided as enum or matching string."""
    protocol = CyclingProtocol(
        record=RecordParams(time_s=1),
        method=[OpenCircuitVoltage(until_time_s=2)],
    )
    enum_script = protocol.to_palmsens_methodscript(device=PalmSensDevice.EMSTAT4_HR)
    string_script = protocol.to_palmsens_methodscript(device="emstat4_hr")
    assert enum_script == string_script
    assert enum_script.startswith("e\n")
    assert enum_script.endswith("\n\n")


def test_emstat4_default_variables_are_minimal() -> None:
    """EmStat4 scripts avoid optional add_meas variables by default."""
    protocol = CyclingProtocol(
        record=RecordParams(time_s=1),
        method=[ConstantVoltage(voltage_V=1, until_time_s=2)],
    )
    script = protocol.to_palmsens_methodscript(device=PalmSensDevice.EMSTAT4_HR)
    assert "meas_loop_ca p i 1 1 2" in script
    assert "add_meas(" not in script
    assert "var meas_" not in script
    assert "var f" not in script
    assert "pck_add t" in script
    assert "pck_add p" in script
    assert "pck_add i" in script


def test_emstat4_additional_measurements_are_opt_in() -> None:
    """Supported EmStat4 add_meas variables can be requested explicitly."""
    protocol = CyclingProtocol(
        record=RecordParams(time_s=1),
        method=[ConstantVoltage(voltage_V=1, until_time_s=2)],
    )
    script = protocol.to_palmsens_methodscript(
        device=PalmSensDevice.EMSTAT4_HR,
        additional_measurements=("ab", "ac", "ab"),
    )
    assert "var meas_ab" in script
    assert "var meas_ac" in script
    assert "var meas_ab\nvar meas_ac" in script
    assert "add_meas(0 ab meas_ab)" in script
    assert "add_meas(0 ac meas_ac)" in script
    assert "pck_add meas_ab" in script
    assert "pck_add meas_ac" in script
    assert "add_meas(0 ae meas_ae)" not in script
    assert "add_meas(0 ba meas_ba)" not in script


def test_nexus_additional_measurements_are_opt_in() -> None:
    """Nexus scripts include requested Nexus-specific variables."""
    protocol = CyclingProtocol(
        record=RecordParams(time_s=1),
        method=[ConstantVoltage(voltage_V=1, until_time_s=2)],
    )
    script = protocol.to_palmsens_methodscript(
        device=PalmSensDevice.NEXUS,
        additional_measurements=("ah", "bb"),
    )
    assert script.startswith("e\n")
    assert "add_meas(0 ah meas_ah)" in script
    assert "add_meas(0 bb meas_bb)" in script
    assert "add_meas(0 ai meas_ai)" not in script


def test_constant_current_and_loop_rendering() -> None:
    """CC steps use CP loops and unicycler loops become MethodSCRIPT loops."""
    protocol = CyclingProtocol(
        record=RecordParams(time_s=1),
        sample={"capacity_mAh": 10},
        method=[
            Tag(tag="cycle"),
            ConstantCurrent(rate_C=1, until_voltage_V=2, until_time_s=3),
            Loop(loop_to="cycle", cycle_count=4),
        ],
    )
    script = protocol.to_palmsens_methodscript()
    assert "loop loop_1 < 4i" in script
    assert "meas_loop_cp p i 10m 1 3" in script
    assert "add_meas(" not in script
    assert "if p >= 2" in script


def test_voltage_scan_requires_step_size() -> None:
    """LSV export needs an explicit or record-derived voltage step."""
    protocol = CyclingProtocol(
        record=RecordParams(time_s=1),
        method=[VoltageScan(start_voltage_V=0, end_voltage_V=1, scan_rate_mV_per_s=10)],
    )
    with pytest.raises(ValueError, match="VoltageScan requires"):
        protocol.to_palmsens_methodscript()
    script = protocol.to_palmsens_methodscript(scan_step_voltage_V=0.01)
    assert "meas_loop_lsv p i 0 1 10m 10m" in script


def test_eis_and_geis_rendering() -> None:
    """PEIS and GEIS use MethodSCRIPT EIS loops with AC/DC outputs."""
    peis = CyclingProtocol(
        record=RecordParams(time_s=1),
        method=[
            ImpedanceSpectroscopy(
                amplitude_V=0.01,
                start_frequency_Hz=1000,
                end_frequency_Hz=10,
                points_per_decade=5,
            ),
        ],
    )
    peis_script = peis.to_palmsens_methodscript()
    assert "meas_loop_eis f z_real z_imag 10m 1000 10 11i 0 eis_acdc" in peis_script

    geis = CyclingProtocol(
        record=RecordParams(time_s=1),
        method=[
            ImpedanceSpectroscopy(
                amplitude_mA=1,
                start_frequency_Hz=1000,
                end_frequency_Hz=10,
                points_per_decade=5,
            ),
        ],
    )
    geis_script = geis.to_palmsens_methodscript(eis_dc_current_mA=2)
    assert "meas_loop_geis f z_real z_imag 1m 1000 10 11i 2m eis_acdc" in geis_script


def test_strict_profile_failures() -> None:
    """Out-of-profile values and unsupported devices raise clear errors."""
    protocol = CyclingProtocol(
        record=RecordParams(time_s=1),
        method=[ConstantVoltage(voltage_V=4, until_time_s=1)],
    )
    with pytest.raises(ValueError, match="outside the EmStat4 LR range"):
        protocol.to_palmsens_methodscript(device=PalmSensDevice.EMSTAT4_LR)
    with pytest.raises(ValueError, match="Unsupported PalmSens device"):
        protocol.to_palmsens_methodscript(device="emstat_pico")
    with pytest.raises(ValueError, match="Unsupported additional PalmSens measurement"):
        protocol.to_palmsens_methodscript(additional_measurements=("zz",))


def test_c_rate_without_capacity_raises_value_error() -> None:
    """PalmSens validates C-rate capacity before resolving profile currents."""
    protocol = CyclingProtocol(
        record=RecordParams(time_s=1),
        method=[ConstantCurrent(rate_C=1, until_time_s=1)],
    )
    with pytest.raises(ValueError, match="Sample capacity must be set"):
        protocol.to_palmsens_methodscript()


def test_save_path(tmp_path) -> None:  # noqa: ANN001
    """Exporter optionally writes MethodSCRIPT to disk."""
    protocol = CyclingProtocol(
        record=RecordParams(time_s=1),
        method=[OpenCircuitVoltage(until_time_s=2)],
    )
    path = tmp_path / "method.mscript"
    script = protocol.to_palmsens_methodscript(save_path=path)
    assert path.read_text(encoding="utf-8") == script
