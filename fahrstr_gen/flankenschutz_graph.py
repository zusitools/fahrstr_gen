#!/usr/bin/env python3

from .konstanten import *
from .streckengraph import Streckengraph, Knoten
from .strecke import gegenrichtung
from .fahrstrasse import FahrstrWeichenstellung

import logging

# Ein Streckengraph, der zum Finden von Flankenschutzweichen in Fahrstrassen dient.
# Knoten sind zusaetzlich Zugfahrt-Hauptsignale sowie Gleissperren (Signale mit Entgleisen-Ereignis).
# NB. Der Einfachheit halber werden Gleissperren als in beide Richtungen wirksam betrachtet.
class FlankenschutzGraph(Streckengraph):
    def __init__(self):
        super().__init__()

    def _neuer_knoten(self, element):
        return FlankenschutzGraphKnoten(self, element)

    def _ist_knoten(self, element):
        if element is None:
            return False
        if super()._ist_knoten(element):
            return True
        for richtung in [NORM, GEGEN]:
            signal = element.signal(richtung)
            # Hauptsignale beliebigen Typs verhindern die Erzeugung von Flankenschutz-Verknuepfungen,
            # da zu ihnen potenziell eine Fahrstrasse gestellt sein kann, in der eine Weiche verknuepft ist.
            if signal is not None and (any(zeile.hsig_geschw == 0 and zeile.fahrstr_typ != 0 for zeile in signal.zeilen) or signal.ist_gleissperre):
                return True
        return False

class FlankenschutzGraphKnoten(Knoten):
    def __init__(self, graph, element):
        super().__init__(graph, element)

        # Von den nachfolgenden Informationen existiert ein Dictionary  pro Richtung.
        # In jedem Dictionary steht mit Schluessel i eine Liste von Weichenstellungen, 
        # die eingefuegt werden muessen, wenn am Element der Nachfolger Nummer i gestellt wird.
        # Es werden nur solche Weichenstellungen angegeben, die nicht der Vorzugslage der Weiche entsprechen.
        self.flankenschutz_stellungen = [dict(), dict()]

    # Gibt die Weichenstellungen zurueck, die eingefuegt werden muessen, um dem Element Flankenschutz
    # zu gewaehren, wenn es in Richtung Nachfolger Nummer idx (0-indiziert) befahren wird.
    def get_flankenschutz_stellungen(self, richtung, idx):
        key = 0 if richtung == NORM else 1
        try:
            return self.flankenschutz_stellungen[key][idx]
        except KeyError:
            logging.debug("Suche Flankenschutz-Stellungen ab {}, Nachfolger {}".format(self.richtung(richtung), idx + 1))
            result = self._get_flankenschutz_stellungen(richtung, idx)
            self.flankenschutz_stellungen[key][idx] = result
            return result

    def _get_flankenschutz_stellungen(self, richtung, idx):
        result = []
        for nach_idx, nachfolger in enumerate(self.element.nachfolger(richtung)):
            if nach_idx != idx:
                element_richtung_vorgaenger = self.element.richtung(richtung)
                element_richtung = nachfolger
                laenge = 0

                while element_richtung is not None and self.graph.get_knoten(element_richtung.element) is None:
                    laenge += element_richtung.element.laenge()
                    if laenge >= 200:
                        element_richtung = None
                        break

                    nachfolger_liste = element_richtung.nachfolger()
                    if len(nachfolger_liste) == 0:
                        element_richtung = None
                        break

                    assert(len(nachfolger_liste) == 1) # sonst waere es ein Knoten
                    element_richtung_vorgaenger = element_richtung
                    element_richtung = nachfolger_liste[0]

                if element_richtung is not None:
                    vorgaenger_liste = element_richtung.vorgaenger()
                    if len(vorgaenger_liste) > 1:
                        try:
                            vorgaenger_index = vorgaenger_liste.index(element_richtung_vorgaenger)
                        except ValueError:
                            logging.warn(("Stellung der stumpf befahrenen Weiche an Element {} von Element {} kommend konnte nicht ermittelt werden. " +
                                    "Die Weiche wird nicht in Flankenschutzstellung gebracht.").format(element_richtung, element_richtung_vorgaenger))
                            return

                        if vorgaenger_index == 0:
                            # Die Weiche steht in ihrer Vorrangstellung in Richtung von `self`. Stelle sie also um. 
                            weichen_refpunkt = element_richtung.element.refpunkt(gegenrichtung(element_richtung.richtung), REFTYP_WEICHE)
                            if weichen_refpunkt is None:
                                logging.warn(("Element {} hat mehr als einen Vorgaenger in {} Richtung, aber keinen Referenzpunkteintrag vom Typ Weiche. " +
                                        "Diese Weiche wird nicht in Flankenschutzstellung gebracht.").format(element_richtung))
                            else:
                                result.append(FahrstrWeichenstellung(weichen_refpunkt, len(vorgaenger_liste)))

        return result
