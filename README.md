# CW Rig Desk

[Русский](README.ru.md) · English · [Illustrated user guide (PDF, Russian)](docs/CW_Rig_Desk_User_Guide_RU.pdf)

Windows desktop workstation for receiving, decoding and transmitting Morse code. A radio profile controls the rig, while Windows audio devices carry the received signal and transmit tones. The app includes Russian and Latin decoding, CW filters, HF presets, telemetry and editable macros. It is the desktop successor to G90 CW.

| Connection | Typical equipment | How audio is routed |
| --- | --- | --- |
| Direct Xiegu G90 CI-V | G90/G90S with DE-19 | DE-19 USB audio and ACC |
| Hamlib rigctld | Yaesu FT-891, Icom IC-7300, Kenwood TS-590SG and other [Hamlib backends](https://github.com/Hamlib/Hamlib/wiki/Supported-Radios) | Rig USB audio or a separate audio interface |
| TCI over WebSocket | ExpertSDR3 with a SunSDR radio and compatible TCI servers | Windows sound device or virtual audio routing. TCI is used for control and telemetry. |

Frequency, mode, bands, VFO/channel, split and PTT follow the selected profile. Meter readings and optional commands depend on the device, server and firmware. Models listed under Hamlib are examples from Hamlib's supported-rig list. Hardware operation has yet to be verified for this release.

![CW Rig Desk main window with demo readings](docs/main-window.png)

## Quick start

1. Install Python 3.12 or 3.13 for Windows with Tcl/Tk. Extract the archive or clone the repository.
2. Run `start_windows.bat`. It creates a local environment and installs dependencies at first launch. You can also run `python -m cw_rig_desk` after installing `requirements.txt`.
3. Open **Оборудование** (Equipment). Select **Вход RX** (RX input), **Выход TX** (TX output) and **Интерфейс CAT** (CAT interface).
4. Use **Подключить CAT** (Connect CAT). Turn the tuning knob and verify that the frequency follows. Select a CW tone and click **Запустить** (Start). **Демо** runs the decoder on a generated signal with no hardware.
5. To send, select the radio's upper-sideband audio/data mode and route the selected playback device to the radio input. Start at low power into a suitable dummy load. Enable **Разрешить TX**, then click **Передать** (Send) or a macro. **Esc** stops the transmission. The app sends keyed audio tones under PTT in USB or upper-sideband data mode. The same transmit path is used for typed text and macros.

## Connect a radio

### Hamlib

Install [Hamlib](https://github.com/Hamlib/Hamlib/releases) separately. Find the exact model ID with `rigctl.exe -l`. Close other programs that directly own the COM port. In PowerShell, run a command like this, substituting the CAT port and the speed configured on your radio:

```powershell
rigctld.exe -m 1036 -r COM5 -s 38400 -P RIG -T 127.0.0.1 -t 4532
```

In this example, **1036** is the Yaesu FT-891. **3073** is the Icom IC-7300 and **2037** the Kenwood TS-590SG. Use the actual model ID for your rig. Do not pass `-o` (rigctld VFO mode). Use the loopback address for a local server. Choose **Hamlib · rigctld**, host `127.0.0.1`, port `4532`, and set up the rig's audio separately. For example, an FT-891 station uses a separate audio interface connected to the radio's DATA port.

### TCI

Start the SDR and enable TCI in ExpertSDR3. Use the endpoint shown in its settings, for example `ws://127.0.0.1:40001`. Select **TCI · WebSocket** and receiver **0** (first) or **1** (second). CW Rig Desk reads the server's state and follows its updates. VFO A/B selects the channel managed by this app for the chosen receiver.

Route the SDR's receive audio to **Вход RX** using a sound device or a virtual audio cable. For TX, route the app's selected **Выход TX** to **Mic PC** in ExpertSDR. The app requests that source explicitly over TCI. Select USB or DIGU and channel A with SPLIT off. This desktop release uses Windows sound devices for audio. TCI binary audio streams and the native TCI CW keyer are separate features that are outside this implementation.

### Direct G90

Choose **Xiegu G90 · CI-V**. Connect DE-19 ACC to the G90 rear ACC port and DE-19 CIV to the COMM port on the G90 display head. Choose its COM port and CI-V address **70** or **88**. Use DE-19 audio devices and U-D on the G90. The program can import existing G90 CW settings on first start.

## Development

```sh
python -m pip install -r requirements.txt -r requirements-test.txt
python -m unittest discover -s tests -v
```

The automated tests use local TCP and WebSocket simulators and synthetic CW audio. GitHub Actions runs them on Windows with Python 3.12 and 3.13 after the project is pushed.

References for the connection design: [WSJT-X setup guide](https://wsjt.sourceforge.io/wsjtx-main_en.html) · [FT8CN](https://github.com/N0BOY/FT8CN) · [Hamlib rigctld protocol](https://manpages.debian.org/trixie/libhamlib-utils/rigctld.1.en.html) · [ExpertSDR TCI specification](https://github.com/ExpertSDR3/TCI).
