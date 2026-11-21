from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest import TestCase, skipUnless
import os

from cw_rig_desk.hamlib_runtime import (
    AUTO, ManagedHamlib, catalog, command_line, parse_models, resolve_serial,
)


DEVICE = SimpleNamespace


class ModelTests(TestCase):
    def test_catalog_is_searchable_and_omits_legacy_bridges(self):
        models = parse_models(
            " Rig #  Mfg                    Model                   Version         Status      Macro\n"
            "     2  Hamlib                 NET rigctl              20240418.0      Stable      RIG_MODEL_NETRIGCTL\n"
            "     1  Hamlib                 Dummy                   20240709.0      Stable      RIG_MODEL_DUMMY\n"
            "  1036  Yaesu                  FT-891                  20241225.0      Stable      RIG_MODEL_FT891\n"
            "  3073  Icom                   IC-7300                 20250517.14     Stable      RIG_MODEL_IC7300\n"
        )
        self.assertEqual([m.id for m in models], [1, 3073, 1036])
        self.assertEqual(models[2].label, "Yaesu FT-891 [1036]")

    def test_port_auto_detects_only_unambiguous_usb(self):
        usb = DEVICE(device="COM18", vid=0x10C4, description="USB UART")
        builtin = DEVICE(device="COM2", vid=None)
        second = DEVICE(device="COM37", vid=0x0403)
        self.assertEqual(resolve_serial(1036, AUTO, [builtin, usb]), "COM18")
        self.assertEqual(resolve_serial(1036, "COM37", [usb, second]), "COM37")
        self.assertIsNone(resolve_serial(1, AUTO, []))
        with self.assertRaises(ValueError):
            resolve_serial(1036, AUTO, [usb, second])
        with self.assertRaises(ValueError):
            resolve_serial(1036, "COM99", [usb])
        with self.assertRaises(ValueError):
            resolve_serial(1036, AUTO, [builtin])

    def test_ft891_uses_enhanced_usb_port(self):
        enhanced = DEVICE(device="COM5", vid=0x10C4, description="Silicon Labs Enhanced COM Port")
        standard = DEVICE(device="COM6", vid=0x10C4, description="Silicon Labs Standard COM Port")
        self.assertEqual(resolve_serial(1036, AUTO, [standard, enhanced]), "COM5")
        with self.assertRaises(ValueError):
            resolve_serial(3073, AUTO, [standard, enhanced])

    def test_auto_baud_and_port_flags(self):
        args = command_line("rigctld.exe", 1036, "COM18", None, 24532)
        self.assertEqual(args[-1], r"\\.\COM18" if os.name == "nt" else "COM18")
        self.assertEqual(args[args.index("-T")+1], "127.0.0.1")
        self.assertNotIn("-s", args)
        self.assertEqual(command_line("rigctld.exe", 1036, "COM18", 38400, 24532)[-2:], ["-s", "38400"])


@skipUnless(os.environ.get("CW_TEST_RIGCTL_DIR"), "requires portable Hamlib")
class ManagedHamlibTests(TestCase):
    def test_real_hamlib_dummy_and_automatic_shutdown(self):
        bin_dir = Path(os.environ["CW_TEST_RIGCTL_DIR"])
        models = catalog(bin_dir)
        ids = {model.id for model in models}
        self.assertTrue({1, 1036, 2037, 3073}.issubset(ids))
        readings = {}
        stop = Event()
        rig = ManagedHamlib(bin_dir / "rigctld.exe", 1, None, None,
                            readings.__setitem__, lambda *_: None, stop)
        try:
            rig.open()
            process = rig.child
            rig.init_state(stop)
            rig.write("frequency", 14060000)
            rig.write("mode", "USB")
            rig.check_tx()
            rig.ptt(True)
            self.assertTrue(rig.get_ptt())
            rig.recover()
            rig.ptt(False)
            self.assertFalse(rig.get_ptt())
            self.assertEqual(readings["frequency"], 14060000)
            self.assertIs(rig.child, process)
        finally:
            rig.close()
        self.assertIsNotNone(process.poll())
