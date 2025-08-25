from collections import namedtuple, defaultdict
from copy import deepcopy
import xml.etree.ElementTree as ET

from .konstanten import *
from . import modulverwaltung

import logging
import math

# Schnelle Implementierung von node.find("./tag1/tag2"), wenn tag1 nur einmal vorkommen kann.
def find_2(node, tag1, tag2):
    for n in node:
        if n.tag == tag1:
            for n2 in n:
                if n2.tag == tag2:
                    return n2
            break

# Schnelle Implementierung von node.findall("./tag1/tag2"), wenn tag1 nur einmal vorkommen kann.
def findall_2(node, tag1, tag2):
    for n in node:
        if n.tag == tag1:
            return [n2 for n2 in n if n2.tag == tag2]
    return []

# Betrachtet die Kindknoten von "node" mit demselben Tag wie "kindknoten" und fuegt diesen Knoten
# nach Knoten Nummer "pos" in diese Liste ein. Wenn pos == -1, fuegt es ihn am Ende ein.
# Nicht schnell, wird aber auch nicht haeufig gebraucht.
def kindknoten_einfuegen(node, kindknoten, pos):
    node.insert([idx for idx, n in enumerate(node) if n.tag == kindknoten.tag][pos] + 1, kindknoten)

class Element:
    def __init__(self, modul, xml_knoten):
        self.modul = modul
        self.xml_knoten = xml_knoten

        self._signal_gesucht = [False, False]
        self._signal = [None, None]
        self._nachfolger = [None, None]
        self._ereignisse = [None, None]
        self._laenge = None

    def __repr__(self):
        if self.modul == modulverwaltung.dieses_modul:
            return self.xml_knoten.get("Nr", "0")
        else:
            return "{}[{}]".format(self.xml_knoten.get("Nr", "0"), self.modul.name_kurz())

    def laenge(self):
        if self._laenge is None:
            b_knoten = self.xml_knoten.find("b")
            g_knoten = self.xml_knoten.find("g")
            try:
                p1 = [float(b_knoten.get("X", 0)), float(b_knoten.get("Y", 0)), float(b_knoten.get("Z", 0))]
                p2 = [float(g_knoten.get("X", 0)), float(g_knoten.get("Y", 0)), float(g_knoten.get("Z", 0))]
            except AttributeError:
                p1 = [0, 0, 0]
                p2 = [0, 0, 0]
                if b_knoten is not None:
                    p1 = [float(b_knoten.get("X", 0)), float(b_knoten.get("Y", 0)), float(b_knoten.get("Z", 0))]
                if g_knoten is not None:
                    p2 = [float(g_knoten.get("X", 0)), float(g_knoten.get("Y", 0)), float(g_knoten.get("Z", 0))]
            self._laenge = math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2)
        return self._laenge

    def richtung(self, richtung):
        return ElementUndRichtung(self, richtung)

    def ereignisse(self, richtung):
        key = 1 if richtung == NORM else 0
        if self._ereignisse[key] is None:
            # Die Sortierung dient primaer dazu, die Reihenfolge von Ereignissen deterministisch zu halten.
            # Damit kann man sich z.B. darauf verlassen, dass Ereignisse "Signalhaltfall" immer vor Ereignissen "Fahrstrasse aufloesen" gefunden werden.
            self._ereignisse[key] = sorted(findall_2(self.xml_knoten, "InfoNormRichtung" if richtung == NORM else "InfoGegenRichtung", "Ereignis"), key = lambda n: int(n.get("Er", 0)))
        return self._ereignisse[key]

    def signal(self, richtung):
        key = 1 if richtung == NORM else 0
        if not self._signal_gesucht[key]:
            self._signal_gesucht[key] = True
            signal_xml_knoten = find_2(self.xml_knoten, "InfoNormRichtung" if richtung == NORM else "InfoGegenRichtung", "Signal")
            self._signal[key] = Signal(self.richtung(richtung), signal_xml_knoten) if signal_xml_knoten is not None else None
        return self._signal[key]

    def refpunkt(self, richtung, typ):
        for refpunkt in self.modul.referenzpunkte[self]:
            if refpunkt.element_richtung.richtung == richtung and refpunkt.reftyp == typ:
                return refpunkt
        return None

    def registernr(self, richtung):
        for n in self.xml_knoten:
            if n.tag == ("InfoNormRichtung" if richtung == NORM else "InfoGegenRichtung"):
                return int(n.get("Reg", 0))
        return 0

    def hat_koppelweiche(self, richtung):
        for n in self.xml_knoten:
            if n.tag == ("InfoNormRichtung" if richtung == NORM else "InfoGegenRichtung"):
                return int(n.get("KoppelWeicheNr", 0)) != 0
        return False

    def pos_xy(self, richtung):
        tag = "b" if richtung == NORM else "g"
        for n in self.xml_knoten:
            if n.tag == tag:
                return (float(n.get("X", 0)), float(n.get("Y", 0)))
        return (0, 0)

    def nachfolger(self, richtung):
        key = 1 if richtung == NORM else 0
        if self._nachfolger[key] is None:
            anschluss = int(self.xml_knoten.get("Anschluss", 0))

            nachfolger_knoten = [n for n in self.xml_knoten if
                (richtung == NORM and (n.tag == "NachNorm" or n.tag == "NachNormModul")) or
                (richtung == GEGEN and (n.tag == "NachGegen" or n.tag == "NachGegenModul"))]
            self._nachfolger[key] = []

            for idx, n in enumerate(nachfolger_knoten):
                anschluss_shift = idx + (8 if richtung == GEGEN else 0)
                if "Modul" not in n.tag:
                    nach_modul = self.modul
                    try:
                        nach_el = nach_modul.streckenelemente[int(n.get("Nr", 0))]
                    except KeyError:
                        self._nachfolger[key].append(None)
                        continue
                    nach_richtung = NORM if (anschluss >> anschluss_shift) & 1 == 0 else GEGEN
                    self._nachfolger[key].append(ElementUndRichtung(nach_el, nach_richtung))
                else:
                    nach_modul = modulverwaltung.get_modul_aus_dateiknoten(n, self.modul)
                    if nach_modul is None:
                        self._nachfolger[key].append(None)
                        continue

                    try:
                        nach_ref = nach_modul.referenzpunkte_by_nr[int(n.get("Nr", 0))]
                    except KeyError:
                        self._nachfolger[key].append(None)
                        continue

                    self._nachfolger[key].append(nach_ref.element_richtung.gegenrichtung())  # Referenzpunkt zeigt zur Modulschnittstelle hin

        return self._nachfolger[key]

    def vorgaenger(self, richtung):
        return [(e.gegenrichtung() if e is not None else None) for e in self.nachfolger(GEGEN if richtung == NORM else NORM)]

class ElementUndRichtung(namedtuple('ElementUndRichtung', ['element', 'richtung'])):
    def __repr__(self):
        if self.element.modul == modulverwaltung.dieses_modul:
            return self.element.xml_knoten.get("Nr", "0") + ("b" if self.richtung == NORM else "g")
        else:
            return "{}{}[{}]".format(self.element.xml_knoten.get("Nr", "0"), "b" if self.richtung == NORM else "g", self.element.modul.name_kurz())

    def laenge(self):
        return self.element.laenge()

    def signal(self):
        return self.element.signal(self.richtung)

    def refpunkt(self, typ):
        return self.element.refpunkt(self.richtung, typ)

    def registernr(self):
        return self.element.registernr(self.richtung)

    def hat_koppelweiche(self):
        return self.element.hat_koppelweiche(self.richtung)

    def ereignisse(self):
        return self.element.ereignisse(self.richtung)

    def gegenrichtung(self):
        return ElementUndRichtung(self.element, GEGEN if self.richtung == NORM else NORM)

    def nachfolger(self):
        return self.element.nachfolger(self.richtung)

    def vorgaenger(self):
        return self.element.vorgaenger(self.richtung)

def geschw_min(v1, v2):
    if v1 < 0 and v2 >= 0:
        return v2
    if v2 < 0 and v1 >= 0:
        return v1
    return min(v1, v2)

def geschw_kleiner(v1, v2):
    if v2 < 0 and v1 >= 0:
        return v1 >= 0
    if v1 < 0 and v2 >= 0:
        return False
    return v1 < v2

str_geschw = lambda v : "oo<{:.0f}>".format(v) if v < 0 else "{:.0f}".format(v * 3.6)

float_geschw = lambda v : float("Infinity") if v < 0 else v

SignalZeile = namedtuple('SignalZeile', ['fahrstr_typ', 'hsig_geschw'])
SignalZelle = namedtuple('SignalZelle', ['naechste_vorsignalgeschwindigkeit', 'node'])

class Signal:
    def __init__(self, element_richtung, xml_knoten):
        self.element_richtung = element_richtung
        self.xml_knoten = xml_knoten

        self.betrst = self.xml_knoten.get("NameBetriebsstelle", "")
        self.name = self.xml_knoten.get("Signalname", "")

        self.zeilen = []
        self.spalten = []
        self.matrix = []
        self.signalgeschwindigkeit = None
        self.zs3signalgeschwindigkeiten = []
        self.ist_hilfshauptsignal = False
        self.ist_gleissperre = False

        self.regelgleisanzeiger = 0 # Signalbild-ID
        self.gegengleisanzeiger = 0 # Signalbild-ID
        self.hat_gegengleisanzeiger_in_ersatzsignalmatrix = False
        self.richtungsanzeiger = defaultdict(int) # Ziel-> Signalbild-ID
        self.richtungsvoranzeiger = defaultdict(int) # Ziel -> Signalbild-ID
        self.hat_sigframes = False # Hat das Signal ueberhaupt Landschaftsdateien?
        self.hat_ersatzsignal = False

        self.sigflags = int(self.xml_knoten.get("SignalFlags", 0))
        self.sigtyp = int(self.xml_knoten.get("SignalTyp", 0))
        self.hsig_fuer = 0  # Fahrstrassentypen, fuer die dies ein Hauptsignal ist
        self.zusatzsignal_fuer = 0

        self.vsig_verkn_warnung = False # Wurde Warnung ausgegeben?

        for n in self.xml_knoten:
            if n.tag == "HsigBegriff":
                fahrstr_typ = int(n.get("FahrstrTyp", 0))
                hsig_geschw = float(n.get("HsigGeschw", 0))
                if hsig_geschw == 0:
                    self.hsig_fuer |= fahrstr_typ
                elif hsig_geschw > 0:
                    self.zusatzsignal_fuer |= fahrstr_typ
                self.zeilen.append(SignalZeile(fahrstr_typ, hsig_geschw))
            elif n.tag == "VsigBegriff":
                self.spalten.append(float(n.attrib.get("VsigGeschw", 0)))
            elif n.tag == "SignalFrame":
                self.hat_sigframes = True
            elif n.tag == "MatrixEintrag":
                naechste_vorsignalgeschwindigkeit = float(n.get("MatrixGeschw", 0))
                for ereignis in n:
                    if ereignis.tag == "Ereignis":
                        ereignisnr = int(ereignis.get("Er", 0))
                        beschr = ereignis.get("Beschr", "")
                        if ereignisnr == EREIGNIS_HILFSHAUPTSIGNAL:
                            self.ist_hilfshauptsignal = True
                        elif ereignisnr == EREIGNIS_ENTGLEISEN and float(ereignis.get("Wert", 0)) == 0:
                            self.ist_gleissperre = True
                        elif ereignisnr == EREIGNIS_SIGNALGESCHWINDIGKEIT and self.signalgeschwindigkeit is None and beschr != "vsig":
                            signalgeschwindigkeit = float(ereignis.get("Wert", 0))
                            if signalgeschwindigkeit != 0:
                                self.signalgeschwindigkeit = signalgeschwindigkeit
                        elif ereignisnr == EREIGNIS_SIGNALGESCHWINDIGKEIT and beschr == "vsig":
                            naechste_vorsignalgeschwindigkeit = float(ereignis.get("Wert", 0))
                        elif ereignisnr == EREIGNIS_REGELGLEIS:
                            signalbegriff_nr = int(float(ereignis.get("Wert", 0)))
                            if signalbegriff_nr >= 0 and signalbegriff_nr <= 63:
                                self.regelgleisanzeiger |= 1 << signalbegriff_nr
                            else:
                                logging.warn("{}: Matrix enthaelt Ereignis \"Regelgleis kennzeichnen\" mit Signalbegriff-Nr. {}, die nicht im Bereich 0..63 liegt".format(self, signalbegriff_nr))
                        elif ereignisnr == EREIGNIS_GEGENGLEIS:
                            signalbegriff_nr = int(float(ereignis.get("Wert", 0)))
                            if signalbegriff_nr >= 0 and signalbegriff_nr <= 63:
                                self.gegengleisanzeiger |= 1 << signalbegriff_nr
                            else:
                                logging.warn("{}: Matrix enthaelt Ereignis \"Gegengleis kennzeichnen\" mit Signalbegriff-Nr. {}, die nicht im Bereich 0..63 liegt".format(self, signalbegriff_nr))
                        elif ereignisnr == EREIGNIS_RICHTUNGSANZEIGER_ZIEL:
                            if len(beschr):
                                signalbegriff_nr = int(float(ereignis.get("Wert", 0)))
                                if signalbegriff_nr >= 0 and signalbegriff_nr <= 63:
                                    self.richtungsanzeiger[ereignis.get("Beschr")] |= 1 << signalbegriff_nr
                                else:
                                    logging.warn("{}: Matrix enthaelt Ereignis \"Richtungsanzeiger-Ziel\" mit Signalbegriff-Nr. {}, die nicht im Bereich 0..63 liegt".format(self, signalbegriff_nr))
                            else:
                                logging.warn("{}: Matrix enthaelt Ereignis \"Richtungsanzeiger-Ziel\" ohne Text".format(self))
                        elif ereignisnr == EREIGNIS_RICHTUNGSVORANZEIGER:
                            if len(beschr):
                                signalbegriff_nr = int(float(ereignis.get("Wert", 0)))
                                if signalbegriff_nr >= 0 and signalbegriff_nr <= 63:
                                    self.richtungsvoranzeiger[ereignis.get("Beschr")] |= 1 << signalbegriff_nr
                                else:
                                    logging.warn("{}: Matrix enthaelt Ereignis \"Richtungsvoranzeiger\" mit Signalbegriff-Nr. {}, die nicht im Bereich 0..63 liegt".format(self, signalbegriff_nr))
                            else:
                                logging.warn("{}: Matrix enthaelt Ereignis \"Richtungsvoranzeiger\" ohne Text".format(self))
                self.matrix.append(SignalZelle(naechste_vorsignalgeschwindigkeit, n))
            elif n.tag == "Ersatzsignal":
                self.hat_ersatzsignal = True
                for matrixeintrag in n:
                    if matrixeintrag.tag == "MatrixEintrag":
                        for ereignis in matrixeintrag:
                            if ereignis.tag == "Ereignis":
                                ereignisnr = int(ereignis.get("Er", 0))
                                if ereignisnr == EREIGNIS_GEGENGLEIS:
                                    self.hat_gegengleisanzeiger_in_ersatzsignalmatrix = True
                                    break
                        if self.hat_gegengleisanzeiger_in_ersatzsignalmatrix:
                            break

        vsigeintraege = len(self.spalten)
        signalv = -1
        for n in self.matrix:
            vsigeintraege -= 1
            for ereignis in n.node:
                if ereignis.tag == "Ereignis":
                    ereignisnr = int(ereignis.get("Er", 0))
                    beschr = ereignis.get("Beschr", "")
                    if ereignisnr == EREIGNIS_SIGNALGESCHWINDIGKEIT and beschr != "vsig":
                        signalgeschwindigkeit = float(ereignis.get("Wert", 0))
                        if signalgeschwindigkeit != 0:
                            signalv = geschw_min(signalv, signalgeschwindigkeit)
            if vsigeintraege == 0:
                self.zs3signalgeschwindigkeiten.append(signalv)
                vsigeintraege = len(self.spalten)
                signalv = -1
        self.zs3signalgeschwindigkeiten.append(signalv)

    def __repr__(self):
        if self.betrst == "" and self.name == "":
            return "Signal an Element {}".format(self.element_richtung)
        else:
            return "Signal {} {} an Element {}".format(self.betrst, self.name, self.element_richtung)

    def signalbeschreibung(self):
        return "{} {}".format(self.betrst, self.name)

    def matrix_geschw(self, zeile, spalte):
        return self.matrix[zeile * len(self.spalten) + spalte].naechste_vorsignalgeschwindigkeit

    def ist_hsig_fuer_fahrstr_typ(self, fahrstr_typ):
        return self.hsig_fuer & fahrstr_typ != 0

    def ist_zusatzsignal_fuer_fahrstr_typ(self, fahrstr_typ):
        # Verwendung fuer allein stehende Zs3
        return self.zusatzsignal_fuer & fahrstr_typ != 0 and not self.ist_hsig_fuer_fahrstr_typ(fahrstr_typ) and not self.ist_vsig()

    def ist_fahrstr_start_sig(self, fahrstr_typ):
        # Zusi-Logik: Das Signal muss ein Hauptsignal fuer mindestens einen der bei der
        # Fahrstrassenerzeugung angekreuzten Fahrstrassentypen sein sowie eine Zeile
        # (gleich welcher Geschwindigkeit) fuer `fahrstr_typ` haben.
        #
        # Die fahrstr_gen-Logik ist leicht anders:
        #  - Sie ist unabhaengig davon, ob andere Fahrstrassentypen als `fahrstr_typ` angekreuzt sind.
        #  - Sie verlangt eine Zeile mit v != 0 oder ein Ersatzsignal fuer `fahrstr_typ`, da sonst das
        #    Signal nicht sinnvoll angesteuert werden kann (Zusi steuert in diesem Fall die nicht existente Zeile -1 an).
        return self.ist_hsig_fuer_fahrstr_typ(FAHRSTR_TYP_RANGIER | FAHRSTR_TYP_ZUG | FAHRSTR_TYP_ANZEIGE) and (
            any(zeile.fahrstr_typ & fahrstr_typ != 0 and (self.hat_ersatzsignal or zeile.hsig_geschw != 0) for zeile in self.zeilen))

    def ist_vsig(self):
        # Anders als in der Doku angegeben, ist fuer Zusi anscheinend nur relevant, ob das Signal eine
        # Spalte fuer Geschwindigkeit != -1 hat, also auf die Geschwindigkeit des naechsten Hauptsignals
        # in irgendeiner Weise reagiert. Die Zeilen, insbesondere deren Fahrstrassentypen, werden nicht beachtet.
        return any(spalten_geschw != -1 for spalten_geschw in self.spalten) and len(self.zeilen) > 0

    # Gibt die Matrixzeile zurueck, die in diesem Signal fuer die gegebene Geschwindigkeit != 0 angesteuert werden soll.
    # Das ist normalerweise die Zeile mit der passenden oder naechstkleineren Geschwindigkeit, die groesser als 0 ist.
    # Wenn solche eine Zeile nicht existiert, wird die Zeile mit der naechstgroesseren Geschwindigkeit genommen.
    # Richtungs- und Gegengleisanzeiger werden nicht betrachtet.
    def get_hsig_zeile(self, fahrstr_typ, zielgeschwindigkeit):
        assert zielgeschwindigkeit != 0
        zeile_kleinergleich, geschw_kleinergleich = None, 0
        zeile_groesser, geschw_groesser = None, -1

        for idx, zeile in enumerate(self.zeilen):
            if zeile.fahrstr_typ & fahrstr_typ == 0:
                continue

            # Zeilen fuer Spezialgeschwindigkeiten werden nicht betrachtet.
            if zeile.hsig_geschw == 0.0 or zeile.hsig_geschw == -2.0 or zeile.hsig_geschw == -999.0:
                continue

            if geschw_kleiner(geschw_kleinergleich, zeile.hsig_geschw) and not geschw_kleiner(zielgeschwindigkeit, zeile.hsig_geschw):
                # geschw > geschw_kleinergleich und geschw <= zielgeschwindigkeit
                zeile_kleinergleich = idx
                geschw_kleinergleich = zeile.hsig_geschw

            elif (zeile_groesser is None or geschw_kleiner(zeile.hsig_geschw, geschw_groesser)) and geschw_kleiner(zielgeschwindigkeit, zeile.hsig_geschw):
                # geschw < geschw_groesser und geschw > zielgeschwindigkeit
                zeile_groesser = idx
                geschw_groesser = zeile.hsig_geschw

        if zeile_kleinergleich is None and zeile_groesser is None:
            # WORKAROUND zur Kompatibilitaet mit Zusi: Zusi akzeptiert auch Zeile -2 als Hsig-Geschwindigkeit.
            for idx, zeile in enumerate(self.zeilen):
                if zeile.fahrstr_typ & fahrstr_typ != 0 and zeile.hsig_geschw == -2.0:
                    logging.warn("{}: Nutze Kennlichtzeile {} (Geschwindigkeit -2) als regulaere Fahrstrassenzeile fuer Fahrstrassentyp {} (Geschwindigkeit {})".format(self, idx, str_fahrstr_typ(fahrstr_typ), str_geschw(zielgeschwindigkeit)))
                    return idx

        if zeile_kleinergleich is not None:
            return zeile_kleinergleich
        else:
            # Das ist recht normal, falls Signale nicht geschwindigkeitsabhaengig sind (etwa alleinstehende Zs oder GUe)
            # logging.warn("{}: Nutze Zeile {} (Geschwindigkeit {}) fuer Fahrstrassengeschwindigkeit {}, weil keine Zeile mit kleinerer Geschwindigkeit != 0 existiert.".format(self, zeile_groesser, str_geschw(geschw_groesser), str_geschw(zielgeschwindigkeit)))
            return zeile_groesser

    # Gibt die Zeile zurueck, die die Zeile Nummer `zeilenidx_original` gemaess dem angegebenen Richtungsanzeiger
    # und der angegebenen Gleisangabe erweitert.
    def get_richtungsanzeiger_zeile(self, zeilenidx_original, rgl_ggl, richtungsanzeiger_ziel):
        if not self.hat_sigframes:
            return zeilenidx_original

        neue_signalframes = 0
        if rgl_ggl == GLEIS_GEGENGLEIS:
            neue_signalframes |= self.gegengleisanzeiger
        elif rgl_ggl == GLEIS_REGELGLEIS:
            neue_signalframes |= self.regelgleisanzeiger
        if richtungsanzeiger_ziel != '' and richtungsanzeiger_ziel in self.richtungsanzeiger:
            neue_signalframes |= self.richtungsanzeiger[richtungsanzeiger_ziel]

        if not neue_signalframes:
            return zeilenidx_original

        # Erweitere Signalbild der ersten Spalte der Originalzeile um Richtungs- und Gegengleisanzeiger.
        zielsignalbild = int(self.matrix[zeilenidx_original * len(self.spalten)].node.get("Signalbild", 0)) | neue_signalframes

        # Suche existierende Zeile mit dem neuen Signalbild.
        zeile_original = self.zeilen[zeilenidx_original]
        for idx, zeile in enumerate(self.zeilen):
            if zeile.fahrstr_typ == zeile_original.fahrstr_typ and zeile.hsig_geschw == zeile_original.hsig_geschw and int(self.matrix[idx * len(self.spalten)].node.get("Signalbild", 0)) == zielsignalbild:
                return idx

        # Nicht gefunden, Matrix erweitern.

        # Neuer <HsigBegriff>-Knoten
        self.zeilen.append(self.zeilen[zeilenidx_original])
        hsig_begriff_knoten = ET.Element("HsigBegriff")
        if self.zeilen[zeilenidx_original].fahrstr_typ != 0:
            hsig_begriff_knoten.set("FahrstrTyp", str(self.zeilen[zeilenidx_original].fahrstr_typ))
        if self.zeilen[zeilenidx_original].hsig_geschw != 0:
            hsig_begriff_knoten.set("HsigGeschw", "{:f}".format(self.zeilen[zeilenidx_original].hsig_geschw).rstrip('0').rstrip('.'))
        kindknoten_einfuegen(self.xml_knoten, hsig_begriff_knoten, -1)

        # Neue <MatrixEintrag>-Knoten
        for eintrag in self.matrix[zeilenidx_original * len(self.spalten) : (zeilenidx_original+1) * len(self.spalten)]:
            neuer_eintrag = deepcopy(eintrag)
            neuer_eintrag.node.set("Signalbild", str(int(neuer_eintrag.node.get("Signalbild", 0)) | neue_signalframes))
            kindknoten_einfuegen(self.xml_knoten, neuer_eintrag.node, -1)
            self.matrix.append(neuer_eintrag)

        self.element_richtung.element.modul.geaendert = True

        result = len(self.zeilen) - 1
        logging.debug("{}: Erweitere Signalmatrix: Neue Zeile {} als Kopie von Zeile {} fuer Gleisangabe \"{}\" und Richtungsanzeiger-Ziel \"{}\"".format(self, result, zeilenidx_original, str_rgl_ggl(rgl_ggl), richtungsanzeiger_ziel))
        return result

    def get_hsig_ersatzsignal_zeile(self, rgl_ggl):
        for zeile, begriff in enumerate(self.xml_knoten.iterfind("./Ersatzsignal")):
            if (rgl_ggl == GLEIS_GEGENGLEIS) != (begriff.find("./MatrixEintrag/Ereignis[@Er='28']") is None): \
                return zeile

        return None

    # Gibt die Matrixspalte zurueck, die in diesem Signal fuer die gegebene Geschwindigkeit angesteuert werden soll.
    # Das ist die Zeile mit der passenden oder naechstkleineren Geschwindigkeit.
    def get_vsig_spalte(self, zielgeschwindigkeit):
        if zielgeschwindigkeit == 0:
            try:
                return self.spalten.index(0)
            except ValueError:
                return None

        spalte_kleinergleich, geschw_kleinergleich = None, 0

        for idx, vsig_geschw in enumerate(self.spalten):
            # Spalten fuer die Spezialgeschwindigkeit -2 werden nur betrachtet, wenn tatsaechlich nach dieser Geschwindigkeit gesucht wird.
            if vsig_geschw == -2.0:
                if zielgeschwindigkeit == -2.0:
                    return idx
                continue

            if (geschw_kleiner(geschw_kleinergleich, vsig_geschw) and not geschw_kleiner(zielgeschwindigkeit, vsig_geschw)) or \
                    (spalte_kleinergleich is None and vsig_geschw == 0):
                # geschw > geschw_kleinergleich und geschw <= zielgeschwindigkeit
                spalte_kleinergleich = idx
                geschw_kleinergleich = vsig_geschw

        if spalte_kleinergleich is not None and geschw_kleinergleich == 0 and spalte_kleinergleich != 0 and not self.vsig_verkn_warnung:
            logging.warn("{}: Spalte mit Geschwindigkeit 0 ist nicht erste Spalte, dies wuerde im 3D-Editor momentan zu einer fehlerhaften Vorsignalverknuepfung fuehren.".format(self))
            self.vsig_verkn_warnung = True

        return spalte_kleinergleich

    # Gibt die Spalte zurueck, die die Spalte Nummer `spaltenidx_original` gemaess dem angegebenen Richtungsanzeiger-Ziel
    # und der angegebenen Gleisangabe erweitert.
    def get_richtungsvoranzeiger_spalte(self, spaltenidx_original, rgl_ggl, richtungsanzeiger_ziel):
        if not self.hat_sigframes:
            return spaltenidx_original

        neue_signalframes = 0
        if rgl_ggl == GLEIS_GEGENGLEIS:
            neue_signalframes |= self.gegengleisanzeiger
        elif rgl_ggl == GLEIS_REGELGLEIS:
            neue_signalframes |= self.regelgleisanzeiger
        if richtungsanzeiger_ziel != '' and richtungsanzeiger_ziel in self.richtungsvoranzeiger:
            neue_signalframes |= self.richtungsvoranzeiger[richtungsanzeiger_ziel]

        if not neue_signalframes:
            return spaltenidx_original

        # Erweitere Signalbild der ersten Zeile der Originalspalte um Richtungs- und Gegengleisanzeiger.
        zielsignalbild = int(self.matrix[spaltenidx_original].node.get("Signalbild", 0)) | neue_signalframes

        # Suche existierende Spalte mit dem neuen Signalbild.
        for idx, vsig_geschw in enumerate(self.spalten):
            if vsig_geschw == self.spalten[spaltenidx_original] and int(self.matrix[idx].node.get("Signalbild", 0)) == zielsignalbild:
                return idx

        # Nicht gefunden. Matrix erweitern.
        assert len(self.matrix) == len(self.zeilen) * len(self.spalten)

        # Neuer <VsigBegriff>-Knoten
        vsig_begriff_knoten = ET.Element("VsigBegriff")
        if self.spalten[spaltenidx_original] != 0:
            vsig_begriff_knoten.set("VsigGeschw", "{:f}".format(self.spalten[spaltenidx_original]).rstrip('0').rstrip('.'))
        kindknoten_einfuegen(self.xml_knoten, vsig_begriff_knoten, -1)

        # Neue <MatrixEintrag>-Knoten
        for idx in range(0, len(self.zeilen)):
            neuer_eintrag = deepcopy(self.matrix[idx * (len(self.spalten) + 1) + spaltenidx_original])
            neuer_eintrag.node.set("Signalbild", str(int(neuer_eintrag.node.get("Signalbild", 0)) | neue_signalframes))
            neuer_eintrag_idx = idx * (len(self.spalten) + 1) + (len(self.spalten) - 1)
            kindknoten_einfuegen(self.xml_knoten, neuer_eintrag.node, neuer_eintrag_idx)
            self.matrix.insert(neuer_eintrag_idx + 1, neuer_eintrag)

        self.element_richtung.element.modul.geaendert = True

        self.spalten.append(self.spalten[spaltenidx_original])
        result = len(self.spalten) - 1
        logging.debug("{}: Erweitere Signalmatrix: Neue Spalte {} als Kopie von Spalte {} fuer Gleisangabe \"{}\" und Richtungsvoranzeiger-Ziel \"{}\"".format(self, result, spaltenidx_original, str_rgl_ggl(rgl_ggl), richtungsanzeiger_ziel))
        return result

def ist_hsig_fuer_fahrstr_typ(signal, fahrstr_typ):
    return signal is not None and signal.ist_hsig_fuer_fahrstr_typ(fahrstr_typ)

def ist_zusatzsignal_fuer_fahrstr_typ(signal, fahrstr_typ):
    return signal is not None and signal.ist_zusatzsignal_fuer_fahrstr_typ(fahrstr_typ)

def ist_fahrstr_start_sig(signal, fahrstr_typ):
    return signal is not None and signal.ist_fahrstr_start_sig(fahrstr_typ)

def ist_vsig(signal):
    return signal is not None and signal.ist_vsig()

def gegenrichtung(richtung):
    return GEGEN if richtung == NORM else NORM

str_rgl_ggl = lambda x : { GLEIS_REGELGLEIS: "Regelgleis", GLEIS_GEGENGLEIS: "Gegengleis", GLEIS_EINGLEISIG: "Eingleisige Strecke", GLEIS_BAHNHOF: "Innerhalb Bahnhof" }[x]

st3_attrib_order = {
    "AutorEintrag": ["AutorID", "AutorName", "AutorEmail", "AutorAufwand", "AutorLizenz", "AutorBeschreibung"],
    "BefehlsKonfiguration": ["Dateiname", "NurInfo"],
    "Beschreibung": ["Beschreibung"],
    "b": ["X", "Y", "Z"],
    "Datei": ["Dateiname", "NurInfo"],
    "Ereignis": ["Er", "Beschr", "Wert"],
    "Ersatzsignal": ["ErsatzsigBezeichnung", "ErsatzsigID"],
    "Fahrstrasse": ["FahrstrName", "FahrstrStrecke", "RglGgl", "FahrstrTyp", "ZufallsWert", "Laenge"],
    "FahrstrAufloesung": ["Ref"],
    "FahrstrRegister": ["Ref"],
    "FahrstrSigHaltfall": ["Ref"],
    "FahrstrSignal": ["Ref", "FahrstrSignalZeile", "FahrstrSignalErsatzsignal"],
    "FahrstrStart": ["Ref"],
    "FahrstrTeilaufloesung": ["Ref"],
    "FahrstrVSignal": ["Ref", "FahrstrSignalSpalte"],
    "FahrstrWeiche": ["Ref", "FahrstrWeichenlage"],
    "FahrstrZiel": ["Ref"],
    "g": ["X", "Y", "Z"],
    "HimmelTex": ["Dateiname", "NurInfo"],
    "HintergrundDatei": ["Dateiname", "NurInfo"],
    "HsigBegriff": ["HsigGeschw", "FahrstrTyp"],
    "Info": ["DateiTyp", "Version", "MinVersion", "ObjektID", "Beschreibung", "EinsatzAb", "EinsatzBis", "DateiKategorie"],
    "InfoGegenRichtung": ["vMax", "km", "pos", "Reg", "KoppelWeicheNr", "KoppelWeicheNorm"],
    "InfoNormRichtung": ["vMax", "km", "pos", "Reg", "KoppelWeicheNr", "KoppelWeicheNorm"],
    "Kachelpfad": ["Dateiname", "NurInfo"],
    "KoppelSignal": ["ReferenzNr"],
    "lookat": ["X", "Y", "Z"],
    "MatrixEintrag": ["Signalbild", "MatrixGeschw", "SignalID"],
    "MondTex": ["Dateiname", "NurInfo"],
    "NachGegenModul": ["Nr"],
    "NachGegen": ["Nr"],
    "NachNormModul": ["Nr"],
    "NachNorm": ["Nr"],
    "phi": ["X", "Y", "Z"],
    "PunktXYZ": ["X", "Y", "Z"],
    "p": ["X", "Y", "Z"],
    "ReferenzElemente": ["ReferenzNr", "StrElement", "StrNorm", "RefTyp", "Info"],
    "SignalFrame": ["WeichenbaugruppeIndex", "WeichenbaugruppeNr", "WeichenbaugruppeBeschreibung", "WeichenbaugruppePos0", "WeichenbaugruppePos1"],
    "Signal": ["NameBetriebsstelle", "Stellwerk", "Signalname", "ZufallsWert", "SignalFlags", "SignalTyp", "BoundingR", "Zwangshelligkeit"],
    "Skybox0": ["Dateiname", "NurInfo"],
    "Skybox1": ["Dateiname", "NurInfo"],
    "Skybox2": ["Dateiname", "NurInfo"],
    "Skybox3": ["Dateiname", "NurInfo"],
    "Skybox4": ["Dateiname", "NurInfo"],
    "Skybox5": ["Dateiname", "NurInfo"],
    "SonneHorizontTex": ["Dateiname", "NurInfo"],
    "SonneTex": ["Dateiname", "NurInfo"],
    "SternTex": ["Dateiname", "NurInfo"],
    "StreckenStandort": ["StrInfo"],
    "Strecke": ["RekTiefe", "Himmelsmodell"],
    "StrElement": ["Nr", "Ueberh", "kr", "spTrass", "Anschluss", "Fkt", "Oberbau", "Volt", "Drahthoehe", "Zwangshelligkeit"],
    "up": ["X", "Y", "Z"],
    "UTM": ["UTM_WE", "UTM_NS", "UTM_Zone", "UTM_Zone2"],
    "VsigBegriff": ["VsigGeschw"],
}

def _escape(txt):
    # Nicht die beste Escape-Funktion, aber Zusi macht auch nicht viel mehr.
    # Zur Performance siehe http://stackoverflow.com/a/27086669/1083696 (die Strings in Zusi-XML-Dateien sind eher kurz)
    if "&" in txt:
        txt = txt.replace("&", "&amp;")
    if "<" in txt:
        txt = txt.replace("<", "&lt;")
    if ">" in txt:
        txt = txt.replace(">", "&gt;")
    if '"' in txt:
        txt = txt.replace('"', "&quot;")
    if "'" in txt:
        txt = txt.replace("'", "&apos;")
    return txt

# Schreibt eine Streckendatei im selben Format wie Zusi, um Diffs zu minimieren:
# Keine Einrueckung, Attributreihenfolge gleich, Zeilenende CR+LF.
def writeuglyxml(fp, elem):
    buf = []
    do_writeuglyxml(elem, buf)
    fp.write(''.join(buf).encode("utf-8"))

def index_or_9999(l, elem):
    try:
        return l.index(elem)
    except ValueError:
        return 9999

def do_writeuglyxml(elem, buf):
    try:
        attrib_order = st3_attrib_order[elem.tag]
    except KeyError:
        attrib_order = []

    buf.append(u"<{}".format(elem.tag))
    buf.extend([u" {}=\"{}\"".format(k, _escape(v)) for k, v in sorted(elem.items(), key = lambda i: index_or_9999(attrib_order, i[0]))])
    if len(elem):
      buf.append(u">\r\n")
      for child in elem:
        do_writeuglyxml(child, buf)
      buf.append(u"</{}>\r\n".format(elem.tag))
    else:
      buf.append(u"/>\r\n")
