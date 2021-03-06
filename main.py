import serial       # Used for UART communication
import pynmea2      # Used for GPS Library
import os           # Used to check if a drive is mounted
import time         # Used for delays
import smbus        # Used for sensor access
import math         # Used for math operations
import shutil       # Used for file operations
import RPi.GPIO as GPIO  # Needed for GPIO actions (eg. Buttons)

from multiprocessing import Process, SimpleQueue  # Used for multiprocessing
from imusensor.MPU9250 import MPU9250   # Used for getting MPU9250 readings
from imusensor.filters import madgwick  # Used for the madgwick filter
from datetime import datetime           # Used for the madgwick filter timing


# Function definitions:
def empty_queue(queue):         # empty a given queue
    while not queue.empty():    # while it's not empty
        queue.get()             # get elements from it


def usb_automount():
    done = False    # init done as false
    global collecting_data
    while not done and not collecting_data:                     # only loop this while it's not done and not collecting data
        ismounted = os.path.ismount("/media/usb0")              # check if a drive is mounted
        print("Device mounted: " + str(ismounted))              # output drive mount status
        if ismounted:                                           # if a drive is mounted, copy the datafile to it
            try:                                                # try to copy the file
                for filename in os.listdir("./data/"):          # loop through all datafiles
                    shutil.copy("./data/"+filename, "/media/usb0")  # Copy the current file to the drive
                    print("copied!")                            # Confirmation that a file was copied successfully
                    GPIO.output(led, 1)  # turn LED on
                    time.sleep(0.1)
                    GPIO.output(led, 0)  # turn LED off
            except:                                             # Error-Case: tell the user that the file wasn't copied
                print("copy error! (is there a datafile?)")     # Write the error
            while ismounted:                                    # while the device is mounted, tell the user to unplug it
                ismounted = os.path.ismount("/media/usb0")      # check the mount state of the drive
                print("remove drive!")                          # Tell the user to remove the drive
                done = True                                     # Break the automount loop
                time.sleep(1)                                   # 1-Second delay
        time.sleep(1)                                           # 1-Second delay


def sensor_fusion():
    currtime = time.time()      # get the current time for the first sensorfusion
    mpuerror = False            # init mpuerror as false
    calc_count = 0
    while not mpuerror:
        try:
            imu.readSensor()
            for fusionloop in range(10):  # get new sensor readings
                newtime = time.time()  # run the sensorfusion algorythm 10x faster than the sensor gets read
                dt = newtime - currtime  # get the new time
                currtime = newtime  # calculate the difference between the last and the new time
                sensorfusion.updateRollPitchYaw(imu.AccelVals[0], imu.AccelVals[1], imu.AccelVals[2], imu.GyroVals[0],
                                                imu.GyroVals[1], imu.GyroVals[2], imu.MagVals[0], imu.MagVals[1],
                                                imu.MagVals[2], dt)  # call the sensorfusion algorithm
            if calc_count == 25:
                roll = sensorfusion.roll  # get roll
                pitch = sensorfusion.pitch  # get pitch
                yaw = sensorfusion.yaw  # get yaw
                temp = imu.Temp  # get temp

                a = math.radians(roll - 90)  # flip the roll data by -90 degrees and save it into a
                b = math.radians(pitch + 90)  # flip the pitch data by 90 degrees and save it into a

                flipa = math.radians(roll - 180)  # flip the roll data by -180 degrees and save it into flipa

                if a < math.pi * -1:  # if a is now less than -pi
                    a = a + 2 * math.pi  # flip it by 2pi

                if b > math.pi:  # if a is now more than pi
                    b = b - 2 * math.pi  # flip it by -2pi

                if flipa < math.pi * -1:  # if flip a is now less than -pi
                    flipa = flipa + 2 * math.pi  # flip it by 2pi

                xoffs = math.sqrt(((g * math.tan(math.radians(90))) / math.sqrt(
                    (math.tan(math.radians(90)) ** 2) / (math.cos(b) ** 2) + 1)) ** 2)  # Offset in x
                yoffs = g / math.sqrt((math.tan(0) ** 2) + (math.tan(a) ** 2) + 1)  # Offset in y
                zoffs = g / math.sqrt(((1 / math.tan(a)) ** 2) + ((1 / math.tan(b)) ** 2) + 1)  # Offset in z

                if pitch < 0:  # check if x-Offset should be subtracted
                    ax = imu.AccelVals[0] - xoffs  # subtract x-Offset
                else:  # check if x-Offset should be added
                    ax = imu.AccelVals[0] + xoffs  # add x-Offset

                if flipa < 0:  # check if y-Offset should be subtracted
                    ay = imu.AccelVals[1] - yoffs  # subtract y-Offset
                else:  # check if y-Offset should be added
                    ay = imu.AccelVals[1] + yoffs  # add y-Offset

                az = imu.AccelVals[2] + zoffs  # subtract z-Offset
                
                roll += 180
                if roll > 180:  # if roll is now greater than 180
                    roll = roll - 360  # flip it by 360

                empty_queue(mpu_queue)  # empty the queue
                mpu_queue.put(str(roll)+","+str(pitch)+","+str(yaw)+","+str(ax)+","+str(ay)+","+str(az)+","+str(temp))
                calc_count = 0
            calc_count +=1
            time.sleep(0.01)

        except:
            empty_queue(mpu_queue)  # empty the queue
            mpu_queue.put("error,error,error,error,error,error,error")


def get_gps():
    gpserror = False        # set gpserror false
    while not gpserror:
        try:
            newdata = str(ser.readline())   # get new data
            newdata = newdata[2:-5]         # delete unwanted characters
            if newdata[0:6] == "$GPRMC":  # check if the right string is available
                newmsg = pynmea2.parse(newdata)  # parse new data
                lat = newmsg.latitude  # save latitude
                lng = newmsg.longitude  # save longitude
                empty_queue(gps_queue)  # empty the queue
                gps_queue.put(str(lat) + "," + str(lng))  # save gps data as string

        except:
            empty_queue(gps_queue)  # empty the queue
            gps_queue.put("error,error")    # set gps to error
            gpserror = True


def counter_rear_l(pin):                            # function for the rear left wheel time measurement
    global dt_rl, newtime_rl, currtime_rl, flag_rl, cnt_rear_l  # make variables global
    newtime_rl = time.time()                        # get newtime
    dt_rl = newtime_rl - currtime_rl                # delta time
    currtime_rl = newtime_rl                        # write newtime to current time
    flag_rl = True                                  # set flag true
    cnt_rear_l += 1


def counter_rear_r(pin):                        # function for the rear right wheel count
    global dt_rr, newtime_rr, currtime_rr, flag_rr, cnt_rear_r  # make variables global
    newtime_rr = time.time()  # get newtime
    dt_rr = newtime_rr - currtime_rr  # delta time
    currtime_rr = newtime_rr  # write newtime to current time
    flag_rr = True  # set flag true
    cnt_rear_r += 1


def counter_front_l(pin):  # function for the front left wheel count
    global dt_fl, newtime_fl, currtime_fl, flag_fl, cnt_front_l  # make variables global
    newtime_fl = time.time()  # get newtime
    dt_fl = newtime_fl - currtime_fl  # delta time
    currtime_fl = newtime_fl  # write newtime to current time
    flag_fl = True  # set flag true
    cnt_front_l += 1


def counter_front_r(pin):  # function for the front right wheel count
    global dt_fr, newtime_fr, currtime_fr, flag_fr, cnt_front_r  # make variables global
    newtime_fr = time.time()  # get newtime
    dt_fr = newtime_fr - currtime_fr  # delta time
    currtime_fr = newtime_fr  # write newtime to current time
    flag_fr = True  # set flag true
    cnt_front_r += 1


def get_rpm(d_wheel, slots_rear, slots_front):     # function for the rpm calculations
    global dt_rl, dt_rr, dt_fl, dt_fr, flag_rl, flag_rr, flag_fl, flag_fr, rpm_rear_l, rpm_rear_r, rpm_front_l, rpm_front_r, vel_ms, newtime_rpm, currtime_rpm, dt_rpm, cnt_rear_l, cnt_rear_r, cnt_front_l, cnt_front_r # make variables global
    newtime_rpm = time.time()  # get newtime
    dt_rpm = newtime_rpm - currtime_rpm  # delta time
    currtime_rpm = newtime_rpm  # write newtime to current time

    alt_rpm_rear_l = ((cnt_rear_l / dt_rpm) * 60) / slots_rear
    alt_rpm_rear_r = ((cnt_rear_r / dt_rpm) * 60) / slots_rear
    alt_rpm_front_l = ((cnt_front_l / dt_rpm) * 60) / slots_front
    alt_rpm_front_r = ((cnt_front_r / dt_rpm) * 60) / slots_front

    cnt_front_l = 0
    cnt_front_r = 0
    cnt_rear_l = 0
    cnt_rear_r = 0

    if flag_rl == True:
        rpm_rear_l = (60/dt_rl)/slots_rear  # calculate the rpm
    else:
        rpm_rear_l = 0

    if flag_rr == True:
        rpm_rear_r = (60/dt_rr)/slots_rear  # calculate the rpm
    else:
        rpm_rear_r = 0

    if flag_fl == True:
        rpm_front_l = (60/dt_fl)/slots_front  # calculate the rpm
    else:
        rpm_front_l = 0

    if flag_fr == True:
        rpm_front_r = (60/dt_fr)/slots_front  # calculate the rpm
    else:
        rpm_front_r = 0

    if rpm_rear_l > alt_rpm_rear_l * 1.5:
        rpm_rear_l = alt_rpm_rear_l

    if rpm_rear_r > alt_rpm_rear_r * 1.5:
        rpm_rear_r = alt_rpm_rear_r

    if rpm_front_l > alt_rpm_front_l * 1.5:
        rpm_front_l = alt_rpm_front_l

    if rpm_front_r > alt_rpm_front_r * 1.5:
        rpm_front_r = alt_rpm_front_r

    vel_ms = d_wheel * math.pi * (float((rpm_front_l + rpm_front_r) / 2) / 60) # calculate the velocity as an average of the two front wheels
    flag_rl = False
    flag_rr = False
    flag_fl = False
    flag_fr = False


def print_data(u_mpu, u_rpm_rear_l, u_rpm_rear_r, u_rpm_front_l, u_rpm_front_r, u_vel_ms, u_gps):        # print the data (meant for debugging purposes)
    print("MPU: " + str(u_mpu))  # print roll
    print("RPM: " + str(u_rpm_rear_l) + "," + str(u_rpm_rear_r) + "," + str(u_rpm_front_l) + "," + str(u_rpm_front_r) + "," + str(u_vel_ms))  # print rpm
    print("GPS: " + str(u_gps))  # print gps


def write_data(u_now, u_mpu, u_rpm_rear_l, u_rpm_rear_r, u_rpm_front_l, u_rpm_front_r, u_vel_ms, u_gps):  # write the data to the internal sd card
    file.write(str(u_now) + ",")  # write Time
    file.write(str(u_mpu) + ",")  # write roll
    file.write(str(u_rpm_rear_l) + "," + str(u_rpm_rear_r) + "," + str(u_rpm_front_l) + "," + str(u_rpm_front_r) + "," + str(u_vel_ms) + ",")  # write rpm
    file.write(str(u_gps))  # write gps
    file.write("\n")  # write newline


def start_stop(pin):                            # function for switching modes
    global collecting_data
    collecting_data = not collecting_data       # invert collecting_data
    if not collecting_data:               # Also, close the file if data collection is stopped
        file.close()


if not os.path.exists('data'):  # If the data path doesn't exit, create it
    os.makedirs('data')

g = 10                                              # set g as 10
mpu_queue = SimpleQueue()                                  # init imuerror
try:                                                # Error handling for the IMU
    sensorfusion = madgwick.Madgwick(0.5)           # set Madgwick as the sensorfusion-algorythm
    address = 0x68                                  # MPU9250 I2C-Address
    bus = smbus.SMBus(1)                            # smbus for the imu
    imu = MPU9250.MPU9250(bus, address)             # set MPU9250 as the selected IMU
    imu.begin()                                     # begin IMU readings
    imu.loadCalibDataFromFile("./config/Calib.json")  # load calibration data
    process_sensorfusion = Process(target=sensor_fusion)  # create process for the sensorfusion
    process_sensorfusion.start()                    # start the process for the sensorfusion

except:                                             # Except-Statement for imuerror
    mpu_queue.put("error,error,error,error,error,error,error")
    print("MPU 9250: Error! (Not connected?)")      # Write error message


port = "/dev/ttyAMA0"                               # define UART device
ser = serial.Serial(port, baudrate=9600, timeout=0.5)  # set serial communication options
gps_queue = SimpleQueue()                           # create gps queue
gps_queue.put("error,error")                        # set gps to error,error (error code)
gps_process = Process(target=get_gps)               # create process for the gps module
gps_process.start()                                 # start the process for the gps module

collecting_data = False                             # init collecting_data
led = 37                                            # set the LED to PIN 37
modeswitch = 40                                     # set the modeswitch Button to PIN 40
GPIO.setmode(GPIO.BOARD)                            # Set GPIO to use Board pin layout
GPIO.setup(modeswitch, GPIO.IN, pull_up_down=GPIO.PUD_UP)   # turn on pullup and set as input (modeswitch button)
GPIO.setup(led, GPIO.OUT)   # set as output (led)
GPIO.add_event_detect(modeswitch, GPIO.FALLING, callback=start_stop, bouncetime=1000)   # Attach interrupt to modeswitch

sensor_rear_L = 11      # set rear_L pin
sensor_rear_R = 12      # set rear_R pin
sensor_front_L = 13     # set front_L pin
sensor_front_R = 15     # set front_R pin
GPIO.setup(sensor_rear_L, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)  # turn on pulldown and set as input (rear_L)
GPIO.setup(sensor_rear_R, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)  # turn on pulldown and set as input (rear_R)
GPIO.setup(sensor_front_L, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)  # turn on pulldown and set as input (front_L)
GPIO.setup(sensor_front_R, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)  # turn on pulldown and set as input (front_R)
GPIO.add_event_detect(sensor_rear_L, GPIO.RISING, callback=counter_rear_l)  # Attach interrupt to rear_L
GPIO.add_event_detect(sensor_rear_R, GPIO.RISING, callback=counter_rear_r)  # Attach interrupt to rear_R
GPIO.add_event_detect(sensor_front_L, GPIO.RISING, callback=counter_front_l)    # Attach interrupt to front_L
GPIO.add_event_detect(sensor_front_R, GPIO.RISING, callback=counter_front_r)    # Attach interrupt to front_R
currtime_rl = time.time()
currtime_rr = currtime_rl
currtime_fl = currtime_rl
currtime_fr = currtime_rl
currtime_rpm = currtime_rl
flag_rl = False
flag_rr = False
flag_fl = False
flag_fr = False
rpm_rear_l = 0
rpm_rear_r = 0
rpm_front_l = 0
rpm_front_r = 0
cnt_rear_l = 0
cnt_rear_r = 0
cnt_front_l = 0
cnt_front_r = 0
vel_ms = 0

while 1:                            # main loop
    if not collecting_data:   # if in usb-transfer mode
        GPIO.output(led, 0)  # turn LED off
        usb_automount()             # call usb_automount

    elif collecting_data:      # if in data collection mode
        GPIO.output(led, 1)  # turn LED on
        now = str(datetime.now())    # get datetime for the file name
        now = now.replace(' ', '_')  # replace blank space with underline for the file name
        now = now.replace(':', '_')  # replace colon with underline for the file name
        now = now.replace('.', '_')  # replace dot with underline for the file name
        file = open("./data/" + now + ".txt", 'w')  # create and open a new datafile
        file.write("datetime,roll,pitch,yaw,ax,ay,az,Temp,rpm_rear_l,rpm_rear_r,rpm_front_l,rpm_front_r,vel_ms,lat,lng\n")  # write the data legend into a new line
        while collecting_data:
            now = datetime.now()    # get datetime
            if not gps_queue.empty():
                gps = gps_queue.get()   # get gps data
            if not mpu_queue.empty():
                mpu = mpu_queue.get()   # get rpm data
            get_rpm(0.153, 4, 4)
            print_data(mpu, rpm_rear_l, rpm_rear_r, rpm_front_l, rpm_front_r, vel_ms, gps)         # print the data (meant for debugging purposes)
            write_data(now, mpu, rpm_rear_l, rpm_rear_r, rpm_front_l, rpm_front_r, vel_ms, gps)    # write the data to the internal sd card
            time.sleep(0.25)
