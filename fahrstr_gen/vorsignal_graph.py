#!/usr/bin/env python3

from .konstanten import *
from .streckengraph import Streckengraph, Knoten
from .strecke import ist_hsig_fuer_fahrstr_typ, ist_vsig

import logging

# Ein Streckengraph, der zum Finden von Vorsignalen von Fahrstrassen dient.
# Knoten sind zusaetzlich Zugfahrt-Hauptsignale.
class VorsignalGraph(Streckengraph):
    def __init__(self):
        super().__init__()

    def _neuer_knoten(self, element):
        return VorsignalGraphKnoten(self, element)

    def _ist_knoten(self, element):
        return element is not None and (
                super()._ist_knoten(element) or
                ist_hsig_fuer_fahrstr_typ(element.signal(NORM), FAHRSTR_TYP_ZUG) or
                ist_hsig_fuer_fahrstr_typ(element.signal(GEGEN), FAHRSTR_TYP_ZUG))

# Eine Kante zwischen zwei Knoten im Streckengraphen, die alle Vorsignale auf dem Weg zwischen zwei Knoten (rueckwaerts) enthaelt.
# Der Zielknoten ist also ein *Vorgaenger* des Startknotens.
# Der Zielknoten ist None, wenn die Kante an einem Element ohne Vorgaenger oder mit Ereignis "Vorher keine Vsig-Verknuepfung" endet.
class VorsignalGraphKante:
    def __init__(self):
        self.ziel = None  # KnotenUndRichtung
        self.vorsignale = []
        self.vorher_keine_vsig_verknuepfung = False

class VorsignalGraphKnoten(Knoten):
    def __init__(self, graph, element):
        super().__init__(graph, element)

        # Von den nachfolgenden Informationen existiert eine Liste pro Richtung.
        self.vorsignal_kanten = [None, None]
        self.vorsignale = [None, None]

    def get_vorsignale(self, richtung):
        key = 0 if richtung == NORM else 1
        if self.vorsignale[key] is None:
            logging.debug("Suche Vorsignale ab {}".format(self.richtung(richtung)))
            self.vorsignale[key] = self._get_vorsignale(richtung)
        return self.vorsignale[key]

    # Gibt alle von diesem Knoten ausgehenden Vorsignalkanten in der angegebenen Richtung zurueck (gesucht wird also in der Gegenrichtung).
    def get_vorsignal_kanten(self, richtung):
        key = 0 if richtung == NORM else 1
        if self.vorsignal_kanten[key] is None:
            # TODO: Vorher keine Vsig-Verknuepfung im Element selbst?
            logging.debug("Suche Vorsignal-Kanten ab {}".format(self.richtung(richtung)))
            self.vorsignal_kanten[key] = []
            for v in self.element.richtung(richtung).vorgaenger():
                if v is not None:
                    kante = VorsignalGraphKante()
                    self.vorsignal_kanten[key].append(self._neue_vorsignal_kante(kante, v))
        return self.vorsignal_kanten[key]

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

            knoten = self.graph.get_knoten(element_richtung.element)
            if knoten is not None:
                kante.ziel = knoten.richtung(element_richtung.richtung)
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
