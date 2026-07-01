import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

OPCODE_WRITE_PROG = 0x01
OPCODE_WRITE_DATA = 0x02
OPCODE_READ_DATA = 0x03
OPCODE_SET_THREADS = 0x04
OPCODE_START = 0x05

UIO_IN_READY = 0x01   # adapter -> host (bit 0)
UIO_IN_VALID = 0x02   # host -> adapter (bit 1)
UIO_OUT_VALID = 0x04  # adapter -> host (bit 2)
UIO_OUT_READY = 0x08  # host -> adapter (bit 3)
UIO_DONE = 0x10       # adapter -> host (bit 4)


async def send_byte(dut, value):
    while (int(dut.uio_out.value) & UIO_IN_READY) == 0:
        await RisingEdge(dut.clk)
    dut.ui_in.value = value
    dut.uio_in.value = int(dut.uio_in.value) | UIO_IN_VALID
    await RisingEdge(dut.clk)
    dut.uio_in.value = int(dut.uio_in.value) & ~UIO_IN_VALID & 0xFF
    # Force at least one full idle cycle with in_valid low before the next byte can be
    # presented - otherwise, if in_ready is already back up, the next send_byte() call's
    # "set valid" write can land in the same simulation instant as this "clear valid" write,
    # so the adapter would never actually observe in_valid deasserted between bytes.
    await RisingEdge(dut.clk)


async def read_byte(dut):
    while (int(dut.uio_out.value) & UIO_OUT_VALID) == 0:
        await RisingEdge(dut.clk)
    value = int(dut.uo_out.value)
    dut.uio_in.value = int(dut.uio_in.value) | UIO_OUT_READY
    await RisingEdge(dut.clk)
    dut.uio_in.value = int(dut.uio_in.value) & ~UIO_OUT_READY & 0xFF
    await RisingEdge(dut.clk)
    return value


async def write_program_word(dut, addr, data16):
    await send_byte(dut, OPCODE_WRITE_PROG)
    await send_byte(dut, addr)
    await send_byte(dut, data16 & 0xFF)
    await send_byte(dut, (data16 >> 8) & 0xFF)


async def write_data_byte(dut, addr, data):
    await send_byte(dut, OPCODE_WRITE_DATA)
    await send_byte(dut, addr)
    await send_byte(dut, data)


async def read_data_byte(dut, addr):
    await send_byte(dut, OPCODE_READ_DATA)
    await send_byte(dut, addr)
    return await read_byte(dut)


async def set_thread_count(dut, count):
    await send_byte(dut, OPCODE_SET_THREADS)
    await send_byte(dut, count)


async def start_kernel(dut):
    await send_byte(dut, OPCODE_START)


@cocotb.test()
async def test_tt_adapter_matadd(dut):
    # Drives an 8-thread matrix-addition kernel entirely through the Tiny Tapeout pin-level
    # byte-serial protocol (see docs/info.md) - this is the interface a real host would use.
    clock = Clock(dut.clk, 25, unit="us")
    cocotb.start_soon(clock.start())

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    program = [
        0b0101000011011110, # MUL R0, %blockIdx, %blockDim
        0b0011000000001111, # ADD R0, R0, %threadIdx         ; i = blockIdx * blockDim + threadIdx
        0b1001000100000000, # CONST R1, #0                   ; baseA (matrix A base address)
        0b1001001000001000, # CONST R2, #8                   ; baseB (matrix B base address)
        0b1001001100010000, # CONST R3, #16                  ; baseC (matrix C base address)
        0b0011010000010000, # ADD R4, R1, R0                 ; addr(A[i]) = baseA + i
        0b0111010001000000, # LDR R4, R4                     ; load A[i] from global memory
        0b0011010100100000, # ADD R5, R2, R0                 ; addr(B[i]) = baseB + i
        0b0111010101010000, # LDR R5, R5                     ; load B[i] from global memory
        0b0011011001000101, # ADD R6, R4, R5                 ; C[i] = A[i] + B[i]
        0b0011011100110000, # ADD R7, R3, R0                 ; addr(C[i]) = baseC + i
        0b1000000001110110, # STR R7, R6                     ; store C[i] in global memory
        0b1111000000000000, # RET                            ; end of kernel
    ]
    data = [
        0, 1, 2, 3, 4, 5, 6, 7, # Matrix A (1 x 8)
        0, 1, 2, 3, 4, 5, 6, 7  # Matrix B (1 x 8)
    ]

    for addr, instr in enumerate(program):
        await write_program_word(dut, addr, instr)

    for addr, value in enumerate(data):
        await write_data_byte(dut, addr, value)

    await set_thread_count(dut, 8)
    await start_kernel(dut)

    cycles = 0
    while (int(dut.uio_out.value) & UIO_DONE) == 0:
        await RisingEdge(dut.clk)
        cycles += 1
        if cycles > 2000:
            raise Exception("kernel did not finish within 2000 cycles")

    dut._log.info(f"Kernel completed in {cycles} cycles (via TT adapter)")

    expected_results = [a + b for a, b in zip(data[0:8], data[8:16])]
    for i, expected in enumerate(expected_results):
        result = await read_data_byte(dut, 16 + i)
        assert result == expected, f"Result mismatch at index {i}: expected {expected}, got {result}"
