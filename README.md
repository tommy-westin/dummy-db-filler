# Dummyfiller

Skapar verklighetstrogen dummy-data utifrån databasscheman, för utvecklare som ska bygga datamodeller,
integrationer och data warehouse utan tillgång till produktionsdata. Allt körs lokalt i Python och
ingen data hämtas från internet.

## Kom igång

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"   # första gången
.\.venv\Scripts\python.exe -m dummyfiller               # startar gränssnittet på http://localhost:8501
```

Vill du prova direkt: gå till **1. Källa → DDL-skript**, välj ett exempelschema (vård, ekonomi, personal eller
tandvård) och klicka på **Läs in exempelschema**. Exemplen kan läsas in tillsammans.

Verktyget är anpassat för Region Jämtland Härjedalen: personer och enheter hamnar främst på orter i länet,
vårdenheter heter hälsocentraler och Östersunds sjukhus, och de inbyggda områdena är vård, ekonomi, personal
och tandvård.

## Arbetsgång

| Steg | Vad du gör |
|---|---|
| 1. Källa | Läs in schema från SQL Server (endast metadata), från DDL-skript, eller hoppa över och bygg själv. |
| 2. Diagram | Se och redigera allt i ett tabelldiagram: flytta tabeller, dra pilar mellan kolumner för att skapa relationer, godta föreslagna relationer och ändra tabeller och kolumner i sidopanelen. |
| 3. Tabeller och relationer | Kategorisera tabeller, ange antal rader eller barn per förälder, skapa egna tabeller, lägg till eller föreslå relationer, se relationsdiagrammet. |
| 4. Kolumner | Granska förslaget per kolumn, byt generator, finjustera parametrar och se en förhandsgranskning direkt. Ställ in historik (SCD2) och spara egna regler. |
| 5. Värdelistor | Läs in exempelfiler, hela kodverk, testpersonnummer och profil från produktion. |
| 6. Generatorer | Bygg egna generatorer (uppslagstabeller och förinställningar), ersätt de inbyggda listorna med regionens riktiga koder, hantera regler och dela biblioteket med teamet. |
| 7. Generera | Välj scenario, ny eller inkrementell körning och eventuell smutsig data. Granska datan och kvalitetsrapporten och skriv till databas, CSV, Parquet eller SQL-skript. |

Allt du gör sparas automatiskt i en lokal SQLite-databas, `data/dummyfiller.db` i repot, så att arbetet finns
kvar när sidan laddas om eller appen startas om. I sidopanelen byter du projekt, skapar nya eller kopierar ett
projekt att experimentera i. Under **Historik** kan du återställa tidigare versioner. En ny version sparas när du
har arbetat en stund, och det nuvarande innehållet sparas alltid som en version innan en återställning.

Databasen ignoreras av git eftersom den innehåller varje utvecklares eget arbete. För att dela ett projekt med
teamet eller versionshantera det: **Fil (YAML) → Exportera**. Lösenord sparas aldrig, varken i databasen eller i
filen. Databasen kan flyttas med miljövariabeln `DUMMYFILLER_DB`.

## Diagrammet

- **Klicka** på en tabellrubrik för att ändra namn, schema, kategori, antal rader och historik, lägga till kolumner
  eller ta bort tabellen. Klicka på en kolumn för att välja generator och inställningar, med förhandsgranskning
  under diagrammet. Generatorlistan går att söka i.
- **Dra från pricken** till höger om en kolumn till en kolumn i en annan tabell för att skapa en relation. Pilen
  pekar på föräldern; dras den från en nyckel vänds den automatiskt. Olika datatyper går inte att koppla ihop.
- **Klicka på en pil** för att ändra fördelning, barn per förälder och andel NULL, eller ta bort relationen.
- **Förslag på relationer** utifrån kolumnnamn visas som streckade pilar med ett plustecken. Klicka för att lägga till.
- Tabellerna placeras automatiskt (föräldrar till vänster). Flyttar du dem sparas placeringen i projektfilen.
  Ctrl + scrollhjul zoomar, scrollhjulet panorerar.
- Kolumner märkta ⚠ är gissningar som är värda att titta på.
- **⛶ Maximera** i diagrammets verktygsrad döljer sidomenyn och sidhuvudet och låter diagrammet fylla hela
  fönstret, med redigeringspanelen kvar till höger. Esc eller **✕ Avsluta** går tillbaka. Tryck F11 för helskärm.

Diagrammet är en liten HTML/JavaScript-komponent (`dummyfiller/diagram/index.html`) utan externa bibliotek.
Övrig logik är Python. En direktlänk som öppnar ett projekt i diagrammet:
`http://localhost:8501/?projekt=projekt/vard.yaml&steg=2`.

## Så blir datan verklighetstrogen

- **Automatisk tolkning.** Kolumn- och tabellnamn (svenska och engelska), datatyper och nycklar avgör vilken
  generator varje kolumn får. Kolumner där tolkningen är en gissning märks med ⚠ så att du vet var du bör titta.
- **Sammanhängande rader.** Förnamn, efternamn, kön, födelsedatum, personnummer och e-post hör ihop på raden.
  Detsamma gäller ort, postnummer, kommun och län, leverantör och organisationsnummer, konto och belopp,
  befattning och lön samt tandvårdsåtgärd, tand och pris.
- **Nycklar och relationer.** Primärnycklar och unika kolumner blir unika, främmande nycklar pekar alltid på
  rader som finns, och tabellerna laddas i beroendeordning. Självrelationer (chef → anställd), kopplingstabeller
  och cirkulära relationer hanteras. Fördelningen över föräldrar kan vara jämn, skev eller en-till-en.
- **Datumlogik.** Slutdatum hamnar efter startdatum, förfallodatum 30 dagar efter fakturadatum, och datumdimensioner fylls
  med en dag per rad där år, månad, vecka och veckodag härleds från datumet.
- **Tid mellan tabeller.** En fakturarad hamnar aldrig före sin faktura, ett provsvar hamnar inom sin vårdkontakt och
  en vårdkontakt aldrig före patientens födelsedatum. Händelser för samma förälder bildar ett förlopp i tidsordning.
- **CHECK-villkor och standardvärden** i schemat blir värdelistor och intervall automatiskt.
- **Reproducerbart.** Samma slumpfrö och samma inställningar ger samma data.

### Radantal och relationer

- **Barn per förälder.** Ange t.ex. 1–5 på en relation, så följer tabellens radantal av föräldern (fakturarader per
  faktura, diagnoser per vårdkontakt). Detaljtabeller får detta som utgångsvärde.
- **Scenarier.** `liten`, `mellan` och `stor` multiplicerar radantalen (inte kodtabeller och kalendrar). Egna
  scenarier läggs till under steg 7.
- **Styrda relationer.** När en kodkolumn pekar på en kodtabell väljs föräldern utifrån kolumnens generator, så
  att t.ex. diagnosen passar patienten.

### Data warehouse

- **Historik (SCD2).** Tabeller med giltig från/till får flera versioner per affärsnyckel med giltighetstider som
  inte överlappar, och en flagga för aktuell version. Känns igen automatiskt och ställs in under steg 4.
- **Inkrementella körningar.** Lägg nya rader ovanpå befintlig data: löpnummer fortsätter efter de befintliga,
  datum hamnar från och med valt datum, och nya rader pekar på föräldrar som redan finns i databasen.
- **Smutsig data.** Blanksteg, blandade versaler, tomma strängar, formatvariationer, dubbletter och föräldralösa
  nycklar i valda tabeller. Nyckelkolumner rörs inte, så datan går fortfarande att ladda.
- **Kvalitetsrapport.** Efter genereringen visas dubbletter i nycklar, föräldralösa rader per relation samt
  fyllnadsgrad, unika värden och vanligaste värden per kolumn.
- **Profil från produktion.** Ett SQL-skript som bara returnerar aggregat (radantal, andel NULL, min/max/medel,
  värdefördelning för kolumner med få unika värden). Identifierande kolumner ingår inte och sällsynta värden
  utelämnas. Resultatet läses in och ställer in vikter, intervall och radantal.
- **Egna regler.** "Kolumner som heter `*kod` ska alltid genereras så här" sparas en gång och gäller i alla
  projekt. Filen ligger i `~/.dummyfiller/regler.yaml` eller där `DUMMYFILLER_RULES` pekar.

### Sätt att styra datan själv

| Generator | Användning |
|---|---|
| Egna värden med vikt | `Aktiv \| 80`, `Inaktiv \| 20` – du bestämmer värden och fördelning. |
| Värdelista / exempelfil | Värden från en inläst fil: som de är, i ordning, eller som förlaga för nya värden med samma mönster. Kolumner från samma CSV-fil kan hållas ihop radvis. |
| Mönster | `FAK-{seq:06}`, `??-####`, `{Fornamn}.{Efternamn}@example.com` |
| Egna värden beroende på annan kolumn | `Vårdtillfälle: Slutenvård` / `Besök: Primärvård \| 60, Specialiserad öppenvård \| 40` – samband mellan kolumner. |
| Formel | `round(BeloppExklMoms * 0.25, 2)`, `Startdatum + days(30)`, `'Ja' if Belopp > 1000 else 'Nej'` |
| Datum relativt annan kolumn | T.ex. förfallodatum 30 dagar efter fakturadatum. |
| Datum efter eller inom förälderns datum | Fakturarad efter fakturadatum, provsvar inom vårdkontakten. |
| Datum i förlopp per förälder | Händelser för samma patient, anställd eller leverantör i tidsordning med rimliga avstånd. |
| Löpnummer per förälder | Radnummer 1, 2, 3 … som börjar om för varje faktura. |
| Del av datum | År, kvartal, månad, veckodag m.m. från en datumkolumn. |
| Kopiera värde från relaterad tabell | Denormaliserade kolumner, t.ex. leverantörsnamn på en faktura. |
| Tal | Intervall med jämn, normal eller skev fördelning. |
| Valfri Faker-metod | Allt som biblioteket Faker kan generera. |

### Egna generatorer och regionens egna koder (steg 6)

- **Uppslagstabell:** klistra in eller läs in en tabell, t.ex. regionens ansvarskoder med benämning och förvaltning.
  En kolumn som använder generatorn väljer ett fält; kolumner på samma rad hämtar från samma tabellrad, och en
  viktkolumn styr hur vanlig varje rad är. I kodtabeller delas raderna ut i ordning.
- **Förinställning:** en befintlig generator med sparade inställningar, t.ex. `JH: Fakturanummer` = mönstret
  `LF-{seq:06}`. Ändrar du förinställningen ändras alla kolumner som använder den.
- **Inbyggda listor:** kontoplan, ansvar, verksamheter, befattningar och löner, tandvårdsåtgärder, diagnoser,
  läkemedel, orter och de förvalda värdelistorna kan redigeras, ersättas från fil och återställas till originalet.
- **Regler:** "kolumner som heter `*ansvar*` ska använda JH: Ansvar" kan skapas direkt när en generator sparas.
- **Dela med teamet:** exportera biblioteket (generatorer, listor och regler) till en YAML-fil och läs in den hos
  kollegorna, eller använd den från kommandoraden med `--bibliotek`.

Biblioteket är gemensamt för alla projekt och sparas i den lokala databasen. Ett projekt som använder en egen
generator får en kopia av den, så att projektet fungerar även hos någon som saknar generatorn. Egna generatorer
syns i generatorlistan under **Egna**.

### Vård

Gruppen **Vård** innehåller diagnoser (ICD-10-SE), åtgärder (KVÅ), läkemedel (ATC, substans, styrka,
beredningsform), labbanalyser med enhet, referensintervall och avvikelseflagga, vårdenheter med klinik,
sjukhus, region och HSA-id, samt värdelistor för kontakttyp, besökstyp, vårdform, yrkeskategori, triage,
remisstatus med flera.

Sambanden är inbyggda: varje vårdkontakt får en huvudorsak som passar patientens ålder och kön, och diagnoser,
läkemedel och provsvar som hör till kontakten följer den (diabetes ger oftare metformin och förhöjt HbA1c).
Första diagnosen per kontakt är huvuddiagnos, vårdtiden beror på kontakttypen och en patients kontakter
ligger i tidsordning.

Kodlistorna är ett litet urval exempelkoder i rätt format, inte kompletta kodverk. Hela kodverk (t.ex.
Socialstyrelsens ICD-10-SE och KVÅ som Excel eller text) läses in under **5. Värdelistor → Kodverk**. De vanliga
koderna förblir vanliga och resten förekommer mer sällan. I tabeller med kategorin *Referens / kodtabell* delas
koderna ut i ordning, en per rad.

### Ekonomi, personal och tandvård

| Område | Innehåll |
|---|---|
| Ekonomi | Kontoplan (konto, benämning, kontoklass), ansvar/kostnadsställe med förvaltning, verksamhet, redovisningsperiod, belopp som är rimliga för kontot, OCR-nummer, fakturastatus, betalvillkor och budgetversion. Moms och fakturabelopp räknas fram, utfall hamnar nära budget, betalningsdatum finns bara på betalda fakturor och verksamheten följer ansvaret. |
| Personal | Befattning, yrkeskategori, månadslön som passar befattningen, anställningsform, sysselsättningsgrad, frånvaroorsak och löneart. Frånvaro per anställd ligger i tidsordning och varar dagar. |
| Tandvård | Åtgärdskod och text, pris, tandnummer, tandytor och diagnos som hör ihop (en fyllning på tre ytor får tre ytor på en tand av rätt slag), samt folktandvårdskliniker i länet. |

Kontoplanen, ansvarskoderna, befattningarna, lönenivåerna och tandvårdspriserna är exempel i rimligt format, inte
regionens riktiga kodplan eller gällande prislistor. De riktiga koderna läser ni in som värdelistor (CSV med kod
och benämning hålls ihop radvis), eller hämtar via profil från produktion.

**Testpersonnummer:** läs in Skatteverkets testpersonnummer som värdelista och välj den under
**5. Värdelistor → Testpersonnummer**. Då används bara de numren, och födelsedatum och kön följer numret.

## Kommandorad

```powershell
python -m dummyfiller                                              # gränssnittet
python -m dummyfiller generate projekt/vard.yaml --target csv --scenario liten
python -m dummyfiller generate projekt/vard.yaml --target db --empty-first
python -m dummyfiller generate projekt/vard.yaml --target db --append --since 2026-11-14 --fraction 5
python -m dummyfiller profile-sql projekt/vard.yaml --out profil.sql
python -m dummyfiller apply-profile projekt/vard.yaml resultat.csv --factor 0.01
python -m dummyfiller export-bibliotek teamets_bibliotek.yaml
python -m dummyfiller import-bibliotek teamets_bibliotek.yaml
python -m dummyfiller generate projekt/vard.yaml --target csv --bibliotek teamets_bibliotek.yaml
```

Anslutningen tas från projektfilen (eller `--url`). Lösenord för SQL-inloggning läses från miljövariabeln
`DUMMYFILLER_PASSWORD`. `--empty-first` raderar alla rader i projektets tabeller innan laddning.

## Bra att veta

- Personnummer, organisationsnummer och HSA-id är påhittade men korrekt uppbyggda (kontrollsiffra m.m.).
  Ett påhittat personnummer kan av en slump sammanfalla med ett verkligt; använd en lista med
  testpersonnummer om det inte får hända.
- Vid inkrementell körning läses befintliga rader (högst 50 000 per tabell) från databasen för att nya rader
  ska kunna peka på dem. Kör det därför bara mot databaser som innehåller dummy-data.
- Med historik (SCD2) anger tabellens radantal antalet unika affärsnycklar, inte antalet rader.
- E-postadresser använder som standard de reserverade domänerna `example.com/.org/.net`, så att testdata
  aldrig kan nå riktiga brevlådor. Domänerna går att ändra per kolumn.
- Laddning till databas sker i en enda transaktion. Går något fel rullas allt tillbaka.
- "Töm tabellerna först" kör `DELETE` på alla tabeller i projektet och kräver en extra bekräftelse.
- Egna tabeller kan skapas i databasen vid laddning. Egna kolumner i inlästa tabeller hoppas över om de
  inte finns i databasen, men följer med till filer.
- Vid cirkulära relationer utan NULL-bar kolumn måste FK-kontrollen stängas av vid laddning; appen varnar då.

## Kodstruktur

| Fil | Innehåll |
|---|---|
| `dummyfiller/model.py` | Projektmodell och YAML |
| `dummyfiller/ddl.py` | Tolk för `CREATE TABLE` / `ALTER TABLE` |
| `dummyfiller/dbio.py` | Anslutning, schemainläsning och laddning (SQLAlchemy + pyodbc) |
| `dummyfiller/inference.py` | Kategorier, generatorförslag och relationsförslag |
| `dummyfiller/generators.py`, `care.py`, `region.py`, `vocab.py` | Generatorer och inbyggda ordlistor (vård; ekonomi, personal, tandvård; orter) |
| `dummyfiller/engine.py` | Laddordning, nycklar, unika värden, typanpassning |
| `dummyfiller/export.py`, `valuelists.py` | Filexport och inläsning av exempelfiler |
| `dummyfiller/dirty.py`, `quality.py` | Smutsig data och kvalitetsrapport |
| `dummyfiller/prodprofile.py`, `rules.py` | Profil från produktion och egna regler |
| `dummyfiller/app.py`, `__main__.py` | Webbgränssnittet (Streamlit) och kommandoraden |
| `dummyfiller/store.py` | Automatisk sparning och versionshistorik i SQLite |
| `dummyfiller/library.py` | Generatorbiblioteket: egna generatorer, ändrade inbyggda listor, export och import |
| `dummyfiller/diagram/index.html`, `edit.py` | Tabelldiagrammet och redigering av struktur (byta namn, koppla, placera) |

En ny generator läggs till med dekoratorn `@register(...)` i `generators.py`; parameterlistan blir
automatiskt ett formulär i gränssnittet.

Tester: `.\.venv\Scripts\python.exe -m pytest`
