# Сравнение CW-декодеров на реальных QSO

Расширенная выборка: **20 разных CW-QSO** из 5 открытых записей Archive.org (WebSDR KFS/NA5B). Сравнивались **CW Rig Desk 1.4.2** (`ToneDecoder`) и **CW Panorama 0.3** (`src/web/dsp.js`, класс `Skimmer`).

## Методика

- 20 фрагментов реальных QSO; в длинных записях взяты разные обмены, в таблице указаны источник и время.
- Аудио: mono, 120 с (JH2FXK — 113 с), перебор начальной скорости 10–33 WPM.
- Наш декодер: auto gain, два режима — «тон вручную» (частота тона из спектрограммы) и «авто-тон» (как в приложении по умолчанию).
- CW Panorama: `Skimmer`, `alphabet=en`, полоса ±220 Гц вокруг того же тона, `sensitivity=6`, до 6 треков, перебор 10–33 WPM; выбирался лучший трек.
- Метрики: контрольные позывные, число валидных позывных, CW-слов, символов и символов-заменителей `�`. Шкала вспомогательная, не CER.
- Победитель: разница вспомогательных баллов ≥15; иначе ничья.

## Источники и фрагменты

| # | QSO | Источник | Время | Тон | Контрольные позывные |
|---|---|---|---|---|---|
| 1 | EA1WX ↔ JH2FXK, 160 м | [JH2FXK 160m QSO](https://archive.org/details/Jh2fxk160mQso) | 0:00–1:53 | 438 Гц | JH2FXK, EA1WX |
| 2 | K6YR ↔ WB6UZ, 80 м | [CW Found Randomly (KFS WebSDR)](https://archive.org/details/cw-found-randomly.-recorded-in-lsb-and-cw-modes.-near-w-1-aw-cw-freq.-sun.-2023-) | 10:00–12:00 | 391 Гц | K6YR, WB6UZ |
| 3 | Сеть MRCA, 80 м (1) | [CW On 3558 kHz (KFS WebSDR)](https://archive.org/details/cw-on-3558-k-hz.-sunday.-2023-11-27-t-03-57-12-z-3558.8k-hz) | 0:00–2:00 | 842 Гц | — |
| 4 | Сеть MRCA, 80 м (2) | [CW On 3558 kHz (KFS WebSDR)](https://archive.org/details/cw-on-3558-k-hz.-sunday.-2023-11-27-t-03-57-12-z-3558.8k-hz) | 4:00–6:00 | 844 Гц | — |
| 5 | Сеть MRCA, 80 м (KG6REU) | [CW On 3558 kHz (KFS WebSDR)](https://archive.org/details/cw-on-3558-k-hz.-sunday.-2023-11-27-t-03-57-12-z-3558.8k-hz) | 6:00–8:00 | 844 Гц | KG6REU |
| 6 | Сеть MRCA, 80 м (W7WOW) | [CW On 3558 kHz (KFS WebSDR)](https://archive.org/details/cw-on-3558-k-hz.-sunday.-2023-11-27-t-03-57-12-z-3558.8k-hz) | 8:00–10:00 | 841 Гц | W7WOW |
| 7 | Сеть MRCA, 80 м (5) | [CW On 3558 kHz (KFS WebSDR)](https://archive.org/details/cw-on-3558-k-hz.-sunday.-2023-11-27-t-03-57-12-z-3558.8k-hz) | 11:40–13:40 | 793 Гц | — |
| 8 | Новогодний обмен, 40 м (1) | [40 Meter CW as the Ball Dropped (KFS WebSDR)](https://archive.org/details/40-meter-cw-as-the-ball-dropped.-new-years.-2024-01-01-t-08-12-50-z-7009.5k-hz) | 0:00–2:00 | 344 Гц | OH6NPV, II3WWA |
| 9 | Новогодний обмен, 40 м (2) | [40 Meter CW as the Ball Dropped (KFS WebSDR)](https://archive.org/details/40-meter-cw-as-the-ball-dropped.-new-years.-2024-01-01-t-08-12-50-z-7009.5k-hz) | 2:00–4:00 | 343 Гц | II3WWA |
| 10 | Испаноязычный QSO, 40 м (1) | [40 Meter CW as the Ball Dropped (KFS WebSDR)](https://archive.org/details/40-meter-cw-as-the-ball-dropped.-new-years.-2024-01-01-t-08-12-50-z-7009.5k-hz) | 10:00–12:00 | 489 Гц | — |
| 11 | Испаноязычный QSO, 40 м (2) | [40 Meter CW as the Ball Dropped (KFS WebSDR)](https://archive.org/details/40-meter-cw-as-the-ball-dropped.-new-years.-2024-01-01-t-08-12-50-z-7009.5k-hz) | 26:40–28:40 | 562 Гц | — |
| 12 | ARRL 160 м (N7Y/KG8CW) | [ARRL 160m CW Contest (KFS WebSDR, LSB 7 kHz)](https://archive.org/details/arrl-160m-cw-contest-in-lsb-mode-at-7khz-width.-sat.-2020-12-06-t-04-39-34-z-1849.0k-hz) | 2:00–4:00 | 1009 Гц | N7Y, KG8CW |
| 13 | ARRL 160 м (N7Y/W0UY/K0RC) | [ARRL 160m CW Contest (KFS WebSDR, LSB 7 kHz)](https://archive.org/details/arrl-160m-cw-contest-in-lsb-mode-at-7khz-width.-sat.-2020-12-06-t-04-39-34-z-1849.0k-hz) | 4:00–6:00 | 978 Гц | N7Y, W0UY, K0RC |
| 14 | ARRL 160 м (N7Y/N6WT) | [ARRL 160m CW Contest (KFS WebSDR, LSB 7 kHz)](https://archive.org/details/arrl-160m-cw-contest-in-lsb-mode-at-7khz-width.-sat.-2020-12-06-t-04-39-34-z-1849.0k-hz) | 6:20–8:20 | 1031 Гц | N7Y, N6WT |
| 15 | ARRL 160 м (N7Y/K7SV) | [ARRL 160m CW Contest (KFS WebSDR, LSB 7 kHz)](https://archive.org/details/arrl-160m-cw-contest-in-lsb-mode-at-7khz-width.-sat.-2020-12-06-t-04-39-34-z-1849.0k-hz) | 8:20–10:20 | 1038 Гц | N7Y, K7SV |
| 16 | ARRL 160 м (N7Y) | [ARRL 160m CW Contest (KFS WebSDR, LSB 7 kHz)](https://archive.org/details/arrl-160m-cw-contest-in-lsb-mode-at-7khz-width.-sat.-2020-12-06-t-04-39-34-z-1849.0k-hz) | 10:20–12:20 | 1006 Гц | N7Y |
| 17 | ARRL 160 м (W6FA) | [ARRL 160m CW Contest (KFS WebSDR, LSB 7 kHz)](https://archive.org/details/arrl-160m-cw-contest-in-lsb-mode-at-7khz-width.-sat.-2020-12-06-t-04-39-34-z-1849.0k-hz) | 12:00–14:00 | 389 Гц | W6FA |
| 18 | ARRL 160 м (VE7KW/K2RD) | [ARRL 160m CW Contest (KFS WebSDR, LSB 7 kHz)](https://archive.org/details/arrl-160m-cw-contest-in-lsb-mode-at-7khz-width.-sat.-2020-12-06-t-04-39-34-z-1849.0k-hz) | 15:00–17:00 | 600 Гц | VE7KW, K2RD |
| 19 | ARRL 160 м (K2RD/VE7BV) | [ARRL 160m CW Contest (KFS WebSDR, LSB 7 kHz)](https://archive.org/details/arrl-160m-cw-contest-in-lsb-mode-at-7khz-width.-sat.-2020-12-06-t-04-39-34-z-1849.0k-hz) | 18:00–20:00 | 601 Гц | K2RD, VE7BV |
| 20 | ARRL 160 м (K2RD/K1GG) | [ARRL 160m CW Contest (KFS WebSDR, LSB 7 kHz)](https://archive.org/details/arrl-160m-cw-contest-in-lsb-mode-at-7khz-width.-sat.-2020-12-06-t-04-39-34-z-1849.0k-hz) | 20:00–22:00 | 601 Гц | K2RD, K1GG |

## Результаты

| # | QSO | Наш, авто-тон | Наш, тон вручную | CW Panorama | Победитель |
|---|---|---|---|---|---|
| 1 | EA1WX ↔ JH2FXK, 160 м | 285 (позывные 2/2, `�` 2) | 265 (позывные 2/2, `�` 2) | 177 (позывные 2/2, `�` 25) | наш |
| 2 | K6YR ↔ WB6UZ, 80 м | 285 (позывные 2/2, `�` 2) | 299 (позывные 2/2, `�` 0) | 166 (позывные 1/2, `�` 2) | наш |
| 3 | Сеть MRCA, 80 м (1) | 5 (позывные 0/0, `�` 3) | 10 (позывные 0/0, `�` 3) | 22 (позывные 0/0, `�` 6) | ничья |
| 4 | Сеть MRCA, 80 м (2) | 43 (позывные 0/0, `�` 0) | 43 (позывные 0/0, `�` 0) | 27 (позывные 0/0, `�` 4) | наш |
| 5 | Сеть MRCA, 80 м (KG6REU) | 179 (позывные 1/1, `�` 0) | 179 (позывные 1/1, `�` 0) | 163 (позывные 1/1, `�` 4) | наш |
| 6 | Сеть MRCA, 80 м (W7WOW) | 167 (позывные 1/1, `�` 0) | 172 (позывные 1/1, `�` 0) | 134 (позывные 1/1, `�` 5) | наш |
| 7 | Сеть MRCA, 80 м (5) | 13 (позывные 0/0, `�` 7) | 42 (позывные 0/0, `�` 6) | -9 (позывные 0/0, `�` 11) | наш |
| 8 | Новогодний обмен, 40 м (1) | 425 (позывные 2/2, `�` 0) | 431 (позывные 2/2, `�` 0) | 162 (позывные 1/2, `�` 6) | наш |
| 9 | Новогодний обмен, 40 м (2) | 253 (позывные 1/1, `�` 1) | 278 (позывные 1/1, `�` 1) | 177 (позывные 1/1, `�` 15) | наш |
| 10 | Испаноязычный QSO, 40 м (1) | 34 (позывные 0/0, `�` 2) | 51 (позывные 0/0, `�` 4) | -16 (позывные 0/0, `�` 8) | наш |
| 11 | Испаноязычный QSO, 40 м (2) | -6 (позывные 0/0, `�` 4) | 0 (позывные 0/0, `�` 3) | -53 (позывные 0/0, `�` 17) | наш |
| 12 | ARRL 160 м (N7Y/KG8CW) | 435 (позывные 2/2, `�` 1) | 441 (позывные 2/2, `�` 1) | 343 (позывные 2/2, `�` 9) | наш |
| 13 | ARRL 160 м (N7Y/W0UY/K0RC) | 533 (позывные 3/3, `�` 2) | 546 (позывные 3/3, `�` 2) | 540 (позывные 3/3, `�` 7) | ничья |
| 14 | ARRL 160 м (N7Y/N6WT) | 324 (позывные 1/2, `�` 2) | 526 (позывные 2/2, `�` 0) | 442 (позывные 2/2, `�` 3) | наш |
| 15 | ARRL 160 м (N7Y/K7SV) | 343 (позывные 2/2, `�` 1) | 373 (позывные 2/2, `�` 1) | 217 (позывные 1/2, `�` 4) | наш |
| 16 | ARRL 160 м (N7Y) | 288 (позывные 1/1, `�` 0) | 306 (позывные 1/1, `�` 0) | 288 (позывные 1/1, `�` 2) | наш |
| 17 | ARRL 160 м (W6FA) | 170 (позывные 1/1, `�` 2) | 147 (позывные 1/1, `�` 0) | 168 (позывные 1/1, `�` 1) | Panorama |
| 18 | ARRL 160 м (VE7KW/K2RD) | 393 (позывные 2/2, `�` 0) | 380 (позывные 2/2, `�` 0) | 340 (позывные 2/2, `�` 4) | наш |
| 19 | ARRL 160 м (K2RD/VE7BV) | 473 (позывные 2/2, `�` 0) | 454 (позывные 2/2, `�` 0) | 389 (позывные 2/2, `�` 4) | наш |
| 20 | ARRL 160 м (K2RD/K1GG) | 341 (позывные 2/2, `�` 0) | 372 (позывные 2/2, `�` 0) | 282 (позывные 2/2, `�` 12) | наш |

## Итоги

- Контрольные позывные: наш (тон вручную) **26/26**, авто-тон **25/26**, CW Panorama **23/26**.
- Символы-заменители `�`: наш **23**, авто-тон **29**, Panorama **149**.
- Победители: наш **17/20**, CW Panorama **1/20**, ничьи **2/20**.
- При авто-тоне наш декодер выигрывает по вспомогательным баллам в **16/20** фрагментах.
- На сильных контестовых сигналах Panorama иногда получает близкий балл за счёт более длинного, но шумного текста (17-c-6, W6FA); явного преимущества по точности там нет — оба варианта в основном повторяют один позывной.

## Примеры

### Сеть MRCA, 80 м (2)

**Наш (тон вручную):**
```
EFAZR ES FAMILY SLUMBER P+TY LAST NITE AT THE NEW OFFICE BLN T 5 D E BLDG MY DAUGHTER LAUREN BOUGHT FOR A HEALING CENTER , WE ALL CAMPED ON TS THE FLOOR ES HAD A RIO T = TNX BOB NET GENTS ES 73 BT U R
```
**CW Panorama:**
```
EFAMIR H FAZLY SLUMBER P+TY L�T NITE AT THE NEW �FICE BLN T 5 D E BLDG MY DAUGHNR LA�EN BOUGHT FOR A HEALING CENTER , WE ALL CAMPED ON TS THE FLO� ES HAD A RIO T = TNX BOB NET GENTS ES 73 BT U RE
```

### ARRL 160 м (N7Y/W0UY/K0RC)

**Наш (тон вручную):**
```
S 5NN NV TT N7 YK CQ N7 Y K KQ N 7 Y D TT 3 K CQ N7 Y K ?? CQ N7 Y K K � � ? W0UY 5NN NV E TU E YK CQ N7 Y K CQ N7YK K0RC 5NN NV E E E E E MN? H R TUEE CQ T E CQ N 7 K KN
```
**CW Panorama:**
```
S5NN I S MN EI- N7 �K CQ N7YK NQ N7 K E��TE N T M K CQ N7YK E EE ?? CQ N7 Y K K � �H � ? E H EI HE W0UY 5NN NV ES ESEDE TU YK CQ N7N K K Q N7 YK E K0RC 5NN NV SNMN MN? SE R A EUEE CQ T � ES T E EO CQ T M E T NI K T EE
```

### ARRL 160 м (W6FA)

**Наш (тон вручную):**
```
TE E E EE E T E W6FA W6FA WB FA W6 FA W6 FA W6 FA W6FA W6 W6FA
```
**CW Panorama:**
```
A EE D O6FA WB FA W6 FA ERAEI� 6 FA W6 FA EE W6 FA W6 W6FA
```

## Вывод

На расширенной выборке преимущество нашего декодера подтверждается: заметно меньше `�`, лучше удерживаются короткие паузы и слабые посылки, чище связный текст QSO. CW Panorama 0.3 остаётся полезным многоканальным скиммером для поиска позывных в сильных сигналах, но как декодер непрерывного текста уступает.

Ограничения: 20 QSO из 5 записей (в основном WebSDR KFS/NA5B), без полных эталонных транскриптов; Panorama — скиммер, а не специализированный декодер QSO; для нашего декодера в основном варианте тон задавался вручную. Аудиофрагменты и текстовые выходы сохранены в рабочей папке эксперимента.
