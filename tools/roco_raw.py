"""Offline reader for Roco BinDataCompressed and BinLocalize containers.

This implements the footer, MSB-first presence bits and constant indirections in
FRocoBinData. BinData (the different, uncompressed 56-byte-footer format) is not
supported or auto-detected. Callers must supply the matched schema/localization;
this module never searches files, selects Pak layers, or writes JSON.

Strict mode rejects schema-size differences, unknown presence bits, unconsumed
struct bytes and missing localization. Permissive mode records those conditions;
invalid indices, metadata, UTF-8, array lengths and local read bounds still fail.
An absent presence bit stays absent. An absent localized value becomes an empty
string only in permissive mode, with an explicit missing-localization record.
"""
import struct


MAGIC = 0x53DF17BE
MAX_DEPTH = 64
_TABLE = struct.Struct("<Iiq")
_COMPRESSED_FOOTER = struct.Struct("<qqiqqiqiqq")
_LOCALIZATION_FOOTER = struct.Struct("<qiqq")
_FOOTER_FIELDS = ("DataSectionOffset", "DataSectionLength", "EntriesCount", "StructSize",
                  "DataTableOffset", "DataTableEntriesCount", "ConstantsTableOffset",
                  "ConstantsTableEntriesCount", "ConstantsSectionOffset", "ConstantsSectionLength")
_LOCALIZATION_FIELDS = ("ConstantsTableOffset", "ConstantsTableEntriesCount",
                        "ConstantsSectionOffset", "ConstantsSectionLength")
_PRIMITIVES = {"EUint32": "<I", "EInt32": "<i", "EInt64": "<q",
               "EUint64": "<Q", "EFloat": "<f", "EBool": "<B"}
_WIDTHS = {"EUint32": 4, "EInt32": 4, "EInt64": 8, "EUint64": 8,
           "EFloat": 4, "EBool": 1, "EString": 4, "EStruct": 4, "ELocalizedString": 4}


class RocoDecodeError(ValueError):
    """Invalid or mismatched Roco source data; never a silent partial decode."""


def _pointer(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def _span(offset, length, lower, upper, label):
    if length < 0 or offset < lower or offset > upper or length > upper - offset:
        raise RocoDecodeError(f"{label} bounds: offset={offset}, length={length}, allowed={lower}..{upper}")


def _container(raw, localization=False):
    raw = bytes(raw)
    footer_spec = _LOCALIZATION_FOOTER if localization else _COMPRESSED_FOOTER
    if len(raw) < 4 + footer_spec.size:
        raise RocoDecodeError("Container/footer bounds: file is too short")
    if struct.unpack_from("<I", raw)[0] != MAGIC:
        raise RocoDecodeError("Invalid Roco magic")
    footer_at = len(raw) - footer_spec.size
    fields = _LOCALIZATION_FIELDS if localization else _FOOTER_FIELDS
    footer = dict(zip(fields, footer_spec.unpack_from(raw, footer_at)))
    footer["FooterOffset"] = footer_at
    footer["Format"] = "BinLocalize" if localization else "BinDataCompressed"
    regions = []

    def region(offset, length, label):
        if length == 0 and offset == 0:
            return
        _span(offset, length, 4, footer_at, label)
        if length:
            regions.append((offset, offset + length, label))

    if not localization:
        if footer["EntriesCount"] < 0 or footer["StructSize"] < 0:
            raise RocoDecodeError("Negative footer count or struct size")
        if footer["EntriesCount"] != footer["DataTableEntriesCount"]:
            raise RocoDecodeError("Footer data entry count mismatch")
        region(footer["DataSectionOffset"], footer["DataSectionLength"], "Data section")
    region(footer["ConstantsSectionOffset"], footer["ConstantsSectionLength"], "Constants section")
    tables = {}
    for prefix in (["Constants"] if localization else ["Data", "Constants"]):
        count, offset = footer[prefix + "TableEntriesCount"], footer[prefix + "TableOffset"]
        if count < 0:
            raise RocoDecodeError(prefix + " table has negative count")
        region(offset, count * _TABLE.size, prefix + " table")
        section_at = footer[prefix + "SectionOffset"]
        section_length = footer[prefix + "SectionLength"]
        expected = section_at
        entries = []
        for ordinal in range(count):
            index, length, entry_at = _TABLE.unpack_from(raw, offset + ordinal * _TABLE.size)
            if index != ordinal + 1:
                raise RocoDecodeError(prefix + " table index is not the expected 1-based ordinal")
            _span(entry_at, length, section_at, section_at + section_length, prefix + " entry")
            if entry_at != expected:
                raise RocoDecodeError(prefix + " entry offsets are not contiguous within the declared section")
            entries.append((index, length, entry_at))
            expected = entry_at + length
        if expected != section_at + section_length:
            raise RocoDecodeError(prefix + " entry lengths do not consume their declared section")
        tables[prefix] = entries
    ordered = sorted(regions)
    for first, second in zip(ordered, ordered[1:]):
        if first[1] > second[0]:
            raise RocoDecodeError(f"Container regions overlap: {first[2]} and {second[2]}")
    return raw, footer, tables.get("Data", []), tables["Constants"]


def _utf8(raw, offset, length):
    try:
        return raw[offset:offset + length].decode("utf-8")
    except UnicodeDecodeError as error:
        raise RocoDecodeError(f"Invalid UTF-8 at byte {offset}") from error


def decode_localization(raw: bytes) -> dict[int, str]:
    """Decode the 28-byte-footer localization format, preserving ordinal gaps.

    Like the source format reader, zero-length entries are absent keys. A later
    index remains its actual 1-based ordinal; lookup must not use len(mapping).
    """
    raw, _, _, constants = _container(raw, localization=True)
    return {index: _utf8(raw, offset, length) for index, length, offset in constants if length}


class _Reader:
    def __init__(self, raw, offset, length, label):
        self.raw, self.start, self.pos, self.end, self.label = raw, offset, offset, offset + length, label

    def take(self, count):
        _span(self.pos, count, self.start, self.end, self.label)
        start = self.pos
        self.pos += count
        return self.raw[start:self.pos]

    def number(self, format):
        size = struct.calcsize(format)
        _span(self.pos, size, self.start, self.end, self.label)
        value = struct.unpack_from(format, self.raw, self.pos)[0]
        self.pos += size
        return value


def _schema_size(schema, ancestors=None, depth=0):
    if depth > MAX_DEPTH:
        raise RocoDecodeError("Schema nesting depth exceeds limit")
    if not isinstance(schema, dict) or schema.get("Type") != "EStruct" or not isinstance(schema.get("Properties"), list):
        raise RocoDecodeError("Schema must be an EStruct with a Properties list")
    ancestors = set() if ancestors is None else ancestors
    if id(schema) in ancestors:
        raise RocoDecodeError("Recursive schema is unsupported")
    ancestors.add(id(schema))
    names, extent = set(), 0
    for prop in schema["Properties"]:
        if not isinstance(prop, dict) or not isinstance(prop.get("Name"), str) or not prop["Name"] or prop["Name"] in names:
            raise RocoDecodeError("Invalid or duplicate schema property name")
        names.add(prop["Name"])
        kind, offset, size = prop.get("Type"), prop.get("Offset"), prop.get("Size")
        if kind not in _WIDTHS:
            raise RocoDecodeError("Unsupported property type: " + str(kind))
        if type(offset) is not int or offset < 0 or type(size) is not int or size != _WIDTHS[kind]:
            raise RocoDecodeError("Invalid schema offset or size for " + prop["Name"])
        if prop.get("ArrayDim") is not None and (type(prop["ArrayDim"]) is not int or prop["ArrayDim"] < 0):
            raise RocoDecodeError("Invalid schema ArrayDim")
        extent = max(extent, offset + size)
        if kind == "EStruct":
            _schema_size(prop.get("Struct"), ancestors, depth + 1)
    ancestors.remove(id(schema))
    return extent


class _Decoder:
    def __init__(self, raw, constants, locale, strict, allowed_padding=()):
        self.raw, self.constants, self.strict = raw, constants, strict
        self.locale = {} if locale is None else locale
        if not isinstance(self.locale, dict) or any(type(k) is not int or k <= 0 or not isinstance(v, str) for k, v in self.locale.items()):
            raise RocoDecodeError("Localization must map positive integer indices to strings")
        self.refs, self.missing, self.structs = [], [], []
        self.allowed_padding = frozenset(allowed_padding)

    def constant(self, index, pointer):
        if index <= 0 or index > len(self.constants):
            raise RocoDecodeError(f"Illegal constant index {index} at {pointer}")
        _, length, offset = self.constants[index - 1]
        return _Reader(self.raw, offset, length, "Constant " + str(index) + " " + pointer)

    def value(self, reader, prop, pointer, depth):
        kind = prop["Type"]
        if kind in _PRIMITIVES:
            value = reader.number(_PRIMITIVES[kind])
            return bool(value) if kind == "EBool" else value
        offset = reader.pos
        index = reader.number("<I" if kind == "EString" else "<i")
        if kind == "EString":
            if index == 0:
                return ""
            source = self.constant(index, pointer)
            return _utf8(self.raw, source.start, source.end - source.start)
        if kind == "ELocalizedString":
            if index <= 0:
                raise RocoDecodeError(f"Illegal localization index {index} at {pointer}")
            found = index in self.locale
            reference = {"row_id": None, "json_pointer": pointer, "raw_index": index,
                         "byte_offset": offset, "resolved": found}
            self.refs.append(reference)
            if not found:
                self.missing.append(reference)
                if self.strict:
                    raise RocoDecodeError(f"Missing localization index {index} at {pointer}, byte {offset}")
                return ""
            return self.locale[index]
        nested = self.constant(index, pointer)
        return self.parse_struct(nested, prop["Struct"], pointer, depth + 1)

    def array(self, reader, prop, pointer, depth):
        index = reader.number("<i")
        array = self.constant(index, pointer)
        width = prop["Size"] if prop.get("DynamicArray", False) else 4
        length = array.end - array.start
        if length % width:
            raise RocoDecodeError(f"Array length {length} is not divisible by element width {width} at {pointer}")
        values = [self.value(array, prop, pointer + "/" + str(i), depth) for i in range(length // width)]
        if array.pos != array.end:
            raise RocoDecodeError("Array payload was not fully consumed at " + pointer)
        return values

    def parse_struct(self, reader, schema, pointer, depth=0):
        if depth > MAX_DEPTH:
            raise RocoDecodeError("Struct nesting depth exceeds limit at " + pointer)
        count = len(schema["Properties"])
        flags = reader.take((count + 7) // 8)
        extra_bits = [i for i in range(count, len(flags) * 8) if flags[i // 8] & (1 << (7 - i % 8))]
        ignored = [i for i in extra_bits if depth == 0 and i in self.allowed_padding]
        undefined = [i for i in extra_bits if i not in ignored]
        if undefined and self.strict:
            raise RocoDecodeError("Undefined presence bits at " + pointer + ": " + str(undefined))
        result = {}
        for i, prop in enumerate(schema["Properties"]):
            if not flags[i // 8] & (1 << (7 - i % 8)):
                continue
            child = pointer + "/" + _pointer(prop["Name"])
            if prop.get("DynamicArray", False) or prop.get("ArrayDim") is not None:
                result[prop["Name"]] = self.array(reader, prop, child, depth)
            else:
                result[prop["Name"]] = self.value(reader, prop, child, depth)
        diagnostic = {"row_id": None, "json_pointer": pointer, "offset": reader.start,
                      "length": reader.end - reader.start, "consumed": reader.pos - reader.start,
                      "remaining": reader.end - reader.pos, "undefined_presence_bits": undefined,
                      "ignored_padding_bits": ignored,
                      "schema_name": schema.get("Name")}
        self.structs.append(diagnostic)
        if diagnostic["remaining"] and self.strict:
            raise RocoDecodeError(f"Unconsumed struct bytes at {pointer}: {diagnostic['remaining']}")
        return result


def decode_table(data: bytes, schema: dict, locale: dict[int, str] | None = None,
                 strict: bool = True, *, allowed_top_level_padding_bits=()) -> dict:
    """Decode one compressed table using only explicitly supplied schema/locale.

    References and struct diagnostics use JSON pointers into the returned /rows
    object and preserve the owning row ID even for deeply nested constants.
    BinData-uncompressed is outside this API. The shared magic cannot identify
    the format by itself: this function validates only the compressed layout.
    A caller may supply hash-pinned, observed top-level padding-bit exceptions.
    Only unused positions in the last presence byte are eligible. These bits are
    reported as ignored_padding_bits; the exception never applies to a nested
    struct or relaxes struct consumption, offsets, sizes, indices or bounds.
    """
    raw, footer, entries, constants = _container(data)
    extent = _schema_size(schema)
    schema_diagnostics = []
    if extent != footer["StructSize"]:
        diagnostic = {"kind": "schema_size_mismatch", "schema_size": extent,
                      "footer_struct_size": footer["StructSize"]}
        if strict:
            raise RocoDecodeError(f"Declared schema size {extent} differs from footer struct size {footer['StructSize']}")
        schema_diagnostics.append(diagnostic)
    count = len(schema["Properties"])
    flag_count = (count + 7) // 8
    allowed = tuple(allowed_top_level_padding_bits)
    if any(type(bit) is not int or bit < count or bit >= flag_count * 8 or bit // 8 != flag_count - 1 for bit in allowed):
        raise RocoDecodeError("Allowed padding positions must be unused bits in the final top-level presence byte")
    decoder = _Decoder(raw, constants, locale, strict, allowed)
    rows, locations, skipped = {}, {}, []
    key = schema.get("UniqueKey") or "id"
    for ordinal, length, offset in entries:
        if length == 0:
            skipped.append(ordinal)
            continue
        ref_start, struct_start = len(decoder.refs), len(decoder.structs)
        reader = _Reader(raw, offset, length, "Data row " + str(ordinal))
        row = decoder.parse_struct(reader, schema, "")
        if key not in row or row[key] is None or isinstance(row[key], (dict, list)):
            raise RocoDecodeError(f"Missing or invalid unique key {key!r} in data row {ordinal}")
        ident = str(row[key])
        if ident in rows:
            raise RocoDecodeError("Duplicate row ID " + ident)
        rows[ident] = row
        locations[ident] = {"offset": offset, "length": length, "index": ordinal}
        prefix = "/rows/" + _pointer(ident)
        for item in decoder.refs[ref_start:] + decoder.structs[struct_start:]:
            item["row_id"] = ident
            item["json_pointer"] = prefix + item["json_pointer"]
    return {"rows": rows, "row_locations": locations, "localized_references": decoder.refs,
            "missing_localization": decoder.missing, "struct_diagnostics": decoder.structs,
            "schema_diagnostics": schema_diagnostics, "skipped_empty_entries": skipped,
            "footer": footer}
