using System;
using System.IO;
using Microsoft.Data.Sqlite;
using Dapper;
using CapsStream.Core.Models;

namespace CapsStream.Data;

public class CapsDb
{
    private readonly string _connectionString;
    private static readonly string s_dataDirectory;
    private static readonly string s_dbPath;

    static CapsDb()
    {
        DefaultTypeMap.MatchNamesWithUnderscores = true;

        s_dataDirectory = FindDataDirectory();
        s_dbPath = Path.Combine(s_dataDirectory, "capsstream.db");
        MediaItem.DataDirectory = s_dataDirectory;
    }

    public static string DataDirectory => s_dataDirectory;
    public static string DatabasePath => s_dbPath;

    public CapsDb(string dbPath)
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = dbPath,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Cache = SqliteCacheMode.Shared
        };
        _connectionString = builder.ToString();
    }

    public static CapsDb Default => new(s_dbPath);

    private static string FindDataDirectory()
    {
        // 1. Walk up from AppContext.BaseDirectory
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null)
        {
            var candidate = Path.Combine(dir.FullName, "data");
            if (Directory.Exists(candidate) && File.Exists(Path.Combine(candidate, "capsstream.db")))
            {
                return candidate;
            }
            dir = dir.Parent;
        }

        // 2. Check current working directory
        var cwdCandidate = Path.Combine(Directory.GetCurrentDirectory(), "data");
        if (Directory.Exists(cwdCandidate) && File.Exists(Path.Combine(cwdCandidate, "capsstream.db")))
        {
            return cwdCandidate;
        }

        // 3. Fallback to LocalAppData
        var appData = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "CapsStream"
        );
        Directory.CreateDirectory(appData);
        return appData;
    }

    public SqliteConnection CreateConnection()
    {
        var conn = new SqliteConnection(_connectionString);
        conn.Open();
        using var cmd = conn.CreateCommand();
        cmd.CommandText = "PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;";
        cmd.ExecuteNonQuery();
        return conn;
    }
}
