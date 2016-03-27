#!/usr/bin/env python3

import xml.etree.ElementTree as ET
from collections import namedtuple, defaultdict

from . import strecke
from .konstanten import *
from .strecke import ElementUndRichtung, geschw_min, ist_hsig_fuer_fahrstr_typ, nachfolger_elemente, element_laenge

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

        self.start = einzelfahrstrassen[0].start.refpunkt(REFTYP_SIGNAL, einzelfahrstrassen[0].startrichtung)
        if self.start is None:
            self.start = einzelfahrstrassen[0].start.refpunkt(REFTYP_AUFGLEISPUNKT, einzelfahrstrassen[0].startrichtung)

        self.ziel = einzelfahrstrassen[-1].ziel.refpunkt(REFTYP_SIGNAL, einzelfahrstrassen[-1].zielrichtung)

        # TODO: Setze Regelgleis/Gegengleis
        # TODO: Setze Richtungsanzeiger

        if self.start.reftyp == REFTYP_AUFGLEISPUNKT:
            self.name = "Aufgleispunkt"
        else:
            startsignal = self.start.signal()
            self.name = "{} {}".format(startsignal.attrib.get("NameBetriebsstelle", ""), startsignal.attrib.get("Signalname", ""))

        for idx, einzelfahrstrasse in enumerate(einzelfahrstrassen):
            self.laenge += einzelfahrstrasse.laenge

            zielkante = einzelfahrstrasse.kanten.eintrag
            zielsignal = zielkante.ziel.signal(zielkante.zielrichtung)
            self.name += " -> {} {}".format(zielsignal.attrib.get("NameBetriebsstelle", ""), zielsignal.attrib.get("Signalname", ""))

            # TODO: Hauptsignale (richtig) ansteuern: Startsignal mit oder ohne Ersatzsignal, Kennlichtsignale, Zielsignal auf -999

            for kante in einzelfahrstrasse.kantenliste():
                # TODO: Vorsignale ansteuern
                self.register.extend(kante.register)
                self.weichen.extend(kante.weichen)
                self.teilaufloesepunkte.extend(kante.aufloesepunkte)
                self.signalhaltfallpunkte.extend(kante.signalhaltfallpunkte)

        # TODO: Aufloesepunkte suchen (= Teilaufloesepunkte der naechsten Einzelfahrstrassen am Zielknoten)

    def to_xml(self):
        # TODO: FahrstrStrecke, RglGgl, Zufallswert
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

        self.start.to_xml(ET.SubElement(result, 'FahrstrStart'))
        self.ziel.to_xml(ET.SubElement(result, 'FahrstrZiel'))
        for rp in self.register:
            rp.to_xml(ET.SubElement(result, 'FahrstrRegister'))
        for rp in self.aufloesepunkte:
            rp.to_xml(ET.SubElement(result, 'FahrstrAufloesung'))
        for rp in self.aufloesepunkte:
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
        self.start = None
        self.startrichtung = None

        self.ziel = None
        self.zielrichtung = None

        self.kanten = None  # ListenEintrag
        self.laenge = 0  # Laenge in Metern
        self.signalgeschwindigkeit = -1.0  # Minimale Signalgeschwindigkeit

        self.rgl_ggl = GLEIS_BAHNHOF
        self.richtungsanzeiger = ""

    def erweitere(self, kante):
        if self.start is None:
            self.start = kante.start
            self.startrichtung = kante.startrichtung
        self.ziel = kante.ziel
        self.zielrichtung = kante.zielrichtung
        self.kanten = ListenEintrag(kante, self.kanten)
        self.laenge = self.laenge + kante.laenge
        self.signalgeschwindigkeit = geschw_min(self.signalgeschwindigkeit, kante.signalgeschwindigkeit)

        if self.rgl_ggl == GLEIS_BAHNHOF:
            self.rgl_ggl = kante.rgl_ggl
        if self.richtungsanzeiger == "":
            self.richtungsanzeiger = kante.richtungsanzeiger

    def erweiterte_kopie(self, kante):
        result = EinzelFahrstrasse()
        result.start = self.start
        result.startrichtung = self.startrichtung
        result.kanten = self.kanten
        result.laenge = self.laenge
        result.signalgeschwindigkeit = self.signalgeschwindigkeit
        result.rgl_ggl = self.rgl_ggl
        result.richtungsanzeiger = self.richtungsanzeiger
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
    def __init__(self, fahrstr_typ):
        self.fahrstr_typ = fahrstr_typ
        self.knoten = {}  # <StrElement> -> Knoten

    def ist_knoten(self, element):
        return (
            len([n for n in element if n.tag == "NachNorm" or n.tag == "NachNormModul"]) > 1 or
            len([n for n in element if n.tag == "NachGegen" or n.tag == "NachGegenModul"]) > 1 or
            ist_hsig_fuer_fahrstr_typ(element.find("./InfoNormRichtung/Signal"), self.fahrstr_typ) or
            ist_hsig_fuer_fahrstr_typ(element.find("./InfoGegenRichtung/Signal"), self.fahrstr_typ)
        )

    def get_knoten(self, modul, element):
        try:
            return self.knoten[element]
        except KeyError:
            result = Knoten(self, modul, element)
            self.knoten[element] = result
            return result

# Eine Kante im Streckengraphen. Sie besteht aus einer Liste von gerichteten Streckenelementen
# und enthaelt alle fahrstrassenrelevanten Daten (Signale, Weichen, Aufloesepunkte etc.)
# Eine Kante wird nur erzeugt, wenn sie fuer die Fahrstrasse relevant ist, also an einem
# Streckenelement mit Signal oder Weiche endet und kein Ereignis "Keine X-Fahrstrasse einrichten" enthaelt.
class Kante:
    def __init__(self, start, startrichtung):
        self.start = start
        self.startrichtung = startrichtung

        self.ziel = None  # Knoten
        self.zielrichtung = None  # Richtung

        self.elemente = []  # Elemente+Richtungen, ausschliesslich Startknoten-Element, einschliesslich Zielknoten-Element
        self.laenge = 0  # Laenge in Metern
        self.signalgeschwindigkeit = -1.0  # Minimale Signalgeschwindigkeit auf diesem Abschnitt

        self.register = []  # [RefPunkt]
        self.weichen = []  # [(RefPunkt, Weichenstellung)]
        self.signale = []  # [(RefPunkt, Signalzeile)] -- alle Signale, die nicht eine Fahrstrasse beenden, also z.B. Rangiersignale, sowie "Signal in Fahrstrasse verknuepfen"
        self.vorsignale = []  # [(RefPunkt, Signalspalte)]
        self.aufloesepunkte = []  # [RefPunkt]
        self.signalhaltfallpunkte = []  # RefPunkt

        self.rgl_ggl = GLEIS_BAHNHOF  # Regelgleis-/Gegengleiskennzeichnung dieses Abschnitts
        self.richtungsanzeiger = ""  # Richtungsanzeiger-Ziel dieses Abschnitts

# Ein Knoten im Streckengraphen ist ein relevantes Streckenelement, also eines, das eine Weiche oder ein Hauptsignal enthaelt.
class Knoten:
    def __init__(self, graph, modul, element):
        self.graph = graph  # Streckengraph
        self.modul = modul  # Modul
        self.element = element  # <StrElement>

        # Von den nachfolgenden Informationen existiert eine Liste pro Richtung.
        self.nachfolger_kanten = [None, None]
        self.vorgaenger_kanten = [None, None]
        self.einzelfahrstrassen = [None, None]

    def signal(self, richtung):
        return self.element.find("./Info" + ("Norm" if richtung == NORM else "Gegen") + "Richtung/Signal")

    def refpunkt(self, typ, richtung):
        for refpunkt in self.modul.referenzpunkte[self.element]:
            if refpunkt.richtung == richtung and refpunkt.reftyp == typ:
                return refpunkt
        return None

    # Gibt alle von diesem Knoten ausgehenden (kombinierten) Fahrstrassen in der angegebenen Richtung zurueck.
    def get_fahrstrassen(self, richtung):
        logging.debug("Suche Fahrstrassen ab {} {}{}".format(self.modul.relpath, self.element.attrib["Nr"], 'n' if richtung == NORM else 'g'))
        result = []
        for einzelfahrstrasse in self.get_einzelfahrstrassen(richtung):
            self._get_fahrstrassen_rek([einzelfahrstrasse], result)
        # TODO: filtern nach Loeschliste in self.modul
        return result

    # Gibt alle von diesem Knoten ausgehenden Einzelfahrstrassen in der angegebenen Richtung zurueck.
    def get_einzelfahrstrassen(self, richtung):
        key = 0 if richtung == NORM else 1
        if self.einzelfahrstrassen[key] is None:
            logging.debug("Suche Einzelfahrstrassen ab {} {}{}".format(self.modul.relpath, self.element.attrib["Nr"], 'n' if richtung == NORM else 'g'))
            self.einzelfahrstrassen[key] = self._get_einzelfahrstrassen(richtung)
        return self.einzelfahrstrassen[key]

    # Gibt alle von diesem Knoten ausgehenden Nachfolgerkanten in der angegebenen Richtung zurueck.
    def get_nachfolger_kanten(self, richtung):
        key = 0 if richtung == NORM else 1
        if self.nachfolger_kanten[key] is None:
            logging.debug("Suche Nachfolgerkanten ab {} {}{}".format(self.modul.relpath, self.element.attrib["Nr"], 'n' if richtung == NORM else 'g'))
            self.nachfolger_kanten[key] = []
            nachfolger = nachfolger_elemente(ElementUndRichtung(self.modul, self.element, richtung))
            for idx, n in enumerate(nachfolger):
                kante = Kante(self, richtung)
                if len(nachfolger) > 1:
                    # TODO: Weichenstellung 'idx+1' des aktuellen Elements in die Kante einfuegen
                    pass
                kante = self._neue_nachfolger_kante(kante, n)
                self.nachfolger_kanten[key].append(kante)
        return self.nachfolger_kanten[key]

    # Erweitert die angegebene Kante, die am Nachfolger 'el_r' (Nachfolgerelement Nummer 'idx') dieses Knotens beginnt.
    # Gibt None zurueck, wenn keine fahrstrassenrelevante Kante existiert.
    def _neue_nachfolger_kante(self, kante, element_richtung):
        if element_richtung is None:
            return None

        while element_richtung is not None:
            # TODO: Signal am aktuellen Element in die Signalliste einfuegen
            # TODO: Register am aktuellen Element in die Registerliste einfuegen

            # Ereignisse am aktuellen Element verarbeiten
            for ereignis in element_richtung.element.findall("./Info" + ('Norm' if element_richtung.richtung == NORM else 'Gegen') + "Richtung/Ereignis"):
                ereignis_nr = int(ereignis.attrib.get("Er", 0))
                if ereignis_nr == EREIGNIS_SIGNALGESCHWINDIGKEIT:
                    kante.signalgeschwindigkeit = geschw_min(kante.signalgeschwindigkeit, float(ereignis.attrib.get("Wert", 0)))
                elif ereignis_nr == EREIGNIS_SIGNALHALTFALL:
                    pass
                elif ereignis_nr == EREIGNIS_KEINE_LZB_FAHRSTRASSE:
                    # TODO: vom Fahrstrassen-Typ abhaengig machen
                    pass
                elif ereignis_nr == EREIGNIS_KEINE_ZUGFAHRSTRASSE:
                    # TODO: vom Fahrstrassen-Typ abhaengig machen
                    return None
                elif ereignis_nr == EREIGNIS_KEINE_RANGIERFAHRSTRASSE:
                    # TODO: vom Fahrstrassen-Typ abhaengig machen
                    pass
                elif ereignis_nr == EREIGNIS_FAHRSTRASSE_AUFLOESEN:
                    # TODO: in Liste von Aufloesepunkten einfuegen
                    pass

                elif ereignis_nr == EREIGNIS_GEGENGLEIS:
                    if kante.rgl_ggl == GLEIS_BAHNHOF:
                        kante.rgl_ggl = GLEIS_GEGENGLEIS
                    else:
                        # TODO: Warnmeldung
                        pass

                elif ereignis_nr == EREIGNIS_REGELGLEIS:
                    if kante.rgl_ggl == GLEIS_BAHNHOF:
                        kante.rgl_ggl = GLEIS_REGELGLEIS
                    else:
                        # TODO: Warnmeldung
                        pass

                elif ereignis_nr == EREIGNIS_EINGLEISIG:
                    if kante.rgl_ggl == GLEIS_BAHNHOF:
                        kante.rgl_ggl = GLEIS_EINGLEISIG
                    else:
                        # TODO: Warnmeldung
                        pass

                elif ereignis_nr == EREIGNIS_RICHTUNGSANZEIGER_ZIEL:
                    if kante.richtungsanzeiger == "":
                        kante.richtungsanzeiger = ereignis.attrib.get("Beschr", "")
                    else:
                        # TODO: Warnmeldung
                        pass

                elif ereignis_nr == EREIGNIS_REGISTER_VERKNUEPFEN:
                    # TODO: in Liste von Registern einfuegen
                    pass
                elif ereignis_nr == EREIGNIS_WEICHE_VERKNUEPFEN:
                    # TODO: in Liste von Weichen einfuegen
                    pass
                elif ereignis_nr == EREIGNIS_SIGNAL_VERKNUEPFEN:
                    # TODO: in Liste von Signalen einfuegen
                    pass
                elif ereignis_nr == EREIGNIS_VORSIGNAL_VERKNUEPFEN:
                    # TODO: in Liste von Vorsignalen einfuegen
                    pass

            kante.elemente.append(element_richtung)
            kante.laenge += element_laenge(element_richtung.element)

            if self.graph.ist_knoten(element_richtung.element):
                # TODO: eventuelle stumpf befahrene Weiche als Weichenverknuepfung eintragen
                break

            nachfolger = nachfolger_elemente(element_richtung)
            if len(nachfolger) == 0:
                element_richtung = None
            else:
                assert(len(nachfolger) == 1)  # sonst waere es ein Knoten
                element_richtung = nachfolger[0]

        if element_richtung is None:
            return None
        else:
            kante.ziel = self.graph.get_knoten(element_richtung.modul, element_richtung.element)
            kante.zielrichtung = element_richtung.richtung

        return kante

    # Gibt alle Einzelfahrstrassen zurueck, die an diesem Knoten in der angegebenen Richtung beginnen.
    # Pro Zielsignal wird nur eine Einzelfahrstrasse behalten, auch wenn alternative Fahrwege existieren.
    # Es wird moeglichst die Fahrstrasse mit der hoechsten Signalgeschwindigkeit behalten, als zweites Kriterium
    # wird die Fahrstrasse mit der kuerzesten Gesamtlaenge behalten.
    def _get_einzelfahrstrassen(self, richtung):
        # Zielsignal-Knoten -> [EinzelFahrstrasse]
        einzelfahrstrassen_by_zielsignal = defaultdict(list)
        for kante in self.get_nachfolger_kanten(richtung):
            if kante is not None:
                f = EinzelFahrstrasse()
                f.erweitere(kante)
                self._get_einzelfahrstrassen_rek(f, einzelfahrstrassen_by_zielsignal)

        result = []
        for zielsignal, einzelfahrstrassen in einzelfahrstrassen_by_zielsignal.items():
            # TODO: sortieren nach a) Signalgeschwindigkeit, b) Laenge
            result.append(einzelfahrstrassen[0])

        return result

    # Erweitert die angegebene Einzelfahrstrasse rekursiv ueber Kanten, bis ein Hauptsignal erreicht wird,
    # und fuegt die resultierenden Einzelfahrstrassen in das Ergebnis-Dict ein.
    def _get_einzelfahrstrassen_rek(self, fahrstrasse, ergebnis_dict):
        # Sind wir am Hauptsignal?
        signal = fahrstrasse.ziel.signal(fahrstrasse.zielrichtung)
        if ist_hsig_fuer_fahrstr_typ(signal, self.graph.fahrstr_typ):
            logging.debug("Zielsignal gefunden: {} {}".format(signal.attrib.get("NameBetriebsstelle", "?"), signal.attrib.get("Signalname", "?")))
            ergebnis_dict[fahrstrasse.ziel].append(fahrstrasse)
            return

        folgekanten = fahrstrasse.ziel.get_nachfolger_kanten(fahrstrasse.zielrichtung)
        if len(folgekanten) == 1:
            if folgekanten[0] is not None:
                fahrstrasse.erweitere(folgekanten[0])
                self._get_einzelfahrstrassen_rek(fahrstrasse, ergebnis_dict)
        else:
            for kante in folgekanten:
                if kante is not None:
                    self._get_einzelfahrstrassen_rek(fahrstrasse.erweiterte_kopie(kante), ergebnis_dict)

    def _get_fahrstrassen_rek(self, einzelfahrstr_liste, ziel_liste):
        letzte_fahrstrasse = einzelfahrstr_liste[-1]
        zielknoten = letzte_fahrstrasse.kanten.eintrag.ziel
        zielrichtung = letzte_fahrstrasse.kanten.eintrag.zielrichtung
        zielsignal = zielknoten.signal(zielrichtung)
        ziel_flags = int(zielsignal.attrib.get("SignalFlags", 0))

        fahrstr_abschliessen = True
        fahrstr_weiterfuehren = False

        if ziel_flags & SIGFLAG_KENNLICHT_VORGAENGERSIGNAL != 0:
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
                # if startsignal is None or int(startsignal.attrib.get("SignalFlags", 0)) & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL == 0:

        if ziel_flags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL != 0:
            fahrstr_weiterfuehren = True

        logging.debug("Fahrstrassensuche: an {} {}, Kennlicht Vorgaenger={}, Kennlicht Nachfolger={}, abschl={}, weiter={}".format(
            zielsignal.attrib.get("NameBetriebsstelle", ""), zielsignal.attrib.get("Signalname", ""),
            ziel_flags & SIGFLAG_KENNLICHT_VORGAENGERSIGNAL != 0, ziel_flags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL != 0,
            fahrstr_abschliessen, fahrstr_weiterfuehren))

        if fahrstr_abschliessen:
            ziel_liste.append(Fahrstrasse(self.graph.fahrstr_typ, einzelfahrstr_liste))
        if fahrstr_weiterfuehren:
            for einzelfahrstrasse in zielknoten.get_einzelfahrstrassen(zielrichtung):
                self._get_fahrstrassen_rek(einzelfahrstr_liste + [einzelfahrstrasse], ziel_liste)
