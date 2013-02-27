#!/usr/bin/env python

# Paul Hubbard 2/24/13
# V2 of my bandwidth monitor - project to display link usage of my pfsense
# router/firewall on a pair of analog voltmeters.
#
# This code polls the firewall for data, scales it and updates the
# meters.Also does geometric averaging to smooth out the meter movements.

import requests
import logging as log
from urllib2 import urlopen
from sys import exit
from time import sleep
from datetime import datetime, timedelta
from collections import deque
from ConfigParser import SafeConfigParser

config = SafeConfigParser()
config.read('config.ini')

ROUTER_ADDR = config.get('router', 'address')
IF_NAME = config.get('router', 'if_name')
UPLINK_MAX_CPS = config.getint('router', 'up_max_cps')
DOWNLINK_MAX_CPS = config.getint('router', 'down_max_cps')

ARDUINO_ADDR = config.get('arduino', 'address')
UPLINK_PIN = config.getint('arduino', 'pin_up')
DOWNLINK_PIN = config.getint('arduino', 'pin_down')

LOGIN_DELAY = timedelta(config.getint('router', 'login_refresh_interval'))

USERNAME = config.get('router', 'username')
PASSWORD = config.get('router', 'password')

NUM_PTS_AVERAGE = config.getint('runtime', 'num_pts_average')
LOOP_DELAY_SEC = config.getfloat('runtime', 'update_delay_sec')

LOGIN_URL = 'http://' + ROUTER_ADDR + '/index.php'
DATA_URL = 'http://' + ROUTER_ADDR + '/ifstats.php?if=' + IF_NAME

# Global / shared variables
data_up = deque()
data_down = deque()
last_data = -1.0, -1.0, -1.0
last_login_time = 0
sess = requests.Session()


def do_login():
    # This is the semi-magical data structure holding the login info for requests
    login_data = {'login':'Login', 'passwordfld':PASSWORD, 'usernamefld':USERNAME}

    log.info('Logging in to router...')
    r = sess.post(LOGIN_URL, data=login_data)
    if r.ok:
        log.debug('ok')
        return r
    log.error('Error logging in to router!')
    return None

def get_datapoint():
    log.debug('Fetching data...')
    r = sess.get(DATA_URL).text
    d = r.split('|')
    if len(d) != 3:
        log.error('Error parsing data from router!')
        return None, None, None

    return float(d[0]), float(d[1]), float(d[2])

def scale_datum(datum):
    # Convert from the raw format of (time, down_bytes, up_bytes) into two
    # 0-255 readings for the arduino.
    global last_data

    dt = datum[0] - last_data[0]
    if dt <= 0.0:
        return 0,0

    bytes_down = datum[1] - last_data[1]
    bytes_up = datum[2] - last_data[2]
    up_per_sec = bytes_up / dt
    down_per_sec = bytes_down / dt
    # Arduino output is 0-255 (PWM)
    scaled_down = (down_per_sec / DOWNLINK_MAX_CPS) * 255.0
    scaled_up = (up_per_sec / UPLINK_MAX_CPS) * 255.0
    last_data = datum
    return scaled_down, scaled_up

# To avoid edge effects, we simply sample N+1 times at startup.
def get_initial_data():

    global last_data
    last_data = get_datapoint()

    for x in xrange(NUM_PTS_AVERAGE):
        datum = get_datapoint()
        cur_down, cur_up = scale_datum(datum)
        data_up.append(cur_up)
        data_down.append(cur_down)
        sleep(LOOP_DELAY_SEC)

def get_scaled_datapoint():
    sc_data = scale_datum(get_datapoint())
    data_up.append(sc_data[1])
    data_up.popleft()
    data_down.append(sc_data[0])
    data_down.popleft()

# See http://stackoverflow.com/questions/14884017/how-to-calculate-moving-average-in-python-3-3/14942753#14942753
# for a more elegant solution. This is just a geometric average, need exponential really.
def compute_average():
    avg_up = sum(data_up) / len(data_up)
    avg_down = sum(data_down) / len(data_down)
    return int(avg_down), int(avg_up)

def main_loop():
    log.info('Filling initial data for averaging')
    get_initial_data()

    log.info('Starting monitoring with ' + str(NUM_PTS_AVERAGE) + '-point average and ' + str(LOOP_DELAY_SEC) + ' seconds per point.')
    while True:
        try:
            get_scaled_datapoint()
            down, up = compute_average()
            update_meters(up, down)
            sleep(LOOP_DELAY_SEC)

            if (datetime.now() - last_login_time) > LOGIN_DELAY:
                log.info('Time to renew login!')
                if (do_login() == None):
                    return

        except KeyboardInterrupt:
            log.info('Zeroing meters and exiting.')
            update_meters(0, 0)
            return

def update_meters(uplink, downlink):
    log.debug('Updating meters...')
    url = 'http://' + ARDUINO_ADDR + '/' +  str(UPLINK_PIN) + '/' + str(uplink)
    log.debug(url)
    urlopen(url).close()
    url = 'http://' + ARDUINO_ADDR + '/' + str(DOWNLINK_PIN) + '/' + str(downlink)
    log.debug(url)
    urlopen(url).close()
    log.debug('done')

if __name__ == '__main__':
    log.basicConfig(level=log.INFO, format='%(asctime)s %(levelname)s [%(funcName)s] %(message)s')

    if do_login() == None:
        log.error('Unable to login')
        exit(1)

    last_login_time = datetime.now()
    main_loop()
