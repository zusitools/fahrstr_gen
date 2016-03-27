from collections import namedtuple
from .konstanten import *
from .modulverwaltung import get_modul_aus_dateiknoten

import math

Element = namedtuple('ElementUndRichtung', ['modul', 'element'])
ElementUndRichtung = namedtuple('ElementUndRichtung', ['modul', 'element', 'richtung'])

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

def ist_hsig_fuer_fahrstr_typ(signal, fahrstr_typ):
    return signal is not None and any(float(h.attrib.get("HsigGeschw", 0)) == 0 and int(h.attrib.get("FahrstrTyp", 0)) & fahrstr_typ != 0 for h in signal.findall("./HsigBegriff"))

def element_laenge(element):
    p1 = [0, 0, 0]
    p2 = [0, 0, 0]

    for (knotenname, pos) in [("b", p1), ("g", p2)]:
        knoten = element.find(knotenname)
        if knoten is not None:
            for idx, attribname in enumerate(["X", "Y", "Z"]):
                pos[idx] = float(knoten.attrib.get(attribname, 0))

    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2)

def nachfolger_elemente(element_richtung):
    if element_richtung is None:
        return None

    anschluss = int(element_richtung.element.attrib.get("Anschluss", 0))

    nachfolger_knoten = [n for n in element_richtung.element if
        (element_richtung.richtung == NORM and (n.tag == "NachNorm" or n.tag == "NachNormModul")) or
        (element_richtung.richtung == GEGEN and (n.tag == "NachGegen" or n.tag == "NachGegenModul"))]
    nachfolger = []

    for idx, n in enumerate(nachfolger_knoten):
        anschluss_shift = idx + (8 if element_richtung.richtung == GEGEN else 0)
        if "Modul" not in n.tag:
            nach_modul = element_richtung.modul
            try:
                nach_el = nach_modul.streckenelemente[int(n.attrib.get("Nr", 0))]
            except KeyError:
                nachfolger.append(None)
                continue
            nach_richtung = NORM if (anschluss >> anschluss_shift) & 1 == 0 else GEGEN
        else:
            nach_modul = get_modul_aus_dateiknoten(n, element_richtung.modul)
            if nach_modul is None:
                nachfolger.append(None)
                continue

            try:
                nach_ref = nach_modul.referenzpunkte_by_nr[int(n.attrib.get("Nr", 0))]
            except KeyError:
                nachfolger.append(None)
                continue

            nach_el = nach_ref.element
            nach_richtung = GEGEN if nach_ref.richtung == NORM else NORM # Richtung zeigt zur Modulschnittstelle -> umkehren

        nachfolger.append(ElementUndRichtung(nach_modul, nach_el, nach_richtung))

    return nachfolger

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
    return txt.replace("&", "&amp;").replace(">", "&gt;").replace("<", "&lt;").replace('"', '&quot;').replace("'", "&apos;")

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
