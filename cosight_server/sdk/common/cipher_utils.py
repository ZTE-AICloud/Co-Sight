# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import base64
import hashlib

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


class CipherUtils:
    @staticmethod
    def encrypt(text: str) -> str:
        seed_key, seed_iv = CipherUtils.generate_key_iv()
        cipher = AES.new(seed_key, AES.MODE_CBC, seed_iv)
        padded_text = pad(text.encode(), AES.block_size)
        encrypted = cipher.encrypt(padded_text)
        return base64.b64encode(encrypted).decode('utf-8')

    @staticmethod
    def decrypt(data: str) -> str:
        encrypted = base64.b64decode(data)
        seed_key, seed_iv = CipherUtils.generate_key_iv()
        cipher = AES.new(seed_key, AES.MODE_CBC, seed_iv)
        padded_text = cipher.decrypt(encrypted)
        return unpad(padded_text, AES.block_size).decode('utf-8')

    @staticmethod
    def generate_key_iv():
        # Create a SHA-256 hash of the seed string
        hash_bytes = hashlib.sha256("aim_traffic_ops_2024".encode()).digest()
        # Use the first 16 bytes for the key (AES-128)
        key = hash_bytes[:16]
        # Use the next 16 bytes for the IV
        iv = hash_bytes[16:32]
        return key, iv


# Example usage
if __name__ == "__main__":
    plain_text = "traffic_ops_token_key"

    encrypted_text = CipherUtils.encrypt(plain_text)
    # print(f"Encrypted: {encrypted_text}")

    decrypted_text = CipherUtils.decrypt(encrypted_text)
    # print(f"Decrypted: {decrypted_text}")
