#!/usr/bin/env python3

import xml.etree.ElementTree as ET
from collections import namedtuple, defaultdict

from . import strecke
from .konstanten import *
from .strecke import *

import logging

# Eintrag in einer verketteten Liste
ListenEintrag = namedtuple('Listeneintrag', ['eintrag', 'prev'])

FahrstrWeichenstellung = namedtuple('FahrstrWeichenstellung', ['refpunkt', 'weichenlage'])
FahrstrHauptsignal = namedtuple('FahrstrHauptsignal', ['refpunkt', 'zeile', 'ist_ersatzsignal'])
FahrstrVorsignal = namedtuple('FahrstrVorsignal', ['refpunkt', 'spalte'])

# Eine (simulatortaugliche) Fahrstrasse, die aus einer oder mehreren Einzeifahrstrassen besteht.
class Fahrstrasse:
    def __init__(self, fahrstr_typ, einzelfahrstrassen):
        self.fahrstr_typ = fahrstr_typ
        self.register = []  # [RefPunkt]
        self.weichen = []  # [FahrstrWeichenstellung]
        self.signale = []  # [FahrstrHauptsignal]
        self.vorsignale = []  # [FahrstrVorsignal]
        self.teilaufloesepunkte = [] # [RefPunkt]
        self.aufloesepunkte = [] # [RefPunkt]
        self.signalhaltfallpunkte = [] # [RefPunkt]
        self.laenge = 0

        # Setze Start und Ziel
        self.start = einzelfahrstrassen[0].start.refpunkt(REFTYP_SIGNAL)
        if self.start is None or not ist_hsig_fuer_fahrstr_typ(self.start.signal(), self.fahrstr_typ):
            self.start = einzelfahrstrassen[0].start.refpunkt(REFTYP_AUFGLEISPUNKT)

        self.ziel = einzelfahrstrassen[-1].ziel.refpunkt(REFTYP_SIGNAL)
        self.zufallswert = float(self.ziel.signal().xml_knoten.get("Zufallswert", 0))

        self.name = "LZB: " if self.fahrstr_typ == FAHRSTR_TYP_LZB else ""

        if self.start.reftyp == REFTYP_AUFGLEISPUNKT:
            self.name += "Aufgleispunkt"
        else:
            self.name += self.start.signal().signalbeschreibung()

        # Setze Name, Laenge, Regelgleis/Gegengleis/Streckenname/Richtungsanzeiger
        self.rgl_ggl = GLEIS_BAHNHOF
        self.streckenname = ""
        self.richtungsanzeiger = ""
        for einzelfahrstrasse in einzelfahrstrassen:
            self.laenge += einzelfahrstrasse.laenge

            zielkante = einzelfahrstrasse.kanten.eintrag
            self.name += " -> {}".format(zielkante.ziel.signal().signalbeschreibung())

            for kante in einzelfahrstrasse.kantenliste():
                if kante.rgl_ggl != GLEIS_BAHNHOF:
                    self.rgl_ggl = kante.rgl_ggl
                    self.streckenname = kante.streckenname
                if kante.richtungsanzeiger != "":
                    self.richtungsanzeiger = kante.richtungsanzeiger

        # Ereignis "Signalgeschwindigkeit" im Zielsignal setzt Geschwindigkeit fuer die gesamte Fahrstrasse
        if self.ziel.signal().signalgeschwindigkeit is not None:
            self.signalgeschwindigkeit = self.ziel.signal().signalgeschwindigkeit
        else:
            self.signalgeschwindigkeit = -1.0
            for einzelfahrstrasse in einzelfahrstrassen:
                self.signalgeschwindigkeit = geschw_min(self.signalgeschwindigkeit, einzelfahrstrasse.signalgeschwindigkeit)

        logging.debug("{}: Signalgeschwindigkeit {}, Richtungsanzeiger \"{}\"".format(self.name, str_geschw(self.signalgeschwindigkeit), self.richtungsanzeiger))

        for idx, einzelfahrstrasse in enumerate(einzelfahrstrassen):
            if idx == 0:
                # Startsignal ansteuern
                if ist_hsig_fuer_fahrstr_typ(self.start.signal(), self.fahrstr_typ):
                    zeile_ersatzsignal = self.start.signal().get_hsig_ersatzsignal_zeile(self.rgl_ggl)
                    zeile_regulaer = self.start.signal().get_hsig_zeile(self.fahrstr_typ, self.signalgeschwindigkeit)
                    nutze_ersatzsignal = self.ziel.signal().ist_hilfshauptsignal

                    if nutze_ersatzsignal and zeile_ersatzsignal is None:
                        logging.warn("{}: Startsignal hat keine Ersatzsignal-Zeile fuer RglGgl-Angabe {}. Zwecks Kompatibilitaet mit Zusi wird die regulaere Matrix angesteuert.".format(self.name, self.rgl_ggl))
                        nutze_ersatzsignal = False
                    elif not nutze_ersatzsignal and zeile_regulaer is None:
                        logging.warn("{}: Startsignal hat keine Zeile fuer Geschwindigkeit {}. Zwecks Kompatibilitaet mit Zusi wird die Ersatzsignal-Matrix angesteuert.".format(self.name, str_geschw(self.signalgeschwindigkeit)))
                        nutze_ersatzsignal = True

                    if nutze_ersatzsignal:
                        if zeile_ersatzsignal is None:
                            logging.warn("{}: Startsignal hat keine Ersatzsignal-Zeile fuer RglGgl-Angabe {}. Die Signalverknuepfung wird nicht eingerichtet.".format(self.name, self.rgl_ggl))
                        else:
                            # TODO Richtungsanzeiger
                            self.signale.append(FahrstrHauptsignal(self.start, zeile_ersatzsignal, True))
                    else:
                        if zeile_regulaer is None:
                            logging.warn("{}: Startsignal hat keine Zeile fuer Geschwindigkeit {}. Die Signalverknuepfung wird nicht eingerichtet.".format(self.name, str_geschw(self.signalgeschwindigkeit)))
                        else:
                            zeile_regulaer = self.start.signal().get_richtungsanzeiger_zeile(zeile_regulaer, self.rgl_ggl, self.richtungsanzeiger)
                            self.signale.append(FahrstrHauptsignal(self.start, zeile_regulaer, False))
            else:
                # Kennlichtsignal ansteuern
                gefunden = False
                for idx, zeile in enumerate(einzelfahrstrasse.start.signal().zeilen):
                    if zeile.hsig_geschw == -2.0:
                        refpunkt = einzelfahrstrasse.start.refpunkt(REFTYP_SIGNAL)
                        if refpunkt is None:
                            logging.warn("Element {} enthaelt ein Signal, aber es existiert kein passender Referenzpunkt. Die Signalverknuepfung wird nicht eingerichtet.".format(einzelfahrstrasse.start))
                        else:
                            kennlichtsignal_zeile = einzelfahrstrasse.start.signal().get_richtungsanzeiger_zeile(idx, self.rgl_ggl, self.richtungsanzeiger)
                            self.signale.append(FahrstrHauptsignal(refpunkt, kennlichtsignal_zeile, False))
                        gefunden = True
                        break

                if not gefunden:
                    logging.warn("{}: An Signal {} wurde keine Kennlichtzeile (Geschwindigkeit -2) gefunden".format(self.name, einzelfahrstrasse.start.signal()))

            # Zielsignal ansteuern mit Geschwindigkeit -999, falls vorhanden
            if idx == len(einzelfahrstrassen) - 1:
                for idx, zeile in enumerate(self.ziel.signal().zeilen):
                    if zeile.hsig_geschw == -999.0:
                        self.signale.append(FahrstrHauptsignal(self.ziel, idx, False))
                        break

            for kante in einzelfahrstrasse.kantenliste():
                self.register.extend(kante.register)
                self.weichen.extend(kante.weichen)
                for refpunkt in kante.aufloesepunkte:
                    if refpunkt.reftyp == REFTYP_AUFLOESEPUNKT:
                        # Aufloesepunkte im Zielelement zaehlen als Aufloesung der gesamten Fahrstrasse, nicht als Teilaufloesung.
                        if refpunkt.element_richtung == self.ziel.element_richtung:
                            self.aufloesepunkte.append(refpunkt)
                        else:
                            self.teilaufloesepunkte.append(refpunkt)
                self.signalhaltfallpunkte.extend([refpunkt for refpunkt in kante.aufloesepunkte if refpunkt.reftyp == REFTYP_SIGNALHALTFALL])
                for signal_verkn in kante.signale:
                    if signal_verkn.zeile != -1:
                        self.signale.append(signal_verkn)
                    else:
                        zeile = signal_verkn.refpunkt.signal().get_hsig_zeile(self.fahrstr_typ, self.signalgeschwindigkeit)
                        if zeile is None:
                            logging.warn("{}: Signal {} ({}) hat keine Zeile fuer Geschwindigkeit {}".format(self.name, signal_verkn.refpunkt.signal(), signal_verkn.refpunkt, str_geschw(self.signalgeschwindigkeit)))
                        else:
                            zeile = signal_verkn.refpunkt.signal().get_richtungsanzeiger_zeile(zeile, self.rgl_ggl, self.richtungsanzeiger)
                            self.signale.append(FahrstrHauptsignal(signal_verkn.refpunkt, zeile, False))
                self.vorsignale.extend(kante.vorsignale)

        # Aufloesepunkte suchen. Wenn wir vorher schon einen Aufloesepunkt gefunden haben, lag er im Zielelement der Fahrstrasse,
        # und es muss nicht weiter gesucht werden.
        if len(self.aufloesepunkte) == 0:
            for aufl in einzelfahrstrassen[-1].ziel.knoten.get_aufloesepunkte(einzelfahrstrassen[-1].ziel.richtung):
                if aufl.reftyp == REFTYP_SIGNALHALTFALL:
                    self.signalhaltfallpunkte.append(aufl)
                else:
                    self.aufloesepunkte.append(aufl)

        # Vorsignale ansteuern. Erst *nach* Abarbeiten aller Einzelfahrstrassen, da deren Ereignisse "Vorsignal in Fahrstrasse verknuepfen" Prioritaet haben!
        if self.start.reftyp == REFTYP_SIGNAL and len(self.signale) > 0 and not self.signale[0].ist_ersatzsignal:
            for vsig in einzelfahrstrassen[0].start.knoten.get_vorsignale(einzelfahrstrassen[0].start.richtung):
                if not any(vsig == vsig_existiert.refpunkt for vsig_existiert in self.vorsignale):
                    spalte = None
                    if self.fahrstr_typ == FAHRSTR_TYP_LZB:
                        for idx, spalten_geschw in enumerate(vsig.signal().spalten):
                            if spalten_geschw == -2.0:
                                spalte = idx
                                break
                        if spalte is None:
                            logging.debug("{}: An Signal {} ({}) wurde keine Vorsignalspalte fuer Geschwindigkeit -2 (Dunkelschaltung) gefunden. Suche Vorsignalspalte gemaess Signalgeschwindigkeit {}".format(self.name, vsig.signal(), vsig.element_richtung, self.signalgeschwindigkeit))
                    if spalte is None:
                        spalte = vsig.signal().get_vsig_spalte(self.signalgeschwindigkeit)

                    if len(vsig.signal().richtungsvoranzeiger) > 0:
                        spalte = vsig.signal().get_richtungsvoranzeiger_spalte(0 if spalte is None else spalte, self.rgl_ggl, self.richtungsanzeiger)
                    if spalte is None:
                        logging.warn("{}: An Signal {} ({}) wurde keine Vorsignalspalte fuer Geschwindigkeit {} gefunden".format(self.name, vsig.signal(), vsig.element_richtung, str_geschw(self.signalgeschwindigkeit)))
                    else:
                        self.vorsignale.append(FahrstrVorsignal(vsig, spalte))

    def to_xml(self):
        result = ET.Element('Fahrstrasse', {
            "FahrstrName": self.name,
            "Laenge": "{:.1f}".format(self.laenge)
        })
        if self.fahrstr_typ == FAHRSTR_TYP_RANGIER:
            result.attrib["FahrstrTyp"] = "TypRangier"
        elif self.fahrstr_typ == FAHRSTR_TYP_ZUG:
            result.attrib["FahrstrTyp"] = "TypZug"
        elif self.fahrstr_typ == FAHRSTR_TYP_LZB:
            result.attrib["FahrstrTyp"] = "TypLZB"

        if self.zufallswert != 0:
            result.set("Zufallwert", str(self.zufallswert))
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
        self.signalgeschwindigkeit = -1.0  # Minimale Signalgeschwindigkeit
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
        assert(kante.ziel is not None)
        if self.start is None:
            self.start = kante.start
        self.ziel = kante.ziel
        self.kanten = ListenEintrag(kante, self.kanten)
        self.laenge = self.laenge + kante.laenge
        if not self.hat_ende_weichenbereich:
            self.signalgeschwindigkeit = geschw_min(self.signalgeschwindigkeit, kante.signalgeschwindigkeit)
        self.hat_ende_weichenbereich = self.hat_ende_weichenbereich or kante.hat_ende_weichenbereich

    def erweiterte_kopie(self, kante):
        result = EinzelFahrstrasse()
        result.start = self.start
        result.kanten = self.kanten
        result.laenge = self.laenge
        result.signalgeschwindigkeit = self.signalgeschwindigkeit
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

# Ein Graph, der eine Strecke auf der untersten uns interessierenden Ebene beschreibt:
# Knoten sind Elemente mit Weichenfunktion oder Hauptsignal fuer den gewuenschten
# Fahrstrassentyp.
class Streckengraph:
    def __init__(self, fahrstr_typ, vorsignal_graph = None):
        self.fahrstr_typ = fahrstr_typ
        self.knoten = {}  # <StrElement> -> Knoten
        self.vorsignal_graph = vorsignal_graph
        self._besuchszaehler = 1  # Ein Knoten gilt als besucht, wenn sein Besuchszaehler gleich dem Besuchszaehler des Graphen ist. Alle Knoten koennen durch Inkrementieren des Besuchszaehlers als unbesucht markiert werden.

    def markiere_unbesucht(self):
        self._besuchszaehler += 1

    def ist_knoten(self, element):
        if len([n for n in element.xml_knoten if n.tag == "NachNorm" or n.tag == "NachNormModul"]) > 1 or \
                len([n for n in element.xml_knoten if n.tag == "NachGegen" or n.tag == "NachGegenModul"]) > 1:
            return True

        if self.fahrstr_typ == FAHRSTR_TYP_VORSIGNALE:
            return (
                ist_hsig_fuer_fahrstr_typ(element.signal(NORM), FAHRSTR_TYP_ZUG) or
                ist_hsig_fuer_fahrstr_typ(element.signal(GEGEN), FAHRSTR_TYP_ZUG)
            )
        else:
            return (
                ist_hsig_fuer_fahrstr_typ(element.signal(NORM), self.fahrstr_typ) or
                ist_hsig_fuer_fahrstr_typ(element.signal(GEGEN), self.fahrstr_typ)
            )

    def get_knoten(self, element):
        try:
            return self.knoten[element]
        except KeyError:
            result = Knoten(self, element)
            self.knoten[element] = result
            return result

# Eine Kante zwischen zwei Knoten im Streckengraphen. Sie enthaelt alle fahrstrassenrelevanten Daten (Signale, Weichen, Aufloesepunkte etc.)
# einer Folge von gerichteten Streckenelementen zwischen den beiden Knoten (exklusive Start, inklusive Ziel, inklusive Start-Weichenstellung).
class Kante:
    def __init__(self, start):
        self.start = start  # KnotenUndRichtung
        self.ziel = None  # KnotenUndRichtung

        self.laenge = 0  # Laenge in Metern
        self.signalgeschwindigkeit = -1.0  # Minimale Signalgeschwindigkeit auf diesem Abschnitt

        self.register = []  # [RefPunkt]
        self.weichen = []  # [FahrstrWeichenstellung]
        self.signale = []  # [FahrstrHauptsignal] -- alle Signale, die nicht eine Fahrstrasse beenden, also z.B. Rangiersignale, sowie "Signal in Fahrstrasse verknuepfen". Wenn die Signalzeile den Wert -1 hat, ist die zu waehlende Zeile fahrstrassenabhaengig.
        self.vorsignale = []  # [FahrstrVorsignal] -- nur Vorsignale, die mit "Vorsignal in Fahrstrasse verknuepfen" in einem Streckenelement dieser Kante verknuepft sind
        self.aufloesepunkte = []  # [RefPunkt] -- Signalhaltfall- und Aufloesepunkte. Reihenfolge ist wichtig!

        self.rgl_ggl = GLEIS_BAHNHOF  # Regelgleis-/Gegengleiskennzeichnung dieses Abschnitts
        self.streckenname = ""  # Streckenname (Teil der Regelgleis-/Gegengleiskennzeichnung)
        self.richtungsanzeiger = ""  # Richtungsanzeiger-Ziel dieses Abschnitts

        self.hat_ende_weichenbereich = False  # Liegt im Verlauf dieser Kante ein Ereignis "Ende Weichenbereich"?

    def __repr__(self):
        return "Kante<{} -> {}>".format(self.start, self.ziel)

# Eine Kante zwischen zwei Knoten im Streckengraphen, die alle Vorsignale auf dem Weg zwischen zwei Knoten (rueckwaerts) enthaelt.
# Der Zielknoten ist also ein *Vorgaenger* des Startknotens.
# Der Zielknoten ist None, wenn die Kante an einem Element ohne Vorgaenger oder mit Ereignis "Vorher keine Vsig-Verknuepfung" endet.
class VorsignalKante:
    def __init__(self):
        self.ziel = None  # KnotenUndRichtung
        self.vorsignale = []
        self.vorher_keine_vsig_verknuepfung = False

# Ein Knoten im Streckengraphen ist ein relevantes Streckenelement, also eines, das eine Weiche oder ein Hauptsignal enthaelt.
class Knoten:
    def __init__(self, graph, element):
        self.graph = graph  # Streckengraph
        self.element = element  # Instanz der Klasse Element (Tupel aus Modul und <StrElement>-Knoten)

        # Von den nachfolgenden Informationen existiert eine Liste pro Richtung.
        self.nachfolger_kanten = [None, None]
        self.einzelfahrstrassen = [None, None]
        self.aufloesepunkte = [None, None]  # Aufloesepunkte bis zum naechsten Zugfahrt-Hauptsignal.

        # Nur im Vorsignal-Streckengraphen
        self.vorsignal_kanten = [None, None]
        self.vorsignale = [None, None]

        self._besuchszaehler = self.graph._besuchszaehler - 1  # Dokumentation siehe Streckengraph._besuchszaehler

    def __repr__(self):
        return "Knoten<{}>".format(repr(self.element))

    def __str__(self):
        return str(self.element)

    def ist_besucht(self):
        return self._besuchszaehler >= self.graph._besuchszaehler

    def markiere_besucht(self):
        self._besuchszaehler = self.graph._besuchszaehler

    def richtung(self, richtung):
        return KnotenUndRichtung(self, richtung)

    def signal(self, richtung):
        return self.element.signal(richtung)

    def refpunkt(self, richtung, typ):
        return self.element.refpunkt(richtung, typ)

    # Gibt alle von diesem Knoten ausgehenden (kombinierten) Fahrstrassen in der angegebenen Richtung zurueck.
    def get_fahrstrassen(self, richtung):
        logging.debug("Suche Fahrstrassen ab {}".format(self.richtung(richtung)))
        result = []
        for einzelfahrstrasse in self.get_einzelfahrstrassen(richtung):
            self._get_fahrstrassen_rek([einzelfahrstrasse], result)
        # TODO: filtern nach Loeschliste in self.modul
        return result

    # Gibt alle von diesem Knoten ausgehenden Einzelfahrstrassen in der angegebenen Richtung zurueck.
    def get_einzelfahrstrassen(self, richtung):
        key = 0 if richtung == NORM else 1
        if self.einzelfahrstrassen[key] is None:
            logging.debug("Suche Einzelfahrstrassen ab {}".format(self.richtung(richtung)))
            self.einzelfahrstrassen[key] = self._get_einzelfahrstrassen(richtung)
        return self.einzelfahrstrassen[key]

    # Gibt alle von diesem Knoten in der angegebenen Richtung erreichbaren Signalhaltfall- und Aufloesepunkte bis zum naechsten Hauptsignal.
    # Die Suche stoppt jeweils nach dem ersten gefundenen Aufloesepunkt.
    def get_aufloesepunkte(self, richtung):
        key = 0 if richtung == NORM else 1
        if self.aufloesepunkte[key] is None:
            logging.debug("Suche Aufloesepunkte ab {}".format(self.richtung(richtung)))
            self.aufloesepunkte[key] = self._get_aufloesepunkte(richtung)
        return self.aufloesepunkte[key]

    def get_vorsignale(self, richtung):
        if self.graph.fahrstr_typ != FAHRSTR_TYP_VORSIGNALE:
            if self.graph.vorsignal_graph is not None:
                return self.graph.vorsignal_graph.get_knoten(self.element).get_vorsignale(richtung)
            else:
                return []

        key = 0 if richtung == NORM else 1
        if self.vorsignale[key] is None:
            logging.debug("Suche Vorsignale ab {}".format(self.richtung(richtung)))
            self.vorsignale[key] = self._get_vorsignale(richtung)
        return self.vorsignale[key]

    # Gibt alle von diesem Knoten ausgehenden Nachfolgerkanten in der angegebenen Richtung zurueck.
    # Eine Kante wird nur komplett erzeugt, wenn sie fuer die Fahrstrasse relevant ist, also an einem
    # Streckenelement mit Signal oder Weiche endet und kein Ereignis "Keine X-Fahrstrasse einrichten" enthaelt.
    # Andernfalls wird sie zwar erzeugt (zwecks Signalhaltfall-/Aufloeseelementen), aber ihr Zielknoten ist dann None.
    def get_nachfolger_kanten(self, richtung):
        key = 0 if richtung == NORM else 1
        if self.nachfolger_kanten[key] is None:
            logging.debug("Suche Nachfolgerkanten ab {}".format(self.richtung(richtung)))
            self.nachfolger_kanten[key] = []
            nachfolger = self.element.richtung(richtung).nachfolger()

            weichen_refpunkt = None
            if len(nachfolger) > 1:
                # Weichenstellung am Startelement in die Kante mit aufnehmen
                weichen_refpunkt = self.element.refpunkt(richtung, REFTYP_WEICHE)
                if weichen_refpunkt is None:
                    logging.warn(("Element {} hat mehr als einen Nachfolger in {} Richtung, aber keinen Referenzpunkteintrag vom Typ Weiche. " +
                            "Es werden keine Fahrstrassen ueber dieses Element erzeugt.").format(
                            self.element.element.attrib["Nr"], "blauer" if richtung == NORM else "gruener"))
                    self.nachfolger_kanten[key] = [None] * len(nachfolger)
                    return

            for idx, n in enumerate(nachfolger):
                kante = Kante(self.richtung(richtung))
                # Ende Weichenbereich wirkt schon im Startelement
                kante.hat_ende_weichenbereich = any(int(ereignis.get("Er", 0)) == 1000002 for ereignis in self.element.ereignisse(richtung))
                if weichen_refpunkt is not None:
                    kante.weichen.append(FahrstrWeichenstellung(weichen_refpunkt, idx + 1))
                kante = self._neue_nachfolger_kante(kante, n)
                if kante is not None:
                    self.nachfolger_kanten[key].append(kante)
        return self.nachfolger_kanten[key]

    # Gibt alle von diesem Knoten ausgehenden Vorsignalkanten in der angegebenen Richtung zurueck (gesucht wird also in der Gegenrichtung).
    def get_vorsignal_kanten(self, richtung):
        key = 0 if richtung == NORM else 1
        if self.vorsignal_kanten[key] is None:
            # TODO: Vorher keine Vsig-Verknuepfung im Element selbst?
            logging.debug("Suche Vorsignal-Kanten ab {}".format(self.richtung(richtung)))
            self.vorsignal_kanten[key] = []
            for v in self.element.richtung(richtung).vorgaenger():
                if v is not None:
                    kante = VorsignalKante()
                    self.vorsignal_kanten[key].append(self._neue_vorsignal_kante(kante, v))
        return self.vorsignal_kanten[key]


    # Erweitert die angegebene Kante, die am Nachfolger 'element_richtung' dieses Knotens beginnt.
    # Gibt None zurueck, wenn keine fahrstrassenrelevante Kante existiert.
    def _neue_nachfolger_kante(self, kante, element_richtung):
        while element_richtung is not None:
            # Bei Ereignis "Keine Fahrstrasse einrichten" sofort abbrechen (keine weiteren Ereignisse/Signale an diesem Element betrachten)
            keine_fahrstr_einrichten = False
            for ereignis in element_richtung.ereignisse():
                ereignis_nr = int(ereignis.get("Er", 0))
                if ereignis_nr in [EREIGNIS_KEINE_LZB_FAHRSTRASSE, EREIGNIS_LZB_ENDE] and self.graph.fahrstr_typ == FAHRSTR_TYP_LZB \
                        or ereignis_nr == EREIGNIS_KEINE_ZUGFAHRSTRASSE and self.graph.fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_LZB] \
                        or ereignis_nr == EREIGNIS_KEINE_RANGIERFAHRSTRASSE and self.graph.fahrstr_typ == FAHRSTR_TYP_RANGIER:
                    keine_fahrstr_einrichten = True
                    break

            if keine_fahrstr_einrichten:
                logging.debug("{}: Keine Fahrstrasse einrichten".format(element_richtung))
                element_richtung = None
                break

            # Signal am aktuellen Element in die Signalliste einfuegen
            signal = element_richtung.signal()
            if signal is not None and not signal.ist_hsig_fuer_fahrstr_typ(self.graph.fahrstr_typ):
                verkn = False
                zeile = -1

                # Hauptsignale, die nicht dem aktuellen Fahrstrassentyp entsprechen, auf -1 stellen:
                if signal.ist_hsig_fuer_fahrstr_typ(FAHRSTR_TYP_LZB):
                    zeile = signal.get_hsig_zeile(FAHRSTR_TYP_LZB, -1)
                    if zeile is None:
                        logging.warn("Signal an Element {} enthaelt keine passende Zeile fuer Fahrstrassentyp LZB und Geschwindigkeit -1. Die Signalverknuepfung wird nicht eingerichtet.".format(element_richtung))
                    else:
                        logging.debug("Signal an Element {}: LZB-Hauptsignal bei Nicht-LZB-Fahrstrasse umstellen (Geschwindigkeit -1/Zeile {})".format(element_richtung, zeile))
                        verkn = True
                elif signal.ist_hsig_fuer_fahrstr_typ(FAHRSTR_TYP_RANGIER):
                    if signal.sigflags & SIGFLAG_RANGIERSIGNAL_BEI_ZUGFAHRSTR_UMSTELLEN != 0:
                        zeile = signal.get_hsig_zeile(FAHRSTR_TYP_RANGIER, -1)
                        if zeile is None:
                            logging.warn("Signal an Element {} enthaelt keine passende Zeile fuer Fahrstrassentyp Rangier und Geschwindigkeit -1. Die Signalverknuepfung wird nicht eingerichtet.".format(element_richtung))
                        else:
                            logging.debug("Signal an Element {}: Rangiersignal bei Zug- oder LZB-Fahrstrasse umstellen (Geschwindigkeit -1/Zeile {})".format(element_richtung, zeile))
                            verkn = True
                elif signal.ist_hsig_fuer_fahrstr_typ(FAHRSTR_TYP_FAHRWEG):
                    if signal.sigflags & SIGFLAG_FAHRWEGSIGNAL_WEICHENANIMATION == 0:
                        zeile = signal.get_hsig_zeile(FAHRSTR_TYP_FAHRWEG, -1)
                        if zeile is None:
                            logging.warn("Signal an Element {} enthaelt keine passende Zeile fuer Fahrstrassentyp Fahrweg und Geschwindigkeit -1. Die Signalverknuepfung wird nicht eingerichtet.".format(element_richtung))
                        else:
                            logging.debug("Signal an Element {}: Fahrwegsignal (ausser Weichenanimation) bei Fahrstrasse umstellen (Geschwindigkeit -1/Zeile {})".format(element_richtung, zeile))
                            verkn = True

                # Signale, die mehr als eine Zeile haben, stehen potenziell auf der falschen Zeile (z.B. durch Verknuepfung aus anderen Fahrstrassen)
                # und muessen deshalb zumindest in Grundstellung gebracht werden.
                # Betrachte aber nur Signale, die zumindest eine Zeile fuer den aktuellen Fahrstrassentyp besitzen.
                elif len(signal.zeilen) >= 2 and any(zeile.fahrstr_typ & self.graph.fahrstr_typ != 0 for zeile in signal.zeilen):
                    verkn = True
                    logging.debug("Signal an Element {}: hat mehr als eine Zeile (Zeile noch unbekannt)".format(element_richtung))
                    # Zeile muss ermittelt werden

                # Signale, die einen Richtungs- oder Gegengleisanzeiger haben
                elif signal.gegengleisanzeiger != 0 or len(signal.richtungsanzeiger) > 0:
                    verkn = True
                    logging.debug("Signal an Element {}: hat Richtungs- oder Gegengleisanzeiger (Zeile noch unbekannt)".format(element_richtung))
                    # Zeile muss ermittelt werden

                else:
                    logging.debug("Signal an Element {}: wird nicht in die Fahrstrasse aufgenommen".format(element_richtung))

                if verkn:
                    refpunkt = element_richtung.refpunkt(REFTYP_SIGNAL)
                    if refpunkt is None:
                        logging.warn("Element {} enthaelt ein Signal, aber es existiert kein passender Referenzpunkt. Die Signalverknuepfung wird nicht eingerichtet.".format(element_richtung))
                    else:
                        kante.signale.append(FahrstrHauptsignal(refpunkt, zeile, False))

            # Signal am aktuellen Element (Gegenrichtung) in die Signalliste einfuegen
            element_richtung_gegenrichtung = element_richtung.gegenrichtung()
            signal_gegenrichtung = element_richtung_gegenrichtung.signal()
            if signal_gegenrichtung is not None \
                    and signal_gegenrichtung.sigflags & SIGFLAG_FAHRWEGSIGNAL_BEIDE_FAHRTRICHTUNGEN != 0 \
                    and signal_gegenrichtung.sigflags & SIGFLAG_FAHRWEGSIGNAL_WEICHENANIMATION == 0 \
                    and signal_gegenrichtung.ist_hsig_fuer_fahrstr_typ(FAHRSTR_TYP_FAHRWEG):
                refpunkt = element_richtung_gegenrichtung.refpunkt(REFTYP_SIGNAL)
                if refpunkt is None:
                    logging.warn("Element {} enthaelt ein Signal, aber es existiert kein passender Referenzpunkt. Die Signalverknuepfung wird nicht eingerichtet.".format(element_richtung_gegenrichtung))
                else:
                    zeile = signal_gegenrichtung.get_hsig_zeile(FAHRSTR_TYP_FAHRWEG, -1)
                    if zeile is None:
                        logging.warn("Signal an Element {} enthaelt keine passende Zeile fuer Fahrstrassentyp Fahrweg und Geschwindigkeit -1. Die Signalverknuepfung wird nicht eingerichtet.".format(element_richtung_gegenrichtung))
                    else:
                        kante.signale.append(FahrstrHauptsignal(refpunkt, zeile, False))

            # Register am aktuellen Element in die Registerliste einfuegen
            regnr = element_richtung.registernr()
            if regnr != 0:
                refpunkt = element_richtung.refpunkt(REFTYP_REGISTER)
                if refpunkt is None:
                    logging.warn("Element {} enthaelt ein Register, aber es existiert kein passender Referenzpunkt. Die Registerverknuepfung wird nicht eingerichtet.".format(element_richtung))
                else:
                    kante.register.append(refpunkt)

            # Ereignisse am aktuellen Element verarbeiten
            hat_ende_weichenbereich = False
            for ereignis in element_richtung.ereignisse():
                ereignis_nr = int(ereignis.get("Er", 0))
                if ereignis_nr == EREIGNIS_SIGNALGESCHWINDIGKEIT:
                    if not kante.hat_ende_weichenbereich:
                        kante.signalgeschwindigkeit = geschw_min(kante.signalgeschwindigkeit, float(ereignis.get("Wert", 0)))

                elif ereignis_nr == EREIGNIS_ENDE_WEICHENBEREICH:
                    hat_ende_weichenbereich = True # wird erst am Element danach wirksam

                elif ereignis_nr == EREIGNIS_GEGENGLEIS:
                    kante.rgl_ggl = GLEIS_GEGENGLEIS
                    kante.streckenname = ereignis.get("Beschr", "")

                elif ereignis_nr == EREIGNIS_REGELGLEIS:
                    kante.rgl_ggl = GLEIS_REGELGLEIS
                    kante.streckenname = ereignis.get("Beschr", "")

                elif ereignis_nr == EREIGNIS_EINGLEISIG:
                    kante.rgl_ggl = GLEIS_EINGLEISIG
                    kante.streckenname = ereignis.get("Beschr", "")

                elif ereignis_nr == EREIGNIS_RICHTUNGSANZEIGER_ZIEL:
                    kante.richtungsanzeiger = ereignis.get("Beschr", "")

                elif ereignis_nr == EREIGNIS_FAHRSTRASSE_AUFLOESEN:
                    refpunkt = element_richtung.refpunkt(REFTYP_AUFLOESEPUNKT)
                    if refpunkt is None:
                        logging.warn("Element {} enthaelt ein Ereignis \"Fahrstrasse aufloesen\", aber es existiert kein passender Referenzpunkt. Die Aufloese-Verknuepfung wird nicht eingerichtet.".format(element_richtung))
                    else:
                        kante.aufloesepunkte.append(refpunkt)

                elif ereignis_nr == EREIGNIS_SIGNALHALTFALL:
                    refpunkt = element_richtung.refpunkt(REFTYP_SIGNALHALTFALL)
                    if refpunkt is None:
                        logging.warn("Element {} enthaelt ein Ereignis \"Signalhaltfall\", aber es existiert kein passender Referenzpunkt. Die Signalhaltfall-Verknuepfung wird nicht eingerichtet.".format(element_richtung))
                    else:
                        kante.aufloesepunkte.append(refpunkt)

                elif ereignis_nr == EREIGNIS_REGISTER_VERKNUEPFEN:
                    try:
                        kante.register.append(element_richtung.element.modul.referenzpunkte_by_nr[int(float(ereignis.get("Wert", 0)))])
                    except (KeyError, ValueError):
                        logging.warn("Ereignis \"Register in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltige Referenzpunkt-Nummer \"{}\". Die Registerverknuepfung wird nicht eingerichtet.".format(element_richtung, ereignis.get("Wert", 0)))
                        continue

                elif ereignis_nr == EREIGNIS_WEICHE_VERKNUEPFEN:
                    try:
                        refpunkt = element_richtung.element.modul.referenzpunkte_by_nr[int(float(ereignis.get("Wert", 0)))]
                    except (KeyError, ValueError):
                        logging.warn("Ereignis \"Weiche in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltige Referenzpunkt-Nummer \"{}\". Die Weichenverknuepfung wird nicht eingerichtet.".format(element_richtung, ereignis.get("Wert", 0)))
                        continue

                    try:
                        weichenstellung = int(ereignis.get("Beschr", 0))
                    except ValueError:
                        logging.warn("Ereignis \"Weiche in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltige Weichenstellung \"{}\". Die Weichenverknuepfung wird nicht eingerichtet.".format(element_richtung, ereignis.get("Beschr", "")))

                    if weichenstellung <= 0:
                        logging.warn("Ereignis \"Weiche in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltige Weichenstellung {}. Die Weichenverknuepfung wird nicht eingerichtet.".format(element_richtung, weichenstellung))
                    else:
                        kante.weichen.append(FahrstrWeichenstellung(refpunkt, int(ereignis.get("Beschr", ""))))

                elif ereignis_nr == EREIGNIS_SIGNAL_VERKNUEPFEN:
                    try:
                        refpunkt = element_richtung.element.modul.referenzpunkte_by_nr[int(float(ereignis.get("Wert", 0)))]
                    except (KeyError, ValueError):
                        logging.warn("Ereignis \"Signal in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltige Referenzpunkt-Nummer \"{}\". Die Signalverknuepfung wird nicht eingerichtet.".format(element_richtung, ereignis.get("Wert", 0)))
                        continue

                    try:
                        kante.signale.append(FahrstrHauptsignal(refpunkt, int(ereignis.get("Beschr", "")), False))
                        logging.debug("Signal an Element {}: wird per \"Signal an Fahrstrasse verknuepfen\" an Element {} in dessen Fahrstrassen aufgenommen".format(refpunkt.element_richtung, element_richtung))
                    except ValueError:
                        logging.warn("Ereignis \"Signal in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltige Zeilennummer {}. Die Signalverknuepfung wird nicht eingerichtet.".format(element_richtung, ereignis.get("Beschr", "")))

                elif ereignis_nr == EREIGNIS_VORSIGNAL_VERKNUEPFEN:
                    try:
                        refpunkt = element_richtung.element.modul.referenzpunkte_by_nr[int(float(ereignis.get("Wert", 0)))]
                    except (KeyError, ValueError):
                        logging.warn("Ereignis \"Vorsignal in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltige Referenzpunkt-Nummer \"{}\". Die Vorsignalverknuepfung wird nicht eingerichtet.".format(element_richtung, ereignis.get("Wert", 0)))
                        continue

                    try:
                        kante.vorsignale.append(FahrstrVorsignal(refpunkt, int(ereignis.get("Beschr", ""))))
                    except ValueError:
                        logging.warn("Ereignis \"Vorsignal in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltige Spaltennummer {}. Die Vorsignalverknuepfung wird nicht eingerichtet.".format(element_richtung, ereignis.get("Beschr", "")))

            kante.hat_ende_weichenbereich = kante.hat_ende_weichenbereich or hat_ende_weichenbereich
            kante.laenge += element_richtung.element.laenge()

            if self.graph.ist_knoten(element_richtung.element):
                break

            nachfolger = element_richtung.nachfolger()
            if len(nachfolger) == 0:
                element_richtung = None
                break

            assert(len(nachfolger) == 1)  # sonst waere es ein Knoten
            element_richtung_neu = nachfolger[0]

            if element_richtung_neu is None:
                element_richtung = None
                break

            nachfolger_vorgaenger = element_richtung_neu.vorgaenger()
            if nachfolger_vorgaenger is not None and len(nachfolger_vorgaenger) > 1:
                # Stumpf befahrene Weiche stellen
                weichen_refpunkt = self.graph.get_knoten(element_richtung_neu.element).refpunkt(gegenrichtung(element_richtung_neu.richtung), REFTYP_WEICHE)
                if weichen_refpunkt is None:
                    logging.warn(("Element {} hat mehr als einen Vorgaenger in {} Richtung, aber keinen Referenzpunkteintrag vom Typ Weiche. " +
                            "Es werden keine Fahrstrassen ueber dieses Element erzeugt.").format(
                            self.element.attrib["Nr"], "blauer" if richtung == NORM else "gruener"))
                    return None

                try:
                    kante.weichen.append(FahrstrWeichenstellung(weichen_refpunkt, nachfolger_vorgaenger.index(element_richtung) + 1))
                except ValueError:
                    logging.warn(("Stellung der stumpf befahrenen Weiche an Element {} {} von Element {} {} kommend konnte nicht ermittelt werden. " +
                            "Es werden keine Fahrstrassen ueber das letztere Element erzeugt.").format(
                            element_richtung_neu.element.attrib["Nr"], "blau" if element_richtung_neu.richtung == NORM else "gruen",
                            element_richtung.element.attrib["Nr"], "blau" if element_richtung.richtung == NORM else "gruen"))
                    return None

            element_richtung = element_richtung_neu

        if element_richtung is not None:
            kante.ziel = KnotenUndRichtung(self.graph.get_knoten(element_richtung.element), element_richtung.richtung)

        return kante

    # Erweitert die angegebene Vorsignal-Kante, die am Vorgaenger 'element_richtung' dieses Knotens beginnt.
    def _neue_vorsignal_kante(self, kante, element_richtung):
        while element_richtung is not None:
            signal = element_richtung.signal()
            if signal is not None and (signal.ist_vsig() or len(signal.richtungsvoranzeiger) > 0):
                refpunkt = element_richtung.refpunkt(REFTYP_SIGNAL)
                if refpunkt is None:
                    logging.warn("Element {} enthaelt ein Vorsignal, aber es existiert kein passender Referenzpunkt. Die Vorsignalverknuepfung wird nicht eingerichtet.".format(element_richtung))
                else:
                    logging.debug("Vorsignal an {}".format(refpunkt))
                    kante.vorsignale.append(refpunkt)

            for ereignis in element_richtung.ereignisse():
                ereignis_nr = int(ereignis.get("Er", 0))
                if ereignis_nr == EREIGNIS_VORHER_KEINE_VSIG_VERKNUEPFUNG:
                    kante.vorher_keine_vsig_verknuepfung = True
                    break
                elif ereignis_nr == EREIGNIS_KEINE_ZUGFAHRSTRASSE:
                    kante.vorher_keine_vsig_verknuepfung = True
                    break

            if self.graph.ist_knoten(element_richtung.element):
                kante.ziel = KnotenUndRichtung(self.graph.get_knoten(element_richtung.element), element_richtung.richtung)
                if ist_hsig_fuer_fahrstr_typ(element_richtung.signal(), FAHRSTR_TYP_ZUG) and \
                        element_richtung.signal().sigflags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL == 0 and \
                        element_richtung.signal().sigflags & SIGFLAG_KENNLICHT_VORGAENGERSIGNAL == 0:
                    kante.vorher_keine_vsig_verknuepfung = True
                break

            if kante.vorher_keine_vsig_verknuepfung:
                break

            vorgaenger = element_richtung.vorgaenger()
            if len(vorgaenger) == 0:
                element_richtung = None
                break

            assert(len(vorgaenger) == 1)  # sonst waere es ein Knoten
            element_richtung = vorgaenger[0]

        return kante

    # Gibt alle Einzelfahrstrassen zurueck, die an diesem Knoten in der angegebenen Richtung beginnen.
    # Pro Zielsignal wird nur eine Einzelfahrstrasse behalten, auch wenn alternative Fahrwege existieren.
    def _get_einzelfahrstrassen(self, richtung):
        # Zielsignal-Refpunkt -> [EinzelFahrstrasse]
        einzelfahrstrassen_by_zielsignal = defaultdict(list)
        for kante in self.get_nachfolger_kanten(richtung):
            if kante.ziel is not None:
                f = EinzelFahrstrasse()
                f.erweitere(kante)
                self._get_einzelfahrstrassen_rek(f, einzelfahrstrassen_by_zielsignal)

        result = []
        for ziel_refpunkt, einzelfahrstrassen in einzelfahrstrassen_by_zielsignal.items():
            if len(einzelfahrstrassen) > 1:
                logging.debug("{} Einzelfahrstrassen zu {} gefunden: {}".format(
                    len(einzelfahrstrassen), ziel_refpunkt.signal(),
                    " / ".join("{} km/h, {:.2f} m".format(strecke.str_geschw(einzelfahrstrasse.signalgeschwindigkeit), einzelfahrstrasse.laenge) for einzelfahrstrasse in einzelfahrstrassen)))
            # result.append(min(einzelfahrstrassen, key = lambda fstr: (float_geschw(fstr.signalgeschwindigkeit), fstr.laenge)))
            result.append(einzelfahrstrassen[0])

        return result

    # Erweitert die angegebene Einzelfahrstrasse rekursiv ueber Kanten, bis ein Hauptsignal erreicht wird,
    # und fuegt die resultierenden Einzelfahrstrassen in das Ergebnis-Dict ein.
    def _get_einzelfahrstrassen_rek(self, fahrstrasse, ergebnis_dict):
        # Sind wir am Hauptsignal?
        signal = fahrstrasse.ziel.signal()
        if ist_hsig_fuer_fahrstr_typ(signal, self.graph.fahrstr_typ):
            logging.debug("Zielsignal gefunden: {}".format(signal))
            ergebnis_dict[fahrstrasse.ziel.refpunkt(REFTYP_SIGNAL)].append(fahrstrasse)
            return

        folgekanten = fahrstrasse.ziel.knoten.get_nachfolger_kanten(fahrstrasse.ziel.richtung)
        for idx, kante in enumerate(folgekanten):
            if kante.ziel is None:
                continue

            if idx == len(folgekanten) - 1:
                fahrstrasse.erweitere(kante)
                self._get_einzelfahrstrassen_rek(fahrstrasse, ergebnis_dict)
            else:
                self._get_einzelfahrstrassen_rek(fahrstrasse.erweiterte_kopie(kante), ergebnis_dict)

    def _get_fahrstrassen_rek(self, einzelfahrstr_liste, ziel_liste):
        letzte_fahrstrasse = einzelfahrstr_liste[-1]
        zielknoten = letzte_fahrstrasse.kanten.eintrag.ziel.knoten
        zielrichtung = letzte_fahrstrasse.kanten.eintrag.ziel.richtung
        zielsignal = zielknoten.signal(zielrichtung)

        fahrstr_abschliessen = True
        fahrstr_weiterfuehren = False

        if zielsignal.sigflags & SIGFLAG_KENNLICHT_VORGAENGERSIGNAL != 0:
            # Fahrstrasse nur abschliessen, wenn schon ein Signal mit "Kennlichtschaltung Nachfolgersignal" aufgenommen wurde.
            # Ansonsten Fahrstrasse weiterfuehren.

            # TODO: Wenn mehr als eine Einzelfahrstrasse vorhanden ist, dann ist auf jeden Fall ein Kennlichtsignal beteiligt?
            if len(einzelfahrstr_liste) == 1:
                fahrstr_abschliessen = False
                fahrstr_weiterfuehren = True
                
                # erste_fahrstrasse = einzelfahrstr_liste[0]
                # startknoten = erste_fahrstrasse.kanten.eintrag.start
                # startrichtung = erste_fahrstrasse.kanten.eintrag.startrichtung
                # startsignal = startknoten.signal(startrichtung)
                # if startsignal is None or int(startsignal.get("SignalFlags", 0)) & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL == 0:

        if zielsignal.sigflags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL != 0:
            fahrstr_weiterfuehren = True

        logging.debug("Fahrstrassensuche: an {}, Kennlicht Vorgaenger={}, Kennlicht Nachfolger={}, abschl={}, weiter={}".format(
            zielsignal,
            zielsignal.sigflags & SIGFLAG_KENNLICHT_VORGAENGERSIGNAL != 0, zielsignal.sigflags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL != 0,
            fahrstr_abschliessen, fahrstr_weiterfuehren))

        if fahrstr_abschliessen:
            ziel_liste.append(Fahrstrasse(self.graph.fahrstr_typ, einzelfahrstr_liste))
        if fahrstr_weiterfuehren:
            for einzelfahrstrasse in zielknoten.get_einzelfahrstrassen(zielrichtung):
                self._get_fahrstrassen_rek(einzelfahrstr_liste + [einzelfahrstrasse], ziel_liste)

    def _get_aufloesepunkte(self, richtung):
        self.graph.markiere_unbesucht()
        result = []
        for kante in self.get_nachfolger_kanten(richtung):
            self._get_aufloesepunkte_rek(richtung, kante, result)
        return result

    def _get_aufloesepunkte_rek(self, startrichtung, kante, result_liste):
        aufloesepunkt_gefunden = False
        for aufl in kante.aufloesepunkte:
            # Aufloeseelement im Zielknoten nur einfuegen, wenn dieser noch nicht besucht wurde,
            # sonst wird es mehrmals eingefuegt.
            if kante.ziel is None or aufl.element_richtung.element != kante.ziel.knoten.element or not kante.ziel.knoten.ist_besucht():
                logging.debug("Aufloesepunkt an {}".format(aufl))
                result_liste.append(aufl)
            if aufl.reftyp == REFTYP_AUFLOESEPUNKT:
                aufloesepunkt_gefunden = True
                break

        if aufloesepunkt_gefunden:
            return

        if kante.ziel is not None and not kante.ziel.knoten.ist_besucht():
            kante.ziel.knoten.markiere_besucht()
            if ist_hsig_fuer_fahrstr_typ(kante.ziel.signal(), FAHRSTR_TYP_ZUG):
                if not aufloesepunkt_gefunden:
                    logging.warn("Es gibt einen Fahrweg zwischen den Signalen {} ({}) und {} ({}), der keinen Aufloesepunkt (fuer am ersten Signal endende Fahrstrassen) enthaelt.".format(self.signal(startrichtung), self.richtung(startrichtung), kante.ziel.signal(), kante.ziel))
            else:
                for kante in kante.ziel.knoten.get_nachfolger_kanten(kante.ziel.richtung):
                    self._get_aufloesepunkte_rek(startrichtung, kante, result_liste)

    def _get_vorsignale(self, richtung):
        self.graph.markiere_unbesucht()
        result = []
        for kante in self.get_vorsignal_kanten(richtung):
            self._get_vorsignale_rek(kante, result)
        return result

    def _get_vorsignale_rek(self, kante, result_liste):
        result_liste.extend(kante.vorsignale)

        if not kante.vorher_keine_vsig_verknuepfung and kante.ziel is not None and not kante.ziel.knoten.ist_besucht():
            kante.ziel.knoten.markiere_besucht()
            for kante2 in kante.ziel.knoten.get_vorsignal_kanten(kante.ziel.richtung):
                self._get_vorsignale_rek(kante2, result_liste)

class KnotenUndRichtung(namedtuple('KnotenUndRichtung', ['knoten', 'richtung'])):
    def __repr__(self):
        return repr(self.knoten) + ("b" if self.richtung == NORM else "g")

    def __str__(self):
        return str(self.knoten) + ("b" if self.richtung == NORM else "g")

    def signal(self):
        return self.knoten.element.signal(self.richtung)

    def refpunkt(self, typ):
        return self.knoten.element.refpunkt(self.richtung, typ)
