import datetime
import socket
import struct
import time
import Queue
import threading
import select

TASK_QUEUE = Queue.Queue()
STOP_FLAG = False

def system_to_ntp_time(timestamp):
    """Convert a system time to a NTP time.

    Parameters:
    timestamp -- timestamp in system time

    Returns:
    corresponding NTP time
    """
    return timestamp + NTP.NTP_DELTA

def _to_int(timestamp):
    """Return the integral part of a timestamp.

    Parameters:
    timestamp -- NTP timestamp

    Retuns:
    integral part
    """
    return int(timestamp)

def _to_frac(timestamp, bits=32):
    """Return the fractional part of a timestamp.

    Parameters:
    timestamp -- NTP timestamp
    n         -- number of bits of the fractional part

    Retuns:
    fractional part
    """
    return int(abs(timestamp - _to_int(timestamp)) * 2**bits)

def _to_time(integ, frac, bits=32):
    """Return a timestamp from an integral and fractional part.

    Parameters:
    integ -- integral part
    frac  -- fractional part
    n     -- number of bits of the fractional part

    Retuns:
    timestamp
    """
    return integ + float(frac)/2**bits



class NTPException(Exception):
    """Exception raised by this module."""
    pass


class NTP(object):
    """Helper class defining constants."""

    _SYSTEM_EPOCH = datetime.date(*time.gmtime(0)[0:3])
    """system epoch"""
    _NTP_EPOCH = datetime.date(1900, 1, 1)
    """NTP epoch"""
    NTP_DELTA = (_SYSTEM_EPOCH - _NTP_EPOCH).days * 24 * 3600
    """delta between system and NTP time"""

    REF_ID_TABLE = {
        'DNC': "DNC routing protocol",
        'NIST': "NIST public modem",
        'TSP': "TSP time protocol",
        'DTS': "Digital Time Service",
        'ATOM': "Atomic clock (calibrated)",
        'VLF': "VLF radio (OMEGA, etc)",
        'callsign': "Generic radio",
        'LORC': "LORAN-C radionavidation",
        'GOES': "GOES UHF environment satellite",
        'GPS': "GPS UHF satellite positioning",
    }
    """reference identifier table"""

    STRATUM_TABLE = {
        0: "unspecified",
        1: "primary reference",
    }
    """stratum table"""

    MODE_TABLE = {
        0: "unspecified",
        1: "symmetric active",
        2: "symmetric passive",
        3: "client",
        4: "server",
        5: "broadcast",
        6: "reserved for NTP control messages",
        7: "reserved for private use",
    }
    """mode table"""

    LEAP_TABLE = {
        0: "no warning",
        1: "last minute has 61 seconds",
        2: "last minute has 59 seconds",
        3: "alarm condition (clock not synchronized)",
    }
    """leap indicator table"""

class NTPPacket(object):
    """NTP packet class.

    This represents an NTP packet.
    """

    _PACKET_FORMAT = "!B B B b 11I"
    """packet format to pack/unpack"""

    def __init__(self, version=2, mode=3, tx_timestamp=0):
        """Constructor.

        Parameters:
        version      -- NTP version
        mode         -- packet mode (client, server)
        tx_timestamp -- packet transmit timestamp
        """
        self.leap = 0
        """leap second indicator"""
        self.version = version
        """version"""
        self.mode = mode
        """mode"""
        self.stratum = 0
        """stratum"""
        self.poll = 0
        """poll interval"""
        self.precision = 0
        """precision"""
        self.root_delay = 0
        """root delay"""
        self.root_dispersion = 0
        """root dispersion"""
        self.ref_id = 0
        """reference clock identifier"""
        self.ref_timestamp = 0
        """reference timestamp"""
        self.orig_timestamp = 0
        self.orig_timestamp_high = 0
        self.orig_timestamp_low = 0
        """originate timestamp"""
        self.recv_timestamp = 0
        """receive timestamp"""
        self.tx_timestamp = tx_timestamp
        self.tx_timestamp_high = 0
        self.tx_timestamp_low = 0
        """tansmit timestamp"""

    def to_data(self):
        """Convert this NTPPacket to a buffer that can be sent over a socket.

        Returns:
        buffer representing this packet

        Raises:
        NTPException -- in case of invalid field
        """
        try:
            packed = struct.pack(NTPPacket._PACKET_FORMAT,
                                 (self.leap << 6 | self.version << 3 | self.mode),
                                 self.stratum,
                                 self.poll,
                                 self.precision,
                                 _to_int(self.root_delay) << 16 | _to_frac(self.root_delay, 16),
                                 _to_int(self.root_dispersion) << 16 |
                                 _to_frac(self.root_dispersion, 16),
                                 self.ref_id,
                                 _to_int(self.ref_timestamp),
                                 _to_frac(self.ref_timestamp),
                                 #Change by lichen, avoid loss of precision
                                 self.orig_timestamp_high,
                                 self.orig_timestamp_low,
                                 _to_int(self.recv_timestamp),
                                 _to_frac(self.recv_timestamp),
                                 _to_int(self.tx_timestamp),
                                 _to_frac(self.tx_timestamp))
        except struct.error:
            raise NTPException("Invalid NTP packet fields.")
        return packed

    def from_data(self, data):
        """Populate this instance from a NTP packet payload received from
        the network.

        Parameters:
        data -- buffer payload

        Raises:
        NTPException -- in case of invalid packet format
        """
        try:
            unpacked = struct.unpack(NTPPacket._PACKET_FORMAT,
                                     data[0:struct.calcsize(NTPPacket._PACKET_FORMAT)])
        except struct.error:
            raise NTPException("Invalid NTP packet.")

        self.leap = unpacked[0] >> 6 & 0x3
        self.version = unpacked[0] >> 3 & 0x7
        self.mode = unpacked[0] & 0x7
        self.stratum = unpacked[1]
        self.poll = unpacked[2]
        self.precision = unpacked[3]
        self.root_delay = float(unpacked[4])/2**16
        self.root_dispersion = float(unpacked[5])/2**16
        self.ref_id = unpacked[6]
        self.ref_timestamp = _to_time(unpacked[7], unpacked[8])
        self.orig_timestamp = _to_time(unpacked[9], unpacked[10])
        self.orig_timestamp_high = unpacked[9]
        self.orig_timestamp_low = unpacked[10]
        self.recv_timestamp = _to_time(unpacked[11], unpacked[12])
        self.tx_timestamp = _to_time(unpacked[13], unpacked[14])
        self.tx_timestamp_high = unpacked[13]
        self.tx_timestamp_low = unpacked[14]

    def get_tx_time_stamp(self):
        return (self.tx_timestamp_high, self.tx_timestamp_low)

    def set_origin_time_stamp(self, high, low):
        self.orig_timestamp_high = high
        self.orig_timestamp_low = low


class RecvThread(threading.Thread):
    def __init__(self, my_socket):
        threading.Thread.__init__(self)
        self.my_socket = my_socket
    def run(self):
        global TASK_QUEUE, STOP_FLAG
        while True:
            if STOP_FLAG is True:
                print "RecvThread Ended"
                break
            rlist, _, _ = select.select([self.my_socket], [], [], 1)
            if len(rlist) != 0:
                print "Received %d packets" % len(rlist)
                for temp_socket in rlist:
                    try:
                        data, addr = temp_socket.recvfrom(1024)
                        recv_timestamp = recv_timestamp = system_to_ntp_time(time.time())
                        TASK_QUEUE.put((data, addr, recv_timestamp))
                    except socket.error, msg:
                        print msg

class WorkThread(threading.Thread):
    def __init__(self, my_socket):
        threading.Thread.__init__(self)
        self.my_socket = my_socket
    def run(self):
        global TASK_QUEUE, STOP_FLAG
        while True:
            if STOP_FLAG is True:
                print "WorkThread Ended"
                break
            try:
                data, addr, recv_timestamp = TASK_QUEUE.get(timeout=1)
                recv_packet = NTPPacket()
                recv_packet.from_data(data)
                time_stamp_high, time_stamp_low = recv_packet.get_tx_time_stamp()
                send_packet = NTPPacket(version=3, mode=4)
                send_packet.stratum = 2
                send_packet.poll = 10
                # send_packet.precision = 0xfa
                # send_packet.root_delay = 0x0bfa
                # send_packet.root_dispersion = 0x0aa7
                # send_packet.ref_id = 0x808a8c2c
                send_packet.ref_timestamp = recv_timestamp-5
                send_packet.set_origin_time_stamp(time_stamp_high, time_stamp_low)
                send_packet.recv_timestamp = recv_timestamp
                send_packet.tx_timestamp = system_to_ntp_time(time.time())
                self.my_socket.sendto(send_packet.to_data(), addr)
                print "Sended to %s:%d" % (addr[0], addr[1])
            except Queue.Empty:
                continue

def main():
    global STOP_FLAG
    listen_ip = "0.0.0.0"
    listen_port = 123
    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listen_socket.bind((listen_ip, listen_port))
    print "local socket: ", listen_socket.getsockname()
    recv_thread = RecvThread(listen_socket)
    recv_thread.start()
    work_thread = WorkThread(listen_socket)
    work_thread.start()

    while True:
        try:
            time.sleep(0.5)
        except KeyboardInterrupt:
            print "Exiting..."
            STOP_FLAG = True
            recv_thread.join()
            work_thread.join()
            #listen_socket.close()
            print "Exited"
            break

if __name__ == '__main__':
    main()
