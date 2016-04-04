# Fahrstrassengenerierung fuer Zusi-3-Strecken

Eine alternative Implementierung der Fahrstraßengenerierung des Zusi-3D-Editors, die versucht, so weit wie möglich und sinnvoll mit dem Vorbild kompatibel zu sein.

## Vorgehensweise

Die Generierung der Fahrstraßen geschieht durch schrittweise Vergröberung des Streckennetzes. Die Ebenen sind:
* **Streckenelemente**: Die Eingabe ist die ST3-Datei mit den einzelnen Streckenelementen. Zwecks besserem Caching werden ein paar leichtgewichtige Wrapperklassen um die wichtigsten XML-Knoten (\<StrElement>, \<Signal>, \<RefPunkt>) genutzt. Ziel ist es, jedes Streckenelement nur konstant oft anzufassen, egal, wie viele Fahrstraßen darüber verlaufen.
* **Streckengraph**: Die erste Abstraktionsebene ist ein gerichteter Graph, dessen Knoten die fahrstraßenrelevanten Streckenelemente sind, also solche mit einer Weiche (>1 Nachfolger) oder einem Hauptsignal für den gewählten Fahrstraßentyp. Die Kanten zwischen diesen Knoten enthalten alle fahrstraßenrelevanten Daten (Signale, Weichenstellungen, Auflösepunkte, ...).
* **Einzelfahrstraßen**: Eine Einzelfahrstraße ist eine Liste von Kanten, die von einem Hauptsignal oder Aufgleispunkt zum nächsten Hauptsignal führen. Wenn es mehrere Einzelfahrstraßen zwischen zwei Knoten gibt, wird auf dieser Ebene die Entscheidung getroffen, welche davon behalten und welche gelöscht werden.
* **Fahrstraßen**: Eine oder mehrere Einzelfahrstraßen werden zu einer (simulatortauglichen) Fahrstraße zusammengesetzt. Normalerweise besteht eine Fahrstraße aus einer einzigen Einzelfahrstraße, nur im Fall von Kennlichtschaltungen werden mehrere Einzelfahrstraßen zusammengesetzt. Auf dieser Ebene werden auch Start- und Zielsignal angesteuert und es wird der Vor- und Nachlauf (Vorsignale und Auflösepunkte) generiert.
