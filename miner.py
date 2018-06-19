import tx

import hashlib
import time
import pickle

POW_TARGET = 2 ** 244 #the nonces produced by the miners MUST be different!
SEC_WAIT_FOR_BLK_PROPAG = 3

mempool = []
blockchain = [] #always to be accessed/modified using the blockchain_lock
with open('genesis_block', 'rb') as f:
	genesis_block = pickle.load(f)
	blockchain.append(genesis_block)

def is_block_valid(block, parent_block):
	if type(block) != type(blockchain[0]):
		print("The type of the received block is invalid!")
		return False

	parent_block_hash = parent_block.get_hash_hex()
	if block.block_header.prev_block_hash != parent_block_hash:
		print("The parent hash {} of the received block with hash {} is different from {}!".format(block.block_header.prev_block_hash, block.get_hash_hex(), parent_block_hash))
		return False

	candidate = tx.Candidate_Block(block.transactions)
	tx_merkle_root = candidate.get_merkle_root()
	if block.block_header.merkle_root != tx_merkle_root:
		print("The merkle root of the txs in the received block and its header are different!")
		return False

	if block.block_header.pow_target < POW_TARGET:
		print("The pow_target specified in the header of the received block is less than POW_TARGET!")
		return False
	
	header_hash = block.get_hash_hex()
	if int(header_hash, 16) >= POW_TARGET:
		print("The actual header_hash of the received block is bigger than POW_TARGET!")
		return False

	return True


def mine_for_life(blockchain, blockchain_lock, miners_pubkey_compressed, STATE_CATCHING_UP, peers_socks_vers_out): #can the lock really be passed like this?
	print("STATE_CATCHING_UP: ", STATE_CATCHING_UP)

	def wait_long_enough(blockchain):
		#let the newly-added block propagate through the network
		parent_block = blockchain[-1]
		block_to_be_mined_nr = len(blockchain)
		initial_time = time.time()

		old_nr_of_peers = len(peers_socks_vers_out)

		while True:
			current_time = time.time()

			socks_vers_out_length = len(peers_socks_vers_out)
			if socks_vers_out_length > old_nr_of_peers:
				old_nr_of_peers = socks_vers_out_length
				print("New connection spotted while inside wait_long_enough. I've paused to let the connection go through")
				initial_time = current_time

			chain_height = len(blockchain)
			if chain_height > block_to_be_mined_nr:
				block_to_be_mined_nr = chain_height
				print("\nWhile inside wait_long_enough, the block {} has been mined by someone!\n".format(block_to_be_mined_nr))
				initial_time = current_time
			else:
				new_latest_block = blockchain[-1]
				if new_latest_block != parent_block:
					old_parent_block = parent_block
					parent_block = new_latest_block
					if chain_height == block_to_be_mined_nr:
						print("\nWhile inside wait_long_enough, the parent block with hash {} has been replaced by the block with hash {}!\n".format(old_parent_block.get_hash_hex(), blockchain[-1].get_hash_hex()))
						initial_time = current_time
					else:
						block_to_be_mined_nr = chain_height
						print("\nWhile inside wait_long_enough, a new block has been added to the blockchain\n")
						initial_time = current_time

			if current_time - initial_time > SEC_WAIT_FOR_BLK_PROPAG:
				return



	def mine_next_block():
		#create header
		current_time = time.time()
		current_time = bytes(str(int(current_time)).encode("UTF-8"))
		blockchain_lock.acquire()
		block_to_be_mined_nr = len(blockchain)
		blockchain_lock.release()
		parent_block = blockchain[block_to_be_mined_nr - 1]
		parent_block_hash = parent_block.get_hash_hex()
		header = tx.Block_Header(parent_block_hash, merkle_root, current_time, POW_TARGET)

		old_nr_of_peers = len(peers_socks_vers_out)

		# print("Started mining block {}".format(block_to_be_mined_nr))

		for nonce in range(max_nonce):
			socks_vers_out_length = len(peers_socks_vers_out)
			if socks_vers_out_length > old_nr_of_peers:
				print("New connection spotted while mining. I've paused to let the connection go through")
				wait_long_enough(blockchain)

			if STATE_CATCHING_UP == True:
				# print("\nSTATE_CATCHING_UP == True\n")
				return nonce
			else:
				chain_height = len(blockchain)
				if chain_height > block_to_be_mined_nr:
					print("The block {} has already been mined by someone. I've tried {} times/hashes!".format(block_to_be_mined_nr, nonce))
					wait_long_enough(blockchain)
					return nonce

				else:
					new_latest_block = blockchain[-1]
					if new_latest_block != parent_block:
						if chain_height == block_to_be_mined_nr:
							print("The parent block with hash {} has been replaced by the block with hash {}! Gotta start mining the new block from zero".format(parent_block.get_hash_hex(), blockchain[-1].get_hash_hex()))
						else:
							print("A new block has been added to the blockchain")
						wait_long_enough(blockchain)
						return nonce

				header_plus_nonce = header.header + bytes(nonce)
				header_hash = hashlib.sha256(header_plus_nonce).hexdigest() #or, maybe, do double-hash?
				if int(header_hash, 16) < header.pow_target:

					# if blockchain[-1] != parent_block:
					# 	print("Right after I've mined the new block, the parent block with hash {} has been replaced by the block with hash {}! Gotta start mining the new block from zero".format(parent_block.get_hash_hex(), blockchain[-1].get_hash_hex()))
					# 	return nonce

					header.nonce = nonce
					mined_block = tx.Block(header, candidate.transactions)

					blockchain_lock.acquire()
					
					if len(blockchain) > block_to_be_mined_nr:
						blockchain_lock.release()
						print("The block {} has been mined by someone right after I've mined it myself after {} times/hashes!".format(block_to_be_mined_nr, nonce))
						wait_long_enough(blockchain)
						return nonce
					
					blockchain.insert(block_to_be_mined_nr, mined_block)
					blockchain_lock.release()
					print("Inserted the block {} mined by me into the blockchain".format(block_to_be_mined_nr))

					print("Success with nonce: ", nonce)
					print("Hash is %s" % header_hash)
					wait_long_enough(blockchain)
					return (header, nonce)

		print("Failed after %d (max_nonce) tries" % nonce)
		return nonce

	max_nonce = 2 ** 32  # 4 billion

	#create Coinbase tx
	coinbase_input = tx.Input("coinbase")
	coinbase_output = tx.Output(50, miners_pubkey_compressed)
	coinbase_tx = tx.Transaction([coinbase_input],[coinbase_output])

	candidate = tx.Candidate_Block([coinbase_tx])
	merkle_root = candidate.get_merkle_root()
	
	while True:
		mine_next_block()
