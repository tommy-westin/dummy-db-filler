-- Exempelschema (personal: anställda, frånvaro och lönetransaktioner) för att prova dummyfiller utan databasanslutning.
-- Läs in filen under "1. Källa" -> "DDL-skript".

CREATE TABLE [dbo].[Organisationsenhet](
    [EnhetID] [int] IDENTITY(1,1) NOT NULL,
    [Enhetsnamn] [nvarchar](80) NOT NULL,
    [Forvaltning] [nvarchar](60) NOT NULL,
    [Ort] [nvarchar](60) NULL,
 CONSTRAINT [PK_Organisationsenhet] PRIMARY KEY CLUSTERED ([EnhetID] ASC)
)
GO

CREATE TABLE [dbo].[Anstalld](
    [AnstalldID] [int] IDENTITY(1,1) NOT NULL,
    [Anstallningsnummer] [varchar](10) NOT NULL,
    [Personnummer] [char](13) NOT NULL,
    [Fornamn] [nvarchar](50) NOT NULL,
    [Efternamn] [nvarchar](50) NOT NULL,
    [Epost] [nvarchar](120) NULL,
    [Befattning] [nvarchar](60) NOT NULL,
    [Yrkeskategori] [nvarchar](60) NOT NULL,
    [Anstallningsform] [nvarchar](20) NOT NULL,
    [Sysselsattningsgrad] [tinyint] NOT NULL CHECK ([Sysselsattningsgrad] >= 1 AND [Sysselsattningsgrad] <= 100),
    [Manadslon] [decimal](10, 0) NOT NULL,
    [EnhetID] [int] NOT NULL,
    [ChefID] [int] NULL,
    [AnstalldFran] [date] NOT NULL,
    [AnstalldTill] [date] NULL,
 CONSTRAINT [PK_Anstalld] PRIMARY KEY CLUSTERED ([AnstalldID] ASC),
 CONSTRAINT [UQ_Anstalld_Nr] UNIQUE ([Anstallningsnummer]),
 CONSTRAINT [UQ_Anstalld_Pnr] UNIQUE ([Personnummer])
)
GO

CREATE TABLE [dbo].[Franvaro](
    [FranvaroID] [bigint] IDENTITY(1,1) NOT NULL,
    [AnstalldID] [int] NOT NULL,
    [Franvaroorsak] [nvarchar](30) NOT NULL,
    [FranDatum] [date] NOT NULL,
    [TillDatum] [date] NOT NULL,
    [Omfattning] [tinyint] NOT NULL,
    [Godkand] [bit] NOT NULL DEFAULT ((1)),
 CONSTRAINT [PK_Franvaro] PRIMARY KEY CLUSTERED ([FranvaroID] ASC)
)
GO

CREATE TABLE [dbo].[Lonetransaktion](
    [LonetransaktionID] [bigint] IDENTITY(1,1) NOT NULL,
    [AnstalldID] [int] NOT NULL,
    [Period] [int] NOT NULL,
    [Loneart] [nvarchar](40) NOT NULL,
    [Belopp] [decimal](10, 2) NOT NULL,
    [Utbetalningsdatum] [date] NOT NULL,
 CONSTRAINT [PK_Lonetransaktion] PRIMARY KEY CLUSTERED ([LonetransaktionID] ASC)
)
GO

ALTER TABLE [dbo].[Anstalld] ADD CONSTRAINT [FK_Anstalld_Enhet] FOREIGN KEY([EnhetID]) REFERENCES [dbo].[Organisationsenhet] ([EnhetID])
GO
ALTER TABLE [dbo].[Anstalld] ADD CONSTRAINT [FK_Anstalld_Chef] FOREIGN KEY([ChefID]) REFERENCES [dbo].[Anstalld] ([AnstalldID])
GO
ALTER TABLE [dbo].[Franvaro] ADD CONSTRAINT [FK_Franvaro_Anstalld] FOREIGN KEY([AnstalldID]) REFERENCES [dbo].[Anstalld] ([AnstalldID])
GO
ALTER TABLE [dbo].[Lonetransaktion] ADD CONSTRAINT [FK_Lonetransaktion_Anstalld] FOREIGN KEY([AnstalldID]) REFERENCES [dbo].[Anstalld] ([AnstalldID])
GO
