# This file is dual licensed under the terms of the Apache License, Version
# 2.0, and the BSD License. See the LICENSE file in the root of this repository
# for complete details.

from __future__ import absolute_import, division, print_function

import pytest

from cryptography.hazmat._der import (
    DERReader, INTEGER, NULL, OCTET_STRING, SEQUENCE, encode_der_integer,
    encode_der
)


def test_der_reader_basic():
    reader = DERReader(b"123456789")
    assert reader.read_byte() == ord(b"1")
    assert reader.read_bytes(1).tobytes() == b"2"
    assert reader.read_bytes(4).tobytes() == b"3456"

    with pytest.raises(ValueError):
        reader.read_bytes(4)

    assert reader.read_bytes(3).tobytes() == b"789"

    # The input is now empty.
    with pytest.raises(ValueError):
        reader.read_bytes(1)
    with pytest.raises(ValueError):
        reader.read_byte()


def test_der():
    # This input is the following structure, using
    # https://github.com/google/der-ascii
    #
    # SEQUENCE {
    #   SEQUENCE {
    #     NULL {}
    #     INTEGER { 42 }
    #     OCTET_STRING { "hello" }
    #   }
    # }
    der = b"\x30\x0e\x30\x0c\x05\x00\x02\x01\x2a\x04\x05\x68\x65\x6c\x6c\x6f"
    reader = DERReader(der)
    with pytest.raises(ValueError):
        reader.check_empty()

    # Parse the outer element.
    outer = reader.read_element(SEQUENCE)
    reader.check_empty()
    assert outer.data.tobytes() == der[2:]

    # Parse the outer element with read_any_element.
    reader = DERReader(der)
    tag, outer2 = reader.read_any_element()
    reader.check_empty()
    assert tag == SEQUENCE
    assert outer2.data.tobytes() == der[2:]

    # Parse the outer element with read_single_element.
    outer3 = DERReader(der).read_single_element(SEQUENCE)
    assert outer3.data.tobytes() == der[2:]

    # read_single_element rejects trailing data.
    with pytest.raises(ValueError):
        DERReader(der + der).read_single_element(SEQUENCE)

    # Continue parsing the structure.
    inner = outer.read_element(SEQUENCE)
    outer.check_empty()

    # Parsing a missing optional element should work.
    assert inner.read_optional_element(INTEGER) is None

    null = inner.read_element(NULL)
    null.check_empty()

    # Parsing a present optional element should work.
    integer = inner.read_optional_element(INTEGER)
    assert integer.as_integer() == 42

    octet_string = inner.read_element(OCTET_STRING)
    assert octet_string.data.tobytes() == b"hello"

    # Parsing a missing optional element should work when the input is empty.
    inner.check_empty()
    assert inner.read_optional_element(INTEGER) is None

    # Re-encode the same structure.
    der2 = encode_der(
        SEQUENCE,
        encode_der(
            SEQUENCE,
            encode_der(NULL),
            encode_der(INTEGER, encode_der_integer(42)),
            encode_der(OCTET_STRING, b"hello"),
        )
    )
    assert der2 == der


@pytest.mark.parametrize(
    "length,header",
    [
        # Single-byte lengths.
        (0, b"\x04\x00"),
        (1, b"\x04\x01"),
        (2, b"\x04\x02"),
        (127, b"\x04\x7f"),
        # Long-form lengths.
        (128, b"\x04\x81\x80"),
        (129, b"\x04\x81\x81"),
        (255, b"\x04\x81\xff"),
        (0x100, b"\x04\x82\x01\x00"),
        (0x101, b"\x04\x82\x01\x01"),
        (0xffff, b"\x04\x82\xff\xff"),
        (0x10000, b"\x04\x83\x01\x00\x00"),
    ]
)
def test_der_lengths(length, header):
    body = length * b"a"
    der = header + body

    reader = DERReader(der)
    element = reader.read_element(OCTET_STRING)
    reader.check_empty()
    assert element.data.tobytes() == body

    assert encode_der(OCTET_STRING, body) == der


@pytest.mark.parametrize(
    "bad_input",
    [
        # The input ended before the tag.
        b"",
        # The input ended before the length.
        b"\x30",
        # The input ended before the second byte of the length.
        b"\x30\x81",
        # The input ended before the body.
        b"\x30\x01",
        # The length used long form when it should be short form.
        b"\x30\x81\x00",
        # The length was not minimally-encoded.
        b"\x30\x82\x00\x80" + (0x80 * b"a"),
        # Indefinite-length encoding is not valid DER.
        b"\x30\x80\x00\x00"
        # Tag number (the bottom 5 bits) 31 indicates long form tags, which we
        # do not support.
        b"\x1f\x00",
        b"\x9f\x00",
        b"\xbf\x00",
        b"\xff\x00",
    ]
)
def test_der_reader_bad_input(bad_input):
    reader = DERReader(bad_input)
    with pytest.raises(ValueError):
        reader.read_any_element()


def test_der_reader_wrong_tag():
    reader = DERReader(b"\x04\x00")
    with pytest.raises(ValueError):
        reader.read_element(SEQUENCE)


@pytest.mark.parametrize(
    "value,der",
    [
        (0, b'\x00'),
        (1, b'\x01'),
        (2, b'\x02'),
        (3, b'\x03'),
        (127, b'\x7f'),
        (128, b'\x00\x80'),
        (0x112233445566778899aabbccddeeff, b'\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb\xcc\xdd\xee\xff'),
        (-1, b'\xff'),
        (-2, b'\xfe'),
        (-3, b'\xfd'),
        (-4, b'\xfc'),
        (-127, b'\x81'),
        (-128, b'\x80'),
        (-129, b'\xff\x7f'),
        (-0x112233445566778899aabbccddeeff, b'\xee\xdd\xcc\xbb\xaa\x99\x88\x77\x66\x55\x44\x33\x22\x11\x01'),
    ]
)
def test_integer(value, der):
    assert encode_der_integer(value) == der
    assert DERReader(der).as_integer() == value


@pytest.mark.parametrize(
    "bad_input",
    [
        # Zero is encoded as b"\x00", not the empty string.
        b"",
        # Too many leading zeros.
        b"\x00\x00",
        b"\x00\x7f",
        # Too many leading ones.
        b"\xff\xff",
        b"\xff\x80",
    ]
)
def test_invalid_integer(bad_input):
    reader = DERReader(bad_input)
    with pytest.raises(ValueError):
        reader.as_integer()
