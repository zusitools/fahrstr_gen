#!/bin/sh
ZUSI3_DATAPATH=. ../fahrstr_gen.py --modus=vergleiche ./routes/RangiersignalTest.st3
ZUSI3_DATAPATH=. ../fahrstr_gen.py --fahrstr_typen rangier,zug --modus=vergleiche ./routes/FahrstrNummerierungTest.st3
ZUSI3_DATAPATH=. ../fahrstr_gen.py --modus=vergleiche ./routes/UngueltigeRichtungsanzeigerTest.st3
ZUSI3_DATAPATH=. ../fahrstr_gen.py --modus=vergleiche ./routes/FahrstrStartZielSignalTest.st3
ZUSI3_DATAPATH=. ../fahrstr_gen.py --modus=vergleiche ./routes/RegisterVerknuepfungUngueltigesModul.st3
