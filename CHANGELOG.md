# История версий / Changelog

## 1.4.1

### Русский

- Подстройка скорости использует длительности посылок и пауз даже при ошибках распознавания символов.
- На громком TCI-аудио детектор меньше реагирует на затухающий хвост CW-фильтра, который может скрывать короткие паузы.

### English

- Speed tracking uses mark and gap durations even when symbol recognition fails.
- On loud TCI audio, lingering filter ringing is less likely to obscure short key-up gaps.

## 1.4.0

### Русский

- В панели «Приём CW» появилась галочка «Байесовский декодер». Режим оценивает варианты целого символа по длительности посылок и пауз.
- Галочка по умолчанию выключена. Выбор сохраняется между запусками и применяется при следующем запуске приёма.

### English

- The CW receive panel now has a Bayesian decoder checkbox. The mode scores symbol candidates using measured marks and gaps.
- The checkbox is off by default. The selection is saved and applies the next time reception starts.

## 1.3.2

### Русский

- Декодер удерживает посылку при коротких провалах звука и отбрасывает короткие импульсы.
- Автоматическое усиление TCI опирается на уровень выбранного тона. Подстройка скорости использует несколько последних посылок.

### English

- The decoder keeps marks intact across brief audio dropouts and rejects short impulses.
- TCI automatic gain follows the selected tone. Speed tracking uses several recent marks.

## 1.3.1

### Русский

- Окно по умолчанию выше, а водопад компактнее: область декодированного текста снова занимает несколько строк.

### English

- The default window is taller and the waterfall more compact, so the decoded-text area keeps several lines.

## 1.3.0

### Русский

- Добавлен водопад принимаемого аудио 0–1600 Гц. Водопад прокручивается по времени и работает как для TCI, так и для звуковой карты.
- Прицельная рамка показывает текущий тон декодера и полосу выбранного CW-фильтра: видно, совпадает ли сигнал с настройкой и попадает ли он в фильтр.
- В строке состояния показывается распознанный тон, поэтому автоподстройку и водопад удобно использовать вместе.

### English

- Added a 0–1600 Hz waterfall of the received audio. It scrolls over time and works for both TCI and sound-card input.
- The aiming frame marks the decoder tone and the selected CW filter, so you can see whether the signal matches the setting and stays inside the filter.
- The detected tone is shown in the status line, making the waterfall and auto tone work together.

## 1.2.2

### Русский

- Приём CW по TCI теперь сам подстраивается под реальный тон SDR и уровень аудиопотока. Раньше декодер принимал только тон в пределах ±50 Гц от поля «Тон, Гц» и сигнал громче −34 дБFS, поэтому при других настройках SDR текст не появлялся.
- Добавлен флажок «Авто тон»: частота ключевого тона определяется по спектру и показывается в строке состояния.
- Тихий TCI-поток автоматически усиливается для декодера, а показания уровня остаются в дБFS.
- Технический журнал TCI сохраняется в `%LOCALAPPDATA%\CW_Rig_Desk\tci-audio.log` (заголовки пакетов, тон, уровень, ошибки).

### English

- CW reception over TCI now adapts to the SDR's actual tone and audio level. Previously the decoder accepted only a tone within ±50 Hz of the "Tone, Hz" value and a signal above −34 dBFS, so different SDR settings produced no text.
- Added an "Auto tone" option: the keyed tone frequency is detected from the spectrum and shown in the status line.
- Quiet TCI audio is lifted automatically for the decoder, while the level readout stays in dBFS.
- A technical TCI log is kept at `%LOCALAPPDATA%\CW_Rig_Desk\tci-audio.log` (packet headers, tone, level, errors).

## 1.2.1

### Русский

- Исправлено декодирование CW из аудиопотока TCI 1.4–1.8 (ExpertSDR2): в заголовке этих серверов поле `length` задаёт кадры, а не отдельные отсчёты. Раньше из каждого пакета читалась только половина, и Морзе не декодировался.
- После перезапуска DSP сервера TCI аудиопоток запрашивается заново, а не останавливается с ошибкой «Нет аудио RX по TCI».

### English

- Fixed CW decoding from TCI 1.4–1.8 (ExpertSDR2) audio: those servers put the frame count in `length`, not the number of scalar samples. Previously only half of every packet was used, so CW did not decode.
- After a TCI server DSP restart the audio stream is requested again instead of stopping receive with a "no TCI RX audio" error.

## 1.2.0

### Русский

- «Запустить» принимает звук SDR по TCI и направляет его в декодер Морзе. Виртуальный кабель нужен только при выборе входа Windows.
- Индикатор показывает, когда поступает звук TCI. Если сервер не отдаёт аудио, программа сообщает об этом отдельно от состояния CAT.

### English

- Start RX can feed SDR audio directly to the Morse decoder over TCI. A virtual cable is only needed when using the Windows input.
- The receive status identifies TCI audio and reports a missing audio stream separately from CAT status.

## 1.1.0

### Русский

- В верхней панели можно переключать интерфейс между русским и английским без перезапуска. Выбор сохраняется.
- Переведены настройки, телеметрия CAT, сообщения об ошибках и стандартные названия макросов. Алфавит декодера и пользовательские макросы настраиваются отдельно.

### English

- Switch between Russian and English from the top bar without restarting. The app remembers your choice.
- Equipment settings, CAT telemetry, error messages and default macro names are translated. The decoder alphabet and custom macros are independent of the interface language.

## 1.0.0

### Русский

- Автономный файл `CW_Rig_Desk-1.0.0-windows-x64.exe` со встроенными Python, Tcl/Tk, PortAudio и Hamlib 4.7.2. Запускается двойным щелчком.
- Hamlib загружает список моделей из комплекта, автоматически запускается при подключении CAT и останавливается при отключении.
- Номер версии отображается в окне и в свойствах EXE. Настройки и макросы используются из существующего профиля.
- Обновлено руководство со скриншотами.

### English

- The standalone `CW_Rig_Desk-1.0.0-windows-x64.exe` includes Python, Tcl/Tk, PortAudio and Hamlib 4.7.2. Double-click to launch.
- The included Hamlib supplies the radio list and starts and stops with CAT.
- The window and EXE properties show the same version. Existing settings and macros carry over.
- The illustrated user guide has been updated.
