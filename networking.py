import key_gen
import miner

import socket
import pickle
from threading import Thread
from threading import Lock
import traceback
import sys
from threading import Lock
import time
from datetime import datetime
import argparse
import os
import os.path
from random import shuffle
import hashlib
import copy


max_peers_lock = Lock() #the lock used to NOT accept more peers than I should

SEED_NODE_PORT = 1500
MAX_ACTIVE_CONNECTIONS_OUT = 2
MAX_ACTIVE_CONNECTIONS_IN = 4
MAX_ACTIVE_CONNECTIONS = MAX_ACTIVE_CONNECTIONS_IN + MAX_ACTIVE_CONNECTIONS_OUT
STATE_CATCHING_UP = False
active_peers_ports = []
peers_socks_vers_out = [] #the sockets in which I'm always the first one to write

#is it really needed?
peers_socks_vers_in = [] #the sockets in which my peers are always the first ones to write

blockchain_lock = Lock()
blockchain = [] #always to be modified after acquiring the blockchain_lock
with open('genesis_block', 'rb') as f:
	genesis_block = pickle.load(f)
	blockchain.append(genesis_block)
# print("{}: Genesis block: {}".format(datetime.now().time(), blockchain[0]))

priv_key = key_gen.generate_a_private_key()
pub_key_compressed = key_gen.compress_the_public_key_point(key_gen.generate_the_public_key_point(priv_key))

peers_socks_vers_out_lock = Lock() #must be used to avoid sending different requests to the same peers at the same time 


class InvalidFirstCommandException(Exception):
	pass
class FullPeerException(Exception):
	pass


def talk_to_a_client(conn, addr):
	addr_you = None
	data = conn.recv(1024)
	try:
		if data != b'version_msg':
			raise InvalidFirstCommandException("not a valid first command!")
		max_peers_lock.acquire()
		if len(active_peers_ports) >= MAX_ACTIVE_CONNECTIONS_IN:
			print("{}: {}, I'm full. Try connecting to my peers".format(datetime.now().time(), addr))
			pickled_peers = pickle.dumps(active_peers_ports)
			conn.sendall(pickled_peers)
			raise Exception("Couldn't accept a new peer, cause I've got too many connections")

		conn.sendall(data)
		peers_version_msg = conn.recv(1024)
		conn.sendall(peers_version_msg)
		current_time_you, addr_me, addr_you, your_highest_block = pickle.loads(peers_version_msg)

		if addr_me != my_port_nr:
			conn.sendall(bytes((str(current_time_you) + 'rejected').encode('UTF-8')))
			raise Exception("current_time_you rejected")
			
		my_reply = bytes((str(current_time_you) + 'accepted').encode('UTF-8'))
		conn.sendall(my_reply)
		tmp = conn.recv(len(my_reply))
		if tmp != my_reply:
			print("{}: conn.recv(1024) != my_reply: {} != {}".format(datetime.now().time(), tmp, my_reply))
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
			print("connecting to the new peer {} in return".format(addr_you))
			connection_result = connect_to_a_peer(addr_you)
			
			if type(connection_result) is not tuple:
				print("{}: {}".format(datetime.now().time(), connection_result))
				peers_socks_vers_out_lock.release()
				raise FullPeerException("Couldn't connect in return to {}: the peer is full!".format(addr_you))

			peers_socks_vers_out.append(connection_result)
			remember_peers()
				
		peers_socks_vers_out_lock.release()
		max_peers_lock.release()
		# print("len(peers_socks_vers_out): ", len(peers_socks_vers_out))

	except InvalidFirstCommandException:
		conn.shutdown(socket.SHUT_RDWR); conn.close()
		return
	except FullPeerException:
		conn.shutdown(socket.SHUT_RDWR); conn.close()
		max_peers_lock.release()
		#remove the in-socket from peers_socks_vers_in, as well??
		return
	except:
		conn.shutdown(socket.SHUT_RDWR); conn.close()
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
			pickled_peers = pickle.dumps(active_peers_ports)
			conn.sendall(pickled_peers)

		elif data == b"reveal_your_highest_block":
			conn.sendall(pickle.dumps(len(blockchain) - 1))
		
		elif data == b"get_block":
			conn.sendall(data)
			wanted_block_nr = conn.recv(1024)
			wanted_block_nr = pickle.loads(wanted_block_nr)
			if wanted_block_nr >= 0 and wanted_block_nr < len(blockchain):
				wanted_block_pickled = pickle.dumps(blockchain[wanted_block_nr])
				conn.sendall(wanted_block_pickled)
		
		elif data == b'take_new_block':
			if STATE_CATCHING_UP is False:
				conn.sendall(data)
				new_block_tuple = conn.recv(1024)
				new_block_id, new_block = pickle.loads(new_block_tuple)
				print("{}: Received block {} with hash {}"\
					.format(datetime.now().time(), new_block_id,new_block.get_hash_hex()))
				Thread(target = react_to_take_new_block, \
					args = [blockchain, blockchain_lock, new_block_id, new_block]).start()
			else:
				conn.sendall(b"I can't accept any new blocks while catching up!")
		
		else:
			print("{}: \n \"{}\" is not a valid command!\n".format(datetime.now().time(), data))
	
	conn.shutdown(socket.SHUT_RDWR); conn.close()

		
def react_to_take_new_block(blockchain, blockchain_lock, new_block_id, new_block):
	blockchain_lock.acquire()
	len_blockchain = len(blockchain)
	if new_block_id == len_blockchain:
		#accept the direct child of the highest block
		parent_block = blockchain[new_block_id-1]
		if miner.is_block_valid(new_block, parent_block):
			blockchain.append(new_block)
			print("{}: Appended the received block {}  with hash {} to the blockchain"\
				.format(datetime.now().time(), new_block_id, new_block.get_hash_hex()))
		else:
			print("{}: the new block {} is invalid".format(datetime.now().time(), new_block_id))

	elif new_block_id > 0 and new_block_id == len_blockchain - 1:
		#accept new block with the same height as the highest one
		parent_block = blockchain[new_block_id-1]
		highest_block = blockchain[new_block_id]
		if new_block.get_parent_hash() == highest_block.get_parent_hash()\
			and miner.is_block_valid(new_block, parent_block):
				new_block_hash = new_block.get_hash_hex()
				highest_block_hash = highest_block.get_hash_hex()

				# accept it only if it has a bigger Proof Of Work:
				new_block_nonce = new_block.get_nonce()
				highest_block_nonce = highest_block.get_nonce()
				if new_block_nonce > highest_block_nonce:
					blockchain[new_block_id] = new_block
					#help propagate the replaced block
					print("{}: Replaced the latest block {} with hash {} with a new one that's been \
						more difficult to mine with the hash {}"\
						.format(datetime.now().time(), new_block_id, highest_block_hash, new_block_hash))
				
				elif new_block_nonce == highest_block_nonce:
					if int(new_block_hash, 16) < int(highest_block_hash, 16):
						blockchain[new_block_id] = new_block
						#help propagate the replaced block
						print("{}: Replaced the latest block {} with hash {} with a new one (hash: {}) \
							with the same nonce, but smaller (int-wise) hash"\
							.format(datetime.now().time(), new_block_id, highest_block_hash, new_block_hash))
	else:
		print("{}: The new block {} isn't the direct child nor a sibling of block {}"\
			.format(datetime.now().time(), new_block_id, len_blockchain-1))
	
	blockchain_lock.release()


def connect_to_a_peer(peers_port):
	print("{}: Trying to connect to {}".format(datetime.now().time(), peers_port))
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.connect(('', peers_port))
		
		s.sendall(b'version_msg')
		data = s.recv(1024)
		if data != b'version_msg':
			peers_ports = pickle.loads(data)
			if type(peers_ports) is list:
				#the peer is full. return all of his neighbours
				return peers_ports
			else:
				raise Exception("Smth strange received in response to my version_msg!")

		my_version_msg_dumped = pickle.dumps((time.time(), peers_port, my_port_nr, len(blockchain) - 1))
		s.sendall(my_version_msg_dumped)
		if s.recv(len(my_version_msg_dumped)) != my_version_msg_dumped:
			raise Exception("What I've received in response isn't identical to my_version_msg_dumped!")

		my_version_msg = pickle.loads(my_version_msg_dumped)
		anticipated_reply = bytes((str(my_version_msg[0]) + 'accepted').encode('UTF-8'))
		peers_verdict = s.recv(len(anticipated_reply))
		s.sendall(peers_verdict)

		if peers_verdict != anticipated_reply:
			raise Exception("{} hasn't accepted me!".format(peers_port))

		peers_version_msg = s.recv(1024)
		s.sendall(peers_version_msg)
		current_time_you, addr_me, addr_you, your_highest_block = pickle.loads(peers_version_msg)
		
		time_accepted_msg = bytes((str(current_time_you) + 'accepted').encode('UTF-8'))
		if addr_me == my_port_nr and addr_you == peers_port:
			s.sendall(time_accepted_msg)
		else:
			s.sendall(bytes((str(current_time_you) + 'rejected').encode('UTF-8')))
			raise Exception("I've rejected the peers_version_msg from {}".format(peers_port))

		peers_echo = s.recv(len(time_accepted_msg))
		if peers_echo != time_accepted_msg:
			print("{}: {}  !=  {}".format(datetime.now().time(), peers_echo, time_accepted_msg))
			raise Exception("The echo-msg after I've accepted {} isn't identical to mine".format(peers_port))

		if addr_you not in active_peers_ports:
			active_peers_ports.append(addr_you)

		print("{}: Connected to {}".format(datetime.now().time(), peers_port))
		# peers_socks_vers_out.append((s, peers_version_msg))

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
						blockchain.insert(wanted_block_nr, block_received) #transform into an append()?
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
			
			if blockchain_lock.locked():
				blockchain_lock.release()
			STATE_CATCHING_UP = False

		peers_version_msg = pickle.loads(peers_version_msg)
		return (s, peers_version_msg)
			
	except Exception as e:
		print("{}: Couldn't connect to {}. Like, at all!".format(datetime.now().time(), peers_port))
		print(e)
		#no problem. will try connecting to someone else
	finally:
		if blockchain_lock.locked():
			blockchain_lock.release()

def connect_to_more_peers(peers_ports):
	#connect to as many peers as possible, starting from peers_ports
	ports_to_be_tried = peers_ports
	ports_already_tried = []
	while len(peers_socks_vers_out) < MAX_ACTIVE_CONNECTIONS_OUT and len(ports_to_be_tried) > 0:
		port_nr = ports_to_be_tried[0]

		peers_socks_vers_out_lock.acquire()
		if find_sock_out(port_nr) is None and port_nr != my_port_nr:
			connection_result = connect_to_a_peer(port_nr)
			if type(connection_result) is tuple:
				peers_socks_vers_out.append(connection_result)
				# print("{}: Appended port {} from inside connect_to_more_peers".format(datetime.now().time(), port_nr))
				remember_peers()
			elif type(connection_result) is list:
				#the peer is full; got his peers_list
				for peer in connection_result:
					if peer not in ports_already_tried and peer not in ports_to_be_tried:
						ports_to_be_tried.append(peer)
			else:
				print("{}: While \"connecting to more peers\", couldn't connect to {}: something went wrong!".format(datetime.now().time(), port_nr))
		peers_socks_vers_out_lock.release()
		
		ports_already_tried.append(port_nr)
		ports_to_be_tried.remove(port_nr)

def get_peer_ports(socket_to_the_peer):
	#returns the randomized list of the peer's ports
	peers_socks_vers_out_lock.acquire()
	socket_to_the_peer.sendall(b'get_peer_ports')
	peers_ports = pickle.loads(socket_to_the_peer.recv(1024))
	peers_socks_vers_out_lock.release()
	return shuffle(peers_ports)

def become_a_server(my_port_nr):
	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) #does it really make any difference?
	s.bind(('', my_port_nr))
	s.listen()
	while True:
		conn, addr = s.accept()
		print("{}: Accepted a client.".format(datetime.now().time()))
		Thread(target = talk_to_a_client, args = (conn,addr)).start()

def remember_peers():
	file_name = "recent_successful_connections" + str(my_port_nr)
	with open(file_name, "w") as f:
		for sock_ver in peers_socks_vers_out:
			f.write(str(sock_ver[1][2]) + '\n')

class PeerNotAliveException(Exception):
	pass

def monitor_the_peer_connections():
	failed_still_alives = dict()

	def check_whether_alive():
		try:
			for sock_ver in peers_socks_vers_out[:]: #[:] refers to a shallow copy
				socket_to_the_peer = sock_ver[0]
				peers_port_nr = sock_ver[1][2]
				still_alive_msg = b'still alive'
				
				peers_socks_vers_out_lock.acquire()
				socket_to_the_peer.settimeout(1)
				socket_to_the_peer.sendall(still_alive_msg)
				try:
					reply = socket_to_the_peer.recv(len(still_alive_msg))
					peers_socks_vers_out_lock.release()
					if reply != still_alive_msg:
						raise PeerNotAliveException("The peer has missed 1 still_alive")
					else:
						 #the peer is still alive - reset its failed_still_alives counter
						 failed_still_alives[peers_port_nr] = 0

				except (PeerNotAliveException, socket.timeout):
					if peers_socks_vers_out_lock.locked():
						peers_socks_vers_out_lock.release()
					if peers_port_nr in failed_still_alives:
						failed_still_alives[peers_port_nr] += 1
						if failed_still_alives[peers_port_nr] > 5:
							print ("\n{}: {} is no longer alive!\n"\
								.format(datetime.now().time(), peers_port_nr))
							shutdown_close_remove(sock_ver)
							remember_peers()
					else:
						failed_still_alives[peers_port_nr] = 1
					# print("{}: +1 missed 'still alive' for {}".format(datetime.now().time(), peers_port_nr))
				
				finally:
					socket_to_the_peer.settimeout(None)

		except Exception as e:
			print("{}: {}".format(datetime.now().time(), e))
		finally:
			if peers_socks_vers_out_lock.locked():
				peers_socks_vers_out_lock.release()

	file_name = "recent_successful_connections" + str(my_port_nr)
	while True:
		check_whether_alive()
		if not os.path.isfile(file_name): #move these if's outside the loop?
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
	peers_socks_vers_out_lock.acquire()
	peers_socks_vers_out.remove(sock_ver)
	peers_socks_vers_out_lock.release()
	
	for tuples in peers_socks_vers_in:
		if sock_ver == tuples[1][2]:
			peers_socks_vers_in.remove(sock_ver)
			break

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
					# previous_active_peers_ports = current_active_peers_ports #shouldn't it be here?
				if len(peers_socks_vers_out) >= MAX_ACTIVE_CONNECTIONS_OUT:
					previous_active_peers_ports = current_active_peers_ports
					print("{}: active_peers_ports: {}".format(datetime.now().time(), active_peers_ports))
		time.sleep(1)

def print_active_peers_ports():
	while True:
		print("{}: active_peers_ports: {}".format(datetime.now().time(), active_peers_ports))
		time.sleep(1)

def print_blockchain_state():
	#whenever the blockchain grows, shrinks or has its highest block change, its state is printed
	current_bc_len = len(blockchain)
	hash_of_highest_block = blockchain[current_bc_len-1]
	while True:
		new_bc_len = len(blockchain)
		hash_of_new_highest_block = blockchain[new_bc_len-1].get_hash_hex()
		if new_bc_len != current_bc_len or hash_of_highest_block != hash_of_new_highest_block:
			print("{}: Now, the blockchain contains {} blocks (excluding the Genesis one):".format(datetime.now().time(), len(blockchain)-1))
			for i in range(1, len(blockchain)):
				print("{}: Block {} hash: {}".format(datetime.now().time(), i, blockchain[i].get_hash_hex()))
			current_bc_len = new_bc_len
		time.sleep(1)


def notify_peers_about_new_blocks():
	try:
		current_highest_block_nr = len(blockchain) - 1
		parent_block = blockchain[current_highest_block_nr]

		while True:
			new_highest_block_nr = len(blockchain) - 1
			replaced_block = blockchain[new_highest_block_nr]

			if new_highest_block_nr > current_highest_block_nr:
				parent_block = blockchain[-1]
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
								print ("{}: Couldn't forward the new block {} to {}. \
									It hasn't echoed \"take_new_block\"!"\
									.format(datetime.now().time(), i, sock_ver[1][2]))
							else:
								sock_ver[0].sendall(tuple_to_share)
								print("{}: Sent block {} with hash {} to {}"\
									.format(datetime.now().time(), i, new_block.get_hash_hex(), sock_ver[1][2]))
					except:
						print("{}: Something went wrong when trying to forward the new block {} to a peer!"\
							.format(datetime.now().time(), i))

					peers_socks_vers_out_lock.release()
				current_highest_block_nr = new_highest_block_nr
			
			elif new_highest_block_nr == current_highest_block_nr \
				and replaced_block.get_hash_hex() != parent_block.get_hash_hex() \
				and current_highest_block_nr > 0:
				# print("{}: new_highest_block_nr: {}, current_highest_block_nr: {} (must be equal!)"\
				# .format(datetime.now().time(), new_highest_block_nr,current_highest_block_nr))
				tuple_to_share = (current_highest_block_nr, replaced_block)
				tuple_to_share = pickle.dumps(tuple_to_share)
				peers_socks_vers_out_lock.acquire()
				for sock_ver in peers_socks_vers_out[:]:
					try:
						sock_ver[0].sendall(b'take_new_block')
						reply = sock_ver[0].recv(1024)
						if reply != b'take_new_block':
							print("{}: Couldn't forward the new block {} to {}. \
								It hasn't echoed \"take_new_block\"!"\
								.format(datetime.now().time(), i, sock_ver[1][2]))
						else:
							sock_ver[0].sendall(tuple_to_share)
							print("{}: Sent the replaced block {} with hash {} to {}"\
								.format(datetime.now().time(), current_highest_block_nr, \
									replaced_block.get_hash_hex(), sock_ver[1][2]))
							# print("{}: parent_block hash: {}\nreplaced_block hash: {}"\
							# .format(datetime.now().time(), parent_block.get_hash_hex(), \
							# replaced_block.get_hash_hex()))
					except socket.timeout:
						pass
				peers_socks_vers_out_lock.release()
				
				#deep copy??
				parent_block = copy.deepcopy(replaced_block)
			time.sleep(1) #brought massive improvement!
	except Exception as e:
		print("{}: {}".format(datetime.now().time(), e))
	finally:
		if blockchain_lock.locked():
			blockchain_lock.release()
		if peers_socks_vers_out_lock.locked():
			peers_socks_vers_out_lock.release()


def find_sock_out(port_nr):
	socket = None
	for sock_ver in peers_socks_vers_out:
		if sock_ver[1][2] == port_nr:
			socket = sock_ver[0]
			break
	return socket


def connect_to_peers_and_remember(socket_to_the_peer):
	peers_ports = get_peer_ports(socket_to_the_peer)
	connect_to_more_peers(peers_ports)
	remember_peers()


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
Thread(target = become_a_server, args = [my_port_nr]).start()

recent_peers = []
first_peer_port_nr = args.friend_port_nr
if args.friend_port_nr == None:
	file_name = "recent_successful_connections" + str(my_port_nr)
	if os.path.isfile(file_name):
		with open(file_name,'r') as f:
			for line in f.readlines():
				recent_peers.append(int(line))
	if len(recent_peers) == 0:
		first_peer_port_nr = SEED_NODE_PORT

go_for_the_seed = 1
if len(recent_peers) != 0:
	connect_to_more_peers(recent_peers)
	if len(peers_socks_vers_out) > 0:
		go_for_the_seed = 0

try:
	if go_for_the_seed == 1 and my_port_nr != SEED_NODE_PORT:
		socket_to_first_peer = find_sock_out(first_peer_port_nr)
		peers_socks_vers_out_lock.acquire()
		if socket_to_first_peer is None:
			connection_result = connect_to_a_peer(first_peer_port_nr)
			if type(connection_result) is tuple:
				peers_socks_vers_out.append(connection_result)
			peers_socks_vers_out_lock.release()

			if type(connection_result) is tuple:
				print("{}: Appended port {} from main".format(datetime.now().time(), first_peer_port_nr))
				socket_to_first_peer = connection_result[0]
				connect_to_peers_and_remember(socket_to_first_peer)

			elif type(connection_result) is list:
				connect_to_more_peers(connection_result)
				if len(peers_socks_vers_out) == 0:
					raise Exception("Couldn't connect to no peers: nobody is free!") #should never get here
			else:
				print("{}: Connection to first_peer_port_nr has failed!".format(datetime.now().time())) #redundant?
				raise Exception("Connection to first_peer_port_nr has failed!")
		else:
			peers_socks_vers_out_lock.release()
			connect_to_peers_and_remember(socket_to_first_peer)
			
except Exception as e:
	print(e)
finally:
	if peers_socks_vers_out_lock.locked():
		peers_socks_vers_out_lock.release()


Thread(target = monitor_the_peer_connections).start()
Thread(target = maximize_active_peers).start()
# Thread(target = print_active_peers_ports).start()

while len(peers_socks_vers_out) == 0:
	time.sleep(1)

Thread(target = notify_peers_about_new_blocks).start()
Thread(target = miner.mine_for_life, args = [blockchain, blockchain_lock, pub_key_compressed, STATE_CATCHING_UP, peers_socks_vers_out]).start()
# Thread(target = print_blockchain_state).start()


'''
#Shutdown and close all sockets
for i in peers_socks_vers_in:
	shutdown_and_close(i[0])
for i in peers_socks_vers_out:
	shutdown_and_close(i[0])
'''