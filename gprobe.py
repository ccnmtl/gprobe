#!/usr/bin/env python
import re
import subprocess
import sys
from socket import socket
import time
import argparse


def split_line(line):
    line = line.strip()
    return line.split(' ')


def percent(num, den):
    if den == 0:
        return 0.
    return float(num) / float(den) * 100.


def probe_vm():
    for line in open("/proc/vmstat", "r").readlines():
        if line.startswith('pswpin'):
            v = split_line(line)[1]
            yield ('vmstat.swap.in', v)
        if line.startswith('pswpout'):
            v = split_line(line)[1]
            yield ('vmstat.swap.out', v)


def probe_mem():
    pattern = re.compile(r"[:\s]+")
    values = dict()
    for line in open("/proc/meminfo", "r").readlines():
        parts = pattern.split(line.strip())
        key = parts[0]
        value = int(parts[1])
        if len(parts) > 2:
            if parts[2] == 'kB':
                value = value * 1024
        values[key] = value

    memtotal = values['MemTotal']
    swaptotal = values['SwapTotal']
    for k in ['MemFree', 'Buffers', 'Cached', 'Active', 'Inactive']:
        yield ("memory.%s.bytes" % k, values[k])
        yield ("memory.%s.percent" % k, percent(values[k],  memtotal))
    yield ('memory.SwapFree.bytes', values['SwapFree'])
    yield ('memory.SwapFree.percent', percent(values['SwapFree'], swaptotal))


def probe_net():
    pattern = re.compile(r"[:\s]+")
    data = open("/proc/net/dev", "r").readlines()
    # first two lines are just headers that we can skip
    for line in data[2:]:
        (iface,
         rx_bytes, rx_packets, rx_errs, rx_drop, rx_fifo,
         rx_frame, rx_compressed, rx_multicast,

         tx_bytes, tx_packets, tx_errs, tx_drop,
         tx_fifo, tx_frame, tx_compressed, tx_multicast
         ) = pattern.split(line.strip())
        if not iface.startswith('eth'):
            continue
        yield ("network.%s.receive.byte_count" % iface, rx_bytes)
        yield ("network.%s.receive.packet_count" % iface, rx_packets)
        yield ("network.%s.transmit.byte_count" % iface, tx_bytes)
        yield ("network.%s.transmit.packet_count" % iface, tx_packets)


def probe_disk():
    # TODO: still need to implement this
    pattern = re.compile(r'\s+')
    for line in open("/proc/diskstats", "r").readlines():
        parts = pattern.split(line.strip())
    return []


def probe_cpu():
    cpu_count = 0
    pattern = re.compile(r'^cpu\d')
    pattern2 = re.compile(r'\s+')
    (end_user, end_system, end_iowait) = (0, 0, 0)
    for line in open("/proc/stat", "r").readlines():
        if pattern.match(line):
            cpu_count += 1
        if line.startswith('cpu '):
            parts = pattern2.split(line.strip())
            end_user = int(parts[1])
            end_system = int(parts[3])
            end_iowait = int(parts[5])
    yield ('cpu.time.user_seconds_count', percent(end_user, cpu_count))
    yield ('cpu.time.system_seconds_count', percent(end_system, cpu_count))
    yield ('cpu.time.iowait_seconds_count', percent(end_iowait, cpu_count))


def probe_load():
    parts = open("/proc/loadavg", "r").read().strip().split(' ')
    yield ('cpu.load_average.1_minute', parts[0])
    yield ('cpu.load_average.5_minute', parts[1])
    pcount = subprocess.check_output("ps -ef | wc -l", shell=True)
    # original perl version had a '$pcount--'
    # i assume to remove this probe process from the count
    yield ('process_count', int(pcount.strip()) - 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', help='graphite prefix', required=True)
    parser.add_argument('--graphite', help='carbon host', required=True)
    parser.add_argument('--port', help='carbon port',
                        default=2003, type=int)
    parser.add_argument('--debug', help="just print values, don't send",
                        type=bool,
                        default=False)
    args = parser.parse_args()
    prefix = args.prefix
    graphite = args.graphite

    now = int(time.time())
    stats = []
    probes = [probe_vm, probe_mem, probe_net, probe_disk, probe_cpu, probe_load]
    for p in probes:
        for (label, value) in p():
            stats.append("%s.%s %s %d" % (prefix, label, value, now))

    message = '\n'.join(stats) + '\n'

    if args.debug:
        print(message)
    else:
        sock = socket()
        try:
            sock.connect((args.graphite, args.port))
        except:
            print ((
                "Couldn't connect to %(server)s on port %(port)d, "
                "is carbon-agent.py running?") % {'server': args.graphite,
                                                  'port': args.port})
            sys.exit(1)
        sock.sendall(message.encode('utf-8'))
