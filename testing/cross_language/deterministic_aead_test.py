# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Cross-language tests for the DeterministicAead primitive."""

from absl.testing import absltest
from absl.testing import parameterized

import tink
from tink import daead
from tink.proto import tink_pb2
from util import keyset_builder
from util import supported_key_types
from util import testing_servers

SUPPORTED_LANGUAGES = testing_servers.SUPPORTED_LANGUAGES_BY_PRIMITIVE['daead']


def key_rotation_test_cases():
  for enc_lang in SUPPORTED_LANGUAGES:
    for dec_lang in SUPPORTED_LANGUAGES:
      for prefix in [tink_pb2.RAW, tink_pb2.TINK]:
        daead_templates = daead.deterministic_aead_key_templates
        old_key_tmpl = daead_templates.create_aes_siv_key_template(64)
        old_key_tmpl.output_prefix_type = prefix
        new_key_tmpl = daead.deterministic_aead_key_templates.AES256_SIV
        yield (enc_lang, dec_lang, old_key_tmpl, new_key_tmpl)


def setUpModule():
  daead.register()
  testing_servers.start()


def tearDownModule():
  testing_servers.stop()


class DeterministicAeadTest(parameterized.TestCase):

  @parameterized.parameters(
      supported_key_types.test_cases(supported_key_types.DAEAD_KEY_TYPES))
  def test_encrypt_decrypt(self, key_template_name, supported_langs):
    self.assertNotEmpty(supported_langs)
    key_template = supported_key_types.KEY_TEMPLATE[key_template_name]
    # Take the first supported language to generate the keyset.
    keyset = testing_servers.new_keyset(supported_langs[0], key_template)
    supported_daeads = [
        testing_servers.deterministic_aead(lang, keyset)
        for lang in supported_langs
    ]
    self.assertNotEmpty(supported_daeads)
    unsupported_daeads = [
        testing_servers.deterministic_aead(lang, keyset)
        for lang in SUPPORTED_LANGUAGES
        if lang not in supported_langs
    ]
    plaintext = (
        b'This is some plaintext message to be encrypted using '
        b'key_template %s.' % key_template_name.encode('utf8'))
    associated_data = (
        b'Some associated data for %s.' % key_template_name.encode('utf8'))
    ciphertext = None
    for p in supported_daeads:
      if ciphertext:
        self.assertEqual(
            ciphertext,
            p.encrypt_deterministically(plaintext, associated_data))
      else:
        ciphertext = p.encrypt_deterministically(plaintext, associated_data)
    for p2 in supported_daeads:
      output = p2.decrypt_deterministically(ciphertext, associated_data)
      self.assertEqual(output, plaintext)
    for p2 in unsupported_daeads:
      with self.assertRaises(tink.TinkError):
        p2.decrypt_deterministically(ciphertext, associated_data)
    for p in unsupported_daeads:
      with self.assertRaises(tink.TinkError):
        p.encrypt_deterministically(b'plaintext', b'associated_data')

  @parameterized.parameters(key_rotation_test_cases())
  def test_key_rotation(self, enc_lang, dec_lang, old_key_tmpl, new_key_tmpl):
    # Do a key rotation from an old key generated from old_key_tmpl to a new
    # key generated from new_key_tmpl. Encryption and decryption are done
    # in languages enc_lang and dec_lang.
    builder = keyset_builder.new_keyset_builder()
    older_key_id = builder.add_new_key(old_key_tmpl)
    builder.set_primary_key(older_key_id)
    enc_daead1 = testing_servers.deterministic_aead(enc_lang, builder.keyset())
    dec_daead1 = testing_servers.deterministic_aead(dec_lang, builder.keyset())
    newer_key_id = builder.add_new_key(new_key_tmpl)
    enc_daead2 = testing_servers.deterministic_aead(enc_lang, builder.keyset())
    dec_daead2 = testing_servers.deterministic_aead(dec_lang, builder.keyset())

    builder.set_primary_key(newer_key_id)
    enc_daead3 = testing_servers.deterministic_aead(enc_lang, builder.keyset())
    dec_daead3 = testing_servers.deterministic_aead(dec_lang, builder.keyset())

    builder.disable_key(older_key_id)
    enc_daead4 = testing_servers.deterministic_aead(enc_lang, builder.keyset())
    dec_daead4 = testing_servers.deterministic_aead(dec_lang, builder.keyset())

    self.assertNotEqual(older_key_id, newer_key_id)
    # 1 encrypts with the older key. So 1, 2 and 3 can decrypt it, but not 4.
    ciphertext1 = enc_daead1.encrypt_deterministically(b'plaintext', b'ad')
    self.assertEqual(dec_daead1.decrypt_deterministically(ciphertext1, b'ad'),
                     b'plaintext')
    self.assertEqual(dec_daead2.decrypt_deterministically(ciphertext1, b'ad'),
                     b'plaintext')
    self.assertEqual(dec_daead3.decrypt_deterministically(ciphertext1, b'ad'),
                     b'plaintext')
    with self.assertRaises(tink.TinkError):
      _ = dec_daead4.decrypt_deterministically(ciphertext1, b'ad')

    # 2 encrypts with the older key. So 1, 2 and 3 can decrypt it, but not 4.
    ciphertext2 = enc_daead2.encrypt_deterministically(b'plaintext', b'ad')
    self.assertEqual(dec_daead1.decrypt_deterministically(ciphertext2, b'ad'),
                     b'plaintext')
    self.assertEqual(dec_daead2.decrypt_deterministically(ciphertext2, b'ad'),
                     b'plaintext')
    self.assertEqual(dec_daead3.decrypt_deterministically(ciphertext2, b'ad'),
                     b'plaintext')
    with self.assertRaises(tink.TinkError):
      _ = dec_daead4.decrypt_deterministically(ciphertext2, b'ad')

    # 3 encrypts with the newer key. So 2, 3 and 4 can decrypt it, but not 1.
    ciphertext3 = enc_daead3.encrypt_deterministically(b'plaintext', b'ad')
    with self.assertRaises(tink.TinkError):
      _ = dec_daead1.decrypt_deterministically(ciphertext3, b'ad')
    self.assertEqual(dec_daead2.decrypt_deterministically(ciphertext3, b'ad'),
                     b'plaintext')
    self.assertEqual(dec_daead3.decrypt_deterministically(ciphertext3, b'ad'),
                     b'plaintext')
    self.assertEqual(dec_daead4.decrypt_deterministically(ciphertext3, b'ad'),
                     b'plaintext')

    # 4 encrypts with the newer key. So 2, 3 and 4 can decrypt it, but not 1.
    ciphertext4 = enc_daead4.encrypt_deterministically(b'plaintext', b'ad')
    with self.assertRaises(tink.TinkError):
      _ = dec_daead1.decrypt_deterministically(ciphertext4, b'ad')
    self.assertEqual(dec_daead2.decrypt_deterministically(ciphertext4, b'ad'),
                     b'plaintext')
    self.assertEqual(dec_daead3.decrypt_deterministically(ciphertext4, b'ad'),
                     b'plaintext')
    self.assertEqual(dec_daead4.decrypt_deterministically(ciphertext4, b'ad'),
                     b'plaintext')

if __name__ == '__main__':
  absltest.main()
