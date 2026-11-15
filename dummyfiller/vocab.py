"""Inbyggda ordlistor (svenska) som gör datan sammanhängande utan internetåtkomst."""

# (ort, kommun, län, postnummerprefix, vikt ~ befolkning)
SWEDISH_CITIES = [
    ("Stockholm", "Stockholm", "Stockholms län", ["111", "112", "113", "114", "115", "116", "117", "118"], 98),
    ("Göteborg", "Göteborg", "Västra Götalands län", ["411", "412", "413", "414", "415", "416", "417", "418"], 60),
    ("Malmö", "Malmö", "Skåne län", ["211", "212", "213", "214", "215", "216", "217"], 36),
    ("Uppsala", "Uppsala", "Uppsala län", ["752", "753", "754", "756"], 24),
    ("Västerås", "Västerås", "Västmanlands län", ["721", "722", "723", "724"], 16),
    ("Örebro", "Örebro", "Örebro län", ["702", "703"], 16),
    ("Linköping", "Linköping", "Östergötlands län", ["581", "582", "583", "584", "587"], 17),
    ("Helsingborg", "Helsingborg", "Skåne län", ["251", "252", "253", "254", "256"], 15),
    ("Jönköping", "Jönköping", "Jönköpings län", ["551", "553", "554", "556"], 14),
    ("Norrköping", "Norrköping", "Östergötlands län", ["602", "603"], 14),
    ("Lund", "Lund", "Skåne län", ["221", "222", "223", "224", "226", "227"], 13),
    ("Umeå", "Umeå", "Västerbottens län", ["901", "903", "904", "906", "907"], 13),
    ("Gävle", "Gävle", "Gävleborgs län", ["802", "803", "804", "806"], 10),
    ("Borås", "Borås", "Västra Götalands län", ["503", "504", "506", "507"], 11),
    ("Södertälje", "Södertälje", "Stockholms län", ["151", "152"], 10),
    ("Eskilstuna", "Eskilstuna", "Södermanlands län", ["632", "633"], 11),
    ("Halmstad", "Halmstad", "Hallands län", ["302"], 10),
    ("Växjö", "Växjö", "Kronobergs län", ["351", "352"], 10),
    ("Karlstad", "Karlstad", "Värmlands län", ["652", "653", "654"], 10),
    ("Sundsvall", "Sundsvall", "Västernorrlands län", ["852", "853", "854", "856"], 10),
    ("Östersund", "Östersund", "Jämtlands län", ["831"], 6),
    ("Trollhättan", "Trollhättan", "Västra Götalands län", ["461"], 6),
    ("Luleå", "Luleå", "Norrbottens län", ["972", "973", "974"], 8),
    ("Kalmar", "Kalmar", "Kalmar län", ["392", "393"], 7),
    ("Falun", "Falun", "Dalarnas län", ["791"], 6),
    ("Skellefteå", "Skellefteå", "Västerbottens län", ["931"], 7),
    ("Karlskrona", "Karlskrona", "Blekinge län", ["371"], 7),
    ("Kristianstad", "Kristianstad", "Skåne län", ["291"], 9),
    ("Skövde", "Skövde", "Västra Götalands län", ["541"], 6),
    ("Uddevalla", "Uddevalla", "Västra Götalands län", ["451"], 6),
    ("Nyköping", "Nyköping", "Södermanlands län", ["611"], 6),
    ("Visby", "Gotland", "Gotlands län", ["621"], 6),
    ("Kiruna", "Kiruna", "Norrbottens län", ["981"], 2),
    ("Varberg", "Varberg", "Hallands län", ["432"], 7),
    ("Motala", "Motala", "Östergötlands län", ["591"], 4),
    ("Örnsköldsvik", "Örnsköldsvik", "Västernorrlands län", ["891"], 6),
    ("Borlänge", "Borlänge", "Dalarnas län", ["781", "784"], 5),
    ("Täby", "Täby", "Stockholms län", ["183", "187"], 7),
    ("Solna", "Solna", "Stockholms län", ["169", "171"], 8),
    ("Mölndal", "Mölndal", "Västra Götalands län", ["431"], 7),
]

BRANDS = ["Nordlys", "Fjällvik", "Björkå", "Tallbacka", "Skärgård", "Älvdal", "Solvik", "Granit", "Kustlinjen", "Midvinter"]
VARIANTS = ["", "", "", "Pro", "Mini", "Plus", "XL", "Classic", "Eco", "2.0"]

# kategori -> (produkter, (lägsta pris, högsta pris), enhet, vikt)
PRODUCT_CATEGORIES = {
    "Elektronik": (["Hörlurar", "Bluetooth-högtalare", "Laddare", "Powerbank", "Bildskärm", "Tangentbord", "Datormus", "Webbkamera", "Smartklocka", "Surfplatta", "Router", "USB-hubb"], (149, 12999), "st", 18),
    "Möbler": (["Skrivbord", "Kontorsstol", "Bokhylla", "Soffbord", "Fåtölj", "Sängram", "Byrå", "Matbord", "Pall", "Garderob"], (399, 14999), "st", 10),
    "Kläder": (["T-shirt", "Jeans", "Vinterjacka", "Stickad tröja", "Skjorta", "Regnjacka", "Mössa", "Vantar", "Sneakers", "Kängor"], (99, 2999), "st", 20),
    "Livsmedel": (["Kaffe", "Havregryn", "Knäckebröd", "Lingonsylt", "Olivolja", "Pasta", "Müsli", "Te", "Honung", "Choklad"], (15, 189), "st", 22),
    "Verktyg": (["Skruvdragare", "Hammare", "Borrmaskin", "Sticksåg", "Vattenpass", "Måttband", "Skiftnyckel", "Tång", "Verktygslåda"], (79, 3999), "st", 9),
    "Sport & fritid": (["Yogamatta", "Löparskor", "Ryggsäck", "Tält", "Sovsäck", "Cykelhjälm", "Vattenflaska", "Hantlar", "Skidstavar"], (99, 5999), "st", 11),
    "Kontorsmaterial": (["Kopieringspapper", "Pärm", "Kulspetspenna", "Anteckningsblock", "Häftapparat", "Whiteboardpenna", "Kuvert", "Etiketter"], (19, 499), "förp", 12),
    "Hem & trädgård": (["Golvlampa", "Kruka", "Trädgårdsslang", "Sekatör", "Grill", "Ljuslykta", "Gardin", "Matta", "Kudde"], (49, 6999), "st", 12),
    "Bygg": (["Regel 45x95", "Gipsskiva", "Träskruv", "Väggfärg", "Isolering", "Trall", "Fogmassa", "Spackel"], (39, 1299), "st", 8),
}

MONTHS_SV = ["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober", "november", "december"]
WEEKDAYS_SV = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

NOTES = [
    "Kunden önskar leverans före kl. 12.",
    "Ring innan leverans.",
    "Uppdaterad efter telefonsamtal med kund.",
    "Avvaktar svar från leverantören.",
    "Kompletterande uppgifter inkom via e-post.",
    "Ärendet överlämnat till handläggare.",
    "Kontrollerad och godkänd.",
    "Kunden har bytt kontaktperson.",
    "Leveransen försenad på grund av restnoterad artikel.",
    "Fakturan skickad på nytt efter adressändring.",
    "Rabatt enligt ramavtal.",
    "Portkod saknas, kontakta mottagaren.",
    "Återkoppling önskas inom en vecka.",
    "Manuellt registrerad av kundtjänst.",
    "Avtalet förlängt med tolv månader.",
    "Reklamation mottagen, ersättningsvara skickad.",
    "Betalningspåminnelse skickad.",
    "Inga avvikelser noterade.",
    "Preliminär uppgift, bekräftas senare.",
    "Godset lämnas vid lastkajen.",
    "Kunden föredrar kontakt via e-post.",
    "Uppgiften importerad från tidigare system.",
    "Delleverans, resterande skickas vecka 12.",
    "Ändrad efter intern granskning.",
]

WORDS = [
    "norr", "söder", "blå", "grön", "röd", "ljus", "mörk", "liten", "stor", "snabb", "trygg", "klar",
    "björk", "tall", "sten", "strand", "berg", "dal", "sjö", "skog", "äng", "bro", "hamn", "torg",
    "projekt", "plan", "rapport", "analys", "avtal", "paket", "tjänst", "modul", "enhet", "zon",
]

# Förvalda värdelistor för generatorn "Egna värden med vikt" – format "värde | vikt"
PRESETS = {
    "status": ["Aktiv | 75", "Inaktiv | 15", "Vilande | 5", "Avslutad | 5"],
    "order_status": ["Ny | 8", "Bekräftad | 12", "Plockad | 5", "Skickad | 15", "Levererad | 52", "Makulerad | 5", "Returnerad | 3"],
    "payment": ["Kort | 45", "Faktura | 25", "Swish | 20", "Autogiro | 7", "Kontant | 3"],
    "channel": ["Webb | 50", "Butik | 30", "Telefon | 10", "App | 10"],
    "priority": ["Låg | 30", "Medel | 50", "Hög | 17", "Akut | 3"],
    "department": ["Försäljning | 25", "Kundtjänst | 20", "IT | 12", "Ekonomi | 10", "Lager | 15", "Marknad | 8", "HR | 5", "Ledning | 5"],
    "customer_type": ["Privat | 70", "Företag | 25", "Offentlig sektor | 5"],
    "role": ["Användare | 80", "Administratör | 8", "Läsare | 12"],
    "language": ["sv | 85", "en | 10", "fi | 2", "no | 2", "da | 1"],
    "currency_code": ["SEK | 85", "EUR | 8", "USD | 3", "NOK | 2", "DKK | 1", "GBP | 1"],
    "currency": ["Svensk krona | 85", "Euro | 8", "US-dollar | 3", "Norsk krona | 2", "Dansk krona | 1", "Brittiskt pund | 1"],
    "country": ["Sverige | 88", "Norge | 4", "Danmark | 3", "Finland | 3", "Tyskland | 2"],
    "country_code": ["SE | 88", "NO | 4", "DK | 3", "FI | 3", "DE | 2"],
    "color": ["Svart | 25", "Vit | 20", "Grå | 15", "Blå | 14", "Röd | 9", "Grön | 8", "Beige | 5", "Gul | 4"],
    "size": ["XS | 6", "S | 20", "M | 34", "L | 26", "XL | 11", "XXL | 3"],
    "unit": ["st | 70", "kg | 8", "m | 6", "l | 6", "förp | 10"],
    "vat_rate": ["25 | 75", "12 | 17", "6 | 8"],
    "category": ["Kategori A | 40", "Kategori B | 30", "Kategori C | 20", "Kategori D | 10"],
    "product_category": [f"{name} | {v[3]}" for name, v in PRODUCT_CATEGORIES.items()],
    "brand": [f"{b} | 10" for b in BRANDS],
}
