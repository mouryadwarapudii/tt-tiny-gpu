<!---

This file is staged for use as docs/info.md in an actual Tiny Tapeout project repo (see the
note at the top of tt/info.yaml for how to set that up). It generates the project's datasheet
page once submitted.

-->

## How it works

This project is [tiny-gpu](https://github.com/adam-maj/tiny-gpu), a minimal educational GPU
implementation, wrapped for Tiny Tapeout. tiny-gpu executes a small custom 11-instruction ISA
(`ADD`/`SUB`/`MUL`/`DIV`, `LDR`/`STR`, `LDS`/`STS`, `CMP`/`BRnzp`, `CONST`, `RET`) across
multiple SIMD cores, each with its own private L1 cache, register files, ALUs, and load-store
units, backed by a shared L2 cache and an on-chip shared-memory scratchpad per core.

tiny-gpu's native interface is far wider than Tiny Tapeout's pin budget (separate wide buses for
program memory, 4-channel data memory, and device control), so `tt_adapter` puts small on-chip
program/data memories directly behind the GPU's existing async memory ports, and exposes a
simple byte-serial command protocol over the 24 available pins instead:

- `ui[7:0]` carries one command or data byte at a time from the host
- `uo[7:0]` carries one response byte at a time back to the host
- `uio[0]`/`uio[1]` are a standard ready/valid handshake for the host->chip byte
- `uio[2]`/`uio[3]` are a standard valid/ready handshake for the chip->host response byte
- `uio[4]` mirrors the GPU's kernel-done signal directly, for cheap polling

Commands (first byte of each transaction on `ui`):

| Opcode | Name | Args | Effect |
|---|---|---|---|
| `0x01` | `WRITE_PROGRAM_WORD` | addr, data_lo, data_hi | `program_mem[addr] = {data_hi, data_lo}` |
| `0x02` | `WRITE_DATA_BYTE` | addr, data | `data_mem[addr] = data` |
| `0x03` | `READ_DATA_BYTE` | addr | responds with `data_mem[addr]` |
| `0x04` | `SET_THREAD_COUNT` | count | sets the kernel's thread count |
| `0x05` | `START` | (none) | launches the kernel |
| `0x06` | `KERNEL_RESET` | (none) | resets the GPU (not the whole chip) so a new kernel can be loaded |

## How to test

1. Load a program (repeat `WRITE_PROGRAM_WORD` for each instruction) and initial data
   (repeat `WRITE_DATA_BYTE` for each byte).
2. `SET_THREAD_COUNT` with the number of threads the kernel should launch.
3. `START` the kernel.
4. Poll `uio[4]` (done) until it goes high.
5. `READ_DATA_BYTE` to read back results from data memory.

See `test/test_tt_adapter.py` in the main tiny-gpu repo for a complete worked example that
drives an 8-thread matrix-addition kernel through this exact protocol and checks the results.

## External hardware

None - this project is entirely self-contained and communicates over the standard Tiny Tapeout
pin header.
