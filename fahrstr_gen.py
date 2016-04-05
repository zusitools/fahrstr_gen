#!/usr/bin/env python3

from fahrstr_gen import modulverwaltung, streckengraph, strecke
from fahrstr_gen.konstanten import *
from fahrstr_gen.strecke import writeuglyxml, ist_hsig_fuer_fahrstr_typ, Element
from fahrstr_gen.fahrstr_suche import FahrstrassenSuche
from fahrstr_gen.fahrstr_graph import FahrstrGraph
from fahrstr_gen.vorsignal_graph import VorsignalGraph
from fahrstr_gen.flankenschutz_graph import FlankenschutzGraph

import xml.etree.ElementTree as ET
import argparse
import operator
import tempfile
import shutil
import os
import sys
from collections import defaultdict, namedtuple

import logging
import tkinter
import tkinter.filedialog
import tkinter.ttk

def refpunkt_fmt(refpunkt):
    pfad = refpunkt[1]
    if pfad.rfind('\\') != -1:
        pfad = pfad[pfad.rfind('\\')+1:]
    return "({},{})".format(pfad, refpunkt[0])

def finde_fahrstrassen(args):
    dieses_modul_relpath = modulverwaltung.get_zusi_relpath(args.dateiname)
    modulverwaltung.dieses_modul = modulverwaltung.Modul(dieses_modul_relpath.replace('/', '\\'), ET.parse(args.dateiname).getroot())
    modulverwaltung.module[modulverwaltung.normalize_zusi_relpath(dieses_modul_relpath)] = modulverwaltung.dieses_modul

    loeschfahrstrassen_namen = [n.get("FahrstrName", "") for n in modulverwaltung.dieses_modul.root.findall("./Strecke/LoeschFahrstrasse")]

    fahrstrassen = []
    fahrstrassen_nummerierung = defaultdict(list) # (Start-Refpunkt, ZielRefpunkt) -> [Fahrstrasse], zwecks Durchnummerierung

    bedingungen = dict()
    if args.bedingungen is not None:
        for bedingung in ET.parse(args.bedingungen).getroot().findall("Bedingung"):
            bedingungen[bedingung.attrib["EinzelFahrstrName"]] = bedingung

    vorsignal_graph = VorsignalGraph()
    flankenschutz_graph = FlankenschutzGraph()

    for fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_LZB]:
        logging.debug("Generiere Fahrstrassen vom Typ {}".format(fahrstr_typ))
        fahrstr_suche = FahrstrassenSuche(fahrstr_typ, bedingungen,
                vorsignal_graph if fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_LZB] else None,
                flankenschutz_graph if fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_LZB] else None)
        graph = FahrstrGraph(fahrstr_typ)

        for nr, str_element in sorted(modulverwaltung.dieses_modul.streckenelemente.items(), key = lambda t: t[0]):
            if str_element in modulverwaltung.dieses_modul.referenzpunkte:
                for richtung in [NORM, GEGEN]:
                    if any(
                            (fahrstr_typ == FAHRSTR_TYP_ZUG and r.reftyp == REFTYP_AUFGLEISPUNKT)
                            or (r.reftyp == REFTYP_SIGNAL and ist_hsig_fuer_fahrstr_typ(r.signal(), fahrstr_typ))
                            for r in modulverwaltung.dieses_modul.referenzpunkte[str_element] if r.element_richtung.richtung == richtung
                        ):

                        for f in fahrstr_suche.get_fahrstrassen(graph.get_knoten(str_element), richtung):
                            if f.name in loeschfahrstrassen_namen:
                                logging.info("Loesche Fahrstrasse: {}".format(f.name))
                            else:
                                if args.nummerieren:
                                    idx = len(fahrstrassen_nummerierung[(f.start, f.ziel)])
                                    if idx != 0:
                                        f.name += " ({})".format(idx)
                                    fahrstrassen_nummerierung[(f.start, f.ziel)].append(f)
                                fahrstrassen.append(f)

    strecke = modulverwaltung.dieses_modul.root.find("./Strecke")
    if strecke is not None:
        if args.modus == 'schreibe':
            for fahrstrasse_alt in strecke.findall("./Fahrstrasse"):
                strecke.remove(fahrstrasse_alt)
            for fahrstrasse_neu in sorted(fahrstrassen, key = lambda f: f.name):
                logging.info("Fahrstrasse erzeugt: {}".format(fahrstrasse_neu.name))
                strecke.append(fahrstrasse_neu.to_xml())
            fp = tempfile.NamedTemporaryFile('wb', delete = False)
            with fp:
                fp.write(b"\xef\xbb\xbf")
                fp.write(u'<?xml version="1.0" encoding="UTF-8"?>\r\n'.encode("utf-8"))
                writeuglyxml(fp, modulverwaltung.dieses_modul.root)
            shutil.copyfile(fp.name, args.dateiname)
            os.remove(fp.name)

        elif args.modus == 'vergleiche':
            logging.info("Vergleiche erzeugte Fahrstrassen mit denen aus der ST3-Datei.")

            alt_vs_neu = defaultdict(dict)
            for fahrstrasse_alt in strecke.findall("./Fahrstrasse"):
                alt_vs_neu[fahrstrasse_alt.attrib["FahrstrName"]]["alt"] = fahrstrasse_alt
            for fahrstrasse_neu in fahrstrassen:
                alt_vs_neu[fahrstrasse_neu.name]["neu"] = fahrstrasse_neu

            for name, fahrstrassen in sorted(alt_vs_neu.items(), key = operator.itemgetter(0)):
                try:
                    fahrstr_alt = fahrstrassen["alt"]
                except KeyError:
                    logging.info("{} existiert in Zusi nicht".format(name))
                    continue
                try:
                    fahrstr_neu = fahrstrassen["neu"]
                except KeyError:
                    logging.info("{} existiert in Zusi, wurde aber nicht erzeugt".format(name))
                    continue

                laenge_alt = float(fahrstr_alt.get("Laenge", 0))
                if abs(laenge_alt - fahrstr_neu.laenge) > 1:
                    # TODO: Zusi berechnet die Fahrstrassenlaenge inklusive Start-, aber ohne Zielelement.
                    # Wir berechnen exklusive Start, inklusive Ziel, was richtiger scheint.
                    # logging.info("{}: unterschiedliche Laenge: {:.2f} vs. {:.2f}".format(name, laenge_alt, fahrstr_neu.laenge))
                    pass

                fahrstr_typ = fahrstr_alt.get("FahrstrTyp", "")
                if fahrstr_neu.fahrstr_typ == FAHRSTR_TYP_RANGIER and fahrstr_typ != "TypRangier":
                    logging.info("{}: unterschiedlicher Fahrstrassentyp: {} vs TypRangier".format(name, fahrstr_typ))
                elif fahrstr_neu.fahrstr_typ == FAHRSTR_TYP_ZUG and fahrstr_typ != "TypZug":
                    logging.info("{}: unterschiedlicher Fahrstrassentyp: {} vs TypZug".format(name, fahrstr_typ))
                elif fahrstr_neu.fahrstr_typ == FAHRSTR_TYP_LZB and fahrstr_typ != "TypLZB":
                    logging.info("{}: unterschiedlicher Fahrstrassentyp: {} vs TypLZB".format(name, fahrstr_typ))

                rgl_ggl_alt = int(fahrstr_alt.get("RglGgl", 0))
                if fahrstr_neu.rgl_ggl != rgl_ggl_alt:
                    logging.info("{}: unterschiedliche RglGgl-Spezifikation: {} vs {}".format(name, rgl_ggl_alt, fahrstr_neu.rgl_ggl))

                streckenname_alt = fahrstr_alt.get("FahrstrStrecke", "")
                if fahrstr_neu.streckenname != streckenname_alt:
                    logging.info("{}: unterschiedlicher Streckenname: {} vs {}".format(name, streckenname_alt, fahrstr_neu.streckenname))

                zufallswert_alt = float(fahrstr_alt.get("ZufallsWert", 0))
                if fahrstr_neu.zufallswert != zufallswert_alt:
                    logging.info("{}: unterschiedlicher Zufallswert: {} vs {}".format(name, zufallswert_alt, fahrstr_neu.zufallswert))

                start_alt = fahrstr_alt.find("./FahrstrStart")
                start_alt_refnr = int(start_alt.get("Ref", 0))
                start_alt_modul = start_alt.find("./Datei").get("Dateiname", "")
                if start_alt_refnr != fahrstr_neu.start.refnr or start_alt_modul.upper() != fahrstr_neu.start.element_richtung.element.modul.relpath.upper():
                    logging.info("{}: unterschiedlicher Start: {}@{} vs. {}@{}".format(name, start_alt_refnr, start_alt_modul, fahrstr_neu.start.refnr, fahrstr_neu.start.element_richtung.element.modul.relpath))

                ziel_alt = fahrstr_alt.find("./FahrstrZiel")
                ziel_alt_refnr = int(ziel_alt.get("Ref", 0))
                ziel_alt_modul = ziel_alt.find("./Datei").get("Dateiname", "")
                if ziel_alt_refnr != fahrstr_neu.ziel.refnr or ziel_alt_modul.upper() != fahrstr_neu.ziel.element_richtung.element.modul.relpath.upper():
                    logging.info("{}: unterschiedliches Ziel: {}@{} vs. {}@{}".format(name, ziel_alt_refnr, ziel_alt_modul, fahrstr_neu.ziel.refnr, fahrstr_neu.ziel.element_richtung.element.modul.relpath))

                # Register
                register_alt = set((int(register_alt.get("Ref", 0)), register_alt.find("./Datei").get("Dateiname", "").upper()) for register_alt in fahrstr_alt.iterfind("./FahrstrRegister"))
                register_neu = set((register_neu.refnr, register_neu.element_richtung.element.modul.relpath.upper()) for register_neu in fahrstr_neu.register)

                for refpunkt in register_alt - register_neu:
                    logging.info("{}: Registerverknuepfung {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(refpunkt)))
                for refpunkt in register_neu - register_alt:
                    logging.info("{}: Registerverknuepfung {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(refpunkt)))

                # Aufloesepunkte
                aufloesepunkte_alt = set((int(aufl.get("Ref", 0)), aufl.find("./Datei").get("Dateiname", "").upper()) for aufl in fahrstr_alt.iterfind("./FahrstrAufloesung"))
                aufloesepunkte_neu = set((aufl.refnr, aufl.element_richtung.element.modul.relpath.upper()) for aufl in fahrstr_neu.aufloesepunkte)

                for refpunkt in aufloesepunkte_alt - aufloesepunkte_neu:
                    logging.info("{}: Aufloesepunkt {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(refpunkt)))
                for refpunkt in aufloesepunkte_neu - aufloesepunkte_alt:
                    logging.info("{}: Aufloesepunkt {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(refpunkt)))

                # Signalhaltfallpunkte
                sighaltfallpunkte_alt = set((int(haltfall.get("Ref", 0)), haltfall.find("./Datei").get("Dateiname", "").upper()) for haltfall in fahrstr_alt.iterfind("./FahrstrSigHaltfall"))
                sighaltfallpunkte_neu = set((haltfall.refnr, haltfall.element_richtung.element.modul.relpath.upper()) for haltfall in fahrstr_neu.signalhaltfallpunkte)

                for refpunkt in sighaltfallpunkte_alt - sighaltfallpunkte_neu:
                    logging.info("{}: Signalhaltfallpunkt {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(refpunkt)))
                for refpunkt in sighaltfallpunkte_neu - sighaltfallpunkte_alt:
                    logging.info("{}: Signalhaltfallpunkt {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(refpunkt)))

                # Teilaufloesepunkte
                teilaufloesepunkte_alt = set((int(aufl.get("Ref", 0)), aufl.find("./Datei").get("Dateiname", "").upper()) for aufl in fahrstr_alt.iterfind("./FahrstrTeilaufloesung"))
                teilaufloesepunkte_neu = set((aufl.refnr, aufl.element_richtung.element.modul.relpath.upper()) for aufl in fahrstr_neu.teilaufloesepunkte)

                for refpunkt in teilaufloesepunkte_alt - teilaufloesepunkte_neu:
                    logging.info("{}: Teilaufloesung {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(refpunkt)))
                for refpunkt in teilaufloesepunkte_neu - teilaufloesepunkte_alt:
                    logging.info("{}: Teilaufloesung {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(refpunkt)))

                # Weichen
                weichenstellungen_alt_vs_neu = defaultdict(dict)
                for weiche_alt in fahrstr_alt.findall("./FahrstrWeiche"):
                    weichenstellungen_alt_vs_neu[(int(weiche_alt.get("Ref", 0)), weiche_alt.find("./Datei").get("Dateiname", "").upper())]["alt"] = int(weiche_alt.get("FahrstrWeichenlage", 0))
                for weiche_neu in fahrstr_neu.weichen:
                    weichenstellungen_alt_vs_neu[(weiche_neu.refpunkt.refnr, weiche_neu.refpunkt.element_richtung.element.modul.relpath.upper())]["neu"] = weiche_neu.weichenlage

                for weichen_refpunkt, weichenstellungen in sorted(weichenstellungen_alt_vs_neu.items(), key = operator.itemgetter(0)):
                    if "alt" not in weichenstellungen:
                        logging.info("{}: Weichenstellung {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(weichen_refpunkt)))
                    elif "neu" not in weichenstellungen:
                        logging.info("{}: Weichenstellung {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(weichen_refpunkt)))
                    elif weichenstellungen["alt"] != weichenstellungen["neu"]:
                        logging.info("{}: Weiche {} hat unterschiedliche Stellungen: {} vs. {}".format(name, refpunkt_fmt(weichen_refpunkt), weichenstellungen["alt"], weichenstellungen["neu"]))

                # Hauptsignale
                hsig_alt_vs_neu = defaultdict(dict)
                for hsig_alt in fahrstr_alt.findall("./FahrstrSignal"):
                    hsig_alt_vs_neu[(int(hsig_alt.get("Ref", 0)), hsig_alt.find("./Datei").get("Dateiname", "").upper())]["alt"] = (int(hsig_alt.get("FahrstrSignalZeile", 0)), int(hsig_alt.get("FahrstrSignalErsatzsignal", 0)) == 1)
                for hsig_neu in fahrstr_neu.signale:
                    hsig_alt_vs_neu[(hsig_neu.refpunkt.refnr, hsig_neu.refpunkt.element_richtung.element.modul.relpath.upper())]["neu"] = (hsig_neu.zeile, hsig_neu.ist_ersatzsignal)

                for hsig_refpunkt, hsig in sorted(hsig_alt_vs_neu.items(), key = operator.itemgetter(0)):
                    if "alt" not in hsig:
                        logging.info("{}: Hauptsignalverknuepfung {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(hsig_refpunkt)))
                    elif "neu" not in hsig:
                        logging.info("{}: Hauptsignalverknuepfung {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(hsig_refpunkt)))
                    elif hsig["alt"] != hsig["neu"]:
                        logging.info("{}: Hauptsignalverknuepfung {} hat unterschiedliche Zeile: {} vs. {}".format(name, refpunkt_fmt(hsig_refpunkt), hsig["alt"], hsig["neu"]))

                # Vorsignale
                vsig_alt_vs_neu = defaultdict(dict)
                for vsig_alt in fahrstr_alt.findall("./FahrstrVSignal"):
                    vsig_alt_vs_neu[(int(vsig_alt.get("Ref", 0)), vsig_alt.find("./Datei").get("Dateiname", "").upper())]["alt"] = int(vsig_alt.get("FahrstrSignalSpalte", 0))
                for vsig_neu in fahrstr_neu.vorsignale:
                    vsig_alt_vs_neu[(vsig_neu.refpunkt.refnr, vsig_neu.refpunkt.element_richtung.element.modul.relpath.upper())]["neu"] = vsig_neu.spalte

                for vsig_refpunkt, vsig in sorted(vsig_alt_vs_neu.items(), key = operator.itemgetter(0)):
                    if "alt" not in vsig:
                        logging.info("{}: Vorsignalverknuepfung {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(vsig_refpunkt)))
                    elif "neu" not in vsig:
                        logging.info("{}: Vorsignalverknuepfung {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(vsig_refpunkt)))
                    elif vsig["alt"] != vsig["neu"]:
                        logging.info("{}: Vorsignalverknuepfung {} hat unterschiedliche Spalte: {} vs. {}".format(name, refpunkt_fmt(vsig_refpunkt), vsig["alt"], vsig["neu"]))

            logging.info("Fahrstrassen-Vergleich abgeschlossen.")

# http://stackoverflow.com/a/35365616/1083696
class LoggingHandlerFrame(tkinter.ttk.Frame):

    class Handler(logging.Handler):
        def __init__(self, widget):
            logging.Handler.__init__(self)
            self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
            self.widget = widget

        def emit(self, record):
            self.widget.insert(tkinter.END, self.format(record) + "\n")
            self.widget.see(tkinter.END)

    def __init__(self, *args, **kwargs):
        tkinter.ttk.Frame.__init__(self, *args, **kwargs)

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.rowconfigure(0, weight=1)

        self.scrollbar = tkinter.Scrollbar(self)
        self.scrollbar.grid(row=0, column=1, sticky=(tkinter.N,tkinter.S,tkinter.E))

        self.text = tkinter.Text(self, yscrollcommand=self.scrollbar.set)
        self.text.grid(row=0, column=0, sticky=(tkinter.N,tkinter.S,tkinter.E,tkinter.W))

        self.scrollbar.config(command=self.text.yview)

        self.logging_handler = LoggingHandlerFrame.Handler(self.text)

    def clear(self):
        self.text.delete(1.0, tkinter.END)

    def setLevel(self, level):
        self.logging_handler.setLevel(level)

def gui():
    def btn_start_callback():
        ent_log.logging_handler.setLevel(logging.DEBUG if var_debug.get() else logging.INFO)
        ent_log.clear()

        try:
            args = namedtuple('args', ['dateiname', 'modus', 'nummerieren', 'bedingungen'])
            args.dateiname = ent_dateiname.get()
            args.modus = 'vergleiche' if var_vergleiche.get() else 'schreibe'
            args.nummerieren = var_nummerieren.get()
            args.bedingungen = None if ent_bedingungen.get() == '' else ent_bedingungen.get()
            finde_fahrstrassen(args)
        except Exception as e:
            logging.exception(e)

    def btn_dateiname_callback():
        filename = tkinter.filedialog.askopenfilename(initialdir=os.path.join(modulverwaltung.get_zusi_datapath(), 'Routes'), filetypes=[('ST3-Dateien', '.st3'), ('Alle Dateien', '*')])
        ent_dateiname.delete(0, tkinter.END)
        ent_dateiname.insert(0, filename)

    def btn_bedingungen_callback():
        filename = tkinter.filedialog.askopenfilename()
        ent_bedingungen.delete(0, tkinter.END)
        ent_bedingungen.insert(0, filename)

    def btn_logkopieren_callback():
        root.clipboard_clear()
        root.clipboard_append(ent_log.text.get(1.0, tkinter.END))

    root = tkinter.Tk()
    root.wm_title("Fahrstrassengenerierung")

    frame = tkinter.Frame(root)

    lbl_dateiname = tkinter.Label(frame, text="ST3-Datei: ")
    lbl_dateiname.grid(row=0, column=0, sticky=tkinter.W)
    ent_dateiname = tkinter.Entry(frame, width=50)
    ent_dateiname.grid(row=0, column=1, sticky=(tkinter.W,tkinter.E))
    btn_dateiname = tkinter.Button(frame, text="...", command=btn_dateiname_callback)
    btn_dateiname.grid(row=0, column=2, sticky=tkinter.W)

    lbl_bedingungen = tkinter.Label(frame, text="Bedingungsdatei (fuer Profis): ")
    lbl_bedingungen.grid(row=10, column=0, sticky=tkinter.W)
    ent_bedingungen = tkinter.Entry(frame, width=50)
    ent_bedingungen.grid(row=10, column=1, sticky=(tkinter.W,tkinter.E))
    btn_bedingungen = tkinter.Button(frame, text="...", command=btn_bedingungen_callback)
    btn_bedingungen.grid(row=10, column=2, sticky=tkinter.W)

    var_nummerieren = tkinter.BooleanVar()
    chk_nummerieren = tkinter.Checkbutton(frame, text="Fahrstrassen nummerieren (3D-Editor 3.1.0.4+)", variable=var_nummerieren)
    chk_nummerieren.grid(row=20, column=1, columnspan=2, sticky=tkinter.W)

    var_debug = tkinter.BooleanVar()
    chk_debug = tkinter.Checkbutton(frame, text="Debug-Ausgaben anzeigen", variable=var_debug)
    chk_debug.grid(row=30, column=1, columnspan=2, sticky=tkinter.W)

    var_vergleiche = tkinter.BooleanVar()
    chk_vergleiche = tkinter.Checkbutton(frame, text="Nichts schreiben, stattdessen erzeugte Fahrstrassen mit existierenden vergleichen", variable=var_vergleiche)
    chk_vergleiche.grid(row=40, column=1, columnspan=2, sticky=tkinter.W)

    btn_start = tkinter.Button(frame, text="Start", command=btn_start_callback)
    btn_start.grid(row=98, columnspan=3, sticky='we')

    ent_log = LoggingHandlerFrame(frame)
    ent_log.grid(row=99, columnspan=3, sticky='wens')
    logging.getLogger().addHandler(ent_log.logging_handler)
    logging.getLogger().setLevel(logging.DEBUG)  # wird durch handler.setLevel eventuell weiter herabgesetzt

    btn_logkopieren = tkinter.Button(frame, text="Log kopieren", command=btn_logkopieren_callback)
    btn_logkopieren.grid(row=100, columnspan=3, sticky='we')

    frame.rowconfigure(99, minsize=100, weight=1)
    frame.columnconfigure(1, weight=1)

    frame.pack(fill=tkinter.BOTH, expand=tkinter.YES)
    tkinter.mainloop()

if __name__ == '__main__':
    if len(sys.argv) == 1:
        # Ohne Parameter wird die GUI-Version aufgerufen.
        gui()
    else:
        parser = argparse.ArgumentParser(description='Fahrstrassengenerierung fuer ein Zusi-3-Modul')
        parser.add_argument('dateiname')
        parser.add_argument('--modus', choices=['schreibe', 'vergleiche'], default='schreibe', help="Modus \"vergleiche\" schreibt die Fahrstrassen nicht, sondern gibt stattdessen die Unterschiede zu den bestehenden Fahrstrassen aus.")
        parser.add_argument('--profile', choices=['profile', 'line_profiler'], help=argparse.SUPPRESS)
        parser.add_argument('--debug', action='store_true', help="Debug-Ausgaben anzeigen")
        parser.add_argument('--nummerieren', action='store_true', help="Fahrstrassen mit gleichem Start+Ziel durchnummerieren (wie 3D-Editor 3.1.0.4)")
        parser.add_argument('--bedingungen', help="Datei mit Bedingungen fuer die Fahrstrassengenerierung")
        args = parser.parse_args()

        logging.basicConfig(format='%(relativeCreated)d:%(levelname)s:%(message)s', level=(logging.DEBUG if args.debug else logging.INFO))

        if args.profile == 'profile':
            import profile, pstats
            p = profile.Profile()
            p.run('finde_fahrstrassen(args)')
            s = pstats.Stats(p)
            s.strip_dirs()
            s.sort_stats('cumtime')
            s.print_stats()
            s.print_callers()
        elif args.profile == 'line_profiler':
            import line_profiler
            p = line_profiler.LineProfiler(finde_fahrstrassen)
            # p.add_function(...)
            p.run('finde_fahrstrassen(args)')
            p.print_stats()
        else:
            finde_fahrstrassen(args)
