import tx

import pickle
import hashlib
from datetime import datetime
import time
micro_sleep = lambda x: time.sleep(x/1000.0)

POW_TARGET = 2 ** 244 #the nonces produced by the miners MUST be different!
SEC_WAIT_FOR_BLK_PROPAG = 3

mempool = []
blockchain = [] #always to be modified using the blockchain_lock
with open('genesis_block', 'rb') as f:
	genesis_block = pickle.load(f)
	blockchain.append(genesis_block)

def is_block_valid(block, parent_block):
	if type(block) != type(blockchain[0]):
		print("{}: The type of the received block is invalid!".format(datetime.now().time()))
		return False

	parent_block_hash = parent_block.get_hash_hex()
	if block.block_header.prev_block_hash != parent_block_hash:
		print("{}: The parent hash {} of the received block with hash {} is different from {}!"\
					.format(datetime.now().time(), block.block_header.prev_block_hash, block.get_hash_hex(), \
					parent_block_hash))
		return False

	candidate = tx.Candidate_Block(block.transactions)
	tx_merkle_root = candidate.get_merkle_root()
	if block.block_header.merkle_root != tx_merkle_root:
		print("{}: The merkle root of the txs in the received block and its header are different!"\
					.format(datetime.now().time()))
		return False

	if block.block_header.pow_target < POW_TARGET: #really necessary?
		print("{}: The pow_target specified in the header of the received block is less than POW_TARGET!"\
					.format(datetime.now().time()))
		return False
	
	header_hash = block.get_hash_hex()
	if int(header_hash, 16) >= POW_TARGET:
		print("{}: The actual header_hash of the received block is bigger than POW_TARGET!"\
					.format(datetime.now().time()))
		return False

	return True


def mine_for_life(blockchain, blockchain_lock, miners_pubkey_compressed, STATE_CATCHING_UP, peers_socks_vers_out):

	def wait_long_enough():
		block_to_be_mined_nr = len(blockchain)
		parent_block_hash = blockchain[block_to_be_mined_nr - 1].get_hash_hex()

		nr_of_peers = len(peers_socks_vers_out)
		initial_time = current_time = time.time()

		while current_time - initial_time < SEC_WAIT_FOR_BLK_PROPAG:
			current_time = time.time()

			new_nr_of_peers = len(peers_socks_vers_out)
			if new_nr_of_peers > nr_of_peers:
				nr_of_peers = new_nr_of_peers
				print("{}: New connection spotted while inside wait_long_enough. \
							Reset the timer to let the connection go through".format(datetime.now().time()))
				initial_time = current_time

			chain_height = len(blockchain)
			if chain_height > block_to_be_mined_nr:
				print("\n{}: While inside wait_long_enough, the block {} has been mined by someone!\
					The block that should be mined now is {}"\
					.format(datetime.now().time(), block_to_be_mined_nr, chain_height))
				block_to_be_mined_nr = chain_height
				parent_block_hash = blockchain[chain_height - 1].get_hash_hex()
				initial_time = current_time
			else:
				highest_block_hash = blockchain[chain_height - 1].get_hash_hex()
				if highest_block_hash != parent_block_hash:

					if chain_height == block_to_be_mined_nr:
						print("\n{}: While inside wait_long_enough, the parent block with hash {} \
								has been replaced by the block with hash {}!\n"\
								.format(datetime.now().time(), parent_block_hash, highest_block_hash))
					else:
						print("\n{}: While inside wait_long_enough, at least 1 block has been deleted from the \
							blockchain\n".format(datetime.now().time()))
						block_to_be_mined_nr = chain_height

					parent_block_hash = highest_block_hash
					initial_time = current_time

			time.sleep(1)


	def mine_next_block():
		block_to_be_mined_nr = len(blockchain)
		current_time_encoded = bytes(str(int(time.time())).encode("UTF-8"))
		parent_block_hash = blockchain[block_to_be_mined_nr - 1].get_hash_hex()
		header = tx.Block_Header(parent_block_hash, merkle_root, current_time_encoded, POW_TARGET)

		nr_of_peers = len(peers_socks_vers_out)

		# print("{}: Started mining block {}".format(datetime.now().time(), block_to_be_mined_nr))
		for nonce in range(max_nonce):
			if len(peers_socks_vers_out) > nr_of_peers:
				nr_of_peers = len(peers_socks_vers_out)
				print("{}: New connection(-s) spotted while mining. Pausing to let it go through..."\
						.format(datetime.now().time()))
				wait_long_enough()
				#return? this would mean losing all the work done while mining the current block

			if STATE_CATCHING_UP == True:
				print("\n{}: Stopping the mining because STATE_CATCHING_UP is True\n"\
					.format(datetime.now().time()))
				return

			chain_height = len(blockchain)
			if chain_height > block_to_be_mined_nr:
				print("{}: Block {} was mined by someone else. I've tried {} nonces. \
							The block that should be mined now is {}. Pausing..."\
							.format(datetime.now().time(), block_to_be_mined_nr, nonce, chain_height))
				wait_long_enough()
				return
			else:
				highest_block_hash = blockchain[chain_height - 1].get_hash_hex()
				if highest_block_hash != parent_block_hash:
					if chain_height == block_to_be_mined_nr:
						print("{}: Parent block ({}) has been replaced by the block {}! \
									Gotta start mining block {} from zero. Pausing..."\
									.format(datetime.now().time(), parent_block_hash, highest_block_hash, \
									block_to_be_mined_nr))
					else:
						print("{}: At least 1 block has been deleted from blockchain. Pausing..."\
								.format(datetime.now().time()))
					wait_long_enough()
					return

			header_plus_nonce = header.header + bytes(nonce)
			header_hash = hashlib.sha256(header_plus_nonce).hexdigest() #or, maybe, do double-hash?
			if int(header_hash, 16) < header.pow_target:
				header.nonce = nonce
				mined_block = tx.Block(header, candidate.transactions)

				blockchain_lock.acquire() #what exactly gets broken if this is moved lower?
				highest_block_hash = blockchain[-1].get_hash_hex()
				if highest_block_hash != parent_block_hash:
					print("Right after I've mined the new block, the parent block with hash {} has been \
							replaced by the block with hash {}! Gotta start mining the new block from zero.\
							Pausing...".format(parent_block_hash, highest_block_hash))
					blockchain_lock.release()
					wait_long_enough()
					return

				if len(blockchain) > block_to_be_mined_nr:
					print("{}: Block {} was mined by someone else right after I've mined it myself \
						trying {} hashes. Pausing...".format(datetime.now().time(), block_to_be_mined_nr, nonce))
					blockchain_lock.release()
					wait_long_enough()
					return
				
				blockchain.insert(block_to_be_mined_nr, mined_block)
				blockchain_lock.release()

				print("{}: Mined block {} ({}). Added it to the blockchain. Successful nonce: {}. Pausing..."\
						.format(datetime.now().time(), block_to_be_mined_nr, header_hash, nonce))
				wait_long_enough()
				return (header, nonce)

		print("Failed after %d (max_nonce) tries" % max_nonce)
		return

	max_nonce = 2 ** 32  # 4 billion

	coinbase_input = tx.Input("coinbase")
	coinbase_output = tx.Output(50, miners_pubkey_compressed)
	coinbase_tx = tx.Transaction([coinbase_input],[coinbase_output])

	candidate = tx.Candidate_Block([coinbase_tx])
	merkle_root = candidate.get_merkle_root()
	
	while True:
		mine_next_block()