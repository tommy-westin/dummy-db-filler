"""Inbyggda ordlistor (svenska) som gör datan sammanhängande utan internetåtkomst.

Anpassade för Region Jämtland Härjedalen: de flesta personer och enheter hamnar på orter i länet.
Postnummerprefixen är ungefärliga – de ger rimliga, inte garanterat giltiga, postnummer.
"""

# (ort, kommun, län, postnummerprefix, vikt)
SWEDISH_CITIES = [
    ("Östersund", "Östersund", "Jämtlands län", ["831"], 44),
    ("Frösön", "Östersund", "Jämtlands län", ["832"], 12),
    ("Brunflo", "Östersund", "Jämtlands län", ["834"], 5),
    ("Lit", "Östersund", "Jämtlands län", ["836"], 2),
    ("Krokom", "Krokom", "Jämtlands län", ["835"], 6),
    ("Järpen", "Åre", "Jämtlands län", ["837"], 3),
    ("Åre", "Åre", "Jämtlands län", ["837"], 4),
    ("Strömsund", "Strömsund", "Jämtlands län", ["833"], 7),
    ("Svenstavik", "Berg", "Jämtlands län", ["845"], 4),
    ("Bräcke", "Bräcke", "Jämtlands län", ["843"], 3),
    ("Hammarstrand", "Ragunda", "Jämtlands län", ["844"], 3),
    ("Sveg", "Härjedalen", "Jämtlands län", ["842"], 5),
    ("Funäsdalen", "Härjedalen", "Jämtlands län", ["846"], 2),
    ("Hede", "Härjedalen", "Jämtlands län", ["846"], 1),
    # utomlänspatienter och personer som flyttat
    ("Sundsvall", "Sundsvall", "Västernorrlands län", ["852", "853", "854", "856"], 3),
    ("Örnsköldsvik", "Örnsköldsvik", "Västernorrlands län", ["891"], 1),
    ("Umeå", "Umeå", "Västerbottens län", ["901", "903", "904", "906", "907"], 2),
    ("Stockholm", "Stockholm", "Stockholms län", ["111", "112", "113", "114", "115", "116", "117", "118"], 4),
    ("Uppsala", "Uppsala", "Uppsala län", ["752", "753", "754", "756"], 1),
    ("Gävle", "Gävle", "Gävleborgs län", ["802", "803", "804", "806"], 1),
    ("Göteborg", "Göteborg", "Västra Götalands län", ["411", "412", "413", "414", "415", "416", "417", "418"], 1.5),
    ("Malmö", "Malmö", "Skåne län", ["211", "212", "213", "214", "215", "216", "217"], 0.5),
]

HOME_COUNTY = "Jämtlands län"
HOME_REGION = "Region Jämtland Härjedalen"
# orter i länet, för namn på hälsocentraler och tandvårdskliniker
HOME_TOWNS = [c[0] for c in SWEDISH_CITIES if c[2] == HOME_COUNTY]
OSTERSUND_UNITS = ["Lugnvik", "Odensala", "Torvalla", "Zätagränd"]

MONTHS_SV = ["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober", "november", "december"]
WEEKDAYS_SV = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# allmänna administrativa anteckningar (ekonomi, personal, ärenden)
NOTES = [
    "Fakturan attesterad av budgetansvarig.",
    "Avvaktar kompletterande underlag från leverantören.",
    "Kompletterande uppgifter inkom via e-post.",
    "Ärendet överlämnat till handläggare.",
    "Kontrollerad och godkänd.",
    "Fakturan bestridd, kreditfaktura begärd.",
    "Konteringen rättad efter intern granskning.",
    "Enligt gällande ramavtal.",
    "Återkoppling önskas inom en vecka.",
    "Manuellt registrerad av ekonomiservice.",
    "Avtalet förlängt med tolv månader.",
    "Betalningspåminnelse mottagen.",
    "Inga avvikelser noterade.",
    "Preliminär uppgift, bekräftas senare.",
    "Uppgiften importerad från tidigare system.",
    "Omfördelning av budget enligt beslut i ledningsgruppen.",
    "Periodiserad över året.",
    "Avser föregående månad.",
    "Vikariat med anledning av föräldraledighet.",
    "Ändrad sysselsättningsgrad från och med nästa månad.",
    "Beviljad tjänstledighet för studier.",
    "Läkarintyg inkommet.",
    "Löneöversyn genomförd.",
    "Schemaändring godkänd av enhetschef.",
]

WORDS = [
    "norr", "söder", "blå", "grön", "röd", "ljus", "mörk", "liten", "stor", "snabb", "trygg", "klar",
    "björk", "tall", "sten", "strand", "berg", "dal", "sjö", "skog", "äng", "bro", "hamn", "torg",
    "projekt", "plan", "rapport", "analys", "avtal", "paket", "tjänst", "modul", "enhet", "zon",
]

# Förvalda värdelistor för generatorn "Egna värden med vikt" – format "värde | vikt"
PRESETS = {
    "status": ["Aktiv | 75", "Inaktiv | 15", "Vilande | 5", "Avslutad | 5"],
    "case_status": ["Avslutad | 60", "Pågående | 22", "Ny | 10", "Makulerad | 8"],
    "payment": ["Faktura | 45", "Kort | 38", "Swish | 14", "Kontant | 3"],
    "priority": ["Låg | 30", "Medel | 50", "Hög | 17", "Akut | 3"],
    "department": ["Ekonomiavdelningen | 15", "HR-avdelningen | 15", "IT-avdelningen | 15", "Kommunikationsavdelningen | 8",
                   "Upphandlingsenheten | 8", "Fastighetsenheten | 12", "Kost och service | 15", "Regionstaben | 12"],
    "role": ["Användare | 80", "Administratör | 8", "Läsare | 12"],
    "language": ["sv | 88", "en | 6", "fi | 2", "sma | 1", "no | 2", "ar | 1"],
    "currency_code": ["SEK | 92", "EUR | 4", "NOK | 2", "USD | 1", "DKK | 1"],
    "currency": ["Svensk krona | 92", "Euro | 4", "Norsk krona | 2", "US-dollar | 1", "Dansk krona | 1"],
    "country": ["Sverige | 93", "Norge | 4", "Finland | 2", "Danmark | 1"],
    "country_code": ["SE | 93", "NO | 4", "FI | 2", "DK | 1"],
    "vat_rate": ["25 | 70", "12 | 8", "6 | 7", "0 | 15"],
    "category": ["Kategori A | 40", "Kategori B | 30", "Kategori C | 20", "Kategori D | 10"],
}
