-- Exempelschema (ekonomi: kodplan, leverantörsfakturor och budget) för att prova dummyfiller utan databasanslutning.
-- Läs in filen under "1. Källa" -> "DDL-skript".

CREATE TABLE [dbo].[Konto](
    [Kontonr] [varchar](4) NOT NULL,
    [Kontonamn] [nvarchar](80) NOT NULL,
    [Kontoklass] [nvarchar](40) NOT NULL,
 CONSTRAINT [PK_Konto] PRIMARY KEY CLUSTERED ([Kontonr] ASC)
)
GO

CREATE TABLE [dbo].[Ansvar](
    [Ansvar] [varchar](5) NOT NULL,
    [Benamning] [nvarchar](80) NOT NULL,
    [Forvaltning] [nvarchar](60) NOT NULL,
 CONSTRAINT [PK_Ansvar] PRIMARY KEY CLUSTERED ([Ansvar] ASC)
)
GO

CREATE TABLE [dbo].[Verksamhet](
    [Verksamhetskod] [varchar](3) NOT NULL,
    [Benamning] [nvarchar](60) NOT NULL,
 CONSTRAINT [PK_Verksamhet] PRIMARY KEY CLUSTERED ([Verksamhetskod] ASC)
)
GO

CREATE TABLE [dbo].[Leverantor](
    [LeverantorID] [int] IDENTITY(1,1) NOT NULL,
    [Leverantorsnummer] [varchar](12) NOT NULL,
    [Leverantorsnamn] [nvarchar](100) NOT NULL,
    [Organisationsnummer] [char](11) NOT NULL,
    [Bankgiro] [varchar](9) NULL,
    [Leverantorstyp] [nvarchar](30) NOT NULL,
    [Gatuadress] [nvarchar](100) NULL,
    [Postnummer] [char](6) NULL,
    [Ort] [nvarchar](60) NULL,
    [Epost] [nvarchar](120) NULL,
    [Sparrad] [bit] NOT NULL DEFAULT ((0)),
    [Registrerad] [date] NOT NULL,
 CONSTRAINT [PK_Leverantor] PRIMARY KEY CLUSTERED ([LeverantorID] ASC),
 CONSTRAINT [UQ_Leverantor_Nr] UNIQUE ([Leverantorsnummer])
)
GO

CREATE TABLE [dbo].[Leverantorsfaktura](
    [FakturaID] [bigint] IDENTITY(1,1) NOT NULL,
    [LeverantorID] [int] NOT NULL,
    [Fakturanummer] [varchar](20) NOT NULL,
    [OCR] [varchar](16) NULL,
    [Fakturadatum] [date] NOT NULL,
    [Forfallodatum] [date] NOT NULL,
    [Betalningsdatum] [date] NULL,
    [BeloppExklMoms] [decimal](12, 2) NOT NULL,
    [Moms] [decimal](12, 2) NOT NULL,
    [Fakturabelopp] [decimal](12, 2) NOT NULL,
    [Valuta] [char](3) NOT NULL DEFAULT ('SEK'),
    [Betalvillkor] [nvarchar](30) NULL,
    [Status] [nvarchar](20) NOT NULL,
    [Attestant] [nvarchar](80) NULL,
 CONSTRAINT [PK_Leverantorsfaktura] PRIMARY KEY CLUSTERED ([FakturaID] ASC),
 CONSTRAINT [CK_Faktura_Belopp] CHECK ([BeloppExklMoms] >= 0)
)
GO

CREATE TABLE [dbo].[Fakturarad](
    [FakturaradID] [bigint] IDENTITY(1,1) NOT NULL,
    [FakturaID] [bigint] NOT NULL,
    [Radnr] [int] NOT NULL,
    [Kontonr] [varchar](4) NOT NULL,
    [Ansvar] [varchar](5) NOT NULL,
    [Verksamhetskod] [varchar](3) NOT NULL,
    [Belopp] [decimal](12, 2) NOT NULL,
    [Bokforingsdatum] [date] NOT NULL,
    [Period] [int] NOT NULL,
    [Radtext] [nvarchar](200) NULL,
 CONSTRAINT [PK_Fakturarad] PRIMARY KEY CLUSTERED ([FakturaradID] ASC)
)
GO

CREATE TABLE [dbo].[Budget](
    [BudgetID] [int] IDENTITY(1,1) NOT NULL,
    [Ar] [smallint] NOT NULL,
    [Period] [int] NOT NULL,
    [Kontonr] [varchar](4) NOT NULL,
    [Ansvar] [varchar](5) NOT NULL,
    [Verksamhetskod] [varchar](3) NOT NULL,
    [Budgetversion] [nvarchar](30) NOT NULL,
    [Budgetbelopp] [decimal](14, 2) NOT NULL,
    [Utfall] [decimal](14, 2) NULL,
    [Avvikelse] [decimal](14, 2) NULL,
 CONSTRAINT [PK_Budget] PRIMARY KEY CLUSTERED ([BudgetID] ASC)
)
GO

ALTER TABLE [dbo].[Leverantorsfaktura] ADD CONSTRAINT [FK_Faktura_Leverantor] FOREIGN KEY([LeverantorID]) REFERENCES [dbo].[Leverantor] ([LeverantorID])
GO
ALTER TABLE [dbo].[Fakturarad] ADD CONSTRAINT [FK_Fakturarad_Faktura] FOREIGN KEY([FakturaID]) REFERENCES [dbo].[Leverantorsfaktura] ([FakturaID])
GO
ALTER TABLE [dbo].[Fakturarad] ADD CONSTRAINT [FK_Fakturarad_Konto] FOREIGN KEY([Kontonr]) REFERENCES [dbo].[Konto] ([Kontonr])
GO
ALTER TABLE [dbo].[Fakturarad] ADD CONSTRAINT [FK_Fakturarad_Ansvar] FOREIGN KEY([Ansvar]) REFERENCES [dbo].[Ansvar] ([Ansvar])
GO
ALTER TABLE [dbo].[Fakturarad] ADD CONSTRAINT [FK_Fakturarad_Verksamhet] FOREIGN KEY([Verksamhetskod]) REFERENCES [dbo].[Verksamhet] ([Verksamhetskod])
GO
ALTER TABLE [dbo].[Budget] ADD CONSTRAINT [FK_Budget_Konto] FOREIGN KEY([Kontonr]) REFERENCES [dbo].[Konto] ([Kontonr])
GO
ALTER TABLE [dbo].[Budget] ADD CONSTRAINT [FK_Budget_Ansvar] FOREIGN KEY([Ansvar]) REFERENCES [dbo].[Ansvar] ([Ansvar])
GO
ALTER TABLE [dbo].[Budget] ADD CONSTRAINT [FK_Budget_Verksamhet] FOREIGN KEY([Verksamhetskod]) REFERENCES [dbo].[Verksamhet] ([Verksamhetskod])
GO
