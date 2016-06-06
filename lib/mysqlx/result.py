# MySQL Connector/Python - MySQL driver written in Python.
# Copyright (c) 2016, Oracle and/or its affiliates. All rights reserved.

# MySQL Connector/Python is licensed under the terms of the GPLv2
# <http://www.gnu.org/licenses/old-licenses/gpl-2.0.html>, like most
# MySQL Connectors. There are special exceptions to the terms and
# conditions of the GPLv2 as it is applied to this software, see the
# FOSS License Exception
# <http://www.mysql.com/about/legal/licensing/foss-exception.html>.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA

"""Implementation of the Result Set classes."""

import decimal
import struct
import sys

from datetime import datetime, timedelta
from .dbdoc import DbDoc
from .charsets import MYSQL_CHARACTER_SETS

def from_protobuf(col_type, payload):
    if len(payload) == 0:
        return None

    try:
        return {
            ColumnProtoType.SINT: varsint_from_protobuf,
            ColumnProtoType.UINT: varint_from_protobuf,
            ColumnProtoType.BYTES: bytes_from_protobuf,
            ColumnProtoType.DATETIME: datetime_from_protobuf,
            ColumnProtoType.TIME: time_from_protobuf,
            ColumnProtoType.FLOAT: float_from_protobuf,
            ColumnProtoType.DOUBLE: double_from_protobuf,
            ColumnProtoType.BIT: varint_from_protobuf,
            ColumnProtoType.SET: set_from_protobuf,
            ColumnProtoType.ENUM: bytes_from_protobuf,
            ColumnProtoType.DECIMAL: decimal_from_protobuf,
        }[col_type](payload)
    except KeyError as e:
        sys.stderr.write("{0}".format(e))
        sys.stderr.write("{0}".format(payload.encode("hex")))
        return None


def bytes_from_protobuf(payload):
    # Strip trailing char
    return payload[:-1]


def float_from_protobuf(payload):
    assert len(payload) == 4
    return struct.unpack("<f", payload)


def double_from_protobuf(payload):
    assert len(payload) == 8
    return struct.unpack("<d", payload)


def varint_from_protobuf_stream(payload):
    if len(payload) == 0:
        raise ValueError("Payload is empty")

    cur = 0
    i = 0
    shift = 0

    for c in payload:
        ch = ord(c)
        eos = (ch & 0x80) == 0
        cur_bits = (ch & 0x7f)
        cur_bits <<= shift
        i |= cur_bits
        if eos:
            return i, payload[cur + 1:]
        cur += 1
        shift += 7

    raise EOFError("Payload too short")


def varint_from_protobuf(payload):
    i, payload = varint_from_protobuf_stream(payload)
    if len(payload) != 0:
        raise ValueError("Payload too long")

    return i


def varsint_from_protobuf(payload):
    i, payload = varint_from_protobuf_stream(payload)
    if len(payload) != 0:
        raise ValueError("Payload too long")

    # Zigzag encoded, revert it
    if i & 0x1:
        i = ~i
        i = (i >> 1)
        i |= 1 << 63
    else:
        i = (i >> 1)

    return i


def set_from_protobuf(payload):
    s = []
    while True:
        try:
            field_len, payload = varint_from_protobuf_stream(payload)
            if len(payload) < field_len:
                if len(payload) == 0 and field_len == 1 and len(s) == 0:
                    # Special case for empty set
                    return []
                raise ValueError("Invalid Set encoding")

            s.append(payload[:field_len])
            payload = payload[field_len:]
            if len(payload) == 0:
                # Done
                break
        except ValueError:
            break
    return s


def decimal_from_protobuf(payload):
    digits = []
    sign = None
    scale = ord(payload[0])
    payload = payload[1:]

    for c in payload:
        ch = ord(c)
        high_bcd = (ch & 0xf0) >> 4
        low_bcd = ch & 0x0f
        if high_bcd < 0x0a:
            digits.append(high_bcd)
            if low_bcd < 0x0a:
                digits.append(low_bcd)
            elif low_bcd == 0x0c:
                sign = 0
                break
            elif low_bcd == 0x0d:
                sign = 1
                break
            else:
                raise ValueError("Invalid BCD")
        elif high_bcd == 0x0c:
            sign = 0
            assert low_bcd == 0x00
            break
        elif high_bcd == 0x0d:
            sign = 1
            assert low_bcd == 0x00
            break
        else:
            raise ValueError("Invalid BCD: {0}".format(high_bcd))

    return decimal.Decimal((sign, digits, -scale))


def datetime_from_protobuf(payload):
    # A sequence of varints
    hour = 0
    minutes = 0
    seconds = 0
    useconds = 0
    year, payload = varint_from_protobuf_stream(payload)
    month, payload = varint_from_protobuf_stream(payload)
    day, payload = varint_from_protobuf_stream(payload)

    try:
        hour, payload = varint_from_protobuf_stream(payload)
        minutes, payload = varint_from_protobuf_stream(payload)
        seconds, payload = varint_from_protobuf_stream(payload)
        useconds, payload = varint_from_protobuf_stream(payload)
    except ValueError:
        pass

    return datetime(year, month, day, hour, minutes, seconds, useconds)


def time_from_protobuf(payload):
    # A sequence of varints
    hour = 0
    minutes = 0
    seconds = 0
    useconds = 0
    negate = payload[0] == 1
    payload = payload[1:]

    try:
        hour, payload = varint_from_protobuf_stream(payload)
        minutes, payload = varint_from_protobuf_stream(payload)
        seconds, payload = varint_from_protobuf_stream(payload)
        useconds, payload = varint_from_protobuf_stream(payload)
    except ValueError:
        pass

    if negate:
        # Negate the first non-zero value
        if hour:
            hour *= -1
        elif minutes:
            minutes *= -1
        elif seconds:
            seconds *= -1
        elif useconds:
            useconds *= -1

    return timedelta(hours=hour, minutes=minutes, seconds=seconds,
                     microseconds=useconds)


class Collations(object):
    UTF8_GENERAL_CI = 33

class ColumnType(object):
    BIT = 1
    TINYINT = 2
    SMALLINT = 3
    MEDIUMINT = 4
    INT = 5
    BIGINT = 6
    FLOAT = 7
    DECIMAL = 8
    DOUBLE = 9
    JSON = 10
    STRING = 11
    BYTES = 12
    TIME = 13
    DATE = 14
    DATETIME = 15
    TIMESTAMP = 16
    SET = 17
    ENUM = 18
    GEOMETRY = 19
    XML = 20

class ColumnProtoType(object):
    SINT = 1
    UINT = 2
    DOUBLE = 5
    FLOAT = 6
    BYTES = 7
    TIME = 10
    DATETIME = 12
    SET = 15
    ENUM = 16
    BIT = 17
    DECIMAL = 18


class Flags(object):
    def __init__(self, value):
        self._allowed_flags = {}
        self._flag_names = {}
        for k, v in self.__class__.__dict__.items():
            if k.startswith("__"):
                continue
            if type(v) in (int, ):
                self._allowed_flags[k] = v
                self._flag_names[v] = k
        self.value = value

    def __str__(self):
        mask = 1
        flag_names = []
        value = self.value

        for _ in range(0, 63):
            mask <<= 1
            flag = value & mask
            if flag:
                # We matched something, find the name for it
                try:
                    flag_names.append(self._flag_names[flag])
                except KeyError:
                    sys.stderr.write("{0}".format(self._flag_names))
                    sys.stderr.write("{0}".format(self.__class__.__dict__))

        return ",".join(flag_names)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = v


class ColumnFlags(Flags):
    NOT_NULL = 0x0010
    PRIMARY_KEY = 0x0020
    UNIQUE_KEY = 0x0040
    MULTIPLE_KEY = 0x0080
    AUTO_INCREMENT = 0x0100


class DatetimeColumnFlags(ColumnFlags):
    TIMESTAMP = 0x0001


class UIntColumnFlags(ColumnFlags):
    ZEROFILL = 0x0001


class DoubleColumnFlags(ColumnFlags):
    UNSIGNED = 0x0001


class FloatColumnFlags(ColumnFlags):
    UNSIGNED = 0x0001


class BytesColumnFlags(ColumnFlags):
    RIGHT_PAD = 0x0001

class BytesContentType(ColumnFlags):
    GEOMETRY = 0x0001
    JSON = 0x0002
    XML = 0x0003


class ColumnMetaData(object):
    def __init__(self, col_type, catalog=None, schema=None, table=None,
                 original_table=None, name=None, original_name=None,
                 length=None, collation=None, fractional_digits=None,
                 flags=None, content_type=None):
        self._schema = schema
        self._name = name
        self._original_name = original_name
        self._table = table
        self._original_table = original_table
        self._proto_type = col_type
        self._col_type = None
        self._catalog = catalog
        self._length = length
        self._collation = collation
        self._fractional_digits = fractional_digits
        self._flags = flags
        self._content_type = content_type
        self._number_signed = False
        self._is_padded = False
        self._is_binary = False
        self._collation_name = None
        self._character_set_name = None

        if self._collation > 0:
            if self._collation >= len(MYSQL_CHARACTER_SETS):
                raise Exception("No mapping found for collation " + str(self._collation))
            info = MYSQL_CHARACTER_SETS[self._collation]
            self._character_set_name = info[0]
            self._collation_name = info[1]
            self._is_binary = "binary" in self._collation_name or "_bin" in self._collation_name
        self._map_type()

    def __str__(self):
        return str({
            "col_type": self._col_type.name,
            "schema": self._schema,
            "table": self._table,
            "flags": str(self._flags),
        })

    def get_schema_name(self):
        return self._schema

    def get_table_name(self):
        return self._original_table or self._table

    def get_table_label(self):
        return self._table or self._original_table

    def get_column_name(self):
        return self._original_name or self._name

    def get_column_label(self):
        return self._name or self._original_name

    def get_type(self):
        return self._col_type

    def get_length(self):
        return self._length

    def get_fractional_digits(self):
        return self._fractional_digits

    def get_collation_name(self):
        return self._collation_name

    def get_character_set_name(self):
        return self._character_set_name

    def is_number_signed(self):
        return self._number_signed

    def is_padded(self):
        return self._is_padded

    def _map_int_type(self):
        if self._length <= 4: self._col_type = ColumnType.TINYINT
        elif self._length <= 6: self._col_type = ColumnType.SMALLINT
        elif self._length <= 9: self._col_type = ColumnType.MEDIUMINT
        elif self._length <= 11: self._col_type = ColumnType.INT
        else:
            self._col_type = ColumnType.BIGINT
        self._number_signed = True

    def _map_uint_type(self):
        if self._length <= 3: self._col_type = ColumnType.TINYINT
        elif self._length <= 5: self._col_type = ColumnType.SMALLINT
        elif self._length <= 8: self._col_type = ColumnType.MEDIUMINT
        elif self._length <= 10: self._col_type = ColumnType.INT
        else:
            self._col_type = ColumnType.BIGINT
        self._zero_fill = self._flags & 1

    def _map_bytes(self):
        if self._content_type == BytesContentType.GEOMETRY:
            self._col_type = ColumnType.GEOMETRY
        elif self._content_type == BytesContentType.JSON:
            self._col_type = ColumnType.JSON
        elif self._content_type == BytesContentType.XML:
            self._col_type = ColumnType.XML
        elif self._is_binary:
            self._col_type = ColumnType.BYTES
        else:
            self._col_type = ColumnType.STRING
        self._is_padded = self._flags & 1

    def _map_datetime(self):
        if self._length == 10: self._col_type = ColumnType.DATE
        elif self._length == 19: self._col_type = ColumnType.DATETIME
        elif self._flags & DatetimeColumnFlags.TIMESTAMP > 0: self._col_type = ColumnType.TIMESTAMP
        raise Exception("Datetime mapping scenario unhandled")

    def _map_type(self):
        if self._proto_type == ColumnProtoType.SINT: self._map_int_type()
        elif self._proto_type == ColumnProtoType.UINT: self._map_uint_type()
        elif self._proto_type == ColumnProtoType.FLOAT:
            self._col_type = ColumnType.FLOAT
            self._is_number_signed = (self._flags & FloatColumnFlags.UNSIGNED) == 0
        elif self._proto_type == ColumnProtoType.DECIMAL:
            self._col_type = ColumnType.DECIMAL
            self._is_number_signed = (self._flags & FloatColumnFlags.UNSIGNED) == 0
        elif self._proto_type == ColumnProtoType.DOUBLE:
            self._col_type = ColumnType.DOUBLE
            self._is_number_signed = (self._flags & FloatColumnFlags.UNSIGNED) == 0
        elif self._proto_type == ColumnProtoType.BYTES: self._map_bytes()
        elif self._proto_type == ColumnProtoType.TIME: self._col_type = ColumnType.TIME
        elif self._proto_type == ColumnProtoType.DATETIME: self._map_datetime()
        elif self._proto_type == ColumnProtoType.SET: self._col_type = ColumnType.SET
        elif self._proto_type == ColumnProtoType.ENUM: self._col_type = ColumnType.ENUM
        else:
            raise Exception("Unknown column type {0}".format(self._col_type))


class Warning(object):
    def __init__(self, level, code, msg):
        self._level = level
        self._code = code
        self._message = msg

    @property
    def Level(self):
        return self._level

    @property
    def Code(self):
        return self._code

    @property
    def Message(self):
        return self._message


class Row(object):
    def __init__(self, rs, fields):
        self._fields = fields
        self._resultset = rs

    def __getitem__(self, index):
        if isinstance(index, basestring):
            index = self._resultset.index_of(index)
        elif index >= len(self._fields):
            raise IndexError("Index out of range")
        return self._fields[index]

    def get_string(self, str_index):
        int_index = self._resultset.index_of(str_index)
        if int_index >= len(self._fields):
            raise IndexError("Argument out of range")
        if int_index == -1:
            raise ValueError("Column name '{0}' not found".format(str_index))
        return str(self._fields[int_index])


class BaseResult(object):
    def __init__(self, connection):
        self._connection = connection
        self._protocol = self._connection.protocol
        self._closed = False
        self._rows_affected = 0
        self._warnings = []
        if connection._active_result is not None:
            connection._active_result.fetch_all()
            connection._active_result = None

    @property
    def get_warnings(self):
        return self._warnings

    def get_warnings_count(self):
        return len(self._warnings)


class Result(BaseResult):
    def __init__(self, connection):
        super(Result, self).__init__(connection)
        self._protocol.close_result(self)

    @property
    def get_affected_items_count(self):
        return self._rows_affected

    @property
    def get_autoincrement_value(self):
        pass


class BufferingResult(BaseResult):
    def __init__(self, connection):
        super(BufferingResult, self).__init__(connection)
        self._init_result()

    def _init_result(self):
        self._columns = self._protocol.get_column_metadata(self)
        self._has_more_data = True if len(self._columns) > 0 else False
        self._items = []
        self._page_size = 20
        self._position = -1
        self._connection._active_result = self if self._has_more_data else None

    @property
    def count(self):
        return len(self._items)

    def __getitem__(self, index):
        return self._items[index]

    def index_of(self, col_name):
        index = 0
        for col in self._columns:
            if col.get_column_name() == col_name:
                return index
            index = index + 1
        return -1

    def _read_item(self, dumping):
        row = self._protocol.read_row(self)
        if row is None:
            return None
        item = [None] * len(row.field)
        if not dumping:
            for x in range(len(row.field)):
                col = self._columns[x]
                item[x] = from_protobuf(col._proto_type, row.field[x])
        return Row(self, item)

    def _page_in_items(self):
        if self._closed:
            return False

        count = 0
        for i in range(self._page_size):
            item = self._read_item(False)
            if item is None:
                break
            self._items.append(item)
            count += 1
        return count

    def fetch_all(self):
        while True:
            if not self._page_in_items():
                break
        return self._items


class RowResult(BufferingResult):
    def __init__(self, connection):
        super(RowResult, self).__init__(connection)

    @property
    def columns(self):
        return self._columns


class SqlResult(RowResult):
    def __init__(self, connection):
        super(SqlResult, self).__init__(connection)
        self._has_more_results = False

    def next_result(self):
        if self._closed:
            return False
        self._has_more_results = False
        self._init_result()
        return True


class DocResult(BufferingResult):
    def __init__(self, connection):
        super(DocResult, self).__init__(connection)

    def _read_item(self, dumping):
        row = super(DocResult, self)._read_item(dumping)
        if row is None:
            return None
        return DbDoc(row[0])
