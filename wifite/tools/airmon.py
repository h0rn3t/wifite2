#!/usr/bin/python2.7
# -*- coding: utf-8 -*-

from ..model.interface import Interface
from ..util.process import Process
from ..util.color import Color
from ..config import Configuration

import re
import os
import signal

class Airmon(object):
    ''' Wrapper around the 'airmon-ng' program '''
    base_interface = None
    killed_network_manager = False

    #see if_arp.h
    ARPHRD_ETHER = 1 #managed
    ARPHRD_IEEE80211_RADIOTAP = 803 #monitor

    def __init__(self):
        self.refresh()

    def refresh(self):
        ''' Get airmon-recognized interfaces '''
        self.interfaces = Airmon.get_interfaces()

    def print_menu(self):
        ''' Prints menu '''
        print Interface.menu_header()
        for idx, iface in enumerate(self.interfaces, start=1):
            Color.pl(" {G}%d{W}. %s" % (idx, iface))

    def get(self, index):
        ''' Gets interface at index (starts at 1) '''
        if type(index) is str:
            index = int(index)
        return self.interfaces[index - 1]


    @staticmethod
    def get_interfaces():
        '''
            Returns:
                List of Interface objects known by airmon-ng
        '''
        interfaces = []
        p = Process('airmon-ng')
        for line in p.stdout().split('\n'):
            # Ignore blank/header lines
            if len(line) == 0 or line.startswith('Interface') or line.startswith('PHY'):
                continue

            # Strip out interface information
            fields = line.split("\t")
            while '' in fields:
                fields.remove('')
            # Add Interface object to list
            interfaces.append(Interface(fields))
        return interfaces

    @staticmethod
    def start_baddriver(iface): #fix for bad drivers like the rtl8812AU
        os.system("ifconfig %s down; iwconfig %s mode monitor; ifconfig %s up" % (iface, iface, iface))
        with open("/sys/class/net/" + iface + "/type", "r") as f:
            if (int(f.read()) == Airmon.ARPHRD_IEEE80211_RADIOTAP):
                return iface

        return None

    @staticmethod
    def stop_baddriver(iface):
        os.system("ifconfig %s down; iwconfig %s mode managed; ifconfig %s up" % (iface, iface, iface))
        with open("/sys/class/net/" + iface + "/type", "r") as f:
            if (int(f.read()) == Airmon.ARPHRD_ETHER): 
                return iface

        return None

    @staticmethod
    def start(iface):
        '''
            Starts an interface (iface) in monitor mode
            Args:
                iface - The interface to start in monitor mode
                        Either an instance of Interface object,
                        or the name of the interface (string).
            Returns:
                Name of the interface put into monitor mode.
            Throws:
                Exception - If an interface can't be put into monitor mode
        '''
        # Get interface name from input
        if type(iface) == Interface:
            iface = iface.name
        Airmon.base_interface = iface

        # Call airmon-ng
        Color.p("{+} enabling {G}monitor mode{W} on {C}%s{W}... " % iface)
        (out,err) = Process.call('airmon-ng start %s' % iface)

        # Find the interface put into monitor mode (if any)
        mon_iface = None
        for line in out.split('\n'):
            if 'monitor mode' in line and 'enabled' in line and ' on ' in line:
                mon_iface = line.split(' on ')[1]
                if ']' in mon_iface:
                    mon_iface = mon_iface.split(']')[1]
                if ')' in mon_iface:
                    mon_iface = mon_iface.split(')')[0]
                break

        if mon_iface is None:
            # Airmon did not enable monitor mode on an interface
            mon_iface = Airmon.start_baddriver(iface)

        if mon_iface is None:
            Color.pl("{R}failed{W}")

        mon_ifaces = Airmon.get_interfaces_in_monitor_mode()

        # Assert that there is an interface in monitor mode
        if len(mon_ifaces) == 0:
            Color.pl("{R}failed{W}")
            raise Exception("iwconfig does not see any interfaces in Mode:Monitor")

        # Assert that the interface enabled by airmon-ng is in monitor mode
        if mon_iface not in mon_ifaces:
            Color.pl("{R}failed{W}")
            raise Exception("iwconfig does not see %s in Mode:Monitor" % mon_iface)

        # No errors found; the device 'mon_iface' was put into MM.
        Color.pl("{G}enabled {C}%s{W}" % mon_iface)

        Configuration.interface = mon_iface

        return mon_iface


    @staticmethod
    def stop(iface):
        Color.p("{!} {R}disabling {O}monitor mode{O} on {R}%s{O}... " % iface)
        (out,err) = Process.call('airmon-ng stop %s' % iface)
        mon_iface = None
        for line in out.split('\n'):
            # aircrack-ng 1.2 rc2
            if 'monitor mode' in line and 'disabled' in line and ' for ' in line:
                mon_iface = line.split(' for ')[1]
                if ']' in mon_iface:
                    mon_iface = mon_iface.split(']')[1]
                if ')' in mon_iface:
                    mon_iface = mon_iface.split(')')[0]
                break

            # aircrack-ng 1.2 rc1
            match = re.search('([a-zA-Z0-9]+).*\(removed\)', line)
            if match:
                mon_iface = match.groups()[0]
                break

        if not mon_iface:
            mon_iface = Airmon.stop_baddriver(iface)

        if mon_iface:
            Color.pl('{R}disabled %s{W}' % mon_iface)
        else:
            Color.pl('{O}could not disable on {R}%s{W}' % iface)


    @staticmethod
    def get_interfaces_in_monitor_mode():
        '''
            Uses 'iwconfig' to find all interfaces in monitor mode
            Returns:
                List of interface names that are in monitor mode
        '''
        interfaces = []
        (out, err) = Process.call("iwconfig")
        for line in out.split("\n"):
            if len(line) == 0: continue
            if line[0] != ' ':
                iface = line.split(' ')[0]
                if '\t' in iface:
                    iface = iface.split('\t')[0]
            if 'Mode:Monitor' in line and iface not in interfaces:
                interfaces.append(iface)
        return interfaces


    @staticmethod
    def ask():
        '''
            Asks user to define which wireless interface to use.
            Does not ask if:
                1. There is already an interface in monitor mode, or
                2. There is only one wireles interface (automatically selected).
            Puts selected device into Monitor Mode.
        '''

        Airmon.terminate_conflicting_processes()

        Color.pl('\n{+} looking for {C}wireless interfaces{W}')
        mon_ifaces = Airmon.get_interfaces_in_monitor_mode()
        mon_count = len(mon_ifaces)
        if mon_count == 1:
            # Assume we're using the device already in montior mode
            iface = mon_ifaces[0]
            Color.pl('{+} using interface {G}%s{W} which is already in monitor mode'
                % iface);
            Airmon.base_interface = None
            return iface

        a = Airmon()
        count = len(a.interfaces)
        if count == 0:
            # No interfaces found
            Color.pl('\n{!} {O}airmon-ng did not find {R}any{O} wireless interfaces')
            Color.pl('{!} {O}make sure your wireless device is connected')
            Color.pl('{!} {O}see {C}http://www.aircrack-ng.org/doku.php?id=airmon-ng{O} for more info{W}')
            raise Exception('airmon-ng did not find any wireless interfaces')

        Color.pl('')

        a.print_menu()

        Color.pl('')

        if count == 1:
            # Only one interface, assume this is the one to use
            choice = 1
        else:
            # Multiple interfaces found
            question = Color.s("{+} select interface ({G}1-%d{W}): " % (count))
            choice = raw_input(question)

        iface = a.get(choice)

        if a.get(choice).name in mon_ifaces:
            Color.pl('{+} {G}%s{W} is already in monitor mode' % iface.name)
        else:
            iface.name = Airmon.start(iface)
        return iface.name


    @staticmethod
    def terminate_conflicting_processes():
        ''' Deletes conflicting processes reported by airmon-ng '''

        '''
        % airmon-ng check

        Found 3 processes that could cause trouble.
        If airodump-ng, aireplay-ng or airtun-ng stops working after
        a short period of time, you may want to kill (some of) them!
        -e
        PID Name
        2272    dhclient
        2293    NetworkManager
        3302    wpa_supplicant
        '''

        out = Process(['airmon-ng', 'check']).stdout()
        if 'processes that could cause trouble' not in out:
            # No proceses to kill
            return

        hit_pids = False
        for line in out.split('\n'):
            if re.search('^ *PID', line):
                hit_pids = True
                continue
            if not hit_pids or line.strip() == '':
                continue
            match = re.search('^[ \t]*(\d+)[ \t]*([a-zA-Z0-9_\-]+)[ \t]*$', line)
            if match:
                # Found process
                pid = match.groups()[0]
                pname = match.groups()[1]
                if Configuration.kill_conflicting_processes:
                    Color.pl('{!} {R}terminating {O}conflicting process {R}%s{O} (PID {R}%s{O})' % (pname, pid))
                    os.kill(int(pid), signal.SIGTERM)
                    if pname == 'NetworkManager':
                        Airmon.killed_network_manager= True
                else:
                    Color.pl('{!} {O}conflicting process: {R}%s{O} (PID {R}%s{O})' % (pname, pid))

        if not Configuration.kill_conflicting_processes:
            Color.pl('{!} {O}if you have problems, try killing these processes ({R}kill -9 PID{O}){W}')

    @staticmethod
    def put_interface_up(iface):
        Color.p("{!} {O}putting interface {R}%s up{O}..." % (iface))
        (out,err) = Process.call('ifconfig %s up' % (iface))
        Color.pl(" {R}done{W}")

    @staticmethod
    def start_network_manager():
        Color.p("{!} {O}restarting {R}NetworkManager{O}...")

        if Process.exists('service'):
            cmd = 'service network-manager start'
            proc = Process(cmd)
            (out, err) = proc.get_output()
            if proc.poll() != 0:
                Color.pl(" {R}Error executing {O}%s{W}" % cmd)
                if out is not None and out.strip() != "":
                    Color.pl("{!} {O}STDOUT> %s{W}" % out)
                if err is not None and err.strip() != "":
                    Color.pl("{!} {O}STDERR> %s{W}" % err)
            else:
                Color.pl(" {G}done{W} ({C}%s{W})" % cmd)
                return

        if Process.exists('systemctl'):
            cmd = 'systemctl start NetworkManager'
            proc = Process(cmd)
            (out, err) = proc.get_output()
            if proc.poll() != 0:
                Color.pl(" {R}Error executing {O}%s{W}" % cmd)
                if out is not None and out.strip() != "":
                    Color.pl("{!} {O}STDOUT> %s{W}" % out)
                if err is not None and err.strip() != "":
                    Color.pl("{!} {O}STDERR> %s{W}" % err)
            else:
                Color.pl(" {G}done{W} ({C}%s{W})" % cmd)
                return
        else:
            Color.pl(" {R}can't restart NetworkManager: {O}systemctl{R} or {O}service{R} not found{W}")

if __name__ == '__main__':
    Airmon.terminate_conflicting_processes()
    iface = Airmon.ask()
    Airmon.stop(iface)
