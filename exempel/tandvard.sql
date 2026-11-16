-- Exempelschema (tandvård: kliniker, patienter, besök och behandlingar) för att prova dummyfiller utan databasanslutning.
-- Läs in filen under "1. Källa" -> "DDL-skript".

CREATE TABLE [dbo].[Tandvardsklinik](
    [KlinikID] [int] IDENTITY(1,1) NOT NULL,
    [Kliniknamn] [nvarchar](80) NOT NULL,
    [HsaId] [varchar](30) NOT NULL,
 CONSTRAINT [PK_Tandvardsklinik] PRIMARY KEY CLUSTERED ([KlinikID] ASC)
)
GO

CREATE TABLE [dbo].[TandvardsAtgard](
    [Atgardskod] [varchar](3) NOT NULL,
    [Atgardstext] [nvarchar](120) NOT NULL,
    [Referenspris] [decimal](10, 2) NOT NULL,
 CONSTRAINT [PK_TandvardsAtgard] PRIMARY KEY CLUSTERED ([Atgardskod] ASC)
)
GO

CREATE TABLE [dbo].[Tandvardspatient](
    [PatientID] [int] IDENTITY(1,1) NOT NULL,
    [Personnummer] [char](13) NOT NULL,
    [Fornamn] [nvarchar](50) NOT NULL,
    [Efternamn] [nvarchar](50) NOT NULL,
    [Fodelsedatum] [date] NOT NULL,
    [Postnummer] [char](6) NULL,
    [Ort] [nvarchar](60) NULL,
    [Patienttyp] [nvarchar](30) NOT NULL,
 CONSTRAINT [PK_Tandvardspatient] PRIMARY KEY CLUSTERED ([PatientID] ASC),
 CONSTRAINT [UQ_Tandvardspatient_Pnr] UNIQUE ([Personnummer])
)
GO

CREATE TABLE [dbo].[Tandvardsbesok](
    [BesokID] [bigint] IDENTITY(1,1) NOT NULL,
    [PatientID] [int] NOT NULL,
    [KlinikID] [int] NOT NULL,
    [Behandlare] [nvarchar](80) NOT NULL,
    [Besoksdatum] [datetime2](0) NOT NULL,
    [Status] [nvarchar](20) NOT NULL,
 CONSTRAINT [PK_Tandvardsbesok] PRIMARY KEY CLUSTERED ([BesokID] ASC)
)
GO

CREATE TABLE [dbo].[Tandbehandling](
    [BehandlingID] [bigint] IDENTITY(1,1) NOT NULL,
    [BesokID] [bigint] NOT NULL,
    [Atgardskod] [varchar](3) NOT NULL,
    [Tandnummer] [tinyint] NULL,
    [Tandyta] [varchar](5) NULL,
    [Diagnoskod] [varchar](8) NOT NULL,
    [Pris] [decimal](10, 2) NOT NULL,
 CONSTRAINT [PK_Tandbehandling] PRIMARY KEY CLUSTERED ([BehandlingID] ASC)
)
GO

ALTER TABLE [dbo].[Tandvardsbesok] ADD CONSTRAINT [FK_Tandvardsbesok_Patient] FOREIGN KEY([PatientID]) REFERENCES [dbo].[Tandvardspatient] ([PatientID])
GO
ALTER TABLE [dbo].[Tandvardsbesok] ADD CONSTRAINT [FK_Tandvardsbesok_Klinik] FOREIGN KEY([KlinikID]) REFERENCES [dbo].[Tandvardsklinik] ([KlinikID])
GO
ALTER TABLE [dbo].[Tandbehandling] ADD CONSTRAINT [FK_Tandbehandling_Besok] FOREIGN KEY([BesokID]) REFERENCES [dbo].[Tandvardsbesok] ([BesokID])
GO
ALTER TABLE [dbo].[Tandbehandling] ADD CONSTRAINT [FK_Tandbehandling_Atgard] FOREIGN KEY([Atgardskod]) REFERENCES [dbo].[TandvardsAtgard] ([Atgardskod])
GO
