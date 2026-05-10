With a `CyclingProtocol` object, use `to_palmsens_methodscript()`.

```python
from aurora_unicycler.palmsens import PalmSensDevice

methodscript = my_protocol.to_palmsens_methodscript(
    sample_name="test-sample",
    capacity_mAh=45,
    device=PalmSensDevice.EMSTAT4_HR,
    save_path="some/location/method.mscript",
)
```

This returns a PalmSens MethodSCRIPT string, and optionally saves it to a file.

### Supported devices

Only Palmsens devices with galvanostatic control are currently supported. This includes:

- `PalmSensDevice.EMSTAT4_HR`
- `PalmSensDevice.EMSTAT4_LR`
- `PalmSensDevice.NEXUS`

Matching string values (`"emstat4_hr"`, `"emstat4_lr"`, `"nexus"`) are also
accepted, so importing the enum is optional.

The `channel` option selects the instrument PGStat channel. Not all Palmsens instruments have multiple PGStat channels; the default
`channel=0` selects the first channel and should be supported on all supported
instruments.

### Recorded variables

For MethodSCRIPT measurement loops that support `add_meas`, the exporter adds
all supported measured variables for the selected device profile. EmStat4
profiles record:

- `ab` / `VT_POTENTIAL`
- `ac` / `VT_POTENTIAL_CE`
- `ae` / `VT_POTENTIAL_RE`
- `ag` / `VT_POTENTIAL_WE_VS_CE`
- `as` / `VT_POTENTIAL_AIN0`
- `ba` / `VT_CURRENT`

Nexus additionally records its supported extra variables, such as bipot current,
temperature, and second-sense potentials.

Each packet includes timing where the MethodSCRIPT command supports it, the
primary outputs for the technique, and the configured measured variables.

### Notes

- `record.time_s` is required because it sets the MethodSCRIPT measurement loop
  cadence for OCV, constant-current, and constant-voltage steps.
- `VoltageScan` is exported as `meas_loop_lsv`. It needs
  `scan_step_voltage_V`, or falls back to `record.voltage_V`.
- Device voltage, current, and EIS limits are checked before rendering.
