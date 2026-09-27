"""Linux SPI transfer helper for the isolated Pi/Pico bench."""
import ctypes
import fcntl
import struct


def transfer(fd, command, speed):
    tx = ctypes.create_string_buffer(command.to_bytes(4,'big') + bytes(4),8)
    rx = ctypes.create_string_buffer(8)
    desc = struct.pack('=QQIIHBBBBBB',ctypes.addressof(tx),ctypes.addressof(rx),8,speed,0,8,0,0,0,0,0)
    fcntl.ioctl(fd,0x40206b00,desc)  # SPI_IOC_MESSAGE(1), one 32-byte descriptor
    return int.from_bytes(rx.raw[4:],'big')


def transfer_many(fd, commands, speed):
    """Send up to 32 reads in one ioctl, toggling CE0 between each read."""
    if not 1 <= len(commands) <= 32:
        raise ValueError('batch must contain 1..32 commands')
    tx = ctypes.create_string_buffer(8 * len(commands))
    rx = ctypes.create_string_buffer(8 * len(commands))
    descriptors = []
    for index, command in enumerate(commands):
        ctypes.memmove(ctypes.addressof(tx) + 8 * index,
                       command.to_bytes(4, 'big'), 4)
        descriptors.append(struct.pack(
            '=QQIIHBBBBBB', ctypes.addressof(tx) + 8 * index,
            ctypes.addressof(rx) + 8 * index, 8, speed, 0, 8,
            int(index + 1 < len(commands)), 0, 0, 0, 0))
    size = 32 * len(commands)
    fcntl.ioctl(fd, 0x40006b00 | (size << 16), b''.join(descriptors))
    return [int.from_bytes(rx.raw[8*index+4:8*index+8], 'big')
            for index in range(len(commands))]
