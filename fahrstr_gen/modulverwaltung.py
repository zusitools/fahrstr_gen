#!/usr/bin/env python3

import xml.etree.ElementTree as ET
import os
import tempfile
import shutil
from collections import defaultdict
from functools import lru_cache

from .konstanten import *

import logging

path_insensitive_cache = {}

# http://stackoverflow.com/a/8462613
def path_insensitive(path):
    """
    Get a case-insensitive path for use on a case sensitive system.
    """
    try:
        return path_insensitive_cache[path]
    except KeyError:
        ret = _path_insensitive(path) or path
        path_insensitive_cache[path] = ret
        return ret

def _path_insensitive(path):
    """
    Recursive part of path_insensitive to do the work.
    """

    if path == '' or os.path.exists(path):
        return path

    base = os.path.basename(path)  # may be a directory or a file
    dirname = os.path.dirname(path)

    suffix = ''
    if not base:  # dir ends with a slash?
        if len(dirname) < len(path):
            suffix = path[:len(path) - len(dirname)]

        base = os.path.basename(dirname)
        dirname = os.path.dirname(dirname)

    if not os.path.exists(dirname):
        dirname = _path_insensitive(dirname)
        if not dirname:
            return

    # at this point, the directory exists but not the file

    try:  # we are expecting dirname to be a directory, but it could be a file
        files = os.listdir(dirname)
    except OSError:
        return

    baselow = base.lower()
    try:
        basefinal = next(fl for fl in files if fl.lower() == baselow)
    except StopIteration:
        return

    if basefinal:
        return os.path.join(dirname, basefinal) + suffix
    else:
        return

class RefPunkt:
    def __init__(self, refnr, reftyp, element_richtung):
        self.refnr = refnr
        self.reftyp = reftyp
        self.element_richtung = element_richtung

    def __repr__(self):
        global dieses_modul
        return "{}{}{}".format(
            self.element_richtung.element.xml_knoten.get("Nr", "0"),
            'b' if self.element_richtung.richtung == NORM else 'g',
            "" if self.element_richtung.element.modul == dieses_modul else "[{}]".format(self.modul_kurz())
        )

    def modul_kurz(self):
        return os.path.basename(self.element_richtung.element.modul.relpath.replace('\\', os.sep))

    def signal(self):
        return self.element_richtung.signal()

    def to_xml(self, node):
        node.attrib["Ref"] = str(self.refnr)
        ET.SubElement(node, 'Datei', {"Dateiname": self.element_richtung.element.modul.relpath, "NurInfo": "1" })

# aus zusicommon
# From the first key in "keys" that contains a value, returns a dictionary
# with the values indexed by "valuenames"
def read_registry_strings(keys, valuenames):
    result = {}

    try:
        import winreg
        for (root, path) in keys:
            try:
                key = winreg.OpenKey(root, path)
            except WindowsError:
                continue

            # We have to enumerate all key-value pairs in the open key
            try:
                index = 0
                while True:
                    # The loop will be ended by a WindowsError being thrown when there
                    # are no more key-value pairs
                    value = winreg.EnumValue(key, index)
                    if value[0] in valuenames and value[1] != "":
                        result[value[0]] = value[1]
                    index += 1
            except WindowsError:
                pass

            if len(result):
                break

    except ImportError:
        # we're not on Windows
        return None
    except WindowsError:
        return None

    return result if len(result) else None

# aus zusicommon, angepasst
@lru_cache(maxsize=None)
def get_zusi_datapath():
    result = os.environ.get("ZUSI3_DATAPATH", None)

    if result is not None:
        return result

    try:
        import winreg
        registry_values = read_registry_strings([
            (winreg.HKEY_LOCAL_MACHINE, "Software\\Zusi3"),
            (winreg.HKEY_LOCAL_MACHINE, "Software\\Wow6432Node\\Zusi3"),
            (winreg.HKEY_CURRENT_USER, "Software\\Zusi3"),
            (winreg.HKEY_CURRENT_USER, "Software\\Wow6432Node\\Zusi3"),
        ], set(["DatenVerzeichnis", "DatenVerzeichnisSteam", "DatenVerzeichnisDemo", "DatenDir", "DatenDirDemo"]))
        if registry_values is not None:
            if "DatenVerzeichnis" in registry_values:
                return registry_values["DatenVerzeichnis"]
            elif "DatenVerzeichnisSteam" in registry_values:
                return registry_values["DatenVerzeichnisSteam"]
            elif "DatenDir" in registry_values:
                return registry_values["DatenDir"]
            elif "DatenVerzeichnisDemo" in registry_values:
                return registry_values["DatenVerzeichnisDemo"]
            elif "DatenDirDemo" in registry_values:
                return registry_values["DatenDirDemo"]
    except ImportError:
        return ""

    return ""

@lru_cache(maxsize=None)
def get_zusi_datapath_official():
    result = os.environ.get("ZUSI3_DATAPATH_OFFICIAL", None)

    if result is not None:
        return result

    try:
        import winreg
        registry_values = read_registry_strings([
            (winreg.HKEY_LOCAL_MACHINE, "Software\\Zusi3"),
            (winreg.HKEY_LOCAL_MACHINE, "Software\\Wow6432Node\\Zusi3"),
            (winreg.HKEY_CURRENT_USER, "Software\\Zusi3"),
            (winreg.HKEY_CURRENT_USER, "Software\\Wow6432Node\\Zusi3"),
        ], set(["DatenVerzeichnisOffiziell", "DatenVerzeichnisOffiziellSteam", ]))
        if registry_values is not None:
            if "DatenVerzeichnisOffiziell" in registry_values:
                return registry_values["DatenVerzeichnisOffiziell"]
            elif "DatenVerzeichnisOffiziellSteam" in registry_values:
                return registry_values["DatenVerzeichnisOffiziellSteam"]
    except ImportError:
        return ""

    return get_zusi_datapath()

# Konvertiert einen Dateisystempfad in einen Pfad relativ zum Zusi-Dateiverzeichnis mit Backslash als Verzeichnistrenner.
def get_zusi_relpath(realpath):
    try:
        candidate1 = os.path.relpath(realpath, get_zusi_datapath())
    except ValueError:
        candidate1 = None

    try:
        candidate2 = os.path.relpath(realpath, get_zusi_datapath_official())
    except ValueError:
        candidate2 = None

    if candidate1 is None or candidate1.startswith(os.pardir):
        if candidate2 is None:
            raise Exception("Kann {} nicht in Zusi-relativen Pfad umwandeln (Datenverzeichnis: {}, Datenverzeichnis offiziell: {})".format(realpath, get_zusi_datapath(), get_zusi_datapath_official()))
        else:
            return candidate2.replace('/', '\\')
    else:
        return candidate1.replace('/', '\\')

# Gibt eine kanonische Version des angegebenen Zusi-Pfades zurueck.
def normalize_zusi_relpath(relpath):
    return relpath.upper().lstrip('\\').strip()

# Konvertiert einen Zusi-Pfad (relativ zum Zusi-Datenverzeichnis) in einen Pfad auf dem aktuellen Dateisystem.
def get_abspath(zusi_relpath, force_user_dir=False):
    zusi_relpath = zusi_relpath.lstrip('\\').strip().replace('\\', os.sep)
    result = path_insensitive(os.path.join(get_zusi_datapath(), zusi_relpath))
    if force_user_dir or os.path.exists(result):
        return result
    return path_insensitive(os.path.join(get_zusi_datapath_official(), zusi_relpath))

# Relativer Zusi-Pfad -> (Modul oder None, wenn das Modul nicht existiert)
module = dict()

dieses_modul = None

class Modul:
    def __init__(self, dateiname, relpath):
        from .strecke import Element, ElementUndRichtung  # get around circular dependency by deferring the import to here

        self.dateiname = dateiname
        self.relpath = relpath
        self.root = ET.parse(dateiname).getroot() # XML-Knoten
        self.streckenelemente = dict(  # Nr -> StrElement
            (int(s.get("Nr", 0)), Element(self, s))
            for s in self.root.findall("./Strecke/StrElement")
        )

        self.referenzpunkte = defaultdict(list)  # Element -> [RefPunkt]
        for r in self.root.findall("./Strecke/ReferenzElemente"):
            try:
                element = self.streckenelemente[int(r.get("StrElement", 0))]
                self.referenzpunkte[element].append(RefPunkt(
                    int(r.get("ReferenzNr", 0)),
                    int(r.get("RefTyp", 0)),
                    ElementUndRichtung(element, NORM if int(r.get("StrNorm", 0)) == 1 else GEGEN)
                ))
            except KeyError:
                logging.debug("Referenzpunkt {} in Modul {} verweist auf ungueltiges Streckenelement {}".format(int(r.get("ReferenzNr", 0)), self.relpath, int(r.get("StrElement", 0))))

        self.referenzpunkte_by_nr = dict((r.refnr, r) for rs in self.referenzpunkte.values() for r in rs)  # Nr -> RefPunkt
        self.geaendert = False

    def name_kurz(self):
        return os.path.basename(self.relpath.replace('\\', os.sep))

    # (utm_we, utm_ns)
    def utm(self):
        utm_knoten = self.root.find("./Strecke/UTM")
        if utm_knoten is None:
            return (0, 0)
        return (float(utm_knoten.get("UTM_WE", 0)), float(utm_knoten.get("UTM_NS", 0)))

    def schreibe_moduldatei(self):
        from .strecke import writeuglyxml

        fp = tempfile.NamedTemporaryFile('wb', delete = False)
        with fp:
            fp.write(b"\xef\xbb\xbf")
            fp.write(u'<?xml version="1.0" encoding="UTF-8"?>\r\n'.encode("utf-8"))
            writeuglyxml(fp, self.root)
        out_filename = get_abspath(self.relpath, force_user_dir=True)
        os.makedirs(os.path.dirname(out_filename), exist_ok=True)
        shutil.copyfile(fp.name, out_filename)
        os.remove(fp.name)

# Liefert das angegebene Modul oder None zurueck (relpath leer = Fallback)
def get_modul_by_name(relpath, fallback):
    if not len(relpath):
        return fallback

    relpath_norm = normalize_zusi_relpath(relpath)
    if relpath_norm not in module:
        dateiname = get_abspath(relpath)
        try:
            logging.debug("Lade Modul {} ({})".format(relpath, dateiname))
            module[relpath_norm] = Modul(dateiname, relpath)
        except FileNotFoundError:
            logging.warn("Moduldatei {} nicht gefunden".format(dateiname))
            module[relpath_norm] = None
    return module[relpath_norm]

# Sucht Knoten ./Datei und liefert Modul oder None zurueck (leerer String oder nicht vorhandener Knoten = Fallback)
def get_modul_aus_dateiknoten(knoten, fallback):
    datei = knoten.find("./Datei")
    if datei is not None and "Dateiname" in datei.attrib:
        relpath = datei.attrib["Dateiname"]
        return get_modul_by_name(relpath, fallback)
    return fallback
