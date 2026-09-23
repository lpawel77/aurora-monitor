import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import matplotlib.dates as mdates
import numpy as np
import requests
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.figure import Figure

import aurora

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

KOLOR_SLUPKA = "#2a78d6"
KOLOR_TOR = "#e1e0d9"
KOLOR_SIATKI = "#e1e0d9"
KOLOR_OSI = "#c3c2b7"
KOLOR_OPISOW = "#898781"
KOLOR_TEKSTU = "#0b0b0b"
KOLOR_TLA_WYKRESU = "#fcfcfb"

# klasyczna skala kolorów indeksu Kp (konwencja NOAA: spokojnie -> burza)
KOLOR_KP_SPOKOJNIE = "#008300"
KOLOR_KP_AKTYWNIE = "#eda100"
KOLOR_KP_BURZA = "#eb6834"
KOLOR_KP_SILNA_BURZA = "#e34948"

# rozbiezna (diverging) skala dla Bz: poludnie (ujemny, sprzyja zorzy) -> szary (blisko zera) -> polnoc
KOLOR_BZ_POLUDNIE = "#e34948"
KOLOR_BZ_NEUTRALNY = "#e1e0d9"
KOLOR_BZ_POLNOC = "#2a78d6"
MAPA_KOLOROW_BZ = LinearSegmentedColormap.from_list(
    "bz_rozbiezny", [KOLOR_BZ_POLUDNIE, KOLOR_BZ_NEUTRALNY, KOLOR_BZ_POLNOC]
)


def kolor_kp(kp: float) -> str:
    if kp >= 6:
        return KOLOR_KP_SILNA_BURZA
    if kp >= 5:
        return KOLOR_KP_BURZA
    if kp >= 4:
        return KOLOR_KP_AKTYWNIE
    return KOLOR_KP_SPOKOJNIE


def formatuj_wiadomosc(tekst: str) -> str:
    """Zwija pojedyncze zlamania linii z biuletynow NOAA (ktore i tak lamia tekst
    co kilka slow) w spacje, ale zachowuje przerwy miedzy akapitami (puste linie)."""
    tekst = tekst.strip()
    tekst = re.sub(r"\n\s*\n+", "\n\n", tekst)
    return re.sub(r"(?<!\n)\n(?!\n)", " ", tekst)


def pobierz_lokalizacje(nazwa: str) -> list:
    response = requests.get(
        GEOCODING_URL, params={"name": nazwa, "count": 10, "language": "pl", "format": "json"}, timeout=10
    )
    response.raise_for_status()
    return response.json().get("results", [])


class AuroraApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Monitor zorzy polarnej - NOAA SWPC")
        self.geometry("1450x900")
        self.minsize(1250, 800)

        self._numer_zapytania = 0
        self._lokalizacje = []
        self._lat = 52.23
        self._lon = 21.01
        self._nazwa_lokalizacji = "52.23°, 21.01°"

        self._buduj_ui()
        self._odswiez()

    def _buduj_ui(self):
        lewy = ttk.Frame(self, padding=10)
        lewy.pack(side="left", fill="y")

        ttk.Label(lewy, text="Miejscowość:").pack(anchor="w")
        self.wpis_miasta = tk.StringVar()
        pole_miasta = ttk.Entry(lewy, textvariable=self.wpis_miasta, width=28)
        pole_miasta.pack(fill="x", pady=(0, 5))
        pole_miasta.bind("<Return>", lambda e: self._szukaj_lokalizacji())

        ttk.Button(lewy, text="Szukaj miasta", command=self._szukaj_lokalizacji).pack(fill="x")

        ramka_listy = ttk.Frame(lewy)
        ramka_listy.pack(fill="x", pady=(5, 10))

        pasek = ttk.Scrollbar(ramka_listy, orient="vertical")
        self.lista = tk.Listbox(ramka_listy, yscrollcommand=pasek.set, width=32, height=5)
        pasek.config(command=self.lista.yview)
        pasek.pack(side="right", fill="y")
        self.lista.pack(side="left", fill="x", expand=True)
        self.lista.bind("<<ListboxSelect>>", self._wybrano_z_listy)

        ttk.Separator(lewy, orient="horizontal").pack(fill="x", pady=(0, 10))

        ttk.Label(lewy, text="lub współrzędne ręcznie:").pack(anchor="w")
        ramka_wspolrzedne = ttk.Frame(lewy)
        ramka_wspolrzedne.pack(fill="x", pady=(5, 5))

        ttk.Label(ramka_wspolrzedne, text="Szer.:").grid(row=0, column=0, sticky="w")
        self.wpis_lat = tk.StringVar(value=str(self._lat))
        ttk.Entry(ramka_wspolrzedne, textvariable=self.wpis_lat, width=10).grid(row=0, column=1, padx=(5, 10))

        ttk.Label(ramka_wspolrzedne, text="Dług.:").grid(row=0, column=2, sticky="w")
        self.wpis_lon = tk.StringVar(value=str(self._lon))
        ttk.Entry(ramka_wspolrzedne, textvariable=self.wpis_lon, width=10).grid(row=0, column=3, padx=(5, 0))

        ttk.Button(lewy, text="Sprawdź współrzędne", command=self._sprawdz_wspolrzedne).pack(fill="x")

        ttk.Separator(lewy, orient="horizontal").pack(fill="x", pady=10)

        ttk.Button(lewy, text="Odśwież dane", command=self._odswiez).pack(fill="x")

        self.status = tk.StringVar(value="Wczytywanie...")
        ttk.Label(lewy, textvariable=self.status, wraplength=220).pack(anchor="w", pady=(10, 0))

        prawy = ttk.Frame(self, padding=10)
        prawy.pack(side="left", fill="both", expand=True)

        kolumna_glowna = ttk.Frame(prawy)
        kolumna_glowna.pack(side="left", fill="both", expand=True)

        self.etykieta_naglowek = ttk.Label(kolumna_glowna, font=("Segoe UI", 16, "bold"))
        self.etykieta_naglowek.pack(anchor="w")

        self.etykieta_czas = ttk.Label(kolumna_glowna, font=("Segoe UI", 9), foreground=KOLOR_OPISOW)
        self.etykieta_czas.pack(anchor="w", pady=(0, 10))

        ttk.Label(
            kolumna_glowna, text="Prawdopodobieństwo zorzy w Twojej lokalizacji:", font=("Segoe UI", 11, "bold")
        ).pack(anchor="w")
        self.etykieta_prawdopodobienstwo = ttk.Label(kolumna_glowna, font=("Segoe UI", 20, "bold"))
        self.etykieta_prawdopodobienstwo.pack(anchor="w")

        self.figura_wskaznik = Figure(figsize=(6.3, 0.7), dpi=90)
        self.figura_wskaznik.patch.set_facecolor(KOLOR_TLA_WYKRESU)
        self.wykres_wskaznik = FigureCanvasTkAgg(self.figura_wskaznik, master=kolumna_glowna)
        self.wykres_wskaznik.get_tk_widget().pack(anchor="w", pady=(5, 15))

        ttk.Label(
            kolumna_glowna, text="Indeks Kp (obserwowany + prognoza NOAA):", font=("Segoe UI", 11, "bold")
        ).pack(anchor="w")

        self.figura_kp = Figure(figsize=(6.3, 2.6), dpi=90)
        self.figura_kp.patch.set_facecolor(KOLOR_TLA_WYKRESU)
        self.wykres_kp = FigureCanvasTkAgg(self.figura_kp, master=kolumna_glowna)
        self.wykres_kp.get_tk_widget().pack(anchor="w", pady=(5, 15))

        ttk.Label(
            kolumna_glowna, text="Alerty zorzowe / geomagnetyczne:", font=("Segoe UI", 11, "bold")
        ).pack(anchor="w")
        self.tekst_alerty = ScrolledText(
            kolumna_glowna, wrap="word", height=14, width=68, font=("Segoe UI", 9),
            padx=8, pady=8, borderwidth=1, relief="solid",
        )
        self.tekst_alerty.pack(anchor="w", pady=(5, 0))
        self.tekst_alerty.tag_configure("naglowek", font=("Segoe UI", 9, "bold"))
        self.tekst_alerty.configure(state="disabled")

        kolumna_boczna = ttk.Frame(prawy, padding=(20, 0, 0, 0))
        kolumna_boczna.pack(side="left", fill="y", anchor="n")

        ttk.Label(
            kolumna_boczna, text="Bz (pole międzyplanetarne, nT):", font=("Segoe UI", 11, "bold")
        ).pack(anchor="w")

        self.figura_bz = Figure(figsize=(4.2, 1.8), dpi=90)
        self.figura_bz.patch.set_facecolor(KOLOR_TLA_WYKRESU)
        self.wykres_bz = FigureCanvasTkAgg(self.figura_bz, master=kolumna_boczna)
        self.wykres_bz.get_tk_widget().pack(anchor="w", pady=(5, 0))

        ttk.Label(
            kolumna_boczna,
            text="Kolor linii: czerwony = południowy (sprzyja zorzy), niebieski = północny — im intensywniej, tym silniejszy Bz",
            font=("Segoe UI", 8),
            foreground=KOLOR_OPISOW,
            wraplength=380,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        self.etykieta_wiatr = ttk.Label(kolumna_boczna, justify="left", font=("Consolas", 9))
        self.etykieta_wiatr.pack(anchor="w", pady=(0, 10))

        ttk.Label(
            kolumna_boczna, text="Prędkość wiatru słonecznego (km/s):", font=("Segoe UI", 11, "bold")
        ).pack(anchor="w")

        self.figura_wiatr = Figure(figsize=(4.2, 1.8), dpi=90)
        self.figura_wiatr.patch.set_facecolor(KOLOR_TLA_WYKRESU)
        self.wykres_wiatr = FigureCanvasTkAgg(self.figura_wiatr, master=kolumna_boczna)
        self.wykres_wiatr.get_tk_widget().pack(anchor="w", pady=(5, 15))

        ttk.Label(
            kolumna_boczna, text="Top komórki siatki z najwyższą auroą (świat):", font=("Segoe UI", 11, "bold")
        ).pack(anchor="w")

        self.figura_top = Figure(figsize=(4.2, 2.2), dpi=90)
        self.figura_top.patch.set_facecolor(KOLOR_TLA_WYKRESU)
        self.wykres_top = FigureCanvasTkAgg(self.figura_top, master=kolumna_boczna)
        self.wykres_top.get_tk_widget().pack(anchor="w", pady=(5, 15))

    def _szukaj_lokalizacji(self):
        nazwa = self.wpis_miasta.get().strip()
        if not nazwa:
            return
        self.status.set(f"Szukam: {nazwa}...")
        self.lista.delete(0, "end")
        watek = threading.Thread(target=self._pobierz_lokalizacje_watek, args=(nazwa,), daemon=True)
        watek.start()

    def _pobierz_lokalizacje_watek(self, nazwa: str):
        try:
            lokalizacje = pobierz_lokalizacje(nazwa)
        except requests.exceptions.RequestException as e:
            self.after(0, self._blad, str(e))
            return
        self.after(0, self._pokaz_lokalizacje, lokalizacje)

    def _pokaz_lokalizacje(self, lokalizacje: list):
        self._lokalizacje = lokalizacje
        if not lokalizacje:
            self.status.set("Nie znaleziono takiej miejscowości.")
            return
        for miejsce in lokalizacje:
            region = miejsce.get("admin1", "")
            opis = (
                f"{miejsce['name']}, {region}, {miejsce.get('country', '')}"
                if region
                else f"{miejsce['name']}, {miejsce.get('country', '')}"
            )
            self.lista.insert("end", opis)
        self.status.set(f"Znaleziono {len(lokalizacje)} lokalizacji.")

    def _wybrano_z_listy(self, event):
        zaznaczenie = self.lista.curselection()
        if not zaznaczenie:
            return
        miejsce = self._lokalizacje[zaznaczenie[0]]
        self._lat = miejsce["latitude"]
        self._lon = miejsce["longitude"]
        region = miejsce.get("admin1", "")
        podtytul = f"{region}, {miejsce.get('country', '')}" if region else miejsce.get("country", "")
        self._nazwa_lokalizacji = f"{miejsce['name']} ({podtytul})"
        self.wpis_lat.set(str(round(self._lat, 2)))
        self.wpis_lon.set(str(round(self._lon, 2)))
        self._odswiez()

    def _sprawdz_wspolrzedne(self):
        try:
            self._lat = float(self.wpis_lat.get().replace(",", "."))
            self._lon = float(self.wpis_lon.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Błędne dane", "Szerokość i długość muszą być liczbami.")
            return
        self._nazwa_lokalizacji = f"{self._lat:.2f}°, {self._lon:.2f}°"
        self._odswiez()

    def _odswiez(self):
        self._numer_zapytania += 1
        moj_numer = self._numer_zapytania
        self.status.set("Pobieranie danych z NOAA SWPC...")
        watek = threading.Thread(
            target=self._pobierz_dane_watek, args=(self._lat, self._lon, moj_numer), daemon=True
        )
        watek.start()

    def _pobierz_dane_watek(self, lat: float, lon: float, moj_numer: int):
        try:
            payload = aurora.fetch_json(aurora.OVATION_URL)
            probability, nearest_lat, nearest_lon = aurora.get_probability_for_location(payload, lat, lon)
            top_cells = aurora.top_probability_cells(payload, limit=8)
            czas_obserwacji = payload.get("Observation Time", "brak") if isinstance(payload, dict) else "brak"
            czas_prognozy = payload.get("Forecast Time", "brak") if isinstance(payload, dict) else "brak"
        except Exception as e:
            self.after(0, self._blad, str(e))
            return

        try:
            alerty = aurora.parse_alerts(aurora.fetch_json(aurora.ALERTS_URL))
        except Exception:
            alerty = []

        try:
            dane_kp = aurora.parse_kp_index(aurora.fetch_json(aurora.KP_URL))
        except Exception:
            dane_kp = []

        try:
            dane_bz = aurora.parse_solar_wind_mag(aurora.fetch_json(aurora.MAG_URL))
        except Exception:
            dane_bz = []

        try:
            dane_wiatr = aurora.parse_solar_wind_plasma(aurora.fetch_json(aurora.WIND_URL))
        except Exception:
            dane_wiatr = []

        self.after(
            0,
            self._aktualizuj,
            moj_numer,
            probability,
            nearest_lat,
            nearest_lon,
            top_cells,
            czas_obserwacji,
            czas_prognozy,
            alerty,
            dane_kp,
            dane_bz,
            dane_wiatr,
        )

    def _blad(self, komunikat: str):
        self.status.set("Błąd połączenia.")
        messagebox.showerror("Błąd połączenia", komunikat)

    def _aktualizuj(
        self,
        moj_numer: int,
        probability: float,
        nearest_lat: float,
        nearest_lon: float,
        top_cells: list,
        czas_obserwacji: str,
        czas_prognozy: str,
        alerty: list,
        dane_kp: list,
        dane_bz: list,
        dane_wiatr: list,
    ):
        if moj_numer != self._numer_zapytania:
            return  # przyszła odpowiedź na nieaktualne zapytanie - ignorujemy

        self.etykieta_naglowek.configure(text=self._nazwa_lokalizacji)
        self.etykieta_czas.configure(
            text=f"Obserwacja: {czas_obserwacji}    Prognoza: {czas_prognozy}    "
            f"Najbliższy punkt siatki: {nearest_lat:.2f}°, {nearest_lon:.2f}°"
        )

        etykieta = aurora.probability_label(probability)
        self.etykieta_prawdopodobienstwo.configure(text=f"{probability:.1f}%  —  {etykieta}")

        self._rysuj_wskaznik(probability)
        self._rysuj_kp(dane_kp)
        self._rysuj_top(top_cells)
        self._rysuj_bz(dane_bz)
        self._aktualizuj_tekst_wiatru(dane_bz, dane_wiatr)
        self._rysuj_wiatr(dane_wiatr)

        self._pokaz_alerty(alerty)

        self.status.set("Gotowe.")

    def _pokaz_alerty(self, alerty: list):
        self.tekst_alerty.configure(state="normal")
        self.tekst_alerty.delete("1.0", "end")

        if not alerty:
            self.tekst_alerty.insert("end", "Brak aktualnych alertów zorzowych lub geomagnetycznych.")
        else:
            for i, alert in enumerate(alerty):
                if i > 0:
                    self.tekst_alerty.insert("end", "\n" + "─" * 60 + "\n\n")
                issue = aurora.isoformat_utc(alert.get("issue_time"))
                self.tekst_alerty.insert("end", f"{alert['event']} | {issue}\n", "naglowek")
                self.tekst_alerty.insert("end", formatuj_wiadomosc(alert["message"]))

        self.tekst_alerty.configure(state="disabled")

    def _rysuj_wskaznik(self, probability: float):
        self.figura_wskaznik.clear()
        ax = self.figura_wskaznik.add_subplot(111)
        ax.set_facecolor(KOLOR_TLA_WYKRESU)

        ax.barh([""], [100], color=KOLOR_TOR, height=0.6)
        ax.barh([""], [probability], color=KOLOR_SLUPKA, height=0.6)

        ax.set_xlim(0, 100)
        ax.set_yticks([])
        ax.tick_params(axis="x", colors=KOLOR_OPISOW, labelsize=8)
        for spina in ("top", "right", "left"):
            ax.spines[spina].set_visible(False)
        ax.spines["bottom"].set_color(KOLOR_OSI)

        self.figura_wskaznik.tight_layout()
        self.wykres_wskaznik.draw()

    def _rysuj_kp(self, dane_kp: list):
        self.figura_kp.clear()
        ax = self.figura_kp.add_subplot(111)
        ax.set_facecolor(KOLOR_TLA_WYKRESU)

        if not dane_kp:
            ax.text(0.5, 0.5, "Brak danych", ha="center", va="center", color=KOLOR_OPISOW)
            ax.axis("off")
            self.figura_kp.tight_layout()
            self.wykres_kp.draw()
            return

        # ostatnie ~4 dni obserwacji (3h/wpis) + cala dostepna prognoza
        obserwowane = [d for d in dane_kp if d["observed"]][-32:]
        prognoza = [d for d in dane_kp if not d["observed"]]
        wpisy = obserwowane + prognoza

        x = list(range(len(wpisy)))
        wartosci = [d["kp"] for d in wpisy]
        kolory = [kolor_kp(d["kp"]) for d in wpisy]
        przezroczystosc = [1.0 if d["observed"] else 0.45 for d in wpisy]

        for xi, wartosc, kolor, alfa in zip(x, wartosci, kolory, przezroczystosc):
            ax.bar(xi, wartosc, width=0.85, color=kolor, alpha=alfa)

        granica = len(obserwowane) - 0.5
        if prognoza:
            ax.axvline(granica, color=KOLOR_OSI, linestyle="--", linewidth=1)
            ax.text(
                granica, 9.3, " prognoza →", fontsize=8, color=KOLOR_OPISOW, va="bottom", ha="left"
            )

        krok = max(1, len(wpisy) // 10)
        ax.set_xticks(x[::krok])
        ax.set_xticklabels(
            [wpisy[i]["time"].strftime("%d.%m\n%Hh") for i in x[::krok]], fontsize=7
        )

        ax.set_ylim(0, 9.3)
        ax.set_yticks([0, 3, 4, 5, 6, 7, 8, 9])
        ax.tick_params(axis="both", colors=KOLOR_OPISOW, labelsize=8)
        ax.grid(axis="y", color=KOLOR_SIATKI, linewidth=0.8)
        ax.set_axisbelow(True)
        for spina in ("top", "right"):
            ax.spines[spina].set_visible(False)
        ax.spines["left"].set_color(KOLOR_OSI)
        ax.spines["bottom"].set_color(KOLOR_OSI)

        self.figura_kp.tight_layout()
        self.wykres_kp.draw()

    def _rysuj_bz(self, dane_bz: list):
        self.figura_bz.clear()
        ax = self.figura_bz.add_subplot(111)
        ax.set_facecolor(KOLOR_TLA_WYKRESU)

        if not dane_bz:
            ax.text(0.5, 0.5, "Brak danych", ha="center", va="center", color=KOLOR_OPISOW)
            ax.axis("off")
            self.figura_bz.tight_layout()
            self.wykres_bz.draw()
            return

        wpisy = dane_bz[-360:]  # ostatnie ~6h przy probkowaniu co 1 min
        czasy = [w["time"] for w in wpisy]
        bz = [w["bz"] for w in wpisy]

        x_num = mdates.date2num(czasy)
        zakres = max(5.0, max(abs(v) for v in bz))  # min. +-5 nT, zeby przy spokojnym Bz kolory nie "krzyczaly"
        norm = Normalize(vmin=-zakres, vmax=zakres)

        ax.axhline(0, color=KOLOR_OSI, linewidth=1)

        punkty = np.array([x_num, bz]).T.reshape(-1, 1, 2)
        segmenty = np.concatenate([punkty[:-1], punkty[1:]], axis=1)
        # kolor segmentu = wartosc Bz na jego poczatku; dodatnie (polnoc) -> niebieski,
        # ujemne (poludnie, sprzyja zorzy) -> czerwony, tym intensywniej im wieksza wartosc bezwzgledna
        lc = LineCollection(segmenty, cmap=MAPA_KOLOROW_BZ, norm=norm)
        lc.set_array(np.array(bz[:-1]))
        lc.set_linewidth(1.8)
        ax.add_collection(lc)

        ax.set_xlim(x_num.min(), x_num.max())
        zapas = max(1.0, zakres * 0.15)
        ax.set_ylim(min(bz) - zapas, max(bz) + zapas)

        krok = max(1, len(wpisy) // 5)
        ax.set_xticks(x_num[::krok])
        ax.set_xticklabels([c.strftime("%H:%M") for c in czasy[::krok]], fontsize=7)

        ax.tick_params(axis="both", colors=KOLOR_OPISOW, labelsize=8)
        ax.grid(axis="y", color=KOLOR_SIATKI, linewidth=0.8)
        ax.set_axisbelow(True)
        for spina in ("top", "right"):
            ax.spines[spina].set_visible(False)
        ax.spines["left"].set_color(KOLOR_OSI)
        ax.spines["bottom"].set_color(KOLOR_OSI)

        self.figura_bz.tight_layout()
        self.wykres_bz.draw()

    def _aktualizuj_tekst_wiatru(self, dane_bz: list, dane_wiatr: list):
        if not dane_bz and not dane_wiatr:
            self.etykieta_wiatr.configure(text="Brak danych o wietrze słonecznym.")
            return

        czesci = []
        if dane_bz:
            ostatni_bz = dane_bz[-1]
            czesci.append(f"Bz: {ostatni_bz['bz']:+.1f} nT")
            czesci.append(f"Bt: {ostatni_bz['bt']:.1f} nT")
        if dane_wiatr:
            ostatni_wiatr = dane_wiatr[-1]
            czesci.append(f"Prędkość: {ostatni_wiatr['predkosc']:.0f} km/s")
            czesci.append(f"Gęstość: {ostatni_wiatr['gestosc']:.1f} /cm³")
        self.etykieta_wiatr.configure(text="Teraz — " + "   ".join(czesci))

    def _rysuj_wiatr(self, dane_wiatr: list):
        self.figura_wiatr.clear()
        ax = self.figura_wiatr.add_subplot(111)
        ax.set_facecolor(KOLOR_TLA_WYKRESU)

        if not dane_wiatr:
            ax.text(0.5, 0.5, "Brak danych", ha="center", va="center", color=KOLOR_OPISOW)
            ax.axis("off")
            self.figura_wiatr.tight_layout()
            self.wykres_wiatr.draw()
            return

        wpisy = dane_wiatr[-360:]  # ostatnie ~6h przy probkowaniu co 1 min
        czasy = [w["time"] for w in wpisy]
        predkosc = [w["predkosc"] for w in wpisy]

        ax.plot(czasy, predkosc, color=KOLOR_SLUPKA, linewidth=1.5)

        krok = max(1, len(wpisy) // 5)
        ax.set_xticks(czasy[::krok])
        ax.set_xticklabels([c.strftime("%H:%M") for c in czasy[::krok]], fontsize=7)

        ax.tick_params(axis="both", colors=KOLOR_OPISOW, labelsize=8)
        ax.grid(axis="y", color=KOLOR_SIATKI, linewidth=0.8)
        ax.set_axisbelow(True)
        for spina in ("top", "right"):
            ax.spines[spina].set_visible(False)
        ax.spines["left"].set_color(KOLOR_OSI)
        ax.spines["bottom"].set_color(KOLOR_OSI)

        self.figura_wiatr.tight_layout()
        self.wykres_wiatr.draw()

    def _rysuj_top(self, top_cells: list):
        self.figura_top.clear()
        ax = self.figura_top.add_subplot(111)
        ax.set_facecolor(KOLOR_TLA_WYKRESU)

        # odwracamy, zeby najwyzsza wartosc byla na gorze wykresu
        cells = list(reversed(top_cells))
        etykiety = [f"{lat:.0f}°, {lon:.0f}°" for _, lat, lon in cells]
        wartosci = [wartosc for wartosc, _, _ in cells]

        if not wartosci:
            ax.text(0.5, 0.5, "Brak danych", ha="center", va="center", color=KOLOR_OPISOW)
            ax.axis("off")
            self.figura_top.tight_layout()
            self.wykres_top.draw()
            return

        slupki = ax.barh(etykiety, wartosci, height=0.6, color=KOLOR_SLUPKA)
        for slupek, wartosc in zip(slupki, wartosci):
            ax.text(
                slupek.get_width() + max(wartosci) * 0.02,
                slupek.get_y() + slupek.get_height() / 2,
                f"{wartosc:.0f}%",
                va="center",
                ha="left",
                fontsize=9,
                color=KOLOR_TEKSTU,
            )

        ax.set_xlim(0, max(wartosci) * 1.15)
        ax.tick_params(axis="y", colors=KOLOR_TEKSTU, labelsize=9, length=0)
        ax.tick_params(axis="x", colors=KOLOR_OPISOW, labelsize=8)
        ax.grid(axis="x", color=KOLOR_SIATKI, linewidth=0.8)
        ax.set_axisbelow(True)
        for spina in ("top", "right", "left"):
            ax.spines[spina].set_visible(False)
        ax.spines["bottom"].set_color(KOLOR_OSI)

        self.figura_top.tight_layout()
        self.wykres_top.draw()


if __name__ == "__main__":
    app = AuroraApp()
    app.mainloop()
