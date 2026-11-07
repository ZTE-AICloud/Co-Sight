"""口令哈希与策略单测（纯标准库，不连 DB）。"""

from __future__ import annotations

import pytest

from auth import passwords


def test_hash_and_verify_roundtrip():
    stored = passwords.hash_password('correct horse battery staple')

    assert stored.startswith('scrypt$16384$8$1$')
    assert passwords.verify_password('correct horse battery staple', stored)
    assert not passwords.verify_password('wrong password', stored)


def test_hash_uses_a_fresh_salt_each_time():
    first = passwords.hash_password('same-password')
    second = passwords.hash_password('same-password')

    assert first != second
    assert passwords.verify_password('same-password', first)
    assert passwords.verify_password('same-password', second)


@pytest.mark.parametrize('stored', [
    '',
    'plaintext',
    'scrypt$16384$8$1$not-base64$also-not',
    'scrypt$3$8$1$c2FsdHNhbHRzYWx0$' + 'A' * 43,
    'scrypt$16384$99$1$c2FsdHNhbHRzYWx0$' + 'A' * 43,
    'scrypt$16384$8$0$c2FsdHNhbHRzYWx0$' + 'A' * 43,
    'bcrypt$whatever',
])
def test_verify_rejects_malformed_hashes_without_raising(stored):
    assert passwords.verify_password('anything', stored) is False


def test_verify_rejects_empty_password():
    stored = passwords.hash_password('something')
    assert passwords.verify_password('', stored) is False
    assert passwords.verify_password(None, stored) is False


def test_needs_rehash_detects_weaker_parameters():
    current = passwords.hash_password('pw')
    weaker = current.replace('scrypt$16384$8$1$', 'scrypt$1024$8$1$', 1)

    assert passwords.needs_rehash(current) is False
    assert passwords.needs_rehash(weaker) is True
    assert passwords.needs_rehash('garbage') is True


def test_dummy_hash_never_matches_real_passwords():
    assert passwords.verify_password('dummy-password-for-timing-equalization',
                                     passwords.DUMMY_HASH) is True
    assert passwords.verify_password('admin', passwords.DUMMY_HASH) is False


def test_validate_username():
    assert passwords.validate_username('  alice  ') == 'alice'
    assert passwords.validate_username('a.b@c-d_1') == 'a.b@c-d_1'


@pytest.mark.parametrize('value', ['', 'ab', 'a' * 65, 'bad name', '汉字名'])
def test_validate_username_rejects_bad_values(value):
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.validate_username(value)


def test_validate_password_length_and_control_characters():
    assert passwords.validate_password('12345678') == '12345678'
    assert passwords.validate_password('x' * 128) == 'x' * 128

    for value in ('', '   ', 'short', 'x' * 129, 'line\nbreak'):
        with pytest.raises(passwords.PasswordPolicyError):
            passwords.validate_password(value)
