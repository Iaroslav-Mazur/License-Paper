import os
import time

port_nr = 1500

for i in range(0,200):
	os.system("python3 networking.py " + str(port_nr + i) + "> " + str(port_nr + i) +" &")
	time.sleep(0.05)