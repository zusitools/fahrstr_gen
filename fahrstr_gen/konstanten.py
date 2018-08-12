NORM = True
GEGEN = False

REFTYP_AUFGLEISPUNKT = 0
REFTYP_MODULGRENZE = 1
REFTYP_REGISTER = 2
REFTYP_WEICHE = 3
REFTYP_SIGNAL = 4
REFTYP_AUFLOESEPUNKT = 5
REFTYP_SIGNALHALTFALL = 6

FAHRSTR_TYP_FAHRWEG = 1
FAHRSTR_TYP_RANGIER = 2
FAHRSTR_TYP_ZUG = 4
FAHRSTR_TYP_LZB = 8

def str_fahrstr_typ(typ):
    if typ == FAHRSTR_TYP_FAHRWEG:
        return "Fahrweg"
    elif typ == FAHRSTR_TYP_RANGIER:
        return "Rangierfahrt"
    elif typ == FAHRSTR_TYP_ZUG:
        return "Zugfahrt"
    elif typ == FAHRSTR_TYP_LZB:
        return "LZB"

EREIGNIS_SIGNALGESCHWINDIGKEIT = 1
EREIGNIS_SIGNALHALTFALL = 3
EREIGNIS_FAHRSTRASSE_AUFLOESEN = 4
EREIGNIS_VORHER_KEINE_VSIG_VERKNUEPFUNG = 20
EREIGNIS_KEINE_LZB_FAHRSTRASSE = 45
EREIGNIS_KEINE_ZUGFAHRSTRASSE = 21
EREIGNIS_KEINE_RANGIERFAHRSTRASSE = 22
EREIGNIS_HILFSHAUPTSIGNAL = 23
EREIGNIS_GEGENGLEIS = 28
EREIGNIS_REGELGLEIS = 39
EREIGNIS_EINGLEISIG = 40
EREIGNIS_RICHTUNGSVORANZEIGER = 38
EREIGNIS_RICHTUNGSANZEIGER_ZIEL = 29
EREIGNIS_REGISTER_VERKNUEPFEN = 34
EREIGNIS_REGISTER_BEDINGT_VERKNUEPFEN = 35
EREIGNIS_WEICHE_VERKNUEPFEN = 36
EREIGNIS_SIGNAL_VERKNUEPFEN = 37
EREIGNIS_VORSIGNAL_VERKNUEPFEN = 50
EREIGNIS_ENTGLEISEN = 52
EREIGNIS_LZB_ENDE = 3002
EREIGNIS_ENDE_WEICHENBEREICH = 1000002

GLEIS_BAHNHOF = 0
GLEIS_EINGLEISIG = 1
GLEIS_REGELGLEIS = 2
GLEIS_GEGENGLEIS = 3

SIGFLAG_FAHRWEGSIGNAL_BEIDE_FAHRTRICHTUNGEN = 1<<0
SIGFLAG_FAHRWEGSIGNAL_WEICHENANIMATION = 1<<1
SIGFLAG_RANGIERSIGNAL_BEI_ZUGFAHRSTR_UMSTELLEN = 1<<2
SIGFLAG_KENNLICHT_NACHFOLGESIGNAL = 1<<4
SIGFLAG_KENNLICHT_VORGAENGERSIGNAL = 1<<5
SIGFLAG_HOCHSIGNALISIERUNG = 1<<7
