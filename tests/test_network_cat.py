"""Protocol-level tests against local TCP and WebSocket endpoints."""

from contextlib import contextmanager
import queue
import socketserver
import threading
import unittest

from websockets.sync.server import serve

from cw_rig_desk.network_cat import CommandError, Hamlib, NetworkSession, Tci


class HamlibHandler(socketserver.StreamRequestHandler):
    def handle(self):
        for request in self.rfile:
            command = request.decode("ascii").strip().removeprefix("+\\")
            name, _, arguments = command.partition(" ")
            self.server.commands.append(command)
            fields = []
            result = 0
            if name == "get_freq":
                fields = [f"Frequency: {self.server.frequency}"]
            elif name == "set_freq":
                self.server.frequency = int(arguments)
            elif name == "get_mode":
                fields = [f"Mode: {self.server.mode}", "Passband: 2400"]
            elif name == "set_mode":
                self.server.mode = arguments.split()[0]
            elif name == "get_ptt":
                fields = [f"PTT: {self.server.ptt}"]
            elif name == "set_ptt":
                self.server.ptt = int(arguments)
                if self.server.ptt and self.server.drop_ack:
                    return
            elif name == "get_split_vfo":
                fields = [f"Split: {self.server.split}", "TX VFO: VFOB"]
            elif name == "set_split_vfo":
                self.server.split = int(arguments.split()[0])
            elif name == "get_vfo":
                fields = [f"VFO: {self.server.vfo}"]
            elif name == "set_vfo":
                self.server.vfo = arguments
            elif name == "get_level":
                return_value = {"STRENGTH": -17, "SWR": 1.25, "RFPOWER_METER_WATTS": 6.5, "ALC": .15}
                value = return_value[arguments]
                fields = [f"{arguments}: {value}" if arguments == "ALC" else str(value)]
            else:
                result = -11
            response = ("\n".join([f"{name}: {arguments}", *fields, f"RPRT {result}"]) + "\n").encode()
            # A real TCP reply can split a field or the final status line across reads.
            self.wfile.write(response[:9])
            self.wfile.write(response[9:])


@contextmanager
def rigctld_fixture():
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), HamlibHandler) as server:
        server.daemon_threads = True
        server.frequency, server.mode, server.ptt = 7030000, "USB", 0
        server.vfo, server.split, server.drop_ack = "VFOA", 0, False
        server.commands = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(2)


@contextmanager
def tci_fixture():
    commands = []
    state = {"vfo0": 7030000, "vfo1": 7041000, "modulation": "USB", "trx": "false", "split_enable": "false"}

    def peer(ws):
        ws.send("protocol:ExpertSDR3,2.0;device:SunSDR;receive_only:false;"
                "modulations_list:USB,DIGU,CW;vfo:1,0,18100000;ready;")
        for message in ws:
            for command in message.split(";"):
                if not command:
                    continue
                commands.append(command)
                name, _, payload = command.partition(":")
                args = payload.split(",")
                if name == "vfo":
                    rx, channel, *new = args
                    key = "vfo" + channel
                    if new:
                        state[key] = int(new[0])
                    ws.send(f"vfo:{rx},{channel},{state[key]};")
                elif name in ("modulation", "trx", "split_enable"):
                    receiver, *new = args
                    if new:
                        state[name] = new[0]
                    ws.send(f"{name}:{receiver},{state[name]};")
                elif name == "rx_sensors_enable":
                    ws.send("rx_channel_sensors:1,0,-20;rx_channel_sensors:0,0,-80.5;")
                elif name == "tx_sensors_enable":
                    ws.send("tx_sensors:0,-6,4.5,6.0,1.4;")

    with serve(peer, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"ws://127.0.0.1:{server.socket.getsockname()[1]}", commands, state
        finally:
            server.shutdown()
            thread.join(2)


class NetworkCatTests(unittest.TestCase):
    def test_hamlib_frequency_modes_split_and_meters(self):
        with rigctld_fixture() as server:
            readings = {}
            rig = Hamlib(*server.server_address, readings.__setitem__, lambda *_: None)
            rig.open()
            self.addCleanup(rig.close)
            try:
                rig.init_state(threading.Event())
                self.assertEqual(readings["frequency"], 7030000)
                rig.write("frequency", 14060000)
                self.assertEqual(readings["frequency"], 14060000)
                rig.write("mode", "U-D")
                self.assertEqual(readings["mode"], ("U-D", "2400 Гц"))
                rig.write("vfo", 1)
                self.assertEqual(readings["vfo"], "VFOB")
                rig.write("split", True)
                self.assertEqual(readings["split"], "Вкл")
                self.assertIn("set_split_vfo 1 VFOA", server.commands)
                with self.assertRaises(CommandError):
                    rig.check_tx()
                rig.write("split", False)
                rig.check_tx()
                for meter in rig.meters:
                    rig.read_meter(meter)
                self.assertEqual(readings["swr_live"], ("1.25:1", 1.25))
                self.assertEqual(readings["po"], "6.5 Вт")
                self.assertEqual(readings["signal"], "-17 дБ от S9")
                with self.assertRaises(CommandError):
                    rig.request("not_supported")
            finally:
                rig.close()

    def test_hamlib_keyed_recovers_after_failed_ptt_ack(self):
        with rigctld_fixture() as server:
            session = NetworkSession(
                lambda pub, log: Hamlib(*server.server_address, pub, log), "test", lambda *_: None
            )
            session.driver.open()
            try:
                cancel = threading.Event()
                with session.keyed(cancel) as enabled:
                    self.assertTrue(enabled)
                    self.assertEqual(server.ptt, 1)
                self.assertEqual(server.ptt, 0)
                server.drop_ack = True
                with self.assertRaises(ConnectionError):
                    with session.keyed(cancel):
                        self.fail("audio must not start without PTT acknowledgement")
                self.assertEqual(server.ptt, 0)
                cancel.set()
                with session.keyed(cancel) as enabled:
                    self.assertFalse(enabled)
                self.assertEqual(server.commands.count("set_ptt 1"), 2)
            finally:
                session.driver.close()

    def test_tci_request_confirmation_receiver_and_ptt(self):
        with tci_fixture() as (url, commands, state):
            readings = {}
            rig = Tci(url, 0, readings.__setitem__, lambda *_: None)
            rig.open()
            try:
                rig.init_state(threading.Event())
                rig.wait_for(lambda: "swr_live" in readings)
                self.assertEqual(readings["frequency"], 7030000)
                self.assertEqual(readings["signal"], "-80.5 дБм")
                self.assertEqual(readings["swr_live"], ("1.40:1", 1.4))
                rig.write("frequency", 14060000)
                self.assertEqual(readings["frequency"], 14060000)
                rig.write("mode", "U-D")
                self.assertEqual(readings["mode"], ("U-D", None))
                rig.write("vfo", 1)
                self.assertEqual(readings["frequency"], 7041000)
                with self.assertRaises(CommandError):
                    rig.check_tx()
                rig.write("vfo", 0)
                rig.check_tx()
                rig.ptt(True)
                self.assertEqual(state["trx"], "true")
                self.assertIn("trx:0,true,micpc", commands)
                rig.ptt(False)
                self.assertEqual(readings["ptt"], "RX")
            finally:
                rig.close()

    def test_session_dispatch(self):
        with rigctld_fixture() as server:
            events = queue.Queue()
            session = NetworkSession(
                lambda pub, log: Hamlib(*server.server_address, pub, log), "test",
                lambda name, data: events.put((name, data))
            )
            stop = threading.Event()
            thread = threading.Thread(target=session.run, args=(stop,), daemon=True)
            thread.start()
            try:
                session.jobs.put(("frequency", (10116000,)))
                for _ in range(100):
                    event, value = events.get(timeout=2)
                    if event == "cat_write_done":
                        self.assertIsNone(value)
                        break
                else:
                    self.fail("missing CAT completion")
                self.assertEqual(session.values["frequency"], 10116000)
            finally:
                stop.set()
                thread.join(2)
                self.assertFalse(thread.is_alive())
