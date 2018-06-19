import tx
import key_gen
import pickle
import hashlib
import time

# priv_key = key_gen.generate_a_private_key()
# pub_key = key_gen.generate_the_public_key_point(priv_key)
# pub_key_compressed = key_gen.compress_the_public_key_point(pub_key)

# print("priv_key: ", priv_key)
# print("pub_key: ", pub_key)
# print("pub_key_compressed: ", pub_key_compressed)


first_input = tx.Input("coinbase")
first_output = tx.Output(50,"03c70dfcab989324d106435333c603faa5f1dc9e0d2a69d23a4332e6cc55c3f599")
first_tx = tx.Transaction([first_input],[first_output])

second_output = tx.Output(50,"03c70dfcab989324d106435333c603faa5f1dc9e0d2a69d23a4332e6cc55c3f590")
second_tx = tx.Transaction([first_input],[second_output])
candidate2 = tx.Candidate_Block([second_tx])

# tx_1_double_hash = hashlib.sha256(hashlib.sha256(first_tx.get_bytes()).digest()).digest()
# print(tx_1_double_hash)
# tx_1_double_hash = hashlib.sha256(hashlib.sha256(first_tx.get_bytes()).hexdigest()).digest()
# print(tx_1_double_hash)

candidate = tx.Candidate_Block([first_tx])
merkle_root = candidate.get_merkle_root()

# if type(candidate) == type(candidate2):
# 	print("equal: ", type(candidate), type(candidate2))
# else:
# 	print("not equal")


target = 2 ** 242
# timp = time.time()
timp = b'1527688894'
timp = bytes(str(int(timp)).encode("UTF-8"))
header = tx.Block_Header("", merkle_root, timp, target)
header.proof_of_work()

genesis_block = tx.Block(header,[first_tx])
# with open('genesis_block', 'wb') as f:
# 	pickle.dump(genesis_block,f)
print(genesis_block.get_hash_hex())