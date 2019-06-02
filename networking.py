import key_gen
import miner

import argparse
from datetime import datetime
from random import shuffle, sample
import os.path
import pickle
import socket as Socket
import sys
from threading import Thread
from threading import Lock
import time as Time


SEED_NODE_PORT = 1500
STATE_CATCHING_UP = False 	#transform it into a lock! (implies a lock and a publicly-accessible state for checking)

MAX_NR_OF_CONN_OUT = 2
MAX_NR_OF_CONN_IN = 4
# MAX_NR_OF_CONN = MAX_NR_OF_CONN_IN + MAX_NR_OF_CONN_OUT

max_peers_lock = Lock() #the lock used to NOT accept more peers than I should
active_peers_ports = []

peers_socks_vers_out_lock = Lock() #must be used to avoid sending different requests to the same peers at the same time
peers_socks_vers_out = [] #the sockets in which I'm always the first one to write

blockchain_lock = Lock()
blockchain = [] #always to be modified after acquiring the blockchain_lock

priv_key = key_gen.generate_a_private_key()
pub_key_compressed = key_gen.compress_the_public_key_point(key_gen.generate_the_public_key_point(priv_key))


def time():
	return datetime.now().time()

def talk_to_a_client(conn, addr):
	addr_you = None
	data = conn.recv(1024)
	try:
		if data != b'version_msg':
			raise Exception("not a valid first command!")
		max_peers_lock.acquire()
		if len(active_peers_ports) >= MAX_NR_OF_CONN_IN:
			print("{}: {}, I'm full. Try connecting to my peers".format(time(), addr))
			pickled_peers = pickle.dumps(active_peers_ports)
			conn.sendall(pickled_peers)
			raise Exception("Couldn't accept a new peer, cause I've got too many connections")

		conn.sendall(data)
		peers_version_msg = conn.recv(1024)
		conn.sendall(peers_version_msg)
		current_time_you, addr_me, addr_you, your_top_block = pickle.loads(peers_version_msg)

		if addr_me != my_port_nr:
			conn.sendall(bytes((str(current_time_you) + 'rejected').encode('UTF-8')))
			raise Exception("current_time_you rejected")
			
		my_reply = bytes((str(current_time_you) + 'accepted').encode('UTF-8'))
		conn.sendall(my_reply)
		if conn.recv(len(my_reply)) != my_reply:
			print("{}: conn.recv(len(my_reply)) != my_reply!".format(time()))
			raise Exception("conn.recv(len(my_reply)) != my_reply")

		my_version_msg = (Time.time(), addr_you, my_port_nr, len(blockchain)-1)
		my_version_msg_dumped = pickle.dumps(my_version_msg)
		conn.sendall(my_version_msg_dumped)
		if conn.recv(len(my_version_msg_dumped)) != my_version_msg_dumped:
			raise Exception("conn.recv(len(my_version_msg_dumped)) != my_version_msg_dumped")

		anticipated_ver_ack = bytes((str(my_version_msg[0]) + 'accepted').encode('UTF-8'))
		ver_ack = conn.recv(len(anticipated_ver_ack))
		conn.sendall(ver_ack)
		if ver_ack != anticipated_ver_ack:
			raise Exception("ver_ack != anticipated_ver_ack")
							
		if addr_you not in active_peers_ports: #are the above actions useless if addr_you is known?
			active_peers_ports.append(addr_you)
			remember_peers()
		print("{}: Connected by {}".format(time(), addr_you))


		#connect to the new peer in return
		connection_result = None
		peers_socks_vers_out_lock.acquire()
		if find_socket_to(addr_you) is None:
			connection_result = connect_to_a_peer(addr_you)
			
			if type(connection_result) is not tuple:
				print("{}: {}".format(time(), connection_result))
				peers_socks_vers_out_lock.release()
				raise Exception("Couldn't connect in return to {}: the peer is full!".format(addr_you))

			peers_socks_vers_out.append(connection_result)
			print("{}: Connected to {}".format(time(), addr_you))
				
		peers_socks_vers_out_lock.release()
		max_peers_lock.release()

	except Exception as e:
		print("{}: {}".format(time(), e))
		conn.shutdown(Socket.SHUT_RDWR)
		conn.close()
		if max_peers_lock.locked():
			max_peers_lock.release()
		if peers_socks_vers_out_lock.locked():
			peers_socks_vers_out_lock.release()
		return

	while True:
		data = conn.recv(1024)
		if not data: break

		if data == b'still alive':
			conn.sendall(data) #just echo to show that I'm alive

		elif data == b'get_peer_ports':
			conn.sendall(pickle.dumps(active_peers_ports))

		elif data == b"reveal_your_top_block":
			conn.sendall(pickle.dumps(len(blockchain)-1))
		
		elif data == b"get_block":
			conn.sendall(data)
			wanted_block = pickle.loads(conn.recv(1024))
			if wanted_block >= 0 and wanted_block < len(blockchain):
				conn.sendall(pickle.dumps(blockchain[wanted_block]))
		
		elif data == b'take_new_block':
			if STATE_CATCHING_UP is False:
				conn.sendall(data)
				block_id, block = pickle.loads(conn.recv(1024))
				print("{}: Received block {} ({})".format(time(), block_id, block.get_hash_hex()))
				Thread(target = react_to_take_new_block, args = [block_id, block]).start()
			else:
				conn.sendall(b"Can't accept any new blocks while catching up!")
		
		else:
			print("{}: \n \"{}\" is not a valid command!\n".format(time(), data))
	
	shutdown_and_close(conn)

		
def react_to_take_new_block(new_block_id, new_block):
	blockchain_lock.acquire()
	len_blockchain = len(blockchain)
	if new_block_id == len_blockchain:
		#accept the direct child of the highest block
		parent_block = blockchain[len_blockchain-1]
		if miner.is_block_valid(new_block, parent_block):
			blockchain.append(new_block)
			print("{}: Appended the received block {}  with hash {} to the blockchain"\
				.format(time(), new_block_id, new_block.get_hash_hex()))
		else:
			print("{}: the new block {} is invalid".format(time(), new_block_id))

	elif new_block_id > 0 and new_block_id == len_blockchain - 1:
		#accept new block with the same height as the highest one
		parent_block = blockchain[new_block_id-1]
		highest_block = blockchain[new_block_id]
		if miner.is_block_valid(new_block, parent_block):
			new_block_hash = new_block.get_hash_hex()
			highest_block_hash = highest_block.get_hash_hex()

			# accept only if it has a bigger Proof Of Work:
			new_block_nonce = new_block.get_nonce()
			highest_block_nonce = highest_block.get_nonce()
			if new_block_nonce > highest_block_nonce:
				blockchain[new_block_id] = new_block
				#help propagate the replaced block
				print("{}: Replaced the latest block {} ({}) with a new one that's been \
					more difficult to mine ({})"\
					.format(time(), new_block_id, highest_block_hash, new_block_hash))
			
			elif new_block_nonce == highest_block_nonce:
				if int(new_block_hash, 16) < int(highest_block_hash, 16):
					blockchain[new_block_id] = new_block
					#help propagate the replaced block
					print("{}: Replaced the latest block {} with hash {} with a new one (hash: {}) \
						with the same nonce, but smaller (int-wise) hash"\
						.format(time(), new_block_id, highest_block_hash, new_block_hash))
	else:
		print("{}: The new block {} isn't the direct child or a sibling of block {}"\
			.format(time(), new_block_id, len_blockchain-1))
	
	blockchain_lock.release()


def connect_to_a_peer(peers_port): #peers_socks_vers_out_lock must be acquired when calling this method
	print("{}: Connecting to {}".format(time(), peers_port))
	try:
		s = Socket.socket(Socket.AF_INET, Socket.SOCK_STREAM)
		s.connect(('', peers_port))
		
		version_msg = b'version_msg'
		s.sendall(version_msg)

		data = s.recv(1024) #reading more than len(version_msg) to receive a list of peers if the peer is full 
		if data != version_msg:
			peers_ports = pickle.loads(data)
			if type(peers_ports) is list:
				#the peer is full. return all of his neighbours
				return peers_ports
			else:
				raise Exception("Smth strange received in response to my version_msg!")

		my_version_msg_dumped = pickle.dumps((Time.time(), peers_port, my_port_nr, len(blockchain) - 1))
		s.sendall(my_version_msg_dumped)
		if s.recv(len(my_version_msg_dumped)) != my_version_msg_dumped:
			raise Exception("The echo to my_version_msg_dumped is invalid!")

		my_version_msg = pickle.loads(my_version_msg_dumped)
		anticipated_reply = bytes((str(my_version_msg[0]) + 'accepted').encode('UTF-8'))
		
		peers_verdict = s.recv(len(anticipated_reply))
		s.sendall(peers_verdict)
		if peers_verdict != anticipated_reply:
			raise Exception("{} hasn't accepted me!".format(peers_port))

		peers_version_msg = s.recv(1024)
		s.sendall(peers_version_msg)
		current_time_you, addr_me, addr_you, your_top_block = pickle.loads(peers_version_msg)
		
		time_accepted_msg = bytes((str(current_time_you) + 'accepted').encode('UTF-8'))
		if addr_me == my_port_nr and addr_you == peers_port:
			s.sendall(time_accepted_msg)
		else:
			s.sendall(bytes((str(current_time_you) + 'rejected').encode('UTF-8')))
			raise Exception("I've rejected the peers_version_msg from {}".format(peers_port))

		data = s.recv(len(time_accepted_msg))
		if data != time_accepted_msg:
			print("{}: {}  !=  {}".format(time(), data, time_accepted_msg))
			raise Exception("The echo to time_accepted_msg after accepting {} is invalid".format(peers_port))

		if addr_you not in active_peers_ports: #are the above actions useless if addr_you is known?
			active_peers_ports.append(addr_you)
			remember_peers()


		#sync our blockchains:
		my_top_block = len(blockchain) - 1
		global STATE_CATCHING_UP
		
		#can't your_top_block become outdated till now?
		if your_top_block > my_top_block and STATE_CATCHING_UP is False:
			print("{}: {} has more blocks than me".format(time(), addr_you))
			STATE_CATCHING_UP = True

			blockchain_lock.acquire()

			your_top_block = ask_for_peers_top_block(s, addr_you)
			my_top_block = len(blockchain) - 1
			
			while your_top_block > my_top_block:
				difference = your_top_block - my_top_block
				print("{}: your_top_block({}) - my_top_block({}) = {}"\
					.format(time(), your_top_block, my_top_block, difference))
				
				get_block_msg = b"get_block"

				for i in range(1, difference + 1):
					s.sendall(get_block_msg)
					
					if s.recv(len(get_block_msg)) != get_block_msg:
						print("{}: The echo to get_block_msg is invalid".format(time()))
						STATE_CATCHING_UP = False
						break

					wanted_block = my_top_block + i
					s.sendall(pickle.dumps(wanted_block))
					print("{}: Asked {} to send me block {}".format(time(), addr_you, wanted_block))
					
					block_received = pickle.loads(s.recv(1024))
					
					if miner.is_block_valid(block_received, blockchain[wanted_block - 1]) is False:
						STATE_CATCHING_UP = False
						break

					if len(blockchain)-1 == wanted_block: #can this ever be True with the BC_lock held?
						print("{}: The block {} is already present!".format(time(), wanted_block))
					else:
						blockchain.insert(wanted_block, block_received)
						print("{}: Added block {} to the blockchain!".format(time(), wanted_block))
				
				if STATE_CATCHING_UP is True:
					your_top_block = ask_for_peers_top_block(s, addr_you)
					my_top_block = len(blockchain)-1
				else:
					blockchain_lock.release()
					your_top_block = 0 #in order to break the outer while loop
			
			if blockchain_lock.locked():
				blockchain_lock.release()
			
			STATE_CATCHING_UP = False

		# remember_peers()
		return (s, pickle.loads(peers_version_msg))
			
	except Exception as e:
		print("{}: Couldn't connect to {}: {}.".format(time(), peers_port, e))
	finally:
		if blockchain_lock.locked():
			blockchain_lock.release()

def ask_for_peers_top_block(socket, peers_addr):
	socket.sendall(b"reveal_your_top_block")
	print("{}: Asked {} to tell me his top block".format(time(), peers_addr))	
	peers_top_block = pickle.loads(socket.recv(1024))

	return peers_top_block

def connect_to_more_peers(peers_ports):
	#connect to as many peers as possible, starting with peers_ports
	potential_peers = peers_ports
	peers_already_tried = []
	
	while len(peers_socks_vers_out) < MAX_NR_OF_CONN_OUT and len(potential_peers) > 0:
		port_nr = potential_peers[0]

		peers_socks_vers_out_lock.acquire()
		if find_socket_to(port_nr) is None and port_nr != my_port_nr:
			connection_result = connect_to_a_peer(port_nr)
			
			if type(connection_result) is tuple:
				peers_socks_vers_out.append(connection_result)
				print("{}: Connected to {}".format(time(), port_nr))

			elif type(connection_result) is list:
				for peer in connection_result:
					if peer not in peers_already_tried and peer not in potential_peers and peer != my_port_nr:
						potential_peers.append(peer)
			else:
				print("{}: While \"connecting to more peers\", couldn't connect to {}: something went wrong!"\
					.format(time(), port_nr))
		peers_socks_vers_out_lock.release()
		
		peers_already_tried.append(port_nr)
		potential_peers.remove(port_nr)


def get_peer_ports(socket_to_the_peer):
	#returns the randomized list of the peer's ports
	peers_socks_vers_out_lock.acquire()
	socket_to_the_peer.sendall(b'get_peer_ports')
	peers_ports = pickle.loads(socket_to_the_peer.recv(1024))
	peers_socks_vers_out_lock.release()

	shuffle(peers_ports)
	return peers_ports


def become_a_server(my_port_nr):
	s = Socket.socket(Socket.AF_INET, Socket.SOCK_STREAM)
	s.setsockopt(Socket.SOL_SOCKET, Socket.SO_REUSEADDR, 1) #does it really make any difference?
	s.bind(('', my_port_nr))
	s.listen()
	while True:
		conn, addr = s.accept()
		print("{}: Accepted a client.".format(time()))
		Thread(target = talk_to_a_client, args = (conn,addr)).start()


def remember_peers(): #must be accompanied by a lock
	file_name = "recent_successful_connections" + str(my_port_nr)
	with open(file_name, "w") as f:
		for port in active_peers_ports:
			f.write(str(port) + '\n')


class PeerNotAliveException(Exception):
	pass

def monitor_the_peer_connections():
	failed_still_alives = dict()
	still_alive_msg = b'still alive'

	def check_whether_alive():
		Time.sleep(2)
		
		for sock_ver in peers_socks_vers_out[:]: #[:] refers to a shallow copy
			socket = sock_ver[0]
			peers_port = sock_ver[1][2]
			
			peers_socks_vers_out_lock.acquire()
			socket.settimeout(1)
			try:
				socket.sendall(still_alive_msg)
				reply = socket.recv(len(still_alive_msg))
				if reply != still_alive_msg:
					print("{}: +1 missed 'still alive' for {}".format(time(), peers_port))
					raise PeerNotAliveException()
				else:
					#the peer is still alive - reset his counter
					failed_still_alives[peers_port] = 0

			except (IOError, PeerNotAliveException, Socket.timeout):
				if peers_port in failed_still_alives:
					failed_still_alives[peers_port] += 1
					if failed_still_alives[peers_port] > 5:
						print ("\n{}: {} is being forgotten!\n".format(time(), peers_port))
						forget_a_peer(sock_ver)
				else:
					failed_still_alives[peers_port] = 1
			
			finally:
				socket.settimeout(None)
				if peers_socks_vers_out_lock.locked():
					peers_socks_vers_out_lock.release()
	while True:
		check_whether_alive()


def shutdown_and_close(socket):
	try:
		socket.shutdown(Socket.SHUT_RDWR)
	except Socket.error as e:
		print("{}: {}".format(time(), e))
	socket.close()


def forget_a_peer(sock_ver): #peers_socks_vers_out_lock must be acquired when entering here
	shutdown_and_close(sock_ver[0])
	active_peers_ports.remove(sock_ver[1][2])
	peers_socks_vers_out.remove(sock_ver)
	remember_peers()


def maximize_active_peers():
	#makes sure that at any given time, you're connected to as many active peers as possible
	while len(active_peers_ports) == 0:
		Time.sleep(1)
	
	peers_number = len(active_peers_ports)
	latest_maximization = Time.time()
	
	try:
		while True:
			Time.sleep(1)
			nr_outer_conns = len(peers_socks_vers_out)
			if nr_outer_conns < MAX_NR_OF_CONN_OUT and STATE_CATCHING_UP == False:
				curr_peers_number = len(active_peers_ports)
				if (Time.time()-latest_maximization > 5) or curr_peers_number != peers_number:
					latest_maximization = Time.time()
					peers_number = curr_peers_number
					
					for i in sample(range(nr_outer_conns), nr_outer_conns):
						socket = peers_socks_vers_out[i][0]
						connect_to_more_peers(get_peer_ports(socket))
	
	except Exception as e:
		print("\n{}: Stopped maximizing the number of active peers!\nCause: {}".format(time(), e))


def print_blockchain_state():
	#whenever the blockchain grows, shrinks or has its highest block changed, its state is printed
	bc_len = len(blockchain)
	highest_block_hash = blockchain[bc_len-1]
	while True:
		new_bc_len = len(blockchain)
		new_highest_block_hash = blockchain[new_bc_len-1].get_hash_hex()
		if new_bc_len != bc_len or highest_block_hash != new_highest_block_hash:
			print("{}: Blockchain contents (excluding the Genesis block):".format(time()))
			for i in range(1, len(blockchain)):
				print("{}: Block {} hash: {}".format(time(), i, blockchain[i].get_hash_hex()))
			bc_len = new_bc_len
		Time.sleep(1)


def notify_peers_about_new_blocks():
	try:
		highest_block = len(blockchain)
		highest_block_hash = blockchain[highest_block-1].get_hash_hex()
		take_new_block_msg = b'take_new_block'

		while True:
			blockchain_len = len(blockchain)
			new_highest_block_hash = blockchain[blockchain_len-1].get_hash_hex()

			blocks_to_broadcast = []
			if blockchain_len > highest_block:
				blocks_to_broadcast = list(range(highest_block, blockchain_len))
				highest_block = blockchain_len
			elif blockchain_len == highest_block and new_highest_block_hash != highest_block_hash:
				blocks_to_broadcast.append(blockchain_len - 1)
			highest_block_hash = new_highest_block_hash

			for block_nr in blocks_to_broadcast:
				block = blockchain[block_nr]
				block_tuple_pickled = pickle.dumps((block_nr, block))

				peers_socks_vers_out_lock.acquire()
				if block.get_hash_hex() != blockchain[block_nr].get_hash_hex():
					peers_socks_vers_out_lock.release()
					break #the block has been replaced in the blockchain; would be wrong to broadcast it

				for sock_ver in peers_socks_vers_out:
					try:
						socket = sock_ver[0]
						peer = sock_ver[1][2]

						socket.sendall(take_new_block_msg)
						if socket.recv(len(take_new_block_msg)) != take_new_block_msg:
							print ("{}: Couldn't forward the new block {} to {}. It hasn't echoed \
								\"take_new_block\"!".format(time(), block_nr, peer))
							continue

						socket.sendall(block_tuple_pickled)
						print("{}: Sent block {} with hash {} to {}".format(time(), block_nr, \
							block.get_hash_hex(), peer))
					except Exception as e:
						print("{}: Something went wrong when trying to forward a block {} to a peer: {}"\
							.format(time(), block_nr, e))		

				peers_socks_vers_out_lock.release()
			Time.sleep(1) #brought massive improvement!

	except Exception as e:
		print("\n{}: Stopped notifying peers about new blocks!\nCause: {}".format(time(), e))
		# print('Error on line {}'.format(sys.exc_info()[-1].tb_lineno), type(e).__name__, e)
	
	finally:
		if peers_socks_vers_out_lock.locked():
			peers_socks_vers_out_lock.release()


def find_socket_to(port_nr):
	socket = None
	for sock_ver in peers_socks_vers_out:
		if sock_ver[1][2] == port_nr:
			socket = sock_ver[0]
			break
	return socket

def add_genesis_block():
	with open('genesis_block', 'rb') as f:
		genesis_block = pickle.load(f)
		blockchain.append(genesis_block)

add_genesis_block()

parser = argparse.ArgumentParser()
parser.add_argument("my_port_nr", type=int, 
						help="the desired listening port number (1024-65535) for your node")
parser.add_argument("-f", "--friend_port_nr", type=int, 
						help="an optional port number (1024-65535) of a known trusted peer \
						to be connected to")
args = parser.parse_args()

my_port_nr = args.my_port_nr
if my_port_nr < 1024 or my_port_nr > 65535:
	raise Exception("The specified my_port_nr is out of range!")

first_peer_port_nr = args.friend_port_nr
if first_peer_port_nr and (first_peer_port_nr < 1024 or first_peer_port_nr > 65535):
	raise Exception("The specified friend_port_nr is out of range!")

#become a full-fledged node
Thread(target = become_a_server, args = [my_port_nr]).start()

recent_peers = []
if args.friend_port_nr is None:
	file_name = "recent_successful_connections" + str(my_port_nr)
	if os.path.isfile(file_name):
		with open(file_name,'r') as f:
			for line in f.readlines():
				recent_peers.append(int(line))
		if len(recent_peers) > 0:
			connect_to_more_peers(recent_peers)

	if len(peers_socks_vers_out) is 0:
		first_peer_port_nr = SEED_NODE_PORT

try:
	if first_peer_port_nr != None and \
		(first_peer_port_nr != SEED_NODE_PORT or my_port_nr != SEED_NODE_PORT):

		peers_socks_vers_out_lock.acquire()
		
		connection_result = connect_to_a_peer(first_peer_port_nr)
		if type(connection_result) is tuple:
			peers_socks_vers_out.append(connection_result)
			print("{}: Connected to {} from main".format(time(), first_peer_port_nr))
		peers_socks_vers_out_lock.release()

		if type(connection_result) is tuple:
			socket_to_first_peer = connection_result[0]
			connect_to_more_peers(get_peer_ports(socket_to_first_peer))

		elif type(connection_result) is list:
			connect_to_more_peers(connection_result)
			if len(peers_socks_vers_out) == 0:
				raise Exception("Couldn't connect to no peers: nobody is free!") #should never get here
		else:
			print("{}: List of peers received: {}".format(time(), connection_result))
			raise Exception("Connection to first_peer_port_nr has failed!")
			
except Exception as e:
	print("{}: {}".format(time(), e))
finally:
	if peers_socks_vers_out_lock.locked():
		peers_socks_vers_out_lock.release()


Thread(target = monitor_the_peer_connections).start()
Thread(target = maximize_active_peers).start()

while len(peers_socks_vers_out) is 0:
	Time.sleep(1)

Thread(target = notify_peers_about_new_blocks).start()
Thread(target = miner.mine_for_life, args = [blockchain, blockchain_lock, pub_key_compressed, \
	STATE_CATCHING_UP, peers_socks_vers_out]).start()
# Thread(target = print_blockchain_state).start()

# main()
#Shutdown and close all sockets