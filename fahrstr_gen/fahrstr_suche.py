#!/usr/bin/env python3

import xml.etree.ElementTree as ET
from collections import OrderedDict

from .konstanten import *
from .fahrstrasse import EinzelFahrstrasse, Fahrstrasse, FahrstrHauptsignal, FahrstrVorsignal, FahrstrWeichenstellung
from .strecke import ist_hsig_fuer_fahrstr_typ, geschw_min, str_geschw, gegenrichtung
from . import modulverwaltung

import logging

class FahrstrassenSuche:
    def __init__(self, fahrstr_typ, bedingungen, vorsignal_graph, flankenschutz_graph):
        self.einzelfahrstrassen = dict()  # KnotenUndRichtung -> [EinzelFahrstrasse]
        self.fahrstr_typ = fahrstr_typ
        self.bedingungen = bedingungen
        self.vorsignal_graph = vorsignal_graph
        self.flankenschutz_graph = flankenschutz_graph

    # Gibt alle vom angegebenen Knoten ausgehenden (kombinierten) Fahrstrassen in der angegebenen Richtung zurueck.
    def get_fahrstrassen(self, knoten, richtung):
        logging.debug("Suche Fahrstrassen ab {}".format(knoten.richtung(richtung)))
        result = []
        for einzelfahrstrasse in self._get_einzelfahrstrassen(knoten, richtung):
            self._get_fahrstrassen_rek([einzelfahrstrasse], result)
        return result

    # Gibt alle vom angegebenen Knoten ausgehenden Einzelfahrstrassen in der angegebenen Richtung zurueck.
    def _get_einzelfahrstrassen(self, knoten, richtung):
        key = knoten.richtung(richtung)
        try:
            return self.einzelfahrstrassen[key]
        except KeyError:
            logging.debug("Suche Einzelfahrstrassen ab {}".format(key))
            result = self._suche_einzelfahrstrassen(knoten, richtung)
            self.einzelfahrstrassen[key] = result
            return result

    # Gibt alle Einzelfahrstrassen zurueck, die an diesem Knoten in der angegebenen Richtung beginnen.
    # Pro Zielsignal wird nur eine Einzelfahrstrasse behalten, auch wenn alternative Fahrwege existieren.
    def _suche_einzelfahrstrassen(self, knoten, richtung):
        # Zielsignal-Refpunkt -> [EinzelFahrstrasse]
        einzelfahrstrassen_by_zielsignal = OrderedDict()  # Reihenfolge, in der die Zielsignale gefunden wurden, ist wichtig fuer Nummerierung
        for kante in knoten.get_nachfolger_kanten(richtung):
            if kante.ziel is not None:
                f = EinzelFahrstrasse()
                f.erweitere(kante)
                self._suche_einzelfahrstrassen_rek(f, einzelfahrstrassen_by_zielsignal)

        result = []
        for ziel_refpunkt, einzelfahrstrassen in einzelfahrstrassen_by_zielsignal.items():
            einzelfahrstr_name = ("Aufgleispunkt" if not ist_hsig_fuer_fahrstr_typ(knoten.signal(richtung), self.fahrstr_typ) else knoten.signal(richtung).signalbeschreibung()) + \
                    " -> " + ziel_refpunkt.signal().signalbeschreibung()

            if einzelfahrstr_name in self.bedingungen:
                logging.debug("Filtere nach Bedingung '{}'".format(einzelfahrstr_name))
                einzelfahrstrassen_gefiltert = einzelfahrstrassen

                for bed in self.bedingungen[einzelfahrstr_name]:
                    if bed.tag == "FahrstrWeiche":
                        einzelfahrstrassen_gefiltert = [f for f in einzelfahrstrassen_gefiltert if any(
                            w.refpunkt.refnr == int(bed.get("Ref", 0)) and
                            w.refpunkt.element_richtung.element.modul.relpath.upper() == bed.find("Datei").get("Dateiname", "").upper() and
                            w.weichenlage == int(bed.get("FahrstrWeichenlage"))
                            for kante in f.kantenliste() for w in kante.weichen
                        )]
                    else:
                        logging.warn("Unbekannter Bedingungstyp: {}".format(bed.tag))

                if len(einzelfahrstrassen_gefiltert) == 0:
                    logging.warn("Fuer Bedingung '{}' wurden keine Fahrstrassen gefunden, die sie erfuellen".format(einzelfahrstr_name))
                else:
                    einzelfahrstrassen = einzelfahrstrassen_gefiltert

            if len(einzelfahrstrassen) > 1:
                logging.debug("{} Einzelfahrstrassen zu {} gefunden: {}".format(
                    len(einzelfahrstrassen), ziel_refpunkt.signal(),
                    " / ".join("{} km/h, {:.2f} m".format(str_geschw(einzelfahrstrasse.signalgeschwindigkeit), einzelfahrstrasse.laenge) for einzelfahrstrasse in einzelfahrstrassen)))
            # result.append(sorted(einzelfahrstrassen, key = lambda fstr: float_geschw(fstr.signalgeschwindigkeit), reverse = True)[0])  # anders als min wird bei sorted Stabilitaet garantiert
            result.append(einzelfahrstrassen[0])

        return result

    # Erweitert die angegebene Einzelfahrstrasse rekursiv ueber Kanten, bis ein Hauptsignal erreicht wird,
    # und fuegt die resultierenden Einzelfahrstrassen in das Ergebnis-Dict ein.
    def _suche_einzelfahrstrassen_rek(self, fahrstrasse, ergebnis_dict):
        # Sind wir am Hauptsignal?
        signal = fahrstrasse.ziel.signal()
        if ist_hsig_fuer_fahrstr_typ(signal, self.fahrstr_typ):
            logging.debug("Zielsignal gefunden: {}".format(signal))
            try:
                ergebnis_dict[fahrstrasse.ziel.refpunkt(REFTYP_SIGNAL)].append(fahrstrasse)
            except KeyError:
                ergebnis_dict[fahrstrasse.ziel.refpunkt(REFTYP_SIGNAL)] = [fahrstrasse]
            return

        folgekanten = fahrstrasse.ziel.knoten.get_nachfolger_kanten(fahrstrasse.ziel.richtung)
        for idx, kante in enumerate(folgekanten):
            if kante.ziel is None:
                continue

            if idx == len(folgekanten) - 1:
                fahrstrasse.erweitere(kante)
                self._suche_einzelfahrstrassen_rek(fahrstrasse, ergebnis_dict)
            else:
                self._suche_einzelfahrstrassen_rek(fahrstrasse.erweiterte_kopie(kante), ergebnis_dict)

    def _get_fahrstrassen_rek(self, einzelfahrstr_liste, ziel_liste):
        letzte_fahrstrasse = einzelfahrstr_liste[-1]
        zielknoten = letzte_fahrstrasse.kanten.eintrag.ziel.knoten
        zielrichtung = letzte_fahrstrasse.kanten.eintrag.ziel.richtung
        zielsignal = zielknoten.signal(zielrichtung)

        fahrstr_abschliessen = True
        fahrstr_weiterfuehren = False

        if zielsignal.sigflags & SIGFLAG_KENNLICHT_VORGAENGERSIGNAL != 0:
            # Fahrstrasse nur abschliessen, wenn schon ein Signal mit "Kennlichtschaltung Nachfolgersignal" aufgenommen wurde.
            # Ansonsten Fahrstrasse weiterfuehren.

            # Wenn mehr als eine Einzelfahrstrasse vorhanden ist, dann ist auf jeden Fall ein Kennlichtsignal beteiligt.
            if len(einzelfahrstr_liste) == 1:
                # TODO: Laut Zusi-Dokumentation muesste man jetzt pruefen, ob das Startsignal "Kennlichtschaltung mit Nachfolgesignal" hat.
                # Zusi verhaelt sich hier aber anders als seine Dokumentation und ueberspringt diesen Check ganz.
                #startsignal = einzelfahrstr_liste[0].start.signal()
                #if startsignal is not None and startsignal.sigflags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL == 0:
                    fahrstr_abschliessen = False
                    fahrstr_weiterfuehren = True

        if zielsignal.sigflags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL != 0:
            fahrstr_weiterfuehren = True

        logging.debug("Fahrstrassensuche: an {}, Kennlicht Vorgaenger={}, Kennlicht Nachfolger={}, abschl={}, weiter={}".format(
            zielsignal,
            zielsignal.sigflags & SIGFLAG_KENNLICHT_VORGAENGERSIGNAL != 0, zielsignal.sigflags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL != 0,
            fahrstr_abschliessen, fahrstr_weiterfuehren))

        if fahrstr_abschliessen:
            ziel_liste.append(self._neue_fahrstrasse(einzelfahrstr_liste))
        if fahrstr_weiterfuehren:
            for einzelfahrstrasse in self._get_einzelfahrstrassen(zielknoten, zielrichtung):
                self._get_fahrstrassen_rek(einzelfahrstr_liste + [einzelfahrstrasse], ziel_liste)

    # Baut eine neue Fahrstrasse aus den angegebenen Einzelfahrstrassen zusammen.
    def _neue_fahrstrasse(self, einzelfahrstrassen):
        result = Fahrstrasse(self.fahrstr_typ)

        # Setze Start und Ziel
        result.start = einzelfahrstrassen[0].start.refpunkt(REFTYP_SIGNAL)
        if result.start is None or not ist_hsig_fuer_fahrstr_typ(result.start.signal(), self.fahrstr_typ):
            result.start = einzelfahrstrassen[0].start.refpunkt(REFTYP_AUFGLEISPUNKT)

        result.ziel = einzelfahrstrassen[-1].ziel.refpunkt(REFTYP_SIGNAL)
        result.zufallswert = float(result.ziel.signal().xml_knoten.get("ZufallsWert", 0))

        result.name = "LZB: " if self.fahrstr_typ == FAHRSTR_TYP_LZB else ""

        if result.start.reftyp == REFTYP_AUFGLEISPUNKT:
            result.name += "Aufgleispunkt"
        else:
            result.name += result.start.signal().signalbeschreibung()

        # Setze Name, Laenge, Regelgleis/Gegengleis/Streckenname/Richtungsanzeiger
        result.rgl_ggl = GLEIS_BAHNHOF
        result.streckenname = ""
        result.richtungsanzeiger = ""
        for einzelfahrstrasse in einzelfahrstrassen:
            result.laenge += einzelfahrstrasse.laenge

            zielkante = einzelfahrstrasse.kanten.eintrag
            result.name += " -> {}".format(zielkante.ziel.signal().signalbeschreibung())

            for kante in einzelfahrstrasse.kantenliste():
                if kante.rgl_ggl != GLEIS_BAHNHOF:
                    result.rgl_ggl = kante.rgl_ggl
                    result.streckenname = kante.streckenname
                if kante.richtungsanzeiger != "":
                    result.richtungsanzeiger = kante.richtungsanzeiger

        # Ereignis "Signalgeschwindigkeit" im Zielsignal setzt Geschwindigkeit fuer die gesamte Fahrstrasse
        if result.ziel.signal().signalgeschwindigkeit is not None:
            result.signalgeschwindigkeit = result.ziel.signal().signalgeschwindigkeit
        else:
            for einzelfahrstrasse in einzelfahrstrassen:
                result.signalgeschwindigkeit = geschw_min(result.signalgeschwindigkeit, einzelfahrstrasse.signalgeschwindigkeit)

        logging.debug("{}: Signalgeschwindigkeit {}, Richtungsanzeiger \"{}\"".format(result.name, str_geschw(result.signalgeschwindigkeit), result.richtungsanzeiger))

        flankenschutz_stellungen = []  # [FahrstrWeichenstellung]

        for idx, einzelfahrstrasse in enumerate(einzelfahrstrassen):
            if idx == 0:
                # Startsignal ansteuern
                if ist_hsig_fuer_fahrstr_typ(result.start.signal(), self.fahrstr_typ):
                    zeile_ersatzsignal = result.start.signal().get_hsig_ersatzsignal_zeile(result.rgl_ggl)
                    zeile_regulaer = result.start.signal().get_hsig_zeile(self.fahrstr_typ, result.signalgeschwindigkeit)
                    nutze_ersatzsignal = result.ziel.signal().ist_hilfshauptsignal

                    if nutze_ersatzsignal and zeile_ersatzsignal is None:
                        logging.warn("{}: Startsignal hat keine Ersatzsignal-Zeile fuer RglGgl-Angabe {}. Zwecks Kompatibilitaet mit dem Zusi-3D-Editor wird die regulaere Matrix angesteuert.".format(result.name, result.rgl_ggl))
                        nutze_ersatzsignal = False
                    elif not nutze_ersatzsignal and zeile_regulaer is None:
                        logging.warn("{}: Startsignal hat keine Zeile fuer Geschwindigkeit {}. Zwecks Kompatibilitaet mit dem Zusi-3D-Editor wird die Ersatzsignal-Matrix angesteuert.".format(result.name, str_geschw(result.signalgeschwindigkeit)))
                        nutze_ersatzsignal = True

                    if nutze_ersatzsignal:
                        if zeile_ersatzsignal is None:
                            logging.warn("{}: Startsignal hat keine Ersatzsignal-Zeile fuer RglGgl-Angabe {}. Die Signalverknuepfung wird nicht eingerichtet.".format(result.name, result.rgl_ggl))
                        else:
                            result.signale.append(FahrstrHauptsignal(result.start, zeile_ersatzsignal, True))
                    else:
                        if zeile_regulaer is None:
                            logging.warn("{}: Startsignal hat keine Zeile fuer Geschwindigkeit {}. Die Signalverknuepfung wird nicht eingerichtet.".format(result.name, str_geschw(result.signalgeschwindigkeit)))
                        else:
                            zeile_regulaer = result.start.signal().get_richtungsanzeiger_zeile(zeile_regulaer, result.rgl_ggl, result.richtungsanzeiger)
                            result.signale.append(FahrstrHauptsignal(result.start, zeile_regulaer, False))
            else:
                # Kennlichtsignal ansteuern
                gefunden = False
                for idx, zeile in enumerate(einzelfahrstrasse.start.signal().zeilen):
                    if zeile.hsig_geschw == -2.0:
                        refpunkt = einzelfahrstrasse.start.refpunkt(REFTYP_SIGNAL)
                        if refpunkt is None:
                            logging.warn("Element {} enthaelt ein Signal, aber es existiert kein passender Referenzpunkt. Die Signalverknuepfung wird nicht eingerichtet.".format(einzelfahrstrasse.start))
                        else:
                            kennlichtsignal_zeile = einzelfahrstrasse.start.signal().get_richtungsanzeiger_zeile(idx, result.rgl_ggl, result.richtungsanzeiger)
                            if idx != kennlichtsignal_zeile:
                                logging.info("{}: Kennlichtsignal {} an Element {} (Ref. {}) wird in Zusi nicht mit Richtungs-/Gegengleisanzeiger angesteuert.".format(result.name, refpunkt.signal(), refpunkt.element_richtung, refpunkt.refnr))
                            result.signale.append(FahrstrHauptsignal(refpunkt, kennlichtsignal_zeile, False))
                        gefunden = True
                        break

                if not gefunden:
                    logging.warn("{}: An Signal {} wurde keine Kennlichtzeile (Geschwindigkeit -2) gefunden".format(result.name, einzelfahrstrasse.start.signal()))

            # Zielsignal ansteuern mit Geschwindigkeit -999, falls vorhanden
            if idx == len(einzelfahrstrassen) - 1:
                for idx, zeile in enumerate(result.ziel.signal().zeilen):
                    if zeile.hsig_geschw == -999.0:
                        result.signale.append(FahrstrHauptsignal(result.ziel, idx, False))
                        if result.ziel.element_richtung.element.modul != modulverwaltung.dieses_modul:
                            logging.info("{}: Signal {} an Element {} (Ref. {}) wuerde vom Zusi-3D-Editor momentan nicht als Zielsignal angesteuert, da es in einem anderen Modul liegt".format(result.name, result.ziel.signal(), result.ziel.element_richtung, result.ziel.refnr))
                        break

            for kante in einzelfahrstrasse.kantenliste():
                result.register.extend(kante.register)
                result.weichen.extend(kante.weichen)
                for refpunkt in kante.aufloesepunkte:
                    if refpunkt.reftyp == REFTYP_AUFLOESEPUNKT:
                        # Aufloesepunkte im Zielelement zaehlen als Aufloesung der gesamten Fahrstrasse, nicht als Teilaufloesung.
                        if refpunkt.element_richtung == result.ziel.element_richtung:
                            result.aufloesepunkte.append(refpunkt)
                        else:
                            result.teilaufloesepunkte.append(refpunkt)
                result.signalhaltfallpunkte.extend([refpunkt for refpunkt in kante.aufloesepunkte if refpunkt.reftyp == REFTYP_SIGNALHALTFALL])
                for signal_verkn in kante.signale:
                    if signal_verkn.zeile != -1:
                        result.signale.append(signal_verkn)
                    else:
                        zeile = signal_verkn.refpunkt.signal().get_hsig_zeile(self.fahrstr_typ, result.signalgeschwindigkeit)
                        if zeile is None:
                            logging.warn("{}: Signal {} ({}) hat keine Zeile fuer Geschwindigkeit {}".format(result.name, signal_verkn.refpunkt.signal(), signal_verkn.refpunkt, str_geschw(result.signalgeschwindigkeit)))
                        else:
                            zeile = signal_verkn.refpunkt.signal().get_richtungsanzeiger_zeile(zeile, result.rgl_ggl, result.richtungsanzeiger)
                            result.signale.append(FahrstrHauptsignal(signal_verkn.refpunkt, zeile, False))
                result.vorsignale.extend(kante.vorsignale)

                # Flankenschutz
                if self.flankenschutz_graph is not None:
                    for knoten, richtung, nachfolger_idx in [
                            (self.flankenschutz_graph.get_knoten(kante.start.knoten.element), kante.start.richtung, kante.start_nachfolger_idx),
                            (self.flankenschutz_graph.get_knoten(kante.ziel.knoten.element), gegenrichtung(kante.ziel.richtung), kante.ziel_vorgaenger_idx)]:
                        if knoten is not None and nachfolger_idx is not None:
                            # Flankenschutz-Stellungen mit geringerem Abstand ueberschreiben andere.
                            flankenschutz_neu = knoten.get_flankenschutz_stellungen(richtung, nachfolger_idx)
                            flankenschutz_stellungen = [w for w in flankenschutz_stellungen if not any(w.refpunkt == w2.refpunkt and w.abstand > w2.abstand for w2 in flankenschutz_neu)]
                            flankenschutz_stellungen.extend([w for w in flankenschutz_neu if not any(w.refpunkt == w2.refpunkt and w.abstand > w2.abstand for w2 in flankenschutz_stellungen)])

        for weichenstellung in flankenschutz_stellungen:
            if weichenstellung.weichenlage != 1 and weichenstellung not in result.weichen:
                result.weichen.append(FahrstrWeichenstellung(weichenstellung.refpunkt, weichenstellung.weichenlage))

        # Aufloesepunkte suchen. Wenn wir vorher schon einen Aufloesepunkt gefunden haben, lag er im Zielelement der Fahrstrasse,
        # und es muss nicht weiter gesucht werden.
        if len(result.aufloesepunkte) == 0:
            for aufl in einzelfahrstrassen[-1].ziel.knoten.get_aufloesepunkte(einzelfahrstrassen[-1].ziel.richtung):
                if aufl.reftyp == REFTYP_SIGNALHALTFALL:
                    result.signalhaltfallpunkte.append(aufl)
                else:
                    result.aufloesepunkte.append(aufl)

        # Vorsignale ansteuern. Erst *nach* Abarbeiten aller Einzelfahrstrassen, da deren Ereignisse "Vorsignal in Fahrstrasse verknuepfen" Prioritaet haben!
        if self.vorsignal_graph is not None and result.start.reftyp == REFTYP_SIGNAL and len(result.signale) > 0 and not result.signale[0].ist_ersatzsignal:
            vorsignal_knoten = self.vorsignal_graph.get_knoten(einzelfahrstrassen[0].start.knoten.element)
            if vorsignal_knoten is not None:
                for vsig in vorsignal_knoten.get_vorsignale(einzelfahrstrassen[0].start.richtung):
                    if not any(vsig == vsig_existiert.refpunkt for vsig_existiert in result.vorsignale):
                        spalte = None
                        if self.fahrstr_typ == FAHRSTR_TYP_LZB:
                            for idx, spalten_geschw in enumerate(vsig.signal().spalten):
                                if spalten_geschw == -2.0:
                                    spalte = idx
                                    break
                            if spalte is None:
                                logging.debug("{}: An Signal {} ({}) wurde keine Vorsignalspalte fuer Geschwindigkeit -2 (Dunkelschaltung) gefunden. Suche Vorsignalspalte gemaess Signalgeschwindigkeit {}".format(result.name, vsig.signal(), vsig.element_richtung, result.signalgeschwindigkeit))
                        if spalte is None:
                            spalte = vsig.signal().get_vsig_spalte(result.signalgeschwindigkeit)

                        if len(vsig.signal().richtungsvoranzeiger) > 0:
                            spalte = vsig.signal().get_richtungsvoranzeiger_spalte(0 if spalte is None else spalte, result.rgl_ggl, result.richtungsanzeiger)
                        if spalte is None:
                            logging.warn("{}: An Signal {} ({}) wurde keine Vorsignalspalte fuer Geschwindigkeit {} gefunden".format(result.name, vsig.signal(), vsig.element_richtung, str_geschw(result.signalgeschwindigkeit)))
                        else:
                            result.vorsignale.append(FahrstrVorsignal(vsig, spalte))

        return result
