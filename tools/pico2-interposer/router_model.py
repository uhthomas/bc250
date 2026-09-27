"""Cycle model of the assembled router PIO, including a separate original flash.

This is a digital model, not an RP2350/board emulator. It deliberately exposes
the synchronization, FIFO service and flash release assumptions to its caller.
It cannot establish signal integrity or CPU fault-monitor timing on hardware.
"""
import collections
import ctypes
import json
from pathlib import Path
import subprocess
import tempfile


class NativePolicy:
    """Host-compile the same pure C boundary decision used by core1.

    This validates control decisions, not RP2350 CPU timing. The caller supplies
    a modeled completion latency for the peripheral writes performed by core1.
    """
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory()
        source = Path(self.directory.name) / 'policy.c'
        library = source.with_suffix('.so')
        source.write_text('#include "router_policy.h"\n'
                          '#include "router_stream.h"\n'
                          'int decide(int seek,unsigned clocks,int mismatch,int high,unsigned pc,unsigned start,unsigned done) {\n'
                          'return router_boundary(seek,clocks,mismatch,high,pc,start,done);}\n'
                          'unsigned expand(const struct router_run *r,unsigned n,const unsigned *p,unsigned pass,unsigned patch,unsigned *out,unsigned cap) {\n'
                          'struct router_stream s={0}; unsigned count=0,word;\n'
                          'while(router_stream_next(&s,r,n,p,pass,patch,&word)) { if(count==cap)return UINT32_MAX; out[count++]=word;}\n'
                          'return count;}\n')
        subprocess.run(['cc', '-std=c11', '-O2', '-shared', '-fPIC', '-Wall', '-Werror',
                        '-I', str(Path(__file__).parent), str(source), '-o', str(library)], check=True)
        self.lib = ctypes.CDLL(str(library))
        self.lib.decide.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        self.lib.decide.restype = ctypes.c_int
        pointer=ctypes.POINTER(ctypes.c_uint32)
        self.lib.expand.argtypes=[pointer,ctypes.c_uint32,pointer,ctypes.c_uint32,
                                 ctypes.c_uint32,pointer,ctypes.c_uint32]
        self.lib.expand.restype=ctypes.c_uint32

    def expand(self,runs,payload,labels):
        run_data=(ctypes.c_uint32*(len(runs)*3))(*[x for r in runs for x in (r['command'],r['count'],r['payload'])])
        data=(ctypes.c_uint32*max(1,len(payload)))(*(payload or [0]))
        n=sum(r['count'] for r in runs)*3
        output=(ctypes.c_uint32*n)()
        count=self.lib.expand(run_data,len(runs),data,labels['pass']<<16,labels['patch']<<16,output,n)
        if count!=n:
            raise ValueError('native stream expansion length')
        return list(output)

    def close(self):
        self.directory.cleanup()


class BoundaryMonitor:
    def __init__(self, policy, rows, latency=32):
        if len(rows) < 3 or rows[0][1] or rows[1][1]:
            raise ValueError('seeking profile must start with two PASS guard reads')
        self.policy, self.rows, self.latency = policy, len(rows), latency
        self.mode = 'seeking'
        self.read_index = self.boundaries = self.skipped = 0
        self.pending = None

    def step(self, bus, pins):
        if self.mode not in ('seeking', 'running'):
            return
        if self.pending is None:
            if self.mode == 'running' and 0 in bus.irqs:
                self.pending = (bus.time + self.latency, 'address', None)
            elif self.read_index < len(bus.counter.rx):
                clocks = bus.counter.rx[self.read_index]
                self.read_index += 1
                self.pending = (bus.time + self.latency, 'boundary', clocks)
        if self.pending is None or bus.time < self.pending[0]:
            return
        _, kind, clocks = self.pending
        self.pending = None
        labels = bus.programs[0]['publicLabels']
        action = 4 if kind == 'address' else self.policy.lib.decide(
            self.mode == 'seeking', clocks, 0 in bus.irqs, bool(pins & 4),
            bus.engine.pc, labels['wait_start'], labels['done'])
        if action == 0:
            # RP2350 SM_RESTART + forced JMP: retain X/Y/OSR and FIFO contents.
            bus.engine.isr = bus.engine.delay = 0
            bus.engine.inject = bus.engine.irq_wait = None
            bus.engine.pc = labels['wait_start']
            bus.irqs.discard(0)
            self.skipped += 1
        elif action == 1:
            self.boundaries += 1
            if self.mode == 'seeking':
                self.mode = 'running'
                bus.forced_miso_off = False
            elif self.boundaries == self.rows:
                self.mode = 'complete'
                bus.engine.enabled = False
                bus.forced_miso_off = True
        else:
            self.mode = {2: 'length_fault', 3: 'boundary_fault', 4: 'address_fault'}[action]
            bus.engine.enabled = False
            bus.forced_miso_off = True


def assemble(executable):
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / 'pio.json'
        subprocess.run([executable, '-o', 'json',
                        str(Path(__file__).with_name('router.pio')), str(out)], check=True)
        programs = json.loads(out.read_text())['programs']
        subprocess.run([executable, '-o', 'json',
                        str(Path(__file__).with_name('router_count.pio')), str(out)], check=True)
        return programs + json.loads(out.read_text())['programs']


def encode(rows, labels):
    """Rows are (full_command, substitute_boolean, word_in_SPI_byte_order)."""
    words = []
    for cmd, patch, word in rows:
        if cmd >> 24 != 3 or cmd & 3:
            raise ValueError('only aligned READ03 commands in a router script')
        words += [cmd, labels['patch' if patch else 'pass'] << 16, word if patch else 0]
    return words


class SM:
    def __init__(self, program, fifo=None, *, in_base=4, in_count=32,
                 jmp_pin=2, in_autopush=False):
        self.code = [int(i['hex'], 16) for i in program['instructions']]
        self.wrap, self.start = program['wrap'], program['wrapTarget']
        self.pc = self.x = self.y = self.isr = self.osr = self.delay = 0
        self.inject = None
        self.irq_wait = None
        self.fifo = fifo if fifo is not None else collections.deque()
        self.enabled = True
        self.in_base, self.in_count, self.jmp_pin = in_base, in_count, jmp_pin
        self.in_autopush, self.in_bits = in_autopush, 0
        self.sideset = program['sideset'] is not None
        self.rx = []

    def step(self, pins, irqs):
        change = {}
        if not self.enabled:
            return change
        if self.delay:
            self.delay -= 1
            return change
        injected = self.inject is not None
        ins = self.inject if injected else self.code[self.pc]
        self.inject = None
        if self.sideset and ins & 0x1000:
            change['oe'] = (ins >> 11) & 1
        if self.irq_wait is not None:
            if self.irq_wait in irqs:
                return change
            self.irq_wait = None
            self.pc = self.start if self.pc == self.wrap else self.pc + 1
            return change
        arg, value, op = (ins >> 5) & 7, ins & 31, ins >> 13
        next_pc = self.pc if injected else (self.start if self.pc == self.wrap else self.pc + 1)
        if op == 0:
            take = False
            if arg == 0:
                take = True
            elif arg == 1:
                take = self.x == 0
            elif arg == 2:
                take, self.x = self.x != 0, (self.x - 1) & 0xffffffff
            elif arg == 3:
                take = self.y == 0
            elif arg == 5:
                take = self.x != self.y
            elif arg == 4:
                take, self.y = self.y != 0, (self.y - 1) & 0xffffffff
            elif arg == 6:
                take = bool(pins & (1 << self.jmp_pin))
            else:
                raise AssertionError(('JMP', arg))
            if take:
                next_pc = value
        elif op == 1:
            if (ins >> 5) & 3:
                raise AssertionError('only WAIT GPIO modeled')
            if (pins >> value) & 1 != (ins >> 7) & 1:
                return change
        elif op == 2:
            if arg != 0 or value != 1:
                raise AssertionError('only IN PINS,1 modeled')
            self.isr = ((self.isr << 1) | ((pins >> 4) & 1)) & 0xffffffff
            if self.in_autopush:
                self.in_bits += 1
                if self.in_bits == 32:
                    self.rx.append(self.isr)
                    self.isr = self.in_bits = 0
        elif op == 3:
            n = value or 32
            out = self.osr >> (32 - n)
            self.osr = (self.osr << n) & 0xffffffff
            if arg == 0 and n == 1:
                change['data'] = out
            elif arg == 7 and n == 16:
                self.inject = out  # OUT EXEC takes a separate execution cycle
            else:
                raise AssertionError(('OUT', arg, n))
        elif op == 4:
            if (ins & 0xe0ff) == 0x8020:
                self.rx.append(self.isr)
                self.isr = 0
            else:
                if (ins & 0xe0ff) != 0x80a0:
                    raise AssertionError('only PUSH/PULL BLOCK modeled')
                if not self.fifo:
                    return change
                self.osr = self.fifo.popleft()
        elif op == 5:
            operation = (ins >> 3) & 3
            if operation not in (0, 1):
                raise AssertionError('MOV operation')
            source = {0: (pins >> self.in_base) & ((1 << self.in_count) - 1),
                      2: self.y, 3: 0, 6: self.isr, 7: self.osr}[ins & 7]
            if operation:
                source ^= 0xffffffff
            if arg == 1:
                self.x = source
            elif arg == 2:
                self.y = source
            elif arg == 6:
                self.isr = source
            else:
                raise AssertionError(('MOV', arg))
        elif op == 6:
            irqs.add(value)
            if ins & 0x20:
                self.irq_wait = value
                return change
        elif op == 7:
            if arg == 0:
                change['flash_cs'] = value & 1
            elif arg == 4:
                change['flash_cs'] = 1 - (value & 1)
            elif arg == 1:
                self.x = value
            elif arg == 2:
                self.y = value
            else:
                raise AssertionError(('SET', arg))
        else:
            raise AssertionError(('opcode', op))
        self.pc = next_pc
        self.delay = (ins >> 8) & (7 if self.sideset else 31)
        return change


class Bus:
    def __init__(self, programs, rows, rom_word, *, sync_cycles=2,
                 feed_cycles=64, flash_release_cycles=2, monitor=None):
        self.programs, self.rom_word = programs, rom_word
        self.pending = collections.deque(encode(rows, programs[0]['publicLabels']))
        self.fifo = collections.deque()
        self.engine, self.guard = SM(programs[0], self.fifo), SM(programs[1])
        self.counter = SM(programs[2], in_base=2, in_count=1, jmp_pin=3)
        self.pipe = collections.deque([1 << 2] * sync_cycles)
        self.feed_cycles, self.release_cycles = feed_cycles, flash_release_cycles
        self.irqs = set()
        self.state = dict(oe=0, data=0, flash_cs=1)
        self.time = self.cmd = self.clocks = 0
        self.previous = 1 << 2
        self.flash_previous = 1
        self.release_at = 0
        self.flash_oe = False
        self.flash_data = 0
        self.samples = []
        self.contentions = []
        self.flash_commands = []
        self.monitor = monitor
        self.forced_miso_off = monitor is not None
        self.pico_drive_cycles = 0

    def tick(self, pins, cycles=1):
        for _ in range(cycles):
            cs, clk = bool(pins & 4), bool(pins & 8)
            old_clk = bool(self.previous & 8)
            flash_cs = self.state['flash_cs']
            if self.flash_previous and not flash_cs:
                self.cmd = self.clocks = 0
                self.flash_oe = False
            if not self.flash_previous and flash_cs:
                self.release_at = self.time + self.release_cycles
            if flash_cs and self.time >= self.release_at:
                self.flash_oe = False
            if not flash_cs and clk and not old_clk:
                if self.clocks < 32:
                    self.cmd = (self.cmd << 1) | ((pins >> 4) & 1)
                self.clocks += 1
                if self.clocks == 32:
                    self.flash_commands.append(self.cmd)
            if not flash_cs and not clk and old_clk and self.clocks >= 32:
                bit = self.clocks - 32
                # Only READ03 data is modeled. Other opcodes are opaque
                # pass-through for CS, without a modeled MISO response.
                self.flash_oe = self.cmd >> 24 == 3 and bit < 32
                if self.flash_oe:
                    self.flash_data = (self.rom_word(self.cmd) >> (31 - bit)) & 1
            pico_oe = int(self.state['oe'] and not self.forced_miso_off)
            self.pico_drive_cycles += pico_oe
            if self.flash_oe and pico_oe:
                self.contentions.append(self.time)
            if not cs and clk and not old_clk:
                drivers = int(self.flash_oe) + pico_oe
                value = self.state['data'] if pico_oe else self.flash_data
                self.samples.append((drivers, value))
            # External pins update after each modeled PIO cycle. GPIO propagation
            # is bounded here by one clock; board wire/analogue delay is not modeled.
            self.pipe.append(pins)
            synced = self.pipe.popleft()
            self.state.update(self.engine.step(synced, self.irqs))
            self.state.update(self.guard.step(synced, self.irqs))
            self.counter.step(synced, self.irqs)
            if self.monitor is not None:
                self.monitor.step(self,pins)
            if self.time % self.feed_cycles == 0 and self.pending and len(self.fifo) < 4:
                self.fifo.append(self.pending.popleft())
            self.previous, self.flash_previous = pins, flash_cs
            self.time += 1

    def transaction(self, command, half_cycles=15, *, clocks=64, setup_cycles=30,
                    high_cycles=150):
        start = len(self.samples)
        self.tick(0, setup_cycles)
        for bit in range(clocks):
            mosi = ((command >> (31 - bit)) & 1) << 4 if bit < 32 else 0
            self.tick(mosi, half_cycles)
            self.tick(mosi | 8, half_cycles)
        self.tick(0, half_cycles)  # final falling edge, CS hold
        self.tick(4, high_cycles)
        return self.samples[start:]

    @staticmethod
    def data(samples):
        if len(samples) != 64:
            raise AssertionError('expected 64 host clocks')
        value = 0
        for drivers, bit in samples[32:]:
            if drivers != 1:
                raise AssertionError(f'expected one MISO driver, got {drivers}')
            value = (value << 1) | bit
        return value
