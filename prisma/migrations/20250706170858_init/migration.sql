-- CreateTable
CREATE TABLE "players" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "fullName" TEXT NOT NULL,
    "firstName" TEXT NOT NULL,
    "lastName" TEXT NOT NULL,
    "primaryNumber" TEXT,
    "birthDate" DATETIME,
    "currentAge" INTEGER,
    "birthCity" TEXT,
    "birthStateProvince" TEXT,
    "birthCountry" TEXT,
    "height" TEXT,
    "weight" INTEGER,
    "active" BOOLEAN NOT NULL DEFAULT true,
    "primaryPosition" TEXT,
    "useName" TEXT,
    "mlbDebutDate" DATETIME,
    "batSide" TEXT,
    "pitchHand" TEXT,
    "nameSlug" TEXT,
    "strikeZoneTop" REAL,
    "strikeZoneBottom" REAL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL
);

-- CreateTable
CREATE TABLE "player_stats" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "playerId" INTEGER NOT NULL,
    "season" TEXT NOT NULL,
    "gamesPlayed" INTEGER,
    "atBats" INTEGER,
    "runs" INTEGER,
    "hits" INTEGER,
    "doubles" INTEGER,
    "triples" INTEGER,
    "homeRuns" INTEGER,
    "rbi" INTEGER,
    "stolenBases" INTEGER,
    "caughtStealing" INTEGER,
    "baseOnBalls" INTEGER,
    "strikeOuts" INTEGER,
    "battingAverage" REAL,
    "onBasePercentage" REAL,
    "sluggingPercentage" REAL,
    "onBasePlusSlugging" REAL,
    "totalBases" INTEGER,
    "hitByPitch" INTEGER,
    "intentionalWalks" INTEGER,
    "groundIntoDoublePlay" INTEGER,
    "leftOnBase" INTEGER,
    "plateAppearances" INTEGER,
    "babip" REAL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" DATETIME NOT NULL,
    CONSTRAINT "player_stats_playerId_fkey" FOREIGN KEY ("playerId") REFERENCES "players" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "player_stats_playerId_season_key" ON "player_stats"("playerId", "season");
