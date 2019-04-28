#!/usr/bin/env python3

from fahrstr_gen import modulverwaltung
from fahrstr_gen.konstanten import *
from fahrstr_gen.strecke import ist_fahrstr_start_sig
from fahrstr_gen.fahrstr_suche import FahrstrassenSuche
from fahrstr_gen.fahrstr_graph import FahrstrGraph
from fahrstr_gen.vorsignal_graph import VorsignalGraph
from fahrstr_gen.flankenschutz_graph import FlankenschutzGraph

import xml.etree.ElementTree as ET
import argparse
import operator
import os
import re
import sys
from collections import defaultdict, namedtuple

import logging
import tkinter
import tkinter.filedialog
import tkinter.messagebox
import tkinter.ttk

logging.COMPAT = 15
logging.addLevelName(logging.COMPAT, 'COMPAT')

def refpunkt_fmt(refpunkt):
    pfad = refpunkt[1]
    if pfad.rfind('\\') != -1:
        pfad = pfad[pfad.rfind('\\')+1:]
    return "({},{})".format(pfad, refpunkt[0])

def abfrage_janein_cli(frage):
    antwort = '?'
    while antwort not in "jn":
        antwort = input(frage + " [j/n] ")
    return antwort == 'j'

def abfrage_janein_gui(frage):
    return tkinter.messagebox.askyesno("Frage", frage)

abfrage_janein = abfrage_janein_cli

nat_sort_regex = re.compile('(\d+)')

def nat_sort_key(s):
    # http://stackoverflow.com/a/5967539
    return [(int(s) if s.isdigit() else s) for s in nat_sort_regex.split(s)]

def fahrstr_sort_key(fahrstrasse):
    # Sortiere Aufgleisfahrstrassen an den Anfang, sortiert nach Zielsignal-Name
    # Sortiere restliche Fahrstrassen danach ein, sortiert nach Startsignal-Name.
    #   Fahrstrassen mit demselben Startsignal sollen so sortiert sein, dass der beste Fahrweg zu einem gegebenen Signal
    #   mittels Tiefensuche ermittelt werden kann. Eine Tiefensuche, die dem Vorrangstrang der Weichen zuerst folgt,
    #   erfuellt dieses Kriterium in der Regel.
    if fahrstrasse.start.reftyp == REFTYP_AUFGLEISPUNKT:
        return ([], nat_sort_key(fahrstrasse.ziel.signal().signalbeschreibung()))
    else:
        return (nat_sort_key(fahrstrasse.start.signal().signalbeschreibung()), [])

def finde_fahrstrassen(args):
    modulverwaltung.module = dict()
    modulverwaltung.dieses_modul = None

    dieses_modul_relpath = modulverwaltung.get_zusi_relpath(args.dateiname)
    modulverwaltung.dieses_modul = modulverwaltung.Modul(args.dateiname, dieses_modul_relpath)
    modulverwaltung.module[modulverwaltung.normalize_zusi_relpath(dieses_modul_relpath)] = modulverwaltung.dieses_modul

    loeschfahrstrassen_namen = [n.get("FahrstrName", "") for n in modulverwaltung.dieses_modul.root.findall("./Strecke/LoeschFahrstrasse")]

    fahrstrassen = []

    bedingungen = dict()
    if args.bedingungen is not None:
        for bedingung in ET.parse(args.bedingungen).getroot().findall("Bedingung"):
            bedingungen[bedingung.attrib["EinzelFahrstrName"]] = bedingung

    vorsignal_graph = VorsignalGraph()
    flankenschutz_graph = FlankenschutzGraph()

    fahrstr_typen = []
    for s in map(lambda s: s.lower().strip(), args.fahrstr_typen.split(",")):
        if s.startswith("r"):
            fahrstr_typen.append(FAHRSTR_TYP_RANGIER)
        elif s.startswith("z"):
            fahrstr_typen.append(FAHRSTR_TYP_ZUG)
        elif s.startswith("a") or s.startswith("l"):
            fahrstr_typen.append(FAHRSTR_TYP_ANZEIGE)

    for fahrstr_typ in fahrstr_typen:
        logging.debug("Generiere Fahrstrassen vom Typ {}".format(str_fahrstr_typ(fahrstr_typ)))
        fahrstr_suche = FahrstrassenSuche(fahrstr_typ, args.alternative_fahrwege, bedingungen,
                vorsignal_graph if fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_ANZEIGE] else None,
                flankenschutz_graph if args.flankenschutz and (fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_ANZEIGE]) else None,
                loeschfahrstrassen_namen)
        graph = FahrstrGraph(fahrstr_typ)

        for nr, str_element in sorted(modulverwaltung.dieses_modul.streckenelemente.items(), key = lambda t: t[0]):
            if str_element in modulverwaltung.dieses_modul.referenzpunkte:
                for richtung in [NORM, GEGEN]:
                    if any(
                            (fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_RANGIER] and r.reftyp == REFTYP_AUFGLEISPUNKT)
                            or (r.reftyp == REFTYP_SIGNAL and ist_fahrstr_start_sig(r.signal(), fahrstr_typ))
                            for r in modulverwaltung.dieses_modul.referenzpunkte[str_element] if r.element_richtung.richtung == richtung
                        ):

                        knoten = graph.get_knoten(str_element)
                        assert(knoten is not None)
                        fahrstrassen.extend(fahrstr_suche.get_fahrstrassen(knoten, richtung))

    strecke = modulverwaltung.dieses_modul.root.find("./Strecke")
    if strecke is not None:
        if args.modus == 'schreibe':
            for fahrstrasse_alt in strecke.findall("./Fahrstrasse"):
                strecke.remove(fahrstrasse_alt)
            # N.B. sort() und sorted() sind stabile Sortierverfahren.
            # Das ist hier notwendig, da die Information ueber den Vorrangstrang nur implizit (ueber die Reihenfolge) in der Fahrstrassenliste enthalten ist.
            for fahrstrasse_neu in sorted(fahrstrassen, key = fahrstr_sort_key):
                logging.info("Fahrstrasse erzeugt: {}".format(fahrstrasse_neu.name))
                strecke.append(fahrstrasse_neu.to_xml())
            modulverwaltung.dieses_modul.schreibe_moduldatei()

            for modul in modulverwaltung.module.values():
                if modul is not None and modul.geaendert and modul != modulverwaltung.dieses_modul:
                    if abfrage_janein("Modul {} wurde bei der Fahrstrassenerzeugung ebenfalls geaendert. Aenderungen speichern?".format(modul.dateiname)):
                        modul.schreibe_moduldatei()

        elif args.modus == 'profile':
            anzahl_elemente = 0
            for modul in modulverwaltung.module.values():
                anzahl_elemente += len(modul.streckenelemente)
            logging.info("{} Streckenelemente in {} Modulen".format(anzahl_elemente, len(modulverwaltung.module)))

        elif args.modus == 'vergleiche':
            logging.info("Vergleiche erzeugte Fahrstrassen mit denen aus der ST3-Datei.")
            unterschied = False

            alt_vs_neu = defaultdict(dict)
            for fahrstrasse_alt in strecke.findall("./Fahrstrasse"):
                fahrstr_typ = fahrstrasse_alt.get("FahrstrTyp", "")
                if fahrstr_typ == "TypLZB":
                    fahrstr_typ = "TypAnzeige"
                alt_vs_neu[(fahrstr_typ, fahrstrasse_alt.get("FahrstrName", ""))]["alt"] = fahrstrasse_alt
            for fahrstrasse_neu in fahrstrassen:
                if fahrstrasse_neu.fahrstr_typ == FAHRSTR_TYP_RANGIER:
                    alt_vs_neu[("TypRangier", fahrstrasse_neu.name)]["neu"] = fahrstrasse_neu
                elif fahrstrasse_neu.fahrstr_typ == FAHRSTR_TYP_ZUG:
                    alt_vs_neu[("TypZug", fahrstrasse_neu.name)]["neu"] = fahrstrasse_neu
                elif fahrstrasse_neu.fahrstr_typ == FAHRSTR_TYP_ANZEIGE:
                    alt_vs_neu[("TypAnzeige", fahrstrasse_neu.name)]["neu"] = fahrstrasse_neu

            for (typ, name), fahrstrasse in sorted(alt_vs_neu.items(), key = operator.itemgetter(0)):
                try:
                    fahrstr_alt = fahrstrasse["alt"]
                except KeyError:
                    unterschied = True
                    logging.info("Fahrstrasse {} ({}) existiert in Zusi nicht".format(name, typ))
                    continue
                try:
                    fahrstr_neu = fahrstrasse["neu"]
                except KeyError:
                    unterschied = True
                    logging.info("Fahrstrasse {} ({}) existiert in Zusi, wurde aber nicht erzeugt".format(name, typ))
                    continue

                laenge_alt = float(fahrstr_alt.get("Laenge", 0))
                if abs(laenge_alt - fahrstr_neu.laenge) > 1 and abs(laenge_alt - fahrstr_neu.laenge_zusi) > 1 and abs(laenge_alt - fahrstr_neu.laenge_zusi_vor_3_1_7_2) > 1:
                    unterschied = True
                    logging.info("{}: unterschiedliche Laenge: {:.2f} vs. {:.2f} ({:.2f}, {:.2f})".format(name, laenge_alt, fahrstr_neu.laenge, fahrstr_neu.laenge_zusi, fahrstr_neu.laenge_zusi_vor_3_1_7_2))

                rgl_ggl_alt = int(fahrstr_alt.get("RglGgl", 0))
                if fahrstr_neu.rgl_ggl != rgl_ggl_alt:
                    unterschied = True
                    logging.info("{}: unterschiedliche RglGgl-Spezifikation: {} vs {}".format(name, rgl_ggl_alt, fahrstr_neu.rgl_ggl))

                streckenname_alt = fahrstr_alt.get("FahrstrStrecke", "")
                if fahrstr_neu.streckenname != streckenname_alt:
                    unterschied = True
                    logging.info("{}: unterschiedlicher Streckenname: {} vs {}".format(name, streckenname_alt, fahrstr_neu.streckenname))

                zufallswert_alt = float(fahrstr_alt.get("ZufallsWert", 0))
                if fahrstr_neu.zufallswert != zufallswert_alt:
                    unterschied = True
                    logging.info("{}: unterschiedlicher Zufallswert: {} vs {}".format(name, zufallswert_alt, fahrstr_neu.zufallswert))

                start_alt = fahrstr_alt.find("./FahrstrStart")
                start_alt_refnr = int(start_alt.get("Ref", 0))
                start_alt_modul = start_alt.find("./Datei").get("Dateiname", "")
                if start_alt_refnr != fahrstr_neu.start.refnr or start_alt_modul.upper() != fahrstr_neu.start.element_richtung.element.modul.relpath.upper():
                    unterschied = True
                    logging.info("{}: unterschiedlicher Start: {}@{} vs. {}@{}".format(name, start_alt_refnr, start_alt_modul, fahrstr_neu.start.refnr, fahrstr_neu.start.element_richtung.element.modul.relpath))

                ziel_alt = fahrstr_alt.find("./FahrstrZiel")
                ziel_alt_refnr = int(ziel_alt.get("Ref", 0))
                ziel_alt_modul = ziel_alt.find("./Datei").get("Dateiname", "")
                if ziel_alt_refnr != fahrstr_neu.ziel.refnr or ziel_alt_modul.upper() != fahrstr_neu.ziel.element_richtung.element.modul.relpath.upper():
                    unterschied = True
                    logging.info("{}: unterschiedliches Ziel: {}@{} vs. {}@{}".format(name, ziel_alt_refnr, ziel_alt_modul, fahrstr_neu.ziel.refnr, fahrstr_neu.ziel.element_richtung.element.modul.relpath))

                # Register
                register_alt = set((int(register_alt.get("Ref", 0)), register_alt.find("./Datei").get("Dateiname", "").upper()) for register_alt in fahrstr_alt.iterfind("./FahrstrRegister"))
                register_neu = set((register_neu.refnr, register_neu.element_richtung.element.modul.relpath.upper()) for register_neu in fahrstr_neu.register)

                for refpunkt in sorted(register_alt - register_neu, key = operator.itemgetter(0)):
                    unterschied = True
                    logging.info("{}: Registerverknuepfung {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(refpunkt)))
                for refpunkt in sorted(register_neu - register_alt, key = operator.itemgetter(0)):
                    unterschied = True
                    logging.info("{}: Registerverknuepfung {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(refpunkt)))

                # Aufloesepunkte
                aufloesepunkte_alt = set((int(aufl.get("Ref", 0)), aufl.find("./Datei").get("Dateiname", "").upper()) for aufl in fahrstr_alt.iterfind("./FahrstrAufloesung"))
                aufloesepunkte_neu = set((aufl.refnr, aufl.element_richtung.element.modul.relpath.upper()) for aufl in fahrstr_neu.aufloesepunkte)

                for refpunkt in sorted(aufloesepunkte_alt - aufloesepunkte_neu, key = operator.itemgetter(0)):
                    unterschied = True
                    logging.info("{}: Aufloesepunkt {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(refpunkt)))
                for refpunkt in sorted(aufloesepunkte_neu - aufloesepunkte_alt, key = operator.itemgetter(0)):
                    unterschied = True
                    logging.info("{}: Aufloesepunkt {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(refpunkt)))

                # Signalhaltfallpunkte
                sighaltfallpunkte_alt = set((int(haltfall.get("Ref", 0)), haltfall.find("./Datei").get("Dateiname", "").upper()) for haltfall in fahrstr_alt.iterfind("./FahrstrSigHaltfall"))
                sighaltfallpunkte_neu = set((haltfall.refnr, haltfall.element_richtung.element.modul.relpath.upper()) for haltfall in fahrstr_neu.signalhaltfallpunkte)

                for refpunkt in sorted(sighaltfallpunkte_alt - sighaltfallpunkte_neu, key = operator.itemgetter(0)):
                    unterschied = True
                    logging.info("{}: Signalhaltfallpunkt {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(refpunkt)))
                for refpunkt in sorted(sighaltfallpunkte_neu - sighaltfallpunkte_alt, key = operator.itemgetter(0)):
                    unterschied = True
                    logging.info("{}: Signalhaltfallpunkt {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(refpunkt)))

                # Teilaufloesepunkte
                teilaufloesepunkte_alt = set((int(aufl.get("Ref", 0)), aufl.find("./Datei").get("Dateiname", "").upper()) for aufl in fahrstr_alt.iterfind("./FahrstrTeilaufloesung"))
                teilaufloesepunkte_neu = set((aufl.refnr, aufl.element_richtung.element.modul.relpath.upper()) for aufl in fahrstr_neu.teilaufloesepunkte)

                for refpunkt in sorted(teilaufloesepunkte_alt - teilaufloesepunkte_neu, key = operator.itemgetter(0)):
                    unterschied = True
                    logging.info("{}: Teilaufloesung {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(refpunkt)))
                for refpunkt in sorted(teilaufloesepunkte_neu - teilaufloesepunkte_alt, key = operator.itemgetter(0)):
                    unterschied = True
                    logging.info("{}: Teilaufloesung {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(refpunkt)))

                # Weichen
                weichenstellungen_alt_vs_neu = defaultdict(dict)
                for weiche_alt in fahrstr_alt.findall("./FahrstrWeiche"):
                    weichenstellungen_alt_vs_neu[(int(weiche_alt.get("Ref", 0)), weiche_alt.find("./Datei").get("Dateiname", "").upper())]["alt"] = int(weiche_alt.get("FahrstrWeichenlage", 0))
                for weiche_neu in fahrstr_neu.weichen:
                    weichenstellungen_alt_vs_neu[(weiche_neu.refpunkt.refnr, weiche_neu.refpunkt.element_richtung.element.modul.relpath.upper())]["neu"] = weiche_neu.weichenlage

                for weichen_refpunkt, weichenstellungen in sorted(weichenstellungen_alt_vs_neu.items(), key = operator.itemgetter(0)):
                    if "alt" not in weichenstellungen:
                        unterschied = True
                        logging.info("{}: Weichenstellung {} (Nachfolger {}) ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(weichen_refpunkt), weichenstellungen["neu"]))
                    elif "neu" not in weichenstellungen:
                        unterschied = True
                        logging.info("{}: Weichenstellung {} (Nachfolger {}) ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(weichen_refpunkt), weichenstellungen["alt"]))
                    elif weichenstellungen["alt"] != weichenstellungen["neu"]:
                        unterschied = True
                        logging.info("{}: Weiche {} hat unterschiedliche Stellungen: {} vs. {}".format(name, refpunkt_fmt(weichen_refpunkt), weichenstellungen["alt"], weichenstellungen["neu"]))

                # Hauptsignale
                hsig_alt_vs_neu = defaultdict(dict)
                for hsig_alt in fahrstr_alt.findall("./FahrstrSignal"):
                    hsig_alt_vs_neu[(int(hsig_alt.get("Ref", 0)), hsig_alt.find("./Datei").get("Dateiname", "").upper())]["alt"] = (int(hsig_alt.get("FahrstrSignalZeile", 0)), int(hsig_alt.get("FahrstrSignalErsatzsignal", 0)) == 1)
                for hsig_neu in fahrstr_neu.signale:
                    hsig_alt_vs_neu[(hsig_neu.refpunkt.refnr, hsig_neu.refpunkt.element_richtung.element.modul.relpath.upper())]["neu"] = (hsig_neu.zeile, hsig_neu.ist_ersatzsignal)

                for hsig_refpunkt, hsig in sorted(hsig_alt_vs_neu.items(), key = operator.itemgetter(0)):
                    if "alt" not in hsig:
                        unterschied = True
                        logging.info("{}: Hauptsignalverknuepfung {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(hsig_refpunkt)))
                    elif "neu" not in hsig:
                        unterschied = True
                        logging.info("{}: Hauptsignalverknuepfung {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(hsig_refpunkt)))
                    elif hsig["alt"] != hsig["neu"]:
                        unterschied = True
                        logging.info("{}: Hauptsignalverknuepfung {} hat unterschiedliche Zeile: {} vs. {}".format(name, refpunkt_fmt(hsig_refpunkt), hsig["alt"], hsig["neu"]))

                # Vorsignale
                vsig_alt_vs_neu = defaultdict(dict)
                for vsig_alt in fahrstr_alt.findall("./FahrstrVSignal"):
                    vsig_alt_vs_neu[(int(vsig_alt.get("Ref", 0)), vsig_alt.find("./Datei").get("Dateiname", "").upper())]["alt"] = int(vsig_alt.get("FahrstrSignalSpalte", 0))
                for vsig_neu in fahrstr_neu.vorsignale:
                    vsig_alt_vs_neu[(vsig_neu.refpunkt.refnr, vsig_neu.refpunkt.element_richtung.element.modul.relpath.upper())]["neu"] = vsig_neu.spalte

                for vsig_refpunkt, vsig in sorted(vsig_alt_vs_neu.items(), key = operator.itemgetter(0)):
                    if "alt" not in vsig:
                        unterschied = True
                        logging.info("{}: Vorsignalverknuepfung {} ist in Zusi nicht vorhanden".format(name, refpunkt_fmt(vsig_refpunkt)))
                    elif "neu" not in vsig:
                        unterschied = True
                        logging.info("{}: Vorsignalverknuepfung {} ist in Zusi vorhanden, wurde aber nicht erzeugt".format(name, refpunkt_fmt(vsig_refpunkt)))
                    elif vsig["alt"] != vsig["neu"]:
                        unterschied = True
                        logging.info("{}: Vorsignalverknuepfung {} hat unterschiedliche Spalte: {} vs. {}".format(name, refpunkt_fmt(vsig_refpunkt), vsig["alt"], vsig["neu"]))

            logging.info("Fahrstrassen-Vergleich abgeschlossen.")
            return 2 if unterschied else 0

        return 0
    else:
        return 1

# http://stackoverflow.com/a/35365616/1083696
class LoggingHandlerFrame(tkinter.ttk.Frame):

    class Handler(logging.Handler):
        def __init__(self, widget):
            logging.Handler.__init__(self)
            self.setFormatter(logging.Formatter("%(message)s"))
            self.widget = widget

            self.widget.tag_config("error", foreground="red")
            self.widget.tag_config("warning", foreground="orange")
            self.widget.tag_config("info", foreground="blue")
            self.widget.tag_config("compat", foreground="purple")
            self.widget.tag_config("debug", foreground="gray")

        def emit(self, record):
            if record.levelno == logging.ERROR:
                self.widget.insert(tkinter.END, "Fehler: ", "error")
            elif record.levelno == logging.WARNING:
                self.widget.insert(tkinter.END, "Warnung: ", "warning")
            elif record.levelno == logging.INFO:
                self.widget.insert(tkinter.END, "Info: ", "info")
            elif record.levelno == logging.COMPAT:
                self.widget.insert(tkinter.END, "Kompatibilitaet: ", "compat")
            elif record.levelno == logging.DEBUG:
                self.widget.insert(tkinter.END, "Debug: ", "debug")
            else:
                self.widget.insert(tkinter.END, record.levelname + ": ")
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
    def btn_start_callback(vergleiche):
        ent_log.logging_handler.setLevel(var_debug_level.get())
        ent_log.clear()

        try:
            args = namedtuple('args', ['dateiname', 'modus', 'alternative_fahrwege', 'bedingungen', 'flankenschutz'])
            args.dateiname = ent_dateiname.get()
            args.fahrstr_typen = ",".join([
                "r" if var_typ_rangier.get() else "",
                "z" if var_typ_zug.get() else "",
                "a" if var_typ_anzeige.get() else ""])
            args.modus = 'vergleiche' if vergleiche else 'schreibe'
            args.alternative_fahrwege = var_alternative_fahrwege.get()
            args.flankenschutz = var_flankenschutz.get()
            args.bedingungen = None if ent_bedingungen.get() == '' else ent_bedingungen.get()
            finde_fahrstrassen(args)
        except Exception as e:
            logging.exception(e)

    def btn_dateiname_callback():
        filename = tkinter.filedialog.askopenfilename(initialdir=os.path.join(modulverwaltung.get_zusi_datapath(), 'Routes'), filetypes=[('ST3-Dateien', '.st3'), ('Alle Dateien', '*')])
        ent_dateiname.delete(0, tkinter.END)
        ent_dateiname.insert(0, filename)

        (bedingungen_filename, ext) = os.path.splitext(filename)
        bedingungen_filename += ".fahrstr_gen.xml"
        if os.path.exists(bedingungen_filename):
            ent_bedingungen.delete(0, tkinter.END)
            ent_bedingungen.insert(0, bedingungen_filename)

    def btn_bedingungen_callback():
        filename = tkinter.filedialog.askopenfilename(initialdir=os.path.join(modulverwaltung.get_zusi_datapath(), 'Routes'))
        ent_bedingungen.delete(0, tkinter.END)
        ent_bedingungen.insert(0, filename)

    def btn_logkopieren_callback():
        root.clipboard_clear()
        root.clipboard_append(ent_log.text.get(1.0, tkinter.END))

    global abfrage_janein
    abfrage_janein = abfrage_janein_gui

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

    frame_fahrstr_typen = tkinter.Frame(frame)

    var_typ_rangier = tkinter.BooleanVar()
    chk_typ_rangier = tkinter.Checkbutton(frame_fahrstr_typen, text="Rangierfahrstrassen", variable=var_typ_rangier)
    chk_typ_rangier.grid(row=0, column=1, sticky=tkinter.W)

    var_typ_zug = tkinter.BooleanVar()
    var_typ_zug.set(True)
    chk_typ_zug = tkinter.Checkbutton(frame_fahrstr_typen, text="Zugfahrstrassen", variable=var_typ_zug)
    chk_typ_zug.grid(row=0, column=2, sticky=tkinter.W)

    var_typ_anzeige = tkinter.BooleanVar()
    var_typ_anzeige.set(True)
    chk_typ_anzeige = tkinter.Checkbutton(frame_fahrstr_typen, text="Anzeige-Fahrstrassen", variable=var_typ_anzeige)
    chk_typ_anzeige.grid(row=0, column=3, sticky=tkinter.W)

    frame_fahrstr_typen.grid(row=15, column=1, sticky=(tkinter.W,tkinter.E))

    var_alternative_fahrwege = tkinter.BooleanVar()
    chk_alternative_fahrwege = tkinter.Checkbutton(frame, text="Alternative Fahrwege einrichten", variable=var_alternative_fahrwege)
    chk_alternative_fahrwege.grid(row=20, column=1, columnspan=2, sticky=tkinter.W)

    var_flankenschutz = tkinter.BooleanVar()
    chk_flankenschutz = tkinter.Checkbutton(frame, text="Weichen in Flankenschutz-Stellung verknuepfen", variable=var_flankenschutz)
    chk_flankenschutz.grid(row=25, column=1, columnspan=2, sticky=tkinter.W)

    lbl_debug = tkinter.Label(frame, text="Debug-Ausgaben: ")
    lbl_debug.grid(row=30, column=0, sticky=tkinter.W)

    frame_debug_level = tkinter.Frame(frame)

    var_debug_level = tkinter.IntVar()
    var_debug_level.set(logging.COMPAT)

    rad_debug_level_info = tkinter.Radiobutton(frame_debug_level, text="Keine", variable=var_debug_level, value=logging.INFO)
    rad_debug_level_info.grid(row=0, column=1, sticky=tkinter.W)
    rad_debug_level_compat = tkinter.Radiobutton(frame_debug_level, text="Kompatibilitaetsmeldungen", variable=var_debug_level, value=logging.COMPAT)
    rad_debug_level_compat.grid(row=0, column=2, sticky=tkinter.W)
    rad_debug_level_debug = tkinter.Radiobutton(frame_debug_level, text="Kompatibilitaets- und Debug-Meldungen", variable=var_debug_level, value=logging.DEBUG)
    rad_debug_level_debug.grid(row=0, column=3, sticky=tkinter.W)

    frame_debug_level.grid(row=30, column=1, sticky=(tkinter.W,tkinter.E))

    frame_start = tkinter.Frame(frame)
    frame_start.grid(row=98, columnspan=3, sticky='we')
    frame_start.columnconfigure(0, weight=1)
    frame_start.columnconfigure(1, weight=1)

    btn_start_vergleiche = tkinter.Button(frame_start, text="Fahrstr. erzeugen + mit existierenden vergleichen", command=lambda : btn_start_callback(True))
    btn_start_vergleiche.grid(row=0, column=0, sticky='we')
    btn_start_schreibe = tkinter.Button(frame_start, text="Fahrstr. erzeugen + ST3-Datei schreiben", command=lambda : btn_start_callback(False))
    btn_start_schreibe.grid(row=0, column=1, sticky='we')

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
        parser.add_argument('--modus', choices=['schreibe', 'vergleiche', 'profile'], default='schreibe', help="Modus \"vergleiche\" schreibt die Fahrstrassen nicht, sondern gibt stattdessen die Unterschiede zu den bestehenden Fahrstrassen aus.")
        parser.add_argument('--fahrstr_typen', default="zug,anzeige", help="Kommagetrennte Liste von zu generierenden Fahrstrassen-Typen (rangier, zug, anzeige)")
        parser.add_argument('--profile', choices=['profile', 'line_profiler'], help=argparse.SUPPRESS)
        parser.add_argument('--kompat', action='store_true', help="Kompatibilitaetsmeldungen anzeigen")
        parser.add_argument('--debug', action='store_true', help="Kompatibilitaetsmeldungen und Debug-Ausgaben anzeigen")
        parser.add_argument('--alternative_fahrwege', action='store_true', help="Alternative Fahrwege einrichten (Fahrstrassen fuer alle moeglichen Fahrwege zwischen Start- und Zielsignal erzeugen statt nur fuer den zuerst gefundenen)")
        parser.add_argument('--bedingungen', help="Datei mit Bedingungen fuer die Fahrstrassengenerierung")
        parser.add_argument('--flankenschutz', action='store_true', help="Weichen in Flankenschutzstellung in Fahrstrassen verknuepfen")
        args = parser.parse_args()

        logging.basicConfig(format='%(relativeCreated)d:%(levelname)s:%(message)s', level=(logging.DEBUG if args.debug else logging.COMPAT if args.kompat else logging.INFO))

        if args.profile == 'profile':
            import cProfile as profile, pstats
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
            sys.exit(finde_fahrstrassen(args))
