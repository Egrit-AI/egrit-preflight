# Target description fixtures

Synthetic test data for the design note [docs/target-neutral-design.md](../../../docs/target-neutral-design.md). Nothing
here was read from a machine or a device, and nothing here is a report.

- `x86-64-cpu.declared.json`, `jetson.declared.json`: target records in the format `--target` reads today, plus the
  `architecture` and `accelerator` fields the design note discusses. Both are `declared`.
- `assessment-sketch.*.json`: the shape of a separate target assessment document, **design only**. No release produces
  it, and the schema version 1 reader must reject it.

`tests/test_target_neutral_design.py` checks what the current tool does with these, and that none of them can be read
as a hardware result.
