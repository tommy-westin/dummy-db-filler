-- Exempelschema (vård) för att prova dummyfiller utan databasanslutning.
-- Läs in filen under "1. Källa" -> "DDL-skript".
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO

CREATE TABLE [dbo].[Vardenhet](
    [VardenhetID] [int] IDENTITY(1,1) NOT NULL,
    [HsaId] [varchar](30) NOT NULL,
    [Enhetsnamn] [nvarchar](120) NOT NULL,
    [Klinik] [nvarchar](80) NULL,
    [Sjukhus] [nvarchar](80) NULL,
    [Vardform] [nvarchar](40) NOT NULL,
    [Region] [nvarchar](60) NOT NULL,
    [Ort] [nvarchar](60) NULL,
 CONSTRAINT [PK_Vardenhet] PRIMARY KEY CLUSTERED ([VardenhetID] ASC)
    WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF) ON [PRIMARY],
 CONSTRAINT [UQ_Vardenhet_HsaId] UNIQUE NONCLUSTERED ([HsaId] ASC)
) ON [PRIMARY]
GO

CREATE TABLE [dbo].[Patient](
    [PatientID] [int] IDENTITY(1,1) NOT NULL,
    [Personnummer] [char](13) NOT NULL,
    [Fornamn] [nvarchar](50) NOT NULL,
    [Efternamn] [nvarchar](50) NOT NULL,
    [Kon] [char](1) NOT NULL,
    [Fodelsedatum] [date] NOT NULL,
    [Gatuadress] [nvarchar](100) NULL,
    [Postnummer] [char](6) NULL,
    [Ort] [nvarchar](60) NULL,
    [Lan] [nvarchar](60) NULL,
    [Telefon] [varchar](20) NULL,
    [Epost] [nvarchar](120) NULL,
    [SkyddadIdentitet] [bit] NOT NULL DEFAULT ((0)),
    [ListadVardenhetID] [int] NULL,
    [Skapad] [datetime2](0) NOT NULL DEFAULT (sysdatetime()),
    [RadVersion] [rowversion] NOT NULL,
 CONSTRAINT [PK_Patient] PRIMARY KEY CLUSTERED ([PatientID] ASC),
 CONSTRAINT [UQ_Patient_Pnr] UNIQUE ([Personnummer])
)
GO

CREATE TABLE [dbo].[Personal](
    [PersonalID] [int] NOT NULL PRIMARY KEY,
    [Fornamn] [nvarchar](50) NOT NULL,
    [Efternamn] [nvarchar](50) NOT NULL,
    [Yrkeskategori] [nvarchar](40) NOT NULL,
    [Epost] [nvarchar](120) NULL,
    [VardenhetID] [int] NOT NULL,
    [ChefID] [int] NULL,
    [AnstalldFran] [date] NOT NULL,
    [AnstalldTill] [date] NULL
)
GO

CREATE TABLE [dbo].[Diagnos](
    [DiagnosKod] [varchar](8) NOT NULL,
    [DiagnosText] [nvarchar](200) NOT NULL,
 CONSTRAINT [PK_Diagnos] PRIMARY KEY CLUSTERED ([DiagnosKod] ASC)
)
GO

CREATE TABLE [dbo].[Vardkontakt](
    [VardkontaktID] [bigint] IDENTITY(1,1) NOT NULL,
    [PatientID] [int] NOT NULL,
    [VardenhetID] [int] NOT NULL,
    [AnsvarigPersonalID] [int] NULL,
    [Kontakttyp] [nvarchar](30) NOT NULL,
    [Besokstyp] [nvarchar](30) NULL,
    [Triage] [nvarchar](10) NULL,
    [Inskrivningsdatum] [datetime2](0) NOT NULL,
    [Utskrivningsdatum] [datetime2](0) NULL,
    [Status] [nvarchar](20) NOT NULL,
    [Patientavgift] [decimal](10, 2) NULL,
    [Anteckning] [nvarchar](max) NULL,
 CONSTRAINT [PK_Vardkontakt] PRIMARY KEY CLUSTERED ([VardkontaktID] ASC)
)
GO

CREATE TABLE [dbo].[VardkontaktDiagnos](
    [VardkontaktID] [bigint] NOT NULL,
    [DiagnosKod] [varchar](8) NOT NULL,
    [Diagnostyp] [nvarchar](20) NOT NULL,
 CONSTRAINT [PK_VardkontaktDiagnos] PRIMARY KEY CLUSTERED ([VardkontaktID] ASC, [DiagnosKod] ASC)
)
GO

CREATE TABLE [dbo].[Lakemedelsordination](
    [OrdinationID] [bigint] IDENTITY(1,1) NOT NULL PRIMARY KEY,
    [VardkontaktID] [bigint] NOT NULL,
    [ATCKod] [varchar](7) NOT NULL,
    [Lakemedel] [nvarchar](80) NOT NULL,
    [Styrka] [nvarchar](30) NULL,
    [Beredningsform] [nvarchar](40) NULL,
    [Ordinationsdatum] [date] NOT NULL,
    [Utsattningsdatum] [date] NULL
)
GO

CREATE TABLE [dbo].[Labbsvar](
    [LabbsvarID] [bigint] IDENTITY(1,1) NOT NULL PRIMARY KEY,
    [PatientID] [int] NOT NULL,
    [VardkontaktID] [bigint] NULL,
    [Analysnamn] [nvarchar](60) NOT NULL,
    [Resultat] [decimal](10, 2) NOT NULL,
    [Enhet] [nvarchar](20) NOT NULL,
    [ReferensMin] [decimal](10, 2) NULL,
    [ReferensMax] [decimal](10, 2) NULL,
    [Avvikelseflagga] [char](1) NULL,
    [Provtagningsdatum] [datetime2](0) NOT NULL
)
GO

CREATE TABLE [dbo].[DimDatum](
    [DatumID] [int] NOT NULL PRIMARY KEY,
    [Datum] [date] NOT NULL,
    [Ar] [smallint] NOT NULL,
    [Kvartal] [tinyint] NOT NULL,
    [Manad] [tinyint] NOT NULL,
    [Manadsnamn] [nvarchar](20) NOT NULL,
    [Vecka] [tinyint] NOT NULL,
    [Veckodag] [tinyint] NOT NULL,
    [Veckodagsnamn] [nvarchar](20) NOT NULL,
    [ArHelg] [bit] NOT NULL
)
GO

ALTER TABLE [dbo].[Patient] WITH CHECK ADD CONSTRAINT [FK_Patient_Vardenhet] FOREIGN KEY([ListadVardenhetID])
REFERENCES [dbo].[Vardenhet] ([VardenhetID])
GO
ALTER TABLE [dbo].[Patient] CHECK CONSTRAINT [FK_Patient_Vardenhet]
GO
ALTER TABLE [dbo].[Personal] ADD CONSTRAINT [FK_Personal_Vardenhet] FOREIGN KEY([VardenhetID]) REFERENCES [dbo].[Vardenhet] ([VardenhetID])
GO
ALTER TABLE [dbo].[Personal] ADD CONSTRAINT [FK_Personal_Chef] FOREIGN KEY([ChefID]) REFERENCES [dbo].[Personal] ([PersonalID])
GO
ALTER TABLE [dbo].[Vardkontakt] ADD CONSTRAINT [FK_Vardkontakt_Patient] FOREIGN KEY([PatientID]) REFERENCES [dbo].[Patient] ([PatientID])
GO
ALTER TABLE [dbo].[Vardkontakt] ADD CONSTRAINT [FK_Vardkontakt_Vardenhet] FOREIGN KEY([VardenhetID]) REFERENCES [dbo].[Vardenhet] ([VardenhetID])
GO
ALTER TABLE [dbo].[Vardkontakt] ADD CONSTRAINT [FK_Vardkontakt_Personal] FOREIGN KEY([AnsvarigPersonalID]) REFERENCES [dbo].[Personal] ([PersonalID])
GO
ALTER TABLE [dbo].[VardkontaktDiagnos] ADD CONSTRAINT [FK_VKD_Vardkontakt] FOREIGN KEY([VardkontaktID]) REFERENCES [dbo].[Vardkontakt] ([VardkontaktID])
GO
ALTER TABLE [dbo].[VardkontaktDiagnos] ADD CONSTRAINT [FK_VKD_Diagnos] FOREIGN KEY([DiagnosKod]) REFERENCES [dbo].[Diagnos] ([DiagnosKod])
GO
ALTER TABLE [dbo].[Lakemedelsordination] ADD CONSTRAINT [FK_Ordination_Vardkontakt] FOREIGN KEY([VardkontaktID]) REFERENCES [dbo].[Vardkontakt] ([VardkontaktID])
GO
ALTER TABLE [dbo].[Labbsvar] ADD CONSTRAINT [FK_Labbsvar_Patient] FOREIGN KEY([PatientID]) REFERENCES [dbo].[Patient] ([PatientID])
GO
ALTER TABLE [dbo].[Labbsvar] ADD CONSTRAINT [FK_Labbsvar_Vardkontakt] FOREIGN KEY([VardkontaktID]) REFERENCES [dbo].[Vardkontakt] ([VardkontaktID])
GO
