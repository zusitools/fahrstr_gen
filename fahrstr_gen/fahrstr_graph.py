#!/usr/bin/env python3

import xml.etree.ElementTree as ET
from collections import namedtuple, defaultdict, OrderedDict

from .konstanten import *
from .modulverwaltung import get_modul_by_name
from .strecke import ist_hsig_fuer_fahrstr_typ, ist_fahrstr_start_sig, gegenrichtung, geschw_min
from .streckengraph import Streckengraph, Knoten
from .fahrstrasse import FahrstrHauptsignal, FahrstrVorsignal, FahrstrWeichenstellung

import logging

# Ein Streckengraph, der zum Aufbau von Fahrstrassen eines bestimmten Typs benutzt wird.
# Knoten sind zusaetzlich Hauptsignale fuer den gewuenschten Typ sowie Aufgleispunkte.
class FahrstrGraph(Streckengraph):
    def __init__(self, fahrstr_typ):
        super().__init__()
        self.fahrstr_typ = fahrstr_typ

    def _neuer_knoten(self, element):
        return FahrstrGraphKnoten(self, element)

    def _ist_knoten(self, element):
        return element is not None and (
                super()._ist_knoten(element) or
                ist_hsig_fuer_fahrstr_typ(element.signal(NORM), self.fahrstr_typ) or
                ist_hsig_fuer_fahrstr_typ(element.signal(GEGEN), self.fahrstr_typ) or
                ist_fahrstr_start_sig(element.signal(NORM), self.fahrstr_typ) or
                ist_fahrstr_start_sig(element.signal(GEGEN), self.fahrstr_typ) or
                (self.fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_RANGIER] and any(refpunkt.reftyp == REFTYP_AUFGLEISPUNKT for refpunkt in element.modul.referenzpunkte[element])))

# Eine Kante zwischen zwei Knoten im Streckengraphen. Sie enthaelt alle fahrstrassenrelevanten Daten (Signale, Weichen, Aufloesepunkte etc.)
# einer Folge von gerichteten Streckenelementen zwischen den beiden Knoten (exklusive Start, inklusive Ziel, inklusive Start-Weichenstellung).
class FahrstrGraphKante:
    def __init__(self, start):
        assert(start is not None)
        self.start = start  # KnotenUndRichtung
        self.ziel = None  # KnotenUndRichtung

        self.start_nachfolger_idx = None  # Nachfolger-Index des ersten Elements im Startknoten, wenn dieser mehr als einen Nachfolger besitzt
        self.ziel_vorgaenger_idx = None  # Vorgaenger-Index des vorletzten Elements im Zielknoten, wenn dieser mehr als einen Vorgaenger besitzt

        self.laenge = 0  # Laenge in Metern
        self.laenge_zusi = 0  # Laenge in Metern, wie sie Zusi berechnet
        self.signalgeschwindigkeit = -1.0  # Minimale Signalgeschwindigkeit auf diesem Abschnitt

        self.register = []  # [RefPunkt]
        self.bedingte_register = []  # [(RefPunkt, Beschreibung)]
        self.weichen = []  # [FahrstrWeichenstellung]
        self.signale = []  # [FahrstrHauptsignal] -- alle Signale, die nicht eine Fahrstrasse beenden, also z.B. Rangiersignale, sowie "Signal in Fahrstrasse verknuepfen". Wenn die Signalzeile den Wert -1 hat, ist die zu waehlende Zeile fahrstrassenabhaengig.
        self.vorsignale = []  # [FahrstrVorsignal] -- nur Vorsignale, die mit "Vorsignal in Fahrstrasse verknuepfen" in einem Streckenelement dieser Kante verknuepft sind
        self.aufloesepunkte = []  # [RefPunkt] -- Signalhaltfall- und Aufloesepunkte. Reihenfolge ist wichtig!

        self.rgl_ggl = GLEIS_BAHNHOF  # Regelgleis-/Gegengleiskennzeichnung dieses Abschnitts
        self.streckenname = ""  # Streckenname (Teil der Regelgleis-/Gegengleiskennzeichnung)
        self.richtungsanzeiger = ""  # Richtungsanzeiger-Ziel dieses Abschnitts

        self.hat_ende_weichenbereich = False  # Liegt im Verlauf dieser Kante ein Ereignis "Ende Weichenbereich"?
        self.hat_anzeige_geschwindigkeit = False # Liegt im Verlauf dieser Kante ein Ereignis "ETCS-Geschwindigkeit" oder "CIR-ELKE-Geschwindigkeit"
        self.keine_fahrstr_einrichten = None  # Das erste Ereignis "Keine Fahrstrasse einrichten" fuer den Fahrstrassentyp des Graphen im Verlauf dieser Kante

class FahrstrGraphKnoten(Knoten):
    def __init__(self, graph, element):
        super().__init__(graph, element)

        # Von den nachfolgenden Informationen existiert eine Liste pro Richtung.
        self.nachfolger_kanten = [None, None]
        self.einzelfahrstrassen = [None, None]
        self.aufloesepunkte = [None, None]  # Aufloesepunkte bis zum naechsten Zugfahrt-Hauptsignal.

    # Gibt alle von diesem Knoten in der angegebenen Richtung erreichbaren Signalhaltfall- und Aufloesepunkte bis zum naechsten Hauptsignal.
    # Die Suche stoppt jeweils nach dem ersten gefundenen Aufloesepunkt.
    def get_aufloesepunkte(self, richtung):
        key = 0 if richtung == NORM else 1
        if self.aufloesepunkte[key] is None:
            logging.debug("Suche Aufloesepunkte ab {}".format(self.richtung(richtung)))
            self.aufloesepunkte[key] = self._get_aufloesepunkte(richtung)
        return self.aufloesepunkte[key]

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
                kante = FahrstrGraphKante(self.richtung(richtung))
                # Ende Weichenbereich wirkt schon im Startelement
                kante.hat_ende_weichenbereich = any(int(ereignis.get("Er", 0)) == 1000002 for ereignis in self.element.ereignisse(richtung))
                if weichen_refpunkt is not None:
                    kante.start_nachfolger_idx = idx
                    if n.element.modul == self.element.modul:
                        kante.weichen.append(FahrstrWeichenstellung(weichen_refpunkt, idx + 1))
                    else:
                        # Anwendungsfall von Weichen an Modulgrenzen sind alternative Versionen desselben Moduls.
                        # Zusi geht davon aus, dass immer nur eine Version des Nachbarmoduls im Fahrplan enthalten ist
                        # und somit nach dem Laden im Simulator das Element nur einen Nachfolger (Index 0) hat.
                        # Somit ist nach Zusi-Logik keine Weichenverknuepfung notwendig.
                        logging.debug(("Nachfolger Nr. {} von Element {} liegt in anderem Modul. Es wird keine Weichenverknuepfung in der Fahrstrasse erzeugt.").format(idx + 1, self.element.richtung(richtung)))
                kante = self._neue_nachfolger_kante(kante, n)
                if kante is not None:
                    self.nachfolger_kanten[key].append(kante)
        return self.nachfolger_kanten[key]

    # Erweitert die angegebene Kante, die am Nachfolger 'element_richtung' dieses Knotens beginnt.
    # Gibt None zurueck, wenn keine fahrstrassenrelevante Kante existiert.
    def _neue_nachfolger_kante(self, kante, element_richtung):
        element_richtung_vorgaenger = kante.start.element_und_richtung()

        while element_richtung is not None:
            # Bug in Zusi bei der Laengenberechnung moduluebergreifender Fahrstrassen
            if element_richtung_vorgaenger.element.modul != element_richtung.element.modul:
                kante.laenge_zusi -= element_richtung_vorgaenger.element.laenge()
                kante.laenge_zusi += element_richtung.element.laenge()

            # Bei Ereignis "Keine Fahrstrasse einrichten" sofort abbrechen (keine weiteren Ereignisse/Signale an diesem Element betrachten)
            for ereignis in element_richtung.ereignisse():
                ereignis_nr = int(ereignis.get("Er", 0))
                if ereignis_nr in [EREIGNIS_KEINE_ANZEIGE_FAHRSTRASSE, EREIGNIS_LZB_ENDE] and self.graph.fahrstr_typ == FAHRSTR_TYP_ANZEIGE \
                        or ereignis_nr == EREIGNIS_KEINE_ZUGFAHRSTRASSE and self.graph.fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_ANZEIGE] \
                        or ereignis_nr == EREIGNIS_KEINE_RANGIERFAHRSTRASSE and self.graph.fahrstr_typ == FAHRSTR_TYP_RANGIER:
                    logging.debug("{}: Keine Fahrstrasse einrichten (Ereignis Nr. {})".format(element_richtung, ereignis_nr))
                    kante.keine_fahrstr_einrichten = element_richtung
                    break

            if kante.keine_fahrstr_einrichten is not None:
                element_richtung = None
                break

            # Signal am aktuellen Element in die Signalliste einfuegen, falls es nicht Zielsignal der Kante ist
            signal = element_richtung.signal()
            if signal is not None and not signal.ist_hsig_fuer_fahrstr_typ(self.graph.fahrstr_typ):
                verkn = False
                zeile = -1

                # Hauptsignale im Fahrweg, die nicht Zielsignal sind, auf -1 stellen:
                if self.graph.fahrstr_typ == FAHRSTR_TYP_ZUG and (signal.ist_hsig_fuer_fahrstr_typ(FAHRSTR_TYP_ANZEIGE) or signal.ist_fahrstr_start_sig(FAHRSTR_TYP_ANZEIGE)):
                    zeile = signal.get_hsig_zeile(FAHRSTR_TYP_ANZEIGE, -1)
                    if zeile is None:
                        logging.warn("{} enthaelt keine passende Zeile fuer Fahrstrassentyp Anzeige und Geschwindigkeit -1. Die Signalverknuepfung wird nicht eingerichtet.".format(signal))
                    else:
                        logging.debug("{}: Anzeige-Hauptsignal bei Zugfahrstrasse umstellen (Geschwindigkeit -1/Zeile {})".format(signal, zeile))
                        verkn = True
                elif signal.ist_hsig_fuer_fahrstr_typ(FAHRSTR_TYP_RANGIER) or signal.ist_fahrstr_start_sig(FAHRSTR_TYP_RANGIER):
                    if (self.graph.fahrstr_typ == FAHRSTR_TYP_RANGIER) or (signal.sigflags & SIGFLAG_RANGIERSIGNAL_BEI_ZUGFAHRSTR_UMSTELLEN != 0):
                        zeile = signal.get_hsig_zeile(FAHRSTR_TYP_RANGIER, -1)
                        if zeile is None:
                            logging.warn("{} enthaelt keine passende Zeile fuer Fahrstrassentyp Rangier und Geschwindigkeit -1. Die Signalverknuepfung wird nicht eingerichtet.".format(signal))
                        else:
                            logging.debug("{}: Rangiersignal bei Zug- oder Anzeige-Fahrstrasse umstellen (Geschwindigkeit -1/Zeile {})".format(signal, zeile))
                            verkn = True
                elif signal.ist_hsig_fuer_fahrstr_typ(FAHRSTR_TYP_FAHRWEG) or signal.ist_fahrstr_start_sig(FAHRSTR_TYP_FAHRWEG):
                    if signal.sigflags & SIGFLAG_FAHRWEGSIGNAL_WEICHENANIMATION == 0:
                        zeile = signal.get_hsig_zeile(FAHRSTR_TYP_FAHRWEG, -1)
                        if zeile is None:
                            logging.warn("{} enthaelt keine passende Zeile fuer Fahrstrassentyp Fahrweg und Geschwindigkeit -1. Die Signalverknuepfung wird nicht eingerichtet.".format(signal))
                        else:
                            logging.debug("{}: Fahrwegsignal (ausser Weichenanimation) bei Fahrstrasse umstellen (Geschwindigkeit -1/Zeile {})".format(signal, zeile))
                            verkn = True

                # Signale, die mehr als eine Zeile haben, stehen potenziell auf der falschen Zeile (z.B. durch Verknuepfung aus anderen Fahrstrassen)
                # und muessen deshalb zumindest in Grundstellung gebracht werden.
                # Betrachte aber nur Signale, die zumindest eine Zeile fuer den aktuellen Fahrstrassentyp besitzen.
                elif len(signal.zeilen) >= 2 and any(zeile.fahrstr_typ & self.graph.fahrstr_typ != 0 for zeile in signal.zeilen):
                    verkn = True
                    logging.debug("{}: hat mehr als eine Zeile (Zeile noch unbekannt)".format(signal))
                    # Zeile muss ermittelt werden

                # Signale, die einen Richtungs- oder Gegengleisanzeiger haben
                # TODO: eventuell nicht fuer Rangierfahrstrassen?
                elif signal.gegengleisanzeiger != 0 or len(signal.richtungsanzeiger) > 0:
                    verkn = True
                    logging.debug("{}: hat Richtungs- oder Gegengleisanzeiger (Zeile noch unbekannt)".format(signal))
                    # Zeile muss ermittelt werden

                if verkn:
                    refpunkt = element_richtung.refpunkt(REFTYP_SIGNAL)
                    if refpunkt is None:
                        logging.warn("Element {} enthaelt ein Signal, aber es existiert kein passender Referenzpunkt. Die Signalverknuepfung wird nicht eingerichtet.".format(element_richtung))
                    else:
                        kante.signale.append(FahrstrHauptsignal(refpunkt, zeile, False))
                else:
                    logging.debug("{}: wird nicht in die Fahrstrasse aufgenommen".format(signal))
                    if signal.hat_gegengleisanzeiger_in_ersatzsignalmatrix:
                        logging.warn("{}: hat Ereignis \"Gegengleis kennzeichnen\" in der Ersatzsignalmatrix und wuerde von Zusi in der Fahrstrasse verknuepft.".format(signal))

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
                        logging.warn("{} enthaelt keine passende Zeile fuer Fahrstrassentyp Fahrweg und Geschwindigkeit -1. Die Signalverknuepfung wird nicht eingerichtet.".format(signal_gegenrichtung))
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
            hat_aufloesepunkt = False
            for ereignis in element_richtung.ereignisse():
                ereignis_nr = int(ereignis.get("Er", 0))
                if ereignis_nr == EREIGNIS_SIGNALGESCHWINDIGKEIT:
                    if not kante.hat_ende_weichenbereich:
                        signalgeschwindigkeit = float(ereignis.get("Wert", 0))
                        if signalgeschwindigkeit <= 0:
                            logging.warn("Element {}: Ignoriere Ereignis \"Signalgeschwindigkeit\" mit Wert <= 0".format(element_richtung))
                        else:
                            kante.signalgeschwindigkeit = geschw_min(kante.signalgeschwindigkeit, signalgeschwindigkeit)

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
                        hat_aufloesepunkt = True
                        kante.aufloesepunkte.append(refpunkt)

                elif ereignis_nr == EREIGNIS_SIGNALHALTFALL:
                    refpunkt = element_richtung.refpunkt(REFTYP_SIGNALHALTFALL)
                    if refpunkt is None:
                        logging.warn("Element {} enthaelt ein Ereignis \"Signalhaltfall\", aber es existiert kein passender Referenzpunkt. Die Signalhaltfall-Verknuepfung wird nicht eingerichtet.".format(element_richtung))
                    else:
                        kante.aufloesepunkte.append(refpunkt)

                elif ereignis_nr == EREIGNIS_LZB_CIR_ELKE_GESCHWINDIGKEIT or ereignis_nr == EREIGNIS_ETCS_GESCHWINDIGKEIT:
                    kante.hat_anzeige_geschwindigkeit = True

                elif ereignis_nr == EREIGNIS_REGISTER_VERKNUEPFEN or ereignis_nr == EREIGNIS_REGISTER_BEDINGT_VERKNUEPFEN:
                    try:
                        refpunkt_modul = get_modul_by_name(ereignis.get("Beschr", ""), element_richtung.element.modul)
                        refpunkt = refpunkt_modul.referenzpunkte_by_nr[int(float(ereignis.get("Wert", 0)))]

                        if ereignis_nr == EREIGNIS_REGISTER_BEDINGT_VERKNUEPFEN:
                            kante.bedingte_register.append((refpunkt, "Bahnsteigkreuzung"))
                        else:
                            kante.register.append(refpunkt)

                    except (KeyError, ValueError, AttributeError):
                        logging.warn("Ereignis \"Register in Fahrstrasse verknuepfen\" an Element {} enthaelt ungueltigen Referenzpunkt (Nummer \"{}\", Modul \"{}\"). Die Registerverknuepfung wird nicht eingerichtet.".format(element_richtung, ereignis.get("Wert", 0), ereignis.get("Beschr", "")))

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
                        logging.debug("{}: wird per \"Signal an Fahrstrasse verknuepfen\" an Element {} in dessen Fahrstrassen aufgenommen".format(refpunkt.signal(), element_richtung))
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
            element_laenge = element_richtung.element.laenge()
            kante.laenge += element_laenge
            kante.laenge_zusi += element_laenge

            if self.graph.get_knoten(element_richtung.element) is not None:
                if hat_aufloesepunkt and len(element_richtung.nachfolger()) > 1:
                    logging.warn("An Element {} liegt ein Ereignis \"Fahrstrasse aufloesen\" in einem Verzweigungselement".format(element_richtung))
                break

            nachfolger = element_richtung.nachfolger()
            if len(nachfolger) == 0:
                element_richtung = None
                break

            assert(len(nachfolger) == 1)  # sonst waere es ein Knoten
            element_richtung_vorgaenger = element_richtung
            element_richtung = nachfolger[0]

        if element_richtung is not None:
            kante.ziel = self.graph.get_knoten(element_richtung.element).richtung(element_richtung.richtung)

            # Ggf. stumpf befahrene Weiche im Zielknoten stellen
            ziel_vorgaenger = element_richtung.vorgaenger()
            if len(ziel_vorgaenger) > 1:
                weichen_refpunkt = self.graph.get_knoten(element_richtung.element).refpunkt(gegenrichtung(element_richtung.richtung), REFTYP_WEICHE)
                if weichen_refpunkt is None:
                    logging.warn(("Element {} hat mehr als einen Vorgaenger, aber keinen Referenzpunkteintrag vom Typ Weiche. " +
                            "Es werden keine Fahrstrassen ueber dieses Element erzeugt.").format(element_richtung))
                    return None

                try:
                    kante.ziel_vorgaenger_idx = ziel_vorgaenger.index(element_richtung_vorgaenger)
                    if element_richtung_vorgaenger.element.modul == element_richtung.element.modul:
                        kante.weichen.append(FahrstrWeichenstellung(weichen_refpunkt, kante.ziel_vorgaenger_idx + 1))
                    else:
                        logging.debug(("Vorgaenger Nr. {} von Element {} liegt in anderem Modul. Es wird keine Weichenverknuepfung in der Fahrstrasse erzeugt.").format(kante.ziel_vorgaenger_idx + 1, element_richtung))
                except ValueError:
                    logging.warn(("Stellung der stumpf befahrenen Weiche an Element {} von Element {} kommend konnte nicht ermittelt werden. " +
                            "Es werden keine Fahrstrassen ueber das letztere Element erzeugt.").format(element_richtung, element_richtung_vorgaenger))
                    return None

        return kante

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

        if kante.ziel is None:
            if kante.keine_fahrstr_einrichten is not None and not aufloesepunkt_gefunden:
                logging.warn("Es gibt einen Fahrweg zwischen {} und \"Keine Fahrstrasse einrichten\"/LZB-Ende an Element {}, der keinen Aufloesepunkt (fuer an diesem Signal endende Fahrstrassen vom Typ {}) enthaelt.".format(self.signal(startrichtung), kante.keine_fahrstr_einrichten, str_fahrstr_typ(self.graph.fahrstr_typ)))
        elif not kante.ziel.knoten.ist_besucht():
            kante.ziel.knoten.markiere_besucht()
            if ist_hsig_fuer_fahrstr_typ(kante.ziel.signal(), FAHRSTR_TYP_ZUG):
                if not aufloesepunkt_gefunden:
                    logging.warn("Es gibt einen Fahrweg zwischen {} und {}, der keinen Aufloesepunkt (fuer am ersten Signal endende Fahrstrassen) enthaelt.".format(self.signal(startrichtung), kante.ziel.signal()))
            else:
                for kante in kante.ziel.knoten.get_nachfolger_kanten(kante.ziel.richtung):
                    self._get_aufloesepunkte_rek(startrichtung, kante, result_liste)
