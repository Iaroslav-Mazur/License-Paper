import ecdsa
from ecdsa.util import string_to_number, number_to_string
import os
import binascii

SECP256k1 = ecdsa.curves.find_curve((1, 3, 132, 0, 10))
attrs = vars(SECP256k1)
# print (', '.join("%s: %s" % item for item in attrs.items()))
generator = SECP256k1.generator
# print ("generator: ", generator)

def generate_a_private_key():
	random_bytes = os.urandom(32)
	private_key = int(binascii.hexlify(random_bytes),16)
	return private_key

def generate_the_public_key_point(private_key):
	pub_key_point = private_key * generator #how exactly /why does this multiplication happen?
	return pub_key_point

def compress_the_public_key_point(pub_key_point):
	compressed_result = ''
	# even(02) - positive, odd(03) = negative
	if pub_key_point.y() & 1:
		compressed_result = '03' + '%064x' % pub_key_point.x() 
		'''%064x' % = format the number you get as a 64character string, with padding 0s at the beginning, 
		interpreted as hexadecimal'''
	else:
		compressed_result = '02' + '%064x' % pub_key_point.x()
	# return binascii.unhexlify(compressed_result)
	return compressed_result

if __name__ == "__main__":
	priv_key = generate_a_private_key()
	print ("priv_key: {}".format(str(priv_key)))

	pub_key_point = generate_the_public_key_point(priv_key)
	print ("pub_key_point: {}\n".format(pub_key_point))

	# print ("pub_key_point y & 1: {}\n".format(pub_key_point.y() & 1))

	print(compress_the_public_key_point(pub_key_point))

	pub_key_compressed = (int(binascii.hexlify(bytes(compress_the_public_key_point(pub_key_point).encode("ASCII"))),16))
	print ("pub_key_compressed: ", pub_key_compressed)




#http://nullege.com/codes/search/ecdsa.ellipticcurve.Point