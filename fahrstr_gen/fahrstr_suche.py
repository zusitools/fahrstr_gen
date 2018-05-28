#!/usr/bin/env python3

import xml.etree.ElementTree as ET
from collections import OrderedDict
import itertools

from .konstanten import *
from .fahrstrasse import EinzelFahrstrasse, Fahrstrasse, FahrstrHauptsignal, FahrstrVorsignal, FahrstrWeichenstellung
from .strecke import ist_hsig_fuer_fahrstr_typ, geschw_kleiner, geschw_min, str_geschw, gegenrichtung, str_rgl_ggl
from . import modulverwaltung

import logging

def get_alle_bedingten_register(einzelfahrstr):
    result = []
    for kante in einzelfahrstr.kantenliste():
        result.extend(kante.bedingte_register)
    return result

def get_bedingte_register_kombinationen(einzelfahrstr_liste):
    """
    Liefert eine Liste mit gleicher Laenge wie `einzelfahrstr_liste`,
    in der fuer jede Einzelfahrstrasse eine Liste mit allen moeglichen
    Kombinationen bedingter Register (derzeit nur: leere Liste und
    Liste aller bedingten Register) enthalten sind.
    """
    result = []
    for einzelfahrstr in einzelfahrstr_liste:
        alle_bedingten_register = get_alle_bedingten_register(einzelfahrstr)
        if len(alle_bedingten_register):
            result.append([[], alle_bedingten_register])
        else:
            result.append([[]])
    return result

class FahrstrassenSuche:
    def __init__(self, fahrstr_typ, bedingungen, vorsignal_graph, flankenschutz_graph, loeschfahrstr_namen):
        self.einzelfahrstrassen = dict()  # KnotenUndRichtung -> [EinzelFahrstrasse]
        self.fahrstr_typ = fahrstr_typ
        self.bedingungen = bedingungen
        self.vorsignal_graph = vorsignal_graph
        self.flankenschutz_graph = flankenschutz_graph
        self.loeschfahrstr_namen = loeschfahrstr_namen

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
            # Das ist genau dann der Fall, wenn wir mehr als eine Einzelfahrstrasse haben.
            # Ansonsten Fahrstrasse weiterfuehren.
            if len(einzelfahrstr_liste) == 1:
                fahrstr_abschliessen = False
                fahrstr_weiterfuehren = True

        if zielsignal.sigflags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL != 0:
            fahrstr_weiterfuehren = True

        logging.debug("Fahrstrassensuche: an {} (Kennlicht Vorgaenger={}, Kennlicht Nachfolger={}). Fahrstrasse abschliessen={}, Fahrstrasse weiterfuehren={}".format(
            zielsignal,
            zielsignal.sigflags & SIGFLAG_KENNLICHT_VORGAENGERSIGNAL != 0, zielsignal.sigflags & SIGFLAG_KENNLICHT_NACHFOLGESIGNAL != 0,
            fahrstr_abschliessen, fahrstr_weiterfuehren))

        if fahrstr_abschliessen:
            for bedingte_register in itertools.product(*get_bedingte_register_kombinationen(einzelfahrstr_liste)):
                fstr = self._neue_fahrstrasse(einzelfahrstr_liste, bedingte_register)
                if fstr is not None:
                    ziel_liste.append(fstr)
        if fahrstr_weiterfuehren:
            for einzelfahrstrasse in self._get_einzelfahrstrassen(zielknoten, zielrichtung):
                self._get_fahrstrassen_rek(einzelfahrstr_liste + [einzelfahrstrasse], ziel_liste)

    # Gibt zurueck, ob fuer das angegebene Signal die Warnung ausgegeben werden soll,
    # dass es vom Zusi-3D-Editor auf einen Rangier-Fahrtbegriff gestellt werden wuerde.
    def _rangiersignal_in_zugfahrstr_warnung(self, signal):
        return self.fahrstr_typ in [FAHRSTR_TYP_ZUG, FAHRSTR_TYP_LZB] and signal.sigflags & SIGFLAG_RANGIERSIGNAL_BEI_ZUGFAHRSTR_UMSTELLEN != 0 and any(z.fahrstr_typ & FAHRSTR_TYP_RANGIER != 0 and z.hsig_geschw not in [0, -2, -999] for z in signal.zeilen)

    # Baut eine neue Fahrstrasse aus den angegebenen Einzelfahrstrassen zusammen,
    # `bedingte_register` hat die gleiche Laenge wie `einzelfahrstrassen`
    # und enthaelt fuer jede Einzelfahrstrasse die zu aktivierenden bedingten Register
    # (Paare aus Referenzpunkt und Beschreibung)
    def _neue_fahrstrasse(self, einzelfahrstrassen, bedingte_register):
        assert(len(einzelfahrstrassen) > 0)
        assert(len(bedingte_register) == len(einzelfahrstrassen))
        result = Fahrstrasse(self.fahrstr_typ)

        # Setze Start und Ziel
        result.start = einzelfahrstrassen[0].start.refpunkt(REFTYP_SIGNAL)
        if result.start is None or not ist_hsig_fuer_fahrstr_typ(result.start.signal(), self.fahrstr_typ):
            result.start = einzelfahrstrassen[0].start.refpunkt(REFTYP_AUFGLEISPUNKT)

        result.ziel = einzelfahrstrassen[-1].ziel.refpunkt(REFTYP_SIGNAL)
        if any(len(_) for _ in bedingte_register):
            result.zufallswert = 1  # Nicht als Ziel: 100%
        else:
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
        for idx, einzelfahrstrasse in enumerate(einzelfahrstrassen):
            result.laenge += einzelfahrstrasse.laenge

            zielkante = einzelfahrstrasse.kanten.eintrag
            result.name += " -> {}".format(zielkante.ziel.signal().signalbeschreibung())

            if len(bedingte_register[idx]):
                result.name += " (" + ", ".join(list(OrderedDict.fromkeys(reg[1] for reg in bedingte_register[idx]))) + ")"

            for kante in einzelfahrstrasse.kantenliste():
                if kante.rgl_ggl != GLEIS_BAHNHOF:
                    result.rgl_ggl = kante.rgl_ggl
                    result.streckenname = kante.streckenname
                if kante.richtungsanzeiger != "":
                    result.richtungsanzeiger = kante.richtungsanzeiger

        if result.name in self.loeschfahrstr_namen:
            logging.info("Loesche Fahrstrasse {}".format(result.name))
            return None

        if result.start is None:
            logging.error("{}: Startelement {} hat keinen Referenzpunkt mit Typ Signal. Die Fahrstrasse wird nicht eingerichtet.".format(result.name, einzelfahrstrassen[0].start))
            return None
        if result.ziel is None:
            logging.error("{}: Zielelement {} hat keinen Referenzpunkt mit Typ Signal. Die Fahrstrasse wird nicht eingerichtet.".format(result.name, einzelfahrstrassen[-1].ziel))
            return None

        # Ereignis "Signalgeschwindigkeit" im Zielsignal setzt Geschwindigkeit fuer die gesamte Fahrstrasse
        if result.ziel.signal().signalgeschwindigkeit is not None:
            result.signalgeschwindigkeit = result.ziel.signal().signalgeschwindigkeit
            logging.debug("{}: Ereignis \"Signalgeschwindigkeit\" in der Signalmatrix des Zielsignals bestimmt die Signalgeschwindigkeit in der Fahrstrasse".format(result.name))
        else:
            for einzelfahrstrasse in einzelfahrstrassen:
                result.signalgeschwindigkeit = geschw_min(result.signalgeschwindigkeit, einzelfahrstrasse.signalgeschwindigkeit)

        logging.debug("{}: Steuere Hauptsignale an mit Signalgeschwindigkeit {}, Richtungsanzeiger \"{}\", Gleistyp {} ({})".format(result.name, str_geschw(result.signalgeschwindigkeit), result.richtungsanzeiger, result.rgl_ggl, str_rgl_ggl(result.rgl_ggl)))

        flankenschutz_stellungen = []  # [FahrstrWeichenstellung]

        # Workaround fuer Bug/undokumentierte Beschraenkung in Zusi: Das Startsignal muss immer das letzte Signal in der Fahrstrasse sein.
        # Ansonsten werden Ersatzsignale nicht korrekt angesteuert.
        # Speichere es hier zwischen und fuege es am Ende hinzu.
        startsignal_verkn = None

        for idx, einzelfahrstrasse in enumerate(einzelfahrstrassen):
            if idx == 0:
                # Startsignal ansteuern
                if ist_hsig_fuer_fahrstr_typ(result.start.signal(), self.fahrstr_typ):
                    zeile_ersatzsignal = result.start.signal().get_hsig_ersatzsignal_zeile(result.rgl_ggl)
                    zeile_regulaer = result.start.signal().get_hsig_zeile(self.fahrstr_typ, result.signalgeschwindigkeit)
                    nutze_ersatzsignal = any(einzelfahrstrasse.ziel.signal().ist_hilfshauptsignal for einzelfahrstrasse in einzelfahrstrassen)

                    if nutze_ersatzsignal and zeile_ersatzsignal is None:
                        logging.warn("{}: Startsignal (Element {}) hat keine Ersatzsignal-Zeile {} Ereignis \"Gegengleis kennzeichnen\" (fuer Gleistyp \"{}\"). Zwecks Kompatibilitaet mit dem Zusi-3D-Editor wird die regulaere Matrix angesteuert.".format(result.name, result.start, "mit" if result.rgl_ggl == GLEIS_GEGENGLEIS else "ohne", str_rgl_ggl(result.rgl_ggl)))
                        nutze_ersatzsignal = False
                    elif not nutze_ersatzsignal and zeile_regulaer is None:
                        logging.warn("{}: Startsignal hat keine Zeile fuer Typ {}, Geschwindigkeit {}. Zwecks Kompatibilitaet mit dem Zusi-3D-Editor wird die Ersatzsignal-Matrix angesteuert.".format(result.name, str_fahrstr_typ(self.fahrstr_typ), str_geschw(result.signalgeschwindigkeit)))
                        nutze_ersatzsignal = True

                    if nutze_ersatzsignal:
                        if zeile_ersatzsignal is None:
                            logging.error("{}: Startsignal (Element {}) hat keine Ersatzsignal-Zeile {} Ereignis \"Gegengleis kennzeichnen\" (fuer Gleistyp \"{}\"). Die Fahrstrasse wird nicht eingerichtet.".format(result.name, result.start, "mit" if result.rgl_ggl == GLEIS_GEGENGLEIS else "ohne", str_rgl_ggl(result.rgl_ggl)))
                            return None
                        else:
                            startsignal_verkn = FahrstrHauptsignal(result.start, zeile_ersatzsignal, True)
                    else:
                        if zeile_regulaer is None:
                            logging.error("{}: Startsignal (Element {}) hat keine Zeile fuer Typ {}, Geschwindigkeit {}. Die Fahrstrasse wird nicht eingerichtet.".format(result.name, result.start, str_fahrstr_typ(self.fahrstr_typ), str_geschw(result.signalgeschwindigkeit)))
                            return None
                        else:
                            zeile_regulaer = result.start.signal().get_richtungsanzeiger_zeile(zeile_regulaer, result.rgl_ggl, result.richtungsanzeiger)
                            startsignal_verkn = FahrstrHauptsignal(result.start, zeile_regulaer, False)
            else:
                # Kennlichtsignal ansteuern
                gefunden = False
                for zeilenidx, zeile in enumerate(einzelfahrstrasse.start.signal().zeilen):
                    if zeile.hsig_geschw == -2.0:
                        refpunkt = einzelfahrstrasse.start.refpunkt(REFTYP_SIGNAL)
                        if refpunkt is None:
                            logging.error("{}: Element {} enthaelt ein Signal, aber es existiert kein passender Referenzpunkt. Die Fahrstrasse wird nicht eingerichtet.".format(result.name, einzelfahrstrasse.start))
                            return None
                        else:
                            kennlichtsignal_zeile = einzelfahrstrasse.start.signal().get_richtungsanzeiger_zeile(zeilenidx, result.rgl_ggl, result.richtungsanzeiger)
                            if zeilenidx != kennlichtsignal_zeile:
                                logging.info("{}: Kennlichtsignal ({}, Ref. {}) wuerde vom Zusi-3D-Editor nicht mit Richtungs-/Gegengleisanzeiger angesteuert.".format(result.name, refpunkt.signal(), refpunkt.refnr))
                            result.signale.append(FahrstrHauptsignal(refpunkt, kennlichtsignal_zeile, False))
                        gefunden = True
                        break

                if not gefunden:
                    logging.error("{}: Kennlichtsignal ({}) hat keine Zeile fuer Kennlicht (Typ {}, Geschwindigkeit -2). Die Fahrstrasse wird nicht eingerichtet.".format(result.name, einzelfahrstrasse.start.signal(), str_fahrstr_typ(self.fahrstr_typ)))
                    return None

                if self._rangiersignal_in_zugfahrstr_warnung(einzelfahrstrasse.start.signal()):
                    logging.warn("{}: Kennlichtsignal ({}, Ref. {}) wuerde vom Zusi-3D-Editor auf einen Rangierfahrt-Fahrtbegriff gestellt, da \"Rangiersignal in Zugfahrstrasse umstellen\" aktiviert ist.".format(result.name, result.ziel.signal(), result.ziel.refnr))

            # Zielsignal ansteuern mit Geschwindigkeit -999, falls vorhanden
            if idx == len(einzelfahrstrassen) - 1:
                for zeilenidx, zeile in enumerate(result.ziel.signal().zeilen):
                    if zeile.hsig_geschw == -999.0:
                        logging.debug("{}: Zielsignal {} wird in der Fahrstrasse verknuepft (Zeile fuer Geschwindigkeit -999)".format(result.name, result.ziel.signal()))
                        result.signale.append(FahrstrHauptsignal(result.ziel, zeilenidx, False))
                        if result.ziel.element_richtung.element.modul != modulverwaltung.dieses_modul:
                            logging.info("{}: {} (Ref. {}) wuerde vom Zusi-3D-Editor momentan nicht als Zielsignal angesteuert, da es in einem anderen Modul liegt".format(result.name, result.ziel.signal(), result.ziel.refnr))
                        break

            if self._rangiersignal_in_zugfahrstr_warnung(result.ziel.signal()):
                logging.warn("{}: Zielsignal ({}, Ref. {}) wuerde vom Zusi-3D-Editor auf einen Fahrtbegriff gestellt, da \"Rangiersignal in Zugfahrstrasse umstellen\" aktiviert ist.".format(result.name, result.ziel.signal(), result.ziel.refnr))

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
                            logging.warn("{}: {} hat keine Zeile fuer Typ {}, Geschwindigkeit {} und wird daher nicht in der Fahrstrasse verknuepft.".format(result.name, signal_verkn.refpunkt.signal(), str_fahrstr_typ(self.fahrstr_typ), str_geschw(result.signalgeschwindigkeit)))
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

            result.register.extend(reg[0] for reg in bedingte_register[idx])

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
        if startsignal_verkn is not None and not startsignal_verkn.ist_ersatzsignal and self.vorsignal_graph is not None:
            vorsignal_knoten = self.vorsignal_graph.get_knoten(einzelfahrstrassen[0].start.knoten.element)
            if vorsignal_knoten is not None:

                # hochsignalisierung: True, wenn die Suche ueber ein Hauptsignal mit Hochsignalisierungs-Flag hinaus fortgesetzt wurde.
                def finde_vsig_rek(vorsignal_knoten, richtung, signalgeschwindigkeit, geschw_naechstes_hsig, geschw_naechstes_hsig_startsignal_halt, hochsignalisierung):
                    for kante in vorsignal_knoten.get_vorsignal_kanten(richtung):
                        # TODO: Ziel ist hier, die Zeile zu bestimmen, auf der das vorherige Hauptsignal steht.
                        # Eigentlich muesste man Signalgeschwindigkeit-Ereignisse im Startsignal ebenfalls beruecksichtigen.
                        if kante.hat_ende_weichenbereich:
                            signalgeschwindigkeit = kante.signalgeschwindigkeit
                        else:
                            signalgeschwindigkeit = geschw_min(signalgeschwindigkeit, kante.signalgeschwindigkeit)

                        for vsig in kante.vorsignale:
                            if not any(vsig == vsig_existiert.refpunkt for vsig_existiert in result.vorsignale):
                                logging.debug("Vorsignal an {}".format(vsig))
                                spalte = None
                                spalte_startsignal_halt = None
                                if geschw_naechstes_hsig == -2.0:
                                    try:
                                        spalte = vsig.signal().spalten.index(-2.0)
                                    except ValueError:
                                        # Das ist ziemlich normal, etwa bei 500-Hz-Magneten.
                                        logging.debug("{}: An {} (Ref. {}) wurde keine Vorsignalspalte fuer Geschwindigkeit -2 (Dunkelschaltung) gefunden. Suche Vorsignalspalte gemaess Signalgeschwindigkeit {}".format(result.name, vsig.signal(), vsig.refnr, geschw_naechstes_hsig))
                                        if vsig.signal().get_vsig_spalte(geschw_naechstes_hsig) != vsig.signal().get_vsig_spalte(-1):
                                            logging.warn("{}: An {} (Ref. {}) wurde keine Vorsignalspalte fuer Geschwindigkeit -2 (Dunkelschaltung) gefunden. Im Zusi-3D-Editor wuerde die Spalte mit der hoechsten Signalgeschwindigkeit angesteuert.".format(result.name, vsig.signal(), vsig.refnr))

                                if spalte is None:
                                    spalte = vsig.signal().get_vsig_spalte(geschw_naechstes_hsig)
                                    if not hochsignalisierung:
                                        spalte_alt = vsig.signal().get_vsig_spalte(result.signalgeschwindigkeit) # mit dem alten Algorithmus
                                        if spalte != spalte_alt:
                                            logging.log(logging.COMPAT, "{}: Vorsignalsuche: {} wird mit dem neuen Algorithmus auf Spalte {} ({}) statt {} ({}) gestellt".format(result.name, vsig.signal(), spalte, str_geschw(geschw_naechstes_hsig), spalte_alt, str_geschw(result.signalgeschwindigkeit)))
                                    if len(vsig.signal().richtungsvoranzeiger) > 0:
                                        spalte = vsig.signal().get_richtungsvoranzeiger_spalte(0 if spalte is None else spalte, result.rgl_ggl, result.richtungsanzeiger)

                                    spalte_startsignal_halt = vsig.signal().get_vsig_spalte(geschw_naechstes_hsig_startsignal_halt)

                                # Erzeuge Vsig-Verknuepfung nur, wenn die Stellung des Fahrstrassen-Startsignals einen Einfluss auf die gewaehlte Vsig-Spalte hat.
                                if spalte != spalte_startsignal_halt:
                                    if spalte is None:
                                        logging.warn("{}: An {} ({}) wurde keine Vorsignalspalte fuer Geschwindigkeit {} gefunden".format(result.name, vsig.signal(), vsig.element_richtung, str_geschw(result.signalgeschwindigkeit)))
                                    else:
                                        result.vorsignale.append(FahrstrVorsignal(vsig, spalte))
                                else:
                                    logging.log(logging.COMPAT, "{}: Vorsignalsuche: {} wird vom Startsignal der Fahrstrasse nicht beeinflusst (gleiche Spalte {} fuer Geschwindigkeiten {} und {}) und daher nicht verknuepft".format(result.name, vsig.signal(), spalte, str_geschw(geschw_naechstes_hsig), str_geschw(geschw_naechstes_hsig_startsignal_halt)))

                        if not kante.vorher_keine_vsig_verknuepfung and kante.ziel is not None and not kante.ziel.knoten.ist_besucht():
                            kante.ziel.knoten.markiere_besucht()

                            if ist_hsig_fuer_fahrstr_typ(kante.ziel.signal(), FAHRSTR_TYP_ZUG) and \
                                    kante.ziel.signal().sigflags & SIGFLAG_HOCHSIGNALISIERUNG != 0:
                                zeile = kante.ziel.signal().get_hsig_zeile(self.fahrstr_typ, signalgeschwindigkeit) # TODO: Richtungsanzeiger beachten?
                                if spalte is None:
                                    logging.warn("{}: {} hat Hochsignalisierung aktiviert, aber keine Zeile fuer Typ {}, Geschwindigkeit {}. Es werden keine weiteren Vorsignale gesucht.".format(result.name, kante.ziel.signal(), str_fahrstr_typ(self.fahrstr_typ), str_geschw(signalgeschwindigkeit)))
                                    return

                                spalte = kante.ziel.signal().get_vsig_spalte(geschw_naechstes_hsig)
                                if spalte is None:
                                    spalte = 0
                                if spalte >= len(kante.ziel.signal().spalten):
                                    return

                                spalte_startsignal_halt = kante.ziel.signal().get_vsig_spalte(geschw_naechstes_hsig_startsignal_halt)
                                if spalte_startsignal_halt is None:
                                    spalte_startsignal_halt = 0
                                if spalte_startsignal_halt >= len(kante.ziel.signal().spalten):
                                    return

                                geschw_naechstes_hsig = kante.ziel.signal().matrix_geschw(zeile, spalte)
                                geschw_naechstes_hsig_startsignal_halt = kante.ziel.signal().matrix_geschw(zeile, spalte_startsignal_halt)
                                if geschw_naechstes_hsig != geschw_naechstes_hsig_startsignal_halt:
                                    if geschw_kleiner(geschw_naechstes_hsig, geschw_naechstes_hsig_startsignal_halt):
                                        logging.warn("{}: {} hat Hochsignalisierung aktiviert und wechselt beim Stellen der Fahrstrasse auf eine niedrigere Geschwindigkeit (von {} auf {})".format(result.name, kante.ziel.signal(), str_geschw(geschw_naechstes_hsig_startsignal_halt), str_geschw(geschw_naechstes_hsig)))
                                    logging.debug("{}: Hochsignalisierung an {} aktiviert (aktive Zeile: Zeile {} fuer Geschwindigkeit {}), suche weitere Vorsignale mit Vsig-Geschwindigkeit {}/{}".format(result.name, kante.ziel.signal(), zeile, str_geschw(signalgeschwindigkeit), str_geschw(geschw_naechstes_hsig), str_geschw(geschw_naechstes_hsig_startsignal_halt)))
                                    finde_vsig_rek(kante.ziel.knoten, kante.ziel.richtung, -1, geschw_naechstes_hsig, geschw_naechstes_hsig_startsignal_halt, True)
                                else:
                                    logging.debug("{}: Hochsignalisierung an {} aktiviert (aktive Zeile: Zeile {} fuer Geschwindigkeit {}), aber Startsignal beeinflusst die Vorsignalstellung nicht. Suche keine weiteren Vorsignale.".format(result.name, kante.ziel.signal(), zeile, str_geschw(signalgeschwindigkeit)))
                            else:
                                finde_vsig_rek(kante.ziel.knoten, kante.ziel.richtung, signalgeschwindigkeit, geschw_naechstes_hsig, geschw_naechstes_hsig_startsignal_halt, hochsignalisierung)

                spalte = result.start.signal().get_vsig_spalte(0)
                if spalte is None:
                    spalte = 0

                self.vorsignal_graph.markiere_unbesucht()
                geschw_naechstes_hsig = result.start.signal().matrix_geschw(startsignal_verkn.zeile, spalte)
                geschw_naechstes_hsig_startsignal_halt = 0
                logging.debug("{}: Suche Vorsignale ab {}, Vsig-Geschwindigkeit {}/{}".format(result.name, vorsignal_knoten.signal(result.start.element_richtung.richtung), str_geschw(geschw_naechstes_hsig), str_geschw(geschw_naechstes_hsig_startsignal_halt)))
                finde_vsig_rek(vorsignal_knoten, result.start.element_richtung.richtung, -1.0, -2.0 if self.fahrstr_typ == FAHRSTR_TYP_LZB else geschw_naechstes_hsig, geschw_naechstes_hsig_startsignal_halt, False)

        if startsignal_verkn is not None:
            result.signale.append(startsignal_verkn)

        return result
