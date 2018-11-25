import key_gen
import miner

import socket
import pickle
import threading
from threading import Lock
import time
from datetime import datetime
import argparse
import os
import os.path
from random import shuffle
import hashlib
import copy

max_peers_lock = threading.Lock() #the lock used to NOT accept more peers than I should

SEED_NODE_PORT = 1500
MAX_ACTIVE_CONNECTIONS_OUT = 2
MAX_ACTIVE_CONNECTIONS_IN = 4
MAX_ACTIVE_CONNECTIONS = MAX_ACTIVE_CONNECTIONS_IN + MAX_ACTIVE_CONNECTIONS_OUT
STATE_CATCHING_UP = False
# STATE_CATCHING_UP_PEER = False
active_peers_ports = []
peers_socks_vers_out = [] #the sockets in which I'm always the first one to write
peers_socks_vers_in = [] #the sockets in which my peers are always the first ones to write

blockchain_lock = threading.Lock()
blockchain = [] #always to be modified after acquiring the blockchain_lock
with open('genesis_block', 'rb') as f:
	genesis_block = pickle.load(f)
	blockchain.append(genesis_block)
# print("{}: Genesis block: {}".format(datetime.now().time(), blockchain[0]))

priv_key = key_gen.generate_a_private_key()
pub_key_compressed = key_gen.compress_the_public_key_point(key_gen.generate_the_public_key_point(priv_key))

peers_socks_vers_out_lock = threading.Lock() #this lock must be used to avoid sending different requests to the peers at the same time 

def talk_to_a_client(conn, addr):
	connection_time = time.time()
	addr_you = None
	data = conn.recv(1024)
	# if addr_you:
	# 	print("{}: {} sent me: {}".format(datetime.now().time(), addr_you, data))
	# else: 
	# 	print("{}: data: {}".format(datetime.now().time(), data))
	try:
		if data != b'version_msg':
			raise Exception("not a valid first command!")

		max_peers_lock.acquire()
		if len(active_peers_ports) >= MAX_ACTIVE_CONNECTIONS_IN:
			print("{}: {}, I'm full. Try connecting to my peers".format(datetime.now().time(), addr))
			pickled_peers = pickle.dumps(active_peers_ports)
			conn.sendall(pickled_peers)
			return #end the thread from within

		conn.sendall(data)
		peers_version_msg = conn.recv(1024)
		conn.sendall(peers_version_msg)
		peers_version_msg = pickle.loads(peers_version_msg)
		current_time_you, addr_me, addr_you, your_highest_block = peers_version_msg

		if addr_me != my_port_nr:
			conn.sendall(bytes((str(current_time_you) + 'rejected').encode('UTF-8')))
			raise Exception("current_time_you rejected")
			
		my_reply = bytes((str(current_time_you) + 'accepted').encode('UTF-8'))
		conn.sendall(my_reply)
		if conn.recv(1024) != my_reply:
			raise Exception("conn.recv(1024) != my_reply")

		my_version_msg = (time.time(), addr_you, my_port_nr, len(blockchain)-1)
		conn.sendall(pickle.dumps(my_version_msg))
		if pickle.loads(conn.recv(1024)) != my_version_msg:
			raise Exception("pickle.loads(conn.recv(1024)) != my_version_msg")

		ver_ack = conn.recv(1024)
		conn.sendall(ver_ack)
		if ver_ack != bytes((str(my_version_msg[0]) + 'accepted').encode('UTF-8')):
			raise Exception("ver_ack != bytes((str(my_version_msg[0]) + 'accepted').encode('UTF-8')")
							
		if addr_you not in active_peers_ports:
			active_peers_ports.append(addr_you)
		peers_socks_vers_in.append((conn, peers_version_msg))
		print("{}: Connected by {}".format(datetime.now().time(), addr_you))

		#connect to the new peer in return
		connection_result = None
		peers_socks_vers_out_lock.acquire()
		if find_sock_out(addr_you) is None:
			connection_result = connect_to_a_peer(addr_you)
			
			if type(connection_result) is not tuple:
				print("{}: {}".format(datetime.now().time(), connection_result))
				raise Exception("Couldn't connect in return to {}: the peer is full!".format(addr_you))

			peers_socks_vers_out.append(connection_result)
			# print("{}: Appended port {} from inside talk_to_a_client".format(datetime.now().time(), addr_you))
			remember_peers()
				
		peers_socks_vers_out_lock.release()
		
		# global STATE_CATCHING_UP_PEER
		# if your_highest_block < current_highest_block:
		# 	STATE_CATCHING_UP_PEER = True

		#sync our blockchains:
		# current_highest_block = len(blockchain) - 1
		# global STATE_CATCHING_UP
		# if your_highest_block > current_highest_block and STATE_CATCHING_UP == False:
		# 	STATE_CATCHING_UP = True
		# 	s = connection_result[0]
		# 	blockchain_lock.acquire()
		# 	while your_highest_block > current_highest_block:
		# 		difference = your_highest_block - current_highest_block
		# 		print("{}: The current difference is: your_highest_block({}) - current_highest_block({}) = {}".format(datetime.now().time(), your_highest_block, current_highest_block, difference))
		# 		for i in range(1, difference+1):
		# 			peers_socks_vers_out_lock.acquire() #potential problem here
		# 			print("{}: acquired peers_socks_vers_out_lock before syncing with {} in talk_to_a_client".format(datetime.now().time(), addr_you))
		# 			s.sendall(b"get_block")
		# 			print("{}: sent get_block to {}".format(datetime.now().time(), addr_you))
		# 			temp = s.recv(1024)
		# 			if temp != b"get_block":
		# 				print("{}: Haven't received the correct echo of b\"get_block\"".format(datetime.now().time()))
		# 				STATE_CATCHING_UP = False
		# 				peers_socks_vers_out_lock.release()
		# 				break
		# 			print("{}: received the correct echo of get_block from {}".format(datetime.now().time(), addr_you))
		# 			wanted_block_nr = current_highest_block + i
		# 			s.sendall(pickle.dumps(wanted_block_nr))
		# 			print("{}: Asked {} to send me the block {}".format(datetime.now().time(), addr_you,wanted_block_nr))
		# 			block_received = s.recv(1024)
		# 			block_received = pickle.loads(block_received)
		# 			peers_socks_vers_out_lock.release()
					
		# 			if miner.is_block_valid(block_received, blockchain[wanted_block_nr - 1]) is False:
		# 				STATE_CATCHING_UP = False
		# 				break

		# 			if len(blockchain) == wanted_block_nr + 1:
		# 				print("{}: The parent block at the height of {} is already present!".format(datetime.now().time(), wanted_block_nr))
		# 			else:
		# 				blockchain.insert(wanted_block_nr, block_received)
		# 				print("{}: Added block {} to the blockchain!".format(datetime.now().time(), wanted_block_nr))
		# 		if STATE_CATCHING_UP != False:
					# peers_socks_vers_out_lock.acquire()
				# 	s.sendall(b"reveal_your_highest_block")
				# 	print("{}: Asked {} to tell me his highest block".format(datetime.now().time(), addr_you))
				# 	your_highest_block = s.recv(1024)
				# 	# peers_socks_vers_out_lock.release()
				# 	your_highest_block = pickle.loads(your_highest_block)
				# 	current_highest_block = len(blockchain) - 1
				# else:
				# 	your_highest_block = 0 #just to break the outer while loop

		# 	STATE_CATCHING_UP = False
		# 	blockchain_lock.release()

	except:
		pass
	finally:
		max_peers_lock.release()

	while True:
		data = conn.recv(1024)
		if not data: break

		if data == b'get_peer_ports':
			pickled_peers = pickle.dumps(active_peers_ports)
			conn.sendall(pickled_peers)
		
		elif data == b"get_block":
			conn.sendall(data)
			wanted_block_nr = conn.recv(1024)
			wanted_block_nr = pickle.loads(wanted_block_nr)
			if wanted_block_nr >= 0 and wanted_block_nr < len(blockchain):
				# blockchain_lock.acquire()
				wanted_block_pickled = pickle.dumps(blockchain[wanted_block_nr])
				# blockchain_lock.release()
				conn.sendall(wanted_block_pickled)
		elif data == b"reveal_your_highest_block":
			my_highest_block = len(blockchain) - 1
			my_highest_block = pickle.dumps(my_highest_block)
			conn.sendall(my_highest_block)
		
		elif data == b'take_new_block':
			#do it in a new, independent thread?
			if STATE_CATCHING_UP is False:
				conn.sendall(data)
				new_block_tuple = conn.recv(1024)
				new_block_tuple = pickle.loads(new_block_tuple)
				new_block_id, new_block = new_block_tuple
				print("{}: Received block {} with hash {}".format(datetime.now().time(), new_block_id,new_block.get_hash_hex()))
				blockchain_lock.acquire()
				threading.Thread(target = react_to_take_new_block, args = [blockchain, blockchain_lock, new_block_id, new_block]).start()

			else:
				conn.sendall(b"I can't accept any new blocks while catching up!")

		elif data == b'still alive':
			conn.sendall(data) #(just echo the msg to show that I'm alive)
		
		else:
			print("{}: \n \"{}\" is not a valid command!\n".format(datetime.now().time(), data))
			# raise Exception("not a valid command")

		
def react_to_take_new_block(blockchain, blockchain_lock, new_block_id, new_block):
	if new_block_id == len(blockchain): #accept just the direct child of the current highest block
		parent_block = blockchain[new_block_id-1]
		if miner.is_block_valid(new_block, parent_block) is True:
			#acquire the blockchain_lock here?
			blockchain.insert(new_block_id, new_block)
			print("{}: Added the received block {}  with hash {} to the blockchain".format(datetime.now().time(), new_block_id, new_block.get_hash_hex()))
		else:
			print("{}: the new block, {}, is invalid".format(datetime.now().time(), new_block_id))

	elif len(blockchain) > 1 and len(blockchain) - 1 == new_block_id: #accept the new block with the same height as the latest one
		parent_block = blockchain[new_block_id-1]
		current_latest_block = blockchain[new_block_id]
		if new_block.block_header.prev_block_hash == current_latest_block.block_header.prev_block_hash:
			if miner.is_block_valid(new_block, parent_block) is True:
				# accept it only if it's been more difficult to mine:
				current_latest_block = blockchain[new_block_id]
				if new_block.block_header.nonce > current_latest_block.block_header.nonce:
					blockchain[new_block_id] = new_block
					#help propagate the replaced block
					print("{}: Replaced the latest block {} with hash {} with a new one that's been more difficult to mine with the hash {}".format(datetime.now().time(), new_block_id, current_latest_block.get_hash_hex(), new_block.get_hash_hex()))
				
				elif new_block.block_header.nonce == current_latest_block.block_header.nonce:
					new_block_plus_nonce = new_block.block_header.header + bytes(new_block.block_header.nonce)
					new_block_hash = hashlib.sha256(new_block_plus_nonce).hexdigest()

					current_latest_block_plus_nonce = current_latest_block.block_header.header + bytes(current_latest_block.block_header.nonce)
					current_latest_block_hash = hashlib.sha256(current_latest_block_plus_nonce).hexdigest()
					
					if int(new_block_hash, 16) < int(current_latest_block_hash, 16):
						blockchain[new_block_id] = new_block
						#help propagate the replaced block
						print("{}: Replaced the latest block {} with hash {} with a new one (hash: {}) with the same nonce, but smaller (int-wise) hash".format(datetime.now().time(), new_block_id, current_latest_block.get_hash_hex(), new_block.get_hash_hex()))
	else:
		print("{}: The new block, {}, isn't the direct child or grandchild of block {}".format(datetime.now().time(), new_block_id, len(blockchain)-1))
	blockchain_lock.release()


def connect_to_a_peer(peers_port):
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.connect(('', peers_port))
		
		s.sendall(b'version_msg')
		data = s.recv(1024)
		if data == b'version_msg':
			my_version_msg = (time.time(), peers_port, my_port_nr, len(blockchain) - 1)
			s.sendall(pickle.dumps(my_version_msg))
			if s.recv(len(pickle.dumps(my_version_msg))) != pickle.dumps(my_version_msg):
				raise Exception("What I've received in response isn't identical to my_version_msg!")

			peer_verdict = s.recv(1024)
			s.sendall(peer_verdict)
			if peer_verdict != bytes((str(my_version_msg[0]) + 'accepted').encode('UTF-8')):
				print("{}: {}\n{}".format(datetime.now().time(), peer_verdict, bytes((str(my_version_msg[0]) + 'accepted').encode('UTF-8'))))
				raise Exception("The peer {} hasn't accepted me!".format(peers_port))

			peers_version_msg = s.recv(1024)
			s.sendall(peers_version_msg)
			current_time_you, addr_me, addr_you, your_highest_block = pickle.loads(peers_version_msg)
			
			if addr_me == my_port_nr and addr_you == peers_port:
				s.sendall(bytes((str(current_time_you) + 'accepted').encode('UTF-8')))
			else:
				s.sendall(bytes((str(current_time_you) + 'rejected').encode('UTF-8')))
				raise Exception("I've rejected the peers_version_msg from {}".format(peers_port))

			temp = s.recv(1024)
			if temp != bytes((str(current_time_you) + 'accepted').encode('UTF-8')):
				print("{}: {}\n{}".format(datetime.now().time(), temp, bytes((str(current_time_you) + 'accepted').encode('UTF-8'))))
				raise Exception("The echo-msg after I've accepted {} isn't identical to mine".format(peers_port))

			if addr_you not in active_peers_ports:
				active_peers_ports.append(addr_you)

			print("{}: Connected to {}".format(datetime.now().time(), peers_port))


			#sync our blockchains:
			current_highest_block = len(blockchain) - 1
			global STATE_CATCHING_UP
			if your_highest_block > current_highest_block and STATE_CATCHING_UP == False:
				print("{}: detected that the peer {} has more blocks than me".format(datetime.now().time(), addr_you))
				STATE_CATCHING_UP = True
				# print("{}: Set STATE_CATCHING_UP to True".format(datetime.now().time()))
				blockchain_lock.acquire()
				# print("{}: acquired blockchain_lock for syncing with {}".format(datetime.now().time(), addr_you))
				while your_highest_block > current_highest_block:
					difference = your_highest_block - current_highest_block
					print("{}: The current difference is: your_highest_block({}) - current_highest_block({}) = {}".format(datetime.now().time(), your_highest_block, current_highest_block, difference))
					for i in range(1, difference+1):
						# peers_socks_vers_out_lock.acquire() #potential problem here
						s.sendall(b"get_block")
						temp = s.recv(1024)
						if temp != b"get_block":
							print("{}: Haven't received the correct echo of b\"get_block\"".format(datetime.now().time()))
							STATE_CATCHING_UP = False
							blockchain_lock.release()
							# peers_socks_vers_out_lock.release()
							break
						wanted_block_nr = current_highest_block + i
						s.sendall(pickle.dumps(wanted_block_nr))
						print("{}: Asked {} to send me the block {}".format(datetime.now().time(), addr_you,wanted_block_nr))
						block_received = s.recv(1024)
						block_received = pickle.loads(block_received)
						# peers_socks_vers_out_lock.release()
						
						if miner.is_block_valid(block_received, blockchain[wanted_block_nr - 1]) is False:
							STATE_CATCHING_UP = False
							blockchain_lock.release()
							break

						if len(blockchain) == wanted_block_nr + 1:
							print("{}: The parent block at the height of {} is already present!".format(datetime.now().time(), wanted_block_nr))
						else:
							blockchain.insert(wanted_block_nr, block_received)
							print("{}: Added block {} to the blockchain!".format(datetime.now().time(), wanted_block_nr))
					
					if STATE_CATCHING_UP == True:
						# peers_socks_vers_out_lock.acquire()
						s.sendall(b"reveal_your_highest_block")
						print("{}: Asked {} to tell me his highest block".format(datetime.now().time(), addr_you))
						your_highest_block = s.recv(1024)
						# peers_socks_vers_out_lock.release()
						your_highest_block = pickle.loads(your_highest_block)
						current_highest_block = len(blockchain) - 1
					else:
						your_highest_block = 0 #just to break the outer while loop
				
				try:
					blockchain_lock.release()
				except:
					print("{}: Exception when trying to release blockchain_lock!".format(datetime.now().time(), ))
				STATE_CATCHING_UP = False

			peers_version_msg = pickle.loads(peers_version_msg)
			return (s, peers_version_msg)
		else:
			peers_ports = pickle.loads(data)
			if type(peers_ports) is list:
				#the peer is full. return all of his neighbours
				return peers_ports
			else:
				raise Exception("Smth strange received in response to my version_msg!")
	except Exception as e:
		print("{}: Couldn't connect to {}. Like, at all!".format(datetime.now().time(), peers_port))
		print(e)
		#no problem. will try connecting to someone else
	finally:
		try:
			blockchain_lock.release()
		except:
			print("{}: Exception when trying to release blockchain_lock in finally!".format(datetime.now().time()))

def connect_to_more_peers(peers_ports):
	#connect to as many peers as possible, starting from peers_ports
	ports_to_be_tried = peers_ports
	ports_already_tried = []
	while len(ports_to_be_tried)>0:
		port_nr = ports_to_be_tried[0]
		ports_already_tried.append(port_nr)

		if len(peers_socks_vers_out) < MAX_ACTIVE_CONNECTIONS_OUT:
			peers_socks_vers_out_lock.acquire()
			if port_nr != my_port_nr and find_sock_out(port_nr) is None:
				connection_result = connect_to_a_peer(port_nr)
				if type(connection_result) is tuple:
					peers_socks_vers_out.append(connection_result)
					# print("{}: Appended port {} from inside connect_to_more_peers".format(datetime.now().time(), port_nr))
					remember_peers()
				elif type(connection_result) is list:
					#the peer is full; got his peers_list
					for peer in connection_result:
						if peer not in ports_already_tried:
							ports_to_be_tried.append(peer)
				else:
					print("{}: Couldn't connect to a peer: something went wrong!".format(datetime.now().time()))
					# raise Exception("Couldn't connect to a peer: something went wrong!")
			peers_socks_vers_out_lock.release()
		
		else: 
			break
		ports_to_be_tried.remove(port_nr)

def get_peer_ports(s):
	s.sendall(b'get_peer_ports')
	# print("{}: Sent get_peer_ports to {}".format(datetime.now().time(), s))

	data = s.recv(1024)
	# print("{}: Received peer_ports from {}".format(datetime.now().time(), s))
	peers_ports = pickle.loads(data)
	shuffle(peers_ports)
	return peers_ports #return the randomized list of ports

def become_a_server(my_port_nr):
	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) #does it really make any difference?
	s.bind(('', my_port_nr))
	s.listen()
	while True:
		conn, addr = s.accept()
		threading.Thread(target = talk_to_a_client, args = (conn,addr)).start() #does it end when the "client" shuts down?

def remember_peers():
	file_name = "recent_successful_connections" + str(my_port_nr)
	with open(file_name, "w") as f:
		for sock_ver in peers_socks_vers_out:
			f.write(str(sock_ver[1][2]) + '\n')

def monitor_the_peer_connections():
	failed_still_alives = dict()

	def check_whether_alive():
		try:
			for sock_ver in peers_socks_vers_out[:]:
				peers_socks_vers_out_lock.acquire()
				sock_ver[0].settimeout(1)
				sock_ver[0].sendall(b'still alive')
				# print("{}: Sent 'still alive' to {}".format(datetime.now().time(), sock_ver[1][2]))
				try:
					reply = sock_ver[0].recv(1024)
					peers_socks_vers_out_lock.release()
					if reply != b'still alive':
						#transform the following code into a function
						if sock_ver[1][2] in failed_still_alives:
							failed_still_alives[sock_ver[1][2]] += 1
							if failed_still_alives[sock_ver[1][2]] > 5:
								print ("{}: {} is no longer alive!".format(datetime.now().time(), sock_ver[1][2]))
								shutdown_close_remove(sock_ver)
								#remember just the active peers
								remember_peers()
						else:
							failed_still_alives[sock_ver[1][2]] = 1

						#stop bombarding with still-alives for a second
						# time.sleep(2)
					else:
						 #sock_ver[0] is still alive; reset its failed_still_alives counter
						 failed_still_alives[sock_ver[1][2]] = 0

					sock_ver[0].settimeout(None)
				except socket.timeout:
					peers_socks_vers_out_lock.release()
					#transform the following code into a function
					if sock_ver[1][2] in failed_still_alives:
						failed_still_alives[sock_ver[1][2]] += 1
						if failed_still_alives[sock_ver[1][2]] > 5:
							print ("\n{}: socket.timeout for {}!\n".format(datetime.now().time(), sock_ver[1][2]))
							# print("{}: Time when socket.timeout for {}".format(datetime.now().time(), sock_ver[1][2]))
							shutdown_close_remove(sock_ver)
							#remember just the active peers
							remember_peers()
					else:
						failed_still_alives[sock_ver[1][2]] = 1

		except Exception as e:
			print("{}: {}".format(datetime.now().time(), e))
		finally:
			try:
				peers_socks_vers_out_lock.release()
			except:
				# print("{}: Exception when trying to release peers_socks_vers_out_lock in finally!".format(datetime.now().time()))
				pass


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
	#make sure that at any given time, you're connected to as many active peers as possible
	while len(active_peers_ports) == 0:
		time.sleep(1)
	
	previous_active_peers_ports = len(active_peers_ports)
	
	while True:
		if STATE_CATCHING_UP == False:
			current_active_peers_ports = len(active_peers_ports)
			if previous_active_peers_ports != current_active_peers_ports:
				if len(peers_socks_vers_out) < MAX_ACTIVE_CONNECTIONS_OUT:
					shuffled_peers_socks_vers_out = peers_socks_vers_out
					shuffle(shuffled_peers_socks_vers_out)
					for sock_ver in shuffled_peers_socks_vers_out:
						# print("{}: Trying to get peers from {}".format(datetime.now().time(), sock_ver[0]))
						peers_peers = get_peer_ports(sock_ver[0])
						connect_to_more_peers(peers_peers)
						#check whether the connections have, actually, happened!
					if len(peers_socks_vers_out) > len(shuffled_peers_socks_vers_out):
						print("\n{}: active peers before: {}\n".format(datetime.now().time(), previous_active_peers_ports))
						print("\n{}: active peers after: {}\n".format(datetime.now().time(), active_peers_ports))
					else:
						# print("{}: still trying...".format(datetime.now().time()))
						break
				if len(peers_socks_vers_out) >= MAX_ACTIVE_CONNECTIONS_OUT:
					previous_active_peers_ports = current_active_peers_ports
					print("{}: active_peers_ports: {}".format(datetime.now().time(), active_peers_ports))
		time.sleep(1)

def print_active_peers_ports():
	while True:
		print("{}: active_peers_ports: {}".format(datetime.now().time(), active_peers_ports))
		time.sleep(1)

def print_blockchain_state():
	#whenever the blockchain grows, print its state
	current_bc_len = len(blockchain)
	while True:
		new_bc_len = len(blockchain)
		if new_bc_len > current_bc_len:
			print("{}: Right now, the blockchain contains {} blocks (excluding the Genesis one):".format(datetime.now().time(), len(blockchain)-1))
			for i in range(len(blockchain)):
				block = blockchain[i]
				print("{}: Block {} hash: {}".format(datetime.now().time(), i,block.get_hash_hex()))
			current_bc_len = new_bc_len
			

def notify_peers_about_new_blocks():
	#do NOT acquire the blockchain_lock in this function
	try:
		blockchain_lock.acquire()
		current_highest_block_nr = len(blockchain) - 1
		blockchain_lock.release()
		parent_block = blockchain[current_highest_block_nr]

		while True:
			blockchain_lock.acquire()
			new_highest_block_nr = len(blockchain) - 1
			blockchain_lock.release()
			replaced_block = blockchain[new_highest_block_nr]

			if new_highest_block_nr > current_highest_block_nr:
				blockchain_lock.acquire()
				parent_block = blockchain[-1]
				blockchain_lock.release()
				for i in range(current_highest_block_nr + 1, new_highest_block_nr + 1):
					new_block = blockchain[i]
					tuple_to_share = (i, new_block)
					tuple_to_share = pickle.dumps(tuple_to_share)
					peers_socks_vers_out_lock.acquire()

					try:
						for sock_ver in peers_socks_vers_out[:]:
							if new_block != blockchain[i]:
								break
							sock_ver[0].sendall(b'take_new_block')
							reply = sock_ver[0].recv(1024) 
							if reply != b'take_new_block':
								print ("{}: Couldn't forward the new block {} to {}. It hasn't echoed \"take_new_block\"!".format(datetime.now().time(), i, sock_ver[1][2]))
							else:
								sock_ver[0].sendall(tuple_to_share)
								print("{}: Sent block {} with hash {} to {}".format(datetime.now().time(), i, new_block.get_hash_hex(), sock_ver[1][2]))
					except:
						print("{}: Something went wrong when trying to forward the new block {} to a peer!".format(datetime.now().time(), i))

					peers_socks_vers_out_lock.release()
				current_highest_block_nr = new_highest_block_nr
			
			elif new_highest_block_nr == current_highest_block_nr and replaced_block.get_hash_hex() != parent_block.get_hash_hex() and current_highest_block_nr > 0:
				# print("{}: new_highest_block_nr: {}, current_highest_block_nr: {} (must be equal!)".format(datetime.now().time(), new_highest_block_nr,current_highest_block_nr))
				tuple_to_share = (current_highest_block_nr, replaced_block)
				tuple_to_share = pickle.dumps(tuple_to_share)
				peers_socks_vers_out_lock.acquire()
				for sock_ver in peers_socks_vers_out[:]:
					try:
						sock_ver[0].sendall(b'take_new_block')
						reply = sock_ver[0].recv(1024)
						if reply != b'take_new_block':
							print("{}: Couldn't forward the new block {} to {}. It hasn't echoed \"take_new_block\"!".format(datetime.now().time(), i, sock_ver[1][2]))
						else:
							sock_ver[0].sendall(tuple_to_share)
							print("{}: Sent the replaced block {} with hash {} to {}".format(datetime.now().time(), current_highest_block_nr, replaced_block.get_hash_hex(), sock_ver[1][2]))
							# print("{}: parent_block hash: {}\nreplaced_block hash: {}".format(datetime.now().time(), parent_block.get_hash_hex(), replaced_block.get_hash_hex()))
					except socket.timeout:
						pass
				peers_socks_vers_out_lock.release()
				
				#deep copy??
				parent_block = copy.deepcopy(replaced_block)
	except Exception as e:
		print("{}: {}".format(datetime.now().time(), e))
	finally:
		try:
			blockchain_lock.release()
		except:
			pass
		try:
			peers_socks_vers_out_lock.release()
		except:
			pass


def find_sock_out(port_nr):
	s = None
	# print("peers_socks_vers_out right inside find_sock_out")
	# for sock_ver in peers_socks_vers_out[:]:
	# 	print(sock_ver[1][2], port_nr)
	# if len(peers_socks_vers_out) == 0:
	# 	print("peers_socks_vers_out is empty")
	for sock_ver in peers_socks_vers_out:
		if sock_ver[1][2] == port_nr:
			s = sock_ver[0]
	return s

parser = argparse.ArgumentParser()
parser.add_argument("my_port_nr", type=int, 
						help="the desired listening port number (1024-65535) for your node")
parser.add_argument("-f", "--friend_port_nr", type=int, 
						help="the optional port of a known trusted peer to be connected to")
args = parser.parse_args()
my_port_nr = args.my_port_nr
if my_port_nr < 1024 or my_port_nr > 65535: #check the same for the friend's port?
	raise Exception("The specified my_port_nr is out of range!")

#become a full-fledged node
threading.Thread(target = become_a_server, args = [my_port_nr]).start()

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

try:
	if go_for_the_seed == 1:
		if my_port_nr != SEED_NODE_PORT:
			if find_sock_out(first_peer_port_nr) is None:
				peers_socks_vers_out_lock.acquire()
				connection_result = connect_to_a_peer(first_peer_port_nr)
				if type(connection_result) is tuple:
					peers_socks_vers_out.append(connection_result)
				peers_socks_vers_out_lock.release()
				
				if type(connection_result) is tuple:
					print("{}: Appended port {} from main".format(datetime.now().time(), first_peer_port_nr))
					s = connection_result[0]
					peers_ports = get_peer_ports(s)
					connect_to_more_peers(peers_ports)
					remember_peers()

				elif type(connection_result) is list:
					peers_ports = connection_result
					connect_to_more_peers(peers_ports)
					if len(peers_socks_vers_out) == 0:
						raise Exception("Couldn't connect to no peers: nobody is free!") #should never get here
				else:
					print("{}: Connection to first_peer_port_nr has failed!".format(datetime.now().time())) #redundant?
					raise Exception("Connection to first_peer_port_nr has failed!")
			else:
				s = find_sock_out(first_peer_port_nr)
				if s == None:
					raise Exception("s == None!")
				peers_ports = get_peer_ports(s)
				connect_to_more_peers(peers_ports)
				remember_peers()
except Exception as e:
	print(e)
finally:
	try:
		peers_socks_vers_out_lock.release()
	except:
		pass



threading.Thread(target = monitor_the_peer_connections).start()
threading.Thread(target = maximize_active_peers).start()
# threading.Thread(target = print_active_peers_ports).start()

while len(peers_socks_vers_out) == 0:
	pass
threading.Thread(target = notify_peers_about_new_blocks).start()
threading.Thread(target = miner.mine_for_life, args = [blockchain, blockchain_lock, pub_key_compressed, STATE_CATCHING_UP, peers_socks_vers_out]).start()
# threading.Thread(target = print_blockchain_state).start()


'''
#Shutdown and close all sockets
for i in peers_socks_vers_in:
	shutdown_and_close(i[0])
for i in peers_socks_vers_out:
	shutdown_and_close(i[0])
'''