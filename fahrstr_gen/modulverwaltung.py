#!/usr/bin/env python3

import xml.etree.ElementTree as ET
import sys
import os
import io
import argparse
import math
from collections import defaultdict

from .konstanten import *

import logging

path_insensitive_cache = {}

# http://stackoverflow.com/a/8462613/1083696
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

class RefPunkt(object):
    def __init__(self, refnr, reftyp, element_richtung):
        self.refnr = refnr
        self.reftyp = reftyp
        self.element_richtung = element_richtung

    def __repr__(self):
        global dieses_modul
        return "Element {}{}{}".format(
            self.element_richtung.element.xml_knoten.get("Nr", "0"),
            'n' if self.element_richtung.richtung == NORM else 'g',
            "" if self.element_richtung.element.modul == dieses_modul else "[{}]".format(self.modul_kurz())
        )

    def modul_kurz(self):
        return os.path.basename(self.element_richtung.element.modul.relpath.replace('\\', os.sep))

    def signal(self):
        return self.element_richtung.signal()

    def to_xml(self, node):
        node.attrib["Ref"] = str(self.refnr)
        ET.SubElement(node, 'Datei', { "Dateiname": self.element_richtung.element.modul.relpath, "NurInfo": "1" })

def normalize_zusi_relpath(relpath):
    return relpath.upper().replace('/', '\\')

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
        ], set(["DatenVerzeichnis", "DatenDir", "DatenVerzeichnisDemo", "DatenDirDemo"]))
        if registry_values is not None:
            if "DatenVerzeichnis" in registry_values:
                return registry_values["DatenVerzeichnis"]
            elif "DatenDir" in registry_values:
                return registry_values["DatenDir"]
            elif "DatenVerzeichnisDemo" in registry_values:
                return registry_values["DatenVerzeichnisDemo"]
            elif "DatenDirDemo" in registry_values:
                return registry_values["DatenDirDemo"]
    except ImportError:
        return ""

def get_zusi_relpath(realpath):
    if not os.path.isabs(realpath):
        realpath = os.path.abspath(realpath)
    return os.path.relpath(realpath, get_zusi_datapath())

def get_abspath(zusi_relpath):
    return path_insensitive(os.path.join(get_zusi_datapath(), zusi_relpath.lstrip('\\').strip().replace('\\', os.sep)))

# Modulname -> (Modul oder None, wenn das Modul nicht existiert)
module = dict()

dieses_modul = None

class Modul:
    def __init__(self, relpath, root):
        from .strecke import Element, ElementUndRichtung  # get around circular dependency by deferring the import to here

        self.relpath = relpath
        self.root = root
        self.streckenelemente = dict(
            (int(s.get("Nr", 0)), Element(self, s))
            for s in root.findall("./Strecke/StrElement")
        )

        self.referenzpunkte = defaultdict(list)
        for r in root.findall("./Strecke/ReferenzElemente"):
            try:
                element = self.streckenelemente[int(r.get("StrElement", 0))]
                self.referenzpunkte[element].append(RefPunkt(
                    int(r.get("ReferenzNr", 0)),
                    int(r.get("RefTyp", 0)),
                    ElementUndRichtung(element, NORM if int(r.get("StrNorm", 0)) == 1 else GEGEN)
                ))
            except KeyError:
                logging.debug("Referenzpunkt {} in Modul {} verweist auf ungueltiges Streckenelement {}".format(int(r.get("ReferenzNr", 0)), self.relpath, int(r.get("StrElement", 0))))

        self.referenzpunkte_by_nr = dict((r.refnr, r) for rs in self.referenzpunkte.values() for r in rs)
        self.signale = dict()

    def get_signal(self, xml_knoten):
        if xml_knoten is None:
            return None

        try:
            return self.signale[xml_knoten]
        except KeyError:
            from .strecke import Signal  # get around circular dependency by deferring the import to here
            result = Signal(xml_knoten)
            self.signale[xml_knoten] = result
            return result

    def name_kurz(self):
        return os.path.basename(self.relpath.replace('\\', os.sep))

# Sucht Knoten ./Datei und liefert Modul oder None zurueck (leerer String oder nicht vorhandener Knoten = Fallback)
def get_modul_aus_dateiknoten(knoten, fallback):
    datei = knoten.find("./Datei")
    if datei is not None and "Dateiname" in datei.attrib:
        modul_relpath = normalize_zusi_relpath(datei.attrib["Dateiname"])
        if modul_relpath not in module:
            dateiname = get_abspath(datei.attrib["Dateiname"])
            try:
                logging.debug("Lade Modul {}".format(datei.attrib["Dateiname"]))
                module[modul_relpath] = Modul(datei.attrib["Dateiname"], ET.parse(dateiname))
            except FileNotFoundError:
                logging.warn("Moduldatei {} nicht gefunden".format(dateiname))
                module[modul_relpath] = None
        return module[modul_relpath]
    return fallback
