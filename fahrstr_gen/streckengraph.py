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

        # Setze Regelgleis/Gegengleis/Streckenname
        self.rgl_ggl = GLEIS_BAHNHOF
        self.streckenname = ""
        for einzelfahrstrasse in einzelfahrstrassen:
            for kante in einzelfahrstrasse.kantenliste():
                if kante.rgl_ggl != GLEIS_BAHNHOF:
                    self.rgl_ggl = kante.rgl_ggl
                    self.streckenname = kante.streckenname

        # TODO: Setze Richtungsanzeiger

        self.name = "LZB: " if self.fahrstr_typ == FAHRSTR_TYP_LZB else ""

        if self.start.reftyp == REFTYP_AUFGLEISPUNKT:
            self.name += "Aufgleispunkt"
        else:
            startsignal = self.start.signal()
            self.name += "{} {}".format(startsignal.get("NameBetriebsstelle", ""), startsignal.get("Signalname", ""))

        # Ereignis "Signalgeschwindigkeit" im Zielsignal setzt Geschwindigkeit fuer die gesamte Fahrstrasse
        zielsignal_geschw = finde_ereignis_in_signal(self.ziel.signal(), EREIGNIS_SIGNALGESCHWINDIGKEIT)
        if zielsignal_geschw is not None:
            self.signalgeschwindigkeit = float(zielsignal_geschw.get("Wert", 0))
        else:
            self.signalgeschwindigkeit = -1.0
            for einzelfahrstrasse in einzelfahrstrassen:
                self.signalgeschwindigkeit = geschw_min(self.signalgeschwindigkeit, einzelfahrstrasse.signalgeschwindigkeit)

        for idx, einzelfahrstrasse in enumerate(einzelfahrstrassen):
            self.laenge += einzelfahrstrasse.laenge

            zielkante = einzelfahrstrasse.kanten.eintrag
            zielsignal = zielkante.ziel.signal()
            self.name += " -> {} {}".format(zielsignal.get("NameBetriebsstelle", ""), zielsignal.get("Signalname", ""))

            # Startsignal ansteuern
            if idx == 0:
                if ist_hsig_fuer_fahrstr_typ(self.start.signal(), self.fahrstr_typ):
                    if finde_ereignis_in_signal(self.ziel.signal(), EREIGNIS_HILFSHAUPTSIGNAL) is not None:
                        # Wenn Zielsignal Hilfshauptsignal ist, Ersatzsignalzeile ansteuern
                        startsignal_zeile = get_hsig_ersatzsignal_zeile(self.start.signal(), self.rgl_ggl)
                        if startsignal_zeile is None:
                            logging.warn("{}: Startsignal hat keine Ersatzsignal-Zeile fuer RglGgl-Angabe {}".format(self.name, self.rgl_ggl))
                        else:
                            self.signale.append(FahrstrHauptsignal(self.start, startsignal_zeile, True))
                    else:
                        startsignal_zeile = get_hsig_zeile(self.start.signal(), self.fahrstr_typ, self.signalgeschwindigkeit)
                        if startsignal_zeile is None:
                            logging.warn("{}: Startsignal hat keine Zeile fuer Geschwindigkeit {}".format(self.name, str_geschw(self.signalgeschwindigkeit)))
                        else:
                            self.signale.append(FahrstrHauptsignal(self.start, startsignal_zeile, False))

            # TODO: Hauptsignale (richtig) ansteuern: Kennlichtsignale, Zielsignal auf -999

            for kante in einzelfahrstrasse.kantenliste():
                # TODO: Vorsignale ansteuern
                self.register.extend(kante.register)
                self.weichen.extend(kante.weichen)
                self.teilaufloesepunkte.extend(kante.aufloesepunkte)
                self.signalhaltfallpunkte.extend(kante.signalhaltfallpunkte)

        # TODO: Aufloesepunkte suchen (= Teilaufloesepunkte der naechsten Einzelfahrstrassen am Zielknoten)

    def to_xml(self):
        # TODO: Zufallswert
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
        self.start = None # KnotenUndRichtung
        self.ziel = None  # KnotenUndRichtung

        self.kanten = None  # ListenEintrag
        self.laenge = 0  # Laenge in Metern
        self.signalgeschwindigkeit = -1.0  # Minimale Signalgeschwindigkeit

    def erweitere(self, kante):
        if self.start is None:
            self.start = kante.start
        self.ziel = kante.ziel
        self.kanten = ListenEintrag(kante, self.kanten)
        self.laenge = self.laenge + kante.laenge
        self.signalgeschwindigkeit = geschw_min(self.signalgeschwindigkeit, kante.signalgeschwindigkeit)

    def erweiterte_kopie(self, kante):
        result = EinzelFahrstrasse()
        result.start = self.start
        result.kanten = self.kanten
        result.laenge = self.laenge
        result.signalgeschwindigkeit = self.signalgeschwindigkeit
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
        self.aufloesepunkte = []  # [RefPunkt]
        self.signalhaltfallpunkte = []  # [RefPunkt]

        self.rgl_ggl = GLEIS_BAHNHOF  # Regelgleis-/Gegengleiskennzeichnung dieses Abschnitts
        self.streckenname = ""  # Streckenname (Teil der Regelgleis-/Gegengleiskennzeichnung)
        self.richtungsanzeiger = ""  # Richtungsanzeiger-Ziel dieses Abschnitts

# Ein Knoten im Streckengraphen ist ein relevantes Streckenelement, also eines, das eine Weiche oder ein Hauptsignal enthaelt.
class Knoten:
    def __init__(self, graph, element):
        self.graph = graph  # Streckengraph
        self.element = element  # Instanz der Klasse Element (Tupel aus Modul und <StrElement>-Knoten)

        # Von den nachfolgenden Informationen existiert eine Liste pro Richtung.
        self.nachfolger_kanten = [None, None]
        self.vorgaenger_kanten = [None, None]
        self.einzelfahrstrassen = [None, None]

    def __repr__(self):
        return "Knoten<{}>".format(repr(self.element))

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

    # Gibt alle von diesem Knoten ausgehenden Nachfolgerkanten in der angegebenen Richtung zurueck.
    # Eine Kante wird nur erzeugt, wenn sie fuer die Fahrstrasse relevant ist, also an einem
    # Streckenelement mit Signal oder Weiche endet und kein Ereignis "Keine X-Fahrstrasse einrichten" enthaelt.
    def get_nachfolger_kanten(self, richtung):
        key = 0 if richtung == NORM else 1
        if self.nachfolger_kanten[key] is None:
            logging.debug("Suche Nachfolgerkanten ab {}".format(self.richtung(richtung)))
            self.nachfolger_kanten[key] = []
            nachfolger = nachfolger_elemente(self.element.richtung(richtung))

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
                if weichen_refpunkt is not None:
                    kante.weichen.append(FahrstrWeichenstellung(weichen_refpunkt, idx + 1))
                kante = self._neue_nachfolger_kante(kante, n)
                self.nachfolger_kanten[key].append(kante)
        return self.nachfolger_kanten[key]

    # Erweitert die angegebene Kante, die am Nachfolger 'element_richtung' dieses Knotens beginnt.
    # Gibt None zurueck, wenn keine fahrstrassenrelevante Kante existiert.
    def _neue_nachfolger_kante(self, kante, element_richtung):
        if element_richtung is None:
            return None

        while element_richtung is not None:
            # TODO: Signal am aktuellen Element in die Signalliste einfuegen
            # TODO: Register am aktuellen Element in die Registerliste einfuegen

            # Register am aktuellen Element in die Registerliste einfuegen
            regnr = element_richtung.registernr()
            if regnr != 0:
                refpunkt = element_richtung.refpunkt(REFTYP_REGISTER)
                if refpunkt is None:
                    logging.warn("Element {} enthaelt ein Register, aber es existiert kein passender Referenzpunkt. Die Registerverknuepfung wird nicht eingerichetet.".format(element_richtung))
                else:
                    kante.register.append(refpunkt)

            # Ereignisse am aktuellen Element verarbeiten
            for ereignis in element_richtung.ereignisse():
                ereignis_nr = int(ereignis.get("Er", 0))
                if ereignis_nr == EREIGNIS_SIGNALGESCHWINDIGKEIT:
                    kante.signalgeschwindigkeit = geschw_min(kante.signalgeschwindigkeit, float(ereignis.get("Wert", 0)))
                elif ereignis_nr == EREIGNIS_SIGNALHALTFALL:
                    pass
                elif ereignis_nr == EREIGNIS_KEINE_LZB_FAHRSTRASSE and self.graph.fahrstr_typ == FAHRSTR_TYP_LZB:
                    return None
                elif ereignis_nr == EREIGNIS_LZB_ENDE and self.graph.fahrstr_typ == FAHRSTR_TYP_LZB:
                    return None
                elif ereignis_nr == EREIGNIS_KEINE_ZUGFAHRSTRASSE and self.graph.fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_LZB]:
                    return None
                elif ereignis_nr == EREIGNIS_KEINE_RANGIERFAHRSTRASSE and self.graph.fahrstr_typ == FAHRSTR_TYP_RANGIER:
                    return None
                elif ereignis_nr == EREIGNIS_FAHRSTRASSE_AUFLOESEN:
                    # TODO: in Liste von Aufloesepunkten einfuegen
                    pass

                elif ereignis_nr == EREIGNIS_GEGENGLEIS:
                    if kante.rgl_ggl == GLEIS_BAHNHOF:
                        kante.rgl_ggl = GLEIS_GEGENGLEIS
                        kante.streckenname = ereignis.get("Beschr", "")
                    else:
                        # TODO: Warnmeldung
                        pass

                elif ereignis_nr == EREIGNIS_REGELGLEIS:
                    if kante.rgl_ggl == GLEIS_BAHNHOF:
                        kante.rgl_ggl = GLEIS_REGELGLEIS
                        kante.streckenname = ereignis.get("Beschr", "")
                    else:
                        # TODO: Warnmeldung
                        pass

                elif ereignis_nr == EREIGNIS_EINGLEISIG:
                    if kante.rgl_ggl == GLEIS_BAHNHOF:
                        kante.rgl_ggl = GLEIS_EINGLEISIG
                        kante.streckenname = ereignis.get("Beschr", "")
                    else:
                        # TODO: Warnmeldung
                        pass

                elif ereignis_nr == EREIGNIS_RICHTUNGSANZEIGER_ZIEL:
                    if kante.richtungsanzeiger == "":
                        kante.richtungsanzeiger = ereignis.get("Beschr", "")
                    else:
                        # TODO: Warnmeldung
                        pass

                elif ereignis_nr == EREIGNIS_REGISTER_VERKNUEPFEN:
                    try:
                        kante.register.append(element_richtung.modul.referenzpunkte_by_nr[int(float(ereignis.get("Wert", "")))])
                    except (KeyError, ValueError):
                        logging.warn("Ereignis \"Register in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltige Referenzpunkt-Nummer {}. Die Registerverknuepfung wird nicht eingerichetet.".format(element_richtung, ereignis.get("Wert", "")))
                        continue

                elif ereignis_nr == EREIGNIS_WEICHE_VERKNUEPFEN:
                    try:
                        refpunkt = element_richtung.modul.referenzpunkte_by_nr[int(float(ereignis.get("Wert", "")))]
                    except (KeyError, ValueError):
                        logging.warn("Ereignis \"Weiche in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltige Referenzpunkt-Nummer {}. Die Weichenverknuepfung wird nicht eingerichetet.".format(element_richtung, ereignis.get("Wert", "")))
                        continue

                    try:
                        kante.weichen.append(FahrstrWeichenstellung(refpunkt, int(ereignis.get("Beschr", ""))))
                    except ValueError:
                        logging.warn("Ereignis \"Weiche in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltige Weichenstellung {}. Die Weichenverknuepfung wird nicht eingerichetet.".format(element_richtung, ereignis.get("Beschr", "")))
                elif ereignis_nr == EREIGNIS_SIGNAL_VERKNUEPFEN:
                    # TODO: in Liste von Signalen einfuegen
                    pass
                elif ereignis_nr == EREIGNIS_VORSIGNAL_VERKNUEPFEN:
                    # TODO: in Liste von Vorsignalen einfuegen
                    pass

            kante.laenge += element_laenge(element_richtung.element)

            if self.graph.ist_knoten(element_richtung.element):
                break

            nachfolger = nachfolger_elemente(element_richtung)
            if len(nachfolger) == 0:
                element_richtung = None
                break

            assert(len(nachfolger) == 1)  # sonst waere es ein Knoten
            element_richtung_neu = nachfolger[0]

            nachfolger_vorgaenger = vorgaenger_elemente(element_richtung_neu)
            if nachfolger_vorgaenger is not None and len(nachfolger_vorgaenger) > 1:
                # Stumpf befahrene Weiche stellen
                weichen_refpunkt = self.graph.get_knoten(Element(element_richtung_neu.modul, element_richtung_neu.element)).refpunkt(gegenrichtung(element_richtung_neu.richtung), REFTYP_WEICHE)
                if weichen_refpunkt is None:
                    logging.warn(("Element {} hat mehr als einen Vorgaenger in {} Richtung, aber keinen Referenzpunkteintrag vom Typ Weiche. " +
                            "Es werden keine Fahrstrassen ueber dieses Element erzeugt.").format(
                            self.element.attrib["Nr"], "blauer" if richtung == NORM else "gruener"))
                    return None

                try:
                    kante.weichen.append(FahrstrWeichenstellung(weichen_refpunkt, nachfolger_vorgaenger.index(element_richtung) + 1))
                except ValueError:
                    logging.warn(("Stellung der stumpf befahrene Weiche an Element {} {} von Element {} {} kommend konnte nicht ermittelt werden. " +
                            "Es werden keine Fahrstrassen ueber das letztere Element erzeugt.").format(
                            element_richtung_neu.element.attrib["Nr"], "blau" if element_richtung_neu.richtung == NORM else "gruen",
                            element_richtung.element.attrib["Nr"], "blau" if element_richtung.richtung == NORM else "gruen"))
                    return None

            element_richtung = element_richtung_neu

        if element_richtung is None:
            # Fahrweg endet im Nichts, hier ist keine sinnvolle Fahrstrasse zu erzeugen
            return None
        else:
            kante.ziel = KnotenUndRichtung(self.graph.get_knoten(Element(element_richtung.modul, element_richtung.element)), element_richtung.richtung)

        return kante

    # Gibt alle Einzelfahrstrassen zurueck, die an diesem Knoten in der angegebenen Richtung beginnen.
    # Pro Zielsignal wird nur eine Einzelfahrstrasse behalten, auch wenn alternative Fahrwege existieren.
    def _get_einzelfahrstrassen(self, richtung):
        # Zielsignal-Refpunkt -> [EinzelFahrstrasse]
        einzelfahrstrassen_by_zielsignal = defaultdict(list)
        for kante in self.get_nachfolger_kanten(richtung):
            if kante is not None:
                f = EinzelFahrstrasse()
                f.erweitere(kante)
                self._get_einzelfahrstrassen_rek(f, einzelfahrstrassen_by_zielsignal)

        result = []
        for ziel_refpunkt, einzelfahrstrassen in einzelfahrstrassen_by_zielsignal.items():
            if len(einzelfahrstrassen) > 1:
                logging.debug("{} Einzelfahrstrassen zu {} {} gefunden: {}".format(
                    len(einzelfahrstrassen),
                    ziel_refpunkt.signal().get("NameBetriebsstelle", "?"),
                    ziel_refpunkt.signal().get("Signalname", "?"),
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
            logging.debug("Zielsignal gefunden: {} {}".format(signal.get("NameBetriebsstelle", "?"), signal.get("Signalname", "?")))
            ergebnis_dict[fahrstrasse.ziel.refpunkt(REFTYP_SIGNAL)].append(fahrstrasse)
            return

        folgekanten = fahrstrasse.ziel.knoten.get_nachfolger_kanten(fahrstrasse.ziel.richtung)
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
        zielknoten = letzte_fahrstrasse.kanten.eintrag.ziel.knoten
        zielrichtung = letzte_fahrstrasse.kanten.eintrag.ziel.richtung
        zielsignal = zielknoten.signal(zielrichtung)
        ziel_flags = int(zielsignal.get("SignalFlags", 0))

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
                # if startsignal is None or int(startsignal.get("SignalFlags", 0)) & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL == 0:

        if ziel_flags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL != 0:
            fahrstr_weiterfuehren = True

        logging.debug("Fahrstrassensuche: an {} {}, Kennlicht Vorgaenger={}, Kennlicht Nachfolger={}, abschl={}, weiter={}".format(
            zielsignal.get("NameBetriebsstelle", ""), zielsignal.get("Signalname", ""),
            ziel_flags & SIGFLAG_KENNLICHT_VORGAENGERSIGNAL != 0, ziel_flags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL != 0,
            fahrstr_abschliessen, fahrstr_weiterfuehren))

        if fahrstr_abschliessen:
            ziel_liste.append(Fahrstrasse(self.graph.fahrstr_typ, einzelfahrstr_liste))
        if fahrstr_weiterfuehren:
            for einzelfahrstrasse in zielknoten.get_einzelfahrstrassen(zielrichtung):
                self._get_fahrstrassen_rek(einzelfahrstr_liste + [einzelfahrstrasse], ziel_liste)

class KnotenUndRichtung(namedtuple('KnotenUndRichtung', ['knoten', 'richtung'])):
    def __repr__(self):
        return repr(self.knoten) + ("b" if self.richtung == NORM else "g")

    def signal(self):
        return self.knoten.element.signal(self.richtung)

    def refpunkt(self, typ):
        return self.knoten.element.refpunkt(self.richtung, typ)
