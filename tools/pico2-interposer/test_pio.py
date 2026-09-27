"""Execute the assembled bench PIO subset against a synthetic mode-0 master.

This checks bit order, transaction boundaries and output release, not analogue
timing, GPIO electrical behaviour or physical Pico operation.
Run with PIOASM=/path/to/pioasm python3 -m unittest discover ...
"""
import collections
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class SM:
    def __init__(self,p,tx=()):
        self.code=[int(x['hex'],16) for x in p['instructions']]
        self.wrap,self.start=p['wrap'],p['wrapTarget']
        self.pc=self.x=self.isr=self.osr=self.bits=0
        self.tx=collections.deque(tx)
        self.rx=[]

    def step(self,pins):
        ins=self.code[self.pc]
        op=ins>>13
        arg=(ins>>5)&7
        value=ins&31
        next_pc=self.start if self.pc==self.wrap else self.pc+1
        change={}
        if op==0:  # JMP
            if arg==0: next_pc=value
            elif arg==2:
                old=self.x
                self.x=(self.x-1)&0xffffffff
                if old: next_pc=value
            else: raise AssertionError(('jmp',arg))
        elif op==1:  # WAIT GPIO
            if ((ins>>5)&3)!=0: raise AssertionError('not GPIO WAIT')
            if ((pins>>value)&1)!=((ins>>7)&1): return change
        elif op==2:  # IN pins,1, shift left, autopush32
            if arg!=0 or value!=1: raise AssertionError('IN encoding')
            self.isr=((self.isr<<1)|((pins>>4)&1))&0xffffffff
            self.bits+=1
            if self.bits==32:
                self.rx.append(self.isr); self.bits=0; self.isr=0
        elif op==3:  # OUT pins,1, shift left
            if arg!=0 or value!=1: raise AssertionError('OUT encoding')
            change['data']=(self.osr>>31)&1
            self.osr=(self.osr<<1)&0xffffffff
        elif op==4:  # PULL block
            if ins!=0x80a0: raise AssertionError('PULL encoding')
            if not self.tx: return change
            self.osr=self.tx.popleft()
        elif op==7:  # SET X / PINDIRS
            if arg==1: self.x=value
            elif arg==4: change['oe']=value
            else: raise AssertionError(('set',arg))
        else: raise AssertionError(('opcode',op))
        self.pc=next_pc
        return change


class PIOTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        exe=os.environ.get('PIOASM')
        if not exe: raise unittest.SkipTest('set PIOASM to test assembled firmware instructions')
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'reply.json'
            subprocess.run([exe,'-o','json',str(Path(__file__).with_name('reply.pio')),str(out)],check=True)
            cls.programs=json.loads(out.read_text())['programs']
            subprocess.run([exe,'-o','json',str(Path(__file__).with_name('capture.pio')),str(out)],check=True)
            cls.passive=json.loads(out.read_text())['programs'][0]

    def test_passive_has_no_pin_output_instructions(self):
        for i in self.passive['instructions']:
            code=int(i['hex'],16)
            self.assertNotEqual(code>>13,3,'OUT is forbidden in the passive sampler')
            self.assertNotEqual(code>>13,7,'SET is forbidden in the passive sampler')
            self.assertEqual((code>>8)&31,0,'no side-set/delay bits')

    def simulate(self,speed,abort_data=None):
        commands=[0x039dbda0,0x039dbda4,0x039dbda8,0x039dbdac]
        replies=[0,0xffffffff,0xa501ff80,0x80aa5501]
        main=SM(self.programs[0],replies)
        release=SM(self.programs[1])
        pipe=collections.deque([1<<2]*2)
        state=dict(data=0,oe=0)
        half=150000000//speed//2
        def tick(pins,n):
            for _ in range(n):
                pipe.append(pins)
                synced=pipe.popleft()
                state.update(main.step(synced))
                state.update(release.step(synced))
        tick(1<<2,100)
        got=[]
        for cmd in commands:
            tick(0,100)
            for bit in range(31,-1,-1):
                pins=((cmd>>bit)&1)<<4
                tick(pins,half)
                self.assertEqual(state['oe'],0,'MISO must be high-Z through command/address')
                tick(pins|(1<<3),half)
            value=0
            count=32 if abort_data is None else abort_data
            for _ in range(count):
                tick(0,half)
                self.assertEqual(state['oe'],1)
                value=(value<<1)|state['data']
                tick(1<<3,half)
            tick(1<<2,100)
            self.assertEqual(state['oe'],0,'MISO must release when CS# returns high')
            got.append(value)
            if abort_data is not None: break
        if abort_data is None:
            self.assertEqual(got,replies)
            self.assertEqual(main.rx,commands)
        else:
            self.assertEqual(main.rx,commands[:1])

    def test_word_order_and_boundaries(self):
        for speed in (250000,500000,1000000):
            with self.subTest(speed=speed): self.simulate(speed)

    def test_abort_releases_output(self):
        self.simulate(1000000,abort_data=10)


if __name__=='__main__': unittest.main()
