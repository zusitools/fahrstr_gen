#!/usr/bin/env python3

import xml.etree.ElementTree as ET
import logging
from collections import namedtuple

from .konstanten import *
from .strecke import geschw_min

# Eintrag in einer verketteten Liste
ListenEintrag = namedtuple('Listeneintrag', ['eintrag', 'prev'])

FahrstrWeichenstellung = namedtuple('FahrstrWeichenstellung', ['refpunkt', 'weichenlage'])
FahrstrHauptsignal = namedtuple('FahrstrHauptsignal', ['refpunkt', 'zeile', 'ist_ersatzsignal'])
FahrstrVorsignal = namedtuple('FahrstrVorsignal', ['refpunkt', 'spalte'])

FahrstrFlankenschutzWeichenstellung = namedtuple('FahrstrFlankenschutzStellung', ['refpunkt', 'weichenlage', 'abstand'])  # Abstand zum Gefahrpunkt, dient als Prioritaet bei mehreren Flankenschutzstellungen

# Eine (simulatortaugliche) Fahrstrasse, die aus einer oder mehreren Einzeifahrstrassen besteht.
class Fahrstrasse:
    def __init__(self, fahrstr_typ):
        self.fahrstr_typ = fahrstr_typ
        self.name = ""
        self.start = None # RefPunkt
        self.ziel = None # RefPunkt
        self.zufallswert = 0 # float

        self.register = []  # [RefPunkt]
        self.weichen = []  # [FahrstrWeichenstellung]
        self.signale = []  # [FahrstrHauptsignal]
        self.vorsignale = []  # [FahrstrVorsignal]
        self.teilaufloesepunkte = [] # [RefPunkt]
        self.aufloesepunkte = [] # [RefPunkt]
        self.signalhaltfallpunkte = [] # [RefPunkt]

        self.laenge = 0
        self.laenge_zusi = 0  # Die Laenge, wie sie Zusi berechnet (Bug moduluebergreifende Fahrstrassen)
        self.laenge_zusi_vor_3_1_7_2 = 0  # Die Laenge, wie sie Zusi vor 3D-Editor 3.1.7.2 berechnet (Bug moduluebergreifende Fahrstrassen und inklusive Start-, exklusive Zielelement)
        self.signalgeschwindigkeiten = [-1.0]

        self.rgl_ggl = GLEIS_BAHNHOF
        self.streckenname = ""
        self.richtungsanzeiger = ""

    def to_xml(self):
        result = ET.Element('Fahrstrasse', {
            "FahrstrName": self.name,
            "Laenge": "{:.1f}".format(self.laenge)
        })
        if self.fahrstr_typ == FAHRSTR_TYP_RANGIER:
            result.attrib["FahrstrTyp"] = "TypRangier"
        elif self.fahrstr_typ == FAHRSTR_TYP_ZUG:
            result.attrib["FahrstrTyp"] = "TypZug"
        elif self.fahrstr_typ == FAHRSTR_TYP_ANZEIGE:
            result.attrib["FahrstrTyp"] = "TypAnzeige"

        if self.zufallswert != 0:
            result.set("ZufallsWert", "{:f}".format(self.zufallswert).rstrip('0').rstrip('.'))
        if self.rgl_ggl != 0:
            result.set("RglGgl", str(self.rgl_ggl))
        if len(self.streckenname) > 0:
            result.set("FahrstrStrecke", self.streckenname)

        self.start.to_xml(ET.SubElement(result, 'FahrstrStart'))
        self.ziel.to_xml(ET.SubElement(result, 'FahrstrZiel'))
        for rp in self.register:
            rp.to_xml(ET.SubElement(result, 'FahrstrRegister'))
        for rp in self.aufloesepunkte:
            rp.to_xml(ET.SubElement(result, 'FahrstrAufloesung'))
        for rp in self.teilaufloesepunkte:
            rp.to_xml(ET.SubElement(result, 'FahrstrTeilaufloesung'))
        for rp in self.signalhaltfallpunkte:
            rp.to_xml(ET.SubElement(result, 'FahrstrSigHaltfall'))
        for weiche in self.weichen:
            el = ET.SubElement(result, 'FahrstrWeiche')
            if weiche.weichenlage != 0:
                el.attrib["FahrstrWeichenlage"] = str(weiche.weichenlage)
            weiche.refpunkt.to_xml(el)
        for signal in self.signale:
            el = ET.SubElement(result, 'FahrstrSignal')
            if signal.zeile != 0:
                el.attrib["FahrstrSignalZeile"] = str(signal.zeile)
            if signal.ist_ersatzsignal:
                el.attrib["FahrstrSignalErsatzsignal"] = "1"
            signal.refpunkt.to_xml(el)
        for vorsignal in self.vorsignale:
            el = ET.SubElement(result, 'FahrstrVSignal')
            if vorsignal.spalte != 0:
                el.attrib["FahrstrSignalSpalte"] = str(vorsignal.spalte)
            vorsignal.refpunkt.to_xml(el)

        return result

# Eine einzelne Fahrstrasse (= Liste von Kanten)
# von einem Hauptsignal oder Aufgleispunkt zu einem Hauptsignal,
# ohne dazwischenliegende Hauptsignale (etwa fuer Kennlichtschaltungen).
class EinzelFahrstrasse:
    def __init__(self):
        self.start = None # KnotenUndRichtung
        self.ziel = None  # KnotenUndRichtung

        self.kanten = None  # ListenEintrag
        self.laenge = 0  # Laenge in Metern
        self.laenge_zusi = 0  # Laenge in Metern, wie sie Zusi berechnet (Bug moduluebergreifende Fahrstrassen)
        self.signalgeschwindigkeiten = []   # Minimale Signalgeschwindigkeit getrennt nach allen allein stehenden Zs3
        self.signalgeschwindigkeiten.append(-1.0)
        self.hat_ende_weichenbereich = False  # Wurde im Verlauf der Erstellung dieser Fahrstrasse schon ein Weichenbereich-Ende angetroffen?

    def __repr__(self):
        if self.kanten is None:
            return "EinzelFahrstrasse<>"
        weg = str(self.kanten.eintrag.ziel)
        kante = self.kanten
        while kante is not None:
            weg = "{} -> {}".format(kante.eintrag.start, weg)
            kante = kante.prev
        return "EinzelFahrstrasse<{}>".format(weg)

    def erweitere(self, kante):
        assert kante.ziel is not None
        if self.start is None:
            self.start = kante.start
        self.ziel = kante.ziel
        self.kanten = ListenEintrag(kante, self.kanten)
        self.laenge += kante.laenge
        self.laenge_zusi += kante.laenge_zusi
        if not self.hat_ende_weichenbereich:
            self.signalgeschwindigkeiten[len(self.signalgeschwindigkeiten) - 1] = geschw_min(self.signalgeschwindigkeiten[len(self.signalgeschwindigkeiten) - 1], kante.signalgeschwindigkeit)
        if kante.hat_zusatzanzeiger:
            self.signalgeschwindigkeiten.append(-1)
        self.hat_ende_weichenbereich = self.hat_ende_weichenbereich or kante.hat_ende_weichenbereich

    def erweiterte_kopie(self, kante):
        result = EinzelFahrstrasse()
        result.start = self.start
        result.kanten = self.kanten
        result.laenge = self.laenge
        result.laenge_zusi = self.laenge_zusi
        result.signalgeschwindigkeiten = self.signalgeschwindigkeiten.copy()
        result.hat_ende_weichenbereich = self.hat_ende_weichenbereich
        result.erweitere(kante)
        return result

    def kantenliste(self):
        result = []
        kante = self.kanten
        while kante is not None:
            result.append(kante.eintrag)
            kante = kante.prev
        result.reverse()
        return result
