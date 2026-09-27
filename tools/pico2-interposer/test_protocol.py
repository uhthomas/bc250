import contextlib
import io
import os
from pathlib import Path
import pty
import select
import tempfile
import threading
import time
import unittest
import zlib
from capture import HEADER, MAGIC, MAX_WORDS, Serial, collect
from test_capture import waveform


class ProtocolTest(unittest.TestCase):
    def exchange(self,blob,*,usb_test=False,missing_tail=0,stale_reply=False):
        master,slave=pty.openpty()
        port=os.ttyname(slave)
        n=(len(blob)-32)//4
        errors=[]
        def device():
            try:
                def line():
                    data=b''; deadline=time.monotonic()+5
                    while not data.endswith(b'\n'):
                        if not select.select([master],[],[],max(0,deadline-time.monotonic()))[0]:
                            raise TimeoutError('fake device waiting for host')
                        data+=os.read(master,1)
                    return data
                self.assertEqual(line(),b'\n')
                self.assertEqual(line(),b'status\n')
                if stale_reply:
                    os.write(master,b'ERROR invalid command or limits\n')
                os.write(master,b'BC250-PICO2-PASSIVE v1 outputs=OFF usb_test=1\nhelp\n')
                self.assertEqual(line(),(f'usb-test {n}\n' if usb_test else f'capture 0 {n} 1 1000\n').encode())
                os.write(master,b'ARMED test\n'+f'DATA {len(blob)}\n'.encode())
                wire=blob[:-missing_tail] if missing_tail else blob
                for i in range(0,len(wire),511): os.write(master,wire[i:i+511])
                os.write(master,b'\nDONE\n')
            except Exception as e: errors.append(e)
        worker=threading.Thread(target=device)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                out=Path(d)/'test.bcraw'
                with contextlib.redirect_stdout(io.StringIO()):
                    if missing_tail:
                        with self.assertRaisesRegex(TimeoutError,'USB transfer stopped after'):
                            collect(port,out,0,n,1,1,transfer_timeout=0.2)
                        self.assertFalse(out.exists())
                        partial=Path(str(out)+'.partial')
                        self.assertEqual(partial.read_bytes(),blob[:-missing_tail]+b'\nDONE\n')
                        self.assertEqual(partial.stat().st_mode&0o777,0o600)
                    else:
                        collect(port,out,0,n,1,1,usb_test=usb_test)
                        self.assertEqual(out.read_bytes(),blob)
                        self.assertEqual(out.stat().st_mode&0o777,0o600)
                # DATA marks the capture complete: never leave a spurious x
                # command/error queued for the next client after success/failure.
                self.assertFalse(select.select([master],[],[],0)[0])
        finally:
            worker.join(6)
            os.close(master); os.close(slave)
        self.assertFalse(worker.is_alive())
        if errors: raise errors[0]


    def test_binary_serial_roundtrip(self):
        self.exchange(waveform([(bytes.fromhex('0300000000000000'), bytes.fromhex('000000000d0aff80'))]))

    def test_full_size_usb_self_test(self):
        data=bytes(range(256))*(MAX_WORDS*4//256)
        blob=HEADER.pack(MAGIC,MAX_WORDS,150000000,1,0,0x80000000,zlib.crc32(data))+data
        self.exchange(blob,usb_test=True)

    def test_missing_buffered_tail_is_preserved_for_diagnosis(self):
        blob=waveform([(bytes.fromhex('0300000000000000'),bytes(8))])
        self.exchange(blob,missing_tail=32)

    def test_stale_cancel_error_does_not_prevent_rearming(self):
        blob=waveform([(bytes.fromhex('0300000000000000'),bytes(8))])
        self.exchange(blob,stale_reply=True)

    def test_serial_cleanup_after_usb_disconnection(self):
        master,slave=pty.openpty()
        serial=Serial(os.ttyname(slave))
        os.close(master)
        try:
            with self.assertRaisesRegex(EOFError,'disconnected'):
                serial.read(1,time.monotonic()+1)
            serial.close()  # terminal restore must not mask the unplug error
            with self.assertRaises(OSError):
                os.fstat(serial.fd)
        finally:
            os.close(slave)


if __name__=='__main__': unittest.main()
