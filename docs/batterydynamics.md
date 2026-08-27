# Exporting to BatteryDynamics

`to_batterydynamics_json()` creates a self-contained BatteryDynamics task file. The
file contains a JSON list with one task; its `protocolGlobals` and `protocolSteps`
fields contain the embedded BatteryDynamics protocol as JSON-encoded strings.

```python
protocol.to_batterydynamics_json(
    save_path="task.json",
)
```

The exporter fills task data that Unicycler knows:

- sample name and capacity;
- voltage and current safety limits;
- protocol version, steps, and recording intervals.

BatteryDynamics-specific metadata that Unicycler does not model, including channel,
position, battery ID, protocol ID, temperature, and mass, is emitted empty for later
completion # TODO investigate what is needed to run

The initial implementation supports open circuit, constant current,
constant voltage after a matching constant-current step, tags, and finite loops.
Nested loops are supported. 

TODO: Current-change recording and the Unicycler capacity and delay safety fields are rejected until their BatteryDynamics representations are known.

Adjacent CC and CV steps remain separate. This avoids assuming that the native CCCV
step has exactly the same transition semantics.
