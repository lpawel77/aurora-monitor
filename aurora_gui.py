import threading
import tkinter as tk
from tkinter import messagebox, ttk

import requests
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
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


def kolor_kp(kp: float) -> str:
    if kp >= 6:
        return KOLOR_KP_SILNA_BURZA
    if kp >= 5:
        return KOLOR_KP_BURZA
    if kp >= 4:
        return KOLOR_KP_AKTYWNIE
    return KOLOR_KP_SPOKOJNIE


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
        self.geometry("1100x980")
        self.minsize(950, 850)

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
        ramka_listy.pack(fill="both", expand=True, pady=(5, 10))

        pasek = ttk.Scrollbar(ramka_listy, orient="vertical")
        self.lista = tk.Listbox(ramka_listy, yscrollcommand=pasek.set, width=32, height=10)
        pasek.config(command=self.lista.yview)
        pasek.pack(side="right", fill="y")
        self.lista.pack(side="left", fill="both", expand=True)
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

        self.etykieta_naglowek = ttk.Label(prawy, font=("Segoe UI", 16, "bold"))
        self.etykieta_naglowek.pack(anchor="w")

        self.etykieta_czas = ttk.Label(prawy, font=("Segoe UI", 9), foreground=KOLOR_OPISOW)
        self.etykieta_czas.pack(anchor="w", pady=(0, 10))

        ttk.Label(prawy, text="Prawdopodobieństwo zorzy w Twojej lokalizacji:", font=("Segoe UI", 11, "bold")).pack(
            anchor="w"
        )
        self.etykieta_prawdopodobienstwo = ttk.Label(prawy, font=("Segoe UI", 20, "bold"))
        self.etykieta_prawdopodobienstwo.pack(anchor="w")

        self.figura_wskaznik = Figure(figsize=(7.5, 0.7), dpi=90)
        self.figura_wskaznik.patch.set_facecolor(KOLOR_TLA_WYKRESU)
        self.wykres_wskaznik = FigureCanvasTkAgg(self.figura_wskaznik, master=prawy)
        self.wykres_wskaznik.get_tk_widget().pack(anchor="w", pady=(5, 15))

        ttk.Label(
            prawy, text="Indeks Kp (obserwowany + prognoza NOAA):", font=("Segoe UI", 11, "bold")
        ).pack(anchor="w")

        self.figura_kp = Figure(figsize=(7.5, 2.6), dpi=90)
        self.figura_kp.patch.set_facecolor(KOLOR_TLA_WYKRESU)
        self.wykres_kp = FigureCanvasTkAgg(self.figura_kp, master=prawy)
        self.wykres_kp.get_tk_widget().pack(anchor="w", pady=(5, 15))

        ttk.Label(prawy, text="Top komórki siatki z najwyższą auroą (świat):", font=("Segoe UI", 11, "bold")).pack(
            anchor="w"
        )

        self.figura_top = Figure(figsize=(7.5, 2.6), dpi=90)
        self.figura_top.patch.set_facecolor(KOLOR_TLA_WYKRESU)
        self.wykres_top = FigureCanvasTkAgg(self.figura_top, master=prawy)
        self.wykres_top.get_tk_widget().pack(anchor="w", pady=(5, 15))

        ttk.Label(prawy, text="Alerty zorzowe / geomagnetyczne:", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.etykieta_alerty = ttk.Label(prawy, justify="left", wraplength=650)
        self.etykieta_alerty.pack(anchor="w", pady=(5, 0))

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

        if not alerty:
            self.etykieta_alerty.configure(text="Brak aktualnych alertów zorzowych lub geomagnetycznych.")
        else:
            linie = []
            for alert in alerty[:5]:
                issue = aurora.isoformat_utc(alert.get("issue_time"))
                wiadomosc = alert["message"][:200]
                if len(alert["message"]) > 200:
                    wiadomosc += "..."
                linie.append(f"{alert['event']} | {issue}\n{wiadomosc}")
            self.etykieta_alerty.configure(text="\n\n".join(linie))

        self.status.set("Gotowe.")

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
