from collections import namedtuple, defaultdict
from copy import deepcopy
import xml.etree.ElementTree as ET

from .konstanten import *
from . import modulverwaltung

import logging
import math

class Element(namedtuple('ElementUndRichtung', ['modul', 'element'])):
    def __repr__(self):
        if self.modul == modulverwaltung.dieses_modul:
            return self.element.get("Nr", "0")
        else:
            return "{}[{}]".format(self.element.get("Nr", "0"), self.modul.name_kurz())

    def richtung(self, richtung):
        return ElementUndRichtung(self.modul, self.element, richtung)

    def signal(self, richtung):
        return self.modul.get_signal(self.element.find("./Info" + ("Norm" if richtung == NORM else "Gegen") + "Richtung/Signal"))

    def refpunkt(self, richtung, typ):
        for refpunkt in self.modul.referenzpunkte[self.element]:
            if refpunkt.richtung == richtung and refpunkt.reftyp == typ:
                return refpunkt
        return None

class ElementUndRichtung(namedtuple('ElementUndRichtung', ['modul', 'element', 'richtung'])):
    def __repr__(self):
        if self.modul == modulverwaltung.dieses_modul:
            return self.element.get("Nr", "0") + ("b" if self.richtung == NORM else "g")
        else:
            return "{}{}[{}]".format(self.element.get("Nr", "0"), "b" if self.richtung == NORM else "g", self.modul.name_kurz())

    def signal(self):
        return self.modul.get_signal(self.element.find("./Info" + ("Norm" if self.richtung == NORM else "Gegen") + "Richtung/Signal"))

    def refpunkt(self, typ):
        for refpunkt in self.modul.referenzpunkte[self.element]:
            if refpunkt.richtung == self.richtung and refpunkt.reftyp == typ:
                return refpunkt
        return None

    def registernr(self):
        richtungsinfo = self.element.find("./Info" + ("Norm" if self.richtung == NORM else "Gegen") + "Richtung")
        return 0 if richtungsinfo is None else int(richtungsinfo.get("Reg", 0))

    def ereignisse(self):
        # TODO: eventuell auch Ereignisse in Signalen beachten?
        return self.element.iterfind("./Info" + ("Norm" if self.richtung == NORM else "Gegen") + "Richtung/Ereignis")

    def gegenrichtung(self):
        return ElementUndRichtung(self.modul, self.element, GEGEN if self.richtung == NORM else NORM)

def geschw_min(v1, v2):
    if v1 < 0:
        return v2
    if v2 < 0:
        return v1
    return min(v1, v2)

def geschw_kleiner(v1, v2):
    if v2 < 0:
        return v1 >= 0
    if v1 < 0:
        return False
    return v1 < v2

str_geschw = lambda v : "oo<{:.0f}>".format(v) if v < 0 else "{:.0f}".format(v * 3.6)

float_geschw = lambda v : float("Infinity") if v < 0 else v

SignalZeile = namedtuple('SignalZeile', ['fahrstr_typ', 'hsig_geschw'])
Ereignis = namedtuple('Ereignis', ['nr', 'wert', 'beschr'])

class Signal:
    def __init__(self, xml_knoten):
        self.xml_knoten = xml_knoten
        self.zeilen = []
        self.spalten = []
        self.signalgeschwindigkeit = None
        self.ist_hilfshauptsignal = False

        self.gegengleisanzeiger = 0 # Signalbild-ID
        self.richtungsanzeiger = defaultdict(int) # Ziel-> Signalbild-ID
        self.hat_richtungsvoranzeiger = False

        self.sigflags = int(self.xml_knoten.get("SignalFlags", 0))

        for n in self.xml_knoten:
            if n.tag == "HsigBegriff":
                self.zeilen.append(SignalZeile(int(n.get("FahrstrTyp", 0)), float(n.attrib.get("HsigGeschw", 0))))
            elif n.tag == "VsigBegriff":
                self.spalten.append(float(n.attrib.get("VsigGeschw", 0)))
            elif n.tag == "MatrixEintrag":
                for ereignis in n:
                    if ereignis.tag == "Ereignis":
                        ereignisnr = int(ereignis.get("Er", 0))
                        if ereignisnr == EREIGNIS_HILFSHAUPTSIGNAL:
                            self.ist_hilfshauptsignal = True
                        elif ereignisnr == EREIGNIS_SIGNALGESCHWINDIGKEIT and self.signalgeschwindigkeit is None:
                            self.signalgeschwindigkeit = float(ereignis.get("Wert", 0))
                        elif ereignisnr == EREIGNIS_GEGENGLEIS:
                            self.gegengleisanzeiger |= 1 << int(float(ereignis.get("Wert", 0)))
                        elif ereignisnr == EREIGNIS_RICHTUNGSANZEIGER_ZIEL:
                            if ereignis.get("Beschr") is not None:
                                self.richtungsanzeiger[ereignis.get("Beschr")] |= 1 << int(float(ereignis.get("Wert", 0)))
                        elif ereignisnr == EREIGNIS_RICHTUNGSVORANZEIGER:
                            self.hat_richtungsvoranzeiger = True

    def __repr__(self):
        return self.signalbeschreibung()

    def signalbeschreibung(self):
        return "{} {}".format(self.xml_knoten.get("NameBetriebsstelle", ""), self.xml_knoten.get("Signalname"))

    def hat_zeile_fuer_fahrstr_typ(self, fahrstr_typ):
        return any(z.fahrstr_typ & fahrstr_typ != 0 for z in self.zeilen)

    def ist_hsig_fuer_fahrstr_typ(self, fahrstr_typ):
        return any(z.hsig_geschw == 0 and (z.fahrstr_typ & fahrstr_typ != 0) for z in self.zeilen)

    # Gibt die Matrixzeile zurueck, die in diesem Signal fuer die gegebene Geschwindigkeit != 0 angesteuert werden soll.
    # Das ist normalerweise die Zeile mit der passenden oder naechstkleineren Geschwindigkeit, die groesser als 0 ist.
    # Wenn solche eine Zeile nicht existiert, wird die Zeile mit der naechstgroesseren Geschwindigkeit genommen.
    # Richtungs- und Gegengleisanzeiger werden nicht betrachtet.
    def get_hsig_zeile(self, fahrstr_typ, zielgeschwindigkeit):
        assert(zielgeschwindigkeit != 0)
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
                    logging.warn("{}: Nutze Kennlichtzeile (Geschwindigkeit -2) als regulaere Fahrstrassenzeile (Geschwindigkeit {})".format(self, str_geschw(zielgeschwindigkeit)))
                    return idx

        return zeile_kleinergleich if zeile_kleinergleich is not None else zeile_groesser

    # Gibt die Zeile zurueck, die die Zeile Nummer `zeilenidx_original` gemaess dem angegebenen Richtungsanzeiger
    # und der angegebenen Gleisangabe erweitert.
    def get_richtungsanzeiger_zeile(self, zeilenidx_original, rgl_ggl, richtungsanzeiger_ziel):
        if rgl_ggl != GLEIS_GEGENGLEIS and richtungsanzeiger_ziel == '':
            return zeilenidx_original
        if rgl_ggl != GLEIS_GEGENGLEIS and richtungsanzeiger_ziel not in self.richtungsanzeiger:
            return zeilenidx_original
        if richtungsanzeiger_ziel == '' and self.gegengleisanzeiger == 0:
            return zeilenidx_original

        matrix = self.xml_knoten.findall("./MatrixEintrag")

        # Erweitere Signalbild der ersten Spalte der Originalzeile um Richtungs- und Gegengleisanzeiger.
        zielsignalbild = int(matrix[zeilenidx_original * len(self.spalten)].get("Signalbild", 0))
        neue_signalframes = 0
        if rgl_ggl == GLEIS_GEGENGLEIS:
            neue_signalframes |= self.gegengleisanzeiger
        if richtungsanzeiger_ziel != '' and richtungsanzeiger_ziel in self.richtungsanzeiger:
            neue_signalframes |= self.richtungsanzeiger[richtungsanzeiger_ziel]
        zielsignalbild |= neue_signalframes

        # Suche existierende Zeile mit dem neuen Signalbild.
        zeile_original = self.zeilen[zeilenidx_original]
        for idx, zeile in enumerate(self.zeilen):
            if zeile.fahrstr_typ == zeile_original.fahrstr_typ and zeile.hsig_geschw == zeile_original.hsig_geschw and int(matrix[idx * len(self.spalten)].get("Signalbild", 0)) == zielsignalbild:
                return idx

        # Nicht gefunden, Matrix erweitern.
        # TODO: Warnen, wenn nicht im aktuellen Modul.

        # Neuer <HsigBegriff>-Knoten
        einfuegeindex_hsigbegriff = 1
        for idx, n in enumerate(self.xml_knoten):
            if n.tag == "HsigBegriff":
                einfuegeindex_hsigbegriff = idx + 1

        self.zeilen.append(self.zeilen[zeilenidx_original])
        hsig_begriff_knoten = ET.Element("HsigBegriff")
        if self.zeilen[zeilenidx_original].fahrstr_typ != 0:
            hsig_begriff_knoten.set("FahrstrTyp", str(self.zeilen[zeilenidx_original].fahrstr_typ))
        if self.zeilen[zeilenidx_original].hsig_geschw != 0:
            hsig_begriff_knoten.set("HsigGeschw", str(self.zeilen[zeilenidx_original].hsig_geschw))
        self.xml_knoten.insert(einfuegeindex_hsigbegriff, hsig_begriff_knoten)

        # Neue <MatrixEintrag>-Knoten
        einfuegeindex_matrixeintrag = 1
        for idx, n in enumerate(self.xml_knoten):
            if n.tag == "MatrixEintrag":
                einfuegeindex_matrixeintrag = idx + 1

        for eintrag in matrix[zeilenidx_original * len(self.spalten) : (zeilenidx_original+1) * len(self.spalten)]:
            neuer_eintrag = deepcopy(eintrag)
            neuer_eintrag.set("Signalbild", str(int(neuer_eintrag.get("Signalbild", 0)) | neue_signalframes))
            self.xml_knoten.insert(einfuegeindex_matrixeintrag, neuer_eintrag)
            einfuegeindex_matrixeintrag += 1

        return len(self.zeilen) - 1

    def get_hsig_ersatzsignal_zeile(self, rgl_ggl):
        for zeile, begriff in enumerate(self.xml_knoten.iterfind("./Ersatzsignal")):
            if (rgl_ggl == GLEIS_GEGENGLEIS) ^ (begriff.find("./MatrixEintrag/Ereignis[@Er='28']") is None): \
                return zeile

        return None

def ist_hsig_fuer_fahrstr_typ(signal, fahrstr_typ):
    return signal is not None and signal.ist_hsig_fuer_fahrstr_typ(fahrstr_typ)

def element_laenge(element):
    p1 = [0, 0, 0]
    p2 = [0, 0, 0]

    for n in element:
        if n.tag == "b":
            p1[0] = float(n.get("X", 0))
            p1[1] = float(n.get("Y", 0))
            p1[2] = float(n.get("Z", 0))
        elif n.tag == "g":
            p2[0] = float(n.get("X", 0))
            p2[1] = float(n.get("Y", 0))
            p2[2] = float(n.get("Z", 0))

    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2)

def nachfolger_elemente(element_richtung):
    if element_richtung is None:
        return None

    anschluss = int(element_richtung.element.get("Anschluss", 0))

    nachfolger_knoten = [n for n in element_richtung.element if
        (element_richtung.richtung == NORM and (n.tag == "NachNorm" or n.tag == "NachNormModul")) or
        (element_richtung.richtung == GEGEN and (n.tag == "NachGegen" or n.tag == "NachGegenModul"))]
    nachfolger = []

    for idx, n in enumerate(nachfolger_knoten):
        anschluss_shift = idx + (8 if element_richtung.richtung == GEGEN else 0)
        if "Modul" not in n.tag:
            nach_modul = element_richtung.modul
            try:
                nach_el = nach_modul.streckenelemente[int(n.get("Nr", 0))]
            except KeyError:
                nachfolger.append(None)
                continue
            nach_richtung = NORM if (anschluss >> anschluss_shift) & 1 == 0 else GEGEN
        else:
            nach_modul = modulverwaltung.get_modul_aus_dateiknoten(n, element_richtung.modul)
            if nach_modul is None:
                nachfolger.append(None)
                continue

            try:
                nach_ref = nach_modul.referenzpunkte_by_nr[int(n.get("Nr", 0))]
            except KeyError:
                nachfolger.append(None)
                continue

            nach_el = nach_ref.element
            nach_richtung = GEGEN if nach_ref.richtung == NORM else NORM # Richtung zeigt zur Modulschnittstelle -> umkehren

        nachfolger.append(ElementUndRichtung(nach_modul, nach_el, nach_richtung))

    return nachfolger

def gegenrichtung(richtung):
    return GEGEN if richtung == NORM else NORM

def vorgaenger_elemente(element_richtung):
    if element_richtung is None:
        return None

    return [e.gegenrichtung() for e in nachfolger_elemente(element_richtung.gegenrichtung()) if e is not None]

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
    # TODO: das ist nicht die beste Escape-Funktion, aber Zusi macht auch nicht viel mehr.
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
    tag = elem.tag

    fp.write(u"<{}".format(tag).encode("utf-8"))

    for k, v in sorted(elem.attrib.items(), key = lambda i: i[0] if tag not in st3_attrib_order else st3_attrib_order[tag].index(i[0])):
      fp.write(u" {}=\"{}\"".format(k, _escape(v)).encode("utf-8"))

    if len(elem):
      fp.write(u">\r\n".encode("utf-8"))
      for child in elem:
        writeuglyxml(fp, child)
      fp.write(u"</{}>\r\n".format(tag).encode("utf-8"))
    else:
      fp.write(u"/>\r\n".encode("utf-8"))
