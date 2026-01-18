# TM1637 MicroPython driver with colon support (no ljust used)
import time
from machine import Pin

_SEG = {
    ' ': 0x00,
    '-': 0x40,
    '_': 0x08,
    '0': 0x3f,
    '1': 0x06,
    '2': 0x5b,
    '3': 0x4f,
    '4': 0x66,
    '5': 0x6d,
    '6': 0x7d,
    '7': 0x07,
    '8': 0x7f,
    '9': 0x6f,
    'A': 0x77,
    'b': 0x7c,
    'C': 0x39,
    'd': 0x5e,
    'E': 0x79,
    'F': 0x71,
}

class TM1637:
    def __init__(self, clk, dio, brightness=7):
        self.clk = clk
        self.dio = dio
        self.brightness = brightness & 7
        self.clk.init(Pin.OUT, value=1)
        self.dio.init(Pin.OUT, value=1)

    def start(self):
        self.dio(1)
        self.clk(1)
        self.dio(0)
        self.clk(0)

    def stop(self):
        self.dio(0)
        self.clk(1)
        self.dio(1)

    def write_byte(self, b):
        for i in range(8):
            self.dio((b >> i) & 1)
            self.clk(1)
            self.clk(0)

        self.clk.init(Pin.IN)
        time.sleep_us(50)
        ack = self.clk()
        self.clk.init(Pin.OUT)
        return ack == 0

    def encode_char(self, c):
        return _SEG.get(c, 0x00)

    def show(self, text, colon=False):
        # Convert to string
        text = str(text)

        # Manual pad / trim (replaces ljust)
        if len(text) < 4:
            text = text + (" " * (4 - len(text)))
        elif len(text) > 4:
            text = text[:4]

        # Encode characters
        segs = [self.encode_char(c) for c in text]

        # Add colon (middle dots)
        if colon:
            segs[1] |= 0x80

        # Send data
        self.start()
        self.write_byte(0x40)
        self.stop()

        self.start()
        self.write_byte(0xC0)
        for s in segs:
            self.write_byte(s)
        self.stop()

        self.start()
        self.write_byte(0x88 | self.brightness)
        self.stop()

    def number(self, num, colon=False):
        s = "{:04d}".format(num)
        self.show(s, colon)

    def connecting(self):
        self.show('----')

    def power_off(self):
        self.start()
        self.write_byte(0x80)  # display OFF
        self.stop()

    def power_on(self):
        self.start()
        self.write_byte(0x88 | self.brightness)  # display ON
        self.stop()