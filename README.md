# Dummyfiller

Skapar verklighetstrogen dummy-data utifrån databasscheman, för utvecklare som ska bygga datamodeller,
integrationer och data warehouse utan tillgång till produktionsdata. Allt körs lokalt i Python och
ingen data hämtas från internet.

## Kom igång

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"   # första gången
.\.venv\Scripts\python.exe -m dummyfiller               # startar gränssnittet på http://localhost:8501
```

Vill du prova direkt: gå till **1. Källa → DDL-skript** och klicka på **Läs in exempelschema (vård)**.

## Arbetsgång

| Steg | Vad du gör |
|---|---|
| 1. Källa | Läs in schema från SQL Server (endast metadata), från DDL-skript, eller hoppa över och bygg själv. |
| 2. Tabeller och relationer | Kategorisera tabeller, ange antal rader, skapa egna tabeller, lägg till eller föreslå relationer. |
| 3. Kolumner | Granska förslaget per kolumn, byt generator, finjustera parametrar och se en förhandsgranskning direkt. |
| 4. Värdelistor | Läs in text- eller CSV-filer med exempelvärden som styr datan. |
| 5. Generera | Skapa datan, granska den och skriv till databas, CSV, Parquet eller SQL-skript. |

Projektet (schema, kategorier, generatorer, värdelistor) sparas som en YAML-fil via sidopanelen och kan
versionshanteras och delas i teamet. Lösenord sparas aldrig.

## Så blir datan verklighetstrogen

- **Automatisk tolkning.** Kolumn- och tabellnamn (svenska och engelska), datatyper och nycklar avgör vilken
  generator varje kolumn får. Kolumner där tolkningen är en gissning märks med ⚠ så att du vet var du bör titta.
- **Sammanhängande rader.** Förnamn, efternamn, kön, födelsedatum, personnummer och e-post hör ihop på raden.
  Detsamma gäller ort, postnummer, kommun och län, produktnamn, kategori och pris, samt företag och organisationsnummer.
- **Nycklar och relationer.** Primärnycklar och unika kolumner blir unika, främmande nycklar pekar alltid på
  rader som finns, och tabellerna laddas i beroendeordning. Självrelationer (chef → anställd), kopplingstabeller
  och cirkulära relationer hanteras. Fördelningen över föräldrar kan vara jämn, skev eller en-till-en.
- **Datumlogik.** Slutdatum hamnar efter startdatum, leveransdatum efter orderdatum, och datumdimensioner fylls
  med en dag per rad där år, månad, vecka och veckodag härleds från datumet.
- **Reproducerbart.** Samma slumpfrö och samma inställningar ger samma data.

### Sätt att styra datan själv

| Generator | Användning |
|---|---|
| Egna värden med vikt | `Aktiv \| 80`, `Inaktiv \| 20` – du bestämmer värden och fördelning. |
| Värdelista / exempelfil | Värden från en inläst fil: som de är, i ordning, eller som förlaga för nya värden med samma mönster. Kolumner från samma CSV-fil kan hållas ihop radvis. |
| Mönster | `ORD-{seq:06}`, `??-####`, `{Fornamn}.{Efternamn}@example.com` |
| Formel | `round(Antal * Pris, 2)`, `Startdatum + days(30)`, `'Ja' if Belopp > 1000 else 'Nej'` |
| Datum relativt annan kolumn | T.ex. 1–14 dagar efter orderdatum. |
| Del av datum | År, kvartal, månad, veckodag m.m. från en datumkolumn. |
| Kopiera värde från relaterad tabell | Denormaliserade kolumner, t.ex. kundnamn på en order. |
| Tal | Intervall med jämn, normal eller skev fördelning. |
| Valfri Faker-metod | Allt som biblioteket Faker kan generera. |

### Vård

Gruppen **Vård** innehåller diagnoser (ICD-10-SE), åtgärder (KVÅ), läkemedel (ATC, substans, styrka,
beredningsform), labbanalyser med enhet, referensintervall och avvikelseflagga, vårdenheter med klinik,
sjukhus, region och HSA-id, samt värdelistor för kontakttyp, besökstyp, vårdform, yrkeskategori, triage,
remisstatus med flera.

Kodlistorna är ett litet urval exempelkoder i rätt format, inte kompletta kodverk. Behöver du fler koder
läser du in en egen fil under **4. Värdelistor**. I tabeller med kategorin *Referens / kodtabell* delas
koderna ut i ordning, en per rad.

## Bra att veta

- Personnummer, organisationsnummer och HSA-id är påhittade men korrekt uppbyggda (kontrollsiffra m.m.).
  Ett påhittat personnummer kan av en slump sammanfalla med ett verkligt.
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
| `dummyfiller/generators.py`, `care.py`, `vocab.py` | Generatorer och inbyggda ordlistor |
| `dummyfiller/engine.py` | Laddordning, nycklar, unika värden, typanpassning |
| `dummyfiller/export.py`, `valuelists.py` | Filexport och inläsning av exempelfiler |
| `dummyfiller/app.py` | Webbgränssnittet (Streamlit) |

En ny generator läggs till med dekoratorn `@register(...)` i `generators.py`; parameterlistan blir
automatiskt ett formulär i gränssnittet.

Tester: `.\.venv\Scripts\python.exe -m pytest`
