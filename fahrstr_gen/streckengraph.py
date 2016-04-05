#!/usr/bin/env python3

import xml.etree.ElementTree as ET
from collections import namedtuple, defaultdict, OrderedDict

from . import strecke
from .konstanten import *
from .strecke import *

import logging

# Ein Graph, der eine Strecke auf der untersten uns interessierenden Ebene beschreibt:
# Knoten sind Elemente mit Weichenfunktion oder, je nach Unterklasse, weiteren Charakteristiken (z.B. Hauptsignal).
class Streckengraph:
    def __init__(self):
        self._knoten = {}  # <StrElement> -> Knoten
        self._besuchszaehler = 1  # Ein Knoten gilt als besucht, wenn sein Besuchszaehler gleich dem Besuchszaehler des Graphen ist. Alle Knoten koennen durch Inkrementieren des Besuchszaehlers als unbesucht markiert werden.

    def markiere_unbesucht(self):
        self._besuchszaehler += 1

    def _ist_knoten(self, element):
        return len([n for n in element.xml_knoten if n.tag == "NachNorm" or n.tag == "NachNormModul"]) > 1 or \
                len([n for n in element.xml_knoten if n.tag == "NachGegen" or n.tag == "NachGegenModul"]) > 1

    def _neuer_knoten(self, element):
        raise NotImplementedError("Abstrakte Methode aufgerufen")

    def get_knoten(self, element):
        try:
            return self._knoten[element]
        except KeyError:
            result = self._neuer_knoten(element) if self._ist_knoten(element) else None
            self._knoten[element] = result
            return result

# Ein Knoten im Streckengraphen ist ein relevantes Streckenelement, also eines, das eine Weiche oder etwas anderweitig Relevantes enthaelt.
class Knoten:
    def __init__(self, graph, element):
        self.graph = graph  # Streckengraph
        self.element = element  # Element
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

class KnotenUndRichtung(namedtuple('KnotenUndRichtung', ['knoten', 'richtung'])):
    def __repr__(self):
        return repr(self.knoten) + ("b" if self.richtung == NORM else "g")

    def __str__(self):
        return str(self.knoten) + ("b" if self.richtung == NORM else "g")

    def element_und_richtung(self):
        return ElementUndRichtung(self.knoten.element, self.richtung)

    def signal(self):
        return self.knoten.element.signal(self.richtung)

    def refpunkt(self, typ):
        return self.knoten.element.refpunkt(self.richtung, typ)
