import hashlib
import pickle
import copy

class Candidate_Block():
	def __init__(self, transactions):
		self.transactions = copy.deepcopy(transactions)

	def get_merkle_root(self):
		merkle_tree = []
		for tx in self.transactions:
			tx_hash = hashlib.sha256(hashlib.sha256(tx.get_bytes()).digest()).digest()
			merkle_tree.append(tx_hash)

		if len(merkle_tree) % 2 == 1:
			merkle_tree.append(merkle_tree[-1])

		while len(merkle_tree) > 1:
			merkle_tree_new = []

			for tx_hash_nr in range(0, len(merkle_tree)-1, 2):
				pair = merkle_tree[tx_hash_nr] + merkle_tree[tx_hash_nr+1]
				pair_hash = hashlib.sha256(hashlib.sha256(pair).digest()).digest()
				merkle_tree_new.append(pair_hash)
			
			merkle_tree = merkle_tree_new

		return merkle_tree[0]

class Block_Header():
	#prev_block_hash, merkle_root - strings; timestamp, pow_target - integers
	def __init__(self, prev_block_hash, merkle_root, timestamp, pow_target):
		self.prev_block_hash = prev_block_hash
		self.merkle_root = merkle_root
		self.timestamp = timestamp
		self.pow_target = pow_target
		self.nonce = 0
		self.header = bytes(self.prev_block_hash, 'UTF-8') + self.merkle_root + self.timestamp + \
						bytes(str(self.pow_target), 'UTF-8')

	def proof_of_work(self):
		max_nonce = 2 ** 32  # 4 billion

		for nonce in range(max_nonce):
			header_plus_nonce = self.header + bytes(nonce)
			header_hash = hashlib.sha256(header_plus_nonce).hexdigest() #or, maybe, do double-hash?
			if int(header_hash, 16) < self.pow_target:
				self.nonce = nonce
				print("{}: Success with nonce: ".format(datetime.now().time(), nonce))
				print("Hash is %s" % header_hash)
				return (header_hash, nonce)

		print("Failed after %d (max_nonce) tries" % max_nonce)
		return max_nonce



class Block():
	def __init__(self, block_header, transactions):
		self.block_header = block_header
		self.transactions = transactions

	def get_hash_hex(self):
		header_plus_nonce = self.block_header.header + bytes(self.block_header.nonce)
		header_hash = hashlib.sha256(header_plus_nonce).hexdigest()
		return header_hash


class Transaction():
	def __init__(self, inputs, outputs):
		self.inputs_outputs = (inputs, outputs)

	def get_bytes(self):
		return pickle.dumps(self)


class Input():
	def __init__(self, coinbase, tx_hash = None, output_index = None, unlocking_script = None):
		if coinbase == "coinbase":
			self.input = ["coinbase"]
		else:
			self.input = [tx_hash, output_index, unlocking_script]

	def get_input(self):
		return self.input


class Output():
	def __init__(self, amount, locking_script):
		self.output = (amount, locking_script)

	def get_output(self):
		return self.output