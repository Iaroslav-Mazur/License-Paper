import socket
import pickle
import threading
import time
import argparse
import os
import os.path
from random import shuffle

SEED_NODE_PORT = 1500
MAX_ACTIVE_CONNECTIONS = 4
active_peers_ports = []
peers_socks_vers_out = [] #the sockets in which I'm always the first one to write
peers_socks_vers_in = [] #the sockets in which my peers are always the first ones to write


def talk_to_a_client(conn, addr):
	connection_time = time.time()
	addr_you = None
	print('Connected by', addr)
	while True:
		data = conn.recv(1024)
		conn.sendall(data)
		# if addr_you:
		# 	print("{} sent me: {}".format(addr_you, data))
		# else: 
		# 	print("data: ", data)
		if not data: break
		if data == b'get_peer_ports':
			pickled_peers = pickle.dumps(active_peers_ports)
			conn.sendall(pickled_peers)
			if conn.recv(1024) != pickled_peers:
				raise Exception("conn.recv(1024) != pickled_peers")

# #if you know enough active peers, don't connect any new peers yet
# 		if len(active_peers_ports) < MAX_ACTIVE_CONNECTIONS:
			
		elif data == b'version_msg':
			
			peers_version_msg = conn.recv(1024)
			conn.sendall(peers_version_msg)
			peers_version_msg = pickle.loads(peers_version_msg)
			current_time_you, addr_me, addr_you, your_highest_block = peers_version_msg

			if addr_me == my_port_nr:
				my_reply = bytes((str(current_time_you) + 'accepted').encode('UTF-8'))
				conn.sendall(my_reply)
				if conn.recv(1024) != my_reply:
					raise Exception("conn.recv(1024) != my_reply")

				my_version_msg = (time.time(), addr_you, my_port_nr, 0)
				conn.sendall(pickle.dumps(my_version_msg))
				if pickle.loads(conn.recv(1024)) != my_version_msg:
					raise Exception("pickle.loads(conn.recv(1024)) != my_version_msg")

				ver_ack = conn.recv(1024)
				conn.sendall(ver_ack)
				if ver_ack == bytes((str(my_version_msg[0]) + 'accepted').encode('UTF-8')):
					if addr_you not in active_peers_ports:
						active_peers_ports.append(addr_you)
					peers_socks_vers_in.append((conn, peers_version_msg)) 
				else:
					raise Exception("ver_ack != bytes((str(my_version_msg[0]) + 'accepted').encode('UTF-8')")
			else:
				conn.sendall(bytes((str(current_time_you) + 'rejected').encode('UTF-8')))
				raise Exception("current_time_you rejected")

		elif data == b'still alive':
			pass
		else:
			raise Exception("not a valid command")

		#connect to the new peer in return (after 5 seconds since the connection time have passed)
		since_connection = time.time()
		if (since_connection - connection_time  > 5):
			already_connected = 0
			for tuples in peers_socks_vers_out:
				if addr_you == tuples[1][2]:
					already_connected = 1
			if not already_connected:
				#maybe, connect in response only when you have < MAX_ACTIVE_CONNECTIONS?
				peers_socks_vers_out.append(connect_to_a_peer(addr_you))
				remember_peers()
	# shutdown_and_close(conn) #this point is never reached

def connect_to_a_peer(peers_port):
	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.connect(('', peers_port))
	
	s.sendall(b'version_msg')
	print("trying to connect to {}".format(peers_port))
	if s.recv(1024) != b'version_msg':
		raise Exception("s.recv(1024) != b'version_msg'")

	my_version_msg = (time.time(), peers_port, my_port_nr, 0)
	s.sendall(pickle.dumps(my_version_msg))
	if s.recv(len(pickle.dumps(my_version_msg))) != pickle.dumps(my_version_msg):
		raise Exception("s.recv(1024) != pickle.dumps(my_version_msg)")

	peer_verdict = s.recv(1024)
	s.sendall(peer_verdict)
	if peer_verdict != bytes((str(my_version_msg[0]) + 'accepted').encode('UTF-8')):
		print(peer_verdict, '\n', bytes((str(my_version_msg[0]) + 'accepted').encode('UTF-8')))
		raise Exception("s.recv(1024) != bytes(str(my_version_msg[0]) + 'accepted')")

	peers_version_msg = s.recv(1024)
	s.sendall(peers_version_msg)
	current_time_you, addr_me, addr_you, your_highest_block = pickle.loads(peers_version_msg)
	if addr_me == my_port_nr and addr_you == peers_port:
		s.sendall(bytes((str(current_time_you) + 'accepted').encode('UTF-8')))
	else:
		s.sendall(bytes((str(current_time_you) + 'rejected').encode('UTF-8')))
		raise Exception("bytes(str(current_time_you) + 'rejected')")

	temp = s.recv(1024)
	if temp != bytes((str(current_time_you) + 'accepted').encode('UTF-8')):
		print (temp, '\n', bytes((str(current_time_you) + 'accepted').encode('UTF-8')))
		raise Exception("s.recv(1024) != bytes(str(current_time_you) + 'accepted')")

	if addr_you not in active_peers_ports:
		active_peers_ports.append(addr_you)

	peers_version_msg = pickle.loads(peers_version_msg)
	return (s, peers_version_msg)

def connect_to_more_peers(peers_ports):
	for i in peers_ports:
			if i != my_port_nr and i not in active_peers_ports:
					if len(active_peers_ports) < MAX_ACTIVE_CONNECTIONS:
						peers_socks_vers_out.append(connect_to_a_peer(i))

def get_peer_ports(s):
	s.sendall(b'get_peer_ports')
	if s.recv(1024) != b'get_peer_ports':
		raise Exception("s.recv(1024) != b'get_peer_ports'")

	data = s.recv(1024)
	s.sendall(data)
	peers_ports = pickle.loads(data)
	# print('Received', peers_ports)
	shuffle(peers_ports)
	# print('Shuffled: ', peers_ports)
	return peers_ports #return the randomized list of ports

def become_a_server(my_port_nr):
	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	s.bind(('', my_port_nr))
	s.listen()
	while True:
		conn, addr = s.accept()
		threading.Thread(target = talk_to_a_client, args = (conn,addr)).start()

def remember_peers():
	file_name = "recent_successful_connections" + str(my_port_nr)
	with open(file_name, "w") as f:
		for sock_ver in peers_socks_vers_out:
			f.write(str(sock_ver[1][2]) + '\n')

def monitor_the_peer_connections():
	# failed_still_alives = []
	# for i in range(len(peers_socks_vers_out)):
	# 	failed_still_alives[i].append(0)

	def check_whether_alive():
		# print("checking whether alive...")
		for sock_ver in peers_socks_vers_out[:]:
			# print ("check_whether_alive {}: {}".format(sock_ver[1][2], sock_ver[0]))
			sock_ver[0].sendall(b'still alive')
			# print("peers_socks_vers_out: ", peers_socks_vers_out)
			# print ("Asked {} whether it is still alive ({})".format(sock_ver[0], time.time()))
			sock_ver[0].settimeout(0.25)
			try:
				reply = sock_ver[0].recv(1024) 
				if reply != b'still alive':
					print ("{} is no longer alive!".format(sock_ver[0]))
					# print("reply: ", reply)
					shutdown_close_remove(sock_ver)
					#remember just the active peers
					remember_peers()
				else:
					pass
					# print ("{} is still alive".format(sock_ver[0]))
				# print("peers_socks_vers_out: ", peers_socks_vers_out)
				sock_ver[0].settimeout(None)
			except socket.timeout:
				print ("\nsocket.timeout!\n")
				shutdown_close_remove(sock_ver)
	while True:
		check_whether_alive()

		file_name = "recent_successful_connections" + str(my_port_nr)
		if not os.path.isfile(file_name):
			remember_peers()
		elif os.stat(file_name).st_size == 0:
				remember_peers()

		time.sleep(2)


def shutdown_and_close(sock):
	try:
		sock.shutdown(socket.SHUT_RDWR)
	except socket.error:
		pass
	sock.close()

def shutdown_close_remove(sock_ver):
	shutdown_and_close(sock_ver[0])
	active_peers_ports.remove(sock_ver[1][2])
	peers_socks_vers_out.remove(sock_ver)
	for tuples in peers_socks_vers_in:
		if sock_ver == tuples[1][2]:
			peers_socks_vers_in.remove(sock_ver)

def maximize_active_peers():
	while len(active_peers_ports) == 0:
		time.sleep(1)
	
	previous_active_peers_ports = len(active_peers_ports)
	
	while True:
		current_active_peers_ports = len(active_peers_ports)
		# set_1 = set(previous_active_peers_ports)
		# set_2 = set(current_active_peers_ports)
		# difference = set_1.symmetric_difference(set_2)
		# print("\ndifference: ", list(difference))
		# if len(difference) != 0: # and len(current_active_peers_ports) < MAX_ACTIVE_CONNECTIONS:
		if previous_active_peers_ports != current_active_peers_ports:
			print("\nactive peers before: {}\n".format(previous_active_peers_ports))
			shuffled_peers_socks_vers_out = peers_socks_vers_out
			# shuffle(shuffled_peers_socks_vers_out)
			for sock_ver in shuffled_peers_socks_vers_out:
				peers_peers = get_peer_ports(sock_ver[0])
				connect_to_more_peers(peers_peers) #wait some time before connecting?
			print("\nactive peers after: {}\n".format(active_peers_ports))
			previous_active_peers_ports = current_active_peers_ports
		time.sleep(1)

def print_active_peers_ports():
	while True:
		print("active_peers_ports: ", active_peers_ports)
		time.sleep(1)


parser = argparse.ArgumentParser()
parser.add_argument("my_port_nr", type=int, 
						help="the desired listening port number (1024-65535) for your node")
parser.add_argument("-f", "--friend_port_nr", type=int, 
						help="the optional port of a known trusted peer to be connected to")
args = parser.parse_args()
my_port_nr = args.my_port_nr
if 1024 > my_port_nr or my_port_nr > 65535: #check the same for the friend's port?
	raise Exception("The specified my_port_nr is out of range!")

recent_peers = []
if args.friend_port_nr == None:
	file_name = "recent_successful_connections" + str(my_port_nr)
	if os.path.isfile(file_name):
		with open(file_name,'r') as f:
			for line in f.readlines():
				recent_peers.append(int(line))
	if len(recent_peers) == 0:
		first_peer_port_nr = SEED_NODE_PORT
else:
	first_peer_port_nr = args.friend_port_nr

go_for_the_seed = 1
if len(recent_peers) != 0:
	connect_to_more_peers(recent_peers)
	if len(peers_socks_vers_out) > 0:
		go_for_the_seed = 0

if go_for_the_seed == 1:
	if my_port_nr != SEED_NODE_PORT:
		peers_socks_vers_out.append(connect_to_a_peer(first_peer_port_nr))
		s = peers_socks_vers_out[0][0]
		peers_ports = get_peer_ports(s)
		connect_to_more_peers(peers_ports)


#become a full-fledged node
threading.Thread(target = become_a_server, args = [my_port_nr]).start()
threading.Thread(target = monitor_the_peer_connections).start()

# threading.Thread(target = maximize_active_peers).start()
# threading.Thread(target = print_active_peers_ports).start()

'''
#Shutdown and close all sockets
for i in peers_socks_vers_in:
	shutdown_and_close(i[0])
for i in peers_socks_vers_out:
	shutdown_and_close(i[0])
'''
