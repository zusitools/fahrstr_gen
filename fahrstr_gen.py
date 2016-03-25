#!/usr/bin/env python3

from fahrstr_gen import modulverwaltung, streckengraph, strecke
from fahrstr_gen.konstanten import *

import xml.etree.ElementTree as ET
import argparse

import logging
logging.basicConfig(level = logging.INFO)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fahrstrassengenerierung fuer ein Zusi-3-Modul')
    parser.add_argument('dateiname')
    args = parser.parse_args()

    dieses_modul_relpath = modulverwaltung.get_zusi_relpath(args.dateiname)
    modulverwaltung.dieses_modul = modulverwaltung.Modul(dieses_modul_relpath.replace('/', '\\'), ET.parse(args.dateiname))
    modulverwaltung.module[modulverwaltung.normalize_zusi_relpath(dieses_modul_relpath)] = modulverwaltung.dieses_modul

    fahrstrassen = []
    for fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_LZB]:
        graph = streckengraph.Streckengraph(fahrstr_typ)

        for nr, str_element in sorted(modulverwaltung.dieses_modul.streckenelemente.items(), key = lambda t: t[0]):
            if str_element in modulverwaltung.dieses_modul.referenzpunkte:
                for richtung in [NORM, GEGEN]:
                    if any(
                            (fahrstr_typ == FAHRSTR_TYP_ZUG and r.reftyp == REFTYP_AUFGLEISPUNKT)
                            or (r.reftyp == REFTYP_SIGNAL and strecke.ist_hsig_fuer_fahrstr_typ(r.signal(), fahrstr_typ))
                            for r in modulverwaltung.dieses_modul.referenzpunkte[str_element] if r.richtung == richtung
                        ):

                        fahrstrassen.extend(graph.get_knoten(modulverwaltung.dieses_modul, str_element).get_fahrstrassen(richtung))

    for fahrstr in sorted(fahrstrassen, key = lambda f: f.name):
        print(fahrstr.name)
