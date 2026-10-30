"""Small independent binary fixtures for the documented compressed Roco format."""
import importlib.util
from pathlib import Path
import struct
import unittest


MODULE = Path(__file__).resolve().parents[1] / "tools" / "roco_raw.py"
MAGIC = struct.pack("<I", 0x53DF17BE)


def table_fixture(rows, constants=(), struct_size=4):
    data = b"".join(rows)
    pool = b"".join(constants)
    data_table_at = 4 + len(data) + len(pool)
    result = bytearray(MAGIC + data + pool)
    offset = 4
    for index, row in enumerate(rows, 1):
        result += struct.pack("<Iiq", index, len(row), offset)
        offset += len(row)
    constants_table_at = len(result)
    offset = 4 + len(data)
    for index, item in enumerate(constants, 1):
        result += struct.pack("<Iiq", index, len(item), offset)
        offset += len(item)
    result += struct.pack("<qqiqqiqiqq", 4, len(data), len(rows), struct_size,
                          data_table_at, len(rows), constants_table_at, len(constants),
                          4 + len(data), len(pool))
    return bytes(result)


def localization_fixture(strings):
    result = bytearray(MAGIC + b"".join(strings))
    table_at = len(result)
    offset = 4
    for index, item in enumerate(strings, 1):
        result += struct.pack("<Iiq", index, len(item), offset)
        offset += len(item)
    result += struct.pack("<qiqq", table_at, len(strings), 4, table_at - 4)
    return bytes(result)


def prop(name, kind, offset, size=4, **extra):
    return {"Name": name, "Type": kind, "Offset": offset, "Size": size, **extra}


def schema(*properties):
    return {"Name": "FIXTURE", "Type": "EStruct", "UniqueKey": "id", "Properties": list(properties)}


ID = prop("id", "EUint32", 0)
ID_SCHEMA = schema(ID)


class RocoRawTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if MODULE.exists():
            spec = importlib.util.spec_from_file_location("roco_raw", MODULE)
            cls.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.mod)

    def setUp(self):
        self.assertTrue(MODULE.exists(), "offline decoder has not been implemented")

    def test_nested_localization_dynamic_int64_and_absent_fields(self):
        child = schema(prop("name", "EString", 0), prop("reply", "ELocalizedString", 4),
                       prop("active", "EBool", 8, size=1))
        model = schema(ID, prop("title", "ELocalizedString", 4),
                       prop("child", "EStruct", 8, Struct=child),
                       prop("numbers", "EInt64", 12, size=8, DynamicArray=True),
                       prop("absent", "EString", 20))
        nested = b"\xe0" + struct.pack("<IiB", 1, 3, 0)
        raw = table_fixture([b"\xf0" + struct.pack("<Iiii", 7, 2, 3, 4)],
                            ["原始".encode(), b"unused", nested, struct.pack("<qq", -2, 2**40)], 24)
        out = self.mod.decode_table(raw, model, {2: "标题", 3: "回复"})
        self.assertEqual(out["rows"], {"7": {"id": 7, "title": "标题",
                         "child": {"name": "原始", "reply": "回复", "active": False},
                         "numbers": [-2, 2**40]}})
        self.assertEqual([(r["row_id"], r["json_pointer"], r["raw_index"])
                          for r in out["localized_references"]],
                         [("7", "/rows/7/title", 2), ("7", "/rows/7/child/reply", 3)])
        self.assertEqual(len(out["struct_diagnostics"]), 2)
        self.assertTrue(all(d["remaining"] == 0 for d in out["struct_diagnostics"]))
        self.assertEqual(out["row_locations"], {"7": {"offset": 4, "length": 17, "index": 1}})

    def test_fixed_struct_array_uses_stored_pointer_count_without_padding(self):
        model = schema(ID, prop("items", "EStruct", 4, ArrayDim=5, Struct=ID_SCHEMA))
        raw = table_fixture([b"\xc0" + struct.pack("<Ii", 7, 3)],
                            [b"\x80" + struct.pack("<I", 11), b"\x80" + struct.pack("<I", 12),
                             struct.pack("<ii", 1, 2)], 8)
        self.assertEqual(self.mod.decode_table(raw, model)["rows"]["7"]["items"], [{"id": 11}, {"id": 12}])

    def test_localization_indices_keep_gaps_and_lookup_by_key(self):
        loc = self.mod.decode_localization(localization_fixture(["你好".encode(), b"", b"last"]))
        self.assertEqual(loc, {1: "你好", 3: "last"})
        model = schema(ID, prop("text", "ELocalizedString", 4))
        raw = table_fixture([b"\xc0" + struct.pack("<Ii", 7, 3)], struct_size=8)
        self.assertEqual(self.mod.decode_table(raw, model, loc)["rows"]["7"]["text"], "last")

    def test_missing_localization_is_strict_error_or_explicit_diagnostic(self):
        model = schema(ID, prop("text", "ELocalizedString", 4))
        raw = table_fixture([b"\xc0" + struct.pack("<Ii", 7, 2)], struct_size=8)
        with self.assertRaisesRegex(ValueError, "localization"):
            self.mod.decode_table(raw, model, {})
        out = self.mod.decode_table(raw, model, {}, strict=False)
        self.assertEqual(out["rows"]["7"]["text"], "")
        self.assertEqual(out["missing_localization"][0]["raw_index"], 2)
        self.assertEqual(out["missing_localization"][0]["row_id"], "7")

    def test_constant_zero_is_valid_only_for_estring(self):
        model = schema(ID, prop("text", "EString", 4))
        raw = table_fixture([b"\xc0" + struct.pack("<II", 7, 0)], struct_size=8)
        self.assertEqual(self.mod.decode_table(raw, model)["rows"]["7"]["text"], "")
        for bad in [prop("child", "EStruct", 4, Struct=ID_SCHEMA),
                    prop("text", "ELocalizedString", 4),
                    prop("values", "EInt32", 4, DynamicArray=True)]:
            for strict in [True, False]:
                with self.subTest(kind=bad["Type"], strict=strict):
                    with self.assertRaisesRegex(ValueError, "index"):
                        self.mod.decode_table(raw, schema(ID, bad), {}, strict=strict)

    def test_schema_size_mismatch_only_allowed_with_diagnostic(self):
        raw = table_fixture([b"\x80" + struct.pack("<I", 7)], struct_size=8)
        with self.assertRaisesRegex(ValueError, "schema.*size"):
            self.mod.decode_table(raw, ID_SCHEMA)
        out = self.mod.decode_table(raw, ID_SCHEMA, strict=False)
        self.assertEqual(out["schema_diagnostics"][0]["kind"], "schema_size_mismatch")

    def test_unknown_presence_bits_and_unconsumed_bytes_never_silent(self):
        raw = table_fixture([b"\x81" + struct.pack("<I", 7) + b"extra"])
        with self.assertRaisesRegex(ValueError, "presence"):
            self.mod.decode_table(raw, ID_SCHEMA)
        out = self.mod.decode_table(raw, ID_SCHEMA, strict=False)
        diag = out["struct_diagnostics"][0]
        self.assertEqual(diag["remaining"], 5)
        self.assertEqual(diag["undefined_presence_bits"], [7])

    def test_explicit_top_padding_exception_is_reported_without_weakening_strict(self):
        raw = table_fixture([b"\x81" + struct.pack("<I", 7)])
        out = self.mod.decode_table(raw, ID_SCHEMA, allowed_top_level_padding_bits=(7,))
        self.assertEqual(out["rows"], {"7": {"id": 7}})
        self.assertEqual(out["struct_diagnostics"][0]["ignored_padding_bits"], [7])
        self.assertEqual(out["struct_diagnostics"][0]["undefined_presence_bits"], [])
        for illegal in [(0,), (8,)]:
            with self.assertRaisesRegex(ValueError, "padding"):
                self.mod.decode_table(raw, ID_SCHEMA, allowed_top_level_padding_bits=illegal)
        extra = table_fixture([b"\x81" + struct.pack("<I", 7) + b"x"])
        with self.assertRaisesRegex(ValueError, "consum"):
            self.mod.decode_table(extra, ID_SCHEMA, allowed_top_level_padding_bits=(7,))

    def test_top_padding_exception_does_not_apply_to_nested_struct(self):
        model = schema(ID, prop("child", "EStruct", 4, Struct=ID_SCHEMA))
        raw = table_fixture([b"\xc1" + struct.pack("<Ii", 7, 1)],
                            [b"\x81" + struct.pack("<I", 9)], 8)
        with self.assertRaisesRegex(ValueError, "presence.*child"):
            self.mod.decode_table(raw, model, allowed_top_level_padding_bits=(7,))

    def test_nested_trailing_bytes_detected_and_nested_bounds_always_enforced(self):
        model = schema(ID, prop("child", "EStruct", 4, Struct=ID_SCHEMA))
        row = b"\xc0" + struct.pack("<Ii", 7, 1)
        extra = table_fixture([row], [b"\x80" + struct.pack("<I", 9) + b"x"], 8)
        with self.assertRaisesRegex(ValueError, "consum"):
            self.mod.decode_table(extra, model)
        out = self.mod.decode_table(extra, model, strict=False)
        self.assertEqual(out["struct_diagnostics"][0]["json_pointer"], "/rows/7/child")
        self.assertEqual(out["struct_diagnostics"][0]["remaining"], 1)
        short = table_fixture([row], [b"\x80\x01\x00\x00"], 8)
        for strict in [True, False]:
            with self.assertRaisesRegex(ValueError, "bounds"):
                self.mod.decode_table(short, model, strict=strict)

    def test_array_payload_length_must_be_divisible_by_element_width(self):
        model = schema(ID, prop("values", "EInt32", 4, DynamicArray=True))
        raw = table_fixture([b"\xc0" + struct.pack("<Ii", 7, 1)], [b"abc"], 8)
        for strict in [True, False]:
            with self.assertRaisesRegex(ValueError, "divisible"):
                self.mod.decode_table(raw, model, strict=strict)

    def test_duplicate_and_absent_row_ids_rejected(self):
        row = b"\x80" + struct.pack("<I", 7)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.mod.decode_table(table_fixture([row, row]), ID_SCHEMA)
        with self.assertRaisesRegex(ValueError, "unique key"):
            self.mod.decode_table(table_fixture([b"\x00"]), ID_SCHEMA)

    def test_magic_counts_and_out_of_section_offsets_rejected_in_all_modes(self):
        original = table_fixture([b"\x80" + struct.pack("<I", 7)])
        mutations = []
        bad = bytearray(original); bad[0] = 0; mutations.append((bad, "magic"))
        bad = bytearray(original); struct.pack_into("<i", bad, len(bad) - 68 + 16, 2); mutations.append((bad, "count"))
        bad = bytearray(original); struct.pack_into("<q", bad, 9 + 8, 0); mutations.append((bad, "bounds"))
        bad = bytearray(original); struct.pack_into("<q", bad, len(bad) - 68 + 28, len(bad)); mutations.append((bad, "bounds"))
        for bad, message in mutations:
            for strict in [True, False]:
                with self.subTest(error=message, strict=strict):
                    with self.assertRaisesRegex(ValueError, message):
                        self.mod.decode_table(bytes(bad), ID_SCHEMA, strict=strict)

    def test_constant_index_outside_table_rejected_in_permissive_mode(self):
        model = schema(ID, prop("text", "EString", 4))
        raw = table_fixture([b"\xc0" + struct.pack("<II", 7, 2)], [b"one"], 8)
        with self.assertRaisesRegex(ValueError, "index"):
            self.mod.decode_table(raw, model, strict=False)

    def test_negative_integer_large_uint64_float_and_boolean_wire_values(self):
        model = schema(ID, prop("negative", "EInt32", 4), prop("large", "EUint64", 8, size=8),
                       prop("fraction", "EFloat", 16), prop("enabled", "EBool", 20, size=1))
        raw = table_fixture([b"\xf8" + struct.pack("<IiQfB", 7, -123, 2**63 + 5, 1.5, 2)], struct_size=21)
        self.assertEqual(self.mod.decode_table(raw, model)["rows"]["7"],
                         {"id": 7, "negative": -123, "large": 2**63 + 5, "fraction": 1.5, "enabled": True})

    def test_uncompressed_bindata_layout_is_not_accepted_as_compressed(self):
        payload = struct.pack("<IIII", 1, 0, 2, 0)
        raw = MAGIC + payload + struct.pack("<qqiqqiqq", 4, len(payload), 2, 8, 20, 0, 20, 0)
        for strict in [True, False]:
            with self.assertRaises(ValueError):
                self.mod.decode_table(raw, ID_SCHEMA, strict=strict)

    def test_invalid_utf8_and_constant_metadata_are_not_permissive(self):
        model = schema(ID, prop("text", "EString", 4))
        raw = table_fixture([b"\xc0" + struct.pack("<II", 7, 1)], [b"\xff"], 8)
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            self.mod.decode_table(raw, model, strict=False)
        raw = bytearray(localization_fixture([b"one", b"two"]))
        table_at = struct.unpack_from("<q", raw, len(raw) - 28)[0]
        struct.pack_into("<I", raw, table_at + 16, 1)
        with self.assertRaisesRegex(ValueError, "index"):
            self.mod.decode_localization(raw)

    def test_recursive_schema_and_invalid_locale_mapping_rejected(self):
        recursive = schema(ID)
        recursive["Properties"].append(prop("child", "EStruct", 4, Struct=recursive))
        raw = table_fixture([b"\x80" + struct.pack("<I", 7)], struct_size=8)
        with self.assertRaisesRegex(ValueError, "Recursive schema"):
            self.mod.decode_table(raw, recursive)
        raw = table_fixture([b"\x80" + struct.pack("<I", 7)])
        with self.assertRaisesRegex(ValueError, "Localization"):
            self.mod.decode_table(raw, ID_SCHEMA, [])


if __name__ == "__main__":
    unittest.main()
